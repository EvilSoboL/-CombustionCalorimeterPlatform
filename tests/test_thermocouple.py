from __future__ import annotations

import unittest

from calorimeter.thermocouple import (
    gost_k_celsius_to_emf_mv,
    gost_k_emf_mv_to_celsius,
    type_k_voltage_to_celsius,
)


class TypeKThermocoupleTests(unittest.TestCase):
    def test_gost_reference_points_at_zero_cold_junction(self) -> None:
        self.assertAlmostEqual(0.0, type_k_voltage_to_celsius(0.0), places=9)
        self.assertAlmostEqual(100.0, type_k_voltage_to_celsius(0.004095), delta=0.1)
        self.assertAlmostEqual(-200.0, type_k_voltage_to_celsius(-0.005891), delta=0.1)
        self.assertAlmostEqual(1372.0, type_k_voltage_to_celsius(0.054886), delta=0.1)

    def test_free_end_compensation_adds_cold_junction_emf(self) -> None:
        cold_emf_mv = gost_k_celsius_to_emf_mv(25.0)
        hot_emf_mv = gost_k_celsius_to_emf_mv(100.0)
        measured_voltage_v = (hot_emf_mv - cold_emf_mv) / 1000.0

        self.assertAlmostEqual(100.0, type_k_voltage_to_celsius(measured_voltage_v, 25.0), delta=0.1)
        self.assertAlmostEqual(25.0, gost_k_emf_mv_to_celsius(cold_emf_mv), delta=0.1)

    def test_out_of_range_voltage_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "вне диапазона ГОСТ"):
            type_k_voltage_to_celsius(0.060)


if __name__ == "__main__":
    unittest.main()
