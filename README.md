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

## Record IDs and concurrent edits

New workout records receive a UUID at save time. Existing numeric record IDs and
all exercise IDs remain valid; existing rows do not need migration. UUIDs identify
records and are not used to infer when a set was performed.

To use UUIDs consistently, open **History & Edit → Record IDs → Convert existing
record IDs to UUIDs** once. This reads the current Training Log and replaces only
non-UUID ID cells in one batch. Existing UUIDs, ExerciseID, lookup formulas and all
workout values stay unchanged. Blank or duplicate IDs stop the conversion. Once
all IDs are UUIDs, the action disappears. Reload other open app views afterwards;
edits based on the old IDs are rejected until reloaded.

History keeps the original rows shown in each editor and sends only fields that
the user actually changed. Before writing, the app reads the current sheet and
checks those fields against the originals. Conflicting edits, missing records and
duplicate IDs stop the whole save with a Reload message. Deletions also check the
record's date, exercise ID, target and all editable fields. Click Reload to discard
the old editor snapshot and start from the latest data.

Writes are serialized across sessions in the same app server. The read/check/write
sequence is not a database transaction against Google Sheets: direct sheet edits
or a separate server can still race after the check. Strict coordination across
independent writers would require a shared transactional backend.

## Invalid values and previous-set defaults

Date, Weight and Reps keep their original source values alongside parsed analysis
values. Invalid dates, non-finite/non-numeric weights, invalid repetitions and
blank/duplicate record IDs appear in Records needing correction with their sheet
row numbers. They are excluded from charts and editable history, not changed to
zero or written back automatically. Correct those values in Training Log, then
Reload. Mixed slash/hyphen date formats are accepted.

Previous-set defaults come from the latest valid workout date for the selected
exercise. Sets on the same date follow sheet row order, so a backdated record does
not replace a newer workout's defaults. Negative assistance weights are retained,
but are not used as defaults in the non-negative weight entry form.

## Save performance

The UI caches Training Log separately from exercise, constants and template data.
A log save invalidates only Training Log; description and template saves refresh
only reference data. The saved log is still read back from Google Sheets before
displaying updated results. History conflict checks always read fresh sheet values.

New records reuse the loaded column headers and a cached worksheet handle. After
the initial load, adding a set normally needs just the append request and a log
read, without re-fetching master headers or all reference sheets. Read operations
also reuse headers returned with records rather than requesting them separately.
If you manually reorder sheet columns or replace a worksheet, click Reload before
entering records so both headers and worksheet metadata are refreshed.
