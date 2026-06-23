from __future__ import annotations

import unittest
from datetime import date, datetime

from calorimeter.gui import end_time_options_after_start, parse_user_time
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


if __name__ == "__main__":
    unittest.main()
