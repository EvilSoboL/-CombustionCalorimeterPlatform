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


class ResultAnalysisTests(unittest.TestCase):
    def test_analyze_result_csv_groups_experiments_and_converts_emissions(self) -> None:
        content = """Название эксперимента;Режим;Количество тепла, кДж;% O2, среднее;% O2, N;ппм СO, среднее;ппм СO, N;ппм NO, среднее;ппм NO, N;ппм NO2, среднее;ппм NO2, N
exp-a;r1;1000;10;2;100;2;30;2;3;2
exp-a;r2;2600;14;1;200;1;60;1;6;1
exp-b;r1;1800;5;3;50;3;20;3;2;3
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.csv"
            path.write_text(content, encoding="utf-8")
            results = analyze_result_csv(path)

        self.assertEqual(["exp-a", "exp-b"], [result.experiment_name for result in results])
        first = results[0]
        self.assertEqual(2, first.regime_count)
        self.assertAlmostEqual(3600.0, first.heat_kj_total)
        self.assertAlmostEqual(1.0, first.heat_kwh_total)
        self.assertAlmostEqual((10.0 * 2 + 14.0) / 3.0, first.o2_percent_mean)
        self.assertAlmostEqual((100.0 * 2 + 200.0) / 3.0, first.co_ppm_mean)
        self.assertAlmostEqual(
            emissions_mg_kwh(first.co_ppm_mean, first.o2_percent_mean, CO_CONVERSION_FACTOR),
            first.co_mg_kwh,
        )
        self.assertAlmostEqual(
            emissions_mg_kwh(first.no_ppm_mean, first.o2_percent_mean, NO_CONVERSION_FACTOR),
            first.no_mg_kwh,
        )

    def test_export_analysis_csv_uses_semicolon_and_bom(self) -> None:
        content = """Название эксперимента;Режим;Количество тепла, кДж;% O2, среднее;% O2, N;ппм CO, среднее;ппм CO, N;ппм NO, среднее;ппм NO, N;ппм NO2, среднее;ппм NO2, N
exp-a;r1;3600;10;1;100;1;30;1;3;1
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "result.csv"
            target = Path(directory) / "analysis.csv"
            source.write_text(content, encoding="utf-8")
            results = analyze_result_csv(source)
            export_analysis_csv(target, results)
            self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
            with target.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))

        self.assertEqual("exp-a", rows[0]["Название эксперимента"])
        self.assertEqual("3600.0", rows[0]["Суммарное количество тепла, кДж"])
        self.assertEqual("100.0", rows[0]["CO, среднее, ppm"])

    def test_oxygen_must_be_below_reference_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "меньше 21"):
            emissions_mg_kwh(100.0, 21.0, CO_CONVERSION_FACTOR)


if __name__ == "__main__":
    unittest.main()
