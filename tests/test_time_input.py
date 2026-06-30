from __future__ import annotations

import unittest
from datetime import date, datetime

from calorimeter.gui import (
    build_regime_name,
    end_time_options_after_start,
    parse_regime_name,
    parse_user_time,
)
from calorimeter.models import GasData
from calorimeter.processing import gas_contains_minute


class TimeInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gas = GasData(
            [
                datetime(2026, 6, 22, 13, 23, 58),
                datetime(2026, 6, 22, 13, 24, 0),
                datetime(2026, 6, 22, 13, 24, 59),
            ],
            {"% O2": [1.0, 2.0, 3.0]},
            "testo",
        )

    def test_only_hours_and_minutes_are_accepted(self) -> None:
        parsed = parse_user_time("13:24", date(2026, 6, 22))
        self.assertEqual(datetime(2026, 6, 22, 13, 24), parsed)
        with self.assertRaisesRegex(ValueError, "ЧЧ:ММ"):
            parse_user_time("13:24:00", date(2026, 6, 22))

    def test_selected_minute_must_exist_in_xlsx(self) -> None:
        self.assertTrue(gas_contains_minute(self.gas, datetime(2026, 6, 22, 13, 23)))
        self.assertTrue(gas_contains_minute(self.gas, datetime(2026, 6, 22, 13, 24)))
        self.assertFalse(gas_contains_minute(self.gas, datetime(2026, 6, 22, 13, 25)))

    def test_end_time_options_are_later_than_start(self) -> None:
        options = ["13:23", "13:24", "13:25", "13:26"]
        self.assertEqual(["13:25", "13:26"], end_time_options_after_start(options, "13:24"))
        self.assertEqual([], end_time_options_after_start(options, "13:26"))

    def test_regime_name_is_built_from_flow_values(self) -> None:
        self.assertEqual("F1V0.8A7.5", build_regime_name(1.0, "V", 0.8, 7.5))
        self.assertEqual("F1A0.8", build_regime_name(1.0, "A", 0.8, None))
        self.assertEqual((1.0, "V", 0.8, 7.5), parse_regime_name("F1V0.8A7.5"))

    def test_regime_name_rejects_non_positive_flow(self) -> None:
        with self.assertRaisesRegex(ValueError, "топлива"):
            build_regime_name(0.0, "V", 0.8, 7.5)


if __name__ == "__main__":
    unittest.main()
