#!/usr/bin/env python3
"""Split out/archive_notes.txt into one file per patient (Chris, 29.09.2026).

  archive_split.py <archive_notes.txt> <out_dir> <YYYY-MM-DD>

Writes <out_dir>/<n>.txt (the patient's block verbatim) and <out_dir>/manifest.tsv with
one line per note: n, MRN, name, Drive title 'Archive <date> <MRN> <NAME>'.
"""
import os, re, sys

src, out, day = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
txt = open(src, encoding="utf-8").read() if os.path.exists(src) else ""
blocks = [b.strip("\n") for b in re.split(r"\n(?=ARCHIVE  )", txt) if b.strip()]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # OVERLAY_6 4a: no note with a dose leaves
from common import find_doses
_bad = [(n, d) for n, b in enumerate(blocks, 1) for d in find_doses(b)]
if _bad:
    for n, d in _bad:
        print("archive_split: DOSE in note %d: '%s'; remove it before upload" % (n, d))
    sys.exit(1)
man = []
for n, b in enumerate(blocks, 1):
    m = re.match(r"ARCHIVE\s+\S+\s+(.+?)\s+\(MRN ([^)]*)\)", b)
    name, mrn = (m.group(1).strip(), m.group(2).strip()) if m else ("?", "?")
    mrn = "" if mrn == "?" else mrn
    open(os.path.join(out, "%d.txt" % n), "w", encoding="utf-8").write(b + "\n")
    man.append("%d\t%s\t%s\tArchive %s %s %s" % (n, mrn, name, day, mrn or "noMRN", name.upper()))
open(os.path.join(out, "manifest.tsv"), "w", encoding="utf-8").write("\n".join(man) + ("\n" if man else ""))
print("archive_split: %d notes" % len(blocks))
