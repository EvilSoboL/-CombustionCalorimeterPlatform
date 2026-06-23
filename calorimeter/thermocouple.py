from __future__ import annotations

import math


# GOST R 8.585-2001 defines nominal static conversion characteristics for
# thermocouples on ITS-90. For thermocouple ТХА(K), the coefficients below match
# the standard type K characteristic. EMF is in mV, temperature is in °C.
_GOST_K_FORWARD_RANGES = (
    (
        -270.0,
        0.0,
        (
            0.000000000000e00,
            0.394501280250e-01,
            0.236223735980e-04,
            -0.328589067840e-06,
            -0.499048287770e-08,
            -0.675090591730e-10,
            -0.574103274280e-12,
            -0.310888728940e-14,
            -0.104516093650e-16,
            -0.198892668780e-19,
            -0.163226974860e-22,
        ),
        None,
    ),
    (
        0.0,
        1372.0,
        (
            -0.176004136860e-01,
            0.389212049750e-01,
            0.185587700320e-04,
            -0.994575928740e-07,
            0.318409457190e-09,
            -0.560728448890e-12,
            0.560750590590e-15,
            -0.320207200030e-18,
            0.971511471520e-22,
            -0.121047212750e-25,
        ),
        (0.118597600000e00, -0.118343200000e-03, 0.126968600000e03),
    ),
)

_GOST_K_INVERSE_RANGES = (
    (
        -5.891,
        0.0,
        (
            0.0000000e00,
            2.5173462e01,
            -1.1662878e00,
            -1.0833638e00,
            -8.9773540e-01,
            -3.7342377e-01,
            -8.6632643e-02,
            -1.0450598e-02,
            -5.1920577e-04,
        ),
    ),
    (
        0.0,
        20.644,
        (
            0.000000e00,
            2.508355e01,
            7.860106e-02,
            -2.503131e-01,
            8.315270e-02,
            -1.228034e-02,
            9.804036e-04,
            -4.413030e-05,
            1.057734e-06,
            -1.052755e-08,
        ),
    ),
    (
        20.644,
        54.886,
        (
            -1.318058e02,
            4.830222e01,
            -1.646031e00,
            5.464731e-02,
            -9.650715e-04,
            8.802193e-06,
            -3.110810e-08,
        ),
    ),
)


def _polynomial(value: float, coefficients: tuple[float, ...]) -> float:
    result = 0.0
    for coefficient in reversed(coefficients):
        result = result * value + coefficient
    return result


def gost_k_celsius_to_emf_mv(temperature_c: float) -> float:
    """Convert ТХА(K) temperature to EMF in mV by GOST R 8.585-2001."""
    if abs(temperature_c) < 1e-12:
        return 0.0
    for index, (minimum, maximum, coefficients, exponential) in enumerate(_GOST_K_FORWARD_RANGES):
        upper_inclusive = index == len(_GOST_K_FORWARD_RANGES) - 1
        if minimum <= temperature_c < maximum or upper_inclusive and temperature_c == maximum:
            emf = _polynomial(temperature_c, coefficients)
            if exponential is not None:
                a0, a1, a2 = exponential
                emf += a0 * math.exp(a1 * (temperature_c - a2) ** 2)
            return emf
    raise ValueError(
        f"Температура свободных концов {temperature_c:.6g} °C вне диапазона ГОСТ "
        "для ТХА(K): −270…1372 °C"
    )


def gost_k_emf_mv_to_celsius(emf_mv: float) -> float:
    """Convert ТХА(K) EMF in mV to temperature by GOST R 8.585-2001."""
    for index, (minimum, maximum, coefficients) in enumerate(_GOST_K_INVERSE_RANGES):
        upper_inclusive = index == len(_GOST_K_INVERSE_RANGES) - 1
        if minimum <= emf_mv < maximum or upper_inclusive and emf_mv == maximum:
            return _polynomial(emf_mv, coefficients)
    raise ValueError(
        f"ЭДС термопары ТХА(K) {emf_mv:.6g} мВ вне диапазона ГОСТ "
        "−5,891…54,886 мВ (−200…1372 °C)"
    )


def type_k_voltage_to_celsius(voltage_v: float, cold_junction_c: float = 0.0) -> float:
    """Convert measured ТХА(K) voltage to °C with free-end compensation."""
    measured_emf_mv = voltage_v * 1000.0
    compensated_emf_mv = measured_emf_mv + gost_k_celsius_to_emf_mv(cold_junction_c)
    return gost_k_emf_mv_to_celsius(compensated_emf_mv)
