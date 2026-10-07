#!/usr/bin/env python3
"""AMS row-block refresh for Chris's own patients (agreed 30.09.2026).

  ams_rows.py <ams_spill.json|ams.xlsx> <state_new.json> <outdir> --date YYYY-MM-DD [--fellow CH]

For every patient on today's census whose fellow is --fellow, find their CURRENT entry in the AMS
workbook (latest sheet, last entry of the matching block; an entry already shaded orange is still
used, with a note to check whether a new entry is needed; no entry at all gives a drafted new one),
copy it cell for cell over columns A:AH, and fill in what the
run learnt since: room, new antibiotic rows (drug, route, frequency, start, end; never a dose),
stop dates on open antibiotic rows, new culture results, new issues, and dated plan lines from
`updates`. Existing cells are reproduced as displayed and never rewritten except an empty or
"Ongoing" stop date. Added or changed cells are shaded pale green; other cells keep the sheet's own
fill. Output: <outdir>/AMS_rows_<YYYY-MM-DD>.xlsx (sheet "AMS rows": per patient a title line, the
AMS header row, then the block, columns aligned with the AMS sheet so rows paste straight across;
sheet "Summary": where each block sits and what changed). Delivered to Chris in the run session,
never by email. Prints counts and the file path only.
"""
import sys, os, io, re, json, base64, datetime, colorsys

COLS = 34  # A..AH
C_PLAN, C_PDATE, C_FELLOW, C_NAME, C_MRN, C_AGE, C_ROOM = 3, 4, 2, 5, 6, 7, 8
C_ADM, C_CONS, C_ISSUES, C_IND, C_ABX, C_START, C_END, C_CX = 12, 13, 16, 21, 22, 23, 24, 30
GREEN = "#d9f2d0"
HDR = "#d9d9d9"
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
          "sep": 9, "oct": 10, "nov": 11, "dec": 12}

DRUGS = [  # canonical, display name, regex on lower-case AMS text
    ("pip", "Piperacillin-tazobactam", r"pip|tazo"),
    ("mero", "Meropenem", r"mero"),
    ("imi", "Imipenem", r"imip|tienam"),
    ("erta", "Ertapenem", r"erta|invanz"),
    ("vanco", "Vancomycin", r"vanc"),
    ("teico", "Teicoplanin", r"teic|targo"),
    ("linez", "Linezolid", r"linez|zyvox"),
    ("dapto", "Daptomycin", r"dapto"),
    ("amik", "Amikacin", r"amik"),
    ("genta", "Gentamicin", r"genta"),
    ("tige", "Tigecycline", r"tige"),
    ("cipro", "Ciprofloxacin", r"cipro"),
    ("levo", "Levofloxacin", r"levo|tava"),
    ("moxi", "Moxifloxacin", r"moxi|avalox"),
    ("zavi", "Ceftazidime-avibactam", r"zavi|avibac"),
    ("zerbaxa", "Ceftolozane-tazobactam", r"zerbax|ceftoloz"),
    ("ceftaz", "Ceftazidime", r"ceftaz(?!.*avib)|fortum|\bcefta\b"),
    ("ceft", "Ceftriaxone", r"ceftriax|rocephin"),
    ("cefep", "Cefepime", r"cefep|maxipim"),
    ("cefaz", "Cefazolin", r"cefaz|kefzol"),
    ("cefurox", "Cefuroxime", r"cefurox|zinnat"),
    ("augmentin", "Amoxicillin-clavulanate", r"augment|clav"),
    ("ampi", "Ampicillin", r"ampic|\bampi\b"),
    ("amoxi", "Amoxicillin", r"amoxi(?!.*clav)"),
    ("clinda", "Clindamycin", r"clinda|dalacin"),
    ("flagyl", "Metronidazole", r"flagyl|metro"),
    ("azithro", "Azithromycin", r"azith|zithro|\bazi\b"),
    ("clarithro", "Clarithromycin", r"clarith"),
    ("doxy", "Doxycycline", r"doxy"),
    ("bactrim", "Trimethoprim-sulfamethoxazole", r"bactrim|cotrim|tmp.?smx"),
    ("colistin", "Colistin", r"colist"),
    ("fosfo", "Fosfomycin", r"fosfo"),
    ("aztreo", "Aztreonam", r"aztreo|azactam"),
    ("fluco", "Fluconazole", r"fluco|diflucan"),
    ("vori", "Voriconazole", r"vori|vfend"),
    ("posa", "Posaconazole", r"posa"),
    ("isavu", "Isavuconazole", r"isavu|cresemba"),
    ("caspo", "Caspofungin", r"caspo|cancidas"),
    ("ecalta", "Anidulafungin", r"ecalta|anidul"),
    ("mica", "Micafungin", r"micaf|mycamine"),
    ("ampho", "Amphotericin B", r"ampho|ambisome"),
    ("valtrex", "Valaciclovir", r"valac|valtrex"),
    ("acyclo", "Aciclovir", r"acyc|acic|zovirax"),
    ("ganci", "Ganciclovir", r"ganc|cymeven"),
    ("valganci", "Valganciclovir", r"valgan|valcyte"),
    ("remdes", "Remdesivir", r"remde"),
    ("fucid", "Fusidic acid", r"fucid|fusid"),
    ("nysta", "Nystatin", r"nysta|mycostat"),
    ("itra", "Itraconazole", r"itra|sporanox"),
    ("oselta", "Oseltamivir", r"oselt|tamiflu|flumivir"),
    ("rifa", "Rifampicin", r"rifam"),
    ("nitrofur", "Nitrofurantoin", r"nitrof|macrob|furadant"),
]
DISPLAY = {k: d for k, d, _ in DRUGS}
RX = [(k, re.compile(r)) for k, _, r in DRUGS]


def canon(text):
    t = (text or "").lower()
    for k, rx in RX:
        if rx.search(t):
            return k
    w = re.sub(r"[^a-z]", "", t)
    return w[:5] or None


# ---------------------------------------------------------------- workbook
def load(p):
    import openpyxl
    if p.endswith(".json"):
        d = json.load(open(p))
        return openpyxl.load_workbook(io.BytesIO(base64.b64decode(d["content"])))
    return openpyxl.load_workbook(p)


def rgb(c):
    f = c.fill
    if not f or not f.fill_type or f.fgColor is None or f.fgColor.type != "rgb":
        return None
    v = f.fgColor.rgb or ""
    return v[-6:].upper() if len(v) >= 6 else None


def is_orange(h):
    if not h:
        return False
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ss, vv = colorsys.rgb_to_hsv(r, g, b)
    return 15 / 360 <= hh <= 45 / 360 and ss >= 0.45 and vv >= 0.6


def sheet_rank(title):
    t = title.lower()
    y = int(re.search(r"(20\d\d)", t).group(1)) if re.search(r"20\d\d", t) else 2026
    m = max([v for k, v in MONTHS.items() if k in t] or [0])
    return (y, m)


def norm(s):
    return " ".join(re.sub(r"[^a-z ]", " ", (s or "").lower()).split())


def shown(c):
    """The cell as Excel displays it (dates through the cell's own number format)."""
    v = c.value
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        f = (c.number_format or "").lower().replace("\\", "").replace('"', "")
        if "general" in f or not re.search(r"[dmy]", f):
            f = "mm/dd/yy"
        py = ""
        for tok in re.findall(r"y+|m+|d+|[^ymd]+", f.split(";")[0]):
            if tok[0] == "y":
                py += "%Y" if len(tok) >= 4 else "%y"
            elif tok[0] == "m":
                py += "%b" if len(tok) == 3 else ("%B" if len(tok) > 3 else "%m")
            elif tok[0] == "d":
                py += "%d" if len(tok) <= 2 else "%a"
            else:
                py += re.sub(r"[^/.\- ]", "", tok)
        try:
            return v.strftime(py or "%m/%d/%y")
        except Exception:
            return v.strftime("%m/%d/%y")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def name_match(a, b):
    """Same patient by name: surname equal and first names alike (Suzane/Suzanne, Mohammad/Mohamad)."""
    ta, tb = norm(a).split(), norm(b).split()
    if not ta or not tb:
        return False
    if norm(a) == norm(b):
        return True
    def sim(x, y):
        x, y = re.sub(r"(.)\1", r"\1", x), re.sub(r"(.)\1", r"\1", y)
        x, y = x.replace("ou", "u").replace("ey", "i"), y.replace("ou", "u").replace("ey", "i")
        return x == y or (len(x) > 3 and len(y) > 3 and (x.startswith(y) or y.startswith(x)))
    return sim(ta[0], tb[0]) and sim(ta[-1], tb[-1])


def index_entries(wb):
    """(rank, sheet, first_row, last_row, rows) for every patient entry, latest sheet first."""
    sheets = sorted([ws for ws in wb.worksheets if "main sheet" in ws.title.lower()],
                    key=lambda w: sheet_rank(w.title), reverse=True)
    out = []
    for ws in sheets:
        rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=COLS))
        reds = [i + 1 for i, row in enumerate(rows) if sum(rgb(c) == "FF0000" for c in row[:14]) >= 6]
        edges = [1] + reds + [len(rows) + 1]
        for a, b in zip(edges, edges[1:]):
            starts = [r for r in range(a + 1, b) if (rows[r - 1][C_NAME - 1].value or rows[r - 1][C_MRN - 1].value)]
            for i, s in enumerate(starts):
                e = (starts[i + 1] - 1) if i + 1 < len(starts) else b - 1
                out.append((ws, s, e, rows))
    return out


def find_entry(entries, mrn, names):
    best = None
    for ws, s, e, rows in entries:
        r0 = rows[s - 1]
        m = str(r0[C_MRN - 1].value or "").split(".")[0].strip()
        n = str(r0[C_NAME - 1].value or "")
        hit = (mrn and m == mrn) or (any(name_match(n, x) for x in names) and (not mrn or not m.isdigit() or m == mrn))
        if hit:
            if best is None or (best[0] is ws and s > best[1]):
                best = (ws, s, e, rows)
            elif best[0] is not ws:
                break
    return best


# ---------------------------------------------------------------- state side
DATE = re.compile(r"(\d{1,2})[/.](\d{1,2})")


def ddmm(s):
    m = DATE.search(s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def date_variants(d):
    a, b = d
    return {"%02d/%02d" % (a, b), "%d/%d" % (a, b), "%02d.%02d" % (a, b), "%d.%d" % (a, b),
            "%d/%02d" % (a, b), "%02d/%d" % (a, b), "%d.%02d" % (a, b)}


def parse_abx(line):
    """'Pip IV q6h 18/09-25/09' -> dict(drug, route, freq, start, end, open)."""
    head = line.split("(")[0]
    toks = head.split()
    if not toks:
        return None
    route = next((t for t in toks[1:4] if t.upper() in ("IV", "PO", "IM", "SC", "INH") or t.lower() == "topical"), "")
    freq = next((t for t in toks[1:5] if re.fullmatch(r"(q\d+h|OD|BID|TID|QID|x\d|once|weekly)", t, re.I)), "")
    ranges = re.findall(r"~?(\d{1,2}/\d{1,2})(?:\s*-\s*(\d{1,2}/\d{1,2})?|\b)", head)
    if not ranges:
        return None
    start = ranges[0][0]
    dash_open = bool(re.search(r"\d{1,2}/\d{1,2}\s*-\s*$", head.strip())) or bool(re.search(r"\d/\d{1,2}-\s*(\(|$)", line))
    end = ranges[-1][1] or ("" if dash_open else (ranges[-1][0] if re.search(r"x1|once", head, re.I) else ""))
    return dict(drug=toks[0], route=route.upper() if route.lower() != "topical" else "topical",
                freq=freq, start=start, end=end, open=not end)


def near(x, y):
    try:
        return abs((datetime.date(2026, x[1], x[0]) - datetime.date(2026, y[1], y[0])).days) <= 3
    except Exception:
        return False


def issue_head(dx):
    h = (dx or "").split("|")[0].strip()
    return h[:120]


ABBR = [(r"\bbcx\b", "blood culture"), (r"\bucx\b", "urine culture"), (r"\bcx\b", "culture"),
        (r"\bbal\b", "bronchoalveolar"), (r"\bcsf\b", "cerebrospinal"), (r"\bua\b", "urinalysis"),
        (r"\bsa\b", "stool analysis"), (r"\bpcr\b", "pcrx")]


def words(s):
    s = (s or "").lower()
    for a, b in ABBR:
        s = re.sub(a, b, s)
    return {w for w in re.findall(r"[a-z]{4,}", s)
            if w not in ("with", "from", "negative", "positive", "pending", "sets", "since", "none", "done")}


# ---------------------------------------------------------------- build one block
class Block:
    def __init__(self, cells, fills, origin):
        self.cells = cells      # list of rows, each a list of 34 strings
        self.fills = fills      # original fills (hex or None)
        self.changed = set()    # (r, c) 0-based
        self.orig_len = len(cells)
        self.origin = origin
        self.log = []

    def ensure(self, r):
        while len(self.cells) <= r:
            self.cells.append([""] * COLS)
            self.fills.append([None] * COLS)

    def set(self, r, c, v):
        self.ensure(r)
        self.cells[r][c - 1] = v
        self.changed.add((r, c - 1))

    def col_text(self, *cs):
        return "\n".join(row[c - 1] for row in self.cells for c in cs)

    def next_free(self, group):
        last = -1
        for i, row in enumerate(self.cells):
            if any(row[c - 1].strip() for c in group):
                last = i
        return last + 1

    def add_rows(self, group, values_list):
        r = self.next_free(group)
        for vals in values_list:
            for c, v in zip(group, vals):
                if v:
                    self.set(r, c, v)
            r += 1


def fmt_date(d, year):
    return "%02d/%02d/%s" % (d[0], d[1], str(year)[2:])


def refresh(block, p, today, new_entry):
    sy = p.get("synth") or {}
    year = today.year
    # room
    room = str(sy.get("_room") or "").strip()
    if room and norm(room.replace(" ", "")) != norm(block.cells[0][C_ROOM - 1].replace(" ", "").replace(".0", "")):
        block.set(0, C_ROOM, room)
        block.log.append("room")
    # antibiotics
    have = []
    for i, row in enumerate(block.cells):
        if row[C_ABX - 1].strip():
            have.append((i, canon(row[C_ABX - 1]), ddmm(row[C_START - 1]), row[C_END - 1].strip()))
    new_rows, stops = [], 0
    for iss in sy.get("issues") or []:
        for line in iss.get("abx") or []:
            a = parse_abx(line)
            if not a:
                continue
            k = canon(a["drug"])
            st = ddmm(a["start"])
            cands = [h for h in have if h[1] == k]
            same = [h for h in cands if h[2] == st] or [h for h in cands if near(h[2], st)] or [h for h in cands if h[2] is None]
            if not same:
                # a still-open row of the same drug started earlier counts as this course
                same = [h for h in cands if h[3].lower() in ("", "ongoing", "_", "-", "–")]
            if same:
                i, _, hst, hend = same[-1]
                if a["end"] and hend.lower() in ("", "ongoing"):
                    block.set(i, C_END, a["end"])
                    stops += 1
                if hst is None and a["start"] and not block.cells[i][C_START - 1].strip():
                    block.set(i, C_START, a["start"])
                continue
            label = " ".join(x for x in (DISPLAY.get(k, a["drug"]), a["route"], a["freq"]) if x)
            new_rows.append((issue_head(iss.get("dx"))[:80], label, a["start"], a["end"] or "Ongoing"))
            have.append((-1, k, st, a["end"]))
    if new_rows:
        block.add_rows((C_IND, C_ABX, C_START, C_END), new_rows)
    if new_rows or stops:
        block.log.append("abx +%d rows, %d stop dates" % (len(new_rows), stops))
    # culture results
    known = block.col_text(C_CX, C_CX + 1, C_CX + 2, 20, 34).lower()
    add = []
    for m in sy.get("micro") or []:
        d = ddmm(m)
        w = words(m)
        if d:
            present = any(v in known for v in date_variants(d)) and any(x in known for x in w)
        else:
            present = not w or len(w & words(known)) / len(w) >= 0.5
        if not present:
            add.append((m,))
    if add:
        block.add_rows((C_CX,), add)
        block.log.append("cultures +%d" % len(add))
    # issues
    ptxt = block.col_text(C_ISSUES)
    add = []
    for iss in sy.get("issues") or []:
        h = issue_head(iss.get("dx"))
        w = words(h)
        if h and (not w or len(w & words(ptxt)) / len(w) < 0.4):
            add.append((h,))
            ptxt += "\n" + h
    if add:
        block.add_rows((C_ISSUES,), add)
        block.log.append("issues +%d" % len(add))
    # dated plan lines (C/D) newer than the last plan date on the sheet
    last = None
    for row in block.cells:
        d = ddmm(row[C_PDATE - 1])
        if d and d[1] <= 12 and d[0] <= 31:
            key = (d[1], d[0])
            last = key if last is None or key > last else last
    if new_entry:
        last = None
    add = []
    for u in sy.get("updates") or []:
        mm = re.match(r"^(\d{2})/(\d{2}): (.+)$", u)
        if mm:
            d = (int(mm.group(1)), int(mm.group(2)))
            txt = mm.group(3)
        elif u.startswith("o/n: "):
            d, txt = (today.day, today.month), u[5:]
        else:
            continue
        if last is None or (d[1], d[0]) > last:
            add.append((txt, fmt_date(d, year)))
    if add:
        block.add_rows((C_PLAN, C_PDATE), add)
        block.log.append("plan +%d" % len(add))


def skeleton(p, fellow, today):
    sy = p.get("synth") or {}
    ol = sy.get("one_liner") or ""
    age = (re.match(r"\s*(\d{1,3})\s*[MF]\b", ol) or [None, ""])[1]
    adm = re.search(r"\badm (\d{1,2}/\d{1,2})", ol)
    fs = p.get("first_seen") or today.isoformat()
    fsd = datetime.date.fromisoformat(fs)
    row = [""] * COLS
    row[C_FELLOW - 1] = fellow
    row[C_NAME - 1] = p.get("name") or sy.get("name") or ""
    row[C_MRN - 1] = p.get("mrn") or ""
    row[C_AGE - 1] = age
    row[C_ADM - 1] = adm.group(1) if adm else ""
    row[C_CONS - 1] = "UC" if "uc" in [t.lower() for t in sy.get("_tags") or []] else fsd.strftime("%d/%m/%y")
    b = Block([row], [[None] * COLS], None)
    for c, v in enumerate(row):
        if v:
            b.changed.add((0, c))
    return b


# ---------------------------------------------------------------- html
HEAD = ["", "FELLOW", "Plan", "Plan Date", "Pt name", "MRN", "Age", "Room", "weight", "Creatinine",
        "CrCl", "Date of Admission", "Date of ID Consultation", "Chief complaint", "PMH", "Active Issues",
        "last hospitalization", "Abx history", "Imaging", "Pertinent labs", "Indication/ID Diagnosis",
        "Actual antibiotics", "Date started", "Date ended", "Released by ID", "Duration advice",
        "Attending", "Lines", "Discharge Abx", "Culture results/Notes", "Preliminary Results", "Organism",
        "Antibiogram", "notes"]


def letters(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(path, items, widths, today):
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AMS rows"
    fill = lambda h: PatternFill("solid", fgColor="FF" + h)
    grey, green = fill(HDR[1:].upper()), fill(GREEN[1:].upper())
    body_font, bold = Font(name="Arial", size=9), Font(name="Arial", size=9, bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    r = 1
    for title, sub, b in items:
        ws.cell(r, 1, title).font = Font(name="Arial", size=11, bold=True)
        ws.cell(r + 1, 1, sub).font = Font(name="Arial", size=9, italic=True)
        r += 2
        for c, h in enumerate(HEAD, 1):
            x = ws.cell(r, c, h)
            x.fill, x.font, x.alignment = grey, bold, wrap
        r += 1
        for i, row in enumerate(b.cells):
            for c, v in enumerate(row):
                x = ws.cell(r, c + 1, v if v != "" else None)
                x.font, x.alignment = body_font, wrap
                if (i, c) in b.changed:
                    x.fill = green
                elif b.fills[i][c]:
                    x.fill = fill(b.fills[i][c])
            r += 1
        r += 2
    for c in range(1, COLS + 1):
        ws.column_dimensions[letters(c - 1)].width = widths.get(c) or 14
    sm = wb.create_sheet("Summary")
    sm.append(["Patient", "Where in the AMS sheet", "Changes"])
    for title, sub, b in items:
        sm.append([title, sub, ", ".join(b.log) or "none"])
    for col, w in (("A", 45), ("B", 90), ("C", 60)):
        sm.column_dimensions[col].width = w
    for _ws in wb.worksheets:  # OVERLAY_6 4b: no en/em dash leaves in the AMS rows file
        for _row in _ws.iter_rows():
            for _c in _row:
                if isinstance(_c.value, str) and ("\u2013" in _c.value or "\u2014" in _c.value):
                    _c.value = _c.value.replace("\u2013", "-").replace("\u2014", "-")
    wb.save(path)


def main():
    args = sys.argv[1:]
    ams, st, outdir = args[0], args[1], args[2]
    opt = dict(zip(args[3::2], args[4::2]))
    today = datetime.date.fromisoformat(opt["--date"])
    fellow = opt.get("--fellow", "CH")
    state = json.load(open(st))
    pats = [p for p in state["patients"].values()
            if (p.get("synth") or {}).get("_fellow") == fellow
            and ((p.get("active") and (p.get("synth") or {}).get("_date") == today.isoformat())
                 or (not p.get("active") and p.get("archived")))]
    wb = load(ams) if ams != "MISSING" else None
    entries = index_entries(wb) if wb else []
    widths = {}
    if wb:
        top = sorted([w for w in wb.worksheets if "main sheet" in w.title.lower()],
                     key=lambda w: sheet_rank(w.title), reverse=True)
        if top:
            for c in range(1, COLS + 1):
                d = top[0].column_dimensions.get(letters(c - 1))
                widths[c] = min(d.width, 60) if d is not None and d.width else None
    items, n_changed, n_new, n_same = [], 0, 0, 0
    n_fin, n_off, n_drop = 0, 0, 0
    for p in sorted(pats, key=lambda x: (not x.get("active"), str((x.get("synth") or {}).get("_room") or ""))):
        names = [p.get("name") or ""] + list(p.get("aliases") or [])
        hit = find_entry(entries, str(p.get("mrn") or "").strip(), names) if entries else None
        off = not p.get("active")
        if off:
            if hit:
                _ws, _s, _e, _rows = hit
                _f = [rgb(c) for r in range(_s, _e + 1) for c in _rows[r - 1][:14]]
                if sum(is_orange(h) for h in _f) / max(1, len(_f)) >= 0.7:
                    n_fin += 1
                    continue
            else:
                try:
                    age = (today - datetime.date.fromisoformat(str(p.get("archived"))[:10])).days
                except Exception:
                    age = 0
                if age > 14:
                    n_drop += 1
                    continue
            n_off += 1
        if hit:
            ws, s, e, rows = hit
            fills = [[rgb(c) for c in rows[r - 1][:COLS]] + [None] * (COLS - len(rows[r - 1][:COLS]))
                     for r in range(s, e + 1)]
            share = sum(is_orange(h) for fr in fills for h in fr[:14]) / max(1, 14 * len(fills))
            cells = [[shown(c) for c in rows[r - 1][:COLS]] + [""] * (COLS - len(rows[r - 1][:COLS]))
                     for r in range(s, e + 1)]
            b = Block(cells, fills, (ws.title, s, e))
            refresh(b, p, today, False)
            grow = len(b.cells) - b.orig_len
            sub = "%s, rows %d to %d" % (ws.title, s, e)
            if share >= 0.7:
                sub += "; NOTE this entry is shaded orange (closed) on the sheet: check whether a new entry is needed"
            sub += (" (insert %d row%s below row %d before pasting)" % (grow, "s" if grow > 1 else "", e)
                    if grow > 0 else " (same size, paste over it)")
        else:
            b = skeleton(p, fellow, today)
            refresh(b, p, today, True)
            sub = "no entry found in the AMS sheet: new entry, paste where it belongs"
            n_new += 1
        if not b.changed:
            n_same += 1
            sub += "; no change since the sheet"
        elif hit:
            n_changed += 1
        title = "%s  |  %s  |  MRN %s" % ((p.get("synth") or {}).get("_room") or "?", p.get("name"), p.get("mrn") or "?")
        if off:
            title += "  |  OFF LIST since %s, AMS block not finalised" % str(p.get("archived"))[:10]
        items.append((title, sub, b))
    path = os.path.join(outdir, "AMS_rows_%s.xlsx" % today.isoformat())
    if items:
        write_xlsx(path, items, widths, today)
    print("AMS ROWS OK: %d patients (%d with changes in place, %d new entries, %d unchanged; %d off-list still open, %d off-list finalised and dropped, %d off-list with no block for >14d dropped)%s"
          % (len(items), n_changed, n_new, n_same, n_off, n_fin, n_drop, (", file " + path) if items else ", no file (no patients)"))


if __name__ == "__main__":
    main()
