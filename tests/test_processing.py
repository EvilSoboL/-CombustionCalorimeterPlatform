from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from calorimeter.models import GasData, OscilloscopeData, ProcessingSettings, Regime
from calorimeter.processing import export_csv, process_experiment


class ProcessingTests(unittest.TestCase):
    def setUp(self) -> None:
        start = datetime(2026, 6, 22, 13, 30, 0)
        times = [start + timedelta(seconds=index) for index in range(3)]
        self.gas = GasData(times, {"% O2": [1.0, 2.0, 3.0]}, "testo")
        self.temperature = OscilloscopeData(
            times,
            [0.0, 1.0, 2.0],
            [[1.0, 1.0, 1.0], [3.0, 3.0, 3.0]],
            start,
            "temperature.txt",
        )
        self.flow = OscilloscopeData(
            times,
            [0.0, 1.0, 2.0],
            [[2.0, 2.0, 2.0]],
            start,
            "flow.txt",
        )
        self.regime = Regime("steady", start, start + timedelta(seconds=2))
        self.settings = ProcessingSettings(
            "experiment",
            temperature_coefficient_c_per_v=10.0,
            flow_coefficient_l_min_per_v=3.0,
            density_kg_m3=1000.0,
            heat_capacity_j_kg_c=1000.0,
        )

    def test_statistics_and_heat(self) -> None:
        result = process_experiment(
            self.gas, self.temperature, self.flow, [self.regime], self.settings
        )[0]
        self.assertEqual((2.0, 1.0, 3), result.gas_statistics["% O2"])
        self.assertAlmostEqual(10.0, result.base["Температура входа, среднее, °C"])
        self.assertAlmostEqual(30.0, result.base["Температура выхода, среднее, °C"])
        self.assertAlmostEqual(6.0, result.base["Расход, среднее, л/мин"])
        self.assertAlmostEqual(2000.0, result.base["Средняя тепловая мощность, Вт"])
        self.assertAlmostEqual(4.0, result.base["Количество тепла, кДж"])

    def test_export_is_semicolon_csv_with_bom(self) -> None:
        result = process_experiment(
            self.gas, self.temperature, self.flow, [self.regime], self.settings
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.csv"
            export_csv(target, result)
            self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
            with target.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
        self.assertEqual("experiment", rows[0]["Название эксперимента"])
        self.assertEqual("steady", rows[0]["Режим"])
        self.assertEqual("2.0", rows[0]["% O2, среднее"])
        self.assertEqual("1.0", rows[0]["% O2, СКО"])

    def test_regime_must_be_inside_all_sources(self) -> None:
        outside = Regime(
            "outside",
            self.gas.start - timedelta(seconds=1),
            self.gas.start + timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ValueError, "выходит за общий диапазон"):
            process_experiment(
                self.gas, self.temperature, self.flow, [outside], self.settings
            )


if __name__ == "__main__":
    unittest.main()
