"""Shared helpers for the ID service pipeline (no patient data in this file)."""
import re, json, unicodedata, datetime as dt

WARD_ORDER = ["7th floor", "ICU#B", "4th floor", "ICU#D", "3rd floor", "2nd floor", "ER IN", "Paeds", "Other"]

DRUG_SHORT = [
    ("PIPERACILLIN", "Piptazo"), ("MEROPENEM", "Mero"), ("ERTAPENEM", "Erta"), ("IMIPENEM", "Imipenem"),
    ("CEFTAZIDIME/AVIBACTAM", "Zavi"), ("AVIBACTAM", "Zavi"), ("CEFTOLOZANE", "Zerb"), ("CEFEPIME", "Cefe"),
    ("CEFTRIAXONE", "Ceftriax"), ("CEFTAZIDIME", "Ceftaz"), ("AZTREONAM", "Aztreo"), ("AMIKACIN", "Amik"),
    ("GENTAMICIN", "Genta"), ("TIGECYCLINE", "Tige"), ("VANCOMYCIN", "Vanco"), ("TEICOPLANIN", "Teico"),
    ("LEVOFLOXACIN", "Tavanic"), ("CIPROFLOXACIN", "Cipro"), ("MOXIFLOXACIN", "Moxi"), ("AZITHROMYCIN", "Azithro"),
    ("METRONIDAZOLE", "Flagyl"), ("SULFAMETHOXAZOLE", "Bactrim"), ("TRIMETHOPRIM", "Bactrim"),
    ("AMOXICILLIN/CLAVULAN", "Augmentin"), ("CLAVULAN", "Augmentin"), ("AMOXICILLIN", "Amox"), ("AMPICILLIN", "Ampi"),
    ("FLUCONAZOLE", "Fluco"), ("VORICONAZOLE", "Vori"), ("POSACONAZOLE", "Posa"), ("ISAVUCONAZ", "Isavu"),
    ("CASPOFUNGIN", "Caspo"), ("ANIDULAFUNGIN", "Ecalta"), ("MICAFUNGIN", "Mica"), ("AMPHOTERICIN", "AmphoB"),
    ("VALGANCICLOVIR", "Valganci"), ("GANCICLOVIR", "Ganci"), ("ACYCLOVIR", "Acyclo"), ("FIDAXOMICIN", "Fidaxo"),
    ("COLISTIN", "Colistin"), ("COLISTIMETHATE", "Colistin"), ("LINEZOLID", "Linez"), ("DAPTOMYCIN", "Dapto"),
    ("FOSFOMYCIN", "Fosfo"), ("RIFAMPICIN", "Rifampicin"), ("CLINDAMYCIN", "Clinda"), ("DOXYCYCLINE", "Doxy"),
    ("OSELTAMIVIR", "Oselta"), ("REMDESIVIR", "Remde"), ("NITROFURANTOIN", "Nitrofur"), ("CEFUROXIME", "Cefurox"),
    ("CEFAZOLIN", "Cefazolin"), ("CLARITHROMYCIN", "Clarithro"), ("PENICILLIN", "PenG"), ("OXACILLIN", "Oxa"),
]

FREQ_MAP = [
    (r"\bONCE\b", "x1"), (r"\bQ4H", "q4h"), (r"\bQ6H", "q6h"), (r"\bQ8H", "q8h"), (r"\bQ12H", "q12h"),
    (r"\bQ24H", "OD"), (r"\bQ48H", "q48h"), (r"\bQ72H", "q72h"), (r"\bDAILY\b", "OD"), (r"\bOD\b", "OD"),
    (r"\bBID\b", "BID"), (r"\bTID\b", "TID"), (r"\bQID\b", "QID"), (r"\bWEEKLY\b", "weekly"),
    (r"\bQ1W\b", "weekly"), (r"\bQ7D\b", "weekly"), (r"\bQ(\d+)H", None),
]


def drug_short(desc):
    """Short handout name from an order description or free text."""
    u = desc.upper()
    m = re.search(r"\(([A-Z/ \-]+)\)", u)
    gen = m.group(1) if m else u
    for key, short in DRUG_SHORT:
        if key in gen:
            return short
    for key, short in DRUG_SHORT:
        if key in u:
            return short
    w = re.sub(r"[^A-Z]", "", gen.split()[0] if gen.split() else gen)
    return (w[:5].capitalize() if w else "Unknown")


def freq_short(desc):
    u = desc.upper()
    for pat, short in FREQ_MAP:
        m = re.search(pat, u)
        if m:
            return short if short else "q%sh" % m.group(1)
    return "?"


def parse_bed(bed):
    """'B708B' -> room '708B', group '7th floor'. Returns (room, group, flags)."""
    b = (bed or "").strip().upper()
    flags = []
    if not b:
        return ("?", "Other", ["no bed"])
    m = re.match(r"^B?PICU(\d*)([A-Z]?)$", b)
    if m:
        return ("PICU%s%s" % (m.group(1), m.group(2)), "Paeds", ["paeds"])
    m = re.match(r"^B?NICU(\d*)([A-Z]?)$", b)
    if m:
        return ("NICU%s%s" % (m.group(1), m.group(2)), "Paeds", ["paeds"])
    m = re.match(r"^B?CCU(\d*)([A-Z]?)$", b)  # OVERLAY_7: CCU is a unit, grouped with CSU
    if m:
        return ("CCU%s%s" % (m.group(1), m.group(2)), "ICU#D", [])
    m = re.match(r"^B?CSU(\d+)([A-Z]?)$", b)
    if m:
        return ("CSU%s%s" % (m.group(1), m.group(2)), "ICU#D", [])
    m = re.match(r"^B?ICU(\d+)([BD]?)$", b)
    if m:
        wing = m.group(2) or "B"
        return ("ICU%s%s" % (m.group(1), wing), "ICU#D" if wing == "D" else "ICU#B", [])
    m = re.match(r"^B?(SCT|BMT)(\d*)([A-Z]?)$", b)
    if m:
        return ("SCT%s%s" % (m.group(2), m.group(3)), "2nd floor", [])
    m = re.match(r"^B?ER\s*(\w*)$", b)
    if m:
        return ("ER %s" % m.group(1) if m.group(1) else "ER", "ER IN", [])
    m = re.match(r"^B?(\d)(\d{2})([A-Z]?)$", b)
    if m:
        fl = m.group(1)
        grp = {"7": "7th floor", "4": "4th floor", "3": "3rd floor", "2": "2nd floor"}.get(fl, "Other")
        return ("%s%s%s" % (fl, m.group(2), m.group(3)), grp, [] if grp != "Other" else ["unknown floor"])
    return (b, "Other", ["unparsed bed"])


def room_key(room):
    """Sort key: ascending room within group."""
    r = room or ""
    m = re.search(r"(\d+)", r)
    n = int(m.group(1)) if m else 9999
    if r.upper().startswith("SCT"):
        n += 5000  # SCT/BMT last within the 2nd floor
    return (n, r)


def norm_name(name):
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Za-z ]+", " ", s).lower()
    toks = sorted(t for t in s.split() if len(t) > 1)
    return " ".join(toks)


STOP_TOKENS = {"el", "al", "abou", "bou", "abu", "abi", "bin", "ibn", "de", "mr", "mrs", "dr"}


def name_tokens(name):
    return set(norm_name(name).split())


# OVERLAY_6 4o (07.10.2026): one key for Arabic transliteration variants of a name token
# (Raniya/Rania, Haddadi/Haddady, Yusuf/Yousuf).
def translit_key(t):
    t = (t or "").lower()
    if len(t) > 3:
        t = re.sub(r"(iyeh|iyah|ieh|iya|yah|ya|ia|eh|ah|ee|y|i|e)$", "a", t)
    for a, b in (("ou", "u"), ("oo", "u"), ("ee", "i"), ("ei", "i"), ("ey", "i"), ("ie", "i"), ("y", "i"),
                 ("q", "k"), ("ck", "k"), ("ph", "f")):
        t = t.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", t)


# OVERLAY_6 4a (07.10.2026): frequencies only, never a dose, anywhere.
_DRUGS = (r"lovenox|enoxaparin|clexane|heparin|lantus|insulin|novorapid|methylpred\w*|solu-?medrol|hydrocortisone|"
          r"dexa\w*|prednis\w*|pred|lasix|furosemide|tava\w*|levo\w*|mero\w*|vanco\w*|fluco\w*|teico\w*|cefaz\w*|"
          r"ceftri\w*|cefe\w*|piptazo|tazocin|pip|erta\w*|fosfo\w*|amik\w*|colist\w*|acyclo\w*|valacyclo\w*|vori\w*|"
          r"caspo\w*|mica\w*|metro\w*|cipro\w*|augmentin|bactrim|doxy\w*|azithro\w*|clinda\w*|linezolid|dapto\w*|"
          r"genta\w*|zavi\w*|terbin\w*|apixaban|eliquis|rivaroxaban|xarelto|keppra|levetiracetam")
DOSE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:mg|g|gr|mcg|\u00b5g|ug|IU|MU|units?|mL/kg|mg/kg)\b(?!/dL)"
    r"|\b\d{3,4}\s?(?:x1|once|OD|BID|TID|q\d+h)\b|\bloading dose of\s*\d|\(\s*\d{3,4}\b(?![,.]\d)"
    r"|\b\d{3,4}\s+(?:proph|from|then|load|daily|once)\b|\bthen \d{2,4}\b(?!\s*(?:col|/))"
    r"|\b(?:" + _DRUGS + r")\s+\d{1,4}(?:[.,]\d+)?(?:\s?(?:mg|g|mcg|ug|units?|IU|MU)\b)?(?![\w.,])(?!\s*(?:/|%|h\b|hours?|days?|d\b|wks?\b|weeks?|w\b|months?|mo\b|times|doses|col|x10|mmol|cells))", re.I)
_LAB_CTX = re.compile(r"\b(Hb|Hgb|CRP|PCT|Cr|WBC|Plt|lactate|glucose|protein|bili|Na|K|EF|HGT|ANC|col/ml|CrCl|trough|level)\b", re.I)


def find_doses(text):
    """Dose mentions in text, lab values excluded (a lab name in the 45 chars before the hit)."""
    out = []
    for m in DOSE_RE.finditer(text or ""):
        if _LAB_CTX.search(text[max(0, m.start() - 45):m.start() + 1]):
            continue
        out.append(m.group(0))
    return out


def strip_doses(text):
    """Remove dose figures, keep the drug, route, frequency and dates. Line structure kept."""
    def one(line):
        if not find_doses(line):
            return line
        s = line
        for d in find_doses(line):
            m = re.match(r"^((?:" + _DRUGS + r")\s+)(.*)$", d, re.I)
            w = re.match(r"^\d+\s+(\w+)$", d) or re.match(r"^(then|\() ?\d+$", d)
            s = s.replace(d, m.group(1).rstrip() if m else (w.group(1) if w else ""), 1)
        s = re.sub(r"\(\s*\)", "", s)
        s = re.sub(r"\(\s+", "(", s)
        lead = re.match(r"^\s*", s).group(0)
        return lead + re.sub(r" {2,}", " ", s[len(lead):]).rstrip()
    return "\n".join(one(l) for l in (text or "").split("\n"))


def name_sim(a, b):
    """Fuzzy Jaccard on name tokens: tokens match when equal, or when one is a prefix of the other (>=4 chars),
    or when difflib ratio >= 0.8 (transliteration variants). Particles like el/al/abou are ignored."""
    import difflib
    A = [t for t in name_tokens(a) if t not in STOP_TOKENS] or list(name_tokens(a))
    B = [t for t in name_tokens(b) if t not in STOP_TOKENS] or list(name_tokens(b))
    if not A or not B:
        return 0.0
    used = set(); hits = 0
    for x in A:
        for j, y in enumerate(B):
            if j in used:
                continue
            if x == y or (len(x) >= 4 and len(y) >= 4 and (x.startswith(y) or y.startswith(x))) or difflib.SequenceMatcher(None, x, y).ratio() >= 0.8 \
                    or (len(x) >= 4 and len(y) >= 4 and translit_key(x) == translit_key(y)):  # OVERLAY_6 4o
                used.add(j); hits += 1; break
    return hits / (len(A) + len(B) - hits)


def parse_date(s):
    """dd/mm/yyyy, dd.mm.yyyy, yyyy-mm-dd, dd/mm -> ISO date or None."""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    return None


def ddmm(iso):
    if not iso:
        return "?"
    return "%s/%s" % (iso[8:10], iso[5:7])


def iso_from_ddmm(ddmm_s, year):
    m = re.match(r"^~?(\d{1,2})/(\d{1,2})$", ddmm_s.strip())
    if not m:
        return None
    try:
        return dt.date(year, int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def jdump(obj, p):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


# ---- Vitals rules (Chris, 14.09.2026) ----
# vitals[0] is the STATUS line, always present, three parts separated by " | ":
#   <fever: afebrile since dd/mm | Tmax 38.4 dd/mm>  |  <HD: no pressors | off pressors since dd/mm | norad 0.1 since dd/mm>
#   |  <resp: RA | 2 L NC | HFNC 60/50% | BIPAP | intubated PRVC FiO2 40% PEEP 8 since dd/mm>
# Every other vitals line is imaging or a PIVOTAL lab (one that made the diagnosis); routine
# labs are not on the handout. A line starting with "!" is pivotal by declaration and always kept.
STATUS_FEVER = re.compile(r"afebrile|febrile|fever|tmax|\bT\s*\d", re.I)
STATUS_HD = re.compile(r"pressor|norad|noradren|levo|vasopressin|dobut|adren|\bMAP\b|hypotens|shock|\bBP\b|haemodynamically|hemodynamically", re.I)
STATUS_RESP = re.compile(r"\bRA\b|room air|\bNC\b|nasal|O2|oxygen|HFNC|high flow|BIPAP|CPAP|NIV|intubat|ventilat|PRVC|\bPS\b|FiO2|PEEP|SpO2|extubat|trach", re.I)
ROUTINE_LAB = re.compile(r"\b(CrCl|Cr|Na|K|Mg|Hb|Hct|Plt|WBC|ANC|INR|PTT|LFT|ALP|GGT|AST|ALT|bili\w*|trop\w*|CKMB|D-dimer|CRP|PCT|procal\w*|lactate|HCO3|bicarb|glucose|albumin|urea|BUN)\b", re.I)
IMAGING = re.compile(r"\b(CT|CTA|MRI|MRCP|CXR|US|ultrasound|echo|TTE|TEE|PET|doppler|duplex|EEG|EMG|bronch\w*|endoscop\w*|colonoscop\w*|scan|film|x-?ray)\b", re.I)


def status_line_ok(v):
    """True when a status line names fever state, haemodynamics and respiratory support."""
    return bool(STATUS_FEVER.search(v) and STATUS_HD.search(v) and STATUS_RESP.search(v))


def handout_vitals(vitals):
    """vitals[0] as the status line, then imaging and pivotal labs only (rule above)."""
    if not vitals:
        return None, []
    rest = []
    for v in vitals[1:]:
        if v.startswith("!"):
            rest.append(v[1:].strip())
        elif IMAGING.search(v) and not (ROUTINE_LAB.search(v) and not IMAGING.search(v)):
            rest.append(v)
        elif not ROUTINE_LAB.search(v):
            rest.append(v)
    return vitals[0], rest
