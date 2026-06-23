from __future__ import annotations

import csv
import io
import math
import statistics
from dataclasses import dataclass
from pathlib import Path


OXYGEN_REFERENCE_PERCENT = 21.0
ENERGY_CORRECTION_FACTOR = 10.83 / 11.38
CO_CONVERSION_FACTOR = 1.25
NO_CONVERSION_FACTOR = 2.056


@dataclass(frozen=True)
class ExperimentAnalysis:
    experiment_name: str
    regime_count: int
    heat_kj_total: float
    heat_kwh_total: float
    o2_percent_mean: float
    co_ppm_mean: float
    no_ppm_mean: float
    no2_ppm_mean: float
    co_mg_kwh: float
    no_mg_kwh: float
    no2_mg_kwh: float


ANALYSIS_FIELDNAMES = [
    "Название эксперимента",
    "Режимов",
    "Суммарное количество тепла, кДж",
    "Суммарное количество тепла, кВт·ч",
    "O2, среднее, %",
    "CO, среднее, ppm",
    "NO, среднее, ppm",
    "NO2, среднее, ppm",
    "CO, мг/кВт·ч",
    "NO, мг/кВт·ч",
    "NO2, мг/кВт·ч",
]


@dataclass(frozen=True)
class _ResultColumns:
    experiment: str
    heat_kj: str
    o2_mean: str
    o2_count: str | None
    co_mean: str
    co_count: str | None
    no_mean: str
    no_count: str | None
    no2_mean: str
    no2_count: str | None


def _normalize_header(value: str) -> str:
    translation = str.maketrans({"С": "c", "с": "c", "О": "o", "о": "o"})
    return "".join(value.strip().casefold().translate(translation).split())


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            raise ValueError(f"Не удалось открыть CSV анализа: {exc}") from exc
    raise ValueError("Не удалось распознать кодировку CSV анализа")


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace("\xa0", "").replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def _header_map(fieldnames: list[str]) -> dict[str, str]:
    return {_normalize_header(name): name for name in fieldnames}


def _require_column(mapping: dict[str, str], candidates: tuple[str, ...], description: str) -> str:
    for candidate in candidates:
        found = mapping.get(_normalize_header(candidate))
        if found is not None:
            return found
    raise ValueError(f"В CSV результата нет колонки «{description}»")


def _optional_column(mapping: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        found = mapping.get(_normalize_header(candidate))
        if found is not None:
            return found
    return None


def _result_columns(fieldnames: list[str]) -> _ResultColumns:
    mapping = _header_map(fieldnames)
    return _ResultColumns(
        experiment=_require_column(mapping, ("Название эксперимента",), "Название эксперимента"),
        heat_kj=_require_column(mapping, ("Количество тепла, кДж",), "Количество тепла, кДж"),
        o2_mean=_require_column(mapping, ("% O2, среднее", "O2, среднее"), "% O2, среднее"),
        o2_count=_optional_column(mapping, ("% O2, N", "O2, N")),
        co_mean=_require_column(
            mapping,
            ("ппм CO, среднее", "ppm CO, среднее", "CO, среднее"),
            "ппм CO, среднее",
        ),
        co_count=_optional_column(mapping, ("ппм CO, N", "ppm CO, N", "CO, N")),
        no_mean=_require_column(
            mapping,
            ("ппм NO, среднее", "ppm NO, среднее", "NO, среднее"),
            "ппм NO, среднее",
        ),
        no_count=_optional_column(mapping, ("ппм NO, N", "ppm NO, N", "NO, N")),
        no2_mean=_require_column(
            mapping,
            ("ппм NO2, среднее", "ppm NO2, среднее", "NO2, среднее"),
            "ппм NO2, среднее",
        ),
        no2_count=_optional_column(mapping, ("ппм NO2, N", "ppm NO2, N", "NO2, N")),
    )


def _sum_column(rows: list[dict[str, str]], column: str, description: str) -> float:
    values = [_parse_float(row.get(column)) for row in rows]
    numbers = [value for value in values if value is not None]
    if not numbers:
        raise ValueError(f"В колонке «{description}» нет числовых значений")
    return sum(numbers)


def _mean_column(
    rows: list[dict[str, str]],
    value_column: str,
    count_column: str | None,
    description: str,
) -> float:
    values: list[float] = []
    weighted_values: list[tuple[float, float]] = []
    for row in rows:
        value = _parse_float(row.get(value_column))
        if value is None:
            continue
        values.append(value)
        weight = _parse_float(row.get(count_column)) if count_column is not None else None
        if weight is not None and weight > 0:
            weighted_values.append((value, weight))
    if not values:
        raise ValueError(f"В колонке «{description}» нет числовых значений")
    if count_column is not None and len(weighted_values) == len(values):
        total_weight = sum(weight for _, weight in weighted_values)
        return sum(value * weight for value, weight in weighted_values) / total_weight
    return statistics.fmean(values)


def emissions_mg_kwh(ppm: float, oxygen_percent: float, conversion_factor: float) -> float:
    denominator = OXYGEN_REFERENCE_PERCENT - oxygen_percent
    if denominator <= 0:
        raise ValueError("Для пересчета выбросов средний O2 должен быть меньше 21 %")
    return (
        conversion_factor
        * ppm
        * OXYGEN_REFERENCE_PERCENT
        / denominator
        * ENERGY_CORRECTION_FACTOR
    )


def analyze_result_rows(rows: list[dict[str, str]]) -> list[ExperimentAnalysis]:
    if not rows:
        raise ValueError("CSV результата не содержит строк данных")
    fieldnames = list(rows[0])
    columns = _result_columns(fieldnames)
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        experiment = row.get(columns.experiment, "").strip() or "Без названия"
        groups.setdefault(experiment, []).append(row)

    results: list[ExperimentAnalysis] = []
    for experiment, group_rows in groups.items():
        heat_kj = _sum_column(group_rows, columns.heat_kj, "Количество тепла, кДж")
        o2 = _mean_column(group_rows, columns.o2_mean, columns.o2_count, "% O2, среднее")
        co = _mean_column(group_rows, columns.co_mean, columns.co_count, "ппм CO, среднее")
        no = _mean_column(group_rows, columns.no_mean, columns.no_count, "ппм NO, среднее")
        no2 = _mean_column(group_rows, columns.no2_mean, columns.no2_count, "ппм NO2, среднее")
        try:
            co_mg_kwh = emissions_mg_kwh(co, o2, CO_CONVERSION_FACTOR)
            no_mg_kwh = emissions_mg_kwh(no, o2, NO_CONVERSION_FACTOR)
            no2_mg_kwh = emissions_mg_kwh(no2, o2, NO_CONVERSION_FACTOR)
        except ValueError as exc:
            raise ValueError(f"{experiment}: {exc}") from exc
        results.append(
            ExperimentAnalysis(
                experiment_name=experiment,
                regime_count=len(group_rows),
                heat_kj_total=heat_kj,
                heat_kwh_total=heat_kj / 3600.0,
                o2_percent_mean=o2,
                co_ppm_mean=co,
                no_ppm_mean=no,
                no2_ppm_mean=no2,
                co_mg_kwh=co_mg_kwh,
                no_mg_kwh=no_mg_kwh,
                no2_mg_kwh=no2_mg_kwh,
            )
        )
    return results


def read_result_csv(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    if source.suffix.lower() != ".csv":
        raise ValueError("Файл результата должен иметь расширение .csv")
    text = _read_text(source)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    except csv.Error:
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames:
        raise ValueError("CSV результата не содержит заголовков")
    return list(reader)


def analyze_result_csv(path: str | Path) -> list[ExperimentAnalysis]:
    return analyze_result_rows(read_result_csv(path))


def analysis_to_row(result: ExperimentAnalysis) -> dict[str, object]:
    return {
        "Название эксперимента": result.experiment_name,
        "Режимов": result.regime_count,
        "Суммарное количество тепла, кДж": result.heat_kj_total,
        "Суммарное количество тепла, кВт·ч": result.heat_kwh_total,
        "O2, среднее, %": result.o2_percent_mean,
        "CO, среднее, ppm": result.co_ppm_mean,
        "NO, среднее, ppm": result.no_ppm_mean,
        "NO2, среднее, ppm": result.no2_ppm_mean,
        "CO, мг/кВт·ч": result.co_mg_kwh,
        "NO, мг/кВт·ч": result.no_mg_kwh,
        "NO2, мг/кВт·ч": result.no2_mg_kwh,
    }


def export_analysis_csv(path: str | Path, results: list[ExperimentAnalysis]) -> None:
    if not results:
        raise ValueError("Нет результатов анализа для экспорта")
    try:
        handle = Path(path).open("w", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"Не удалось создать CSV анализа: {exc}") from exc
    with handle:
        writer = csv.DictWriter(handle, fieldnames=ANALYSIS_FIELDNAMES, delimiter=";")
        writer.writeheader()
        for result in results:
            writer.writerow(analysis_to_row(result))
