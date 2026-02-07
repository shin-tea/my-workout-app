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

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

st.set_page_config(page_title="Workout Tracker", layout="wide", page_icon="💪")
st.title("🏋️ Workout Tracker")

# --- Success Message Logic ---
if 'success_msg' in st.session_state and st.session_state['success_msg']:
    st.success(st.session_state['success_msg'])
    del st.session_state['success_msg']
# -----------------------------

# --- Connection ---
@st.cache_resource
def init_connection():
    """Establish connection to Google Sheets using gspread."""
    try:
        # Load secrets from strict toml structure
        # We need to construct the credentials dict from st.secrets.connections.gsheets
        # or however we stored it.
        # We stored it under [connections.gsheets]
        
        # Access the secrets. ensure we convert Streamlit's AttrDict to a standard dict if needed
        # but Credentials.from_service_account_info expects a dict.
        
        secrets_dict = dict(st.secrets["connections"]["gsheets"])
        
        # Remove connection-specific keys that aren't part of the service account JSON
        # 'spreadsheet' is not part of the creds
        creds_dict = {k: v for k, v in secrets_dict.items() if k != "spreadsheet"}
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        # Open the spreadsheet
        spreadsheet_url = secrets_dict.get("spreadsheet")
        sh = client.open_by_url(spreadsheet_url)
        return sh
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        return None

sh = init_connection()

# --- Data Loading ---
@st.cache_data(ttl=5)
def load_data():
    """Load all necessary sheets from GSheets."""
    if sh is None:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
    try:
        # Load Training Log
        ws_log = sh.worksheet(SHEET_TRAINING_LOG)
        data_log = ws_log.get_all_records()
        df_log = pd.DataFrame(data_log)
        
        # Ensure ID column exists, treating as numeric
        if 'ID' in df_log.columns:
            df_log['ID'] = pd.to_numeric(df_log['ID'], errors='coerce').fillna(0).astype(int)
        
        # Load Exercise Master
        ws_master = sh.worksheet(SHEET_EXERCISE_MASTER)
        data_master = ws_master.get_all_records()
        df_master = pd.DataFrame(data_master)
        
        # Load Constants
        ws_constants = sh.worksheet(SHEET_CONSTANTS)
        data_constants = ws_constants.get_all_records()
        df_constants = pd.DataFrame(data_constants)
        
        return df_log, df_master, df_constants
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_log, df_master, df_constants = load_data()

if df_master.empty or df_constants.empty:
    if sh is not None:
        st.warning("Could not load Master or Constants data. Please check the spreadsheet.")
    st.stop()

# --- Pre-process Data ---
# 1. Constants Map
# Structure: Category | Value
try:
    set_types_raw = df_constants[df_constants['Category'] == 'SetType']['Value'].dropna().unique().tolist()
    set_types = [""] + set_types_raw
    units = df_constants[df_constants['Category'] == 'Unit']['Value'].dropna().unique().tolist()
except KeyError:
    st.error("Constants sheet missing required 'Category' or 'Value' columns.")
    st.stop()

# 2. Exercise Map
# Structure: exercise_id | target_muscle_group | exercise_name ...
if 'exercise_name' in df_master.columns:
    exercise_options = df_master['exercise_name'].dropna().unique().tolist()
    # Create valid map: Name -> {id, target, ...}
    exercise_map = df_master.set_index('exercise_name').to_dict('index')
else:
    st.error("Exercise Master sheet missing 'exercise_name' column.")
    st.stop()

# --- Sidebar: Input Form ---
st.sidebar.header("📝 Log Workout")

# --- Interactive Selection (Outside Form) ---
# Muscle Filter
muscle_groups_input = sorted(df_master['target_muscle_group'].dropna().unique().tolist()) if 'target_muscle_group' in df_master.columns else []
selected_muscle_input = st.sidebar.selectbox("Filter Muscle", ["All"] + muscle_groups_input)

# Filter Options
filtered_options = exercise_options
if selected_muscle_input != "All":
    filtered_options = [ex for ex in exercise_options if exercise_map.get(ex, {}).get('target_muscle_group') == selected_muscle_input]

# Exercise Selector
selected_exercise = st.sidebar.selectbox("Exercise", filtered_options)

# --- Logic: Handle Set # Reset on Exercise Change ---
if 'last_exercise' not in st.session_state:
    st.session_state['last_exercise'] = None
if 'set_input_val' not in st.session_state:
    st.session_state['set_input_val'] = 1
if 'set_input_key' not in st.session_state:
    st.session_state['set_input_key'] = 0

# If exercise changed, reset set number to 1
if st.session_state['last_exercise'] != selected_exercise:
    st.session_state['set_input_val'] = 1
    st.session_state['set_input_key'] += 1 # Force widget recreate
    st.session_state['last_exercise'] = selected_exercise
# ----------------------------------------------------

with st.sidebar.form("log_form"):
    # Date
    date_val = st.date_input("Date", datetime.date.today(), format="YYYY/MM/DD")
    
    # Stats
    col_w, col_u = st.columns([2, 1])
    with col_w:
        weight = st.number_input("Weight", min_value=0.0, step=2.5, format="%.1f")
    with col_u:
        unit = st.selectbox("Unit", units, index=0 if 'kg' in units else 0, key="unit_select")
    
    col_r, col_s = st.columns(2)
    with col_r:
        reps = st.number_input("Reps", min_value=0, step=1, value=10)
    with col_s:
        # Use dynamic key to allow programmatic updates without "widget value" conflict
        set_num = st.number_input(
            "Set #", 
            min_value=1, 
            step=1, 
            value=st.session_state['set_input_val'],
            key=f"set_num_{st.session_state['set_input_key']}"
        )
        
    rpe = st.number_input("RPE (1-10)", min_value=1.0, max_value=10.0, step=0.5, value=None)
    set_type = st.selectbox("Set Type", set_types, index=0 if 'Main' in set_types else 0)
    memo = st.text_area("Memo", height=2)
    
    submitted = st.form_submit_button("Add Log", type="primary")

if submitted:
    # 1. Get Metadata
    ex_info = exercise_map.get(selected_exercise, {})
    ex_id = ex_info.get('exercise_id', '')
    target_muscle = ex_info.get('target_muscle_group', '')

    # 3. Generate IDs
    if df_log.empty:
        start_id = 1
    else:
        start_id = df_log['ID'].max() + 1
    
    # 4. Create Rows
    # Single record per click
    row = {
        "ID": int(start_id),
        "Date": date_val.strftime("%Y/%m/%d"),
        "ExerciseID": ex_id,
        "Target": target_muscle,
        "Exercise": selected_exercise,
        "Set #": int(set_num),
        "Weight": float(weight),
        "Unit": unit,
        "Reps": int(reps),
        "RPE": float(rpe) if rpe is not None else "",
        "Set Type": set_type,
        "Memo": memo
    }
    new_rows = [row]
    
    # 5. Append to GSheet
    try:
        ws_log = sh.worksheet(SHEET_TRAINING_LOG)
        
        # Convert dictionary rows to list of lists, matching header order
        # Need to read header first to be safe, or assume fixed order defined in prompt?
        # Safe way: match df_log columns if it exists, else assume fixed.
        # But df_log was read from get_all_records(), so keys match headers.
        
        # Prepare data for append_rows
        # We need the headers from the sheet to ensure order.
        # If df_log is loaded, we can use its columns.
        if not df_log.empty:
            headers = df_log.columns.tolist()
        else:
            # Fallback to the known structure if sheet is empty
            headers = ["ID", "Date", "ExerciseID", "Target", "Exercise", "Set #", "Weight", "Unit", "Reps", "RPE", "Set Type", "Memo"]
            
        rows_to_append = []
        for row_dict in new_rows:
            row_vals = [row_dict.get(h, "") for h in headers]
            rows_to_append.append(row_vals)
            
        ws_log.append_rows(rows_to_append, value_input_option='USER_ENTERED')
        
        # Store success message in session state for display after rerun
        st.session_state['success_msg'] = f"Running: Added Set #{set_num} of {selected_exercise}!"
        
        # Increment Set # for next log
        st.session_state['set_input_val'] = int(set_num) + 1
        st.session_state['set_input_key'] += 1 # Force widget recreate next run
        
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Failed to update spreadsheet: {e}")

# --- Dashboard View ---
st.subheader("📊 Progress & History")

tab1, tab2 = st.tabs(["📈 Analysis", "📅 History & Edit"])

# === TAB 1: Analysis ===
with tab1:
    if not df_log.empty:
        # Correct Types for display/plotting
        df_log['Date'] = pd.to_datetime(df_log['Date'], errors='coerce')
        df_log['Weight'] = pd.to_numeric(df_log['Weight'], errors='coerce').fillna(0)
        df_log['Reps'] = pd.to_numeric(df_log['Reps'], errors='coerce').fillna(0)

        # Calculate Derived Columns
        df_log['Weight (kg)'] = df_log.apply(
            lambda x: x['Weight'] * 0.453592 if str(x.get('Unit', '')).lower() == 'lbs' else x['Weight'], 
            axis=1
        )
        df_log['Estimated 1RM (kg)'] = df_log['Weight (kg)'] * (1 + df_log['Reps'] / 30.0)
        
        # Filter by Exercise
        unique_exercises = sorted(df_log['Exercise'].astype(str).unique().tolist())
        
        # --- Muscle Group Filter ---
        if 'target_muscle_group' in df_master.columns:
            muscle_groups = sorted(df_master['target_muscle_group'].dropna().unique().tolist())
            col_m_filter, _ = st.columns([1, 2])
            with col_m_filter:
                selected_muscle = st.selectbox("Dashboard Filter: Muscle Group", ["All"] + muscle_groups, key="dash_muscle_filter")
            
            if selected_muscle != "All":
                filtered_exercises = []
                for ex in unique_exercises:
                    info = exercise_map.get(ex)
                    if info and info.get('target_muscle_group') == selected_muscle:
                        filtered_exercises.append(ex)
                unique_exercises = filtered_exercises
        # ---------------------------

        # Default selection
        default_idx = 0
        if not df_log.empty:
            last_ex = df_log.iloc[-1]['Exercise']
            if last_ex in unique_exercises:
                default_idx = unique_exercises.index(last_ex)
                
        selected_chart_exercise = st.selectbox("Select Exercise to Visualize", unique_exercises, index=default_idx, key="chart_ex_select")
        
        if selected_chart_exercise:
            df_chart = df_log[df_log['Exercise'] == selected_chart_exercise].copy()
            df_chart = df_chart.dropna(subset=['Date'])
            
            if df_chart.empty:
                 st.info("No valid records for this exercise.")
            else:
                # Remove Daily Aggregation to show ALL sets
                # Plotly Scatter Chart
                fig = px.scatter(
                    df_chart, 
                    x='Date', 
                    y='Weight (kg)',
                    size='Reps',
                    color='Estimated 1RM (kg)', # Color by intensity
                    title=f"{selected_chart_exercise} - Performance Analysis",
                    custom_data=['Set #', 'Reps', 'Weight (kg)', 'RPE', 'Memo', 'Estimated 1RM (kg)']
                )
                fig.update_traces(
                    marker=dict(line=dict(width=1, color='DarkSlateGrey'), sizeref=0.5, sizemin=8),
                    hovertemplate=(
                        "<b>%{x|%Y/%m/%d}</b><br>"
                        "<table>"
                        "<tr><td>Weight</td><td>:</td><td>%{customdata[2]:.1f} kg</td></tr>"
                        "<tr><td>Reps</td><td>:</td><td>%{customdata[1]}</td></tr>"
                        "<tr><td>Set #</td><td>:</td><td>%{customdata[0]}</td></tr>"
                        "<tr><td>RPE</td><td>:</td><td>%{customdata[3]}</td></tr>"
                        "<tr><td>1RM</td><td>:</td><td>%{customdata[5]:.1f} kg</td></tr>"
                        "<tr><td>Memo</td><td>:</td><td>%{customdata[4]}</td></tr>"
                        "</table>"
                        "<extra></extra>"
                    )
                )
                fig.update_layout(hovermode="closest", showlegend=False, coloraxis_showscale=False)
                st.plotly_chart(fig, use_container_width=True)
                
                # Metrics
                col1, col2, col3 = st.columns(3)
                max_1rm = df_chart['Estimated 1RM (kg)'].max()
                max_weight = df_chart['Weight (kg)'].max()
                total_sets = len(df_chart)
                
                col1.metric("Personal Best (1RM)", f"{max_1rm:.1f} kg")
                col2.metric("Max Weight Lifted", f"{max_weight:.1f} kg")
                col3.metric("Total Sets Logged", total_sets)
                
                st.divider()
                st.markdown("### ℹ️ Exercise Details & Notes")
                
                # Retrieve details from Master
                ex_info = exercise_map.get(selected_chart_exercise, {})
                
                # Display Read-only fields
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"**Sub Muscle:** {ex_info.get('sub_muscle_group', '-')}")
                c2.markdown(f"**Equipment:** {ex_info.get('equipment_type', '-')}")
                c3.markdown(f"**Category:** {ex_info.get('exercise_category', '-')}")
                
                # Editable Description
                mask = df_master['exercise_name'] == selected_chart_exercise
                if mask.any():
                    original_idx = df_master.index[mask][0]
                    current_desc = df_master.loc[original_idx, 'description']
                    if pd.isna(current_desc): current_desc = ""
                    
                    new_desc = st.text_area("Description / Notes", value=str(current_desc), height=100, key="analysis_desc_edit")
                    
                    if st.button("💾 Save Description", key="save_desc_analysis"):
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
    st.markdown("### 🗓️ Workout History & Management")
    if not df_log.empty:
        # Pre-process Date
        df_log_history = df_log.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_log_history['Date']):
             df_log_history['Date'] = pd.to_datetime(df_log_history['Date'], errors='coerce')

        # Create Date Summary for Selection
        # Group by Date and count sets
        df_date_summary = df_log_history.groupby(df_log_history['Date'].dt.date).size().reset_index(name='Sets')
        df_date_summary.columns = ['Date', 'Sets']
        df_date_summary = df_date_summary.sort_values('Date', ascending=False)
        
        col_list, col_details = st.columns([1, 2])
        
        with col_list:
            st.markdown("#### Select Date(s)")
            st.caption("Max 3 dates.")
            
            # Configure dataframe selection
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
                # Limit to 3
                if len(selected_rows) > 3:
                     st.warning("Max 3 dates allowed. Showing top 3 selected.")
                     selected_rows = selected_rows[:3]
                
                for idx in selected_rows:
                    selected_dates.append(df_date_summary.iloc[idx]['Date'])
                
                selected_dates.sort(reverse=True) # Show newest first or oldest? Oldest to newest seems better for flow.
                # Actually user asked for Old->New in table. Let's keep dates sorted in list.
                selected_dates.sort() 

        # Filter Logic & Display
        with col_details:
            if not selected_dates:
                 pass  # Show nothing until dates are selected
            else:
                # Filter for ALL selected dates
                df_display = df_log_history[df_log_history['Date'].dt.date.isin(selected_dates)]
                
                if df_display.empty:
                    st.info("No logs found for selected dates.")
                else:
                    # Sort: Oldest to Newest as requested
                    df_display = df_display.sort_values(by=['Date', 'ID'], ascending=[True, True])
                    
                    # We will collect all edited dataframes to process deletions at once
                    edited_dfs = []
                    
                    # Insert Delete column globally first to ensure it's there
                    if "Delete" not in df_display.columns:
                        df_display.insert(0, "Delete", False)
                        
                    unique_display_dates = sorted(df_display['Date'].dt.date.unique())
                    
                    st.caption("Check 'Delete' box in any table and click the button at the bottom to remove records.")
                    
                    for d in unique_display_dates:
                        st.markdown(f"#### 📅 {d.strftime('%Y/%m/%d')}")
                        
                        # Subset for this date
                        df_date = df_display[df_display['Date'].dt.date == d]
                        
                        # Show Data Editor
                        # Hide ID, ExerciseID, Date (since it's the header)
                        edited = st.data_editor(
                            df_date,
                            hide_index=True,
                            column_config={
                                "Delete": st.column_config.CheckboxColumn(
                                    "❌",
                                    width="small",
                                    default=False,
                                ),
                                "ID": None, # Hide
                                "ExerciseID": None, # Hide
                                "Date": None, # Hide
                                "Exercise": st.column_config.TextColumn("Exercise", disabled=True),
                                "Weight": st.column_config.NumberColumn("Weight", format="%.1f"),
                                "Estimated 1RM (kg)": st.column_config.NumberColumn("1RM", format="%.1f"),
                            },
                            disabled=["Exercise", "Target", "Set #", "Weight", "Unit", "Reps", "RPE", "Set Type", "Memo", "ID", "ExerciseID", "Date", "Estimated 1RM (kg)", "Weight (kg)"],
                            key=f"editor_{d}"
                        )
                        edited_dfs.append(edited)
                        st.divider()

                    # Process Deletion
                    if st.button("🗑️ Delete Selected Rows", type="primary"):
                        # Collect IDs from all tables
                        ids_to_delete = []
                        for ed in edited_dfs:
                            if not ed.empty and 'Delete' in ed.columns:
                                 deleted_rows = ed[ed['Delete'] == True]
                                 if not deleted_rows.empty:
                                     ids_to_delete.extend(deleted_rows['ID'].tolist())
                        
                        if not ids_to_delete:
                            st.warning("No rows selected for deletion.")
                        else:
                            st.write(f"Deleting {len(ids_to_delete)} records...")
                            try:
                                # 1. Reload latest data
                                ws_log_current = sh.worksheet(SHEET_TRAINING_LOG)
                                current_data = ws_log_current.get_all_records()
                                df_current = pd.DataFrame(current_data)
                                
                                # 2. Filter out deleted IDs
                                if 'ID' in df_current.columns:
                                    df_current['ID'] = pd.to_numeric(df_current['ID'], errors='coerce').fillna(0).astype(int)
                                    
                                df_remaining = df_current[~df_current['ID'].isin(ids_to_delete)]
                                
                                # 3. Rewrite Sheet
                                ws_log_current.clear()
                                
                                headers = df_current.columns.tolist() if not df_current.empty else []
                                if not headers:
                                     headers = ["ID", "Date", "ExerciseID", "Target", "Exercise", "Set #", "Weight", "Unit", "Reps", "RPE", "Set Type", "Memo"]

                                update_data = [headers] + df_remaining.values.tolist()
                                ws_log_current.update(range_name='A1', values=update_data, value_input_option='USER_ENTERED')
                                
                                st.success(f"Deleted {len(ids_to_delete)} records.")
                                time.sleep(1)
                                st.cache_data.clear()
                                st.rerun()
                                
                            except Exception as e:
                                st.error(f"Failed to delete rows: {e}")
    else:
        st.info("No data available.")

