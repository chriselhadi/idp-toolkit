#!/usr/bin/env python3
"""Render column 1 for every census patient (DOCX text with Update:, recap text without), in ward order.

Usage: render.py <synth.py> <census.json> <today ISO> <outdir>
Writes outdir/render.json and outdir/recap_concise.txt. Prints counts only.
"""
import sys, os, re, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import WARD_ORDER, jload, jdump, iso_from_ddmm, ddmm
from validate_synth import load_synth, ABX_RE, PEND_RE


def seg_days(segs, today):
    """Sum of days inside segments; open segment ends today. Returns int or None if any date unknown."""
    y = int(today[:4]); total = 0
    for seg in segs.split(", "):
        m = re.match(r"^~?(\d{2}/\d{2})-~?(\d{2}/\d{2})?$", seg)
        if m:
            a = iso_from_ddmm(m.group(1), y); b = iso_from_ddmm(m.group(2), y) if m.group(2) else today
            if not a or not b:
                return None
            if a > today:  # a start after today means the drug is dated last year
                a = iso_from_ddmm(m.group(1), y - 1)
            total += (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1
        elif seg.startswith("x1 "):
            total += 1
        else:
            return None
    return total


def abx_line(ab, today):
    m = ABX_RE.match(ab)
    if not m:
        return ab
    d = seg_days(m.group("segs"), today)
    core = ab if not m.group("note") else ab[:ab.rfind(" (")]
    note = " (%s)" % m.group("note") if m.group("note") else ""
    if d is None:
        return core + note
    return "%s D%d%s" % (core, d, note)


def pend_line(pe, today):
    m = PEND_RE.match(pe)
    if not m:
        return pe
    iso = iso_from_ddmm(m.group("date"), int(today[:4]))
    age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(iso)).days if iso else None
    tail = " -> " + m.group("gate") if m.group("gate") else ""
    if age is not None and age > 3:
        return "%s (%s, d%d)%s" % (m.group("item"), m.group("date"), age, tail)
    return "%s (%s)%s" % (m.group("item"), m.group("date"), tail)


def render_patient(c, e, today, with_update):
    L = []
    head = "%s %s" % (c["room"], c["name"])
    if c.get("new") or "new" in c.get("tags", []):
        head += " (new)"
    if "uc" in c.get("tags", []):
        head += " (UC)"
    if c.get("fellow"):
        head += " [%s]" % c["fellow"]
    L.append(head)
    L.append(e["one_liner"])
    if with_update:
        L.append("Update: " + "; ".join(e["updates"]))
    for i, iss in enumerate(e["issues"]):
        L.append("%d. %s" % (i + 1, iss["dx"]))
        for ab in iss["abx"]:
            L.append("   " + abx_line(ab, today))
    if e["abx_other"]:
        L.append("Abx (unlinked): " + "; ".join(abx_line(ab, today) for ab in e["abx_other"]))
    if e["micro"]:
        L.append("Micro: " + "; ".join(e["micro"]))
    if e["vitals"]:
        L.append("Vitals/Imaging: " + "; ".join(e["vitals"]))
    if e["pendings"]:
        L.append("Pending: " + "; ".join(pend_line(p, today) for p in e["pendings"]))
    return L


def main():
    synth, census_p, today, out = sys.argv[1:5]
    mod = load_synth(synth); census = jload(census_p); S = mod.SYNTH
    pats = []
    for c in census["patients"]:
        e = S[c["pid"]]
        pats.append({"pid": c["pid"], "room": c["room"], "group": c["group"] if c["group"] in WARD_ORDER else "Other",
                     "name": c["name"], "fellow": c.get("fellow", ""), "new": bool(c.get("new") or "new" in c.get("tags", [])),
                     "lines_docx": render_patient(c, e, today, True), "lines_recap": render_patient(c, e, today, False)})
    # recap text grouped by ward, ward order, no Update block
    R = ["ID Daily Handout, %s" % ("%s.%s.%s" % (today[8:10], today[5:7], today[:4]))]
    sp = os.path.join(out, "run_status.txt")
    if os.path.exists(sp):
        R.append(open(sp, encoding="utf-8").read().strip())
    R.append("")
    for g in WARD_ORDER:
        grp = [p for p in pats if p["group"] == g]
        if not grp:
            continue
        R.append("*%s*" % g)
        for p in grp:
            R.extend(p["lines_recap"]); R.append("")
    recap = "\n".join(R).rstrip() + "\n"
    jdump({"date": today, "patients": pats}, os.path.join(out, "render.json"))
    open(os.path.join(out, "recap_concise.txt"), "w", encoding="utf-8").write(recap)
    sizes = [sum(len(l) for l in p["lines_docx"]) for p in pats]
    print("rendered %d patients; docx chars/patient min %d max %d; recap %d chars" % (
        len(pats), min(sizes) if sizes else 0, max(sizes) if sizes else 0, len(recap)))
    for p, s in zip(pats, sizes):
        if s > 1400:
            print("WARN long entry: %s %s (%d chars)" % (p["room"], p["pid"], s))


if __name__ == "__main__":
    main()
