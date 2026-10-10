#!/usr/bin/env python3
"""AS list gate (overlay 8, 07.10.2026, Chris's decision D2).

  as_gate.py <as_today.json> <as_yday.json|MISSING> <YYYY-MM-DD>

AS GATE OK (exit 0) only when the list was parsed from a spreadsheet attachment whose name carries
today's date (dd.mm.yyyy, any prefix) AND it differs from yesterday's list (MRN, room, drug, frequency).
Otherwise AS GATE WAIT (exit 3) with the reason: fetch the AS list again at once, then every 10 minutes
until today's new list arrives.
"""
import sys, json, os


def key(a):
    return sorted((p.get("mrn") or "", p.get("room") or "", o.get("drug") or "", o.get("freq") or "")
                  for p in a.get("patients", []) for o in p.get("orders", []))


def main():
    if len(sys.argv) < 4 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); return 2
    t, y, day = sys.argv[1], sys.argv[2], sys.argv[3]
    if not os.path.exists(t):
        print("AS GATE WAIT: no parsed AS list yet"); return 3
    a = json.load(open(t, encoding="utf-8"))
    src = a.get("source_used") or ""
    dmy = "%s.%s.%s" % (day[8:10], day[5:7], day[:4])
    if not (src.startswith("attachment:") and dmy in src):
        print("AS GATE WAIT: source is %r, not an attachment named %s" % (src, dmy)); return 3
    if y != "MISSING" and os.path.exists(y) and key(a) == key(json.load(open(y, encoding="utf-8"))):
        print("AS GATE WAIT: today's list is identical to yesterday's (%d order rows)" % len(key(a))); return 3
    print("AS GATE OK: %s, %d patients, differs from yesterday" % (src, len(a.get("patients", []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
