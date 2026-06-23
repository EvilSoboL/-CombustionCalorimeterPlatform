from __future__ import annotations

import csv
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import GasData, OscilloscopeData, PlcData


_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL_COLUMN_RE = re.compile(r"([A-Z]+)")
_EXPERIMENT_TIME_RE = re.compile(
    r"^Experiment Time\s*:\s*(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})\s*$"
)
_CHANNEL_COUNT_RE = re.compile(r"^Number Of Channels\s*:\s*(\d+)\s*$", re.IGNORECASE)


def _column_index(reference: str) -> int:
    match = _CELL_COLUMN_RE.match(reference)
    if not match:
        raise ValueError(f"Некорректная ссылка ячейки XLSX: {reference}")
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - ord("A") + 1
    return result - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for item in root.findall(f"{_NS}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{_NS}t")))
    return values


def _first_sheet(archive: zipfile.ZipFile) -> tuple[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheet = workbook.find(f"{_NS}sheets/{_NS}sheet")
    if sheet is None:
        raise ValueError("В XLSX нет листов")
    relationship_id = sheet.attrib[f"{_REL_NS}id"]
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for relationship in relationships.findall(f"{_PACKAGE_REL_NS}Relationship"):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib["Target"].lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            return sheet.attrib.get("name", "Лист 1"), target
    raise ValueError("Не удалось найти данные первого листа XLSX")


def _cell_value(cell: ET.Element, shared: list[str]) -> str | float | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{_NS}t"))
    value_node = cell.find(f"{_NS}v")
    if value_node is None or value_node.text is None:
        return None
    raw = value_node.text
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError) as exc:
            raise ValueError("Некорректная таблица общих строк XLSX") from exc
    if cell_type in {"str", "e"}:
        return raw
    try:
        return float(raw)
    except ValueError:
        return raw


def _excel_datetime(value: object) -> datetime:
    if isinstance(value, (int, float)):
        # Analyzer exports are millisecond-resolution; rounding removes binary
        # floating-point artifacts such as 13:23:58.000002 at interval edges.
        milliseconds = round(float(value) * 86_400_000)
        return datetime(1899, 12, 30) + timedelta(milliseconds=milliseconds)
    text = str(value).strip()
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(f"Не удалось распознать дату и время XLSX: {text}")


def read_gas_xlsx(path: str | Path) -> GasData:
    """Read the first worksheet without requiring Excel or third-party packages."""
    source = Path(path)
    if source.suffix.lower() != ".xlsx":
        raise ValueError("Файл газоанализатора должен иметь расширение .xlsx")
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Не удалось открыть XLSX: {exc}") from exc

    with archive:
        shared = _shared_strings(archive)
        sheet_name, sheet_path = _first_sheet(archive)
        rows: list[dict[int, str | float | None]] = []
        try:
            stream = archive.open(sheet_path)
        except KeyError as exc:
            raise ValueError("В XLSX отсутствует XML первого листа") from exc
        with stream:
            for event, element in ET.iterparse(stream, events=("end",)):
                if element.tag != f"{_NS}row":
                    continue
                row: dict[int, str | float | None] = {}
                for cell in element.findall(f"{_NS}c"):
                    row[_column_index(cell.attrib.get("r", ""))] = _cell_value(cell, shared)
                rows.append(row)
                element.clear()

    if len(rows) < 2:
        raise ValueError("XLSX не содержит строк данных")
    max_column = max((max(row, default=-1) for row in rows), default=-1)
    headers = [str(rows[0].get(index, "")).strip() for index in range(max_column + 1)]
    if not headers or not headers[0]:
        raise ValueError("Первая колонка XLSX должна содержать дату и время")

    timestamps: list[datetime] = []
    raw_columns: dict[str, list[float | None]] = {
        header: [] for header in headers[1:] if header
    }
    for row_number, row in enumerate(rows[1:], start=2):
        first = row.get(0)
        if first in (None, ""):
            continue
        try:
            timestamp = _excel_datetime(first)
        except ValueError as exc:
            raise ValueError(f"Строка {row_number}: {exc}") from exc
        timestamps.append(timestamp)
        for index, header in enumerate(headers[1:], start=1):
            if not header:
                continue
            value = row.get(index)
            raw_columns[header].append(float(value) if isinstance(value, (int, float)) else None)

    if not timestamps:
        raise ValueError("В XLSX не найдено временных меток")
    numeric_columns = {
        name: values
        for name, values in raw_columns.items()
        if any(value is not None for value in values) and name.strip().lower() not in {"сек", "sec", "seconds"}
    }
    if not numeric_columns:
        raise ValueError("В XLSX не найдено числовых колонок измерений")
    order = sorted(range(len(timestamps)), key=timestamps.__getitem__)
    return GasData(
        timestamps=[timestamps[index] for index in order],
        columns={name: [values[index] for index in order] for name, values in numeric_columns.items()},
        sheet_name=sheet_name,
    )


def read_oscilloscope_txt(path: str | Path, expected_channels: int) -> OscilloscopeData:
    source = Path(path)
    if expected_channels <= 0:
        raise ValueError("Ожидаемое число каналов должно быть положительным")
    experiment_start: datetime | None = None
    declared_channels: int | None = None
    data_started = False
    elapsed: list[float] = []
    channels: list[list[float]] = [[] for _ in range(expected_channels)]

    try:
        with source.open("rb") as probe:
            sample = probe.read(8192)
        try:
            sample.decode("utf-8-sig")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            sample.decode("cp1251")
            encoding = "cp1251"
        handle = source.open("r", encoding=encoding)
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Не удалось открыть TXT {source.name}: {exc}") from exc
    with handle:
        for line in handle:
            if experiment_start is None:
                match = _EXPERIMENT_TIME_RE.match(line.strip())
                if match:
                    experiment_start = datetime.strptime(match.group(1), "%d-%m-%Y %H:%M:%S")
            if declared_channels is None:
                channel_match = _CHANNEL_COUNT_RE.match(line.strip())
                if channel_match:
                    declared_channels = int(channel_match.group(1))
            if not data_started:
                if line.strip() == "Data as Time Sequence:":
                    data_started = True
                continue
            parts = line.replace(",", ".").split()
            if len(parts) < expected_channels + 1:
                continue
            try:
                numbers = [float(part) for part in parts[: expected_channels + 1]]
            except ValueError:
                continue
            elapsed.append(numbers[0])
            for index in range(expected_channels):
                channels[index].append(numbers[index + 1])

    if experiment_start is None:
        raise ValueError(f"В {source.name} не найдена строка Experiment Time")
    if declared_channels is not None and declared_channels != expected_channels:
        raise ValueError(
            f"В {source.name} каналов: {declared_channels}, ожидалось: {expected_channels}"
        )
    if not elapsed:
        raise ValueError(f"В {source.name} не найдены числовые данные")
    if any(current <= previous for previous, current in zip(elapsed, elapsed[1:])):
        raise ValueError(f"Временная шкала {source.name} должна строго возрастать")
    timestamps = [experiment_start + timedelta(seconds=value) for value in elapsed]
    return OscilloscopeData(
        timestamps=timestamps,
        elapsed_seconds=elapsed,
        channels=channels,
        experiment_start=experiment_start,
        source_name=source.name,
    )


def _open_text_with_known_encoding(source: Path) -> tuple[str, str]:
    try:
        with source.open("rb") as probe:
            sample = probe.read(8192)
        try:
            sample.decode("utf-8-sig")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            sample.decode("cp1251")
            encoding = "cp1251"
        return source.read_text(encoding=encoding), encoding
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Не удалось открыть CSV {source.name}: {exc}") from exc


def _plc_timestamp(row: dict[str, str], row_number: int) -> datetime:
    created_at = row.get("created_at", "").strip().strip('"')
    candidates = []
    if created_at:
        candidates.append(created_at)
    event_date = row.get("event_date", "").strip()
    event_time = row.get("event_time", "").strip()
    if event_date and event_time:
        candidates.append(f"{event_date} {event_time}")
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M:%S.%f",
    )
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                pass
    raise ValueError(f"Строка CSV ПЛК {row_number}: не удалось распознать дату и время")


def _optional_float(value: str) -> float | None:
    text = value.strip().strip('"')
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def read_plc_csv(path: str | Path) -> PlcData:
    source = Path(path)
    if source.suffix.lower() != ".csv":
        raise ValueError("Файл ПЛК должен иметь расширение .csv")
    text, _encoding = _open_text_with_known_encoding(source)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,")
        reader = csv.DictReader(text.splitlines(), dialect=dialect)
    except csv.Error:
        reader = csv.DictReader(text.splitlines(), delimiter=";")
    if not reader.fieldnames:
        raise ValueError("CSV ПЛК не содержит заголовков")

    service_columns = {"id", "event_date", "event_time", "created_at"}
    data_columns = [
        name.strip()
        for name in reader.fieldnames
        if name and name.strip() and name.strip() not in service_columns
    ]
    if not data_columns:
        raise ValueError("CSV ПЛК не содержит колонок измерений")

    timestamps: list[datetime] = []
    raw_columns: dict[str, list[float | None]] = {name: [] for name in data_columns}
    for row_number, row in enumerate(reader, start=2):
        normalized = {(key or "").strip(): value or "" for key, value in row.items()}
        timestamps.append(_plc_timestamp(normalized, row_number))
        for name in data_columns:
            raw_columns[name].append(_optional_float(normalized.get(name, "")))

    if not timestamps:
        raise ValueError("CSV ПЛК не содержит строк данных")
    numeric_columns = {
        name: values for name, values in raw_columns.items() if any(value is not None for value in values)
    }
    if not numeric_columns:
        raise ValueError("CSV ПЛК не содержит числовых колонок измерений")

    order = sorted(range(len(timestamps)), key=timestamps.__getitem__)
    return PlcData(
        timestamps=[timestamps[index] for index in order],
        columns={name: [values[index] for index in order] for name, values in numeric_columns.items()},
        source_name=source.name,
    )
