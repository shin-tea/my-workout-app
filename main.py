"""Streamlit screens for recording workouts and reviewing progress."""

import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import workout_sheets as sheets
from workout_data import (
    collect_history_changes,
    exercise_records,
    latest_exercise_record,
    is_uuid,
    normalize_id,
    prepare_log,
    template_exercises,
    valid_log_rows,
)

NO_TEMPLATE = "Select from Exercises"
MOBILE_FORM_CSS = """
<style>
@media (max-width: 600px) {
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"] {
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 0.5rem !important;
    }
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        width: auto !important;
        flex: 1 1 0% !important;
        min-width: 0 !important;
    }
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"] * {
        min-width: 0 !important;
    }
    div[data-testid="stNumberInput"] button {
        min-width: 2.5rem !important;
        width: 2.5rem !important;
    }
}
</style>
"""


@st.cache_resource
def init_connection():
    return sheets.connect(dict(st.secrets["connections"]["gsheets"]))


@st.cache_data(ttl=3600)
def load_data(_spreadsheet):
    return sheets.read_data(_spreadsheet)


def save_changes(action, message, reset_keys=()):
    """Share error handling and show success after reloading fresh sheet data."""
    try:
        action()
    except Exception as error:
        st.error(f"Save failed: {error}")
        return
    for key in reset_keys:
        st.session_state.pop(key, None)
    reset_history()
    st.session_state["success_msg"] = message
    st.cache_data.clear()
    st.rerun()


def reset_history():
    for key in list(st.session_state):
        if key.startswith(("history_original_", "editor_")):
            st.session_state.pop(key)


def exercise_label(exercises, exercise_id):
    return exercises[exercise_id]["exercise_name"]


def muscle_options(exercises):
    return ["All"] + sorted({
        row["target_muscle_group"] for row in exercises.values()
        if pd.notna(row.get("target_muscle_group"))
    })


def filtered_exercises(exercises, muscle):
    return [
        key for key, row in exercises.items()
        if muscle == "All" or row.get("target_muscle_group") == muscle
    ]


def select_log_exercise(exercises, templates):
    template_map = {row["template_id"]: row for row in templates.to_dict("records")}
    template_col, muscle_col, exercise_col = st.columns(3)
    with template_col:
        template_id = st.selectbox(
            "Use Template", [None] + list(template_map), key="template_selector",
            format_func=lambda key: NO_TEMPLATE if key is None else template_map[key]["template_name"],
        )
    label = lambda key: exercise_label(exercises, key)
    if template_id is not None:
        template = template_map[template_id]
        options = template_exercises(template["exercise_ids"], exercises)
        with muscle_col:
            st.markdown(f"**Exercises in Template:** {len(options)}")
        with exercise_col:
            selected = st.selectbox(
                "Exercise (Template Order)", options, format_func=label,
                key=f"log_template_exercise_{template_id}",
            )
        if not options:
            st.warning("No exercises found in template")
        if template.get("memo"):
            st.info(f"**Memo**\n\n{template['memo']}")
        return selected
    with muscle_col:
        muscle = st.selectbox("Filter Muscle", muscle_options(exercises), key="log_muscle_filter")
    with exercise_col:
        return st.selectbox(
            "Exercise", filtered_exercises(exercises, muscle),
            format_func=label, key="log_ex_select_normal",
        )


def render_log(log, exercises, templates, units, set_types, spreadsheet):
    st.markdown("### Log")
    exercise_id = select_log_exercise(exercises, templates)
    if exercise_id is None:
        return None
    exercise = exercises[exercise_id]
    previous = latest_exercise_record(log, exercise_id)
    default_unit = previous.get("Unit", "kg")
    unit_index = units.index(default_unit) if default_unit in units else 0

    with st.form("log_form"):
        date = st.date_input("Date", datetime.date.today(), format="YYYY/MM/DD")
        weight_col, unit_col = st.columns([2, 1])
        with weight_col:
            weight = st.number_input(
                "Weight", min_value=0.0, step=2.5, format="%.1f",
                value=float(previous.get("Weight", 0)), key=f"weight_{exercise_id}",
            )
        with unit_col:
            unit = st.selectbox("Unit", units, index=unit_index, key=f"unit_{exercise_id}")
        reps_col, rpe_col, type_col = st.columns([1, 1, 1.5])
        with reps_col:
            reps = st.number_input(
                "Reps", min_value=0, step=1, value=int(previous.get("Reps", 10)),
                key=f"reps_{exercise_id}",
            )
        with rpe_col:
            rpe = st.number_input(
                "RPE", min_value=1.0, max_value=10.0, step=0.5, value=None,
                key=f"rpe_{exercise_id}",
            )
        with type_col:
            set_type = st.selectbox(
                "Set Type", set_types, index=set_types.index("Main") if "Main" in set_types else 0,
                key=f"set_type_{exercise_id}",
            )
        memo = st.text_input("Memo", key=f"memo_{exercise_id}")
        submitted = st.form_submit_button("Add Log", type="primary")

    if submitted:
        record = {
            "Date": date.strftime("%Y/%m/%d"),
            "ExerciseID": exercise_id,
            "Target": exercise.get("target_muscle_group", ""),
            "Weight": float(weight), "Unit": unit, "Reps": int(reps),
            "RPE": float(rpe) if rpe is not None else "", "Set Type": set_type, "Memo": memo,
        }
        save_changes(
            lambda: sheets.append_log(spreadsheet, record),
            f"Added: {exercise['exercise_name']} ({weight}{unit} x {reps})",
            reset_keys=[f"{field}_{exercise_id}" for field in ("weight", "unit", "reps")],
        )
    return exercise_id


def render_analysis(log, exercise_id, exercises, spreadsheet):
    st.divider()
    st.markdown("### Analysis")
    if log.empty:
        st.info("No training data available yet.")
        return
    if exercise_id is None:
        return
    records = exercise_records(valid_log_rows(log), exercise_id).sort_values(["Date", "_Row"]).copy()
    if records.empty:
        st.info("No valid records for this exercise.")
        return
    exercise = exercises[exercise_id]
    records["Set Order"] = records.groupby("Date").cumcount() + 1
    figure = px.scatter(
        records, x="Date", y="Weight (kg)", size="Reps", color="Estimated 1RM (kg)",
        title=f"{exercise['exercise_name']} - Performance Analysis",
        custom_data=["Set Order", "Reps", "Weight (kg)", "RPE", "Memo", "Estimated 1RM (kg)"],
    )
    figure.update_traces(
        marker=dict(line=dict(width=1, color="DarkSlateGrey"), sizeref=0.5, sizemin=8),
        hovertemplate=(
            "<b>%{x|%Y/%m/%d}</b><br>"
            "Weight:&nbsp;%{customdata[2]:.1f} kg<br>"
            "Reps:&nbsp;&nbsp;&nbsp;%{customdata[1]}<br>"
            "Set #:&nbsp;&nbsp;%{customdata[0]}<br>"
            "RPE:&nbsp;&nbsp;&nbsp;&nbsp;%{customdata[3]}<br>"
            "1RM:&nbsp;&nbsp;&nbsp;&nbsp;%{customdata[5]:.1f} kg<br>"
            "Memo:&nbsp;&nbsp;&nbsp;%{customdata[4]}<extra></extra>"
        ),
    )
    figure.update_layout(hovermode="closest", showlegend=False, coloraxis_showscale=False)
    st.plotly_chart(figure, width="stretch")
    best_col, weight_col, count_col = st.columns(3)
    best_col.metric("Personal Best (1RM)", f"{records['Estimated 1RM (kg)'].max():.1f} kg")
    weight_col.metric("Max Weight Lifted", f"{records['Weight (kg)'].max():.1f} kg")
    count_col.metric("Total Sets Logged", len(records))

    st.markdown("#### Recent Sets")
    recent_dates = sorted(records["Date"].dt.date.unique(), reverse=True)[:3]
    for date in recent_dates:
        st.markdown(f"**📅 {date:%Y/%m/%d}**")
        daily_records = records[records["Date"].dt.date == date]
        for number, row in enumerate(daily_records.to_dict("records"), 1):
            estimated = row["Estimated 1RM (kg)"]
            estimate_text = f" (1RM: {estimated:.1f} kg)" if estimated > 0 else ""
            st.markdown(
                f"&nbsp;&nbsp;&nbsp;&nbsp;**{number}.** "
                f"{row['Weight']:.1f} {row['Unit']} x {int(row['Reps'])}{estimate_text}"
            )
    render_notes(exercise_id, exercise, spreadsheet)


def render_notes(exercise_id, exercise, spreadsheet):
    st.divider()
    st.markdown("### Notes")
    muscle_col, equipment_col, category_col = st.columns(3)
    muscle_col.markdown(f"**Sub Muscle:** {exercise.get('sub_muscle_group', '-')}")
    equipment_col.markdown(f"**Equipment:** {exercise.get('equipment_type', '-')}")
    category_col.markdown(f"**Category:** {exercise.get('exercise_category', '-')}")
    description = exercise.get("description", "")
    description = "" if pd.isna(description) else str(description)
    description = st.text_area(
        "Description / Notes", value=description, height=100,
        key=f"analysis_desc_edit_{exercise_id}",
    )
    if st.button("Save Description", key="save_desc_analysis"):
        save_changes(
            lambda: sheets.save_description(spreadsheet, exercise_id, description),
            "Description updated!",
        )


def history_columns(units, set_types):
    return {
        "Delete": st.column_config.CheckboxColumn("❌", width="small", default=False),
        "ID": None, "ExerciseID": None, "Date": None, "Weight (kg)": None,
        "Original Date": None, "Original Weight": None, "Original Reps": None,
        "Data Issues": None, "_Row": None,
        "Exercise": st.column_config.TextColumn("Exercise", disabled=True),
        "Target": st.column_config.TextColumn("Target", disabled=True),
        "Weight": st.column_config.NumberColumn("Weight", format="%.1f"),
        "Unit": st.column_config.SelectboxColumn("Unit", options=units),
        "Reps": st.column_config.NumberColumn("Reps", step=1),
        "RPE": st.column_config.NumberColumn("RPE", min_value=1.0, max_value=10.0, step=0.5),
        "Set Type": st.column_config.SelectboxColumn("Set Type", options=set_types),
        "Memo": st.column_config.TextColumn("Memo"),
        "Estimated 1RM (kg)": st.column_config.NumberColumn("1RM", format="%.1f", disabled=True),
    }


def render_history(log, units, set_types, spreadsheet):
    st.markdown("### History")
    if log.empty:
        st.info("No data available.")
        return
    with st.expander("Record IDs", expanded=False):
        legacy_count = int((~log["ID"].map(is_uuid)).sum())
        if legacy_count:
            st.caption(
                f"{legacy_count} record ID(s) can be converted to UUIDs. "
                "Existing UUIDs, exercise IDs and workout values will be kept. "
                "Reload other open views after converting."
            )
            if st.button("Convert existing record IDs to UUIDs", key="migrate_record_ids"):
                save_changes(
                    lambda: sheets.migrate_record_ids(spreadsheet),
                    "Record IDs unified. Reload other open views before editing.",
                )
        else:
            st.caption("All record IDs use UUIDs.")
    log = valid_log_rows(log)
    if log.empty:
        st.info("No valid records to edit. Check the records needing correction above.")
        return
    months = log["Date"].dt.strftime("%Y/%m")
    available_months = sorted(months.dropna().unique(), reverse=True)
    if not available_months:
        st.warning("No valid dates. Check the Date column in Training Log.")
        return
    current_month = datetime.date.today().strftime("%Y/%m")
    month = st.selectbox(
        "Select Month", available_months,
        index=available_months.index(current_month) if current_month in available_months else 0,
    )
    monthly_log = log[months == month]
    summary = monthly_log.groupby(monthly_log["Date"].dt.date).size().reset_index(name="Sets")
    summary = summary.sort_values("Date", ascending=False)
    dates_col, details_col = st.columns([1, 2])
    with dates_col:
        st.markdown("#### Dates")
        st.caption("Max 3 dates.")
        event = st.dataframe(
            summary, on_select="rerun", selection_mode="multi-row", hide_index=True,
            column_config={
                "Date": st.column_config.DateColumn("Date", format="YYYY/MM/DD"),
                "Sets": st.column_config.NumberColumn("Sets"),
            },
        )
        selected_rows = event.selection.rows
        if len(selected_rows) > 3:
            st.warning("Max 3 dates allowed. Showing top 3 selected.")
        dates = sorted(summary.iloc[selected_rows[:3]]["Date"].tolist())
    with details_col:
        if not dates:
            return
        st.caption("Edit directly in the table, check 'Delete' to remove records, then save.")
        edited_frames = []
        original_frames = []
        for date in dates:
            st.markdown(f"#### 📅 {date:%Y/%m/%d}")
            snapshot_key = f"history_original_{date}"
            if snapshot_key not in st.session_state:
                daily_log = monthly_log[monthly_log["Date"].dt.date == date].sort_values("_Row").copy()
                daily_log.insert(0, "Delete", False)
                st.session_state[snapshot_key] = daily_log
            daily_log = st.session_state[snapshot_key]
            original_frames.append(daily_log)
            edited_frames.append(st.data_editor(
                daily_log, hide_index=True, column_config=history_columns(units, set_types),
                disabled=["Exercise", "Target", "ID", "ExerciseID", "Date",
                          "Estimated 1RM (kg)", "Weight (kg)", "Original Date",
                          "Original Weight", "Original Reps", "Data Issues", "_Row"],
                key=f"editor_{date}",
            ))
            st.divider()
        if st.button("💾 Apply Changes (Save Edits & Deletes)", type="primary"):
            originals = pd.concat(original_frames).to_dict("records")
            edited = pd.concat(edited_frames).to_dict("records")
            edits, deleted_ids = collect_history_changes(originals, edited)
            if not edits and not deleted_ids:
                st.info("No changes to save.")
                return
            save_changes(
                lambda: sheets.save_history(spreadsheet, edits, deleted_ids, originals),
                f"Changes applied! (Deleted {len(deleted_ids)}, Updated {len(edits)} records).",
            )


def render_template_form(exercises, spreadsheet, template=None):
    """Creation and editing use the same fields, filtering and validation."""
    editing = template is not None
    template = template if editing else {}
    template_id = template.get("template_id")
    prefix = f"edit_template_{template_id}" if editing else "new_template"
    name_col, muscle_col = st.columns(2)
    with name_col:
        name = st.text_input(
            "Template Name", value=template.get("template_name", ""),
            placeholder="e.g., Chest Day", key=f"{prefix}_name",
        )
    with muscle_col:
        muscle = st.selectbox(
            "Filter Exercises by Muscle", muscle_options(exercises), key=f"{prefix}_muscle"
        )
    existing = template_exercises(template.get("exercise_ids", ""), exercises)
    selected = st.session_state.get(f"{prefix}_exercises", existing)
    # Keep chosen exercises available when the muscle filter changes.
    options = list(dict.fromkeys(filtered_exercises(exercises, muscle) + selected + existing))
    exercise_ids = st.multiselect(
        "Select Exercises (Order is preserved)", options, default=existing,
        format_func=lambda key: exercise_label(exercises, key), key=f"{prefix}_exercises",
    )
    memo = st.text_area(
        "Template Memo", value=template.get("memo", ""), key=f"{prefix}_memo"
    )
    if not st.button("Update Template" if editing else "Save Template", type="primary", key=f"{prefix}_save"):
        return
    name = name.strip()
    if not name:
        st.error("Please enter a template name.")
        return
    if name.lower() == NO_TEMPLATE.lower():
        st.error("This template name is reserved. Please pick another.")
        return
    if not exercise_ids:
        st.error("Please select at least one exercise.")
        return
    record = {"template_name": name, "exercise_ids": "|".join(exercise_ids), "memo": memo}
    reset_keys = ()
    if not editing:
        record["created_at"] = datetime.date.today().strftime("%Y/%m/%d")
        reset_keys = [f"{prefix}_{field}" for field in ("name", "muscle", "exercises", "memo")]
    save_changes(
        lambda: sheets.save_template(spreadsheet, record, template_id),
        f"Template '{name}' {'updated' if editing else 'saved'}!", reset_keys,
    )


def render_templates(exercises, templates, spreadsheet):
    st.markdown("### Templates")
    with st.expander("Create New Template", expanded=templates.empty):
        render_template_form(exercises, spreadsheet)
    if not templates.empty:
        template_map = {row["template_id"]: row for row in templates.to_dict("records")}
        with st.expander("Edit Existing Template", expanded=False):
            template_id = st.selectbox(
                "Select Template", list(template_map),
                format_func=lambda key: template_map[key]["template_name"],
                key="edit_template_selector_tid",
            )
            render_template_form(exercises, spreadsheet, template_map[template_id])

    st.divider()
    st.markdown("### Saved")
    if templates.empty:
        st.info("No templates saved yet.")
        return
    display = templates.copy()
    display.insert(0, "Delete", False)
    display["Exercises"] = display["exercise_ids"].map(
        lambda value: ", ".join(exercise_label(exercises, key) for key in template_exercises(value, exercises))
    )
    edited = st.data_editor(
        display, hide_index=True, disabled=[column for column in display if column != "Delete"],
        column_config={
            "Delete": st.column_config.CheckboxColumn("❌", width="small", default=False),
            "template_id": st.column_config.TextColumn("ID"),
            "template_name": st.column_config.TextColumn("Template Name", width="medium"),
            "exercise_ids": None,
            "created_at": st.column_config.TextColumn("Created At"),
            "Exercises": st.column_config.TextColumn("Exercises", width="large"),
            "memo": st.column_config.TextColumn("Memo", width="medium"),
        },
        key="template_list_editor",
    )
    if st.button("🗑️ Delete Selected Templates", type="primary"):
        selected = edited.loc[edited["Delete"], "template_id"].tolist()
        if not selected:
            st.warning("No templates selected for deletion.")
            return
        save_changes(
            lambda: sheets.delete_templates(spreadsheet, selected),
            f"Deleted {len(selected)} template(s).",
        )


def main():
    st.set_page_config(page_title="Workout Tracker", layout="wide", page_icon="💪")
    title_col, reload_col = st.columns([5, 1])
    title_col.title("Workout Tracker")
    with reload_col:
        st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
        if st.button("Reload", use_container_width=True):
            reset_history()
            for key in list(st.session_state):
                if key.startswith(("weight_", "unit_", "reps_")):
                    st.session_state.pop(key)
            st.cache_data.clear()
            st.rerun()
    st.markdown(MOBILE_FORM_CSS, unsafe_allow_html=True)
    if message := st.session_state.pop("success_msg", None):
        st.success(message)
    try:
        spreadsheet = init_connection()
        log, master, constants, templates = load_data(spreadsheet)
        if master.empty or constants.empty:
            st.warning("Could not load Master or Constants data. Please check the spreadsheet.")
            return
        log = prepare_log(log, master)
        set_types = [""] + constants.loc[constants["Category"] == "SetType", "Value"].dropna().unique().tolist()
        units = constants.loc[constants["Category"] == "Unit", "Value"].dropna().unique().tolist()
        exercises = {
            normalize_id(row["exercise_id"]): row
            for row in master.sort_values("exercise_name", key=lambda names: names.str.lower()).to_dict("records")
        }
    except Exception as error:
        st.error(f"Failed to load workout data: {error}")
        return
    if not units:
        st.error("Constants sheet must contain at least one Unit.")
        return
    if not log.empty:
        unknown = log["Exercise"].str.startswith("Unknown ExerciseID: ").sum()
        if unknown:
            st.warning(f"{unknown} log(s) reference unknown exercise IDs. Check History & Edit.")
        problems = log[log["Data Issues"].map(len).gt(0)]
        if not problems.empty:
            st.warning(f"{len(problems)} record(s) need correction. These records are excluded from analysis and editable history.")
            with st.expander("Records needing correction", expanded=True):
                display = problems[["ID", "ExerciseID", "Exercise", "Original Date",
                                    "Original Weight", "Original Reps", "Data Issues"]].copy()
                display["Sheet Row"] = problems["_Row"] + 2
                display["Data Issues"] = display["Data Issues"].map(", ".join)
                # Text keeps malformed source values visible in a mixed-type table.
                st.dataframe(display.astype(str), hide_index=True)
                st.caption("Correct the listed values in Training Log, then click Reload. Original values are preserved.")
    log_tab, history_tab, templates_tab = st.tabs(["Log & Analysis", "History & Edit", "Templates"])
    with log_tab:
        exercise_id = render_log(log, exercises, templates, units, set_types, spreadsheet)
        render_analysis(log, exercise_id, exercises, spreadsheet)
    with history_tab:
        render_history(log, units, set_types, spreadsheet)
    with templates_tab:
        render_templates(exercises, templates, spreadsheet)


if __name__ == "__main__":
    main()
