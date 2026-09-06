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
            if x == y or (len(x) >= 4 and len(y) >= 4 and (x.startswith(y) or y.startswith(x))) or difflib.SequenceMatcher(None, x, y).ratio() >= 0.8:
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
