#!/usr/bin/env python3
"""Today's round for the app: one JSON file with the content of the recap email (30.10.2026).

    python3 round.py <run dir> --date YYYY-MM-DD [--out out/export]

The app reads cultures from the Daily Cultures Archive and history from the AMS workbooks and the register itself;
this file carries only the day's round. Order and group headers follow out/recap_email.txt (which follows the ID
list); each patient's fields come from synth.py and out/census.json. Writes "IDP Round <date>.json" and prints
"ROUND OK: <n> patients, <c> chars".
"""
import argparse
import importlib.util
import json
import os
import re
import sys

HDR = re.compile(r"^(\S+) (.+?)( \(new\))?( \(UC[^)]*\))? \[([A-Z]{2,3}|\?)\]$")
STATUS = re.compile(r"^Status: (.*)$")


def load_synth(path):
    spec = importlib.util.spec_from_file_location("synth", path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def parse_recap(txt):
    """[(group, room, name, new, uc, initials, status)] in recap order, plus the off-list lines."""
    out, off, group, in_off, cur = [], [], "", False, None
    for ln in txt.splitlines():
        s = ln.strip()
        if re.match(r"^\*[^*]+\*$", s):
            group = s.strip("*"); in_off = group.startswith("Not on the ID list"); continue
        if in_off:
            if s:
                room, _, rest = s.partition(" ")
                name, _, line = rest.partition(": ")
                off.append({"room": "" if room == "?" else room, "name": name, "line": line})
            continue
        m = HDR.match(s)
        if m:
            cur = {"group": group, "room": m.group(1), "name": m.group(2), "new": bool(m.group(3)),
                   "uc": bool(m.group(4)), "initials": "" if m.group(5) == "?" else m.group(5), "status": ""}
            out.append(cur); continue
        m = STATUS.match(s)
        if m and cur is not None:
            cur["status"] = m.group(1)
    return out, off


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir"); ap.add_argument("--date", required=True); ap.add_argument("--out", default="")
    a = ap.parse_args()
    out_dir = a.out or os.path.join(a.run_dir, "out", "export")
    recap = open(os.path.join(a.run_dir, "out", "recap_email.txt"), encoding="utf-8").read()
    census = json.load(open(os.path.join(a.run_dir, "out", "census.json"), encoding="utf-8"))
    S = load_synth(os.path.join(a.run_dir, "synth.py")).SYNTH
    by_room = {}
    for p in census.get("patients", []):
        by_room.setdefault(p.get("room", ""), []).append(p)
    rows, off = parse_recap(recap)
    groups, missing = [], []
    for r in rows:
        cands = by_room.get(r["room"], [])
        c = next((p for p in cands if p["pid"] in S), None)
        if c is None:
            missing.append(r["room"] + " " + r["name"]); continue
        e = S[c["pid"]]
        plan = e.get("id_plan") or []
        pt = {"pid": c["pid"], "mrn": str(c.get("mrn") or ""), "room": r["room"], "name": r["name"],
              "new": r["new"], "uc": r["uc"], "initials": r["initials"],
              "one_liner": e.get("one_liner", ""), "updates_id": e.get("updates", []),
              "updates_other": e.get("updates_nonid", []), "im": e.get("im_detail", []),
              "issues": [{"dx": i.get("dx", ""), "abx": i.get("abx", [])} for i in e.get("issues", [])],
              "abx_other": e.get("abx_other", []), "micro_recap": e.get("micro_recap", ""),
              "status": r["status"], "pendings": e.get("pendings", []),
              "id_plan": plan[0] if plan else "",
              "conflicts": e.get("conflicts", []),
              "not_applied": ["%s: %s" % kv for kv in (e.get("not_applied") or {}).items()]}
        if not groups or groups[-1]["header"] != r["group"]:
            groups.append({"header": r["group"], "patients": []})
        groups[-1]["patients"].append(pt)
    doc = {"date": a.date, "groups": groups, "off_list": off}
    txt = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "IDP Round %s.json" % a.date)
    open(path, "w", encoding="utf-8").write(txt)
    n = sum(len(g["patients"]) for g in groups)
    for m in missing:
        print("ROUND MISSING: %s (recap header with no synth entry)" % m)
    if missing:
        print("ROUND FAILED: %d patient(s) not placed" % len(missing)); return 1
    print("%8d  %s" % (len(txt), os.path.basename(path)))
    print("ROUND OK: %d patients, %d chars" % (n, len(txt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
