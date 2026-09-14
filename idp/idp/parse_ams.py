#!/usr/bin/env python3
"""Parse the AMS workbook (download_file_content spill: JSON with base64 'content' of an .xlsx) into patient blocks.

Usage: parse_ams.py <ams_spill.json|MISSING> <out.json> [--probe] [--date=YYYY-MM-DD]
Sheet shape (all 'AMS main sheet' tabs): header row with FELLOW, ID plan, Plan Date, Pt name, MRN, Age, Room, ...,
Indication/ID Diagnosis, Actual antibiotics, Date started, Date ended, Released by ID, notes. A patient block is a row
carrying Pt name or MRN followed by continuation rows (blank name and MRN) that carry one antibiotic course each.
Output: list of blocks {sheet, name, mrn, fellow, room, age, admission, consult_date, dx, plan, plan_date, abx[], notes,
last_date, todos[], text}. Archive only: never current room or regimen. --probe prints sheet names and headers only.
"""
import sys, os, re, io, json, base64, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import parse_bed, parse_date, jdump

DATE_ANY = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")


def load_xlsx(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    obj = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    data = base64.b64decode(obj.get("content") or obj.get("fileContent") or "")
    import openpyxl
    return openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)


def cellstr(v):
    if v is None: return ""
    if hasattr(v, "strftime"): return v.strftime("%d/%m/%Y")
    return re.sub(r"\s+", " ", str(v)).strip()


def any_date(s, year):
    """First date in s as ISO; dd/mm without year gets the sheet year."""
    m = DATE_ANY.search(s or "")
    if not m: return None
    y = m.group(3)
    y = (int(y) + 2000 if y and len(y) == 2 else int(y)) if y else year
    try: return dt.date(y, int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError: return None


def col(hdr, *keys):
    for k in keys:
        for i, h in enumerate(hdr):
            if h and k in h:
                return i
    return None


def parse_sheet(ws, today):
    rows = [[cellstr(v) for v in r] for r in ws.iter_rows(values_only=True)]
    rows = [r for r in rows if any(r)]
    if not rows: return [], None
    hi = next((i for i, r in enumerate(rows[:5]) if any("pt name" in c.lower() or "patient name" in c.lower() for c in r)), None)
    if hi is None: return [], None
    hdr = [c.lower() for c in rows[hi]]
    C = {"fellow": col(hdr, "fellow"), "plan": col(hdr, "id plan", "follow up"), "plan_date": col(hdr, "plan date", "to be seen"),
         "name": col(hdr, "pt name", "patient name"), "mrn": col(hdr, "mrn"), "age": col(hdr, "age"), "room": col(hdr, "room"),
         "adm": col(hdr, "date of admission"), "consult": col(hdr, "date of id consult"), "dx": col(hdr, "indication"),
         "abx": col(hdr, "actual antibiotic"), "start": col(hdr, "date started"), "end": col(hdr, "date ended"),
         "released": col(hdr, "released"), "notes": col(hdr, "notes"), "cx": col(hdr, "culture"), "org": col(hdr, "organism")}
    m = re.search(r"(20\d{2})", ws.title); year = int(m.group(1)) if m else int(today[:4])
    g = lambda r, k: (r[C[k]] if C.get(k) is not None and C[k] < len(r) else "")
    blocks, cur = [], None
    for r in rows[hi + 1:]:
        name, mrn = g(r, "name"), re.sub(r"\D", "", g(r, "mrn"))
        if name or mrn:
            if cur: blocks.append(cur)
            fellow = re.sub(r"[^A-Za-z]", "", g(r, "fellow")).upper()[:3]
            cur = {"sheet": ws.title, "name": name, "mrn": mrn, "fellow": fellow, "room": parse_bed(g(r, "room"))[0] if g(r, "room") else "",
                   "age": g(r, "age"), "admission": any_date(g(r, "adm"), year), "consult_date": any_date(g(r, "consult"), year),
                   "dx": g(r, "dx"), "plan": g(r, "plan"), "plan_date": any_date(g(r, "plan_date"), year), "abx": [], "notes": [],
                   "cx": [], "dates": []}
        if not cur: continue
        if g(r, "abx"):
            cur["abx"].append({"drug": g(r, "abx"), "start": any_date(g(r, "start"), year), "end": any_date(g(r, "end"), year),
                               "released": g(r, "released").lower()[:3]})
        for k in ("notes", "cx", "org"):
            if g(r, k): cur["notes" if k == "notes" else "cx"].append(g(r, k))
        if not name and g(r, "plan"): cur["plan"] = (cur["plan"] + " / " + g(r, "plan")).strip(" /")
        for c in r:
            d = any_date(c, year)
            if d and d <= today: cur["dates"].append(d)
    if cur: blocks.append(cur)
    for b in blocks:
        b["last_date"] = max(b["dates"]) if b["dates"] else None
        del b["dates"]
        todos = []
        if b["plan"]: todos.append("ID plan%s: %s" % ((" " + b["plan_date"][5:].replace("-", "/")) if b["plan_date"] else "", b["plan"][:200]))
        for a in b["abx"]:
            if not a["end"] and a["released"] not in ("yes", "ye"):
                todos.append("%s started %s: no end date, not released" % (a["drug"][:40], a["start"][5:].replace("-", "/") if a["start"] else "?"))
        b["todos"] = todos[:6]
        b["text"] = " | ".join(x for x in ["dx: " + b["dx"], "abx: " + "; ".join("%s %s-%s%s" % (a["drug"], a["start"] or "?", a["end"] or "", " (released)" if a["released"].startswith("ye") else "") for a in b["abx"]),
                                            "plan: " + b["plan"], "cx: " + " / ".join(b["cx"]), "notes: " + " / ".join(b["notes"])] if not x.endswith(": "))[:4000]
    return blocks, hdr


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; probe = "--probe" in sys.argv
    inp, outp = args[0], args[1]
    today = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--date=")), dt.date.today().isoformat())
    if inp.upper() == "MISSING" or not os.path.exists(inp):
        jdump([], outp); print("AMS: 0 blocks (workbook missing)"); return
    wb = load_xlsx(inp)
    blocks = []
    for ws in wb.worksheets:
        b, hdr = parse_sheet(ws, today)
        blocks += b
        if probe:
            print("PROBE sheet '%s': %d blocks, header %s" % (ws.title, len(b), [h[:14] for h in hdr if h][:12] if hdr else "none"))
    recent = sum(1 for b in blocks if b["last_date"] and (dt.date.fromisoformat(today) - dt.date.fromisoformat(b["last_date"])).days <= 3)
    jdump(blocks, outp)
    print("AMS: %d blocks from %d sheets; with MRN %d, with fellow %d, with todos %d, dated within 3 days %d" % (
        len(blocks), len(wb.worksheets), sum(1 for b in blocks if b["mrn"]), sum(1 for b in blocks if b["fellow"]),
        sum(1 for b in blocks if b["todos"]), recent))


if __name__ == "__main__":
    main()
