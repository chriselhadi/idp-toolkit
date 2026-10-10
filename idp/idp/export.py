#!/usr/bin/env python3
"""Daily export: the dashboard bundle the app reads, and research tables in long format.

    python3 export.py <run dir> --date YYYY-MM-DD [--out out/export]

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
"<table> <date> (part n of N).csv", each part a complete CSV with the header. Prints EXPORT OK with the file list.
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datamodel import patient_record  # noqa: E402

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


def csv_text(rows, cols):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("|".join(v) if isinstance(v, list) else v) for k, v in r.items()})
    return buf.getvalue()


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
        e = ams_entries.get(pid)
        r["ams"] = ({k: e[k] for k in ("sheet", "first_row", "last_row", "finalised", "courses", "cultures")}
                    if e else None)
        patients.append(r)
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
        "ams": {"sheets": ams.get("sheets") or [], "entries": ams.get("entries", 0), "checked": bool(ams)},
        "cultures": {"files": (cultures or {}).get("files") or [], "off_census": (cultures or {}).get("off_census") or []},
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
    return bundle, {k: csv_text(v, TABLES[k]) for k, v in T.items()}


def split_text(txt, limit):
    """Consecutive slices of at most `limit` characters."""
    return [txt[i:i + limit] for i in range(0, len(txt), limit)] or [""]


def split_csv(txt, limit):
    """Complete CSVs (header + whole rows) of at most `limit` characters each."""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir"); ap.add_argument("--date", required=True); ap.add_argument("--out", default="")
    ap.add_argument("--part-chars", type=int, default=38000)
    a = ap.parse_args()
    out = a.out or os.path.join(a.run_dir, "out", "export")
    if os.path.isdir(out):
        import shutil
        shutil.rmtree(out)  # a re-run must not leave parts of an earlier split behind
    os.makedirs(os.path.join(out, "tables"), exist_ok=True)
    bundle, tables = build(a.run_dir, a.date)
    text = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    files = write_parts(out, "IDP Dashboard %s" % a.date, ".json", split_text(text, a.part_chars))
    for k, txt in tables.items():
        files += write_parts(os.path.join(out, "tables"), "%s %s" % (k, a.date), ".csv", split_csv(txt, a.part_chars))
    for p in files:
        print("  %7d  %s" % (os.path.getsize(p), os.path.relpath(p, out)))
    print("EXPORT OK: %d patients, %d files" % (bundle["counts"]["census"], len(files)))


if __name__ == "__main__":
    main()
