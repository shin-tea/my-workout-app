import unittest

import pandas as pd

from workout_data import history_table


class HistoryTableTests(unittest.TestCase):
    def test_newest_days_keep_original_set_order_and_units(self):
        records = pd.DataFrame([
            {"Date": pd.Timestamp("2026-10-28"), "_Row": 3, "Weight": -20.0, "Unit": "kg", "Reps": 8},
            {"Date": pd.Timestamp("2026-10-01"), "_Row": 4, "Weight": 90.0, "Unit": "lbs", "Reps": 10},
            {"Date": pd.Timestamp("2026-10-28"), "_Row": 0, "Weight": 40.5, "Unit": "lbs", "Reps": 12},
        ])
        before = records.copy(deep=True)
        result = history_table(records)
        self.assertEqual(result["Weight"].tolist(), ["40.5 lbs", "-20 kg", "90 lbs"])
        self.assertEqual(result["Set"].tolist(), [1, 2, 1])
        self.assertEqual(result["Reps"].tolist(), [12, 8, 10])
        pd.testing.assert_frame_equal(records, before)

    def test_empty_history_has_display_columns(self):
        self.assertEqual(list(history_table(pd.DataFrame())), ["Date", "Set", "Weight", "Reps"])


if __name__ == "__main__":
    unittest.main()
