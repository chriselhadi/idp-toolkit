#!/usr/bin/env python3
"""Render the WhatsApp handoff: bite-sized, fellow to fellow, ID content only.

Usage: render_wa.py <synth.py> <census.json> <state_matched.json|MISSING> <today ISO> <outdir>
Writes outdir/whatsapp.txt, outdir/wa_dropped.txt, outdir/wa_diff.txt.

Content rules (set by Chris, 08.09.2026):
- ID only: diagnosis, findings, treatments (with switch arrows and start/stop dates), rationale, pendings.
- No dose, no frequency. Route printed only when it is not the default IV.
- No length cap: a complex case is allowed to run long.
- No commentary about the run, the sources, the toolkit or what should be edited.
- Inherit, do not rewrite: the block is a pure function of the synth entry, so an
  unchanged entry renders byte-identical to yesterday. wa_diff.txt lists every line
  that moved, so any change that is not backed by a source change is visible.
"""
import sys, os, re, difflib, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import WARD_ORDER, jload, jdump, iso_from_ddmm
from validate_synth import load_synth, ABX_RE, DX_RE, PEND_RE

# Vitals/imaging lines worth carrying into an ID handoff. Anything else is dropped
# to wa_dropped.txt rather than deleted silently.
ID_KEEP = re.compile(
    r"tmax|febrile|fever|afebrile|temp\b|wbc|anc\b|neutroph|crp|procal|lactate|"
    r"trough|peak|level|galactomannan|antigen|toxin|pcr|cx\b|culture|screen|"
    r"consolidat|infiltrat|cavit|abscess|empyema|effusion|collection|pneumon|"
    r"pyelo|cholecyst|cholangit|drain|nodul|ground glass|gg[ o]|hydropneumo|"
    r"stranding|thicken|candida|mrsa|esbl|ampc|cre\b|colonis", re.I)


def dmy(iso):
    return "%s/%s" % (iso[8:10], iso[5:7]) if iso else None


def seg_bounds(segs, year):
    """(first start ISO, last stop ISO or None) for a segment list; None start if unparseable."""
    first, last, open_end = None, None, False
    for seg in segs.split(", "):
        m = re.match(r"^~?(\d{2}/\d{2})-~?(\d{2}/\d{2})?$", seg.strip())
        if m:
            a = iso_from_ddmm(m.group(1), year)
            b = iso_from_ddmm(m.group(2), year) if m.group(2) else None
        else:
            m2 = re.match(r"^x1 ~?(\d{2}/\d{2})$", seg.strip())
            if not m2:
                continue
            a = b = iso_from_ddmm(m2.group(1), year)
        if a and (first is None or a < first):
            first = a
        if b is None:
            open_end = True
        elif last is None or b > last:
            last = b
    return first, (None if open_end else last)


def days(segs, today):
    y = int(today[:4]); total = 0
    for seg in segs.split(", "):
        m = re.match(r"^~?(\d{2}/\d{2})-~?(\d{2}/\d{2})?$", seg.strip())
        if m:
            a = iso_from_ddmm(m.group(1), y); b = iso_from_ddmm(m.group(2), y) if m.group(2) else today
            if not a or not b:
                return None
            if a > today:
                a = iso_from_ddmm(m.group(1), y - 1)
            total += (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1
        elif seg.strip().startswith("x1 "):
            total += 1
        else:
            return None
    return total


def drug_text(ab, today):
    """'Mero IV q8h 06/09- (note)' -> ('Mero 06/09- D3 (note)', first_start, last_stop)."""
    m = ABX_RE.match(ab)
    if not m:
        return ab, None, None
    route = m.group("route") or ""
    head = m.group("drug") + ("" if route in ("", "IV") else " " + route)
    segs = m.group("segs")
    d = days(segs, today)
    txt = "%s %s%s" % (head, segs, " D%d" % d if d is not None else "")
    if m.group("note"):
        txt += " (%s)" % m.group("note")
    a, b = seg_bounds(segs, int(today[:4]))
    return txt, a, b


def rx_line(abx, today):
    """Drugs in start-date order, separated by '; '.

    An earlier version chained non-overlapping drugs with '>' to show switches. It was
    wrong: two unrelated agents that merely fail to overlap (an aminoglycoside stopping
    the day a nitroimidazole starts) rendered as a switch that never happened. Sequence
    is already visible from the dates; the real switches are stated in the Why line,
    where they are written deliberately rather than inferred.
    """
    parsed = []
    for ab in abx:
        txt, a, _b = drug_text(ab, today)
        parsed.append((a or "9999", txt))
    parsed.sort()
    return "; ".join(t for _a, t in parsed)


def pend_text(pe, today):
    m = PEND_RE.match(pe)
    if not m:
        return pe
    iso = iso_from_ddmm(m.group("date"), int(today[:4]))
    age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(iso)).days if iso else None
    tail = " -> " + m.group("gate") if m.group("gate") else ""
    stamp = "%s, d%d" % (m.group("date"), age) if age is not None and age > 3 else m.group("date")
    return "%s (%s)%s" % (m.group("item"), stamp, tail)


def covered(micro, said):
    """True when the issue text above already carries this micro result.

    Word overlap, not substring: the issue prose says the same thing in its own words
    ('CMV PCR borderline positive at Ct 34 on 18/08' vs '18/08 CMV PCR borderline
    positive, Ct 34'). Threshold is deliberately high so nothing unique is dropped.
    """
    w = [x for x in re.findall(r"[a-z0-9]{3,}", micro.lower()) if x not in ("the", "and", "for", "with", "prior")]
    if len(w) < 4:
        return False
    return sum(1 for x in w if x in said) / len(w) >= 0.85


def id_line(one_liner):
    """Keep the identity and the ID-relevant background; drop the internal-medicine course."""
    s = one_liner
    for cut in ("; IM:", ", IM:", "; FM:", " IM:"):
        i = s.find(cut)
        if i > 0:
            s = s[:i]
    return s.rstrip(" ;.,") + "."


def block(c, e, today, dropped):
    L = []
    head = "%s %s" % (c["room"], c["name"])
    if c.get("new") or "new" in c.get("tags", []):
        head += " (new)"
    if "uc" in c.get("tags", []):
        head += " (UC)"
    L.append(head)
    L.append(id_line(e["one_liner"]))
    for i, iss in enumerate(e["issues"], 1):
        m = DX_RE.match(iss["dx"])
        if m:
            L.append("%d. %s (%s)" % (i, m.group("dx"), m.group("date")))
            L.append("   Findings: " + m.group("facts"))
            if iss["abx"]:
                L.append("   Rx: " + rx_line(iss["abx"], today))
            L.append("   Why: " + m.group("status"))
        else:
            L.append("%d. %s" % (i, iss["dx"]))
            if iss["abx"]:
                L.append("   Rx: " + rx_line(iss["abx"], today))
    if e["abx_other"]:
        L.append("Rx (unlinked): " + rx_line(e["abx_other"], today))
    # A micro result already spelled out inside an issue's Findings is not repeated here.
    said = " ".join(L).lower()
    micro = [m for m in e["micro"] if not covered(m, said)]
    for m in e["micro"]:
        if m not in micro:
            dropped.append("%s %s: [micro, already in an issue] %s" % (c["room"], c["name"], m))
    if micro:
        L.append("Micro: " + "; ".join(micro))
    keep = [v for v in e["vitals"] if ID_KEEP.search(v)]
    for v in e["vitals"]:
        if v not in keep:
            dropped.append("%s %s: %s" % (c["room"], c["name"], v))
    if keep:
        L.append("Labs: " + "; ".join(keep))
    if e["pendings"]:
        L.append("Pending: " + "; ".join(pend_text(p, today) for p in e["pendings"]))
    return L


def main():
    synth_p, census_p, state_p, today, out = sys.argv[1:6]
    S = load_synth(synth_p).SYNTH
    census = jload(census_p)
    prev = {}
    if state_p.upper() != "MISSING" and os.path.exists(state_p):
        for pid, rec in (jload(state_p).get("patients") or {}).items():
            # A patient first seen today has only the placeholder keys, nothing to inherit.
            if (rec.get("synth") or {}).get("one_liner"):
                prev[pid] = rec["synth"]

    dropped, diffs, out_lines = [], [], []
    stamp = "%s.%s.%s" % (today[8:10], today[5:7], today[:4])
    out_lines.append("ID handoff %s" % stamp)
    out_lines.append("")
    for g in WARD_ORDER:
        grp = [c for c in census["patients"] if (c["group"] if c["group"] in WARD_ORDER else "Other") == g]
        if not grp:
            continue
        out_lines.append("*%s*" % g)
        for c in grp:
            e = S[c["pid"]]
            new = block(c, e, today, dropped)
            out_lines.extend(new); out_lines.append("")
            pe = prev.get(c["pid"])
            if pe:
                old = block(c, pe, today, [])
                d = [l for l in difflib.unified_diff(old, new, lineterm="", n=0)
                     if l and l[0] in "+-" and not l.startswith(("+++", "---"))]
                if d:
                    diffs.append("%s %s" % (c["room"], c["name"]))
                    diffs += ["  " + x for x in d]
                    diffs.append("")
            else:
                diffs.append("%s %s: new block, nothing to inherit" % (c["room"], c["name"]))
                diffs.append("")

    txt = "\n".join(out_lines).rstrip() + "\n"
    assert "—" not in txt and "–" not in txt, "dash in whatsapp text"
    open(os.path.join(out, "whatsapp.txt"), "w", encoding="utf-8").write(txt)
    open(os.path.join(out, "wa_dropped.txt"), "w", encoding="utf-8").write("\n".join(dropped) + ("\n" if dropped else ""))
    open(os.path.join(out, "wa_diff.txt"), "w", encoding="utf-8").write("\n".join(diffs) + ("\n" if diffs else ""))
    changed = sum(1 for l in diffs if l and not l.startswith("  "))
    print("whatsapp: %d chars, %d patients, %d with changes vs yesterday, %d non-ID lines dropped"
          % (len(txt), len(census["patients"]), changed, len(dropped)))


if __name__ == "__main__":
    main()
