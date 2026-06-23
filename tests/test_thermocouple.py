from __future__ import annotations

import unittest

from calorimeter.thermocouple import type_k_voltage_to_celsius


class TypeKThermocoupleTests(unittest.TestCase):
    def test_nist_reference_points(self) -> None:
        self.assertAlmostEqual(0.0, type_k_voltage_to_celsius(0.0), places=9)
        self.assertAlmostEqual(100.0, type_k_voltage_to_celsius(0.004095), delta=0.1)
        self.assertAlmostEqual(-200.0, type_k_voltage_to_celsius(-0.005891), delta=0.1)
        self.assertAlmostEqual(1372.0, type_k_voltage_to_celsius(0.054886), delta=0.1)

    def test_out_of_range_voltage_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "вне диапазона NIST"):
            type_k_voltage_to_celsius(0.060)


if __name__ == "__main__":
    unittest.main()
