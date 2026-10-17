"""Read and write workout sheets. This module does not render UI."""

from functools import lru_cache, wraps
from threading import RLock
from uuid import uuid4

import pandas as pd

from workout_data import (
    column_letter,
    delete_row_requests,
    exercise_name_formula,
    history_update_requests,
    index_log_rows,
    is_uuid,
    next_template_id,
    normalize_id,
)

TRAINING_LOG = "Training Log"
EXERCISE_MASTER = "Exercise Master"
CONSTANTS = "Constants"
TEMPLATE_MASTER = "Template Master"
TEMPLATE_HEADERS = ["template_id", "template_name", "exercise_ids", "created_at", "memo"]
WRITE_LOCK = RLock()


def serialized_write(function):
    """Keep read/check/write sequences together across sessions in this server."""
    @wraps(function)
    def write(*args, **kwargs):
        with WRITE_LOCK:
            return function(*args, **kwargs)
    return write


def connect(settings):
    # Keep authentication dependencies out of offline data and persistence tests.
    import gspread
    from google.oauth2.service_account import Credentials

    credentials = {key: value for key, value in settings.items() if key != "spreadsheet"}
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    client = gspread.authorize(Credentials.from_service_account_info(credentials, scopes=scopes))
    return client.open_by_url(settings["spreadsheet"])


@lru_cache(maxsize=32)
def get_worksheet(spreadsheet, title):
    """Worksheet handles contain metadata; fetching their values stays uncached."""
    return spreadsheet.worksheet(title)


def clear_sheet_cache():
    get_worksheet.cache_clear()


def read_records(sheet):
    records = sheet.get_all_records()
    headers = list(records[0]) if records else sheet.row_values(1)
    return headers, records


def read_table(sheet):
    headers, records = read_records(sheet)
    frame = pd.DataFrame(records, columns=headers)
    frame.attrs["sheet_headers"] = headers
    return frame


def read_log(spreadsheet):
    return read_table(get_worksheet(spreadsheet, TRAINING_LOG))


def read_reference_data(spreadsheet):
    worksheets = {sheet.title: sheet for sheet in spreadsheet.worksheets()}
    templates = worksheets.get(TEMPLATE_MASTER)
    if templates is None:
        templates = spreadsheet.add_worksheet(title=TEMPLATE_MASTER, rows=100, cols=10)

    headers = templates.row_values(1)
    if not headers:
        templates.append_row(TEMPLATE_HEADERS, value_input_option="RAW")
    elif "memo" not in headers:
        templates.update_cell(1, len(headers) + 1, "memo")

    return tuple(read_table(sheet) for sheet in (
        worksheets[EXERCISE_MASTER], worksheets[CONSTANTS], templates,
    ))


def read_data(spreadsheet):
    """Read all four tables for offline callers; the UI caches them separately."""
    return (read_log(spreadsheet), *read_reference_data(spreadsheet))


@serialized_write
def append_log(spreadsheet, record, log_headers=None, master_headers=None):
    sheet = get_worksheet(spreadsheet, TRAINING_LOG)
    if log_headers is None:
        log_headers = sheet.row_values(1)
    if master_headers is None:
        master_headers = get_worksheet(spreadsheet, EXERCISE_MASTER).row_values(1)
    record = {**record, "ID": str(uuid4()), "Exercise": exercise_name_formula(log_headers, master_headers)}
    sheet.append_row([record.get(header, "") for header in log_headers], value_input_option="USER_ENTERED")


@serialized_write
def migrate_record_ids(spreadsheet):
    """Convert legacy record IDs once; preserve UUIDs and every other cell."""
    sheet = get_worksheet(spreadsheet, TRAINING_LOG)
    headers, rows = read_records(sheet)
    index_log_rows(rows)
    if not rows:
        return 0
    column = column_letter(headers.index("ID") + 1)
    updates = [
        {"range": f"{column}{row_number}", "values": [[str(uuid4())]]}
        for row_number, row in enumerate(rows, 2) if not is_uuid(row["ID"])
    ]
    if updates:
        sheet.batch_update(updates, value_input_option="RAW")
    return len(updates)


@serialized_write
def save_history(spreadsheet, edits, deleted_ids, original_rows):
    sheet = get_worksheet(spreadsheet, TRAINING_LOG)
    headers, current_rows = read_records(sheet)
    requests = history_update_requests(
        sheet.id, headers, current_rows, edits, deleted_ids, original_rows
    )
    if requests:
        spreadsheet.batch_update({"requests": requests})


@serialized_write
def update_record(sheet, key_column, record_id, changes):
    """Read current row positions and update only the requested cells."""
    headers, records = read_records(sheet)
    for row_number, row in enumerate(records, 2):
        if normalize_id(row[key_column]) == normalize_id(record_id):
            updates = [
                {"range": f"{column_letter(headers.index(field) + 1)}{row_number}",
                 "values": [[value]]}
                for field, value in changes.items()
            ]
            sheet.batch_update(updates, value_input_option="RAW")
            return
    raise ValueError(f"Record {record_id} no longer exists. Reload and try again.")


def save_description(spreadsheet, exercise_id, description):
    update_record(
        get_worksheet(spreadsheet, EXERCISE_MASTER), "exercise_id", exercise_id,
        {"description": description},
    )


@serialized_write
def save_template(spreadsheet, record, template_id=None):
    sheet = get_worksheet(spreadsheet, TEMPLATE_MASTER)
    if template_id is not None:
        update_record(sheet, "template_id", template_id, record)
        return
    headers, records = read_records(sheet)
    record = {**record, "template_id": next_template_id(row["template_id"] for row in records)}
    sheet.append_row(
        [record.get(header, "") for header in headers], value_input_option="USER_ENTERED"
    )


@serialized_write
def delete_templates(spreadsheet, template_ids):
    sheet = get_worksheet(spreadsheet, TEMPLATE_MASTER)
    selected = {normalize_id(value) for value in template_ids}
    indexes = [
        index for index, row in enumerate(sheet.get_all_records(), 1)
        if normalize_id(row["template_id"]) in selected
    ]
    requests = delete_row_requests(sheet.id, indexes)
    if requests:
        spreadsheet.batch_update({"requests": requests})
