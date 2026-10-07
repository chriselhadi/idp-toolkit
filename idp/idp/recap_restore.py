#!/usr/bin/env python3
"""Q4f held-back records (overlay 6, 07.10.2026, item 4t).

  recap_restore.py <recap email plaintext file> <name> [<name> ...]

Reads a sent "ID Daily Recap" body and prints, for each named patient, a synth.py line
  _u("<name>", updates=[...], updates_nonid=[...])
built from that patient's "Update (ID):" and "Update (other):" lines. Paste the lines into synth.py.
"""
import sys, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import name_sim

HEAD = re.compile(r"^(\S+) (.+?)(?: \((?:new|UC|re-cs)\))* \[[A-Z?]{1,3}\]$")


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); return 2
    blocks, cur = {}, None
    for l in open(sys.argv[1], encoding="utf-8").read().splitlines():
        m = HEAD.match(l.strip())
        if m:
            cur = m.group(2); blocks[cur] = {"id": [], "other": []}; continue
        if cur and l.startswith("Update (ID): "):
            blocks[cur]["id"] = [l[len("Update (ID): "):].strip()]
        elif cur and l.startswith("Update (other): "):
            blocks[cur]["other"] = [l[len("Update (other): "):].strip()]
        elif not l.strip():
            cur = None
    rc = 0
    for want in sys.argv[2:]:
        best = max(blocks, key=lambda b: name_sim(want, b), default=None)
        if not best or name_sim(want, best) < 0.5:
            print("# NOT FOUND in the recap: %s" % want); rc = 1; continue
        b = blocks[best]
        print("_u(%r, updates=%r, updates_nonid=%r)" % (want, b["id"], b["other"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
