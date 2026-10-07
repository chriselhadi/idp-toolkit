#!/usr/bin/env python3
"""Build the printable handout as a self-contained HTML email body from render.json.

Usage: build_html.py <render.json> <outdir> "<DD Month YYYY>"
Writes outdir/handout.html (htmlBody), outdir/handout.txt (plain-text alternative, the
same lines) and outdir/handout_manifest.json (sha256 of both, char counts, subject).

Why HTML and not DOCX: the attachment has to travel as base64 inside a tool call, and
random base64 does not survive that past roughly 2,000 characters (14.09.2026: three
identical single-character corruptions at offset 1833, DOCX never sent). Structured
text transcribes byte-exactly at 25,000 characters, so the handout now goes as the
email itself. Since 26.09.2026 (Chris): one column of stacked cards in the AS List Delta
Report style, no handwriting columns, greyscale only, new patients shaded #f0f0f0.
"""
import sys, os, json, hashlib
from html import escape
sys.path.insert(0, os.path.dirname(__file__))
from common import WARD_ORDER, jload

# Inline styles only: Gmail keeps them on every client and on forward, a <style> block is not reliable.
# Shading goes through the bgcolor attribute: Gmail strips "background:" from inline styles.
TD = "border:1px solid #808080;padding:2px 4px;vertical-align:top;text-align:left"

KEYS = ("IM detail: ", "Conflict: ", "Update: ", "Abx (unlinked): ", "Micro: ", "Status: ", "Imaging/key labs: ", "Vitals/Imaging: ", "Pending: ")


INK, MUTED, LINE, GREY, WHITE = "#141414", "#5f5f5f", "#dcdcdc", "#f0f0f0", "#ffffff"
RED, BLUE, UCBG, UCBAR = "#c00000", "#1f4ed8", "#e8f0fb", "#1f4e9e"
import re as _re
OPEN_SEG = _re.compile(r"(\d{2}/\d{2}|\?)-(?=[\s,]|$)")
TODAY_DDMM = [""]


def drug_html(txt):
    """One drug: struck through when every segment is closed, blue when ID's
    previous-day recommendation was not applied (Chris, 28.09.2026)."""
    core = txt.split(" [ID rec not applied")[0]
    x1 = _re.search(r"\bx1 ~?(\d{2}/\d{2})", core)
    running = bool(OPEN_SEG.search(core)) or bool(x1 and x1.group(1) == TODAY_DDMM[0])
    h = escape(txt)
    if not running:
        h = "<s>%s</s>" % h
    if "[ID rec not applied" in txt:
        h = '<span style="color:%s;font-weight:700">%s</span>' % (BLUE, h)
    return h


def patient_html(p):
    """One patient as a stacked card, same look as the AS List Delta Report (Chris,
    26.09.2026): single column, no table, no handwriting columns, reads on a phone."""
    out = []
    for i, line in enumerate(p["lines_docx"]):
        if i == 0:
            out.append('<div style="font-size:15px;font-weight:700;color:%s">%s</div>' % (INK, escape(line)))
        elif i == 1 and not line.startswith(KEYS):
            out.append('<div style="font-size:13px;color:%s;margin:2px 0 4px 0">%s</div>' % (MUTED, escape(line)))
        elif line.startswith("   "):
            out.append('<div style="padding-left:16px">%s</div>' % drug_html(line.strip()))
        elif line.startswith("Abx (unlinked): "):
            out.append('<div style="margin-top:3px"><span style="color:%s">Abx (unlinked): </span>%s</div>'
                       % (MUTED, "; ".join(drug_html(x) for x in line[len("Abx (unlinked): "):].split("; "))))
        elif line.startswith("Conflict: "):
            out.append('<div style="margin-top:4px;color:%s;font-weight:700">Conflict: %s</div>' % (RED, escape(line[len("Conflict: "):])))
        else:
            for key in KEYS:
                if line.startswith(key):
                    out.append('<div style="margin-top:3px"><span style="color:%s">%s</span>%s</div>'
                               % (MUTED, escape(key), escape(line[len(key):])))
                    break
            else:
                head, sep, rest = line.partition(" | ")
                out.append('<div style="margin-top:4px"><b>%s</b>%s</div>' % (escape(head), escape(sep + rest)))
    if p.get("uc"):
        return ('<div bgcolor="%s" style="padding:10px 8px;border-left:5px solid %s;border-bottom:1px solid %s;font-size:14px;line-height:1.4;color:%s">%s</div>'
                % (UCBG, UCBAR, LINE, INK, "".join(out)))
    return ('<div bgcolor="%s" style="padding:10px 8px;border-bottom:1px solid %s;font-size:14px;line-height:1.4;color:%s">%s</div>'
            % (GREY if p.get("new") else WHITE, LINE, INK, "".join(out)))


SPLIT_OVER = 55000   # one tool call transcribes ~50 K safely (14.09.2026); above this, two emails by ward group


def build(render, date_label, groups=None, label="", offlist=True):
    TODAY_DDMM[0] = "%s/%s" % (render["date"][8:10], render["date"][5:7]) if render.get("date") else ""
    ttl = "ID Daily Handout%s" % ((" (%s)" % label) if label else "")
    H = ['<div style="margin:0;padding:8px 4px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif">',
         '<div style="font-size:18px;font-weight:700;color:%s">%s</div>' % (INK, escape(ttl)),
         None]
    T = ["ID DAILY HANDOUT%s" % ((" (%s)" % label.upper()) if label else ""), None, ""]
    n = 0
    for g in WARD_ORDER:
        if groups is not None and g not in groups:
            continue
        grp = [p for p in render["patients"] if p["group"] == g]
        if not grp:
            continue
        H.append('<div style="font-size:13px;font-weight:700;color:%s;margin:18px 0 4px 0;letter-spacing:.06em;text-transform:uppercase">'
                 '%s <span style="color:%s;font-weight:400">(%d)</span></div><div style="border-top:1px solid %s">'
                 % (INK, escape(g), MUTED, len(grp), INK))
        T.append("%s (%d)" % (g.upper(), len(grp))); T.append("")
        for p in grp:
            H.append(patient_html(p))
            T.extend(p["lines_docx"]); T.append("")
            n += 1
        H.append("</div>")
    so = render.get("signed_off") or []
    if offlist and so:
        H.append('<div style="font-size:13px;font-weight:700;color:%s;margin:18px 0 4px 0;letter-spacing:.06em;text-transform:uppercase">'
                 'Off the ID list, still ID consulted in handoffs <span style="color:%s;font-weight:400">(%d)</span></div><div style="border-top:1px solid %s">'
                 % (INK, MUTED, len(so), INK))
        T.append("OFF THE ID LIST, STILL ID CONSULTED IN HANDOFFS (%d)" % len(so)); T.append("")
        for o in so:
            H.append('<div bgcolor="%s" style="padding:8px;border-bottom:1px solid %s;font-size:14px;line-height:1.4;color:%s"><b>%s %s</b>: %s</div>'
                     % (WHITE, LINE, INK, escape(o["room"]), escape(o["name"]), escape(o["line"])))
            T.append("%s %s: %s" % (o["room"], o["name"], o["line"]))
        H.append("</div>"); T.append("")
    sub = "%s<br>%d patients" % (escape(date_label), n)
    H[2] = '<div style="font-size:13px;color:%s;margin:4px 0 0 0;line-height:1.4">%s</div>' % (MUTED, sub)
    T[1] = "%s | %d patients" % (date_label, n)
    H.append('<div style="font-size:11px;color:%s;margin:18px 0 0 0;line-height:1.4">Grey card = new to service. '
             "Blue-edged card = UC, under our care. Struck drug = stopped. Blue drug = our previous-day recommendation not applied. "
             "Red = conflict between handoffs, AS list or AMS sheet. "
             "D&lt;n&gt; on a drug line = computed days on drug; ~ = start known only from the AS list; "
             "d&lt;n&gt; on a pending = days outstanding.</div></div>" % MUTED)
    return "\n".join(H) + "\n", "\n".join(T).rstrip() + "\n", n


def main():
    render_p, out, date_label = sys.argv[1:4]
    render = jload(render_p)
    html, txt, n = build(render, date_label)
    for t in (html, txt):
        assert "\u2014" not in t and "\u2013" not in t, "dash in handout"
    # Gmail deletes background: declarations in transit (seen 14.09.2026); bgcolor survives.
    assert "background:" not in html, "background: is deleted in transit, use bgcolor"
    open(os.path.join(out, "handout.html"), "w", encoding="utf-8").write(html)
    open(os.path.join(out, "handout.txt"), "w", encoding="utf-8").write(txt)
    parts = [{"file": "handout.html", "subject": "ID Daily Handout - %s" % date_label, "chars": len(html),
              "sha256": hashlib.sha256(html.encode()).hexdigest()}]
    if len(html) > SPLIT_OVER:
        # Two emails, ward groups split so the halves are near equal in characters.
        sizes = {g: sum(len("".join(p["lines_docx"])) for p in render["patients"] if p["group"] == g) for g in WARD_ORDER}
        first, acc, half = [], 0, sum(sizes.values()) / 2
        for g in WARD_ORDER:
            if acc < half:
                first.append(g); acc += sizes[g]
        second = [g for g in WARD_ORDER if g not in first]
        parts = []
        for i, grp in enumerate((first, second), 1):
            lab = "part %d of 2" % i
            h, t, k = build(render, date_label, grp, lab, offlist=(i == 2))
            fn = "handout_part%d.html" % i
            open(os.path.join(out, fn), "w", encoding="utf-8").write(h)
            parts.append({"file": fn, "subject": "ID Daily Handout - %s (%s)" % (date_label, lab), "chars": len(h),
                          "sha256": hashlib.sha256(h.encode()).hexdigest(), "patients": k})
    man = {"subject": "ID Daily Handout - %s" % date_label, "patients": n,
           "html_chars": len(html), "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
           "txt_chars": len(txt), "txt_sha256": hashlib.sha256(txt.encode()).hexdigest(), "parts": parts}
    json.dump(man, open(os.path.join(out, "handout_manifest.json"), "w"), indent=1)
    print("handout html %d chars, txt %d chars, %d patient rows, %d email(s): %s"
          % (len(html), len(txt), n, len(parts), ", ".join(p["file"] for p in parts)))


if __name__ == "__main__":
    main()
