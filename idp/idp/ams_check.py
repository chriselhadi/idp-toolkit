#!/usr/bin/env python3
"""Compare today's ID record with each patient's block in the AMS workbook (read only).

    python3 ams_check.py <ams_spill.json|ams.xlsx> out/state_new.json out/census.json out --date YYYY-MM-DD

The AMS workbook is the service's long record; the morning run is the daily one. For every patient on today's
census this finds their CURRENT entry in the workbook (latest "Main sheet" tab, last entry of the matching block,
as ams_rows.py does) and compares:
  * antimicrobials: a course the sheet shows as ongoing (no end date, or "Ongoing") that is not running on today's
    record; a drug running today with no row in the sheet; a course the sheet closed that is still running today
  * cultures: a positive culture in the sheet (organism column filled, last 21 days) that today's micro list lacks
  * identity: the sheet's MRN against the record's; no entry at all; an entry already shaded as finalised while the
    patient is still on the service
Findings carry codes starting with X_ and are informational: they never block a send. The workbook is never written.

Writes out/ams_check.json: per patient the entry's location (tab, first and last row: the link between the daily
record and the AMS register used by the research tables), the courses and cultures as the sheet holds them, and
the findings. Prints AMS CHECK OK with counts.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ams_rows as A  # noqa: E402  (workbook reading, entry finding, drug vocabulary)
from datamodel import patient_record  # noqa: E402

C_CX, C_PRELIM, C_ORG, C_AST = 30, 31, 32, 33
CULTURE_WINDOW = 21
# Pipeline short forms the AMS vocabulary in ams_rows.py does not catch on its own.
PRE = {"cefe": "cefepime", "zerb": "zerbaxa", "amox": "amoxicillin", "flagyl": "metronidazole",
       "tavanic": "levofloxacin", "augmentin": "augmentin", "bactrim": "bactrim", "colis": "colistin"}


def drug_key(name):
    t = (name or "").strip().split()
    t = t[0] if t else ""
    return A.canon(PRE.get(t.lower(), t))


def same_drug(a, b):
    """Two drug keys name the same drug: equal, or one a prefix of the other (Vori / Voriconazole)."""
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


NEG = re.compile(r"no growth|negative|\bneg\b|sterile|normal flora|commensal|contaminant|pending|^\s*-\s*$", re.I)


def cell_date(cell, ref):
    """A date from a cell: a real date value, or dd/mm[/yy] text. None when there is none."""
    v = cell.value
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    m = re.search(r"(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?", str(v or ""))
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = int(m.group(3)) if m.group(3) else ref.year
    y = y + 2000 if y < 100 else y
    try:
        out = dt.date(y, mo, d)
    except ValueError:
        return None
    if not m.group(3) and out > ref + dt.timedelta(days=31):
        out = out.replace(year=out.year - 1)
    return out


def family(s):
    t = (s or "").lower()
    for fam, rx in (("blood", r"bcx|blood|bactec|hemoc"), ("urine", r"ucx|urine"),
                    ("respiratory", r"spx|sput|dta|\bbal\b|trache|bronch|resp"),
                    ("screen", r"\brs\b|\bns\b|axs|screen|rectal|nasal|axill|mdro"),
                    ("stool", r"\bss\b|stool|c\.? ?diff"), ("csf", r"csf"),
                    ("catheter", r"\bkt\b|tip|cathet"), ("wound", r"wound|pus|swab|absc|tissue|bone"),
                    ("fluid", r"\bpf\b|pleur|ascit|fluid|drain|synov|perito")):
        if re.search(rx, t):
            return fam
    return "other" if t.strip() else ""


def read_entry(ws, s, e, rows, ref):
    courses, cultures = [], []
    for r in range(s, e + 1):
        row = rows[r - 1]
        drug = str(row[A.C_ABX - 1].value or "").strip()
        if drug:
            end_raw = str(row[A.C_END - 1].value or "").strip()
            end = cell_date(row[A.C_END - 1], ref)
            courses.append({"row": r, "drug": drug, "canon": drug_key(drug),
                            "indication": str(row[A.C_IND - 1].value or "").strip(),
                            "start": (cell_date(row[A.C_START - 1], ref) or None) and cell_date(row[A.C_START - 1], ref).isoformat(),
                            "end": end.isoformat() if end else None,
                            "ongoing": not end or end_raw.lower().startswith("ongo")})
        cx = str(row[C_CX - 1].value or "").strip()
        org = str(row[C_ORG - 1].value or "").strip()
        if cx or org:
            d = cell_date(row[C_CX - 1], ref)
            cultures.append({"row": r, "text": cx, "date": d.isoformat() if d else None, "family": family(cx),
                             "status": str(row[C_PRELIM - 1].value or "").strip(), "organism": org,
                             "ast": str(row[C_AST - 1].value or "").strip(),
                             "positive": bool(org) and not NEG.search(org)})
    finalised = A.is_orange(A.rgb(rows[s - 1][A.C_NAME - 1])) or A.is_orange(A.rgb(rows[s - 1][0]))
    mrn = str(rows[s - 1][A.C_MRN - 1].value or "").split(".")[0].strip()
    name = str(rows[s - 1][A.C_NAME - 1].value or "").strip()
    return {"sheet": ws.title, "first_row": s, "last_row": e, "mrn": mrn, "name": name,
            "finalised": finalised, "courses": courses, "cultures": cultures}


def compare(p, entry, ref):
    out = []
    add = lambda sev, code, key, msg: out.append({
        "id": "%s:%s:%s" % (code, p["pid"], key or "-"), "severity": sev, "code": code, "pid": p["pid"],
        "name": p["name"], "room": p["room"], "key": key, "message": msg})
    if entry is None:
        new = (p.get("days_on_service") or 0) <= 1
        add("INFO" if new else "WARN", "X_NOT_IN_AMS", "",
            "No entry in the AMS sheet yet" + (" (new today)." if new else ": add the block or check the name and MRN."))
        return out
    where = "%s rows %d-%d" % (entry["sheet"], entry["first_row"], entry["last_row"])
    if entry["mrn"].isdigit() and p["mrn"] and entry["mrn"] != p["mrn"]:
        add("WARN", "X_MRN_DIFFERS", "%s/%s" % (p["mrn"], entry["mrn"]),
            "MRN %s on the ID record, %s in the AMS sheet (%s)." % (p["mrn"], entry["mrn"], where))
    if entry["finalised"]:
        add("WARN", "X_AMS_FINALISED_BUT_ACTIVE", where,
            "The AMS entry (%s) is shaded as finalised but the patient is still on the ID list: open a new entry?" % where)
    running = {drug_key(c["drug"]): c for c in p["courses"] if c["running"]}
    ams_open = {c["canon"]: c for c in entry["courses"] if c["ongoing"]}
    ams_any = {c["canon"] for c in entry["courses"]}
    has = lambda k, keys: any(same_drug(k, x) for x in keys)
    for k, c in ams_open.items():
        if not has(k, running):
            add("WARN", "X_AMS_COURSE_OPEN", "%s %s" % (k, c["start"] or "?"),
                "AMS sheet shows %s ongoing since %s (row %d); it is not running on today's record. Close it in the sheet "
                "or check the record." % (c["drug"], c["start"] or "?", c["row"]))
    for k, c in running.items():
        if not has(k, ams_any):
            add("INFO", "X_COURSE_NOT_IN_AMS", k, "%s D%d is running but has no row in the AMS sheet yet (%s)."
                % (c["drug"], c["days"], where))
        elif not has(k, ams_open):
            closed = [x for x in entry["courses"] if same_drug(x["canon"], k) and x["end"]]
            last = max(closed, key=lambda x: x["end"]) if closed else None
            if last and (not c["start"] or last["end"] >= c["start"]):
                add("WARN", "X_AMS_STOPPED_STILL_RUNNING", k, "AMS sheet closed %s on %s (row %d) but it is running "
                    "on today's record (D%d)." % (c["drug"], last["end"], last["row"], c["days"]))
    for cx in entry["cultures"]:
        if not cx["positive"] or not cx["date"]:
            continue
        if (ref - dt.date.fromisoformat(cx["date"])).days > CULTURE_WINDOW:
            continue
        hit = any(m["date"] and abs((dt.date.fromisoformat(m["date"]) - dt.date.fromisoformat(cx["date"])).days) <= 1
                  and (cx["family"] in ("", "other") or family(m["specimen"]) in (cx["family"], "other"))
                  for m in p["micro"])
        if not hit:
            add("WARN", "X_AMS_CULTURE_NOT_ON_LIST", "%s %s" % (cx["date"], cx["family"]),
                "AMS sheet has %s: %s (row %d). Not in today's micro list." % (cx["text"] or cx["date"], cx["organism"], cx["row"]))
    return out


def run(a):
    ref = dt.date.fromisoformat(a.date)
    state = json.load(open(a.state, encoding="utf-8"))
    census = json.load(open(a.census, encoding="utf-8"))
    wb = A.load(a.workbook)
    entries = A.index_entries(wb)
    recs = {pid: patient_record(pid, r, ref) for pid, r in (state.get("patients") or {}).items()}
    out = {"date": a.date, "sheets": sorted({ws.title for ws, *_ in entries}), "entries": len(entries),
           "patients": {}, "findings": []}
    for cp in census.get("patients") or []:
        p = recs.get(cp["pid"])
        if not p:
            continue
        p["room"] = cp.get("room") or p["room"]
        first = p.get("first_seen")
        p["days_on_service"] = (ref - dt.date.fromisoformat(first)).days + 1 if first else None
        names = [p["name"]] + list(p.get("aliases") or [])
        hit = A.find_entry(entries, (p["mrn"] or "").strip(), names)
        entry = read_entry(*hit, ref) if hit else None
        out["patients"][p["pid"]] = entry
        out["findings"] += compare(p, entry, ref)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "ams_check.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    linked = sum(1 for v in out["patients"].values() if v)
    sev = {s: sum(1 for x in out["findings"] if x["severity"] == s) for s in ("WARN", "INFO")}
    print("AMS CHECK OK: %d of %d census patients linked to an AMS entry (%d entries in %d tabs); %d to review, %d notes"
          % (linked, len(out["patients"]), len(entries), len(out["sheets"]), sev["WARN"], sev["INFO"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workbook"); ap.add_argument("state"); ap.add_argument("census"); ap.add_argument("out")
    ap.add_argument("--date", required=True)
    run(ap.parse_args())


if __name__ == "__main__":
    main()
