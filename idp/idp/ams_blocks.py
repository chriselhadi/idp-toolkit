#!/usr/bin/env python3
"""Ready-to-paste AMS row blocks for every patient, with the edits made in the app applied.

    python3 ams_blocks.py <ams_spill.json|ams.xlsx|MISSING> out/state_new.json out/census.json out --date YYYY-MM-DD \
        [--edits in/edits.json]

One builder serves both outputs, so the app and the daily "AMS rows" book can never disagree:
  * ams_rows.py (the book sent each morning, one fellow's patients) calls build_block() per patient;
  * this script writes out/ams_blocks.json for every census patient plus the off-list patients whose AMS entry is
    still open, which export.py puts in the daily file for the app.

For each patient: where the current entry sits in the AMS workbook (tab, first and last row) or that there is none
(a drafted new block), the block with every cell as the sheet shows it plus what the run learnt since (ams_rows.py
refresh), the AMS-sheet fields still empty (the to-do list the app shows), and the edits made in the app.

Edits (edits.py collects them from the Drive folder IDP_Data/edits into in/edits.json) are applied last, oldest first,
so a later edit wins. Keys are semantic, not row numbers, so an edit still lands after the block grows:
  patient   {"fields": {"<AMS column header>": value}}                       -> first row
  abx       {"key": {"drug", "start"}, "fields": {...}}                       -> the row of that course, else a new row
  culture   {"key": {"date", "specimen"}, "fields": {...}}                    -> the row of that specimen, else a new row
  plan      {"fields": {"Plan": text, "Plan Date": "dd/mm/yy"}}              -> a new plan line unless already there
  finalise  {}                                                               -> marks the block ready to finalise
A value with a dose figure is refused (S6) and listed, never applied. The workbook is never written.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ams_rows as A  # noqa: E402
from datamodel import DOSE_RE  # noqa: E402

COL = {h: i + 1 for i, h in enumerate(A.HEAD) if h}          # header -> 1-based column
C_REL, C_DUR, C_ATT, C_LINES, C_DCABX = 25, 26, 27, 28, 29
C_CX, C_PRE, C_ORG, C_AST = 30, 31, 32, 33
ROW0_REQUIRED = ["FELLOW", "Pt name", "MRN", "Age", "Room", "weight", "Creatinine", "CrCl", "Date of Admission",
                 "Date of ID Consultation", "Chief complaint", "PMH", "Active Issues", "Attending"]
ABX_REQUIRED = ["Indication/ID Diagnosis", "Date started", "Date ended", "Released by ID", "Duration advice"]
FINALISE_REQUIRED = ["Lines", "Discharge Abx"]
NEG = re.compile(r"no growth|negative|\bneg\b|sterile|normal flora|commensal|pending|^\s*-\s*$", re.I)


def ddmmyy(iso):
    """'2026-09-03' -> '03/09/26' (the sheet's own date form, S5)."""
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
        return d.strftime("%d/%m/%y")
    except ValueError:
        return ""


def prefill(b, cp):
    """Fill empty first-row cells the AS list already knows (age, CrCl, admission date). Never overwrites."""
    r0 = b.cells[0]
    for col, val in ((A.C_AGE, cp.get("as_age")), (11, cp.get("as_crcl")),
                     (A.C_ADM, ddmmyy(cp.get("as_admission")) if cp.get("as_admission") else "")):
        if val and not r0[col - 1].strip():
            b.set(0, col, str(val))
            b.log.append("%s from the AS list" % A.HEAD[col - 1])


def _find_abx_row(b, drug, start):
    k, st = A.canon(drug), A.ddmm(start or "")
    rows = [i for i, r in enumerate(b.cells) if r[A.C_ABX - 1].strip() and A.canon(r[A.C_ABX - 1]) == k]
    same = [i for i in rows if A.ddmm(b.cells[i][A.C_START - 1]) == st] or \
           [i for i in rows if st and A.ddmm(b.cells[i][A.C_START - 1]) and A.near(A.ddmm(b.cells[i][A.C_START - 1]), st)]
    return same[-1] if same else None


def _find_cx_row(b, date, specimen):
    d = A.ddmm(date or "")
    w = A.words(specimen or "")
    for i, r in enumerate(b.cells):
        t = r[C_CX - 1]
        if not t.strip():
            continue
        if d and not any(v in t for v in A.date_variants(d)):
            continue
        if w and not (w & A.words(t)):
            continue
        return i
    return None


def apply_edits(b, edits, meta):
    """Apply one patient's edits (oldest first) to Block b. Records applied and refused edits in meta."""
    for e in sorted(edits, key=lambda x: x.get("at", "")):
        fields = {k: str(v).strip() for k, v in (e.get("fields") or {}).items() if k in COL and str(v).strip()}
        bad = [v for v in fields.values() if DOSE_RE.search(v)]
        if bad:
            meta["refused"].append({"id": e.get("id"), "why": "dose figure %r (frequencies only)" % bad[0]})
            continue
        kind = e.get("kind")
        if kind == "patient":
            for h, v in fields.items():
                if b.cells[0][COL[h] - 1] != v:
                    b.set(0, COL[h], v)
        elif kind == "abx":
            key = e.get("key") or {}
            i = _find_abx_row(b, key.get("drug") or fields.get("Actual antibiotics", ""), key.get("start") or fields.get("Date started", ""))
            if i is None:
                i = b.next_free((A.C_IND, A.C_ABX, A.C_START, A.C_END, C_REL, C_DUR))
                fields.setdefault("Actual antibiotics", key.get("drug", ""))
                fields.setdefault("Date started", key.get("start", ""))
            b.ensure(i)
            for h, v in fields.items():
                if b.cells[i][COL[h] - 1] != v:
                    b.set(i, COL[h], v)
        elif kind == "culture":
            key = e.get("key") or {}
            i = _find_cx_row(b, key.get("date"), key.get("specimen"))
            if i is None:
                i = b.next_free((C_CX, C_PRE, C_ORG, C_AST))
                fields.setdefault("Culture results/Notes", ("%s %s" % (key.get("date", ""), key.get("specimen", ""))).strip())
            b.ensure(i)
            for h, v in fields.items():
                if b.cells[i][COL[h] - 1] != v:
                    b.set(i, COL[h], v)
        elif kind == "plan":
            text, when = fields.get("Plan", ""), fields.get("Plan Date", "")
            if text and text not in b.col_text(A.C_PLAN):
                b.add_rows((A.C_PLAN, A.C_PDATE), [(text, when)])
        elif kind == "finalise":
            meta["ready_to_finalise"] = True
        else:
            meta["refused"].append({"id": e.get("id"), "why": "unknown edit kind %r" % kind})
            continue
        meta["applied"].append(e.get("id"))
    if meta["applied"]:
        b.log.append("app edits %d" % len(meta["applied"]))


def todo(b, ready):
    """The AMS fields still empty: what the sheet will be missing after this paste."""
    out = []
    r0 = b.cells[0]
    for h in ROW0_REQUIRED:
        if not r0[COL[h] - 1].strip():
            out.append({"row": 0, "field": h, "what": "%s is empty" % h})
    for i, r in enumerate(b.cells):
        drug = r[A.C_ABX - 1].strip()
        if drug:
            for h in ABX_REQUIRED:
                if not r[COL[h] - 1].strip():
                    out.append({"row": i, "field": h, "what": "%s: %s is empty" % (drug, h)})
        cx = r[C_CX - 1].strip()
        if cx:
            status, org = r[C_PRE - 1].strip(), r[C_ORG - 1].strip()
            if not status:
                out.append({"row": i, "field": "Preliminary Results", "what": "%s: Final, Preliminary or Pending?" % cx[:40]})
            elif status.lower().startswith("prelim") or status.lower().startswith("pend"):
                out.append({"row": i, "field": "Preliminary Results", "what": "%s: still %s, follow up the final" % (cx[:40], status.lower())})
            if org and not NEG.search(org) and not r[C_AST - 1].strip():
                out.append({"row": i, "field": "Antibiogram", "what": "%s: antibiogram (R:/S:) missing" % cx[:40]})
    if ready:
        for h in FINALISE_REQUIRED:
            if not r0[COL[h] - 1].strip():
                out.append({"row": 0, "field": h, "what": "to finalise: %s is empty" % h})
    return out


def build_block(p, entries, today, fellow, census_rec=None, edits=None):
    """(Block, meta) for one state patient: the sheet's current entry refreshed, or a drafted new one."""
    names = [p.get("name") or ""] + list(p.get("aliases") or [])
    hit = A.find_entry(entries, str(p.get("mrn") or "").strip(), names) if entries else None
    meta = {"location": None, "finalised": False, "status": "new", "grow": 0, "applied": [], "refused": [],
            "ready_to_finalise": False}
    if hit:
        ws, s, e, rows = hit
        fills = [[A.rgb(c) for c in rows[r - 1][:A.COLS]] + [None] * (A.COLS - len(rows[r - 1][:A.COLS]))
                 for r in range(s, e + 1)]
        share = sum(A.is_orange(h) for fr in fills for h in fr[:14]) / max(1, 14 * len(fills))
        cells = [[A.shown(c) for c in rows[r - 1][:A.COLS]] + [""] * (A.COLS - len(rows[r - 1][:A.COLS]))
                 for r in range(s, e + 1)]
        b = A.Block(cells, fills, (ws.title, s, e))
        A.refresh(b, p, today, False)
        meta.update(location={"sheet": ws.title, "first_row": s, "last_row": e}, finalised=share >= 0.7, status="update")
    else:
        b = A.skeleton(p, fellow, today)
        A.refresh(b, p, today, True)
    if census_rec:
        prefill(b, census_rec)
    if edits:
        apply_edits(b, edits, meta)
    meta["grow"] = len(b.cells) - b.orig_len
    if hit and not b.changed:
        meta["status"] = "same"
    return b, meta


def block_json(b, meta, ready_override=None):
    ready = meta["ready_to_finalise"] if ready_override is None else ready_override
    return {**meta, "header": A.HEAD, "rows": b.cells, "changed": sorted([list(x) for x in b.changed]),
            "log": b.log, "todo": todo(b, ready),
            "tsv": "\n".join("\t".join(c.replace("\t", " ").replace("\n", " ") for c in row) for row in b.cells)}


def load_edits(path):
    if not path or path == "MISSING" or not os.path.exists(path):
        return {}
    by_pid = {}
    for e in json.load(open(path, encoding="utf-8")).get("edits", []):
        if e.get("pid"):
            by_pid.setdefault(e["pid"], []).append(e)
    return by_pid


def run(a):
    today = dt.date.fromisoformat(a.date)
    state = json.load(open(a.state, encoding="utf-8"))
    census = json.load(open(a.census, encoding="utf-8"))
    wb = A.load(a.workbook) if a.workbook != "MISSING" else None
    entries = A.index_entries(wb) if wb else []
    edits = load_edits(a.edits)
    cp_by = {c["pid"]: c for c in census.get("patients") or []}
    out = {"date": a.date, "workbook": bool(wb), "patients": {}, "off_list": {}}
    n = {"update": 0, "new": 0, "same": 0, "edits": 0, "refused": 0}
    for pid, p in (state.get("patients") or {}).items():
        on = pid in cp_by
        recent_off = (not p.get("active")) and p.get("archived") and \
            str(p["archived"])[:10] >= (today - dt.timedelta(days=14)).isoformat()
        if not on and not recent_off:
            continue
        fellow = (p.get("synth") or {}).get("_fellow") or ""
        b, meta = build_block(p, entries, today, fellow, cp_by.get(pid), edits.get(pid))
        if not on and (meta["finalised"] or not meta["location"]):
            continue  # off the list: carried only while an open entry exists (P3)
        (out["patients"] if on else out["off_list"])[pid] = block_json(b, meta)
        n[meta["status"]] += 1
        n["edits"] += len(meta["applied"])
        n["refused"] += len(meta["refused"])
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "ams_blocks.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("AMS BLOCKS OK: %d on the list (%d to update, %d new, %d unchanged), %d off-list still open; "
          "%d app edits applied, %d refused" % (len(out["patients"]), n["update"], n["new"], n["same"],
                                                 len(out["off_list"]), n["edits"], n["refused"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workbook"); ap.add_argument("state"); ap.add_argument("census"); ap.add_argument("out")
    ap.add_argument("--date", required=True); ap.add_argument("--edits", default="")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
