#!/usr/bin/env python3
"""Parse the pharmacy AS list email into patients + restricted-antimicrobial orders.

Usage: parse_as.py <raw.json|spill.json|file.eml> <out.json>
Input is the Gmail get_message RAW result (JSON with a base64url 'raw' field), spilled or recovered, or an .eml.
Reads every attachment (xlsx/xls/csv/html) and every inline HTML table, keeps whichever yields the most rows.
Prints counts and 'sources tried:' only; never prints patient data.
"""
import sys, re, json, base64, io, email, datetime as dt
from email import policy
from html.parser import HTMLParser
sys.path.insert(0, __import__("os").path.dirname(__file__))
from common import drug_short, freq_short, parse_bed, norm_name, parse_date, jdump

HDR_ALIASES = {
    "mrn": ["mrn", "medical record"], "physician": ["ordering physician"], "name": ["patient name"],
    "age": ["age"], "weight": ["patient weight"], "weight_unit": ["weight unit"], "bed": ["bed", "room"],
    "desc": ["description of order", "order description", "medication"], "duration": ["order duration"],
    "duration_unit": ["duration unit"], "valid_from": ["valid from"], "valid_to": ["valid to"],
    "crcl": ["creatinine"], "admission": ["admission date"], "order_no": ["order number"],
}


LOOSE_ALIASES = {
    "mrn": ["file no", "file number", "patient id", "pt id", "hospital no", "record no", "mrn#", "pid"],
    "name": ["name", "patient"], "bed": ["location", "ward", "unit", "floor"],
    "desc": ["drug", "antibiotic", "antimicrobial", "order", "item", "product", "generic"],
    "valid_from": ["start"], "valid_to": ["stop", "end date"], "admission": ["admission", "admit"],
}
QUOTE_RE = re.compile(r'<blockquote|class="gmail_quote|id="divRplyFwdMsg|id="appendonsend|-----Original Message-----|<div[^>]*border-top:\s*solid\s*#E1E1E1', re.I)


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables = []; self.row = None; self.cell = None; self.depth = 0
    def handle_starttag(self, tag, attrs):
        if tag == "table": self.depth += 1; self.tables.append([])
        elif tag == "tr" and self.depth: self.row = []
        elif tag in ("td", "th") and self.depth: self.cell = []
        elif tag == "br" and self.cell is not None: self.cell.append(" ")
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip()); self.cell = None
        elif tag == "tr" and self.row is not None:
            self.tables[-1].append(self.row); self.row = None
        elif tag == "table" and self.depth: self.depth -= 1
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)


def html_tables(html):
    p = TableParser(); p.feed(html); return p.tables


def map_header(hdr):
    cols = {}
    for i, h in enumerate(hdr):
        hl = (h or "").strip().lower()
        for key, als in HDR_ALIASES.items():
            if key not in cols and any(a in hl for a in als):
                if key == "weight" and "unit" in hl: continue
                if key == "duration" and "unit" in hl: continue
                cols[key] = i
    used = set(cols.values())
    for i, h in enumerate(hdr):
        if i in used: continue
        hl = (h or "").strip().lower()
        if not hl: continue
        for key, als in LOOSE_ALIASES.items():
            if key in cols: continue
            if key == "name" and re.search(r"physician|doctor|\bdr\b|nurse|ward|unit|drug|user", hl): continue
            if any(a in hl for a in als):
                cols[key] = i; used.add(i); break
    return cols


def table_rows(tab):
    """Return list of dict rows if the table looks like an AS list, else []."""
    if not tab or len(tab) < 2: return []
    for hi in range(min(8, len(tab))):
        cols = map_header(tab[hi])
        if "mrn" in cols and "name" in cols and "desc" in cols:
            out = []
            for r in tab[hi + 1:]:
                if len(r) <= max(cols.values()): continue
                d = {k: (r[i] or "").strip() for k, i in cols.items()}
                if not d.get("mrn") or not re.search(r"\d", d["mrn"]): continue
                out.append(d)
            return out
    return []


def rows_from_xlsx(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    best = []
    for ws in wb.worksheets:
        tab = []
        for row in ws.iter_rows(values_only=True):
            tab.append(["" if v is None else (v.strftime("%d/%m/%Y") if hasattr(v, "strftime") else str(v)) for v in row])
        rows = table_rows(tab)
        if len(rows) > len(best): best = rows
    return best


def rows_from_csv(data):
    import csv
    txt = data.decode("utf-8-sig", "replace")
    tab = list(csv.reader(io.StringIO(txt)))
    return table_rows(tab)


def load_message(path):
    if path.lower().endswith(".eml"):
        return email.message_from_bytes(open(path, "rb").read(), policy=policy.default)
    txt = open(path, encoding="utf-8").read()
    obj = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    raw = obj["raw"]
    b = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    return email.message_from_bytes(b, policy=policy.default)


def _date_in(s):
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", s or "")
    if not m:
        return None
    y = int(m.group(3)); y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def _received_date(msg_date):
    """Beirut calendar date the mail arrived. Uses the real zone: Lebanon is +3
    only in summer, so a hardcoded +3 mis-dates every list from late October."""
    try:
        d = email.utils.parsedate_to_datetime(msg_date)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        try:
            from zoneinfo import ZoneInfo
            return d.astimezone(ZoneInfo("Asia/Beirut")).date().isoformat()
        except Exception:
            return (d.astimezone(dt.timezone.utc) + dt.timedelta(hours=3)).date().isoformat()
    except Exception:
        return None


def list_date_from(subject, msg_date, filenames=()):
    """The date of the list itself.

    Priority: attachment filename, then subject, then arrival date. Pharmacy
    often replies into an old thread, so the subject can carry a stale date
    ("Re: AS List 05.09.2026" on the 06.09 list). A subject date is therefore
    trusted only when it agrees with the Beirut date the mail arrived.
    """
    for fn in filenames:
        d = _date_in(fn)
        if d:
            return d
    recv = _received_date(msg_date)
    subj = _date_in(subject)
    if subj and (recv is None or subj == recv):
        return subj
    return recv or subj


def build_patients(rows):
    pats = {}
    for r in rows:
        mrn = re.sub(r"\D", "", r.get("mrn", ""))
        p = pats.setdefault(mrn, {"mrn": mrn, "name": r.get("name", ""), "name_norm": norm_name(r.get("name", "")),
                                  "age": r.get("age", ""), "weight_kg": r.get("weight", ""), "bed": r.get("bed", ""),
                                  "admission_date": parse_date(r.get("admission", "")), "crcl": r.get("crcl", ""),
                                  "physicians": [], "orders": []})
        room, grp, flags = parse_bed(r.get("bed", ""))
        p["room"], p["group"], p["flags"] = room, grp, flags
        if r.get("physician") and r["physician"] not in p["physicians"]: p["physicians"].append(r["physician"])
        desc = r.get("desc", "")
        unit = (r.get("duration_unit") or "").upper()
        once = bool(re.search(r"\bONCE\b", desc.upper())) or unit.startswith("DOS")
        p["orders"].append({
            "desc": desc, "drug": drug_short(desc), "freq": "x1" if once else freq_short(desc), "once": once,
            "valid_from": parse_date(r.get("valid_from", "")), "valid_to": parse_date(r.get("valid_to", "")),
            "duration": r.get("duration", ""), "duration_unit": unit, "order_no": r.get("order_no", ""),
        })
    out = []
    for p in pats.values():
        p["once_only"] = all(o["once"] for o in p["orders"])
        p["drugs"] = sorted(set(o["drug"] for o in p["orders"]))
        p["standing_drugs"] = sorted(set(o["drug"] for o in p["orders"] if not o["once"]))
        try:
            if int(re.sub(r"\D", "", p["age"]) or 99) < 18 and "paeds" not in p["flags"]: p["flags"].append("paeds age")
        except ValueError: pass
        out.append(p)
    out.sort(key=lambda p: (p["group"], p["room"]))
    return out


def rows_from_xls(data):
    import xlrd  # pip install xlrd --break-system-packages
    wb = xlrd.open_workbook(file_contents=data); best = []
    for ws in wb.sheets():
        tab = [[str(c.value) if c.value is not None else "" for c in ws.row(r)] for r in range(ws.nrows)]
        rows = table_rows(tab)
        if len(rows) > len(best): best = rows
    return best


def rows_from_text(txt):
    tab = [re.split(r"\t|\s{2,}|\s*\|\s*", l.strip()) for l in txt.splitlines() if l.strip()]
    return table_rows(tab)


def rows_from_html(html):
    best = []
    for t in html_tables(html):
        r2 = table_rows(t)
        if len(r2) > len(best): best = r2
    return best


def main(inp, outp):
    """Overlay 4 (05.10.2026): every source is tried; ranking, best first:
    0 spreadsheet whose filename date is the arrival date, 1 undated spreadsheet/csv,
    2 inline HTML table above any quoted reply, 3 plain-text table, 4 spreadsheet with another date,
    5 table inside quoted (replied-to) text. Ties: more rows."""
    msg = load_message(inp)
    subject = msg.get("subject", ""); sender = msg.get("from", ""); date = msg.get("date", "")
    recv = _received_date(date)
    tried = []; cands = []
    for part in msg.walk():
        ct = part.get_content_type(); fn = part.get_filename() or ""; fl = fn.lower()
        if part.is_multipart(): continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None
        if payload is None: continue
        fdate = _date_in(fn) if fn else None
        sheet_prio = 0 if (fdate and fdate == recv) else (1 if not fdate else 4)
        try:
            if fl.endswith((".xlsx", ".xlsm")) or "spreadsheetml" in ct:
                label = "attachment:%s" % fn; tried.append(label)
                cands.append((sheet_prio, rows_from_xlsx(payload), label, fdate))
            elif fl.endswith(".xls") or ct == "application/vnd.ms-excel":
                label = "attachment:%s" % fn
                try:
                    cands.append((sheet_prio, rows_from_xls(payload), label, fdate)); tried.append(label)
                except ImportError:
                    tried.append(label + " (xls: run pip install xlrd --break-system-packages, then re-run)")
            elif fl.endswith(".csv") or ct == "text/csv":
                label = "attachment:%s" % fn; tried.append(label)
                cands.append((sheet_prio, rows_from_csv(payload), label, fdate))
            elif fl.endswith((".htm", ".html")) or ct == "text/html":
                html = payload.decode(part.get_content_charset() or "utf-8", "replace")
                m = QUOTE_RE.search(html)
                fresh, quoted = (html[:m.start()], html[m.start():]) if m else (html, "")
                label = "attachment:%s" % fn if fn else "inline html"
                tried.append(label)
                cands.append((2 if not fn else sheet_prio, rows_from_html(fresh), label, fdate))
                if quoted:
                    tried.append(label + " (quoted part)")
                    cands.append((5, rows_from_html(quoted), label + " (quoted part)", None))
            elif ct == "text/plain" and not fn:
                txt = payload.decode(part.get_content_charset() or "utf-8", "replace")
                cut = re.search(r"^(>|-----Original Message-----|On .{5,80} wrote:|From: )", txt, re.M)
                tried.append("plain text")
                cands.append((3, rows_from_text(txt[:cut.start()] if cut else txt), "plain text", None))
        except Exception as e:
            tried.append("%s (error %s)" % (fn or ct, e.__class__.__name__))
    good = [c for c in cands if c[1]]
    good.sort(key=lambda c: (c[0], -len(c[1])))
    rows, src, fdate = (good[0][1], good[0][2], good[0][3]) if good else ([], "none", None)
    patients = build_patients(rows)
    list_date = fdate if (fdate and fdate == recv) else list_date_from(subject, date, ())
    out = {"subject": subject, "from": sender, "date": date, "list_date": list_date, "received_date": recv,
           "filename_date": fdate, "source_used": src, "sources_tried": tried, "n_rows": len(rows), "patients": patients}
    jdump(out, outp)
    print("AS list %s: %d order rows, %d patients (%d standing, %d once-only), source=%s" % (
        out["list_date"], len(rows), len(patients), sum(1 for p in patients if not p["once_only"]),
        sum(1 for p in patients if p["once_only"]), src))
    if fdate and fdate != recv:
        print("note: chosen file is dated %s but the email arrived %s" % (fdate, recv))
    print("sources tried:", ", ".join(tried) or "none")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
