#!/usr/bin/env python3
"""ID Active Patients email -> in/roster.txt (overlay 6, 07.10.2026; Q7c, items 4i and 4s).

  email_roster.py <email plaintext file> <out roster.txt> [--yday <yesterday's roster file>]

Every patient named anywhere in the email is on the list: roster lines ('254 Alpha Tester MJ',
'*ICU5B* Bravo Tester (new) CH', '*708B Charlie Tester (UC)* CH'), consult notes that open with a
name ('Delta Tester Admitted today ...'), and names in the updates part ('Echo').
Room from the email, else yesterday's roster, else '?' (match.py then takes the AS-list room).
Initials from the email, else yesterday's roster, else '?'. A consult-note patient is written (new).
Prints: every line written with its source, names it could not place, and yesterday's names the
email does not mention (OFF today). Never copies yesterday's lines forward.
"""
import sys, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import name_sim

ROOM = r"(?:\d{3}[A-Z]?|SCT\d*|NICU\d*[A-Z]?|PICU\d*[A-Z]?|ICU\d+[BD]?|CSU\d*[A-Z]?|CCU\d*[A-Z]?|ER(?: IN)?|\?)"
LINE = re.compile(r"^(" + ROOM + r")\s+([A-Z][A-Za-z0-9'\-]+(?:\s+[A-Za-z][A-Za-z'\-]+){1,5}?)"
                  r"((?:\s*\((?:new|UC|re-cs)\))*)\s*([A-Z]{2,3}|\?)?$")
NOTE = re.compile(r"^([A-Z][a-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3})\s+(?:was\s+)?(?:[Aa]dmitted|[Cc]onsult|[Ss]een|[Pp]resent|[Ii]s an?|\d{1,3}[- ]year)")
DEAD = re.compile(r"\b(passed away|died|expired|deceased|RIP)\b", re.I)


def opt(n):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else None


def parse_line(s):
    s = s.strip().replace("\\", "").replace("*", "")
    s = re.sub(r"\s+", " ", s)
    m = LINE.match(s)
    if not m:
        return None
    return {"room": m.group(1), "name": m.group(2).strip(), "tags": re.findall(r"\(([^)]+)\)", m.group(3) or ""),
            "init": m.group(4) or ""}


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); return 2
    txt = open(sys.argv[1], encoding="utf-8").read()
    yday = []
    if opt("--yday") and os.path.exists(opt("--yday")):
        yday = [p for p in (parse_line(l) for l in open(opt("--yday"), encoding="utf-8")) if p]
    out, unplaced, dead = [], [], []
    def yfind(name):
        best = max(yday, key=lambda y: name_sim(name, y["name"]), default=None)
        return best if best and name_sim(name, best["name"]) >= 0.5 else None
    def have(name):
        return any(name_sim(name, o["name"]) >= 0.67 for o in out)
    in_updates = False
    for raw in txt.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.match(r"^\*?updates?\b", s, re.I):
            in_updates = True; continue
        if re.match(r"^(Christopher El Hadi|Fellow\b)", s):
            break
        p = parse_line(s)
        if p and not in_updates:
            y = yfind(p["name"])
            if p["room"] == "?" and y: p["room"] = y["room"]
            if not p["init"] and y and y["init"] not in ("", "?"): p["init"], p["src"] = y["init"], "email, initials from yesterday"
            p.setdefault("src", "email line")
            if not have(p["name"]): out.append(p)
            continue
        m = NOTE.match(s)
        if m and not in_updates:
            nm = m.group(1)
            if DEAD.search(s): dead.append(nm); continue
            if not have(nm):
                y = yfind(nm)
                out.append({"room": y["room"] if y else "?", "name": nm, "tags": ["new"],
                            "init": y["init"] if y and y["init"] != "?" else "", "src": "consult note"})
            continue
        if in_updates and re.match(r"^[A-Z][a-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3}:?$", s):
            nm = s.rstrip(":")
            hit = [o for o in out if any(t.lower() == w.lower() for t in o["name"].split() for w in nm.split())]
            if hit:
                continue
            y = [p for p in yday if any(t.lower() == w.lower() for t in p["name"].split() for w in nm.split())]
            if len(y) == 1:
                out.append(dict(y[0], src="updates part, room/initials from yesterday"))
            else:
                unplaced.append(nm)
    out = [o for o in out if not any(name_sim(o["name"], d) >= 0.67 for d in dead)]
    lines = []
    for o in out:
        tags = "".join(" (%s)" % t for t in o["tags"] if t != "UC")
        if "UC" in o["tags"]:
            line = "*%s %s (UC)* %s" % (o["room"], o["name"], o["init"] or "?")
        elif "new" in o["tags"]:
            line = "*%s* %s%s %s" % (o["room"], o["name"], tags, o["init"] or "?")
        else:
            line = "%s %s%s %s" % (o["room"], o["name"], tags, o["init"] or "?")
        lines.append(line)
        print("ROSTER %-45s <- %s" % (line, o.get("src")))
    open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines) + "\n")
    off = [y for y in yday if not any(name_sim(y["name"], o["name"]) >= 0.5 for o in out)]
    for y in off:
        print("OFF today (named yesterday, not in today's email): %s %s" % (y["room"], y["name"]))
    for d in dead:
        print("OFF today (email says died): %s" % d)
    for u in unplaced:
        print("UNPLACED name in the updates part (match it by hand): %s" % u)
    print("email_roster: %d on the list, %d off vs yesterday, %d unplaced, %d with '?' initials"
          % (len(lines), len(off), len(unplaced), sum(l.endswith(" ?") for l in lines)))
    return 1 if unplaced else 0


if __name__ == "__main__":
    sys.exit(main())
