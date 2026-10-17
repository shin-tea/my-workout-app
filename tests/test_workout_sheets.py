"""Persistence checks use an in-memory sheet; Google is never contacted."""

import unittest

import workout_sheets as sheets


class FakeSheet:
    def __init__(self, title, headers, rows=(), sheet_id=1):
        self.title = title
        self.id = sheet_id
        self.headers = list(headers)
        self.rows = [dict(row) for row in rows]
        self.updates = []
        self.appended = []

    def row_values(self, number):
        assert number == 1
        return list(self.headers)

    def get_all_records(self):
        return [dict(row) for row in self.rows]

    def update_cell(self, row, column, value):
        assert row == 1
        self.headers.insert(column - 1, value)

    def append_row(self, values, value_input_option):
        self.appended.append((values, value_input_option))
        if not self.headers:
            self.headers = list(values)
        else:
            self.rows.append(dict(zip(self.headers, values)))

    def batch_update(self, updates, value_input_option):
        self.updates.append((updates, value_input_option))


class FakeSpreadsheet:
    def __init__(self, *worksheets):
        self.sheets = {sheet.title: sheet for sheet in worksheets}
        self.requests = []

    def worksheets(self):
        return list(self.sheets.values())

    def worksheet(self, title):
        return self.sheets[title]

    def add_worksheet(self, title, rows, cols):
        sheet = FakeSheet(title, [])
        self.sheets[title] = sheet
        return sheet

    def batch_update(self, body):
        self.requests.append(body)


class PersistenceTests(unittest.TestCase):
    def test_new_log_stores_lookup_formula_in_actual_exercise_column(self):
        log = FakeSheet(sheets.TRAINING_LOG, ['ID', 'ExerciseID', 'Exercise', 'Weight'])
        master = FakeSheet(sheets.EXERCISE_MASTER, ['exercise_id', 'exercise_name'])
        spreadsheet = FakeSpreadsheet(log, master)
        record = {'ID': 1, 'ExerciseID': '27', 'Weight': 40}
        sheets.append_log(spreadsheet, record)
        values, mode = log.appended[0]
        self.assertEqual(values[:2], [1, '27'])
        self.assertTrue(values[2].startswith('=IF('))
        self.assertIn('INDEX($B:$B,ROW())', values[2])
        self.assertEqual(values[3], 40)
        self.assertEqual(mode, 'USER_ENTERED')
        self.assertNotIn('Exercise', record)

    def test_description_changes_only_the_matching_cell(self):
        master = FakeSheet(sheets.EXERCISE_MASTER, ['exercise_id', 'exercise_name', 'description'], [
            {'exercise_id': 52, 'exercise_name': 'Hammer Curl', 'description': ''},
            {'exercise_id': 27, 'exercise_name': 'Row', 'description': ''},
        ])
        sheets.save_description(FakeSpreadsheet(master), '27.0', '=literal note')
        self.assertEqual(master.updates, [([{'range': 'C3', 'values': [['=literal note']]}], 'RAW')])

    def test_template_create_and_edit_preserve_other_columns(self):
        template = FakeSheet(sheets.TEMPLATE_MASTER, sheets.TEMPLATE_HEADERS + ['extra'], [
            {'template_id': 'TMP009'}, {'template_id': 'TMP002'},
        ])
        spreadsheet = FakeSpreadsheet(template)
        record = {'template_name': 'Pull', 'exercise_ids': '27|52', 'created_at': '2026/10/17', 'memo': ''}
        sheets.save_template(spreadsheet, record)
        values, mode = template.appended[0]
        self.assertEqual(values, ['TMP010', 'Pull', '27|52', '2026/10/17', '', ''])
        self.assertEqual(mode, 'USER_ENTERED')
        sheets.save_template(spreadsheet, {'template_name': 'New name'}, 'TMP002')
        self.assertEqual(template.updates, [([{'range': 'B3', 'values': [['New name']]}], 'RAW')])

    def test_deleting_templates_uses_current_rows_and_one_batch(self):
        template = FakeSheet(sheets.TEMPLATE_MASTER, sheets.TEMPLATE_HEADERS, [
            {'template_id': 'TMP003'}, {'template_id': 'TMP001'}, {'template_id': 'TMP002'},
        ], sheet_id=42)
        spreadsheet = FakeSpreadsheet(template)
        sheets.delete_templates(spreadsheet, ['TMP003', 'TMP002'])
        requests = spreadsheet.requests[0]['requests']
        self.assertEqual([r['deleteDimension']['range']['startIndex'] for r in requests], [3, 1])
        self.assertTrue(all(r['deleteDimension']['range']['sheetId'] == 42 for r in requests))

    def test_loading_creates_template_headers_and_migrates_memo_once(self):
        spreadsheet = FakeSpreadsheet(
            FakeSheet(sheets.TRAINING_LOG, ['ID']),
            FakeSheet(sheets.EXERCISE_MASTER, ['exercise_id']),
            FakeSheet(sheets.CONSTANTS, ['Category']),
        )
        self.assertEqual(len(sheets.read_data(spreadsheet)), 4)
        template = spreadsheet.worksheet(sheets.TEMPLATE_MASTER)
        self.assertEqual(template.headers, sheets.TEMPLATE_HEADERS)
        sheets.read_data(spreadsheet)
        self.assertEqual(len(template.appended), 1)
        template.headers.remove('memo')
        sheets.read_data(spreadsheet)
        self.assertEqual(template.headers, sheets.TEMPLATE_HEADERS)

    def test_missing_record_reports_error_instead_of_overwriting_another_row(self):
        template = FakeSheet(sheets.TEMPLATE_MASTER, sheets.TEMPLATE_HEADERS, [{'template_id': 'TMP001'}])
        with self.assertRaisesRegex(ValueError, 'no longer exists'):
            sheets.save_template(FakeSpreadsheet(template), {'template_name': 'New'}, 'TMP002')
        self.assertEqual(template.updates, [])


if __name__ == '__main__':
    unittest.main()
