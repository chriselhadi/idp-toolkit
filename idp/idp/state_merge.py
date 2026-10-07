#!/usr/bin/env python3
"""Merge a duplicate patient record into its primary (overlay 6, 07.10.2026, item 4o).

  state_merge.py <state.json> <duplicate pid> <primary pid>          (writes state.json in place)
  state_merge.py <state.json> --find                                  (lists likely duplicates, writes nothing)

The duplicate's name and aliases become aliases of the primary, its MRN fills an empty primary MRN,
abx_history and pendings_state entries the primary lacks are added, first_seen takes the earlier date,
and the duplicate is removed from "patients" (its pid is kept in "merged": {dup: primary}).
Run it after CHAIN OK and before match.py; the next state patch carries the merge.
"""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import name_sim


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); return 2
    st = json.load(open(sys.argv[1], encoding="utf-8")); P = st["patients"]
    if sys.argv[2] == "--find":
        ids = sorted(P)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                ra, rb = P[a], P[b]
                same_mrn = ra.get("mrn") and ra.get("mrn") == rb.get("mrn")
                s = max(name_sim(x, y) for x in [ra["name"]] + ra.get("aliases", []) for y in [rb["name"]] + rb.get("aliases", []))
                if same_mrn or s >= 0.6:
                    print("possible duplicate: %s %s | %s %s | name %.2f%s" % (a, ra["name"], b, rb["name"], s, ", same MRN" if same_mrn else ""))
        return 0
    dup, pri = sys.argv[2], sys.argv[3]
    if dup not in P or pri not in P:
        print("state_merge: %s or %s not in state" % (dup, pri)); return 1
    d, p = P[dup], P[pri]
    if d.get("mrn") and p.get("mrn") and d["mrn"] != p["mrn"]:
        print("state_merge: REFUSED, different MRNs (%s vs %s): not the same patient" % (d["mrn"], p["mrn"])); return 1
    for n in [d["name"]] + d.get("aliases", []):
        if n != p["name"] and n not in p.setdefault("aliases", []):
            p["aliases"].append(n)
    if d.get("mrn") and not p.get("mrn"):
        p["mrn"] = d["mrn"]
    have = {h["drug"] for h in p.get("abx_history", [])}
    p.setdefault("abx_history", []).extend(h for h in d.get("abx_history", []) if h["drug"] not in have)
    havep = {x["item"] for x in p.get("pendings_state", [])}
    p.setdefault("pendings_state", []).extend(x for x in d.get("pendings_state", []) if x["item"] not in havep)
    if d.get("first_seen") and (not p.get("first_seen") or d["first_seen"] < p["first_seen"]):
        p["first_seen"] = d["first_seen"]
    if (d.get("last_seen") or "") > (p.get("last_seen") or ""):
        p["last_seen"] = d["last_seen"]
    st.setdefault("merged", {})[dup] = pri
    del P[dup]
    json.dump(st, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
    print("state_merge OK: %s (%s) merged into %s (%s)" % (dup, d["name"], pri, p["name"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
