import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import gspread
import time
from google.oauth2.service_account import Credentials

# --- Constants & Config ---
SHEET_TRAINING_LOG = "Training Log"
SHEET_EXERCISE_MASTER = "Exercise Master"
SHEET_CONSTANTS = "Constants"
SHEET_TEMPLATE_MASTER = "Template Master"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

st.set_page_config(page_title="Workout Tracker", layout="wide", page_icon="💪")

col_title, col_action = st.columns([5, 1])
with col_title:
    st.title("Workout Tracker")
with col_action:
    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    if st.button("Reload", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# --- Connection ---
@st.cache_resource
def init_connection():
    """Establish connection to Google Sheets using gspread."""
    try:
        secrets_dict = dict(st.secrets["connections"]["gsheets"])
        creds_dict = {k: v for k, v in secrets_dict.items() if k != "spreadsheet"}
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        spreadsheet_url = secrets_dict.get("spreadsheet")
        sh = client.open_by_url(spreadsheet_url)
        return sh
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        return None

sh = init_connection()

# --- Data Loading ---
@st.cache_data(ttl=3600)
def load_data():
    """Load all necessary sheets from GSheets."""
    if sh is None:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
    try:
        ws_log = sh.worksheet(SHEET_TRAINING_LOG)
        data_log = ws_log.get_all_records()
        df_log = pd.DataFrame(data_log)
        
        if 'ID' in df_log.columns:
            df_log['ID'] = pd.to_numeric(df_log['ID'], errors='coerce').fillna(0).astype(int)
        
        ws_master = sh.worksheet(SHEET_EXERCISE_MASTER)
        data_master = ws_master.get_all_records()
        df_master = pd.DataFrame(data_master)
        
        ws_constants = sh.worksheet(SHEET_CONSTANTS)
        data_constants = ws_constants.get_all_records()
        df_constants = pd.DataFrame(data_constants)
        
        try:
            ws_templates = sh.worksheet(SHEET_TEMPLATE_MASTER)
            data_templates = ws_templates.get_all_records()
            df_templates = pd.DataFrame(data_templates)
        except gspread.exceptions.WorksheetNotFound:
            ws_templates = sh.add_worksheet(title=SHEET_TEMPLATE_MASTER, rows=100, cols=10)
            headers = ["template_id", "template_name", "exercise_ids", "created_at"]
            ws_templates.append_row(headers, value_input_option='USER_ENTERED')
            df_templates = pd.DataFrame(columns=headers)
        
        return df_log, df_master, df_constants, df_templates
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_log, df_master, df_constants, df_templates = load_data()

if df_master.empty or df_constants.empty:
    if sh is not None:
        st.warning("Could not load Master or Constants data. Please check the spreadsheet.")
    st.stop()

# --- Pre-processing Mappings ---
try:
    set_types_raw = df_constants[df_constants['Category'] == 'SetType']['Value'].dropna().unique().tolist()
    set_types = [""] + set_types_raw
    units = df_constants[df_constants['Category'] == 'Unit']['Value'].dropna().unique().tolist()
except KeyError:
    st.error("Constants sheet missing required 'Category' or 'Value' columns.")
    st.stop()

if 'exercise_name' in df_master.columns:
    exercise_options = sorted(df_master['exercise_name'].dropna().unique().tolist(), key=lambda x: str(x).lower())
    exercise_map = df_master.set_index('exercise_name').to_dict('index')
else:
    st.error("Exercise Master sheet missing 'exercise_name' column.")
    st.stop()

template_options = ["Select from Exercises"]
template_map = {}
if not df_templates.empty and 'template_name' in df_templates.columns:
    for _, row in df_templates.iterrows():
        tname = row.get('template_name', '')
        if tname and tname.lower() != "select from exercises":
            template_options.append(tname)
            raw_ids = str(row.get('exercise_ids', ''))
            delim = '|' if '|' in raw_ids else ','
            template_map[tname] = raw_ids.split(delim) if raw_ids else []

def normalize_id(val):
    if pd.isna(val): return ""
    s = str(val).strip()
    if s.endswith('.0'):
        return s[:-2]
    return s

muscle_groups_input = sorted(df_master['target_muscle_group'].dropna().unique().tolist()) if 'target_muscle_group' in df_master.columns else []

# --- Main App ---
tab1, tab2, tab3 = st.tabs(["Log & Analysis", "History & Edit", "Templates"])

# === TAB 1: Log & Analysis ===
with tab1:
    st.markdown("### Log")
    
    if 'success_msg' in st.session_state and st.session_state['success_msg']:
        st.success(st.session_state['success_msg'])
        del st.session_state['success_msg']

    if 'last_template' not in st.session_state:
        st.session_state['last_template'] = template_options[0]
    if 'template_current_idx' not in st.session_state:
        st.session_state['template_current_idx'] = 0

    col_t, col_1, col_2 = st.columns(3)
    with col_t:
        selected_template_option = st.selectbox("Use Template", template_options, key="template_selector")

    if st.session_state['last_template'] != selected_template_option:
        st.session_state['template_current_idx'] = 0
        st.session_state['last_template'] = selected_template_option

    using_template = selected_template_option != "Select from Exercises"
    exercise_ids_in_template = template_map.get(selected_template_option, []) if using_template else []
    
    selected_exercise = None

    if using_template and exercise_ids_in_template:
        template_exercise_names = []
        for eid in exercise_ids_in_template:
            eid_str = normalize_id(eid)
            for ex_name, ex_info in exercise_map.items():
                if normalize_id(ex_info.get('exercise_id', '')) == eid_str:
                    template_exercise_names.append(ex_name)
                    break
        
        with col_1:
            if template_exercise_names:
                st.markdown(f"**Exercises in Template:** {len(template_exercise_names)}")
            else:
                st.warning("No exercises found in template")
        
        with col_2:
            if template_exercise_names:
                current_idx = st.session_state.get('template_current_idx', 0)
                if current_idx >= len(template_exercise_names):
                    current_idx = 0
                
                selected_exercise = st.selectbox(
                    "Exercise (Template Order)", 
                    template_exercise_names, 
                    index=current_idx,
                    key="log_ex_select_template"
                )
                if selected_exercise in template_exercise_names:
                    st.session_state['template_current_idx'] = template_exercise_names.index(selected_exercise)
    else:
        with col_1:
            selected_muscle_input = st.selectbox("Filter Muscle", ["All"] + muscle_groups_input, key="log_muscle_filter")
        with col_2:
            filtered_options = exercise_options
            if selected_muscle_input != "All":
                filtered_options = [ex for ex in exercise_options if exercise_map.get(ex, {}).get('target_muscle_group') == selected_muscle_input]
            selected_exercise = st.selectbox("Exercise", filtered_options, key="log_ex_select_normal")

    # Dynamic defaults for Weight and Unit based on past records
    default_weight = 0.0
    default_unit_idx = 0 if 'kg' in units else 0
    if not df_log.empty and selected_exercise:
        df_ex = df_log[df_log['Exercise'] == selected_exercise]
        if not df_ex.empty:
            last_rec = df_ex.iloc[-1]
            try:
                default_weight = float(last_rec.get('Weight', 0.0))
            except ValueError:
                pass
            
            last_unit = str(last_rec.get('Unit', ''))
            if last_unit in units:
                default_unit_idx = units.index(last_unit)

    st.markdown(
        """
        <style>
        /* Force form columns to stay side-by-side on mobile and prevent horizontal overflow */
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
        """,
        unsafe_allow_html=True
    )

    if selected_exercise:
        with st.form("log_form"):
            date_val = st.date_input("Date", datetime.date.today(), format="YYYY/MM/DD")

            col_w, col_u = st.columns([2, 1])
            with col_w:
                weight = st.number_input("Weight", min_value=0.0, step=2.5, format="%.1f", value=default_weight)
            with col_u:
                unit = st.selectbox("Unit", units, index=default_unit_idx)
                
            col_r, col_rpe, col_t = st.columns([1, 1, 1.5])
            with col_r:
                reps = st.number_input("Reps", min_value=0, step=1, value=10)
            with col_rpe:
                rpe = st.number_input("RPE", min_value=1.0, max_value=10.0, step=0.5, value=None)
            with col_t:
                set_type_idx = 0
                if 'Main' in set_types: set_type_idx = set_types.index('Main')
                set_type = st.selectbox("Set Type", set_types, index=set_type_idx)
                
            memo = st.text_input("Memo")
            
            submitted = st.form_submit_button("Add Log", type="primary")

    if submitted:
        if not selected_exercise:
            st.error("Please select an exercise first.")
        else:
            ex_info = exercise_map.get(selected_exercise, {})
            ex_id = ex_info.get('exercise_id', '')
            target_muscle = ex_info.get('target_muscle_group', '')

            if df_log.empty:
                start_id = 1
            else:
                start_id = df_log['ID'].max() + 1
            
            row = {
                "ID": int(start_id),
                "Date": date_val.strftime("%Y/%m/%d"),
                "ExerciseID": str(ex_id),
                "Target": target_muscle,
                "Exercise": selected_exercise,
                "Weight": float(weight),
                "Unit": unit,
                "Reps": int(reps),
                "RPE": float(rpe) if rpe is not None else "",
                "Set Type": set_type,
                "Memo": memo
            }
            
            try:
                ws_log = sh.worksheet(SHEET_TRAINING_LOG)
                headers = df_log.columns.tolist() if not df_log.empty else ["ID", "Date", "ExerciseID", "Target", "Exercise", "Weight", "Unit", "Reps", "RPE", "Set Type", "Memo"]
                rows_to_append = [[row.get(h, "") for h in headers]]
                
                ws_log.append_rows(rows_to_append, value_input_option='USER_ENTERED')
                
                st.session_state['success_msg'] = f"Added: {selected_exercise} ({weight}{unit} x {reps})"
                
                time.sleep(1.5)
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update spreadsheet: {e}")

    st.divider()
    st.markdown("### Analysis")
    
    if not df_log.empty:
        df_log['Date'] = pd.to_datetime(df_log['Date'], errors='coerce')
        df_log['Weight'] = pd.to_numeric(df_log['Weight'], errors='coerce').fillna(0)
        df_log['Reps'] = pd.to_numeric(df_log['Reps'], errors='coerce').fillna(0)

        df_log['Weight (kg)'] = df_log.apply(
            lambda x: x['Weight'] * 0.453592 if str(x.get('Unit', '')).lower() == 'lbs' else x['Weight'], 
            axis=1
        )
        df_log['Estimated 1RM (kg)'] = df_log['Weight (kg)'] * (1 + df_log['Reps'] / 30.0)
        
        if selected_exercise:
            df_chart = df_log[df_log['Exercise'] == selected_exercise].copy()
            df_chart = df_chart.dropna(subset=['Date'])
            
            if df_chart.empty:
                 st.info("No valid records for this exercise.")
            else:
                df_chart = df_chart.sort_values('ID')
                df_chart['Set Order'] = df_chart.groupby('Date').cumcount() + 1
                
                fig = px.scatter(
                    df_chart, 
                    x='Date', 
                    y='Weight (kg)',
                    size='Reps',
                    color='Estimated 1RM (kg)',
                    title=f"{selected_exercise} - Performance Analysis",
                    custom_data=['Set Order', 'Reps', 'Weight (kg)', 'RPE', 'Memo', 'Estimated 1RM (kg)']
                )
                fig.update_traces(
                    marker=dict(line=dict(width=1, color='DarkSlateGrey'), sizeref=0.5, sizemin=8),
                    hovertemplate=(
                        "<b>%{x|%Y/%m/%d}</b><br>"
                        "Weight:&nbsp;%{customdata[2]:.1f} kg<br>"
                        "Reps:&nbsp;&nbsp;&nbsp;%{customdata[1]}<br>"
                        "Set #:&nbsp;&nbsp;%{customdata[0]}<br>"
                        "RPE:&nbsp;&nbsp;&nbsp;&nbsp;%{customdata[3]}<br>"
                        "1RM:&nbsp;&nbsp;&nbsp;&nbsp;%{customdata[5]:.1f} kg<br>"
                        "Memo:&nbsp;&nbsp;&nbsp;%{customdata[4]}"
                        "<extra></extra>"
                    )
                )
                fig.update_layout(hovermode="closest", showlegend=False, coloraxis_showscale=False)
                st.plotly_chart(fig, width='stretch')
                
                col1, col2, col3 = st.columns(3)
                max_1rm = df_chart['Estimated 1RM (kg)'].max()
                max_weight = df_chart['Weight (kg)'].max()
                total_sets = len(df_chart)
                
                col1.metric("Personal Best (1RM)", f"{max_1rm:.1f} kg")
                col2.metric("Max Weight Lifted", f"{max_weight:.1f} kg")
                col3.metric("Total Sets Logged", total_sets)
                
                st.markdown("#### Recent Sets")
                unique_dates = sorted(df_chart['Date'].dt.date.unique(), reverse=True)[:3]
                df_recent = df_chart[df_chart['Date'].dt.date.isin(unique_dates)].copy()
                
                for d in unique_dates:
                    st.markdown(f"**📅 {d.strftime('%Y/%m/%d')}**")
                    day_sets = df_recent[df_recent['Date'].dt.date == d]
                    day_sets = day_sets.sort_values(by='ID', ascending=True)
                    
                    set_num = 1
                    for _, row in day_sets.iterrows():
                        weight_str = f"{row['Weight']:.1f} {row['Unit']}"
                        rm_val = row.get('Estimated 1RM (kg)', 0)
                        rm_str = f" (1RM: {rm_val:.1f} kg)" if rm_val > 0 else ""
                        st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;**{set_num}.** {weight_str} x {int(row['Reps'])}{rm_str}")
                        set_num += 1
                
                st.divider()
                st.markdown("### Notes")
                ex_info = exercise_map.get(selected_exercise, {})
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"**Sub Muscle:** {ex_info.get('sub_muscle_group', '-')}")
                c2.markdown(f"**Equipment:** {ex_info.get('equipment_type', '-')}")
                c3.markdown(f"**Category:** {ex_info.get('exercise_category', '-')}")
                
                mask = df_master['exercise_name'] == selected_exercise
                if mask.any():
                    original_idx = df_master.index[mask][0]
                    current_desc = df_master.loc[original_idx, 'description']
                    if pd.isna(current_desc): current_desc = ""
                    
                    new_desc = st.text_area("Description / Notes", value=str(current_desc), height=100, key=f"analysis_desc_edit_{selected_exercise}")
                    
                    if st.button("Save Description", key="save_desc_analysis"):
                        try:
                             df_master.at[original_idx, 'description'] = new_desc
                             ws_master = sh.worksheet(SHEET_EXERCISE_MASTER)
                             headers = df_master.columns.tolist()
                             df_to_save = df_master.fillna("")
                             data_to_write = [headers] + df_to_save.values.tolist()
                             ws_master.clear()
                             ws_master.update(range_name='A1', values=data_to_write, value_input_option='USER_ENTERED')
                             st.success("Description updated!")
                             time.sleep(1)
                             st.cache_data.clear()
                             st.rerun()
                        except Exception as e:
                            st.error(f"Save failed: {e}")
                else:
                    st.caption("Exercise not found in master database.")

    else:
        st.info("No training data available yet.")

# === TAB 2: History & Edit ===
with tab2:
    st.markdown("### History")
    if not df_log.empty:
        df_log_history = df_log.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_log_history['Date']):
             df_log_history['Date'] = pd.to_datetime(df_log_history['Date'], errors='coerce')
        
        df_log_history['Month'] = df_log_history['Date'].dt.strftime('%Y/%m')
        available_months = sorted(df_log_history['Month'].dropna().unique().tolist(), reverse=True)
        
        current_month_str = datetime.date.today().strftime('%Y/%m')
        default_month_idx = 0
        if current_month_str in available_months:
            default_month_idx = available_months.index(current_month_str)
            
        selected_month = st.selectbox("Select Month", available_months, index=default_month_idx)
        
        df_log_history = df_log_history[df_log_history['Month'] == selected_month]
        df_date_summary = df_log_history.groupby(df_log_history['Date'].dt.date).size().reset_index(name='Sets')
        df_date_summary.columns = ['Date', 'Sets']
        df_date_summary = df_date_summary.sort_values('Date', ascending=False)
        
        col_list, col_details = st.columns([1, 2])
        
        with col_list:
            st.markdown("#### Dates")
            st.caption("Max 3 dates.")
            event = st.dataframe(
                df_date_summary,
                on_select="rerun",
                selection_mode="multi-row",
                hide_index=True,
                column_config={
                    "Date": st.column_config.DateColumn("Date", format="YYYY/MM/DD"),
                    "Sets": st.column_config.NumberColumn("Sets"),
                }
            )
            
            selected_rows = event.selection.rows
            selected_dates = []
            if selected_rows:
                if len(selected_rows) > 3:
                     st.warning("Max 3 dates allowed. Showing top 3 selected.")
                     selected_rows = selected_rows[:3]
                for idx in selected_rows:
                    selected_dates.append(df_date_summary.iloc[idx]['Date'])
                selected_dates.sort() 

        with col_details:
            if selected_dates:
                df_display = df_log_history[df_log_history['Date'].dt.date.isin(selected_dates)]
                if df_display.empty:
                    st.info("No logs found for selected dates.")
                else:
                    df_display = df_display.sort_values(by=['Date', 'ID'], ascending=[True, True])
                    edited_dfs = []
                    
                    if "Delete" not in df_display.columns:
                        df_display.insert(0, "Delete", False)
                        
                    unique_display_dates = sorted(df_display['Date'].dt.date.unique())
                    st.caption("Edit directly in the table, check 'Delete' box to remove records, and click the button below to save.")
                    
                    for d in unique_display_dates:
                        st.markdown(f"#### 📅 {d.strftime('%Y/%m/%d')}")
                        df_date = df_display[df_display['Date'].dt.date == d]
                        
                        edited = st.data_editor(
                            df_date,
                            hide_index=True,
                            column_config={
                                "Delete": st.column_config.CheckboxColumn("❌", width="small", default=False),
                                "ID": None,
                                "ExerciseID": None,
                                "Date": None,
                                "Exercise": st.column_config.TextColumn("Exercise", disabled=True),
                                "Target": st.column_config.TextColumn("Target", disabled=True),
                                "Weight": st.column_config.NumberColumn("Weight", format="%.1f"),
                                "Unit": st.column_config.SelectboxColumn("Unit", options=units),
                                "Reps": st.column_config.NumberColumn("Reps", step=1),
                                "RPE": st.column_config.NumberColumn("RPE", min_value=1.0, max_value=10.0, step=0.5),
                                "Set Type": st.column_config.SelectboxColumn("Set Type", options=set_types),
                                "Memo": st.column_config.TextColumn("Memo"),
                                "Estimated 1RM (kg)": st.column_config.NumberColumn("1RM", format="%.1f", disabled=True),
                                "Weight (kg)": None,
                            },
                            disabled=["Exercise", "Target", "ID", "ExerciseID", "Date", "Estimated 1RM (kg)", "Weight (kg)"],
                            key=f"editor_{d}"
                        )
                        edited_dfs.append(edited)
                        st.divider()

                    if st.button("💾 Apply Changes (Save Edits & Deletes)", type="primary"):
                        ids_to_delete = []
                        edits = {}
                        
                        for ed in edited_dfs:
                            if not ed.empty:
                                if 'Delete' in ed.columns:
                                    deleted_rows = ed[ed['Delete'] == True]
                                    ids_to_delete.extend(deleted_rows['ID'].tolist())
                                
                                kept_rows = ed[ed['Delete'] == False]
                                for _, row in kept_rows.iterrows():
                                    edits[row['ID']] = {
                                        'Weight': row.get('Weight', ""),
                                        'Unit': row.get('Unit', ""),
                                        'Reps': row.get('Reps', ""),
                                        'RPE': row.get('RPE', ""),
                                        'Set Type': row.get('Set Type', ""),
                                        'Memo': row.get('Memo', "")
                                    }
                        
                        if not ids_to_delete and not edits:
                            st.warning("No changes detected.")
                        else:
                            with st.spinner("Saving changes..."):
                                try:
                                    ws_log_current = sh.worksheet(SHEET_TRAINING_LOG)
                                    current_data = ws_log_current.get_all_records()
                                    df_current = pd.DataFrame(current_data)
                                    
                                    if 'ID' in df_current.columns:
                                        df_current['ID'] = pd.to_numeric(df_current['ID'], errors='coerce').fillna(0).astype(int)
                                        
                                    df_remaining = df_current[~df_current['ID'].isin(ids_to_delete)].copy()
                                    
                                    for i, row in df_remaining.iterrows():
                                        _id = row['ID']
                                        if _id in edits:
                                            edit_vals = edits[_id]
                                            df_remaining.at[i, 'Weight'] = edit_vals['Weight'] if pd.notna(edit_vals['Weight']) else ""
                                            df_remaining.at[i, 'Unit'] = edit_vals['Unit'] if pd.notna(edit_vals['Unit']) else ""
                                            df_remaining.at[i, 'Reps'] = edit_vals['Reps'] if pd.notna(edit_vals['Reps']) else ""
                                            df_remaining.at[i, 'RPE'] = edit_vals['RPE'] if pd.notna(edit_vals['RPE']) else ""
                                            df_remaining.at[i, 'Set Type'] = edit_vals['Set Type'] if pd.notna(edit_vals['Set Type']) else ""
                                            df_remaining.at[i, 'Memo'] = edit_vals['Memo'] if pd.notna(edit_vals['Memo']) else ""
                                            
                                    ws_log_current.clear()
                                    headers = df_current.columns.tolist() if not df_current.empty else ["ID", "Date", "ExerciseID", "Target", "Exercise", "Weight", "Unit", "Reps", "RPE", "Set Type", "Memo"]
                                    update_data = [headers] + df_remaining.fillna("").values.tolist()
                                    ws_log_current.update(range_name='A1', values=update_data, value_input_option='USER_ENTERED')
                                    
                                    st.success(f"Changes applied! (Deleted {len(ids_to_delete)}, Checked {len(edits)} for updates).")
                                    time.sleep(1)
                                    st.cache_data.clear()
                                    st.rerun()
                                    
                                except Exception as e:
                                    st.error(f"Failed to apply changes: {e}")
    else:
        st.info("No data available.")

# === TAB 3: Templates ===
with tab3:
    st.markdown("### Templates")
    
    with st.expander("Create New Template", expanded=df_templates.empty):
        col_name, col_muscle = st.columns(2)
        with col_name:
            new_template_name = st.text_input("Template Name", placeholder="e.g., Chest Day", key="tab_template_name")
        with col_muscle:
            create_muscle_filter = st.selectbox("Filter Exercises by Muscle", ["All"] + muscle_groups_input, key="tab_create_template_muscle")
            
        base_options = exercise_options
        if create_muscle_filter != "All":
            base_options = [ex for ex in exercise_options if exercise_map.get(ex, {}).get('target_muscle_group') == create_muscle_filter]
        
        current_selections = st.session_state.get("tab_template_exercises", [])
        
        options_to_select = []
        for ex in base_options + current_selections:
            if ex not in options_to_select:
                options_to_select.append(ex)
        
        selected_exercises_for_template = st.multiselect("Select Exercises (Order is preserved)", options_to_select, key="tab_template_exercises")
        
        submitted_template = st.button("Save Template", type="primary")
        
        if submitted_template:
            if not new_template_name:
                st.error("Please enter a template name.")
            elif new_template_name.strip().lower() == "select from exercises":
                st.error("This template name is reserved. Please pick another.")
            elif not selected_exercises_for_template:
                st.error("Please select at least one exercise.")
            else:
                try:
                    ex_ids = [normalize_id(exercise_map.get(ex, {}).get('exercise_id', '')) for ex in selected_exercises_for_template]
                    ex_ids_str = "|".join(ex_ids)
                    
                    if df_templates.empty:
                        new_tid = "TMP001"
                    else:
                        last_id = df_templates['template_id'].iloc[-1]
                        try:
                            num = int(last_id.replace("TMP", "")) + 1
                            new_tid = f"TMP{num:03d}"
                        except:
                            new_tid = f"TMP{len(df_templates)+1:03d}"
                    
                    new_template_row = [
                        new_tid,
                        new_template_name,
                        ex_ids_str,
                        datetime.date.today().strftime("%Y/%m/%d")
                    ]
                    
                    ws_templates = sh.worksheet(SHEET_TEMPLATE_MASTER)
                    ws_templates.append_row(new_template_row, value_input_option='USER_ENTERED')
                    
                    for k in ["tab_template_name", "tab_create_template_muscle", "tab_template_exercises"]:
                        if k in st.session_state:
                            del st.session_state[k]
                            
                    st.success(f"Template '{new_template_name}' saved!")
                    time.sleep(1)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save template: {e}")

    if not df_templates.empty:
        with st.expander("Edit Existing Template", expanded=False):
            edit_tid = st.selectbox("Select Template", df_templates['template_id'].tolist(), format_func=lambda x: df_templates[df_templates['template_id']==x]['template_name'].values[0], key="edit_template_selector_tid")
            
            if edit_tid:
                target_row = df_templates[df_templates['template_id'] == edit_tid].iloc[0]
                
                raw_ids_str = target_row['exercise_ids']
                raw_ids = str(raw_ids_str).split('|') if '|' in str(raw_ids_str) else str(raw_ids_str).split(',')
                
                existing_exercises = []
                for eid in raw_ids:
                    eid_str = normalize_id(eid)
                    for ex_name, ex_info in exercise_map.items():
                        if normalize_id(ex_info.get('exercise_id', '')) == eid_str:
                            existing_exercises.append(ex_name)
                            break
                            
                col_ename, col_emuscle = st.columns(2)
                with col_ename:
                    updated_name = st.text_input("Template Name", value=target_row['template_name'], key=f"edit_name_{edit_tid}")
                with col_emuscle:
                    edit_muscle_filter = st.selectbox("Filter Exercises by Muscle", ["All"] + muscle_groups_input, key=f"edit_muscle_{edit_tid}")
                    
                edit_base_options = exercise_options
                if edit_muscle_filter != "All":
                    edit_base_options = [ex for ex in exercise_options if exercise_map.get(ex, {}).get('target_muscle_group') == edit_muscle_filter]
                
                current_edit_selections = st.session_state.get(f"edit_exs_{edit_tid}", existing_exercises)
                
                options_to_select_edit = []
                for ex in edit_base_options + current_edit_selections + existing_exercises:
                    if ex not in options_to_select_edit:
                        options_to_select_edit.append(ex)
                
                updated_exercises = st.multiselect(
                    "Select Exercises (Order is preserved)", 
                    options_to_select_edit, 
                    default=existing_exercises,
                    key=f"edit_exs_{edit_tid}"
                )
                
                if st.button("Update Template", type="primary", key=f"update_btn_{edit_tid}"):
                    if not updated_name:
                        st.error("Please enter a template name.")
                    elif updated_name.strip().lower() == "select from exercises" and updated_name != target_row['template_name']:
                        st.error("This template name is reserved. Please pick another.")
                    elif not updated_exercises:
                        st.error("Please select at least one exercise.")
                    else:
                        try:
                            new_ex_ids = [normalize_id(exercise_map.get(ex, {}).get('exercise_id', '')) for ex in updated_exercises]
                            new_ex_ids_str = "|".join(new_ex_ids)
                            
                            idx_to_update = df_templates.index[df_templates['template_id'] == edit_tid].tolist()[0]
                            df_templates.at[idx_to_update, 'template_name'] = updated_name
                            df_templates.at[idx_to_update, 'exercise_ids'] = new_ex_ids_str
                            
                            ws_templates = sh.worksheet(SHEET_TEMPLATE_MASTER)
                            ws_templates.clear()
                            headers = df_templates.columns.tolist()
                            update_data = [headers] + df_templates.values.tolist()
                            ws_templates.update(range_name='A1', values=update_data, value_input_option='USER_ENTERED')
                            
                            st.success(f"Template '{updated_name}' updated successfully!")
                            time.sleep(1)
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to update template: {e}")

    st.divider()
    st.markdown("### Saved")
    if not df_templates.empty:
        df_temp_display = df_templates.copy()
        
        if "Delete" not in df_temp_display.columns:
            df_temp_display.insert(0, "Delete", False)
            
        def get_exercise_names(ids_str):
            if '|' in str(ids_str):
                ids = str(ids_str).split('|')
            else:
                ids = str(ids_str).split(',')
            
            names = []
            for eid in ids:
                eid = normalize_id(eid)
                for ex_name, ex_info in exercise_map.items():
                    if normalize_id(ex_info.get('exercise_id', '')) == eid:
                        names.append(ex_name)
                        break
            return ", ".join(names)
            
        if 'exercise_ids' in df_temp_display.columns:
            df_temp_display['Exercises'] = df_temp_display['exercise_ids'].apply(get_exercise_names)
            
        edited_templates = st.data_editor(
            df_temp_display,
            hide_index=True,
            column_config={
                "Delete": st.column_config.CheckboxColumn("❌", width="small", default=False),
                "template_id": st.column_config.TextColumn("ID", disabled=True),
                "template_name": st.column_config.TextColumn("Template Name", width="medium"),
                "exercise_ids": None,
                "created_at": st.column_config.TextColumn("Created At", disabled=True),
                "Exercises": st.column_config.TextColumn("Exercises", width="large", disabled=True),
            },
            key="template_list_editor"
        )
        
        if st.button("🗑️ Delete Selected Templates", type="primary"):
            ids_to_del = edited_templates[edited_templates['Delete'] == True]['template_id'].tolist()
            if not ids_to_del:
                st.warning("No templates selected for deletion.")
            else:
                try:
                    ws_temp = sh.worksheet(SHEET_TEMPLATE_MASTER)
                    df_remaining_templates = df_templates[~df_templates['template_id'].isin(ids_to_del)]
                    
                    ws_temp.clear()
                    headers = df_templates.columns.tolist()
                    temp_data_to_write = [headers] + df_remaining_templates.values.tolist()
                    ws_temp.update(range_name='A1', values=temp_data_to_write, value_input_option='USER_ENTERED')
                    
                    st.success(f"Deleted {len(ids_to_del)} template(s).")
                    time.sleep(1)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to delete templates: {e}")
    else:
        st.info("No templates saved yet.")
