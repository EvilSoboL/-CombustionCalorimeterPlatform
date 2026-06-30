from __future__ import annotations


WATER_MOLAR_MASS_KG_MOL = 0.01801528
MIN_SHOMATE_TEMPERATURE_K = 500.0
MAX_SHOMATE_TEMPERATURE_K = 6000.0
WATER_LIQUID_CP_KJ_KG_C = 4.186
STEAM_CP_BELOW_SHOMATE_KJ_KG_C = 2.08
WATER_VAPORIZATION_HEAT_100C_KJ_KG = 2256.9
WATER_BOILING_TEMPERATURE_C = 100.0


_SHOMATE_COEFFICIENTS = (
    (500.0, 1700.0, 30.09200, 6.832514, 6.793435, -2.534480, 0.082139, -250.8810, -241.8264),
    (1700.0, 6000.0, 41.96426, 8.622053, -1.499780, 0.098119, -11.15764, -272.1797, -241.8264),
)


def _temperature_k(temperature_c: float) -> float:
    return temperature_c + 273.15


def _coefficients(temperature_k: float) -> tuple[float, float, float, float, float, float, float]:
    for minimum, maximum, a, b, c, d, e, f, h in _SHOMATE_COEFFICIENTS:
        if minimum <= temperature_k <= maximum:
            return a, b, c, d, e, f, h
    minimum_c = MIN_SHOMATE_TEMPERATURE_K - 273.15
    maximum_c = MAX_SHOMATE_TEMPERATURE_K - 273.15
    raise ValueError(
        "Температура пара должна быть в диапазоне "
        f"{minimum_c:.2f}…{maximum_c:.2f} °C для расчета по уравнению Шомейта"
    )


def _shomate_enthalpy_relative_kj_mol(temperature_k: float) -> float:
    a, b, c, d, e, f, h = _coefficients(temperature_k)
    t = temperature_k / 1000.0
    return a * t + b * t**2 / 2.0 + c * t**3 / 3.0 + d * t**4 / 4.0 - e / t + f - h


def water_vapor_delta_enthalpy_kj_kg(inlet_temperature_c: float, outlet_temperature_c: float) -> float:
    inlet_h = _shomate_enthalpy_relative_kj_mol(_temperature_k(inlet_temperature_c))
    outlet_h = _shomate_enthalpy_relative_kj_mol(_temperature_k(outlet_temperature_c))
    return (outlet_h - inlet_h) / WATER_MOLAR_MASS_KG_MOL


def _steam_superheat_enthalpy_kj_kg(outlet_temperature_c: float) -> float:
    if outlet_temperature_c < WATER_BOILING_TEMPERATURE_C:
        raise ValueError("Температура выхода парогенератора должна быть не ниже 100 °C")
    shomate_minimum_c = MIN_SHOMATE_TEMPERATURE_K - 273.15
    if outlet_temperature_c <= shomate_minimum_c:
        return STEAM_CP_BELOW_SHOMATE_KJ_KG_C * (
            outlet_temperature_c - WATER_BOILING_TEMPERATURE_C
        )
    lower_segment = STEAM_CP_BELOW_SHOMATE_KJ_KG_C * (
        shomate_minimum_c - WATER_BOILING_TEMPERATURE_C
    )
    upper_segment = water_vapor_delta_enthalpy_kj_kg(shomate_minimum_c, outlet_temperature_c)
    return lower_segment + upper_segment


def steam_generator_delta_enthalpy_kj_kg(
    inlet_temperature_c: float,
    outlet_temperature_c: float,
) -> float:
    inlet_liquid_enthalpy = WATER_LIQUID_CP_KJ_KG_C * inlet_temperature_c
    outlet_steam_enthalpy = (
        WATER_LIQUID_CP_KJ_KG_C * WATER_BOILING_TEMPERATURE_C
        + WATER_VAPORIZATION_HEAT_100C_KJ_KG
        + _steam_superheat_enthalpy_kj_kg(outlet_temperature_c)
    )
    return outlet_steam_enthalpy - inlet_liquid_enthalpy
