"""Workout calculations and sheet request builders, without UI or network access."""

import math
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
    result["ID"] = result["ID"].map(normalize_id)
    result["_Row"] = range(len(result))
    for field in ("Date", "Weight", "Reps"):
        result[f"Original {field}"] = result[field]
    # A bare number is not a workout date (pandas would otherwise treat it as Unix time).
    dates = result["Date"].where(~result["Date"].map(lambda value: isinstance(value, Real)))
    result["Date"] = pd.to_datetime(dates, format="mixed", errors="coerce")
    for field in ("Weight", "Reps"):
        values = pd.to_numeric(result[field], errors="coerce")
        result[field] = values.where(values.map(lambda value: pd.notna(value) and math.isfinite(value)))
    issues = [[] for _ in range(len(result))]
    invalid = {field: result[field].isna() for field in ("Date", "Weight", "Reps")}
    invalid["Reps"] |= result["Reps"].lt(0) | result["Reps"].mod(1).ne(0)
    invalid["ID"] = result["ID"].eq("") | result["ID"].duplicated(keep=False)
    for field, mask in invalid.items():
        for index, bad in enumerate(mask):
            if bad:
                issues[index].append(field)
    result["Data Issues"] = issues
    units = result.get("Unit", pd.Series("kg", index=result.index))
    is_lbs = units.astype(str).str.lower().eq("lbs")
    result["Weight (kg)"] = result["Weight"].where(~is_lbs, result["Weight"] * 0.453592)
    result["Estimated 1RM (kg)"] = result["Weight (kg)"] * (1 + result["Reps"] / 30)
    return result


def valid_log_rows(log):
    return log[log["Data Issues"].map(len).eq(0)] if not log.empty else log


def latest_exercise_record(log, exercise_id):
    if log.empty:
        return {}
    records = exercise_records(valid_log_rows(log), exercise_id)
    # Negative assistance weights cannot be used as a non-negative form default.
    records = records[records["Weight"].ge(0)]
    if records.empty:
        return {}
    return records.sort_values(["Date", "_Row"], kind="stable").iloc[-1].to_dict()


def set_comparison(log, exercise_id, date):
    columns = ["Set", "Previous", "Today"]
    if log.empty:
        return pd.DataFrame(columns=columns)
    records = exercise_records(valid_log_rows(log), exercise_id).sort_values("_Row")
    days = records["Date"].dt.normalize()
    selected_day = pd.Timestamp(date).normalize()
    previous_day = days[days < selected_day].max()
    def labels(mask):
        return [
            f"{row['Weight']:.1f} {row['Unit']} × {int(row['Reps'])}"
            for row in records[mask].to_dict("records")
        ]
    previous, today = labels(days == previous_day), labels(days == selected_day)
    count = max(len(previous), len(today))
    comparison = pd.DataFrame({
        "Set": range(1, count + 1),
        "Previous": previous + ["—"] * (count - len(previous)),
        "Today": today + ["—"] * (count - len(today)),
    })
    comparison.attrs["previous_date"] = previous_day.strftime("%Y/%m/%d") if pd.notna(previous_day) else None
    return comparison


def analysis_records(log, exercise_id, months=None, include_warmups=True):
    if log.empty:
        return log.copy()
    records = exercise_records(valid_log_rows(log), exercise_id).sort_values(["Date", "_Row"])
    if months and not records.empty:
        cutoff = records["Date"].max() - pd.DateOffset(months=months)
        records = records[records["Date"] >= cutoff]
    if not include_warmups and "Set Type" in records:
        records = records[records["Set Type"].fillna("").ne("Up")]
    return records.copy()


def daily_progress(records, column="Estimated 1RM (kg)", aggregation="max"):
    if records.empty:
        return pd.DataFrame(columns=["Date", column])
    return records.groupby(records["Date"].dt.normalize())[column].agg(aggregation).reset_index()


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
IDENTITY_FIELDS = ("Date", "ExerciseID", "Target")


def comparable_value(value, field):
    if pd.isna(value) or value == "":
        return ""
    if field == "ExerciseID":
        return normalize_id(value)
    if field in ("Weight", "Reps", "RPE"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value)
    if field == "Date":
        try:
            return pd.Timestamp(value)
        except (TypeError, ValueError):
            return str(value)
    return value


def index_log_rows(rows):
    indexed = {}
    for row in rows:
        key = normalize_id(row.get("ID"))
        if not key or key in indexed:
            raise ValueError("Blank or duplicate record ID. Correct Training Log and Reload.")
        indexed[key] = row
    return indexed


def collect_history_changes(original_rows, edited_rows):
    originals = index_log_rows(original_rows)
    edits, deleted_ids = {}, []
    for row in edited_rows:
        key = normalize_id(row["ID"])
        if row.get("Delete", False):
            deleted_ids.append(key)
            continue
        changes = {
            field: row.get(field, "") for field in EDITABLE_LOG_FIELDS
            if comparable_value(row.get(field, ""), field)
            != comparable_value(originals[key].get(field, ""), field)
        }
        if changes:
            edits[key] = changes
    return edits, deleted_ids


def history_update_requests(sheet_id, headers, current_rows, edits, deleted_ids, original_rows):
    """Update only editable cells; retain lookup formulas and all other columns.

    One Sheets batch applies cell edits before deleting rows from bottom to top.
    Row indexes come from the freshly read sheet, not a cached dataframe.
    """
    deleted_ids = {normalize_id(value) for value in deleted_ids}
    edits = {normalize_id(key): value for key, value in edits.items()}
    current = index_log_rows(current_rows)
    originals = index_log_rows(original_rows)
    # Validate the whole operation before building or sending any write requests.
    for key in set(edits) | deleted_ids:
        if key not in current or key not in originals:
            raise ValueError(f"Record {key} no longer exists. Reload before saving.")
        fields = set(IDENTITY_FIELDS) | (set(EDITABLE_LOG_FIELDS) if key in deleted_ids else set(edits[key]))
        for field in fields:
            before = originals[key].get(f"Original {field}", originals[key].get(field, ""))
            now = current[key].get(field, "")
            if comparable_value(before, field) != comparable_value(now, field):
                raise ValueError(f"Record {key}: {field} changed in another view. Reload before saving.")
    requests, delete_indexes = [], []
    for row_index, row in enumerate(current_rows, 1):
        key = normalize_id(row.get("ID"))
        if key in deleted_ids:
            delete_indexes.append(row_index)
            continue
        if key not in edits:
            continue
        for field, value in edits[key].items():
            if field not in EDITABLE_LOG_FIELDS:
                raise ValueError(f"Field {field} cannot be edited.")
            if pd.isna(value):
                value = ""
            old_value = row.get(field, "")
            if comparable_value(value, field) == comparable_value(old_value, field):
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
