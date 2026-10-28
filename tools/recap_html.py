#!/usr/bin/env python3
import sys, html, re
LABELS = ("Update (ID):", "Update (other):", "IM:", "Rx (unlinked):", "Micro:", "Status:", "Pending:", "ID Plan:")
GREEN, RED, BLACK = "#1a7f37", "#c00000", "#000000"
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
out, expect_hist, in_off = [], False, False
for i, ln in enumerate(lines):
    e = html.escape(ln)
    if i == 0:
        out.append('<div style="font-size:16px;font-weight:700">%s</div>' % e); continue
    if not ln.strip():
        out.append('<div style="height:10px"></div>'); expect_hist = False; continue
    if re.fullmatch(r"\*[^*]+\*", ln.strip()):
        in_off = ln.startswith("*Not on the ID list")
        out.append('<div style="font-weight:700;margin-top:6px">%s</div>' % html.escape(ln.strip("*"))); continue
    if ln.startswith("!!"):
        out.append('<div style="color:%s">%s</div>' % (RED, e)); continue
    lab = next((l for l in LABELS if ln.startswith(l)), None)
    if lab:
        rest = html.escape(ln[len(lab):])
        col = GREEN if lab.startswith("Update") else BLACK
        out.append('<div><b>%s</b><span style="color:%s">%s</span></div>' % (html.escape(lab), col, rest)); continue
    if in_off:
        out.append('<div>%s</div>' % e); continue
    if expect_hist:
        out.append('<div style="font-style:italic">%s</div>' % e); expect_hist = False; continue
    prev = lines[i - 1].strip() if i else ""
    if not prev or re.fullmatch(r"\*[^*]+\*", prev):
        out.append('<div style="font-weight:700">%s</div>' % e); expect_hist = True; continue
    out.append('<div>%s</div>' % e)
doc = '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.45;color:#000000">\n' + "\n".join(out) + "\n</div>"
open(sys.argv[2], "w", encoding="utf-8").write(doc)
print("RECAP HTML OK: %d lines -> %d chars" % (len(lines), len(doc)))
