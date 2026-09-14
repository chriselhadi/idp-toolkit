#!/usr/bin/env python3
"""Parse the ward handoff Google Docs (read_file_content spills) into patient rows.

Usage: parse_wards.py <floors.json|MISSING> <icu.json|MISSING> <cardio.json|MISSING> <neuro.json|MISSING> <out.json> [--probe]
Each input is the read_file_content result: JSON with 'fileContent', a Markdown export of the doc. The docs are
6-column pipe tables: Patient | History | Active points | Medication | Pendings | Synthesis by receiver, under
floor headings ('# 7th floor', '# New ICU', ...). Cell 0 carries the bold name, the room, DOA, UC and consults.
Output: list of rows {doc, section, room, group, name, doa, uc, consults, cells{HDR,ACTIVE,MEDS,ABX,PENDINGS,SYNTHESIS}, text, dated_lines}.
--probe prints shape statistics only (no patient text). Prints counts only.
"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))
from common import parse_bed, jdump

DATE_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\b")
ROOM_PATS = [
    (re.compile(r"\b(?:old\s+icu|icu\s*b)\s*(\d{1,2})\b", re.I), lambda m: "ICU%sB" % m.group(1)),
    (re.compile(r"\b(?:new\s+icu|icu\s*d)\s*(\d{1,2})\b", re.I), lambda m: "ICU%sD" % m.group(1)),
    (re.compile(r"\b(ICU|CSU|PICU|NICU)\s*(\d{1,2})\s*([A-D])\b", re.I), lambda m: "%s%s%s" % (m.group(1).upper(), m.group(2), m.group(3).upper())),
    (re.compile(r"\b(ICU|CSU)\s*(\d{1,2})\b", re.I), lambda m: "%s%s" % (m.group(1).upper(), m.group(2))),
    (re.compile(r"\b(SCT|BMT)\s*(\d{1,2})\b", re.I), lambda m: "SCT%s" % m.group(2)),
    (re.compile(r"(?<![\d/.:])([2-7]\d{2})\s?([A-D])?(?![\d/.a-z])"), lambda m: "%s%s" % (m.group(1), m.group(2) or "")),
]
SECTION_GROUP = [
    (r"7th", "7th floor"), (r"4th", "4th floor"), (r"3rd", "3rd floor"), (r"2nd|SCT|BMT|chemo", "2nd floor"),
    (r"ER\s*IN|\bER\b", "ER IN"), (r"new\s*icu|CSU|\bD\b", "ICU#D"), (r"old\s*icu", "ICU#B"), (r"\bicu\b", "ICU#B"), (r"CCU", "Other"),
]


def unescape(s, keep_bold=False):
    s = s.replace("&#10;", "\n").replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
    for _ in range(3):
        s = re.sub(r"\\([\\*#!>\-\[\]().+_`~|])", r"\1", s)
    if not keep_bold:
        s = s.replace("**", "")
    s = re.sub(r"(^|\s)#+(?=\s|$)", r"\1", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def section_group(sec):
    for pat, grp in SECTION_GROUP:
        if re.search(pat, sec or "", re.I):
            return grp
    return "Other"


def room_from(text, sec_group):
    for pat, fn in ROOM_PATS:
        m = pat.search(text)
        if m:
            room, grp, _ = parse_bed(fn(m))
            if grp == "Other":
                continue
            return room, grp
    return "?", sec_group


def load_text(path):
    if not path or path.upper() == "MISSING" or not os.path.exists(path):
        return None
    txt = open(path, encoding="utf-8", errors="replace").read()
    try:
        obj = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
        for k in ("fileContent", "content", "text"):
            if isinstance(obj.get(k), str):
                return obj[k]
    except Exception:
        pass
    return txt


SKIP_TOKEN = re.compile(r"^(DOA|UC\b|Cs\b|CS\b|Weight|Allerg|Foley|NG\b|Lines|Code|NKFDA|NKDA|Old ICU|New ICU|ICU|Icu|CSU|SCT|Patient X|DNI|DNR|Full code|N/A|Dr\.?\s|Day|Phase)", re.I)


def pick_name(raw0, head):
    kb = unescape(raw0, keep_bold=True)
    lead = kb.split("**")[0]
    lead = re.sub(r"(^|\s)#+", " ", lead).strip(" .-:#\n")
    lead1 = re.split(r"\n|(?=\d)|\s(?=DOA|UC\b|Cs\b|CS\b)", lead)[0].strip(" .-:")
    if len(re.findall(r"[A-Za-z]{2,}", lead1)) >= 2 and not SKIP_TOKEN.match(lead1):
        return lead1
    bold = [t.strip() for t in re.findall(r"\*\*(.+?)\*\*", kb, re.S)]
    for want in (2, 1):
        for t in bold:
            t1 = re.split(r"\n|(?=\d)", t.strip(" .-:#"))[0].strip(" .-:")
            if len(re.findall(r"[A-Za-z]{2,}", t1)) >= want and not SKIP_TOKEN.match(t1) and not DATE_RE.search(t1) and len(t1) < 60:
                return t1
    first = head.split("\n")[0]
    m = re.match(r"^\s*([A-Za-z][A-Za-z' .-]*?)(?=\d|\s+(?:DOA|UC|Cs|CS|ICU|Icu|CSU|SCT|Old|New|NKFDA|Weight)\b|\s*$)", first)
    return (m.group(1) if m else re.split(r"\s{2,}|\n", first)[0]).strip(" .-#:")


HDR_CELL = re.compile(r"^\**\s*(?:past\s+)?(?:medical\s+)?history\s*\**\s*$", re.I)


def is_header_cell(c):
    """True only when the cell IS the column label, not a cell that mentions the word."""
    return bool(HDR_CELL.match(c.strip()))


def is_noise(cells):
    c0 = cells[0]
    if not c0.strip() or "Patient X" in c0 or ":-:" in c0 or is_header_cell(cells[1]):
        return True
    if len(re.findall(r"\b\d{4}\b", c0 + cells[1])) >= 6 and not DATE_RE.search(c0):
        return True  # phone directory row
    if not re.search(r"[A-Za-z]{3,}", c0):
        return True
    if sum(len(c.strip()) for c in cells[1:]) < 30:
        return True  # summary or directory row, no clinical cells
    return False


def parse_rows(text, doc):
    rows, cur_sec = [], ""
    for line in text.split("\n"):
        if line.startswith("#"):
            sec = unescape(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line.lstrip("# ")))[:60]
            if re.search(r"[A-Za-z]", sec):
                cur_sec = sec
            continue
        if not line.startswith("|"):
            continue
        raw = line.split("|")[1:-1]
        if len(raw) < 6:
            continue
        cells = [unescape(c) for c in raw[:6]]
        head = cells[0]
        if not any(c.strip() for c in cells[1:]) and 2 < len(head) < 40 and re.search(r"[A-Za-z]", head):
            cur_sec = head[:60]; continue
        if is_noise(cells) or re.search(r"summary", cur_sec, re.I):
            continue
        sec_group = section_group(cur_sec)
        name = pick_name(raw[0], head)
        name = re.sub(r"\s+", " ", name)[:60]
        md = re.search(r"DOA:?\s*(\d{1,2}[./-]\s?\d{1,2}[./-]?\s?\d{2,4})", head)
        doa = md.group(1) if md else None
        rest = unescape(raw[0], keep_bold=True).replace("**", " ").replace(name, " ", 1)
        rest = re.sub(r"(DOA?:?\s*)?\d{1,2}[./-]\s?\d{1,2}[./-]?\s?\d{2,4}", " ", rest)
        room, grp = room_from(rest, sec_group)
        uc = re.search(r"\bUC\s*(?:of\s*)?(?:Dr\.?\s*)?([A-Za-z' .-]{2,40}?)(?=\s+(?:Cs|CS|DOA|NKFDA|Weight|\d)|\n|$)", head)
        consults = [c.strip() for c in re.findall(r"\bC[sS]\s+([A-Za-z][A-Za-z .'-]{1,30}?)(?=\s+C[sS]\b|\n|$|\s{2,})", head)]
        meds = cells[3]
        abx = ""
        ma = re.search(r"Anti-?microb\w*\s*:?\s*(.*?)(?=\n?\s*(?:Neb|Steroids|Diuretics|Anti-?coag|Other|Home|Anti-?HTN)\w*\s*:|\Z)", meds, re.S | re.I)
        if ma:
            abx = ma.group(1).strip()
        c = {"HDR": cells[1], "ACTIVE": cells[2], "MEDS": meds, "ABX": abx, "PENDINGS": cells[4], "SYNTHESIS": cells[5]}
        c = {k: re.sub(r"\s*\n\s*", " / ", v).strip(" /") for k, v in c.items() if v.strip()}
        text_all = "\n".join("%s: %s" % (k, v) for k, v in c.items())
        dated = []
        for seg in re.split(r"\n| / |(?<=[.;])\s+", (head + "\n" + text_all)):
            if DATE_RE.search(seg) and len(seg.strip()) > 8:
                dated.append(seg.strip()[:300])
        rows.append({"doc": doc, "section": cur_sec, "room": room, "group": grp, "name": name, "doa": doa,
                     "uc": uc.group(1).strip() if uc else "", "consults": consults[:6], "id_consult": bool(re.search(r"\bC[sS]\s+ID\b", head)),
                     "cells": c, "text": text_all[:8000], "dated_lines": dated[-15:]})
    return rows


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; probe = "--probe" in sys.argv
    ins = dict(zip(["floors", "icu", "cardio", "neuro"], args[:4])); outp = args[4]
    allrows, report = [], []
    for doc, path in ins.items():
        text = load_text(path)
        if text is None:
            report.append("%s=missing" % doc); continue
        rows = parse_rows(text, doc)
        allrows += rows
        report.append("%s=%d" % (doc, len(rows)))
        if probe:
            pipe = sum(1 for l in text.split("\n") if l.startswith("|"))
            print("PROBE %s: %d chars, %d lines, %d table lines, %d patient rows, rooms found %d, sections %s" % (
                doc, len(text), text.count("\n"), pipe, len(rows), sum(1 for r in rows if r["room"] != "?"),
                sorted({r["group"] for r in rows})))
    jdump(allrows, outp)
    print("wards: %d rows (%s); with abx cell %d, with dated lines %d, ID consult tagged %d" % (
        len(allrows), ", ".join(report), sum(1 for r in allrows if r["cells"].get("ABX")),
        sum(1 for r in allrows if r["dated_lines"]), sum(1 for r in allrows if r["id_consult"])))


if __name__ == "__main__":
    main()
