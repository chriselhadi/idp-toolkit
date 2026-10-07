#!/usr/bin/env python3
"""Amendment P1 (03.10.2026, Chris), overlay 6 (07.10.2026): group the ID list for the early email.
Usage: python3 id_list.py <roster lines file> [--state <state.json> --date <YYYY-MM-DD>] [--email <email.txt>]
       > out/id_list_email.txt
Order: 2nd floor, SCT, NICU, PICU, 3rd floor, 4th floor, (5th, 6th floor), 7th floor, ICU B, ICU D,
CCU/CSU, then ER and unknown rooms. Rooms sorted within a group; lines kept verbatim, except (4c):
with --state and --date a "(new)" mark is dropped (and the *room* stars with it) when the record was
first seen before --date, unless the --email text marks that name (new) today."""
import sys, re, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
GROUPS = ["2nd floor", "SCT", "NICU", "PICU", "3rd floor", "4th floor", "5th floor", "6th floor",
          "7th floor", "ICU B", "ICU D", "CCU / CSU", "ER", "Room unknown"]
def room(line):
    return line.replace("*", " ").split()[0].upper() if line.strip() else ""
def group(r):
    if r.startswith("SCT"): return "SCT"
    if r.startswith("NICU"): return "NICU"
    if r.startswith("PICU"): return "PICU"
    if r.startswith("CCU") or r.startswith("CSU"): return "CCU / CSU"
    if r.startswith("ICU"):
        return "ICU D" if r.endswith("D") else "ICU B"
    if r.startswith("ER"): return "ER"
    m = re.match(r"(\d)\d\d", r)
    if m:
        n = int(m.group(1))
        name = {2: "2nd floor", 3: "3rd floor"}.get(n, "%dth floor" % n)
        if name in GROUPS: return name
    return "Room unknown"
def key(r):
    m = re.search(r"\d+", r)
    return (int(m.group()) if m else 9999, r)
def opt(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else None
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") or not os.path.exists(sys.argv[1]):
    print(__doc__); sys.exit(2)
lines = [l.rstrip("\n") for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
st, day, em = opt("--state"), opt("--date"), opt("--email")
if st and day and os.path.exists(st):
    from common import name_sim
    recs = json.load(open(st, encoding="utf-8")).get("patients", {})
    etxt = open(em, encoding="utf-8").read() if em and os.path.exists(em) else ""
    enew = [re.sub(r"\(new\).*", "", l).replace("*", " ") for l in etxt.splitlines() if "(new)" in l]
    out2 = []
    for l in lines:
        if "(new)" in l:
            nm = re.sub(r"\([^)]*\)|\*", " ", l).split()
            nm = " ".join(nm[1:-1] if len(nm) > 2 else nm[1:])
            fs = [r.get("first_seen") for r in recs.values() if name_sim(nm, r.get("name", "")) >= 0.5]
            in_email = any(name_sim(nm, " ".join(x.split()[1:])) >= 0.6 for x in enew)
            if fs and min(fs) < day and not in_email:
                l = re.sub(r"\s*\(new\)", "", l)
                l = re.sub(r"^\*(\S+?)\*", r"\1", l)
        out2.append(l)
    lines = out2
by = {}
for l in lines:
    by.setdefault(group(room(l)), []).append(l)
out = []
for g in GROUPS:
    if g in by:
        out.append(g + ":")
        out += sorted(by[g], key=lambda l: key(room(l)))
        out.append("")
print("\n".join(out).rstrip())
