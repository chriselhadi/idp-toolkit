#!/usr/bin/env python3
"""Render the AS List Delta Report as a greyscale HTML email body.

Usage: render_delta.py <delta.json> <as_today.json> <new_mrns.json> <out.html> <out.txt>
<new_mrns.json> is a JSON list of MRNs that are new to service (newly on the AS
list AND absent from every ward handoff sheet). Everything else renders white.
"""
import sys, os, json, html
sys.path.insert(0, __import__("os").path.dirname(__file__))
from common import jload

SHORT = {"Meropenem": "Mero", "Mero": "Mero", "Vancomycin": "Vanco", "Vanco": "Vanco",
         "Piptazo": "Pip", "Pip-tazo": "Pip", "Piperacillin-tazobactam": "Pip",
         "Fluconazole": "Fluco", "Fluco": "Fluco", "Zavicefta": "Zavi", "Zavi": "Zavi",
         "Ertapenem": "Erta", "Erta": "Erta", "Ceftriaxone": "Ceft", "Ceftriax": "Ceft",
         "Teicoplanin": "Teico", "Teico": "Teico", "Ciprofloxacin": "Cipro", "Cipro": "Cipro",
         "Amikacin": "Amik", "Amik": "Amik", "Tavanic": "Tava", "Levofloxacin": "Tava",
         "Azithromycin": "Azi", "Azithro": "Azi", "Clindamycin": "Clinda", "Clinda": "Clinda",
         "Metronidazole": "Flagyl", "Flagyl": "Flagyl", "Cefazolin": "Cefaz", "Cefaz": "Cefaz",
         "Ganciclovir": "Ganci", "Ganci": "Ganci", "Caspofungin": "Caspo", "Caspo": "Caspo",
         "Ecalta": "Ecalta", "Anidulafungin": "Ecalta", "Tigecycline": "Tige", "Tige": "Tige",
         "Colistin": "Colis", "Linezolid": "Linez", "Daptomycin": "Dapto", "Gentamicin": "Genta",
         "Doxycycline": "Doxy", "Bactrim": "Bactrim", "Flumivir": "Flumi", "Flumi": "Flumi",
         "Voriconazole": "Vori", "Vorico": "Vori", "Vfend": "Vori", "Zerbaxa": "Zerb",
         "Cefepime": "Cefep", "Aztreonam": "Aztreo", "Fosfomycin": "Fosfo", "Augmentin": "Augm"}

INK, MUTED, LINE, GREY, WHITE = "#141414", "#5f5f5f", "#dcdcdc", "#f0f0f0", "#ffffff"


def sd(name):
    return SHORT.get(name, name)


def tc(n):
    out = []
    for w in n.split():
        out.append("-".join(p.capitalize() for p in w.split("-")))
    return " ".join(out)


def regimen(p):
    """One entry per drug. Two AS-list rows for the same drug (a loading order and the
    maintenance order) collapse to the drug with its best-documented frequency."""
    freq, order = {}, []
    for o in p.get("orders", []):
        if o.get("once"):
            continue
        d = o["drug"]
        if d not in freq:
            order.append(d); freq[d] = o.get("freq")
        elif (not freq[d] or freq[d] == "?") and o.get("freq"):
            freq[d] = o.get("freq")
    return ", ".join("%s %s" % (sd(d), freq[d] or "?") for d in order) or "-"


def card(room, name, fields, shaded=False, tag=""):
    """One patient as a stacked block: bed + name on the first line, then label: value
    lines. Mobile first (Chris, 14.09.2026): a five-column table squashes to nothing on a
    phone, a stack of short lines reads the same on any width."""
    lines = "".join('<div style="font-size:14px;line-height:1.4;color:%s;margin:2px 0 0 0">'
                    '<span style="color:%s">%s: </span>%s</div>' % (INK, MUTED, html.escape(k), html.escape(v))
                    for k, v in fields if v)
    return ('<div bgcolor="%s" style="padding:10px 8px;border-bottom:1px solid %s">'
            '<div style="font-size:15px;font-weight:700;color:%s">%s &nbsp;%s%s</div>%s</div>'
            % (GREY if shaded else WHITE, LINE, INK, html.escape(room or "?"), html.escape(tc(name)), tag, lines))


def section(title, count, cards):
    hdr = ('<div style="font-size:13px;font-weight:700;color:%s;margin:18px 0 4px 0;'
           'letter-spacing:.06em;text-transform:uppercase">%s <span style="color:%s;font-weight:400">(%d)</span></div>'
           % (INK, title, MUTED, count))
    if not cards:
        return hdr + '<div style="border-top:1px solid %s;padding:8px;font-size:14px;color:%s">None.</div>' % (INK, MUTED)
    return hdr + '<div style="border-top:1px solid %s">%s</div>' % (INK, "".join(cards))


def main():
    dp, tp, np_, hp, tp2 = sys.argv[1:6]
    d = jload(dp)
    t = jload(tp) if os.path.exists(tp) else {"patients": []}
    newset = set(json.load(open(np_))) if os.path.exists(np_) else set()
    if not d.get("computed"):
        # No delta today (no AS list, or no earlier list in state). The report still goes out
        # and says why, so a missing list is visible rather than silent.
        why = d.get("reason", "not computed")
        doc = ('<div style="padding:8px 4px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif">'
               '<div style="font-size:18px;font-weight:700;color:%s">AS List Delta Report</div>'
               '<div style="font-size:14px;color:%s;margin:8px 0 0 0">Delta not computed: %s.</div></div>'
               % (INK, MUTED, html.escape(why)))
        txt = "AS LIST DELTA REPORT\nDelta not computed: %s.\n" % why
        open(hp, "w", encoding="utf-8").write(doc); open(tp2, "w", encoding="utf-8").write(txt)
        print("delta not computed (%s): stub written" % why); return
    bym = {p["mrn"]: p for p in t["patients"]}
    # A "change" with nothing started and nothing stopped is not a change; drop it.
    real_changes = [c for c in d["changes"] if c["started"] or c["stopped"]]

    NEWTAG = (' <span style="font-size:10px;font-weight:700;letter-spacing:.06em;color:%s;'
              'border:1px solid %s;padding:1px 4px">NEW TO SERVICE</span>' % (INK, INK))
    ncards = [card(p["room"], p["name"], [("on", regimen(bym[p["mrn"]]))], p["mrn"] in newset,
                   NEWTAG if p["mrn"] in newset else "")
              for p in sorted(d["new"], key=lambda x: x["room"] or "")]
    ocards = [card(p["room"], p["name"], [("was on", ", ".join(sd(x) for x in p["drugs"]) or "-")])
              for p in sorted(d["off"], key=lambda x: x["room"] or "")]
    ccards = [card(c["room"], c["name"], [("started", ", ".join(sd(x) for x in c["started"])),
                                          ("stopped", ", ".join(sd(x) for x in c["stopped"])),
                                          ("now on", regimen(bym[c["mrn"]]))])
              for c in sorted(real_changes, key=lambda x: x["room"] or "")]

    ct = d["counts"]
    dmy = lambda iso: ".".join(reversed(iso.split("-")))
    missed = d.get("missed_dates") or []
    gap = (" (no AS list on %s, so this delta covers %d days)" % (", ".join(dmy(x) for x in missed), len(missed) + 1)) if missed else ""
    meta = ("AS list %s vs %s%s<br>%d on list, "
            "%d new, %d off, %d changed"
            % (dmy(d["today_date"]), dmy(d["yday_date"]), html.escape(gap),
               ct["today"], ct["new"], ct["off"], len(real_changes)))

    # Outer wrapper carries no background: Gmail deletes background declarations, and a
    # page tint that only some clients honour is worse than none. Bordered card instead.
    # No fixed width, no columns: the report is a single column of short lines that
    # renders the same on a phone and on a desktop.
    doc = (
        '<div style="margin:0;padding:8px 4px;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif">'
        '<div style="font-size:18px;font-weight:700;color:%s">AS List Delta Report</div>'
        '<div style="font-size:13px;color:%s;margin:4px 0 0 0;line-height:1.4">%s</div>'
        '%s%s%s'
        '<div style="font-size:11px;color:%s;margin:18px 0 0 0;line-height:1.4">Rows tagged NEW TO SERVICE are new on today\'s list with no row '
        'in any ward handoff doc, or are named as a new patient in the daily update.</div>'
        '</div>'
        % (INK, MUTED, meta,
           section("New on list", ct["new"], ncards),
           section("Off list", ct["off"], ocards),
           section("Changes", len(real_changes), ccards),
           MUTED))

    # Gmail must not be able to strip meaning out of this report.
    assert "background:" not in doc, "background: is deleted in transit, use bgcolor"
    open(hp, "w", encoding="utf-8").write(doc)

    # Plain-text alternative. No space-padded columns: mail clients render text/plain in a
    # proportional font, which turns aligned columns into ragged mush. One line per field.
    def plain(room, name, *pairs, tag=""):
        out = ["%s  %s%s" % (room or "?", tc(name), tag)]
        for label, val in pairs:
            if val:
                out.append("      %s: %s" % (label, val))
        return "\n".join(out)

    L = ["AS LIST DELTA REPORT", html.unescape(meta.replace("<br>", " | ")), ""]
    L.append("NEW ON LIST (%d)" % ct["new"])
    L.append("")
    for p in sorted(d["new"], key=lambda x: x["room"]):
        L.append(plain(p["room"], p["name"], ("on", regimen(bym[p["mrn"]])),
                       tag="   [NEW TO SERVICE]" if p["mrn"] in newset else ""))
    if not d["new"]:
        L.append("  None.")
    L += ["", "OFF LIST (%d)" % ct["off"], ""]
    for p in sorted(d["off"], key=lambda x: x["room"] or ""):
        L.append(plain(p["room"], p["name"], ("was on", ", ".join(sd(x) for x in p["drugs"]))))
    if not d["off"]:
        L.append("  None.")
    L += ["", "CHANGES (%d)" % len(real_changes), ""]
    for c in sorted(real_changes, key=lambda x: x["room"] or ""):
        L.append(plain(c["room"], c["name"],
                       ("started", ", ".join(sd(x) for x in c["started"])),
                       ("stopped", ", ".join(sd(x) for x in c["stopped"])),
                       ("now on", regimen(bym[c["mrn"]]))))
    if not real_changes:
        L.append("  None.")
    L += ["", "NEW TO SERVICE = new on today's list with no ward handoff row, or named as a new patient in the daily update."]
    txt = "\n".join(L)
    assert "—" not in txt and "–" not in txt, "dash in output"
    assert "—" not in doc and "–" not in doc, "dash in html"
    open(tp2, "w", encoding="utf-8").write(txt)
    print("html %d chars, txt %d chars, %d real changes (%d empty rows dropped)"
          % (len(doc), len(txt), len(real_changes), ct["changed"] - len(real_changes)))


if __name__ == "__main__":
    main()
