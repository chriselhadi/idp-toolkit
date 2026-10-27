#!/usr/bin/env python3
"""Daily export: the dashboard bundle the app reads, and research tables in long format.

    python3 export.py <run dir> --date YYYY-MM-DD [--out out/export] [--part-chars N] [--max-file N] [--max-total N]

Reads from <run dir>/out: state_new.json, census.json, delta.json, run_status.txt, flags.txt, verification.json
(optional), ams_check.json (optional, from ams_check.py: the link to each patient's AMS-sheet entry and the
comparison with it), cultures.json (optional). Writes to --out (default <run dir>/out/export):

  IDP Dashboard <date>.json   one file per day, everything the app shows (census in round order, structured issues,
                              antimicrobial courses with day counts, cultures, pendings with ages, computed changes,
                              verification findings, delta, signed-off block)
  tables/<table> <date>.csv   one row per fact, keyed by pid, identical columns every day (see DATA_DICTIONARY.md):
                              patient_days, abx_courses, abx_segments, micro, issues, pendings, verification,
                              ams_courses, ams_cultures (the AMS sheet's own rows for each census patient)
  tables/identifiers <date>.csv   pid -> MRN, name, aliases. Kept apart so the other tables can be shared
                              pseudonymised by leaving this one out.

Upload each file as text/plain (CSV and JSON stay plain text in Drive). A file longer than --part-chars (default
38000, under the size one upload carries byte-exact) is split: the dashboard into "IDP Dashboard <date> (part n of
N).json", consecutive slices of the one JSON text that the reader joins in order before parsing; a table into
"<table> <date> (part n of N).csv", each part a complete CSV with the header. --max-file (default 20000) caps every
file further, so each one fits a single hand-typed upload call; --part-chars 0 keeps whole files (idp_upload.py sends
bytes, nothing is retyped).

Kept small: repeated identical sub-records, the empty rows trailing an AMS block, and empty or repeated table rows are
left out; micro results that only look alike (no specimen ID to tell them apart) are all kept. All files together stay within --max-total characters (default 120000; 0 = no cap): over it, the oldest
history days leave the dashboard first (updates, imaging, drug history, logs; every earlier daily file still has
them), then long table cells are cut, then the last rows of the largest table go. Each step prints a TRIMMED line.
Prints the file list, then "EXPORT OK: <n> patients, <k> files, <total> chars" (EXPORT FAILED, exit 1, if the
budget cannot be met).
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datamodel import parse_day, patient_record  # noqa: E402
import ams_rows as A  # noqa: E402

SCHEMA_VERSION = 1  # additive fields (ams) keep schema 1: readers ignore what they do not know
WARD_ORDER = ["7th floor", "ICU#B", "4th floor", "ICU#D", "3rd floor", "2nd floor", "SCT", "CCU/CSU", "ER IN", "Paeds"]

TABLES = {
    "patient_days": ["date", "pid", "active", "new", "uc", "room", "ward_group", "fellow", "tags", "n_issues",
                     "n_running_abx", "n_micro", "n_pendings", "fever", "pressors", "resp", "one_liner",
                     "first_seen", "days_on_service", "ams_sheet", "ams_first_row", "ams_last_row",
                     "ams_finalised"],
    "abx_courses": ["date", "pid", "drug", "route", "freq", "issue", "running", "start", "start_approx", "stop",
                    "days", "n_segments", "note", "line"],
    "abx_segments": ["date", "pid", "drug", "seg", "start", "start_approx", "end", "end_approx", "open", "single",
                     "days"],
    "micro": ["date", "pid", "collected", "prior", "specimen", "status", "result", "to_verify", "text"],
    "issues": ["date", "pid", "rank", "dx", "onset", "onset_text", "facts", "status", "n_abx"],
    "pendings": ["date", "pid", "item", "since", "age_days", "gate", "text"],
    "verification": ["date", "id", "severity", "code", "pid", "key", "message", "acknowledged"],
    "ams_courses": ["date", "pid", "ams_sheet", "ams_row", "drug", "drug_key", "indication", "start", "end", "ongoing"],
    "ams_cultures": ["date", "pid", "ams_sheet", "ams_row", "collected", "specimen_family", "text", "status",
                     "organism", "ast", "positive"],
    "identifiers": ["date", "pid", "mrn", "name", "aliases", "first_seen", "last_seen", "archived", "ams_sheet",
                    "ams_first_row", "ams_name", "ams_mrn"],
}


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_text(path):
    return open(path, encoding="utf-8").read() if os.path.exists(path) else ""


def csv_text(rows, cols, dedupe=True):
    """The table as CSV. Rows with nothing but their keys are left out; so are exact repeats unless dedupe is False
    (the micro table: its rows carry no specimen ID, so two same-day sets with the same text are two results)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    seen = set()
    for r in rows:
        r = {k: ("|".join(v) if isinstance(v, list) else v) for k, v in r.items() if k in cols}
        key = tuple(str(r.get(k, "")) for k in cols)
        if (dedupe and key in seen) or not any(r.get(k) not in (None, "") for k in cols if k not in ("date", "pid")):
            continue  # an exact repeat, or a row with nothing but its keys
        seen.add(key)
        w.writerow(r)
    return buf.getvalue()


def uniq(xs):
    """xs without exact repeats, first occurrence kept, order kept."""
    seen, out = set(), []
    for x in xs:
        k = json.dumps(x, sort_keys=True, ensure_ascii=False)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def compact_patient(r):
    """One dashboard patient without repeated identical sub-records and without the empty rows that trail an AMS
    block (an entry read too long carried hundreds of them, 26.10). "courses" is rebuilt from the deduplicated
    issues and abx_other, the way the app rebuilds it from the slim file.
    Cultures are merged only when they are the same record: "micro" entries carry no specimen ID or source row, so
    identical-looking ones stay (two same-day sets with the same text are two results, 1/2 vs 2/2 positive sets
    matters); AMS-sheet cultures merge only when the sheet row and the date are the same too (uniq on the whole
    record, row included)."""
    for k, v in list(r.items()):
        if isinstance(v, list) and k not in ("courses", "issues", "abx_other", "micro"):
            r[k] = uniq(v)
    r["issues"] = uniq([{**it, "abx": uniq(it["abx"])} for it in r["issues"]])
    r["abx_other"] = uniq(r["abx_other"])
    r["courses"] = [c for it in r["issues"] for c in it["abx"]] + r["abx_other"]
    if r.get("ams"):
        r["ams"] = {**r["ams"], "courses": uniq(r["ams"].get("courses") or []), "cultures": uniq(r["ams"].get("cultures") or [])}
    r["ams_block"] = trim_block(r.get("ams_block"))
    return r


def trim_block(b):
    """An AMS block without its trailing fully empty rows (a to-do line still pointing at a row keeps that row)."""
    if not b or not b.get("rows"):
        return b
    keep = max([t.get("row", 0) for t in b.get("todo") or []] + [0])
    n = len(b["rows"])
    while n > keep + 1 and not any(c != "" for c in b["rows"][n - 1]):
        n -= 1
    if n == len(b["rows"]):
        return b
    b = dict(b, rows=b["rows"][:n])
    if "tsv" in b:
        b["tsv"] = "\n".join(b["tsv"].split("\n")[:n])
    return b


def ward_rank(group):
    return WARD_ORDER.index(group) if group in WARD_ORDER else len(WARD_ORDER)


def build(run_dir, date):
    o = os.path.join(run_dir, "out")
    ref = dt.date.fromisoformat(date)
    state = load(os.path.join(o, "state_new.json"), {}) or {}
    census = load(os.path.join(o, "census.json"), {}) or {}
    delta = load(os.path.join(o, "delta.json"), {}) or {}
    ver = load(os.path.join(o, "verification.json"), {}) or {}
    cultures = load(os.path.join(o, "cultures.json"), None)
    ams = load(os.path.join(o, "ams_check.json"), {}) or {}
    blocks = load(os.path.join(o, "ams_blocks.json"), {}) or {}
    ams_entries = ams.get("patients") or {}
    ams_findings = ams.get("findings") or []
    render = load(os.path.join(o, "render.json"), {}) or {}

    cpat = {p["pid"]: p for p in census.get("patients") or []}
    recs = {pid: patient_record(pid, r, ref) for pid, r in (state.get("patients") or {}).items()}
    findings = (ver.get("findings") or []) + ams_findings
    changes = ver.get("changes") or {}

    patients = []
    for pid, cp in cpat.items():
        r = recs.get(pid)
        if not r:
            continue
        r = dict(r)
        r["room"] = cp.get("room") or r["room"]
        r["group"] = cp.get("group") or r["group"]
        r["fellow"] = cp.get("fellow") or r["fellow"]
        r["new"] = bool(cp.get("new"))
        r["uc"] = "uc" in (cp.get("tags") or []) or "uc" in r["tags"]
        r["orphan"] = bool(cp.get("orphan"))
        r["provenance"] = cp.get("provenance") or []
        r["as_orders"] = [{k: x.get(k) for k in ("drug", "freq", "once", "valid_from", "valid_to")}
                          for x in cp.get("as_orders") or []]
        r["as_age"], r["as_crcl"], r["as_admission"] = cp.get("as_age"), cp.get("as_crcl"), cp.get("as_admission")
        r["ams_status"] = cp.get("ams_status")
        r["findings"] = [f for f in findings if f.get("pid") == pid]
        r["changes"] = changes.get(pid, [])
        r["days_on_service"] = (ref - dt.date.fromisoformat(r["first_seen"])).days + 1 if r["first_seen"] else None
        r["ams_block"] = (blocks.get("patients") or {}).get(pid)
        e = ams_entries.get(pid)
        r["ams"] = ({k: e[k] for k in ("sheet", "first_row", "last_row", "finalised", "courses", "cultures")}
                    if e else None)
        patients.append(compact_patient(r))
    patients.sort(key=lambda p: (ward_rank(p["group"]), p["room"] or "", p["name"]))

    bundle = {
        "schema": SCHEMA_VERSION, "kind": "idp_dashboard", "date": date,
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_status": read_text(os.path.join(o, "run_status.txt")).strip(),
        "flags": [l for l in read_text(os.path.join(o, "flags.txt")).splitlines() if l.strip()],
        "counts": {"census": len(patients), "new": sum(p["new"] for p in patients), "uc": sum(p["uc"] for p in patients),
                   "running_abx": sum(1 for p in patients for c in p["courses"] if c["running"]),
                   "pendings": sum(len(p["pendings"]) for p in patients),
                   "errors": (ver.get("counts") or {}).get("ERROR", 0),
                   "blocking": (ver.get("counts") or {}).get("blocking", 0),
                   "warnings": (ver.get("counts") or {}).get("WARN", 0),
                   "ams_linked": sum(1 for p in patients if p.get("ams")),
                   "ams_review": sum(1 for f in ams_findings if f.get("severity") == "WARN")},
        "ward_order": WARD_ORDER,
        "patients": patients,
        "signed_off": render.get("signed_off") or [],
        "archived_today": census.get("archived_today") or [],
        "delta": delta,
        "verification": {"counts": ver.get("counts") or {}, "findings": [f for f in findings if not f.get("pid")]},
        "ams": {"sheets": ams.get("sheets") or [], "entries": ams.get("entries", 0), "checked": bool(ams),
                "blocks": bool(blocks)},
        # Off the ID list in the last 14 days with their AMS entry still open: data keeps arriving until it is sealed.
        "off_list_blocks": [{"pid": pid, "name": (recs.get(pid) or {}).get("name", ""), "block": trim_block(bl)}
                            for pid, bl in (blocks.get("off_list") or {}).items()],
        "cultures": {"files": [f.get("title", "") if isinstance(f, dict) else f for f in (cultures or {}).get("files") or []],
                     "off_census": (cultures or {}).get("off_census") or [],
                     "verify": [v.get("line", "") for v in (cultures or {}).get("verify") or []][:50]},
    }

    T = {k: [] for k in TABLES}
    for pid, r in recs.items():
        e = ams_entries.get(pid) or {}
        T["identifiers"].append({"date": date, "pid": pid, "mrn": r["mrn"], "name": r["name"], "aliases": r["aliases"],
                                 "first_seen": r["first_seen"], "last_seen": r["last_seen"], "archived": r["archived"],
                                 "ams_sheet": e.get("sheet", ""), "ams_first_row": e.get("first_row", ""),
                                 "ams_name": e.get("name", ""), "ams_mrn": e.get("mrn", "")})
    for p in patients:
        pid = p["pid"]
        T["patient_days"].append({
            "date": date, "pid": pid, "active": 1, "new": int(p["new"]), "uc": int(p["uc"]), "room": p["room"],
            "ward_group": p["group"], "fellow": p["fellow"], "tags": p["tags"], "n_issues": len(p["issues"]),
            "n_running_abx": sum(1 for c in p["courses"] if c["running"]), "n_micro": len(p["micro"]),
            "n_pendings": len(p["pendings"]), "fever": p["status"]["fever"], "pressors": p["status"]["pressors"],
            "resp": p["status"]["resp"], "one_liner": p["one_liner"], "first_seen": p["first_seen"],
            "days_on_service": p["days_on_service"], "ams_sheet": (p["ams"] or {}).get("sheet", ""),
            "ams_first_row": (p["ams"] or {}).get("first_row", ""), "ams_last_row": (p["ams"] or {}).get("last_row", ""),
            "ams_finalised": int(bool((p["ams"] or {}).get("finalised")))})
        for c in (p["ams"] or {}).get("courses", []):
            T["ams_courses"].append({"date": date, "pid": pid, "ams_sheet": p["ams"]["sheet"], "ams_row": c["row"],
                                     "drug": c["drug"], "drug_key": c["canon"], "indication": c["indication"],
                                     "start": c["start"], "end": c["end"], "ongoing": int(c["ongoing"])})
        for c in (p["ams"] or {}).get("cultures", []):
            T["ams_cultures"].append({"date": date, "pid": pid, "ams_sheet": p["ams"]["sheet"], "ams_row": c["row"],
                                      "collected": c["date"], "specimen_family": c["family"], "text": c["text"],
                                      "status": c["status"], "organism": c["organism"], "ast": c["ast"],
                                      "positive": int(c["positive"])})
        for c in p["courses"]:
            T["abx_courses"].append({"date": date, "pid": pid, **{k: c[k] for k in ("drug", "route", "freq", "issue",
                                     "running", "start", "start_approx", "stop", "days", "note", "line")},
                                     "n_segments": len(c["segments"])})
            for i, s in enumerate(c["segments"], 1):
                T["abx_segments"].append({"date": date, "pid": pid, "drug": c["drug"], "seg": i, **s})
        for m in p["micro"]:
            T["micro"].append({"date": date, "pid": pid, "collected": m["date"], "prior": int(m["prior"]),
                               "specimen": m["specimen"], "status": m["status"], "result": m["result"],
                               "to_verify": int(m["verify"]), "text": m["text"]})
        for i, it in enumerate(p["issues"], 1):
            T["issues"].append({"date": date, "pid": pid, "rank": i, "dx": it["dx"], "onset": it["onset"],
                                "onset_text": it["onset_text"], "facts": it["facts"], "status": it["status"],
                                "n_abx": len(it["abx"])})
        for pe in p["pendings"]:
            T["pendings"].append({"date": date, "pid": pid, **{k: pe[k] for k in ("item", "since", "age_days", "gate",
                                                                                  "text")}})
    for f in findings:
        T["verification"].append({"date": date, **{k: f.get(k, "") for k in ("id", "severity", "code", "pid", "key",
                                                                               "message", "acknowledged")}})
    return bundle, {k: csv_text(v, TABLES[k], dedupe=k != "micro") for k, v in T.items()}


def slim(bundle):
    """The daily file without what the app rebuilds exactly, so it needs fewer parts to upload (each part is one
    upload the run has to get through):
      - a patient's "courses": the drugs of each issue followed by "abx_other", in that order (datamodel);
      - each AMS block's "header" (once, as "ams_header"), its "tsv" (the rows joined by tabs and newlines) and its
        build "log" (it stays in ams_blocks.json and the AMS rows book).
    The app restores courses, header and tsv when it reads the file (lib/idp/drive.server)."""
    out = dict(bundle)
    out["slim"] = 1
    out["ams_header"] = A.HEAD

    def blk(b):
        if not b:
            return b
        x = {k: v for k, v in b.items() if k not in ("header", "tsv", "log")}
        # rows sparse: {column index: value} for the filled cells only, with the row width once. Long runs of empty
        # cells were miscounted when the file was copied into an upload (12.10: 131 empty cells came back as 129-145).
        x["width"] = max((len(r) for r in b["rows"]), default=0)
        x["rows"] = [{str(i): c for i, c in enumerate(r) if c != ""} for r in b["rows"]]
        # a to-do line that only says "<field> is empty" (or "<drug>: <field> is empty") is rebuilt from row and field
        x["todo"] = [{k: v for k, v in t.items() if not (k == "what" and v == todo_text(b["rows"], t))} for t in b["todo"]]
        return x
    out["patients"] = [{**{k: v for k, v in p.items() if k != "courses"}, "ams_block": blk(p.get("ams_block"))}
                       for p in bundle["patients"]]
    out["off_list_blocks"] = [{**o, "block": blk(o.get("block"))} for o in bundle.get("off_list_blocks") or []]
    return out


def todo_text(rows, t):
    """The default wording of a to-do line (ams_blocks.todo): "<field> is empty", on a drug row "<drug>: ..."."""
    drug = (rows[t["row"]][A.C_ABX - 1].strip() if t["row"] < len(rows) else "") if t["row"] > 0 or t["field"] in (
        "Indication/ID Diagnosis", "Actual antibiotics", "Date started", "Date ended", "Released by ID", "Duration advice") else ""
    return "%s: %s is empty" % (drug, t["field"]) if drug else "%s is empty" % t["field"]


def unslim(b):
    """What the app does on reading: the inverse of slim(). Kept here so the test proves the round trip."""
    out = dict(b)
    head = b.get("ams_header") or []

    def blk(x):
        if not x:
            return x
        rows = [[r.get(str(i), "") for i in range(x["width"])] for r in x["rows"]] if x.get("width") is not None else x["rows"]
        x = {k: v for k, v in x.items() if k != "width"}
        x["rows"] = rows
        return {**x, "header": head, "todo": [{**t, "what": t.get("what", todo_text(x["rows"], t))} for t in x["todo"]],
                "tsv": "\n".join("\t".join(c.replace("\t", " ").replace("\n", " ") for c in row) for row in x["rows"])}
    out["patients"] = [{**p, "courses": [c for it in p["issues"] for c in it["abx"]] + p["abx_other"],
                        "ams_block": blk(p.get("ams_block"))} for p in b["patients"]]
    out["off_list_blocks"] = [{**o, "block": blk(o.get("block"))} for o in b.get("off_list_blocks") or []]
    for k in ("slim", "ams_header"):
        out.pop(k, None)
    return out


def split_text(txt, limit):
    """Consecutive slices of at most `limit` characters; limit 0 = one whole file (uploaded through the app)."""
    if limit <= 0:
        return [txt]
    return [txt[i:i + limit] for i in range(0, len(txt), limit)] or [""]


def split_csv(txt, limit):
    """Complete CSVs (header + whole rows) of at most `limit` characters each; limit 0 = one whole file."""
    if limit <= 0:
        return [txt]
    lines = txt.splitlines(keepends=True)
    head, rows = lines[0], lines[1:]
    parts, cur = [], head
    for r in rows:
        if len(cur) + len(r) > limit and cur != head:
            parts.append(cur)
            cur = head
        cur += r
    parts.append(cur)
    return parts


def write_parts(folder, stem, ext, chunks):
    paths = []
    n = len(chunks)
    for i, c in enumerate(chunks, 1):
        name = "%s%s" % (stem, ext) if n == 1 else "%s (part %d of %d)%s" % (stem, i, n, ext)
        p = os.path.join(folder, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(c)
        paths.append(p)
    return paths


# Dated history the dashboard carries day after day (each day's file is kept in Drive, so the oldest entries are also
# in earlier files): (field, how an entry's date is read). The first thing dropped when the export is over budget.
HISTORY = ("updates", "updates_nonid", "imaging", "abx_history")
LOGS = ("log_id", "log_im", "carry", "since_new", "since_pending", "since_resolved")
TEXT_CAP = 160  # a table cell trimmed to fit the budget keeps this many characters


def entry_day(x, ref):
    """The day a history entry belongs to (a date), or None when it carries none."""
    if isinstance(x, dict):
        v = x.get("last") or x.get("since") or x.get("date")
        try:
            return dt.date.fromisoformat(v) if v else None
        except ValueError:
            return None
    m = re.match(r"^\s*(~?\d{1,2}/\d{1,2})\b", str(x))
    return parse_day(m.group(1), ref)[0] if m else None


def history_days(bundle, ref):
    days = set()
    for p in bundle["patients"]:
        for k in HISTORY:
            days.update(d for d in (entry_day(x, ref) for x in p.get(k) or []) if d)
        for k in LOGS:
            days.update(d for d in (entry_day(l, ref) for l in (p.get(k) or "").split("\n")) if d)
    return sorted(d for d in days if d < ref)


def drop_days_through(bundle, day, ref):
    """Remove every history entry dated `day` or earlier; returns how many went."""
    n = 0
    old = lambda x: (lambda d: d is not None and d <= day)(entry_day(x, ref))
    for p in bundle["patients"]:
        for k in HISTORY:
            v = p.get(k) or []
            p[k] = [x for x in v if not old(x)]
            n += len(v) - len(p[k])
        for k in LOGS:
            lines = (p.get(k) or "").split("\n")
            keep = [l for l in lines if not old(l)]
            if len(keep) != len(lines):
                n += len(lines) - len(keep)
                p[k] = "\n".join(keep)
    return n


def cap_cell(v, n):
    return v if len(v) <= n else v[:max(0, n - 3)] + "..."


def fit_rows(txt, limit):
    """A table whose every row fits one part: a row longer than a part has its longest cells cut."""
    if limit <= 0:
        return txt
    rows = list(csv.reader(io.StringIO(txt)))
    head = len(txt.split("\n", 1)[0]) + 1
    out, changed = [], False
    for r in rows:
        n = TEXT_CAP
        while len(csv_line(r)) > limit - head and n > 8:
            r, changed = [cap_cell(c, n) for c in r], True
            n //= 2
        out.append(r)
    return "".join(csv_line(r) for r in out) if changed else txt


def csv_line(cells):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(cells)
    return buf.getvalue()


def cap_table(txt, n=TEXT_CAP):
    """The table with every cell longer than n characters cut to n."""
    return "".join(csv_line([cap_cell(c, n) for c in r]) for r in csv.reader(io.StringIO(txt)))


def render(bundle, tables, limit):
    """[(folder, stem, ext, [chunks])] for the dashboard and every table, split at `limit` characters."""
    # ASCII only: every accented letter or non-breaking space is written as \\uXXXX, so the text survives being
    # copied into an upload (a copied non-breaking space came back as a plain space on 12.10)
    text = json.dumps(slim(bundle), ensure_ascii=True, separators=(",", ":"))
    out = [("", "IDP Dashboard %s" % bundle["date"], ".json", split_text(text, limit))]
    for k, txt in tables.items():
        out.append(("tables", "%s %s" % (k, bundle["date"]), ".csv", split_csv(fit_rows(txt, limit), limit)))
    return out


def total_chars(parts):
    return sum(len(c) for _, _, _, chunks in parts for c in chunks)


def fit_budget(bundle, tables, limit, max_total, ref):
    """Bring the export under max_total characters: oldest history days out of the dashboard first, then the tables'
    long cells cut, then the tables' last rows dropped (largest table first). Returns (parts, notes)."""
    notes = []
    parts = render(bundle, tables, limit)
    if max_total <= 0 or total_chars(parts) <= max_total:
        return parts, notes
    for day in history_days(bundle, ref):
        n = drop_days_through(bundle, day, ref)
        parts = render(bundle, tables, limit)
        if n:
            notes.append("dashboard: dropped %d history entries dated %s or earlier" % (n, day.isoformat()))
        if total_chars(parts) <= max_total:
            return parts, notes
    cut = {k: cap_table(v) for k, v in tables.items()}
    changed = [k for k in tables if cut[k] != tables[k]]
    if changed:
        tables.update(cut)
        notes.append("tables: cells cut to %d characters in %s" % (TEXT_CAP, ", ".join(changed)))
        parts = render(bundle, tables, limit)
    dropped = {}
    while total_chars(parts) > max_total:
        k = max(tables, key=lambda t: len(tables[t]))
        lines = tables[k].splitlines(keepends=True)
        if len(lines) <= 1:
            break
        over = total_chars(parts) - max_total
        n = 0
        while len(lines) > 1 and over > 0:
            over -= len(lines.pop()); n += 1
        tables[k] = "".join(lines)
        dropped[k] = dropped.get(k, 0) + n
        parts = render(bundle, tables, limit)
    for k, n in dropped.items():
        notes.append("tables: dropped the last %d rows of %s" % (n, k))
    return parts, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir"); ap.add_argument("--date", required=True); ap.add_argument("--out", default="")
    ap.add_argument("--part-chars", type=int, default=38000)
    ap.add_argument("--max-file", type=int, default=20000, help="no file longer than this (0: no cap)")
    ap.add_argument("--max-total", type=int, default=120000, help="all files together at most this long (0: no cap)")
    a = ap.parse_args()
    out = a.out or os.path.join(a.run_dir, "out", "export")
    if os.path.isdir(out):
        import shutil
        shutil.rmtree(out)  # a re-run must not leave parts of an earlier split behind
    os.makedirs(os.path.join(out, "tables"), exist_ok=True)
    bundle, tables = build(a.run_dir, a.date)
    # --part-chars 0 keeps whole files for idp_upload.py (bytes, nothing retyped); otherwise --max-file caps each file
    limit = 0 if a.part_chars <= 0 else min(x for x in (a.part_chars, a.max_file) if x > 0)
    parts, notes = fit_budget(bundle, tables, limit, a.max_total, dt.date.fromisoformat(a.date))
    files = []
    for folder, stem, ext, chunks in parts:
        files += write_parts(os.path.join(out, folder) if folder else out, stem, ext, chunks)
    for p in files:
        print("  %7d  %s" % (os.path.getsize(p), os.path.relpath(p, out)))
    for n in notes:
        print("TRIMMED %s" % n)
    total = total_chars(parts)
    if a.max_total > 0 and total > a.max_total:
        print("EXPORT FAILED: %d chars after trimming, over --max-total %d" % (total, a.max_total))
        sys.exit(1)
    print("EXPORT OK: %d patients, %d files, %d chars" % (bundle["counts"]["census"], len(files), total))


if __name__ == "__main__":
    main()
