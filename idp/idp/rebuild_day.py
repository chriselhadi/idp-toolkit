#!/usr/bin/env python3
"""Rebuild one day's "IDP Dashboard <date>" from what is already in Drive, when the run's own upload failed.

    python3 rebuild_day.py <run_dir> --date YYYY-MM-DD --state <state.json as of that day> \
        --tables <folder holding "patient_days <date>.csv" and "verification <date>.csv"> \
        [--workbook <live AMS workbook .xlsx | ams_spill.json | MISSING>] [--edits in/edits.json]

The daily file is only a view of the run's state, so it can be written again from:
  - the state as of that day (drive_state.py unpackchain over IDP_State: the base plus every patch up to the day);
  - that day's research tables (uploaded separately): patient_days gives who was on the list, in which room, ward
    and fellow, new or not; verification gives the day-to-day check findings;
  - the AMS workbook, read now (ams_check.py and ams_blocks.py run again, so the blocks reflect the sheet as it is);
  - the AS list snapshot kept in the state, for the overnight delta.
What the state does not keep is left empty, never guessed: the AS list orders beyond the standing drugs, and the AS
list's age, CrCl and admission date. run_status says the day was rebuilt and from what.

Writes <run_dir>/out/{state_new,census,verification,delta}.json, runs ams_check, ams_blocks and export, and prints
REBUILD OK. Upload out/export/* exactly as V4/Z says. Read only on the workbook.
"""
import argparse
import ast
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from match import compute_delta  # noqa: E402


def rows(path):
    if not os.path.exists(path):
        sys.exit("REBUILD FAILED: %s not found" % path)
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def tags_of(v):
    v = (v or "").strip()
    if v.startswith("["):
        try:
            return [str(x) for x in ast.literal_eval(v)]
        except (ValueError, SyntaxError):
            pass
    return [t for t in v.replace(";", ",").split(",") if t.strip()]


def census_from(days, state, date):
    """The day's census as the run had it, from the patient_days table (one row per patient on the list)."""
    pats = state.get("patients") or {}
    snap = {str(p.get("mrn") or ""): p for p in (state.get("as_snapshot") or {}).get("patients") or []}
    out = []
    for r in days:
        if r.get("date") != date or str(r.get("active", "1")) not in ("1", "True", "true"):
            continue
        pid = r["pid"]
        mrn = str((pats.get(pid) or {}).get("mrn") or "")
        asp = snap.get(mrn) or {}
        out.append({
            "pid": pid, "mrn": mrn, "name": (pats.get(pid) or {}).get("name", ""), "room": r.get("room", ""),
            "group": r.get("ward_group", ""), "fellow": r.get("fellow", ""), "new": r.get("new") in ("1", "True", "true"),
            "tags": tags_of(r.get("tags")), "orphan": False, "provenance": ["rebuilt"],
            # the state keeps only the standing drugs of the AS list, not each order's frequency and dates
            "as_orders": [{"drug": d, "freq": "", "once": False, "valid_from": None, "valid_to": None}
                          for d in asp.get("standing_drugs") or []],
            "as_standing": asp.get("standing_drugs") or [], "as_age": None, "as_crcl": None, "as_admission": None,
        })
    return {"date": date, "patients": out, "archived_today": [], "rebuilt": True}


def verification_from(vrows, date):
    """The day-to-day check findings as the run wrote them. X_ codes are left out: ams_check writes them again."""
    keep = [r for r in vrows if r.get("date") == date and not (r.get("code") or "").startswith("X_")]
    findings = [{k: (r.get(k) or None) if k in ("pid", "key", "acknowledged") else r.get(k, "")
                 for k in ("id", "severity", "code", "pid", "key", "message", "acknowledged")} for r in keep]
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("ERROR", "WARN", "INFO")}
    counts["acknowledged"] = sum(1 for f in findings if f["acknowledged"])
    counts["blocking"] = sum(1 for f in findings if f["severity"] == "ERROR" and not f["acknowledged"])
    return {"date": date, "counts": counts, "findings": findings, "changes": {}, "rebuilt": True}


def delta_from(state):
    """Today's AS list against the newest earlier one, both kept in the state."""
    today = state.get("as_snapshot")
    if not today:
        return {"computed": False, "reason": "no AS list in the state"}
    earlier = [h for h in state.get("as_history") or [] if (h.get("list_date") or "") < (today.get("list_date") or "")]
    if not earlier:
        return {"computed": False, "reason": "no earlier AS list in the state"}
    return compute_delta(today, max(earlier, key=lambda h: h.get("list_date") or ""))


def run(cmd):
    p = subprocess.run([sys.executable, *cmd], capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    if p.returncode:
        sys.stdout.write(p.stderr)
        sys.exit("REBUILD FAILED: %s" % os.path.basename(cmd[0]))
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir"); ap.add_argument("--date", required=True); ap.add_argument("--state", required=True)
    ap.add_argument("--tables", required=True); ap.add_argument("--workbook", default="MISSING")
    ap.add_argument("--edits", default="")
    a = ap.parse_args()
    o = os.path.join(a.run_dir, "out")
    os.makedirs(o, exist_ok=True)
    state = json.load(open(a.state, encoding="utf-8"))
    shutil.copyfile(a.state, os.path.join(o, "state_new.json"))
    census = census_from(rows(os.path.join(a.tables, "patient_days %s.csv" % a.date)), state, a.date)
    if not census["patients"]:
        sys.exit("REBUILD FAILED: nobody on the %s list in patient_days" % a.date)
    ver = verification_from(rows(os.path.join(a.tables, "verification %s.csv" % a.date)), a.date)
    delta = delta_from(state)
    for name, obj in (("census", census), ("verification", ver), ("delta", delta)):
        json.dump(obj, open(os.path.join(o, name + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    have_wb = a.workbook != "MISSING" and os.path.exists(a.workbook)
    if have_wb:
        run([os.path.join(HERE, "ams_check.py"), a.workbook, os.path.join(o, "state_new.json"),
             os.path.join(o, "census.json"), o, "--date", a.date])
    run([os.path.join(HERE, "ams_blocks.py"), a.workbook if have_wb else "MISSING", os.path.join(o, "state_new.json"),
         os.path.join(o, "census.json"), o, "--date", a.date] + (["--edits", a.edits] if a.edits else []))
    now = dt.datetime.now(dt.timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    note = ("REBUILT %s from Drive: state as of %s, the day's patient_days and verification tables%s. The original "
            "upload of this day failed. Not in the state, so left empty: AS list order details, age, CrCl, admission."
            % (now, a.date, ", the AMS workbook read now" if have_wb else " (no AMS workbook: blocks not built)"))
    open(os.path.join(o, "run_status.txt"), "w", encoding="utf-8").write(note + "\n")
    open(os.path.join(o, "flags.txt"), "w", encoding="utf-8").write(note + "\n")
    run([os.path.join(HERE, "export.py"), a.run_dir, "--date", a.date])
    print("REBUILD OK: %s, %d patients, delta %s, %d check findings kept"
          % (a.date, len(census["patients"]), "computed" if delta.get("computed") else "not computed", len(ver["findings"])))


if __name__ == "__main__":
    main()
