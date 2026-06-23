from __future__ import annotations

import csv
import math
import statistics
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from pathlib import Path

from .models import GasData, OscilloscopeData, ProcessingSettings, Regime, RegimeResult
from .thermocouple import type_k_voltage_to_celsius


def common_time_range(
    gas: GasData,
    temperature: OscilloscopeData | None = None,
    water_flow: OscilloscopeData | None = None,
    fuel_flow: OscilloscopeData | None = None,
) -> tuple[datetime, datetime]:
    sources = [gas, *(item for item in (temperature, water_flow, fuel_flow) if item is not None)]
    return (
        max(source.start for source in sources),
        min(source.end for source in sources),
    )


def gas_contains_minute(gas: GasData, value: datetime) -> bool:
    """Return whether XLSX has at least one timestamp in the selected minute."""
    minute_start = value.replace(second=0, microsecond=0)
    minute_end = minute_start + timedelta(minutes=1)
    index = bisect_left(gas.timestamps, minute_start)
    return index < len(gas.timestamps) and gas.timestamps[index] < minute_end


def validate_regimes(
    regimes: list[Regime],
    gas: GasData,
    temperature: OscilloscopeData | None = None,
    water_flow: OscilloscopeData | None = None,
    fuel_flow: OscilloscopeData | None = None,
) -> None:
    if not regimes:
        raise ValueError("Добавьте хотя бы один режим")
    common_start, common_end = common_time_range(gas, temperature, water_flow, fuel_flow)
    if common_start >= common_end:
        raise ValueError("Временные диапазоны загруженных файлов не пересекаются")
    names: set[str] = set()
    ordered = sorted(regimes, key=lambda item: item.start)
    for regime in ordered:
        normalized_name = regime.name.strip().casefold()
        if normalized_name in names:
            raise ValueError(f"Название режима повторяется: {regime.name}")
        names.add(normalized_name)
        if regime.start < common_start or regime.end > common_end:
            raise ValueError(
                f"Режим «{regime.name}» выходит за общий диапазон загруженных файлов "
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


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def detect_water_pulses(water_flow: OscilloscopeData) -> tuple[list[datetime], float, float]:
    """Detect rising pulse edges using automatic Schmitt-trigger thresholds."""
    values = water_flow.channels[0]
    low_level = _percentile(values, 0.10)
    high_level = _percentile(values, 0.90)
    amplitude = high_level - low_level
    if amplitude <= 1e-9:
        raise ValueError("В файле расхода воды не обнаружен импульсный сигнал")
    lower_threshold = low_level + 0.35 * amplitude
    upper_threshold = low_level + 0.65 * amplitude
    armed = values[0] <= lower_threshold
    pulses: list[datetime] = []
    for timestamp, value in zip(water_flow.timestamps, values):
        if armed and value >= upper_threshold:
            pulses.append(timestamp)
            armed = False
        elif not armed and value <= lower_threshold:
            armed = True
    if not pulses:
        raise ValueError("В файле расхода воды не найдено восходящих фронтов")
    return pulses, lower_threshold, upper_threshold


def _regime_result(
    regime: Regime,
    gas: GasData,
    temperature: OscilloscopeData | None,
    water_flow: OscilloscopeData | None,
    fuel_flow: OscilloscopeData | None,
    water_pulses: list[datetime] | None,
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

    duration_seconds = (regime.end - regime.start).total_seconds()
    base: dict[str, object] = {
        "Название эксперимента": settings.experiment_name.strip(),
        "Режим": regime.name.strip(),
        "Начало режима": regime.start.isoformat(sep=" ", timespec="seconds"),
        "Конец режима": regime.end.isoformat(sep=" ", timespec="seconds"),
        "Длительность, с": duration_seconds,
        "Отсчетов газоанализатора": gas_right - gas_left,
    }

    temp_left = temp_right = 0
    if temperature is not None:
        temp_left = bisect_left(temperature.timestamps, regime.start)
        temp_right = bisect_right(temperature.timestamps, regime.end)
        raw_in = temperature.channels[0][temp_left:temp_right]
        raw_out = temperature.channels[1][temp_left:temp_right]
        if not raw_in:
            raise ValueError(f"В режиме «{regime.name}» нет отсчетов температуры")
        temperatures_in = [type_k_voltage_to_celsius(value) for value in raw_in]
        temperatures_out = [type_k_voltage_to_celsius(value) for value in raw_out]
        base.update(
            {
                "Отсчетов температуры": len(raw_in),
                "Температура входа, среднее, °C": statistics.fmean(temperatures_in),
                "Температура выхода, среднее, °C": statistics.fmean(temperatures_out),
            }
        )

    water_flow_l_min: float | None = None
    if water_flow is not None:
        if water_pulses is None or settings.water_liters_per_pulse is None:
            raise ValueError("Для расчета расхода воды укажите «Вода, л/импульс»")
        water_left = bisect_left(water_flow.timestamps, regime.start)
        water_right = bisect_right(water_flow.timestamps, regime.end)
        if water_left == water_right:
            raise ValueError(f"В режиме «{regime.name}» нет отсчетов расхода воды")
        pulse_left = bisect_left(water_pulses, regime.start)
        pulse_right = bisect_left(water_pulses, regime.end)
        pulse_count = pulse_right - pulse_left
        water_volume_l = pulse_count * settings.water_liters_per_pulse
        water_flow_l_min = water_volume_l * 60.0 / duration_seconds
        base.update(
            {
                "Отсчетов расхода воды": water_right - water_left,
                "Импульсов расхода воды": pulse_count,
                "Объем воды, л": water_volume_l,
                "Расход воды, среднее, л/мин": water_flow_l_min,
            }
        )

    if fuel_flow is not None:
        if settings.fuel_flow_coefficient_l_min_per_v is None:
            raise ValueError("Для расчета расхода топлива укажите «Топливо, л/(мин·В)»")
        fuel_left = bisect_left(fuel_flow.timestamps, regime.start)
        fuel_right = bisect_right(fuel_flow.timestamps, regime.end)
        raw_fuel = fuel_flow.channels[0][fuel_left:fuel_right]
        if not raw_fuel:
            raise ValueError(f"В режиме «{regime.name}» нет отсчетов расхода топлива")
        fuel_values = [
            max(
                0.0,
                (value - settings.fuel_flow_zero_v)
                * settings.fuel_flow_coefficient_l_min_per_v,
            )
            for value in raw_fuel
        ]
        base.update(
            {
                "Отсчетов расхода топлива": len(raw_fuel),
                "Расход топлива, среднее, л/мин": statistics.fmean(fuel_values),
                "Сигнал расхода топлива, среднее, В": statistics.fmean(raw_fuel),
            }
        )

    if temperature is not None and water_flow_l_min is not None:
        internal_times = temperature.timestamps[temp_left:temp_right]
        integration_times = [regime.start]
        integration_times.extend(time for time in internal_times if regime.start < time < regime.end)
        integration_times.append(regime.end)
        powers: list[float] = []
        for timestamp in integration_times:
            voltage_in = _interpolate(temperature.timestamps, temperature.channels[0], timestamp)
            voltage_out = _interpolate(temperature.timestamps, temperature.channels[1], timestamp)
            temperature_in = type_k_voltage_to_celsius(voltage_in)
            temperature_out = type_k_voltage_to_celsius(voltage_out)
            volume_flow_m3_s = water_flow_l_min / 60_000.0
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
        base.update(
            {
                "Средняя тепловая мощность, Вт": heat_j / duration_seconds,
                "Количество тепла, кДж": heat_j / 1000.0,
            }
        )
    return RegimeResult(base=base, gas_statistics=gas_statistics)


def process_experiment(
    gas: GasData,
    temperature: OscilloscopeData | None,
    water_flow: OscilloscopeData | None,
    fuel_flow: OscilloscopeData | None,
    regimes: list[Regime],
    settings: ProcessingSettings,
) -> list[RegimeResult]:
    if temperature is not None and len(temperature.channels) < 2:
        raise ValueError("Файл температуры должен содержать два канала")
    if water_flow is not None and not water_flow.channels:
        raise ValueError("Файл расхода воды должен содержать один канал")
    if fuel_flow is not None and not fuel_flow.channels:
        raise ValueError("Файл расхода топлива должен содержать один канал")
    if water_flow is not None and settings.water_liters_per_pulse is None:
        raise ValueError("Для расчета расхода воды укажите «Вода, л/импульс»")
    if fuel_flow is not None and settings.fuel_flow_coefficient_l_min_per_v is None:
        raise ValueError("Для расчета расхода топлива укажите «Топливо, л/(мин·В)»")
    validate_regimes(regimes, gas, temperature, water_flow, fuel_flow)
    water_pulses = None
    if water_flow is not None:
        water_pulses, _, _ = detect_water_pulses(water_flow)
    return [
        _regime_result(
            regime,
            gas,
            temperature,
            water_flow,
            fuel_flow,
            water_pulses,
            settings,
        )
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
