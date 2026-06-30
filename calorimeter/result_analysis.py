from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path

from .regime_names import parse_regime_name
from .steam_enthalpy import steam_generator_delta_enthalpy_kj_kg


OXYGEN_REFERENCE_PERCENT = 21.0
ENERGY_CORRECTION_FACTOR = 10.83 / 11.38
CO_CONVERSION_FACTOR = 1.25
NO_CONVERSION_FACTOR = 2.056


@dataclass(frozen=True)
class RegimeAnalysis:
    experiment_name: str
    regime_name: str
    start_time: str
    end_time: str
    duration_seconds: float
    heat_kj: float
    heat_kwh: float
    steam_flow_kg_h: float
    steam_mass_kg: float
    steam_delta_enthalpy_kj_kg: float
    steam_heat_kj: float
    fuel_flow_kg_h: float
    fuel_mass_kg: float
    fuel_heat_kj: float
    fuel_specific_heat_kj_kg: float
    fuel_specific_heat_mj_kg: float
    o2_percent: float
    co_ppm: float
    no_ppm: float
    no2_ppm: float
    co_mg_kwh: float
    no_mg_kwh: float
    no2_mg_kwh: float


ANALYSIS_FIELDNAMES = [
    "Название эксперимента",
    "Режим",
    "Начало режима",
    "Конец режима",
    "Длительность, с",
    "Количество тепла, кДж",
    "Количество тепла, кВт·ч",
    "Расход пара, кг/ч",
    "Масса пара, кг",
    "Δh пара, кДж/кг",
    "Тепло пара, кДж",
    "Расход топлива, кг/ч",
    "Масса топлива, кг",
    "Тепло от топлива, кДж",
    "Удельная теплота сгорания, кДж/кг",
    "Удельная теплота сгорания, МДж/кг",
    "O2, %",
    "CO, ppm",
    "NO, ppm",
    "NO2, ppm",
    "CO, мг/кВт·ч",
    "NO, мг/кВт·ч",
    "NO2, мг/кВт·ч",
]


@dataclass(frozen=True)
class _ResultColumns:
    experiment: str
    regime: str
    start: str | None
    end: str | None
    duration_seconds: str
    heat_kj: str
    o2_mean: str
    co_mean: str
    no_mean: str
    no2_mean: str


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
        regime=_require_column(mapping, ("Режим",), "Режим"),
        start=_optional_column(mapping, ("Начало режима",)),
        end=_optional_column(mapping, ("Конец режима",)),
        duration_seconds=_require_column(mapping, ("Длительность, с",), "Длительность, с"),
        heat_kj=_require_column(mapping, ("Количество тепла, кДж",), "Количество тепла, кДж"),
        o2_mean=_require_column(mapping, ("% O2, среднее", "O2, среднее"), "% O2, среднее"),
        co_mean=_require_column(
            mapping,
            ("ппм CO, среднее", "ppm CO, среднее", "CO, среднее"),
            "ппм CO, среднее",
        ),
        no_mean=_require_column(
            mapping,
            ("ппм NO, среднее", "ppm NO, среднее", "NO, среднее"),
            "ппм NO, среднее",
        ),
        no2_mean=_require_column(
            mapping,
            ("ппм NO2, среднее", "ppm NO2, среднее", "NO2, среднее"),
            "ппм NO2, среднее",
        ),
    )


def _required_float(row: dict[str, str], column: str, description: str, row_label: str) -> float:
    value = _parse_float(row.get(column))
    if value is None:
        raise ValueError(f"{row_label}: в колонке «{description}» нет числового значения")
    return value


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


def _flow_masses_from_regime(
    regime_name: str,
    duration_seconds: float,
    row_label: str,
) -> tuple[float, float, float, float]:
    parsed = parse_regime_name(regime_name)
    if parsed is None:
        raise ValueError(
            f"{row_label}: название режима должно иметь вид F1V0.8A7.5 или F1A0.8A7.5"
        )
    fuel_flow_kg_h, atomizer_code, atomizer_flow_kg_h, _air_flow_kg_h = parsed
    duration_h = duration_seconds / 3600.0
    steam_flow_kg_h = atomizer_flow_kg_h if atomizer_code == "V" else 0.0
    return (
        fuel_flow_kg_h,
        fuel_flow_kg_h * duration_h,
        steam_flow_kg_h,
        steam_flow_kg_h * duration_h,
    )


def analyze_result_rows(
    rows: list[dict[str, str]],
    steam_inlet_temperature_c: float,
    steam_outlet_temperature_c: float,
) -> list[RegimeAnalysis]:
    if not rows:
        raise ValueError("CSV результата не содержит строк данных")
    fieldnames = list(rows[0])
    columns = _result_columns(fieldnames)
    steam_delta_h = steam_generator_delta_enthalpy_kj_kg(
        steam_inlet_temperature_c,
        steam_outlet_temperature_c,
    )
    results: list[RegimeAnalysis] = []
    for row_number, row in enumerate(rows, start=2):
        experiment = row.get(columns.experiment, "").strip() or "Без названия"
        regime = row.get(columns.regime, "").strip() or "Без названия"
        row_label = f"{experiment}, режим {regime}, строка {row_number}"
        duration_seconds = _required_float(row, columns.duration_seconds, "Длительность, с", row_label)
        if duration_seconds <= 0:
            raise ValueError(f"{row_label}: длительность режима должна быть больше нуля")
        heat_kj = _required_float(row, columns.heat_kj, "Количество тепла, кДж", row_label)
        fuel_flow, fuel_mass, steam_flow, steam_mass = _flow_masses_from_regime(
            regime,
            duration_seconds,
            row_label,
        )
        steam_heat_kj = steam_delta_h * steam_mass
        fuel_heat_kj = heat_kj - steam_heat_kj
        fuel_specific_heat_kj_kg = fuel_heat_kj / fuel_mass
        o2 = _required_float(row, columns.o2_mean, "% O2, среднее", row_label)
        co = _required_float(row, columns.co_mean, "ппм CO, среднее", row_label)
        no = _required_float(row, columns.no_mean, "ппм NO, среднее", row_label)
        no2 = _required_float(row, columns.no2_mean, "ппм NO2, среднее", row_label)
        try:
            co_mg_kwh = emissions_mg_kwh(co, o2, CO_CONVERSION_FACTOR)
            no_mg_kwh = emissions_mg_kwh(no, o2, NO_CONVERSION_FACTOR)
            no2_mg_kwh = emissions_mg_kwh(no2, o2, NO_CONVERSION_FACTOR)
        except ValueError as exc:
            raise ValueError(f"{row_label}: {exc}") from exc
        results.append(
            RegimeAnalysis(
                experiment_name=experiment,
                regime_name=regime,
                start_time=row.get(columns.start, "").strip() if columns.start else "",
                end_time=row.get(columns.end, "").strip() if columns.end else "",
                duration_seconds=duration_seconds,
                heat_kj=heat_kj,
                heat_kwh=heat_kj / 3600.0,
                steam_flow_kg_h=steam_flow,
                steam_mass_kg=steam_mass,
                steam_delta_enthalpy_kj_kg=steam_delta_h,
                steam_heat_kj=steam_heat_kj,
                fuel_flow_kg_h=fuel_flow,
                fuel_mass_kg=fuel_mass,
                fuel_heat_kj=fuel_heat_kj,
                fuel_specific_heat_kj_kg=fuel_specific_heat_kj_kg,
                fuel_specific_heat_mj_kg=fuel_specific_heat_kj_kg / 1000.0,
                o2_percent=o2,
                co_ppm=co,
                no_ppm=no,
                no2_ppm=no2,
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


def analyze_result_csv(
    path: str | Path,
    steam_inlet_temperature_c: float,
    steam_outlet_temperature_c: float,
) -> list[RegimeAnalysis]:
    return analyze_result_rows(
        read_result_csv(path),
        steam_inlet_temperature_c,
        steam_outlet_temperature_c,
    )


def analysis_to_row(result: RegimeAnalysis) -> dict[str, object]:
    return {
        "Название эксперимента": result.experiment_name,
        "Режим": result.regime_name,
        "Начало режима": result.start_time,
        "Конец режима": result.end_time,
        "Длительность, с": result.duration_seconds,
        "Количество тепла, кДж": result.heat_kj,
        "Количество тепла, кВт·ч": result.heat_kwh,
        "Расход пара, кг/ч": result.steam_flow_kg_h,
        "Масса пара, кг": result.steam_mass_kg,
        "Δh пара, кДж/кг": result.steam_delta_enthalpy_kj_kg,
        "Тепло пара, кДж": result.steam_heat_kj,
        "Расход топлива, кг/ч": result.fuel_flow_kg_h,
        "Масса топлива, кг": result.fuel_mass_kg,
        "Тепло от топлива, кДж": result.fuel_heat_kj,
        "Удельная теплота сгорания, кДж/кг": result.fuel_specific_heat_kj_kg,
        "Удельная теплота сгорания, МДж/кг": result.fuel_specific_heat_mj_kg,
        "O2, %": result.o2_percent,
        "CO, ppm": result.co_ppm,
        "NO, ppm": result.no_ppm,
        "NO2, ppm": result.no2_ppm,
        "CO, мг/кВт·ч": result.co_mg_kwh,
        "NO, мг/кВт·ч": result.no_mg_kwh,
        "NO2, мг/кВт·ч": result.no2_mg_kwh,
    }


def export_analysis_csv(path: str | Path, results: list[RegimeAnalysis]) -> None:
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
