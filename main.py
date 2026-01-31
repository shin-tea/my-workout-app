import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import gspread
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
    set_types = df_constants[df_constants['Category'] == 'SetType']['Value'].dropna().unique().tolist()
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

with st.sidebar.form("log_form"):
    # Date
    date_val = st.date_input("Date", datetime.date.today())
    
    # Exercise
    selected_exercise = st.selectbox("Exercise", exercise_options)
    
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
        sets = st.number_input("Sets", min_value=1, step=1, value=3)
        
    rpe = st.number_input("RPE (1-10)", min_value=0.0, max_value=10.0, step=0.5, value=8.0)
    set_type = st.selectbox("Set Type", set_types, index=0 if 'Main' in set_types else 0)
    memo = st.text_area("Memo", height=2)
    
    submitted = st.form_submit_button("Add Log", type="primary")

if submitted:
    # 1. Calculations
    weight_kg = weight
    if unit == 'lbs':
        weight_kg = weight * 0.453592
    
    # Epley Formula: 1RM = Weight * (1 + Reps/30)
    estimated_1rm = 0.0
    if reps > 0:
        estimated_1rm = weight_kg * (1 + reps / 30.0)
    else:
        estimated_1rm = 0.0

    # 2. Get Metadata
    ex_info = exercise_map.get(selected_exercise, {})
    ex_id = ex_info.get('exercise_id', '')
    target_muscle = ex_info.get('target_muscle_group', '')

    # 3. Generate IDs
    if df_log.empty:
        start_id = 1
    else:
        start_id = df_log['ID'].max() + 1
    
    # 4. Create Rows
    new_rows = []
    for i in range(sets):
        row = {
            "ID": int(start_id + i),
            "Date": date_val.strftime("%Y-%m-%d"),
            "ExerciseID": ex_id,
            "Target": target_muscle,
            "Exercise": selected_exercise,
            "Set #": int(i + 1),
            "Weight": float(weight),
            "Unit": unit,
            "Reps": int(reps),
            "RPE": float(rpe),
            "Set Type": set_type,
            "Memo": memo,
            "Weight (kg)": round(weight_kg, 2),
            "Estimated 1RM (kg)": round(estimated_1rm, 2)
        }
        new_rows.append(row)
    
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
            headers = ["ID", "Date", "ExerciseID", "Target", "Exercise", "Set #", "Weight", "Unit", "Reps", "RPE", "Set Type", "Memo", "Weight (kg)", "Estimated 1RM (kg)"]
            
        rows_to_append = []
        for row_dict in new_rows:
            row_vals = [row_dict.get(h, "") for h in headers]
            rows_to_append.append(row_vals)
            
        ws_log.append_rows(rows_to_append)
        
        st.success(f"Running: Added {sets} sets of {selected_exercise}!")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Failed to update spreadsheet: {e}")

# --- Dashboard View ---
# Filter Section
st.subheader("📊 Progress Dashboard")

if not df_log.empty:
    # Correct Types for display/plotting
    df_log['Date'] = pd.to_datetime(df_log['Date'], errors='coerce')
    
    # Filter by Exercise
    unique_exercises = sorted(df_log['Exercise'].astype(str).unique().tolist())
    
    # Default selection: most recently logged exercise
    default_idx = 0
    if not df_log.empty:
        last_ex = df_log.iloc[-1]['Exercise']
        if last_ex in unique_exercises:
            default_idx = unique_exercises.index(last_ex)
            
    selected_chart_exercise = st.selectbox("Select Exercise to Visualize", unique_exercises, index=default_idx)
    
    if selected_chart_exercise:
        df_chart = df_log[df_log['Exercise'] == selected_chart_exercise].copy()
        df_chart = df_chart.dropna(subset=['Date'])
        
        if df_chart.empty:
             st.info("No valid records for this exercise.")
        else:
            # Aggregations per day for the chart (Max 1RM, Max Weight)
            df_daily = df_chart.groupby('Date').agg({
                'Estimated 1RM (kg)': 'max',
                'Weight (kg)': 'max',
                'Reps': 'max'
            }).reset_index()
            
            # Plotly Line Chart
            fig = px.line(
                df_daily, 
                x='Date', 
                y=['Estimated 1RM (kg)', 'Weight (kg)'],
                markers=True,
                title=f"{selected_chart_exercise} - Max Daily Performance"
            )
            fig.update_layout(hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)
            
            # Metrics
            col1, col2, col3 = st.columns(3)
            max_1rm = df_chart['Estimated 1RM (kg)'].max()
            max_weight = df_chart['Weight (kg)'].max()
            total_sets = len(df_chart)
            
            col1.metric("Personal Best (1RM)", f"{max_1rm} kg")
            col2.metric("Max Weight Lifted", f"{max_weight} kg")
            col3.metric("Total Sets Logged", total_sets)
            
            # Log Table
            with st.expander(f"See Detailed Logs for {selected_chart_exercise}"):
                st.dataframe(
                    df_chart.sort_values(by=['Date', 'Set #'], ascending=[False, True])
                    .style.format({"Weight": "{:.1f}", "Estimated 1RM (kg)": "{:.1f}"})
                )
else:
    st.info("No training data available yet. Add your first workout on the left!")
