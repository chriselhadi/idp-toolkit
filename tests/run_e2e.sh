#!/usr/bin/env bash
# Two-day end-to-end dry run on fictional data. Usage: tests/run_e2e.sh [workdir]
# Day 1 (2026-09-06) starts cold; day 2 (2026-09-07) runs on day 1's out/state_new.json.
# Every check prints "CHECK <name> OK" or stops the run with exit 1. Success ends with "E2E OK: <workdir>".
set -euo pipefail
T=$(cd "$(dirname "$0")/.." && pwd); I="$T/idp/idp"; W=${1:-/tmp/idp_e2e}
rm -rf "$W"; mkdir -p "$W"
D1="$W/d1"; D2="$W/d2"; CH="$W/chain"
export TMPDIR="$W/tmp"; mkdir -p "$TMPDIR"   # drive_state.py leaves mkdtemp dirs behind; keep them in the workdir

fail() { echo "CHECK $1 FAILED${2:+: $2}"; exit 1; }
pycheck() { python3 "$T/tests/e2e_checks.py" "$@" || exit 1; }
# grepcheck <name> <fixed string> <file>
grepcheck() { if grep -qF -- "$2" "$3"; then echo "CHECK $1 OK"; else fail "$1" "'$2' not in $3"; fi; }
# build <label> <ISO date>: runs build.py in the current day dir, must end with BUILD OK
build() {
  local out
  out=$(python3 "$I/build.py" . "$1" --date "$2" --as-today in/as_today.json --ams in/ams.json 2>&1) || { echo "$out" | tail -25; fail "build_$2" "build.py exited non-zero"; }
  echo "$out" | tail -3
  grep -qx "BUILD OK" <<<"$out" || fail "build_$2" "no BUILD OK"
  echo "CHECK build_$2 OK"
}
# dosecheck <name> <python lines appended to a copy of synth.py>: the copy must fail validation with a dose error
dosecheck() {
  local f="synth_dose_$1.py" out rc=0
  { cat synth.py; printf '\n%s\n' "$2"; } > "$f"
  out=$(python3 "$I/validate_synth.py" "$f" out/census.json 2026-09-06) || rc=$?
  grep -m2 "dose" <<<"$out" || true
  [ "$rc" -eq 1 ] || fail "$1" "validate_synth.py exited $rc, expected 1"
  grep -q "ERROR .*dose '" <<<"$out" || fail "$1" "no dose error reported"
  echo "CHECK $1 OK"
}

# ---------------- Day 1: 2026-09-06, cold start ----------------
python3 "$T/tests/make_fixture.py" "$D1" 2026-09-06
cd "$D1"
python3 "$I/parse_as.py" in/as.eml in/as_today.json | tee as_parse.txt
grepcheck as_source_d1 "source=attachment:AS list 06.09.2026.XLSX" as_parse.txt
pycheck as_rows_today 2026-09-06 100090 100011
python3 "$I/as_gate.py" in/as_today.json MISSING 2026-09-06 | tee as_gate.txt
grepcheck as_gate_ok "AS GATE OK" as_gate.txt
python3 "$I/as_gate.py" in/as_today.json in/as_today.json 2026-09-06 > as_gate2.txt || true
grepcheck as_gate_identical "AS GATE WAIT: today's list is identical" as_gate2.txt
python3 "$I/match.py" MISSING in/as_today.json in/wards.json in/ams.json out --date 06.09.2026 --roster in/roster.txt
pycheck roster_lines
pycheck blank_bed_keeps_roster_room
cp "$T/tests/synth_fixture.py" synth.py
build "06 September 2026" 2026-09-06
pycheck synth_extras
out=$(python3 "$I/validate_synth.py" synth.py out/census.json 2026-09-06) || fail main_synth_dose_free "validate_synth.py failed"
grep -q "dose" <<<"$out" && fail main_synth_dose_free "$out"
echo "CHECK main_synth_dose_free OK"
dosecheck dose_in_im_detail 'SYNTH[PID["Alpha Tester One"]]["im_detail"].append("Lovenox 40 SC OD")'
dosecheck dose_in_abx_note 'SYNTH[PID["Alpha Tester One"]]["issues"][0]["abx"][0] = "Mero IV q8h 03/09- (2g)"'

# Golf left and came back: slim his record the way finalize slims an off-list one, then re-pack the
# day-1 state so the Drive chain below starts from exactly the state day 2 reads.
python3 - out/state_new.json <<'EOF'
import json, sys
p = sys.argv[1]; s = json.load(open(p, encoding="utf-8"))
pid = next(k for k, r in s["patients"].items() if r["name"] == "Golf Tester Seven")
for k in ("issues", "abx_other", "vitals", "pendings"):
    s["patients"][pid]["synth"].pop(k)
json.dump(s, open(p, "w", encoding="utf-8"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
print("slimmed %s in the day-1 state" % pid)
EOF
python3 "$I/state_io.py" pack out/state_new.json out/state_parts

# ---------------- Day 2: 2026-09-07, state from day 1 ----------------
python3 "$T/tests/make_fixture.py" "$D2" 2026-09-07
cd "$D2"
python3 "$I/email_roster.py" in/id_email.txt in/roster.txt --yday "$D1/in/roster.txt" | tee email_roster.txt
grepcheck email_roster_consult_note "Lima Tester Ten (new)" in/roster.txt
grepcheck email_roster_off "OFF today (named yesterday, not in today's email): 707A RANIYA Kilo JULIET" email_roster.txt
python3 "$I/parse_as.py" in/as.eml in/as_today.json | tee as_parse.txt
grepcheck as_source_d2 "source=attachment:AS list 07.09.2026.XLSX" as_parse.txt
pycheck as_rows_today 2026-09-07 100011 100010
python3 "$I/match.py" "$D1/out/state_new.json" in/as_today.json in/wards.json in/ams.json out --date 07.09.2026 --roster in/roster.txt
pycheck roster_lines
pycheck blank_bed_keeps_roster_room
pycheck spelling_variant_no_new_pid "$D1/out/state_new.json"
cp "$T/tests/synth_fixture.py" synth.py
build "07 September 2026" 2026-09-07
grepcheck slimmed_record_renders "302 Golf Tester Seven: previous record was slimmed" out/wa_diff.txt
pycheck synth_extras
python3 "$I/id_list.py" in/roster.txt --state "$D1/out/state_new.json" --date 2026-09-07 --email in/id_email.txt > id_list.txt
grep -A1 -x "CCU / CSU:" id_list.txt > id_list_ccu.txt || true
grepcheck id_list_ccu_group "CCU2 Hotel Tester Eight MJ" id_list_ccu.txt
python3 "$I/archive_split.py" out/archive_notes.txt out/archive 2026-09-07 || fail archive_notes_dose_free "archive_split.py refused a note"
grepcheck archive_notes_split "RANIYA Kilo JULIET" out/archive/manifest.tsv

# cross-day verification and the daily export (dashboard bundle + research tables)
python3 "$I/verify_days.py" "$D1/out/state_new.json" out/state_new.json out/census.json in/as_today.json MISSING out --date 2026-09-07 --synth synth.py | tee verify.txt
grepcheck verify_ok "VERIFY OK" verify.txt
python3 - out/state_new.json bad_state.json <<'PY'
import json, sys
s = json.load(open(sys.argv[1], encoding="utf-8"))
pid = next(k for k, r in s["patients"].items() if r["name"] == "Alpha Tester One")
s["patients"][pid]["synth"]["micro"] = []
s["patients"][pid]["synth"]["issues"][0]["abx"] = []
json.dump(s, open(sys.argv[2], "w", encoding="utf-8"))
PY
python3 "$I/verify_days.py" "$D1/out/state_new.json" bad_state.json out/census.json in/as_today.json MISSING verify_bad --date 2026-09-07 > verify_bad.txt || true
grepcheck verify_catches_dropped_drug "BLOCK E_DRUG_DROPPED:P0001:Mero" verify_bad.txt
grepcheck verify_catches_dropped_culture "BLOCK E_MICRO_DROPPED:P0001:2026-09-04 ucx" verify_bad.txt
grepcheck verify_catches_as_drug "BLOCK E_AS_DRUG_NOT_RUNNING:P0001:Mero" verify_bad.txt
python3 "$T/tests/make_ams_fixture.py" in/ams_fixture.xlsx
python3 "$I/ams_check.py" in/ams_fixture.xlsx out/state_new.json out/census.json out --date 2026-09-07 | tee ams_check.txt
grepcheck ams_check_links "AMS CHECK OK: 3 of 10 census patients linked" ams_check.txt
grepcheck ams_open_course "X_AMS_COURSE_OPEN:P0001:vanco" out/ams_check.json
grepcheck ams_culture_missing "X_AMS_CULTURE_NOT_ON_LIST:P0001:2026-09-05 blood" out/ams_check.json
grepcheck ams_finalised_active "X_AMS_FINALISED_BUT_ACTIVE:P0002" out/ams_check.json
grepcheck ams_course_not_in_sheet "X_COURSE_NOT_IN_AMS:P0003:erta" out/ams_check.json
python3 "$I/export.py" . --date 2026-09-07 | tee export.txt
grepcheck export_ok "EXPORT OK: 10 patients, 11 files" export.txt
grepcheck export_ams_link "Main sheet Sep 2026,3,4,0" "out/export/tables/patient_days 2026-09-07.csv"
grepcheck export_ams_culture "2026-09-07,P0001,Main sheet Sep 2026,4,2026-09-05,blood" "out/export/tables/ams_cultures 2026-09-07.csv"
python3 "$I/export.py" . --date 2026-09-07 --out export_split --part-chars 5000 | tee export_split.txt
grepcheck export_split_parts "IDP Dashboard 2026-09-07 (part 1 of" export_split.txt
python3 - export_split out/export <<'PY'
import glob, json, os, re, sys
parts = sorted(glob.glob(os.path.join(sys.argv[1], "IDP Dashboard 2026-09-07 (part * of *).json")),
               key=lambda p: int(re.search(r"part (\d+) of", p).group(1)))
joined = json.loads("".join(open(p, encoding="utf-8").read() for p in parts))
whole = json.load(open(os.path.join(sys.argv[2], "IDP Dashboard 2026-09-07.json"), encoding="utf-8"))
joined.pop("generated"); whole.pop("generated")
assert joined == whole, "parts do not rejoin to the whole file"
for t in glob.glob(os.path.join(sys.argv[1], "tables", "*(part 1 of*).csv")):
    assert open(t).readline() == open(t.replace("part 1 of", "part 2 of")).readline(), "a table part lost its header"
print("CHECK export_split_rejoins OK (%d parts)" % len(parts))
PY
grepcheck export_mero_course "2026-09-07,P0001,Mero,IV,q8h,Urosepsis,True,2026-09-03,False,,5,1" "out/export/tables/abx_courses 2026-09-07.csv"

# ---------------- Drive state chain: day-1 full state + day-2 patch ----------------
mkdir -p "$CH"; cd "$CH"
python3 "$I/drive_state.py" patch "$D1/out/state_new.json" "$D2/out/state_new.json" patch | tee patch.txt
grepcheck state_patch "PATCH OK" patch.txt
python3 "$I/drive_state.py" unpackchain "$D1/out/state_parts" patch rebuilt.json | tee chain.txt
grepcheck state_chain "CHAIN OK: base 2026-09-06 + 1 patch(es) 2026-09-07 -> state dated 2026-09-07" chain.txt
pycheck chain_equal rebuilt.json "$D2/out/state_new.json"

echo "E2E OK: $W"
