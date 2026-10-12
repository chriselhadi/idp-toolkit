#!/usr/bin/env python3
"""AS list gate (overlay 8, 07.10.2026; amendment Y1, Chris 11.10.2026).

  as_gate.py <as_today.json> <as_yday.json|MISSING> <YYYY-MM-DD>

Today's AS List email always carries today's updated list, inline in the body or attached. So the list passes
(AS GATE OK, exit 0) when it was received today (received_date) and the email subject, the attachment name or the
source carries today's date (dd.mm.yyyy), whatever the source (attachment or body). A list identical to
yesterday's passes too, with a note. AS GATE WAIT (exit 3) only when no AS list received today exists yet: fetch
again at once, then every 10 minutes.
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
    received = a.get("received_date")
    dated = any(dmy in str(x or "") for x in (a.get("subject"), src, a.get("filename_date")))
    if received and received != day:
        print("AS GATE WAIT: the newest AS list was received %s, not today (%s)" % (received, day)); return 3
    if not (received == day or dated):
        print("AS GATE WAIT: no AS list received today (%s); source %r" % (dmy, src)); return 3
    if not a.get("patients"):
        print("AS GATE WAIT: today's AS list parsed to no patients (%s)" % src); return 3
    same = y != "MISSING" and os.path.exists(y) and key(a) == key(json.load(open(y, encoding="utf-8")))
    print("AS GATE OK: %s, %d patients, %s" % (src, len(a.get("patients", [])),
                                                "identical to yesterday's list (noted)" if same else "differs from yesterday"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
