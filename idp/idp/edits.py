#!/usr/bin/env python3
"""Collect the edits made in the AMS Register app (Today > Round) into one file the run applies.

    python3 edits.py collect <dir of downloaded edit files> in/edits.json
    python3 edits.py digest in/edits.json out/census.json [--since YYYY-MM-DD]

The app saves every edit as its own plain-text file in the Drive folder IDP_Data/edits, titled
"IDP Edit <YYYY-MM-DD> <pid> <time>.json"; nothing there is ever overwritten, so the folder is the audit trail.
`collect` reads the downloaded files (each either the edit JSON itself, or a download_file_content result holding it
as base64 "content"), checks their shape, drops duplicates by id and writes {"edits": [...]} oldest first.
`digest` prints, per census patient, the edits since a date in plain lines for synthesis: an edit by a fellow is a
source like the updates email (a stop date, a culture result, a plan) and is integrated into the record the same way.
Prints EDITS OK with counts.
"""
import base64
import glob
import json
import os
import sys

KINDS = {"patient", "abx", "culture", "plan", "finalise"}


def read_one(path):
    raw = open(path, encoding="utf-8").read()
    t = raw[raw.find("{"):] if "{" in raw else raw
    d = json.loads(t)
    if isinstance(d, dict) and "content" in d and "pid" not in d:
        d = json.loads(base64.b64decode(d["content"]).decode("utf-8"))
    return d


def problems(e):
    out = []
    if not isinstance(e, dict):
        return ["not an object"]
    for k in ("id", "pid", "at", "kind"):
        if not e.get(k):
            out.append("no %s" % k)
    if e.get("kind") not in KINDS:
        out.append("kind %r" % e.get("kind"))
    if not isinstance(e.get("fields", {}), dict):
        out.append("fields not an object")
    return out


def collect(src, dst):
    seen, edits, bad = set(), [], []
    for p in sorted(glob.glob(os.path.join(src, "*"))):
        try:
            e = read_one(p)
        except Exception as ex:
            bad.append((os.path.basename(p), "unreadable: %s" % ex))
            continue
        pr = problems(e)
        if pr:
            bad.append((os.path.basename(p), "; ".join(pr)))
            continue
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        edits.append(e)
    edits.sort(key=lambda e: e["at"])
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    json.dump({"edits": edits}, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for name, why in bad:
        print("SKIPPED %s: %s" % (name, why))
    print("EDITS OK: %d edits from %d files (%d skipped)" % (len(edits), len(edits) + len(bad), len(bad)))


def digest(src, census_path, since=""):
    edits = json.load(open(src, encoding="utf-8")).get("edits", [])
    census = json.load(open(census_path, encoding="utf-8"))
    names = {c["pid"]: "%s %s" % (c.get("room") or "?", c.get("name") or "") for c in census.get("patients") or []}
    n = 0
    for e in edits:
        if since and e["at"][:10] < since:
            continue
        who = names.get(e["pid"], "%s (off the list)" % e["pid"])
        what = ", ".join("%s: %s" % kv for kv in (e.get("fields") or {}).items())
        key = e.get("key") or {}
        keytxt = (" [%s]" % ", ".join("%s %s" % kv for kv in key.items())) if key else ""
        print("%s | %s | %s %s%s: %s" % (e["at"][:16], e.get("by", "?"), who, e["kind"], keytxt, what or "(no fields)"))
        n += 1
    print("EDITS DIGEST: %d edits%s" % (n, " since %s" % since if since else ""))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["collect"] and len(a) == 3:
        collect(a[1], a[2])
    elif a[:1] == ["digest"] and len(a) >= 3:
        digest(a[1], a[2], a[a.index("--since") + 1] if "--since" in a else "")
    else:
        print(__doc__)
        sys.exit(2)
