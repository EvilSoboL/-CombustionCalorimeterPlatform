from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from calorimeter.models import GasData, OscilloscopeData, ProcessingSettings, Regime
from calorimeter.processing import detect_water_pulses, export_csv, process_experiment
from calorimeter.thermocouple import type_k_voltage_to_celsius


class ProcessingTests(unittest.TestCase):
    def setUp(self) -> None:
        start = datetime(2026, 6, 22, 13, 30, 0)
        times = [start + timedelta(seconds=index) for index in range(5)]
        self.gas = GasData(times, {"% O2": [1.0, 2.0, 3.0, 4.0, 5.0]}, "testo")
        self.temperature = OscilloscopeData(
            times,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            [[0.0] * 5, [0.004095] * 5],
            start,
            "temperature.txt",
        )
        self.water_flow = OscilloscopeData(
            times,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            [[-2.0, 6.0, -2.0, 6.0, -2.0]],
            start,
            "water.txt",
        )
        self.fuel_flow = OscilloscopeData(
            times,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            [[1.0] * 5],
            start,
            "fuel.txt",
        )
        self.regime = Regime("steady", start, start + timedelta(seconds=4))
        self.settings = ProcessingSettings(
            "experiment",
            water_liters_per_pulse=1.0,
            fuel_flow_coefficient_l_min_per_v=2.0,
            cold_junction_temperature_c=0.0,
            density_kg_m3=1000.0,
            heat_capacity_j_kg_c=1000.0,
        )

    def test_statistics_and_heat(self) -> None:
        result = process_experiment(
            self.gas,
            self.temperature,
            self.water_flow,
            self.fuel_flow,
            [self.regime],
            self.settings,
        )[0]
        expected_out = type_k_voltage_to_celsius(0.004095)
        self.assertEqual((3.0, 1.5811388300841898, 5), result.gas_statistics["% O2"])
        self.assertEqual(0.0, result.base["Температура свободных концов термопары, °C"])
        self.assertAlmostEqual(0.0, result.base["Температура входа, среднее, °C"])
        self.assertAlmostEqual(expected_out, result.base["Температура выхода, среднее, °C"])
        self.assertEqual(2, result.base["Импульсов расхода воды"])
        self.assertAlmostEqual(30.0, result.base["Расход воды, среднее, л/мин"])
        self.assertAlmostEqual(2.0, result.base["Расход топлива, среднее, л/мин"])
        expected_power = 1000.0 * (30.0 / 60_000.0) * 1000.0 * expected_out
        self.assertAlmostEqual(expected_power, result.base["Средняя тепловая мощность, Вт"])
        self.assertAlmostEqual(expected_power * 4.0 / 1000.0, result.base["Количество тепла, кДж"])

    def test_xlsx_only_processing_is_allowed(self) -> None:
        result = process_experiment(
            self.gas,
            None,
            None,
            None,
            [self.regime],
            ProcessingSettings("gas-only"),
        )[0]

        self.assertEqual((3.0, 1.5811388300841898, 5), result.gas_statistics["% O2"])
        self.assertEqual("gas-only", result.base["Название эксперимента"])
        self.assertNotIn("Температура входа, среднее, °C", result.base)
        self.assertNotIn("Расход воды, среднее, л/мин", result.base)
        self.assertNotIn("Расход топлива, среднее, л/мин", result.base)

    def test_optional_sensor_coefficients_are_required_only_when_file_is_loaded(self) -> None:
        with self.assertRaisesRegex(ValueError, "Вода, л/импульс"):
            process_experiment(
                self.gas,
                None,
                self.water_flow,
                None,
                [self.regime],
                ProcessingSettings("missing-water-factor"),
            )
        with self.assertRaisesRegex(ValueError, "Топливо"):
            process_experiment(
                self.gas,
                None,
                None,
                self.fuel_flow,
                [self.regime],
                ProcessingSettings("missing-fuel-factor"),
            )

    def test_water_pulses_are_rising_edges(self) -> None:
        pulses, lower, upper = detect_water_pulses(self.water_flow)
        self.assertEqual([self.water_flow.timestamps[1], self.water_flow.timestamps[3]], pulses)
        self.assertLess(lower, upper)

    def test_export_is_semicolon_csv_with_bom(self) -> None:
        result = process_experiment(
            self.gas,
            self.temperature,
            self.water_flow,
            self.fuel_flow,
            [self.regime],
            self.settings,
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.csv"
            export_csv(target, result)
            self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
            with target.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
        self.assertEqual("experiment", rows[0]["Название эксперимента"])
        self.assertEqual("steady", rows[0]["Режим"])
        self.assertEqual("3.0", rows[0]["% O2, среднее"])
        self.assertEqual("2", rows[0]["Импульсов расхода воды"])

    def test_regime_must_be_inside_all_sources(self) -> None:
        outside = Regime(
            "outside",
            self.gas.start - timedelta(seconds=1),
            self.gas.start + timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ValueError, "выходит за общий диапазон"):
            process_experiment(
                self.gas,
                self.temperature,
                self.water_flow,
                self.fuel_flow,
                [outside],
                self.settings,
            )


if __name__ == "__main__":
    unittest.main()
