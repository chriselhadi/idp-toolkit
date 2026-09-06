#!/usr/bin/env python3
"""Write the AS List Delta Report (delta.txt + delta.html) with the AMS block, and the run-status line.

Usage: report.py <outdir> <synth.py> <today ISO> [ams.json|MISSING]
Reads outdir/census.json, delta.json, flags.txt. Writes outdir/delta.txt, delta.html, run_status.txt, flags_email.txt.
"""
import sys, os, re, html, json
sys.path.insert(0, os.path.dirname(__file__))
from common import jload, ddmm
from validate_synth import load_synth, ABX_RE


def main():
    out, synth_p, today = sys.argv[1:4]
    ams = jload(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].upper() != "MISSING" and os.path.exists(sys.argv[4]) else None
    census = jload(os.path.join(out, "census.json")); delta = jload(os.path.join(out, "delta.json"))
    flags = open(os.path.join(out, "flags.txt"), encoding="utf-8").read().splitlines() if os.path.exists(os.path.join(out, "flags.txt")) else []
    mod = load_synth(synth_p); S = mod.SYNTH
    pats = census["patients"]
    ld = census.get("list_date")
    status = []
    status.append("AS list %s" % ("%s.%s.%s" % (ld[8:10], ld[5:7], ld[:4]) if ld else "not received today"))
    if ld and ld != today: status.append("(older than today)")
    status.append("| ID Active Patients email %s" % ("received" if census.get("roster_sent") else "not received today"))
    status.append("| census %d" % len(pats))
    if delta.get("computed"):
        c = delta["counts"]; status.append("| delta: %d new, %d off, %d changed" % (c["new"], c["off"], c["changed"]))
    else:
        status.append("| delta not computed (%s)" % delta.get("reason", "no AS list"))
    if census.get("cold"): status.append("| state rebuilt cold")
    if census.get("archived_today"): status.append("| off the list today: " + ", ".join(census["archived_today"]))
    run_status = " ".join(status)
    open(os.path.join(out, "run_status.txt"), "w", encoding="utf-8").write(run_status + "\n")

    L = ["AS List Delta Report, list %s vs %s" % (ld or "none", delta.get("yday_date") or "none"), run_status, ""]
    if delta.get("computed"):
        L.append("1. New on the AS list (%d)" % len(delta["new"]))
        L += ["  %s %s: %s" % (p["room"], p["name"], ", ".join(p["drugs"]) or "-") for p in delta["new"]] or ["  none"]
        L.append(""); L.append("2. Off the AS list (%d) (restricted abx stopped or pharmacy view changed; not a discharge)" % len(delta["off"]))
        L += ["  %s %s: was on %s" % (p["room"], p["name"], ", ".join(p["drugs"]) or "-") for p in delta["off"]] or ["  none"]
        L.append(""); L.append("3. Changed (%d)" % len(delta["changes"]))
        for ch in delta["changes"]:
            bits = []
            if ch["started"]: bits.append("started " + ", ".join(ch["started"]))
            if ch["stopped"]: bits.append("stopped " + ", ".join(ch["stopped"]))
            if ch["moved"]: bits.append("moved %s -> %s" % ch["moved"])
            L.append("  %s %s: %s" % (ch["room"], ch["name"], "; ".join(bits)))
        if not delta["changes"]: L.append("  none")
        L.append(""); L.append("4. Counts: today %d standing, yesterday %d" % (delta["counts"]["today"], delta["counts"]["yday"]))
    else:
        L += ["1-4. Delta not computed: %s" % ("no AS list received today" if not ld else delta.get("reason", ""))]
    L.append(""); L.append("AMS block")
    a = census.get("ams_summary", {})
    L.append("AMS workbook status: present %d, stale %d, absent %d" % (len(a.get("present", [])), len(a.get("stale", [])), len(a.get("absent", []))))
    if a.get("stale"): L.append("  stale (no entry in 3 days): " + ", ".join(a["stale"]))
    if a.get("absent"): L.append("  absent from workbook: " + ", ".join(a["absent"]))
    # AS-list drugs with no clinical explanation: AS standing drug not tied to any issue in the synth entry
    unexpl = []
    for c in pats:
        e = S.get(c["pid"], {})
        linked = set()
        for iss in e.get("issues", []):
            for ab in iss.get("abx", []):
                m = ABX_RE.match(ab)
                if m: linked.add(m.group("drug"))
        for d in c.get("as_standing", []):
            if d not in linked:
                unexpl.append("%s %s: %s" % (c["room"], c["name"], d))
    L.append("AS-list drugs with no clinical explanation in any source (%d)" % len(unexpl)); L += ["  " + u for u in unexpl] or ["  none"]
    L.append("Single-dose-only names (ONCE orders, no ward row, no census) (%d)" % len(census.get("single_dose", []))); L += ["  " + s for s in census.get("single_dose", [])] or ["  none"]
    L.append("Paeds on the AS list (%d)" % len(census.get("paeds", []))); L += ["  " + s for s in census.get("paeds", [])] or ["  none"]
    L.append("Restricted antimicrobials with no fellow assigned (%d)" % len(census.get("no_fellow", []))); L += ["  " + s for s in census.get("no_fellow", [])] or ["  none"]
    todos = {}
    if ams:
        for b in ams:
            for t in b.get("todos", []):
                todos.setdefault(b.get("fellow") or "?", []).append("%s: %s" % (b.get("name", "?"), t))
    L.append("AMS conflicts and audit items:")
    L += ["  " + f for f in flags if any(k in f.lower() for k in ("ams", "conflict", "close match", "no room"))] or ["  none"]
    L.append("Outstanding AMS to-dos by fellow:")
    for f in sorted(todos):
        L.append("  %s:" % f); L += ["    " + t for t in todos[f]]
    if not todos: L.append("  none recorded in the workbook")
    gaps = len(unexpl) + len(census.get("single_dose", [])) + len(census.get("paeds", [])) + len(census.get("no_fellow", [])) + len(a.get("absent", [])) + len(a.get("stale", []))
    L.append(""); L.append("AMS gaps counted: %d" % gaps)
    txt = "\n".join(L) + "\n"
    open(os.path.join(out, "delta.txt"), "w", encoding="utf-8").write(txt)
    H = ["<html><body style='font-family:Calibri,Arial;font-size:13px'>"]
    for ln in L:
        if not ln: H.append("<br>")
        elif re.match(r"^(\d\.|\d-\d\.|AMS|AS-list|Single|Paeds|Restricted|Outstanding)", ln): H.append("<b>%s</b><br>" % html.escape(ln))
        else: H.append("%s<br>" % html.escape(ln).replace("  ", "&nbsp;&nbsp;"))
    H.append("</body></html>")
    open(os.path.join(out, "delta.html"), "w", encoding="utf-8").write("\n".join(H))
    fl = [f for f in getattr(mod, "FLAGS_EXTRA", [])]
    open(os.path.join(out, "flags_email.txt"), "w", encoding="utf-8").write(("Flags (suggested edits to the instructions)\n" + "\n".join(fl) + "\n") if fl else "Flags: none\n")
    print("run status: " + run_status)
    print("delta report %d chars, AMS gaps %d, flags for handout email %d" % (len(txt), gaps, len(fl)))


if __name__ == "__main__":
    main()
