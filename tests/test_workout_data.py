import unittest

import pandas as pd

from workout_data import (
    exercise_name_formula, exercise_records, history_update_requests,
    next_template_id, prepare_log, resolve_exercise_names, template_exercises,
)


HEADERS = ['ID', 'Date', 'ExerciseID', 'Target', 'Exercise', 'Weight',
           'Unit', 'Reps', 'RPE', 'Set Type', 'Memo']


class ExerciseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.master = pd.DataFrame([
            {'exercise_id': 27, 'exercise_name': 'Seated Row (Cable)'},
            {'exercise_id': 40, 'exercise_name': 'Preacher Curl (Machine)'},
            {'exercise_id': 52, 'exercise_name': 'Hammer Curl (Dumbbell)'},
        ])

    def test_names_and_filter_follow_id_even_when_old_name_conflicts(self):
        logs = pd.DataFrame([
            {'ExerciseID': '27.0', 'Exercise': 'Row (Cable)'},
            {'ExerciseID': 27, 'Exercise': 'Seated Row (Cable)'},
            {'ExerciseID': 40, 'Exercise': 'One Hand Arm Curl (Dumbbell)'},
            {'ExerciseID': '52', 'Exercise': 'Hummer Curl (Dumbbell)'},
        ])
        resolved = resolve_exercise_names(logs, self.master)
        self.assertEqual(resolved['Exercise'].tolist(), [
            'Seated Row (Cable)', 'Seated Row (Cable)',
            'Preacher Curl (Machine)', 'Hammer Curl (Dumbbell)',
        ])
        self.assertEqual(len(exercise_records(resolved, 27.0)), 2)
        self.assertEqual(logs.iloc[0]['Exercise'], 'Row (Cable)')
        renamed = self.master.copy()
        renamed.loc[0, 'exercise_name'] = 'New Row Name'
        self.assertEqual(resolve_exercise_names(logs, renamed).iloc[0]['Exercise'], 'New Row Name')

    def test_unknown_id_stays_visible_without_using_stale_name(self):
        logs = pd.DataFrame([{'ExerciseID': 999, 'Exercise': 'Old name'}])
        result = resolve_exercise_names(logs, self.master)
        self.assertEqual(result.iloc[0]['Exercise'], 'Unknown ExerciseID: 999')
        self.assertEqual(len(result), 1)

    def test_normalized_duplicate_master_ids_are_rejected(self):
        duplicate = pd.concat([self.master, pd.DataFrame([
            {'exercise_id': '27.0', 'exercise_name': 'Duplicate'}])], ignore_index=True)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            resolve_exercise_names(pd.DataFrame(), duplicate)

    def test_formula_tracks_current_row_and_actual_header_positions(self):
        formula = exercise_name_formula(HEADERS, ['exercise_id', 'target', 'exercise_name'])
        self.assertIn('INDEX($C:$C,ROW())', formula)
        self.assertIn("INDEX('Exercise Master'!$C:$C", formula)
        self.assertIn("'Exercise Master'!$A:$A,0)", formula)
        reordered = exercise_name_formula(['ExerciseID', 'Exercise'], ['exercise_name', 'exercise_id'])
        self.assertIn('INDEX($A:$A,ROW())', reordered)
        self.assertIn("INDEX('Exercise Master'!$A:$A", reordered)
        self.assertIn("'Exercise Master'!$B:$B,0)", reordered)


class HistoryUpdateTests(unittest.TestCase):
    def test_updates_preserve_formulas_and_delete_bottom_up(self):
        row = {'ID': 1, 'ExerciseID': 27, 'Exercise': 'Computed name',
               'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': 'Main', 'Memo': ''}
        edits = {1: {field: row[field] for field in ['Weight', 'Unit', 'Reps', 'RPE', 'Set Type', 'Memo']}}
        edits[1]['Weight'] = 40
        edits[1]['Memo'] = '=literal note'
        rows = [row, dict(row, ID=2), dict(row, ID=3), dict(row, ID=4)]
        requests = history_update_requests(123, HEADERS, rows, edits, [2, 4])
        cells = [r['updateCells'] for r in requests if 'updateCells' in r]
        self.assertEqual([r['range']['startColumnIndex'] for r in cells], [5, 10])
        self.assertEqual(cells[0]['rows'][0]['values'][0]['userEnteredValue'], {'numberValue': 40.0})
        self.assertEqual(cells[1]['rows'][0]['values'][0]['userEnteredValue'], {'stringValue': '=literal note'})
        self.assertEqual([r['deleteDimension']['range']['startIndex'] for r in requests if 'deleteDimension' in r], [4, 2])
        self.assertTrue(all(r['range']['sheetId'] == 123 for r in cells))

    def test_unchanged_values_do_not_overwrite_cells(self):
        row = {'ID': 1, 'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': '', 'Memo': ''}
        self.assertEqual(history_update_requests(1, HEADERS, [row], {1: dict(row)}, []), [])


class DataPreparationTests(unittest.TestCase):
    def test_analysis_columns_are_shared_without_changing_source_rows(self):
        master = pd.DataFrame([{'exercise_id': 27, 'exercise_name': 'Seated Row'}])
        log = pd.DataFrame([{
            'ID': '1', 'Date': '2026/01/01', 'ExerciseID': '27.0',
            'Exercise': 'Old name', 'Weight': '100', 'Unit': 'lbs', 'Reps': '10',
        }])
        prepared = prepare_log(log, master)
        self.assertEqual(prepared.iloc[0]['Exercise'], 'Seated Row')
        self.assertAlmostEqual(prepared.iloc[0]['Weight (kg)'], 45.3592)
        self.assertAlmostEqual(prepared.iloc[0]['Estimated 1RM (kg)'], 45.3592 * 4 / 3)
        self.assertEqual(prepared.iloc[0]['Date'], pd.Timestamp('2026-01-01'))
        self.assertEqual(log.iloc[0]['Weight'], '100')
        self.assertNotIn('Estimated 1RM (kg)', log)

    def test_template_ids_preserve_order_and_support_old_separator(self):
        exercises = {'27': {}, '52': {}}
        for value in ['52|27.0|999', ' 52 ,27.0,999']:
            with self.subTest(value=value):
                self.assertEqual(template_exercises(value, exercises), ['52', '27'])
        self.assertEqual(template_exercises(None, exercises), [])
        self.assertEqual(template_exercises('', exercises), [])

    def test_template_number_does_not_depend_on_sheet_order(self):
        self.assertEqual(next_template_id([]), 'TMP001')
        self.assertEqual(next_template_id(['TMP009', 'TMP002', 'other']), 'TMP010')


if __name__ == '__main__':
    unittest.main()
