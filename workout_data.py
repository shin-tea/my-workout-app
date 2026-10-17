"""Workout calculations and sheet request builders, without UI or network access."""

from numbers import Real

import pandas as pd


def normalize_id(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def resolve_exercise_names(log, master):
    """Treat the master ID as authoritative, including for historical records."""
    if not {"exercise_id", "exercise_name"}.issubset(master.columns):
        raise ValueError("Exercise Master requires exercise_id and exercise_name columns.")
    keys = master["exercise_id"].map(normalize_id)
    if keys.eq("").any() or keys.duplicated().any():
        raise ValueError("Exercise Master contains blank or duplicate exercise IDs.")
    if master["exercise_name"].fillna("").astype(str).str.strip().eq("").any():
        raise ValueError("Exercise Master contains blank exercise names.")
    result = log.copy()
    if result.empty:
        return result
    if "ExerciseID" not in result.columns:
        raise ValueError("Training Log requires an ExerciseID column.")
    names = dict(zip(keys, master["exercise_name"]))
    log_keys = result["ExerciseID"].map(normalize_id)
    result["Exercise"] = log_keys.map(names).fillna("Unknown ExerciseID: " + log_keys)
    return result


def exercise_records(log, exercise_id):
    return log[log["ExerciseID"].map(normalize_id).eq(normalize_id(exercise_id))]


def prepare_log(log, master):
    """Prepare a single consistent dataframe for all three screens."""
    result = resolve_exercise_names(log, master)
    if result.empty:
        return result
    result["ID"] = pd.to_numeric(result["ID"], errors="coerce").fillna(0).astype(int)
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    for field in ("Weight", "Reps"):
        result[field] = pd.to_numeric(result[field], errors="coerce").fillna(0)
    is_lbs = result["Unit"].astype(str).str.lower().eq("lbs")
    result["Weight (kg)"] = result["Weight"].where(~is_lbs, result["Weight"] * 0.453592)
    result["Estimated 1RM (kg)"] = result["Weight (kg)"] * (1 + result["Reps"] / 30)
    return result


def template_exercise_ids(value):
    if pd.isna(value):
        return []
    return [normalize_id(part) for part in str(value).replace(",", "|").split("|") if part.strip()]


def template_exercises(value, exercises):
    """Preserve template order and skip IDs removed from the master."""
    return [key for key in template_exercise_ids(value) if key in exercises]


def next_template_id(existing_ids):
    numbers = [
        int(value[3:]) for value in map(str, existing_ids)
        if value.startswith("TMP") and value[3:].isdigit()
    ]
    return f"TMP{max(numbers, default=0) + 1:03d}"


def column_letter(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def exercise_name_formula(log_headers, master_headers):
    """ROW keeps the lookup correct when rows are appended or deleted."""
    log_id = column_letter(log_headers.index("ExerciseID") + 1)
    master_id = column_letter(master_headers.index("exercise_id") + 1)
    master_name = column_letter(master_headers.index("exercise_name") + 1)
    reference = f"INDEX(${log_id}:${log_id},ROW())"
    # IFERROR(VALUE(...),...) accepts numeric IDs stored as text as well.
    key = f"IFERROR(VALUE({reference}),{reference})"
    return (
        f'=IF({reference}="","",IFERROR('
        f"INDEX('Exercise Master'!${master_name}:${master_name},"
        f"MATCH({key},'Exercise Master'!${master_id}:${master_id},0)),"
        f'"Unknown ExerciseID: "&{reference}))'
    )


EDITABLE_LOG_FIELDS = ("Weight", "Unit", "Reps", "RPE", "Set Type", "Memo")


def history_update_requests(sheet_id, headers, current_rows, edits, deleted_ids):
    """Update only editable cells; retain lookup formulas and all other columns.

    One Sheets batch applies cell edits before deleting rows from bottom to top.
    Row indexes come from the freshly read sheet, not a cached dataframe.
    """
    deleted_ids = {normalize_id(value) for value in deleted_ids}
    edits = {normalize_id(key): value for key, value in edits.items()}
    requests, delete_indexes = [], []
    for row_index, row in enumerate(current_rows, 1):
        key = normalize_id(row.get("ID"))
        if key in deleted_ids:
            delete_indexes.append(row_index)
            continue
        if key not in edits:
            continue
        for field in EDITABLE_LOG_FIELDS:
            value = edits[key][field]
            if pd.isna(value):
                value = ""
            old_value = row.get(field, "")
            if value == ("" if old_value is None else old_value):
                continue
            if isinstance(value, Real):
                entered_value = {"numberValue": float(value)}
            else:
                entered_value = {"stringValue": str(value)}
            column_index = headers.index(field)
            requests.append({"updateCells": {
                "range": {"sheetId": sheet_id, "startRowIndex": row_index,
                          "endRowIndex": row_index + 1, "startColumnIndex": column_index,
                          "endColumnIndex": column_index + 1},
                "rows": [{"values": [{"userEnteredValue": entered_value}]}],
                "fields": "userEnteredValue",
            }})
    return requests + delete_row_requests(sheet_id, delete_indexes)


def delete_row_requests(sheet_id, row_indexes):
    """Delete zero-based sheet rows bottom-up so earlier indexes stay valid."""
    return [
        {"deleteDimension": {"range": {
            "sheetId": sheet_id, "dimension": "ROWS",
            "startIndex": row_index, "endIndex": row_index + 1,
        }}}
        for row_index in sorted(set(row_indexes), reverse=True)
    ]
