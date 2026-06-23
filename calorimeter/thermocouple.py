from __future__ import annotations


# NIST ITS-90 inverse coefficients for a type K thermocouple. Input is mV,
# output is degrees Celsius relative to a 0 °C reference junction.
_TYPE_K_INVERSE_RANGES = (
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


def type_k_voltage_to_celsius(voltage_v: float) -> float:
    """Convert type K thermocouple voltage to °C using NIST ITS-90."""
    emf_mv = voltage_v * 1000.0
    for index, (minimum, maximum, coefficients) in enumerate(_TYPE_K_INVERSE_RANGES):
        upper_inclusive = index == len(_TYPE_K_INVERSE_RANGES) - 1
        if minimum <= emf_mv < maximum or upper_inclusive and emf_mv == maximum:
            return _polynomial(emf_mv, coefficients)
    raise ValueError(
        f"ЭДС термопары K {emf_mv:.6g} мВ вне диапазона NIST "
        "−5,891…54,886 мВ (−200…1372 °C)"
    )
