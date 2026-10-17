# my-workout-app

Streamlit workout tracker backed by Google Sheets. Run with `streamlit run main.py`.

## Code layout

- `main.py`: screen rendering, input fields and save feedback. `main()` loads the
  data once, then calls the Log & Analysis, History & Edit and Templates screens.
- `workout_sheets.py`: Google Sheets connection, reads and writes. Existing records
  are updated by ID using current sheet row positions; sheets are never cleared.
- `workout_data.py`: ID matching, shared analysis columns, template IDs and sheet
  request construction. No Streamlit or Google connection is needed here.
- `tests/`: offline tests for data handling and sheet writes using in-memory sheets.

Template creation and editing share one form. All screens use the same prepared
log data, and exercise selectors store IDs while displaying names from the master.

## Exercise names are derived from ExerciseID

`Exercise Master.exercise_id` is the source of truth. The app resolves log names
from this ID on every load and uses the ID for analysis and previous-set defaults.
Unknown IDs remain visible in History & Edit with an explicit warning.

New log rows store a lookup formula in `Training Log.Exercise`. History edits
update only editable cells and delete rows in descending order in one Sheets
batch, preserving the lookup formulas and other sheet contents.

For existing Google Sheets records, enter this formula in `Training Log!E2` and
fill down through the last record (standard layout: ExerciseID in C, Exercise in E;
master IDs in A and names in C):

```excel
=IF(INDEX($C:$C,ROW())="","",IFERROR(INDEX('Exercise Master'!$C:$C,MATCH(IFERROR(VALUE(INDEX($C:$C,ROW())),INDEX($C:$C,ROW())),'Exercise Master'!$A:$A,0)),"Unknown ExerciseID: "&INDEX($C:$C,ROW())))
```

Use individual row formulas, not an ARRAYFORMULA: the app appends its own formula
for each new record. A master name change then updates all existing row formulas.
Changing an ID takes precedence over any previous name. In the supplied snapshot,
this means the 16 rows named One Hand Arm Curl with ID 40 resolve to Preacher Curl
(Machine); the IDs themselves are not changed.

Offline checks: `python -m unittest discover -s tests -v`.
