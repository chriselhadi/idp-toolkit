#!/usr/bin/env python3
import sys, json, re, runpy
idl, cen, syn, outp, d = sys.argv[1:6]
P = json.load(open(cen))["patients"]
WA = runpy.run_path(syn).get("WA", {})
byroom = {}
for p in P:
    byroom.setdefault(p["room"].upper(), []).append(p)
out, err, seen = ["ID Handout " + d, ""], [], set()
BAD = [(r"[–—]", "dash"), (r"\d+(\.\d+)?\s*(mg|mcg|g|units?|iu)\b", "dose"), (r"[_~`]", "WhatsApp markup"),
       (r"\*", "asterisk"), (r"\((ID email|Floors doc|ICU doc|GS doc|AS list|app edit|updates email|handoff)[^)]*\)", "source tag")]


def toks(s):
    s = re.sub(r"\([^)]*\)|\*", " ", s).lower()
    return {t for t in re.findall(r"[a-z]{2,}", s)}


def room_of(s):
    return s.strip("*").split()[0].strip("*").upper()


# Several census patients in one room (two ICU6D lines): pair the room's list lines and patients by name, best pairs
# first, over the whole list, so each line gets its own patient whatever the order of the lines.
LINES = [ln.strip() for ln in open(idl, encoding="utf-8").read().splitlines()]
PAIRED, _taken = {}, set()
_byroom_lines = {}
for i, s in enumerate(LINES):
    if s and not (s.endswith(":") and not s.startswith("*")) and len(byroom.get(room_of(s), [])) > 1:
        _byroom_lines.setdefault(room_of(s), []).append(i)
for room, idx in _byroom_lines.items():
    pairs = []
    for i in idx:
        lt = toks(" ".join(LINES[i].strip("*").split()[1:]))
        for p in byroom[room]:
            pairs.append((len(lt & toks(p["name"])) / max(1, len(lt | toks(p["name"]))), -i, p["pid"]))
    for _, ni, pid in sorted(pairs, reverse=True):
        if -ni not in PAIRED and pid not in _taken:
            PAIRED[-ni] = pid; _taken.add(pid)


def pick(i, s):
    if i in PAIRED:
        return PAIRED[i]
    cand = [p for p in byroom.get(room_of(s), []) if p["pid"] not in seen]
    return cand[0]["pid"] if cand else None


for i, s in enumerate(LINES):
    if not s: continue
    if s.endswith(":") and not s.startswith("*"):
        if out[-1] != "": out.append("")
        out += [s]; continue
    pid = pick(i, s)
    if not pid: err.append("no census pid for: " + s); continue
    seen.add(pid); body = WA.get(pid)
    if not body: err.append(pid + ": no WA entry"); body = []
    if len(body) > 6: err.append(pid + ": %d lines, max 6 under the header" % len(body))
    for b in body:
        for rx, what in BAD:
            if re.search(rx, b, re.I): err.append("%s: %s in: %s" % (pid, what, b))
    out += [s] + body + [""]
for p in P:
    if p["pid"] not in seen: err.append(p["pid"] + " on census but not in the ID list")
for k in WA:
    if k not in seen: err.append(k + ": WA entry for a patient not on the list")
txt = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
open(outp, "w", encoding="utf-8").write(txt)
print("\n".join("WA ERROR " + e for e in err) if err else "WA OK: %d patients, %d lines" % (len(seen), txt.count("\n")))
