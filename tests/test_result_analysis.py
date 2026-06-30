from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from calorimeter.result_analysis import (
    CO_CONVERSION_FACTOR,
    NO_CONVERSION_FACTOR,
    analyze_result_csv,
    emissions_mg_kwh,
    export_analysis_csv,
)
from calorimeter.steam_enthalpy import steam_generator_delta_enthalpy_kj_kg


class ResultAnalysisTests(unittest.TestCase):
    def test_analyze_result_csv_keeps_each_regime_separate(self) -> None:
        content = """Название эксперимента;Режим;Начало режима;Конец режима;Длительность, с;Количество тепла, кДж;% O2, среднее;% O2, N;ппм СO, среднее;ппм СO, N;ппм NO, среднее;ппм NO, N;ппм NO2, среднее;ппм NO2, N
exp-a;F1V0.8A7.5;2026-06-22 13:00:00;2026-06-22 13:02:00;120;5000;10;2;100;2;30;2;3;2
exp-a;F1V0.8A5;2026-06-22 13:03:00;2026-06-22 13:05:00;120;2600;14;1;200;1;60;1;6;1
exp-b;F2A0.5A7.5;2026-06-22 13:06:00;2026-06-22 13:07:00;60;1800;5;3;50;3;20;3;2;3
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.csv"
            path.write_text(content, encoding="utf-8")
            results = analyze_result_csv(path, 250.0, 300.0)

        self.assertEqual(["exp-a", "exp-a", "exp-b"], [result.experiment_name for result in results])
        self.assertEqual(
            ["F1V0.8A7.5", "F1V0.8A5", "F2A0.5A7.5"],
            [result.regime_name for result in results],
        )
        first = results[0]
        self.assertEqual("2026-06-22 13:00:00", first.start_time)
        self.assertEqual("2026-06-22 13:02:00", first.end_time)
        self.assertAlmostEqual(5000.0, first.heat_kj)
        self.assertAlmostEqual(5000.0 / 3600.0, first.heat_kwh)
        delta_h = steam_generator_delta_enthalpy_kj_kg(250.0, 300.0)
        self.assertAlmostEqual(1.0 * 120.0 / 3600.0, first.fuel_mass_kg)
        self.assertAlmostEqual(0.8 * 120.0 / 3600.0, first.steam_mass_kg)
        self.assertAlmostEqual(delta_h * first.steam_mass_kg, first.steam_heat_kj)
        self.assertAlmostEqual(first.heat_kj - first.steam_heat_kj, first.fuel_heat_kj)
        self.assertAlmostEqual(first.fuel_heat_kj / first.fuel_mass_kg, first.fuel_specific_heat_kj_kg)
        self.assertAlmostEqual(10.0, first.o2_percent)
        self.assertAlmostEqual(100.0, first.co_ppm)
        self.assertEqual(0.0, results[2].steam_heat_kj)
        self.assertAlmostEqual(
            emissions_mg_kwh(first.co_ppm, first.o2_percent, CO_CONVERSION_FACTOR),
            first.co_mg_kwh,
        )
        self.assertAlmostEqual(
            emissions_mg_kwh(first.no_ppm, first.o2_percent, NO_CONVERSION_FACTOR),
            first.no_mg_kwh,
        )

    def test_export_analysis_csv_uses_semicolon_and_bom(self) -> None:
        content = """Название эксперимента;Режим;Начало режима;Конец режима;Длительность, с;Количество тепла, кДж;% O2, среднее;% O2, N;ппм CO, среднее;ппм CO, N;ппм NO, среднее;ппм NO, N;ппм NO2, среднее;ппм NO2, N
exp-a;F1V0.8A7.5;2026-06-22 13:00:00;2026-06-22 13:02:00;120;3600;10;1;100;1;30;1;3;1
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "result.csv"
            target = Path(directory) / "analysis.csv"
            source.write_text(content, encoding="utf-8")
            results = analyze_result_csv(source, 250.0, 300.0)
            export_analysis_csv(target, results)
            self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
            with target.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))

        self.assertEqual("exp-a", rows[0]["Название эксперимента"])
        self.assertEqual("F1V0.8A7.5", rows[0]["Режим"])
        self.assertEqual("3600.0", rows[0]["Количество тепла, кДж"])
        self.assertIn("Тепло пара, кДж", rows[0])
        self.assertIn("Удельная теплота сгорания, МДж/кг", rows[0])
        self.assertEqual("100.0", rows[0]["CO, ppm"])

    def test_oxygen_must_be_below_reference_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "меньше 21"):
            emissions_mg_kwh(100.0, 21.0, CO_CONVERSION_FACTOR)

    def test_steam_generator_enthalpy_requires_steam_outlet_temperature(self) -> None:
        self.assertGreater(steam_generator_delta_enthalpy_kj_kg(25.0, 250.0), 0.0)
        with self.assertRaisesRegex(ValueError, "не ниже 100"):
            steam_generator_delta_enthalpy_kj_kg(25.0, 90.0)


if __name__ == "__main__":
    unittest.main()
