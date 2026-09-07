#!/usr/bin/env python3
"""Render the AS List Delta Report as a greyscale HTML email body.

Usage: render_delta.py <delta.json> <as_today.json> <new_mrns.json> <out.html> <out.txt>
<new_mrns.json> is a JSON list of MRNs that are new to service (newly on the AS
list AND absent from every ward handoff sheet). Everything else renders white.
"""
import sys, json, html
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
    seen, out = set(), []
    for o in p.get("orders", []):
        if o.get("once"):
            continue
        k = (o["drug"], o.get("freq"))
        if k in seen:
            continue
        seen.add(k)
        out.append("%s %s" % (sd(o["drug"]), o.get("freq") or "?"))
    return ", ".join(out) or "-"


def cell(txt, **kw):
    st = ("padding:9px 12px;border-bottom:1px solid %s;font-size:13px;"
          "color:%s;vertical-align:top;" % (LINE, kw.get("color", INK)))
    st += kw.get("extra", "")
    return '<td style="%s">%s</td>' % (st, txt)


def head(cols, widths):
    th = ""
    for c, w in zip(cols, widths):
        th += ('<th style="padding:7px 12px;text-align:left;font-size:10px;'
               'letter-spacing:.09em;text-transform:uppercase;color:%s;font-weight:600;'
               'border-bottom:1px solid %s;width:%s">%s</th>' % (MUTED, INK, w, c))
    return "<tr>" + th + "</tr>"


def section(title, count, cols, widths, rows):
    hdr = ('<div style="font-size:13px;font-weight:700;color:%s;margin:0 0 8px 0">'
           '%s <span style="color:%s;font-weight:400">(%d)</span></div>'
           % (INK, title, MUTED, count))
    if not rows:
        return ('<div style="margin:0 0 30px 0">%s'
                '<div style="border-top:1px solid %s;padding:10px 0 0 0;font-size:13px;'
                'color:%s">None.</div></div>' % (hdr, LINE, MUTED))
    return (
        '<div style="margin:0 0 30px 0">%s'
        '<table cellpadding="0" cellspacing="0" border="0" style="width:100%%;'
        'border-collapse:collapse;border-top:1px solid %s">%s%s</table></div>'
        % (hdr, INK, head(cols, widths), "".join(rows)))


def main():
    dp, tp, np_, hp, tp2 = sys.argv[1:6]
    d = jload(dp)
    t = jload(tp)
    newset = set(json.load(open(np_)))
    bym = {p["mrn"]: p for p in t["patients"]}

    def row(cells, shaded):
        bg = GREY if shaded else WHITE
        return '<tr style="background:%s">%s</tr>' % (bg, "".join(cells))

    nrows = []
    for p in sorted(d["new"], key=lambda x: x["room"]):
        shaded = p["mrn"] in newset
        rec = bym[p["mrn"]]
        nrows.append(row([
            cell('<span style="font-weight:600">%s</span>' % html.escape(p["room"] or "?")),
            cell(html.escape(tc(p["name"]))),
            cell(html.escape(regimen(rec))),
        ], shaded))

    orows = []
    for p in sorted(d["off"], key=lambda x: x["room"] or ""):
        orows.append(row([
            cell('<span style="font-weight:600">%s</span>' % html.escape(p["room"] or "?")),
            cell(html.escape(tc(p["name"]))),
            cell(html.escape(", ".join(sd(x) for x in p["drugs"]) or "-")),
        ], False))

    crows = []
    for c in sorted(d["changes"], key=lambda x: x["room"] or ""):
        rec = bym[c["mrn"]]
        started = ", ".join(sd(x) for x in c["started"]) or "-"
        stopped = ", ".join(sd(x) for x in c["stopped"]) or "-"
        crows.append(row([
            cell('<span style="font-weight:600">%s</span>' % html.escape(c["room"] or "?")),
            cell(html.escape(tc(c["name"]))),
            cell(html.escape(started)),
            cell(html.escape(stopped), color=MUTED),
            cell(html.escape(regimen(rec))),
        ], False))

    ct = d["counts"]
    meta = ("AS list %s vs %s &nbsp;&middot;&nbsp; %d on list &nbsp;&middot;&nbsp; "
            "%d new, %d off, %d changed"
            % (".".join(reversed(d["today_date"].split("-"))),
               ".".join(reversed(d["yday_date"].split("-"))),
               ct["today"], ct["new"], ct["off"], ct["changed"]))

    doc = (
        '<div style="margin:0;padding:26px 20px;background:#fafafa;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif">'
        '<div style="max-width:660px;margin:0 auto;background:%s;border:1px solid %s;padding:30px 32px">'
        '<div style="font-size:19px;font-weight:700;color:%s;letter-spacing:-.01em">'
        'AS List Delta Report</div>'
        '<div style="font-size:12px;color:%s;margin:6px 0 0 0">%s</div>'
        '<div style="height:1px;background:%s;margin:22px 0 26px 0"></div>'
        '%s%s%s'
        '<div style="height:1px;background:%s;margin:4px 0 12px 0"></div>'
        '<div style="font-size:11px;color:%s">'
        '<span style="display:inline-block;width:11px;height:11px;background:%s;'
        'border:1px solid %s;vertical-align:-1px"></span> new to service &nbsp;&nbsp;'
        '<span style="display:inline-block;width:11px;height:11px;background:%s;'
        'border:1px solid %s;vertical-align:-1px"></span> already on the sheets'
        '</div></div></div>'
        % (WHITE, LINE, INK, MUTED, meta, LINE,
           section("New on list", ct["new"], ["Bed", "Patient", "Regimen"],
                   ["16%", "42%", "42%"], nrows),
           section("Off list", ct["off"], ["Bed", "Patient", "Was on"],
                   ["16%", "42%", "42%"], orows),
           section("Changes", ct["changed"], ["Bed", "Patient", "Started", "Stopped", "Now on"],
                   ["12%", "30%", "18%", "18%", "22%"], crows),
           LINE, MUTED, GREY, LINE, WHITE, LINE))

    open(hp, "w", encoding="utf-8").write(doc)

    # plain-text alternative
    L = ["AS LIST DELTA REPORT", meta.replace("&nbsp;&middot;&nbsp;", " | "), ""]
    L.append("NEW ON LIST (%d)" % ct["new"])
    for p in sorted(d["new"], key=lambda x: x["room"]):
        mark = "*" if p["mrn"] in newset else " "
        L.append("%s %-7s %-30s %s" % (mark, p["room"], tc(p["name"]), regimen(bym[p["mrn"]])))
    L += ["", "OFF LIST (%d)" % ct["off"]]
    for p in sorted(d["off"], key=lambda x: x["room"] or ""):
        L.append("  %-7s %-30s %s" % (p["room"], tc(p["name"]), ", ".join(sd(x) for x in p["drugs"])))
    if not d["off"]:
        L.append("  None.")
    L += ["", "CHANGES (%d)" % ct["changed"]]
    for c in sorted(d["changes"], key=lambda x: x["room"] or ""):
        L.append("  %-7s %-30s started %s | stopped %s | now %s"
                 % (c["room"], tc(c["name"]),
                    ", ".join(sd(x) for x in c["started"]) or "-",
                    ", ".join(sd(x) for x in c["stopped"]) or "-",
                    regimen(bym[c["mrn"]])))
    L += ["", "* new to service"]
    txt = "\n".join(L)
    assert "—" not in txt and "–" not in txt, "dash in output"
    assert "—" not in doc and "–" not in doc, "dash in html"
    open(tp2, "w", encoding="utf-8").write(txt)
    print("html %d chars, txt %d chars" % (len(doc), len(txt)))


if __name__ == "__main__":
    main()
