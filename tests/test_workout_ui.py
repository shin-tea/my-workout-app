"""Exercise the recording/history flow with local fixtures, without Google access."""
import datetime
import unittest

from streamlit.testing.v1 import AppTest
from streamlit.proto.SelectWidgetFilterMode_pb2 import SelectWidgetFilterMode


APP = '''
import datetime
import pandas as pd
import streamlit as st
import main as ui
from workout_data import prepare_log
master = pd.DataFrame([
    {"exercise_id": "1", "exercise_name": "Bench", "target_muscle_group": "Chest"},
    {"exercise_id": "2", "exercise_name": "Row", "target_muscle_group": "Back"},
])
today = datetime.date.today()
raw = pd.DataFrame([
    {"ID": str(i), "Date": str(today - datetime.timedelta(days=days)),
     "ExerciseID": ex, "Weight": weight, "Reps": 10, "Unit": "kg",
     "RPE": "", "Set Type": "Main", "Memo": ""}
    for i, (days, ex, weight) in enumerate([(7, "1", 50), (7, "1", 55), (0, "1", 60), (5, "2", 30)])
])
log = prepare_log(raw, master)
exercises = {row["exercise_id"]: row for row in master.to_dict("records")}
exercise = ui.render_log(log, exercises, pd.DataFrame(), ["kg", "lbs"], ["", "Main", "Up"], None, [])
ui.render_analysis(log, exercises, None, exercise)
'''


class MobileFlowTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_string(APP, default_timeout=20).run()
        self.assertFalse(app.exception)
        return app

    def test_analysis_follows_logging_exercise_and_table_is_default(self):
        app = self.app()
        self.assertEqual(app.radio(key="analysis_display").value, "Table")
        self.assertEqual(app.dataframe[1].value["Weight"].tolist(), ["60 kg", "50 kg", "55 kg"])
        app.selectbox(key="log_ex_select_normal").select("2").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[1].value["Weight"].tolist(), ["30 kg"])
        self.assertEqual(app.number_input(key="weight_2").value, 30)
        # Chart remains available after switching away from the default table.
        app.radio(key="analysis_display").set_value("Chart").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.get("plotly_chart"))

    def test_direct_history_opens_previous_workout_without_changing_exercise(self):
        app = self.app()
        app.button[0].click().run()
        self.assertFalse(app.exception)
        selector = next(item for item in app.selectbox if item.label == "Workout date")
        self.assertEqual((datetime.date.today() - selector.value).days, 7)
        self.assertEqual(app.selectbox(key="log_ex_select_normal").value, "1")
        selector.select(None).run()
        self.assertFalse(app.exception)
        tables = [frame.value for frame in app.dataframe]
        self.assertTrue(any("Set" in frame and len(frame) == 3 for frame in tables))

    def test_menus_disable_search_until_explicitly_enabled(self):
        app = self.app()
        exercise = app.selectbox(key="log_ex_select_normal")
        self.assertEqual(exercise.proto.filter_mode, SelectWidgetFilterMode.FILTER_MODE_NONE)
        app.toggle(key="search_selectors").set_value(True).run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.selectbox(key="log_ex_select_normal").proto.filter_mode,
            SelectWidgetFilterMode.FILTER_MODE_FUZZY,
        )


if __name__ == "__main__":
    unittest.main()
