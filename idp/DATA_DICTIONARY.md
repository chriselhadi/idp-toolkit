# IDP research tables

Written every run by `idp/idp/export.py` into the Drive folder `IDP_Data/tables`, one CSV per table per day:
`<table> YYYY-MM-DD.csv`. Columns never change within a schema version, so a month or a year is one concatenation
(`pandas.concat(map(pd.read_csv, glob("abx_courses *.csv")))`). Dates are ISO `YYYY-MM-DD`. Every table is keyed by
`pid`, the stable patient id the pipeline assigns on first appearance and carries across days and spelling changes.

Identifiers (MRN, name, aliases) live only in `identifiers`. Share the other tables without it and the data set is
pseudonymised.

| Table | One row per | Columns |
|---|---|---|
| patient_days | patient on the census, per day | date, pid, active, new, uc, room, ward_group, fellow, tags, n_issues, n_running_abx, n_micro, n_pendings, fever, pressors, resp, one_liner, first_seen, days_on_service |
| abx_courses | antimicrobial line, per day | date, pid, drug, route, freq, issue, running, start, start_approx, stop, days, n_segments, note, line |
| abx_segments | administration window | date, pid, drug, seg, start, start_approx, end, end_approx, open, single, days |
| micro | resulted or pending specimen, per day | date, pid, collected, prior, specimen, status (positive, prelim, pending, negative), result, to_verify, text |
| issues | ID issue, per day | date, pid, rank, dx, onset, onset_text, facts, status, n_abx |
| pendings | awaited item, per day | date, pid, item, since, age_days, gate, text |
| verification | finding of the cross-day checks | date, id, severity, code, pid, key, message, acknowledged |
| identifiers | patient known to the state | date, pid, mrn, name, aliases, first_seen, last_seen, archived |

Notes
- `start_approx` / `end_approx` true: the date comes from the AS list only (pharmacy verification, not administration).
- `days` sums the segments, so a drug held and restarted is not inflated.
- The daily snapshot design means a course appears on every day it is on record; deduplicate on (pid, drug, start)
  for course-level analysis, and take the last date per course for its final state.
- `IDP Dashboard YYYY-MM-DD.json` in the same folder holds the full structured day the app reads (schema 1).
