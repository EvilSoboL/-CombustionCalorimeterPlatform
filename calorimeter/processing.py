from __future__ import annotations

import csv
import math
import statistics
from bisect import bisect_left, bisect_right
from datetime import datetime
from pathlib import Path

from .models import GasData, OscilloscopeData, ProcessingSettings, Regime, RegimeResult


def common_time_range(
    gas: GasData, temperature: OscilloscopeData, flow: OscilloscopeData
) -> tuple[datetime, datetime]:
    return max(gas.start, temperature.start, flow.start), min(gas.end, temperature.end, flow.end)


def validate_regimes(
    regimes: list[Regime], gas: GasData, temperature: OscilloscopeData, flow: OscilloscopeData
) -> None:
    if not regimes:
        raise ValueError("Добавьте хотя бы один режим")
    common_start, common_end = common_time_range(gas, temperature, flow)
    if common_start >= common_end:
        raise ValueError("Временные диапазоны трех файлов не пересекаются")
    names: set[str] = set()
    ordered = sorted(regimes, key=lambda item: item.start)
    for regime in ordered:
        normalized_name = regime.name.strip().casefold()
        if normalized_name in names:
            raise ValueError(f"Название режима повторяется: {regime.name}")
        names.add(normalized_name)
        if regime.start < common_start or regime.end > common_end:
            raise ValueError(
                f"Режим «{regime.name}» выходит за общий диапазон файлов "
                f"{common_start:%Y-%m-%d %H:%M:%S} - {common_end:%Y-%m-%d %H:%M:%S}"
            )
    for previous, current in zip(ordered, ordered[1:]):
        if current.start < previous.end:
            raise ValueError(f"Режимы «{previous.name}» и «{current.name}» перекрываются")


def _sample_statistics(values: list[float]) -> tuple[float, float, int]:
    if not values:
        return math.nan, math.nan, 0
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    return statistics.fmean(values), deviation, len(values)


def _interpolate(timestamps: list[datetime], values: list[float], target: datetime) -> float:
    index = bisect_left(timestamps, target)
    if index < len(timestamps) and timestamps[index] == target:
        return values[index]
    if index == 0 or index == len(timestamps):
        raise ValueError("Невозможно интерполировать за пределами временного диапазона")
    left_time = timestamps[index - 1]
    right_time = timestamps[index]
    span = (right_time - left_time).total_seconds()
    fraction = (target - left_time).total_seconds() / span
    return values[index - 1] + fraction * (values[index] - values[index - 1])


def _regime_result(
    regime: Regime,
    gas: GasData,
    temperature: OscilloscopeData,
    flow: OscilloscopeData,
    settings: ProcessingSettings,
) -> RegimeResult:
    gas_left = bisect_left(gas.timestamps, regime.start)
    gas_right = bisect_right(gas.timestamps, regime.end)
    if gas_left == gas_right:
        raise ValueError(f"В режиме «{regime.name}» нет отсчетов газоанализатора")
    gas_statistics: dict[str, tuple[float, float, int]] = {}
    for name, values in gas.columns.items():
        selected = [value for value in values[gas_left:gas_right] if value is not None]
        gas_statistics[name] = _sample_statistics(selected)

    temp_left = bisect_left(temperature.timestamps, regime.start)
    temp_right = bisect_right(temperature.timestamps, regime.end)
    raw_in = temperature.channels[0][temp_left:temp_right]
    raw_out = temperature.channels[1][temp_left:temp_right]
    if not raw_in:
        raise ValueError(f"В режиме «{regime.name}» нет отсчетов температуры")
    temperatures_in = [
        value * settings.temperature_coefficient_c_per_v + settings.temperature_offset_c
        for value in raw_in
    ]
    temperatures_out = [
        value * settings.temperature_coefficient_c_per_v + settings.temperature_offset_c
        for value in raw_out
    ]

    flow_left = bisect_left(flow.timestamps, regime.start)
    flow_right = bisect_right(flow.timestamps, regime.end)
    raw_flow = flow.channels[0][flow_left:flow_right]
    if not raw_flow:
        raise ValueError(f"В режиме «{regime.name}» нет отсчетов расхода")
    flow_values = [
        max(0.0, (value - settings.flow_zero_v) * settings.flow_coefficient_l_min_per_v)
        for value in raw_flow
    ]

    internal_times = temperature.timestamps[temp_left:temp_right]
    integration_times = [regime.start]
    integration_times.extend(time for time in internal_times if regime.start < time < regime.end)
    integration_times.append(regime.end)
    powers: list[float] = []
    for timestamp in integration_times:
        voltage_in = _interpolate(temperature.timestamps, temperature.channels[0], timestamp)
        voltage_out = _interpolate(temperature.timestamps, temperature.channels[1], timestamp)
        temperature_in = voltage_in * settings.temperature_coefficient_c_per_v + settings.temperature_offset_c
        temperature_out = voltage_out * settings.temperature_coefficient_c_per_v + settings.temperature_offset_c
        flow_voltage = _interpolate(flow.timestamps, flow.channels[0], timestamp)
        flow_l_min = max(
            0.0,
            (flow_voltage - settings.flow_zero_v) * settings.flow_coefficient_l_min_per_v,
        )
        volume_flow_m3_s = flow_l_min / 60_000.0
        powers.append(
            settings.density_kg_m3
            * volume_flow_m3_s
            * settings.heat_capacity_j_kg_c
            * (temperature_out - temperature_in)
        )
    heat_j = 0.0
    for index in range(1, len(integration_times)):
        delta_seconds = (integration_times[index] - integration_times[index - 1]).total_seconds()
        heat_j += (powers[index - 1] + powers[index]) * 0.5 * delta_seconds
    duration_seconds = (regime.end - regime.start).total_seconds()

    base: dict[str, object] = {
        "Название эксперимента": settings.experiment_name.strip(),
        "Режим": regime.name.strip(),
        "Начало режима": regime.start.isoformat(sep=" ", timespec="seconds"),
        "Конец режима": regime.end.isoformat(sep=" ", timespec="seconds"),
        "Длительность, с": duration_seconds,
        "Отсчетов газоанализатора": gas_right - gas_left,
        "Отсчетов температуры": len(raw_in),
        "Отсчетов расхода": len(raw_flow),
        "Температура входа, среднее, °C": statistics.fmean(temperatures_in),
        "Температура выхода, среднее, °C": statistics.fmean(temperatures_out),
        "Расход, среднее, л/мин": statistics.fmean(flow_values),
        "Средняя тепловая мощность, Вт": heat_j / duration_seconds,
        "Количество тепла, кДж": heat_j / 1000.0,
    }
    return RegimeResult(base=base, gas_statistics=gas_statistics)


def process_experiment(
    gas: GasData,
    temperature: OscilloscopeData,
    flow: OscilloscopeData,
    regimes: list[Regime],
    settings: ProcessingSettings,
) -> list[RegimeResult]:
    if len(temperature.channels) < 2:
        raise ValueError("Файл температуры должен содержать два канала")
    if not flow.channels:
        raise ValueError("Файл расхода должен содержать один канал")
    validate_regimes(regimes, gas, temperature, flow)
    return [
        _regime_result(regime, gas, temperature, flow, settings)
        for regime in sorted(regimes, key=lambda item: item.start)
    ]


def export_csv(path: str | Path, results: list[RegimeResult]) -> None:
    if not results:
        raise ValueError("Нет результатов для экспорта")
    gas_columns: list[str] = []
    for result in results:
        for name in result.gas_statistics:
            if name not in gas_columns:
                gas_columns.append(name)
    base_columns = list(results[0].base)
    fieldnames = base_columns.copy()
    for name in gas_columns:
        fieldnames.extend((f"{name}, среднее", f"{name}, СКО", f"{name}, N"))

    try:
        handle = Path(path).open("w", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"Не удалось создать CSV: {exc}") from exc
    with handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for result in results:
            row = result.base.copy()
            for name in gas_columns:
                mean, deviation, count = result.gas_statistics.get(name, (math.nan, math.nan, 0))
                row[f"{name}, среднее"] = mean
                row[f"{name}, СКО"] = deviation
                row[f"{name}, N"] = count
            writer.writerow(row)
