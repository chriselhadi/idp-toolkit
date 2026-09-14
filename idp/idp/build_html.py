#!/usr/bin/env python3
"""Build the printable handout as a self-contained HTML email body from render.json.

Usage: build_html.py <render.json> <outdir> "<DD Month YYYY>"
Writes outdir/handout.html (htmlBody), outdir/handout.txt (plain-text alternative, the
same lines) and outdir/handout_manifest.json (sha256 of both, char counts, subject).

Why HTML and not DOCX: the attachment has to travel as base64 inside a tool call, and
random base64 does not survive that past roughly 2,000 characters (14.09.2026: three
identical single-character corruptions at offset 1833, DOCX never sent). Structured
text transcribes byte-exactly at 25,000 characters, so the handout now goes as the
email itself, printable from Gmail: A4 portrait, three columns, columns 2 and 3 empty
for handwriting, greyscale only, new patients shaded #f0f0f0.
"""
import sys, os, json, hashlib
from html import escape
sys.path.insert(0, os.path.dirname(__file__))
from common import WARD_ORDER, jload

# Inline styles only: Gmail keeps them on every client and on forward, a <style> block is not reliable.
# Shading goes through the bgcolor attribute: Gmail strips "background:" from inline styles.
TD = "border:1px solid #808080;padding:2px 4px;vertical-align:top;text-align:left"

KEYS = ("Update: ", "Abx (unlinked): ", "Micro: ", "Status: ", "Imaging/key labs: ", "Vitals/Imaging: ", "Pending: ")


def patient_html(p):
    out = []
    for i, line in enumerate(p["lines_docx"]):
        if i == 0:
            out.append('<div style="font-weight:bold;font-size:9.5pt%s">%s</div>'
                       % (";text-decoration:underline" if p.get("new") else "", escape(line)))
        elif line.startswith("   "):
            out.append('<div style="margin-left:14px">%s</div>' % escape(line.strip()))
        else:
            for key in KEYS:
                if line.startswith(key):
                    out.append('<div><b>%s</b>%s</div>' % (escape(key), escape(line[len(key):])))
                    break
            else:
                out.append('<div>%s</div>' % escape(line))
    return "".join(out)


SPLIT_OVER = 55000   # one tool call transcribes ~50 K safely (14.09.2026); above this, two emails by ward group


def build(render, date_label, groups=None, label=""):
    th = TD + ";font-weight:bold"
    H = ['<div style="font-family:Calibri,Arial,sans-serif;font-size:8.5pt;color:#000">',
         '<p style="margin:0 0 4px 0;font-size:12pt;font-weight:bold">ID Service Daily Handout, %s%s</p>'
         % (escape(date_label), escape(" (%s)" % label) if label else ""),
         '<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;width:100%;table-layout:fixed">',
         '<colgroup><col style="width:58%"><col style="width:21%"><col style="width:21%"></colgroup>',
         '<thead><tr><th bgcolor="#d9d9d9" style="%s">Patient, ID picture</th><th bgcolor="#d9d9d9" style="%s">Vitals / Imaging</th>'
         '<th bgcolor="#d9d9d9" style="%s">Pendings</th></tr></thead><tbody>' % (th, th, th)]
    T = ["ID Service Daily Handout, %s%s" % (date_label, (" (%s)" % label) if label else ""), ""]
    n = 0
    for g in WARD_ORDER:
        if groups is not None and g not in groups:
            continue
        grp = [p for p in render["patients"] if p["group"] == g]
        if not grp:
            continue
        H.append('<tr><td colspan="3" bgcolor="#bfbfbf" style="%s;font-weight:bold;font-size:9pt">%s</td></tr>' % (TD, escape(g)))
        T.append("== %s ==" % g)
        for p in grp:
            td = ('bgcolor="#f0f0f0" ' if p.get("new") else "") + 'style="%s;height:2.2cm"' % TD
            H.append('<tr style="page-break-inside:avoid"><td %s>%s</td><td %s></td><td %s></td></tr>'
                     % (td, patient_html(p), td, td))
            T.extend(p["lines_docx"]); T.append("")
            n += 1
    H.append("</tbody></table>")
    H.append('<p style="margin:4px 0 0 0;font-size:7pt;font-style:italic">Columns 2 and 3 are left blank for handwritten notes on rounds. '
             "D&lt;n&gt; on a drug line = computed days on drug; ~ = start known only from the AS list; "
             "d&lt;n&gt; on a pending = days outstanding.</p></div>")
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
            h, t, k = build(render, date_label, grp, lab)
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
