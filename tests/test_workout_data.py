import unittest

import pandas as pd

from workout_data import (
    analysis_records, collect_history_changes, daily_progress,
    exercise_name_formula, exercise_records, history_update_requests,
    latest_exercise_record, next_template_id, prepare_log, resolve_exercise_names,
    set_comparison, template_exercises,
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
        requests = history_update_requests(123, HEADERS, rows, edits, [2, 4], rows)
        cells = [r['updateCells'] for r in requests if 'updateCells' in r]
        self.assertEqual([r['range']['startColumnIndex'] for r in cells], [5, 10])
        self.assertEqual(cells[0]['rows'][0]['values'][0]['userEnteredValue'], {'numberValue': 40.0})
        self.assertEqual(cells[1]['rows'][0]['values'][0]['userEnteredValue'], {'stringValue': '=literal note'})
        self.assertEqual([r['deleteDimension']['range']['startIndex'] for r in requests if 'deleteDimension' in r], [4, 2])
        self.assertTrue(all(r['range']['sheetId'] == 123 for r in cells))

    def test_unchanged_values_do_not_overwrite_cells(self):
        row = {'ID': 1, 'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': '', 'Memo': ''}
        edits = {1: {field: row[field] for field in ['Weight', 'Unit', 'Reps', 'RPE', 'Set Type', 'Memo']}}
        self.assertEqual(history_update_requests(1, HEADERS, [row], edits, [], [row]), [])

    def test_only_changed_fields_are_collected_and_submitted(self):
        baseline = {'ID': 'legacy-1', 'Date': '2026/01/01', 'ExerciseID': '27', 'Target': '',
                   'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': '', 'Memo': ''}
        edited = dict(baseline, Weight=35, Memo='new note')
        edits, deleted = collect_history_changes([baseline], [edited])
        self.assertEqual(edits, {'legacy-1': {'Weight': 35, 'Memo': 'new note'}})
        self.assertEqual(deleted, [])
        requests = history_update_requests(123, HEADERS, [baseline], edits, deleted, [baseline])
        cells = [r['updateCells']['range']['startColumnIndex'] for r in requests if 'updateCells' in r]
        self.assertEqual(cells, [5, 10])

    def test_edit_conflict_in_same_field_aborts_without_requests(self):
        baseline = {'ID': 'legacy-1', 'Date': '2026/01/01', 'ExerciseID': '27', 'Target': '',
                   'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': '', 'Memo': ''}
        current = dict(baseline, Weight=32)
        edits = {'legacy-1': {'Weight': 35}}
        with self.assertRaisesRegex(ValueError, 'Reload'):
            history_update_requests(123, HEADERS, [current], edits, [], [baseline])

    def test_other_field_change_does_not_conflict_and_delete_checks_all_fields(self):
        baseline = {'ID': 'legacy-1', 'Date': '2026/01/01', 'ExerciseID': '27', 'Target': '',
                   'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': '', 'Memo': ''}
        current = dict(baseline, Memo='concurrent memo')
        requests = history_update_requests(123, HEADERS, [current], {'legacy-1': {'Weight': 35}}, [], [baseline])
        self.assertTrue(any('updateCells' in req for req in requests))
        with self.assertRaisesRegex(ValueError, 'Reload'):
            history_update_requests(123, HEADERS, [current], {}, ['legacy-1'], [baseline])

    def test_duplicate_or_missing_baseline_ids_are_rejected(self):
        row = {'ID': 'legacy-1', 'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': '', 'Memo': ''}
        with self.assertRaises(ValueError):
            history_update_requests(1, HEADERS, [row, dict(row)], {}, [], [row])
        with self.assertRaises(ValueError):
            history_update_requests(1, HEADERS, [row], {'missing': {'Weight': 31}}, [], [row])

    def test_prepared_baseline_raw_values_compare_to_current_sheet_values(self):
        master = pd.DataFrame([{'exercise_id': 27, 'exercise_name': 'Row'}])
        raw = pd.DataFrame([{
            'ID': 17, 'Date': '2026/01/01', 'ExerciseID': '27.0', 'Target': '',
            'Exercise': 'Row', 'Weight': '30.00', 'Unit': 'kg', 'Reps': '10',
            'RPE': '', 'Set Type': '', 'Memo': '',
        }])
        prepared = prepare_log(raw, master).to_dict('records')
        edits = {'17': {'Weight': 35}}
        requests = history_update_requests(1, HEADERS, raw.to_dict('records'), edits, [], prepared)
        self.assertEqual(len(requests), 1)

        for field, value, edit in (
            ('Date', '2026/01/02', '2026/01/03'),
            ('Weight', '31', 35),
            ('Reps', '11', 12),
        ):
            with self.subTest(field=field):
                changed = raw.copy()
                changed.loc[0, field] = value
                with self.assertRaisesRegex(ValueError, 'Reload'):
                    history_update_requests(
                        1, HEADERS, changed.to_dict('records'), {'17': {field: edit}}, [], prepared,
                    )

    def test_memo_only_edit_does_not_restore_stale_weight(self):
        baseline = {'ID': 'uuid', 'Date': '2026/01/01', 'ExerciseID': '27', 'Target': '',
                    'Weight': 80, 'Unit': 'kg', 'Reps': 8, 'RPE': '', 'Set Type': '', 'Memo': ''}
        current = dict(baseline, Weight=85)
        edits, deleted = collect_history_changes([baseline], [dict(baseline, Memo='note')])
        requests = history_update_requests(1, HEADERS, [current], edits, deleted, [baseline])
        cells = [request['updateCells'] for request in requests if 'updateCells' in request]
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]['range']['startColumnIndex'], HEADERS.index('Memo'))
        self.assertEqual(cells[0]['rows'][0]['values'][0]['userEnteredValue'], {'stringValue': 'note'})

    def test_missing_or_duplicate_current_rows_fail_before_any_request_is_built(self):
        row = {'ID': 'x', 'Date': '2026/01/01', 'ExerciseID': '27', 'Target': '',
               'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': '', 'Memo': ''}
        for current in ([], [row, dict(row)]):
            with self.subTest(current=current):
                with self.assertRaises(ValueError):
                    history_update_requests(1, HEADERS, current, {'x': {'Weight': 35}}, [], [row])

    def test_deletion_detects_date_change_in_fresh_sheet(self):
        baseline = {'ID': 'uuid', 'Date': '2026/01/01', 'ExerciseID': '27', 'Target': '',
                    'Weight': 30, 'Unit': 'kg', 'Reps': 10, 'RPE': '', 'Set Type': '', 'Memo': ''}
        current = dict(baseline, Date='2026/01/02')
        with self.assertRaisesRegex(ValueError, 'Reload'):
            history_update_requests(1, HEADERS, [current], {}, ['uuid'], [baseline])


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

    def test_invalid_source_values_are_retained_and_reported(self):
        master = pd.DataFrame([{'exercise_id': 27, 'exercise_name': 'Seated Row'}])
        log = pd.DataFrame([{
            'ID': 'a1', 'Date': 'not-a-date', 'ExerciseID': '27', 'Target': '',
            'Exercise': 'Stale name', 'Weight': 'heavy', 'Unit': 'kg', 'Reps': 'many',
        }])
        prepared = prepare_log(log, master)
        result = prepared.iloc[0]
        self.assertTrue(pd.isna(result['Date']))
        self.assertTrue(pd.isna(result['Weight']))
        self.assertTrue(pd.isna(result['Reps']))
        self.assertEqual(result['Original Date'], 'not-a-date')
        self.assertEqual(result['Original Weight'], 'heavy')
        self.assertEqual(result['Original Reps'], 'many')
        self.assertEqual(set(result['Data Issues']), {'Date', 'Weight', 'Reps'})
        self.assertEqual(result['_Row'], 0)
        self.assertEqual(result['ID'], 'a1')

    def test_latest_record_uses_date_then_sheet_order_and_skips_invalid_rows(self):
        logs = pd.DataFrame([
            {'ID': '8f-af', 'ExerciseID': '27', 'Date': '2026/01/05', 'Weight': '50', 'Reps': '8'},
            {'ID': '2b-bc', 'ExerciseID': 27, 'Date': '2026/01/05', 'Weight': '55', 'Reps': '8'},
            {'ID': '7', 'ExerciseID': '27.0', 'Date': '2026/01/06', 'Weight': 'bad', 'Reps': '8'},
            {'ID': '9', 'ExerciseID': '27', 'Date': '2026/01/04', 'Weight': '80', 'Reps': '1'},
        ])
        latest = latest_exercise_record(prepare_log(logs, pd.DataFrame([
            {'exercise_id': 27, 'exercise_name': 'Seated Row'}])), 27)
        self.assertEqual(latest['ID'], '2b-bc')
        self.assertEqual(latest['Weight'], 55)

    def test_latest_record_returns_empty_when_no_valid_candidate(self):
        logs = pd.DataFrame([{'ID': 'x', 'ExerciseID': 27, 'Date': 'bad', 'Weight': '50', 'Reps': '8'}])
        master = pd.DataFrame([{'exercise_id': 27, 'exercise_name': 'Seated Row'}])
        self.assertEqual(latest_exercise_record(prepare_log(logs, master), 27), {})

    def test_mixed_uuid_and_numeric_ids_are_normalized_and_unique(self):
        master = pd.DataFrame([{'exercise_id': 27, 'exercise_name': 'Row'}])
        logs = pd.DataFrame([
            {'ID': 17, 'Date': '2026/01/01', 'ExerciseID': 27, 'Weight': 30, 'Unit': 'kg', 'Reps': 8},
            {'ID': '8f923c1e-70be-40ca-aa43-d7c0f9b8c86e', 'Date': '2026/01/02',
             'ExerciseID': '27.0', 'Weight': '31', 'Unit': 'kg', 'Reps': '9'},
        ])
        prepared = prepare_log(logs, master)
        self.assertEqual(prepared['ID'].tolist(), ['17', '8f923c1e-70be-40ca-aa43-d7c0f9b8c86e'])
        self.assertEqual(prepared['Data Issues'].tolist(), [[], []])

    def test_mixed_date_formats_and_nonfinite_or_fractional_reps_are_flagged(self):
        master = pd.DataFrame([{'exercise_id': 27, 'exercise_name': 'Row'}])
        logs = pd.DataFrame([
            {'ID': 'a', 'Date': '2026/01/01', 'ExerciseID': 27, 'Weight': 'inf', 'Unit': 'kg', 'Reps': '8.5'},
            {'ID': 'b', 'Date': '2026-01-02', 'ExerciseID': 27, 'Weight': '20', 'Unit': 'kg', 'Reps': '8'},
        ])
        prepared = prepare_log(logs, master)
        self.assertEqual(prepared.iloc[0]['Data Issues'], ['Weight', 'Reps'])
        self.assertTrue(pd.isna(prepared.iloc[0]['Weight']))
        self.assertEqual(prepared.iloc[1]['Date'], pd.Timestamp('2026-01-02'))
        self.assertEqual(prepared.iloc[1]['Data Issues'], [])

    def test_same_date_latest_uses_greatest_original_sheet_row(self):
        master = pd.DataFrame([{'exercise_id': 27, 'exercise_name': 'Row'}])
        logs = pd.DataFrame([
            {'ID': 'later-row', 'Date': '2026/01/05', 'ExerciseID': 27, 'Weight': 40, 'Reps': 8},
            {'ID': 'earlier-row', 'Date': '2026/01/05', 'ExerciseID': 27, 'Weight': 45, 'Reps': 8},
        ])
        latest = latest_exercise_record(prepare_log(logs, master), 27)
        self.assertEqual(latest['ID'], 'earlier-row')

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


class ScreenDataTests(unittest.TestCase):
    def setUp(self):
        self.master = pd.DataFrame([{'exercise_id': 27, 'exercise_name': 'Row'}])

    def test_set_comparison_uses_prior_latest_day_and_same_day_input_order(self):
        log = prepare_log(pd.DataFrame([
            {'ID': 'old', 'Date': '2026/01/01', 'ExerciseID': 27, 'Weight': 90, 'Unit': 'kg',
             'Reps': 5, 'Set Type': 'Main'},
            {'ID': 'prev-1', 'Date': '2026/01/08', 'ExerciseID': 27, 'Weight': 55, 'Unit': 'kg',
             'Reps': 10, 'Set Type': 'Main'},
            {'ID': 'prev-2', 'Date': '2026/01/08', 'ExerciseID': 27, 'Weight': 60, 'Unit': 'kg',
             'Reps': 10, 'Set Type': 'Main'},
            {'ID': 'today-1', 'Date': '2026/01/10', 'ExerciseID': 27, 'Weight': 62.5, 'Unit': 'kg',
             'Reps': 8, 'Set Type': 'Main'},
            {'ID': 'today-2', 'Date': '2026/01/10', 'ExerciseID': 27, 'Weight': 65, 'Unit': 'kg',
             'Reps': 7, 'Set Type': 'Main'},
        ]), self.master)

        compared = set_comparison(log, 27, '2026-01-10')
        self.assertEqual(list(compared.columns), ['Set', 'Previous', 'Today'])
        self.assertEqual(compared['Previous'].tolist(), ['55.0 kg × 10', '60.0 kg × 10'])
        self.assertEqual(compared['Today'].tolist(), ['62.5 kg × 8', '65.0 kg × 7'])
        self.assertEqual(compared['Set'].tolist(), [1, 2])

    def test_set_comparison_uses_dash_for_missing_cell_and_empty_if_no_records(self):
        log = prepare_log(pd.DataFrame([
            {'ID': 'previous', 'Date': '2026/01/08', 'ExerciseID': 27, 'Weight': 55, 'Unit': 'kg',
             'Reps': 10, 'Set Type': 'Main'},
        ]), self.master)
        compared = set_comparison(log, 27, '2026-01-10')
        self.assertEqual(compared['Previous'].tolist(), ['55.0 kg × 10'])
        self.assertEqual(compared['Today'].tolist(), ['—'])
        self.assertEqual(set_comparison(log, 999, '2026-01-10').empty, True)
        self.assertEqual(set_comparison(log, 27, '2025-01-01').empty, True)

    def test_analysis_records_filters_invalids_period_and_optional_warmups(self):
        log = prepare_log(pd.DataFrame([
            {'ID': 'old', 'Date': '2025/10/01', 'ExerciseID': 27, 'Weight': 50, 'Unit': 'kg',
             'Reps': 8, 'Set Type': 'Main'},
            {'ID': 'warmup', 'Date': '2026/01/01', 'ExerciseID': 27, 'Weight': 20, 'Unit': 'kg',
             'Reps': 10, 'Set Type': 'Up'},
            {'ID': 'main', 'Date': '2026/01/01', 'ExerciseID': 27, 'Weight': 60, 'Unit': 'kg',
             'Reps': 8, 'Set Type': ''},
            {'ID': 'invalid', 'Date': '2026/01/02', 'ExerciseID': 27, 'Weight': 'bad', 'Unit': 'kg',
             'Reps': 8, 'Set Type': 'Main'},
            {'ID': 'recent', 'Date': '2026/04/01', 'ExerciseID': 27, 'Weight': 65, 'Unit': 'kg',
             'Reps': 8, 'Set Type': 'Main'},
        ]), self.master)

        recent = analysis_records(log, 27, months=3, include_warmups=False)
        self.assertEqual(recent['ID'].tolist(), ['main', 'recent'])
        all_rows = analysis_records(log, 27, months=None, include_warmups=True)
        self.assertEqual(all_rows['ID'].tolist(), ['old', 'warmup', 'main', 'recent'])
        self.assertEqual(all_rows['_Row'].tolist(), [0, 1, 2, 4])

    def test_daily_progress_aggregates_max_metrics_in_date_order(self):
        log = prepare_log(pd.DataFrame([
            {'ID': 'b2', 'Date': '2026/01/02', 'ExerciseID': 27, 'Weight': 60, 'Unit': 'kg', 'Reps': 6},
            {'ID': 'a1', 'Date': '2026/01/01', 'ExerciseID': 27, 'Weight': 50, 'Unit': 'kg', 'Reps': 8},
            {'ID': 'a2', 'Date': '2026/01/01', 'ExerciseID': 27, 'Weight': 55, 'Unit': 'kg', 'Reps': 7},
        ]), self.master)
        expected_dates = [pd.Timestamp('2026-01-01'), pd.Timestamp('2026-01-02')]
        for column, values in (
            ('Estimated 1RM (kg)', [55 * (1 + 7 / 30), 60 * (1 + 6 / 30)]),
            ('Reps', [8, 6]),
            ('Weight (kg)', [55, 60]),
        ):
            with self.subTest(column=column):
                result = daily_progress(log, column=column, aggregation='max')
                self.assertEqual(result['Date'].tolist(), expected_dates)
                self.assertEqual(result[column].tolist(), values)
        self.assertTrue(daily_progress(log.iloc[0:0], column='Reps').empty)


if __name__ == '__main__':
    unittest.main()
