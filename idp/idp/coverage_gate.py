#!/usr/bin/env python3
"""Zero-loss coverage gate (review item 11, Chris 28.11.2026).

  coverage_gate.py <synth.py> <census.json> <outdir> --date YYYY-MM-DD
                   [--day-updates out/day_updates.txt] [--service-list in/service_list.json]
                   [--cultures out/cultures.json] [--days 1] [--warn-only]
  (also: idp10.py coverage ...)

Every dated source item for a census patient must be reflected in a rendered field of that patient's synth entry
(one_liner, updates, issues and drug lines, micro, micro_recap, vitals, pendings, id_plan, conflicts, not_applied,
im_detail, steroids, devices, logs, WA lines) or carry a waiver:
  - each dated fragment (text from a dd/mm date to the next date) dated today or in the last --days days in the
    ward-doc lines of out/day_updates.txt (today and the --days days before) and in the patient's app write-up (service list `handoff`);
  - each final culture row of a census patient in out/cultures.json (screens and negatives included).
Matching is tolerant: a fragment is covered when one rendered item carries its date (any dd/mm form) and one of its
key nouns (specimen, organism, drug, imaging, procedure, event; abbreviations folded: blood=BCx, urine=UCx ...), or
when one item carries half or more of its key nouns. A fragment without any key noun is not clinical and is skipped.
A culture row is covered when an item carries its collection (or final) date and its organism genus, or for a row
without an organism its specimen or "neg"/"no growth".
Waivers: synth.py WAIVED = {pid: [{"item": <text of the source item, or a distinctive part>, "reason": <why>}]}.

Writes outdir/coverage_gate.txt (one MISS line per item, then the summary) and outdir/coverage_gate.json.
Prints "COVERAGE OK: n checked, c covered, w waived, 0 missed", or "COVERAGE FAIL: m missed (...)" (exit 1),
or with --warn-only "COVERAGE WARN: m missed (...)" (exit 0).
"""
import argparse, datetime as dt, importlib.util, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATE = re.compile(r"(?<![\d/.])(\d{1,2})[/.](\d{1,2})(?:[/.](?:\d{4}|\d{2}))?(?![\d])|(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)")
# key nouns -> canonical token (several spellings fold to one)
ALIASES = {
    "blood": "bcx", "bcx": "bcx", "bc": "bcx", "hemoculture": "bcx", "bacteremia": "bcx", "bacteraemia": "bcx",
    "urine": "ucx", "ucx": "ucx", "uc": "ucx", "urinary": "ucx",
    "sputum": "sputum", "spx": "sputum", "bal": "bal", "eta": "eta", "tracheal": "eta", "aspirate": "eta",
    "csf": "csf", "lp": "csf", "wound": "wound", "swab": "swab", "tip": "tip", "catheter": "line", "line": "line",
    "picc": "line", "cvc": "line", "stool": "stool", "diff": "cdiff", "cdiff": "cdiff", "difficile": "cdiff",
    "tissue": "tissue", "pus": "pus", "abscess": "abscess", "fluid": "fluid", "pleural": "pleural", "ascitic": "ascites",
    "ascites": "ascites", "screen": "screen", "rectal": "screen", "nasal": "screen", "mdro": "screen", "cre": "screen",
    "biofire": "biofire", "pcr": "pcr", "culture": "cx", "cultures": "cx", "cx": "cx", "gram": "gram", "gnb": "gnb",
    "gpc": "gpc", "gnr": "gnb", "yeast": "yeast", "growth": "growth", "neg": "neg", "negative": "neg", "sterile": "neg",
    "ct": "ct", "cta": "ct", "mri": "mri", "cxr": "cxr", "xray": "cxr", "echo": "echo", "tte": "echo", "tee": "echo",
    "us": "us", "ultrasound": "us", "doppler": "us", "pet": "pet", "scan": "scan",
    "surgery": "or", "debridement": "or", "drain": "drain", "drainage": "drain", "bronch": "bronch",
    "bronchoscopy": "bronch", "biopsy": "biopsy", "ercp": "ercp", "intubated": "intub", "intubation": "intub",
    "extubated": "extub", "dialysis": "hd", "hd": "hd", "crrt": "hd", "transfer": "transfer", "transferred": "transfer",
    "icu": "icu", "discharge": "dc", "discharged": "dc", "dc": "dc", "fever": "fever", "febrile": "fever",
    "spiked": "fever", "afebrile": "afebrile", "pressors": "pressors", "levophed": "pressors", "norepinephrine": "pressors",
}
# lab values and lab orders are not key nouns: "CBC CHEM9 procal CRP 28/11" is a to-do, not a clinical event
NEGATED = re.compile(r"\b(?:no need (?:for|of)|monitor(?:ing)?|not for|no indication for|refused|declined|cancel(?:l?ed)?)\s+(?:a |an |the |further )?[a-z]+(?:\s+[a-z]+)?", re.I)
ORGANISMS = ("klebsiella", "coli", "pseudomonas", "acinetobacter", "enterobacter", "serratia", "proteus", "citrobacter",
             "morganella", "stenotrophomonas", "staph", "staphylococcus", "aureus", "mrsa", "mssa", "epidermidis", "cons",
             "enterococcus", "faecalis", "faecium", "vre", "strep", "streptococcus", "pneumoniae", "candida", "albicans",
             "auris", "glabrata", "tropicalis", "aspergillus", "cmv", "ebv", "hsv", "influenza", "covid", "rsv",
             "salmonella", "shigella", "campylobacter", "listeria", "nocardia", "mycobacterium", "tb", "clostridium",
             "clostridioides", "bacteroides", "haemophilus", "moraxella", "providencia", "burkholderia", "esbl", "cre",
             "kpc", "ndm", "oxa")
DRUGS = ("mero", "piptazo", "pip", "tazo", "erta", "zavi", "avibac", "zerb", "cefe", "cefep", "ceftriax", "ceftri",
         "rocephin", "aztreo", "amik", "tige", "vanco", "teico", "tavanic", "levo", "cipro", "azithro", "flagyl", "metro",
         "bactrim", "augmentin", "amox", "fluco", "vori", "caspo", "ecalta", "anidul", "ampho", "valganci", "ganci",
         "fidaxo", "colistin", "colis", "linez", "dapto", "fosfo", "clinda", "doxy", "genta", "cefaz", "cefur", "acyclo",
         "oselt", "tamiflu", "posa", "isavu", "mica", "imipen", "ertapen", "merop")
ORG_ABBR = {"mssa": "staphylococcus aureus", "mrsa": "staphylococcus aureus", "cons": "coagulase negative staphylococcus",
            "vre": "enterococcus faecium", "gbs": "streptococcus agalactiae", "pseudo": "pseudomonas aeruginosa",
            "kleb": "klebsiella pneumoniae", "acineto": "acinetobacter baumannii", "steno": "stenotrophomonas maltophilia"}
ORG_GENERIC = {"spp", "species", "complex", "group", "growth", "mixed", "flora", "normal", "isolated", "esbl", "with", "from"}


def org_hit(orgw, item, need_all=False):
    """Organism words (genus, species) in a rendered item; prefixes of 5 letters count ('K. pneumo', 'Pseudo')."""
    low = (item or "").lower().replace("e. coli", "ecoli coli")
    for ab, full in ORG_ABBR.items():
        low = re.sub(r"\b%s\b" % ab, " %s %s " % (ab, full), low)
    words = re.findall(r"[a-z]{4,}", low)
    hit = lambda o: any(w == o or (len(o) >= 5 and len(w) >= 5 and (w.startswith(o[:5]) or o.startswith(w[:5]))) for w in words)
    return all(hit(o) for o in orgw) if need_all else any(hit(o) for o in orgw)


RENDER_FIELDS = ("one_liner", "updates", "updates_nonid", "issues", "abx_other", "micro", "micro_recap", "vitals",
                 "pendings", "id_plan", "conflicts", "not_applied", "im_detail", "steroids", "devices", "log_id", "log_im")


def ddmm(d, m):
    return "%02d/%02d" % (int(d), int(m))


def dates_in(text):
    out = []
    for m in DATE.finditer(text or ""):
        if m.group(1):
            d, mo = int(m.group(1)), int(m.group(2))
        else:
            d, mo = int(m.group(5)), int(m.group(4))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            out.append((m.start(), m.end(), ddmm(d, mo)))
    return out


def keys_in(text):
    """Canonical key nouns of a text: specimens, tests, imaging, procedures, events, organisms, drug stems."""
    low = NEGATED.sub(" ", (text or "")).lower().replace("c. diff", "cdiff").replace("c.diff", "cdiff").replace("e. coli", "coli") \
        .replace("e.coli", "coli").replace("x-ray", "xray")
    words = re.findall(r"[a-z]+", low)
    out = {"or"} if re.search(r"\bOR\b", text or "") else set()   # the operating room in capitals, never the word "or"
    for w in words:
        if w in ALIASES:
            out.add(ALIASES[w])
        if w in ORGANISMS:
            out.add("org:" + w)
        for dstem in DRUGS:
            if w.startswith(dstem) and len(w) >= 3:
                out.add("drug:" + dstem[:4])
                break
    return out


def flatten(v):
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for k, x in v.items() for s in ([str(k)] + flatten(x))]
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in flatten(x)]
    return []


def entry_items(e, wa=None):
    items = []
    for f in RENDER_FIELDS:
        if f in e:
            items += [s for s in flatten(e[f]) if s and s.strip()]
    items += [s for s in flatten(wa or []) if s.strip()]
    return [(s, {x[2] for x in dates_in(s)}, keys_in(s)) for s in items]


def near(d, year=2026):
    """dd/mm and the day either side (an overnight event is written under either date)."""
    try:
        x = dt.date(year, int(d[3:5]), int(d[:2]))
    except ValueError:
        return {d}
    return {ddmm(y.day, y.month) for y in (x - dt.timedelta(days=1), x, x + dt.timedelta(days=1))}


def covered(date, keys, items):
    """date: canonical dd/mm or None; keys: canonical key set of the source item."""
    if not keys:
        return True
    win = near(date) if date else set()
    for s, ds, ks in items:
        if win & ds and keys & ks:
            return True
        hit = keys & ks
        if len(hit) >= 2 and len(hit) * 2 >= len(keys):
            return True
    return False


def fragments(text, recent):
    """(date, fragment) for every date in `recent` written in text: from the date to the next date (max 220 chars)."""
    ds = dates_in(text)
    out = []
    for i, (s, e, d) in enumerate(ds):
        if d not in recent:
            continue
        end = ds[i + 1][0] if i + 1 < len(ds) else len(text)
        frag = text[max(0, s - 60):s].split("\n")[-1][-60:] + text[s:min(end, s + 220)]
        out.append((d, re.sub(r"\s+", " ", frag).strip()))
    return out


def day_update_blocks(path):
    """out/day_updates.txt -> {pid: text of the ward-doc lines}."""
    out, cur = {}, None
    if not path or not os.path.exists(path):
        return out
    for ln in open(path, encoding="utf-8", errors="ignore"):
        if ln.startswith("=== "):
            m = re.match(r"=== (?:OFFLIST )?(\S+)", ln)
            cur = m.group(1) if m and "OFFLIST" not in ln else None
            continue
        if cur and not ln.startswith("--- ward doc"):
            out[cur] = out.get(cur, "") + ln
    return out


def tok_overlap(a, b):
    A = set(re.findall(r"[a-z0-9]{3,}", (a or "").lower()))
    B = set(re.findall(r"[a-z0-9]{3,}", (b or "").lower()))
    return len(A & B) / max(1, min(len(A), len(B)))


def waived(pid, text, waivers):
    for w in waivers.get(pid, []) or []:
        if not isinstance(w, dict) or not (w.get("reason") or "").strip():
            continue
        it = (w.get("item") or "").strip().lower()
        if it and (it in text.lower() or text.lower() in it or tok_overlap(it, text) >= 0.6):
            return w["reason"]
    return None


def load_synth(path):
    spec = importlib.util.spec_from_file_location("synth_cov", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def same_person(a, b):
    try:
        from common import name_sim
        return name_sim(a or "", b or "") >= 0.67
    except Exception:
        return (a or "").strip().lower() == (b or "").strip().lower()


def run(a):
    m = load_synth(a.synth)
    S, WA, WV = getattr(m, "SYNTH", {}) or {}, getattr(m, "WA", {}) or {}, getattr(m, "WAIVED", {}) or {}
    census = json.load(open(a.census, encoding="utf-8"))
    pats = census.get("patients") or []
    t0 = dt.date.fromisoformat(a.date)
    recent = {ddmm((t0 - dt.timedelta(days=i)).day, (t0 - dt.timedelta(days=i)).month) for i in range(0, a.days + 1)}
    rows, n = [], {"checked": 0, "covered": 0, "waived": 0, "missed": 0}
    kinds = {}

    def check(pid, kind, src, date, keys, text):
        if not keys:
            return
        n["checked"] += 1
        items = ITEMS.get(pid) or []
        if covered(date, keys, items):
            n["covered"] += 1; return
        why = waived(pid, text, WV)
        if why:
            n["waived"] += 1; rows.append({"pid": pid, "kind": kind, "src": src, "text": text, "waived": why}); return
        n["missed"] += 1; kinds[kind] = kinds.get(kind, 0) + 1
        rows.append({"pid": pid, "kind": kind, "src": src, "text": text, "date": date, "keys": sorted(keys)})

    ITEMS = {p["pid"]: entry_items(S.get(p["pid"]) or {}, WA.get(p["pid"])) for p in pats}
    # 1. ward-doc day updates
    for pid, txt in day_update_blocks(a.day_updates).items():
        if pid not in ITEMS:
            continue
        for d, frag in fragments(txt, recent):
            check(pid, "handoff sentence", "ward doc", d, keys_in(frag), frag)
    # 2. app write-ups (service list)
    if a.service_list and os.path.exists(a.service_list):
        sv = json.load(open(a.service_list, encoding="utf-8"))
        for q in sv.get("patients") or []:
            pid = q.get("pid") if q.get("pid") in ITEMS else next(
                (p["pid"] for p in pats if same_person(p.get("name"), q.get("name"))), None)
            if not pid:
                continue
            for d, frag in fragments(q.get("handoff") or "", recent):
                check(pid, "app write-up sentence", "service list", d, keys_in(frag), frag)
    # 3. final culture rows of the current admission (positives always; a row without an organism when it was
    # collected or finalised in the last 3 days). The archive and the digest can both carry one specimen: one check.
    if a.cultures and os.path.exists(a.cultures):
        cx = json.load(open(a.cultures, encoding="utf-8"))
        seen = set()
        for sp in cx.get("specimens") or []:
            if not sp.get("final"):
                continue
            pid = next((p["pid"] for p in pats if (sp.get("mrn") and str(p.get("mrn")) == str(sp["mrn"]))
                        or same_person(p.get("name"), sp.get("patient"))), None)
            if not pid:
                continue
            col = sp.get("collected") or ""
            fd = sp.get("final_date") or sp.get("updated") or ""
            adm = next((p.get("as_admission") for p in pats if p["pid"] == pid), None) or ""
            if re.match(r"\d{4}-\d\d-\d\d", adm) and re.match(r"\d{4}-\d\d-\d\d", col):
                if col < (dt.date.fromisoformat(adm) - dt.timedelta(days=3)).isoformat():
                    continue          # an earlier admission: carried by the BM rule, not checked here
            elif re.match(r"\d{4}-\d\d-\d\d", col) and col < (t0 - dt.timedelta(days=45)).isoformat():
                continue
            orgw = set()
            for o in sp.get("organisms") or []:
                orgw |= {w for w in re.findall(r"[a-z]{4,}", o.lower()) if w not in ORG_GENERIC}
            if not orgw:
                last = max(col, fd)
                if not last or last < (t0 - dt.timedelta(days=3)).isoformat():
                    continue
            spec = keys_in(sp.get("specimen_short") or "") | keys_in(sp.get("specimen") or "")
            k = (pid, col, tuple(sorted(spec)), tuple(sorted(orgw)))
            if k in seen:
                continue
            seen.add(k)
            dates = set()
            if re.match(r"\d{4}-\d\d-\d\d", col):
                dates |= near(ddmm(col[8:10], col[5:7]))
            if re.match(r"\d{4}-\d\d-\d\d", fd):
                dates.add(ddmm(fd[8:10], fd[5:7]))
            text = "%s %s %s: %s" % (col, sp.get("specimen") or "", sp.get("sid") or "", ", ".join(sp.get("organisms") or []) or (sp.get("result") or "")[:80])
            n["checked"] += 1
            items = ITEMS.get(pid) or []
            if orgw:
                ok = any(ds & dates and org_hit(orgw, s) for s, ds, ks in items) or any(
                    len(orgw) >= 2 and org_hit(orgw, s, need_all=True) and spec & ks for s, ds, ks in items)
            else:
                ok = any(ds & dates and ks & (spec | {"neg", "growth"}) for s, ds, ks in items)
            if ok:
                n["covered"] += 1; continue
            need = sorted(orgw) if orgw else sorted(spec | {"neg", "growth"})
            why = waived(pid, text, WV)
            if why:
                n["waived"] += 1; rows.append({"pid": pid, "kind": "final culture", "src": sp.get("source"), "text": text, "waived": why})
                continue
            n["missed"] += 1; kinds["final culture"] = kinds.get("final culture", 0) + 1
            rows.append({"pid": pid, "kind": "final culture", "src": sp.get("source"), "text": text, "date": sorted(dates), "keys": need})
    detail = ", ".join("%s %d" % kv for kv in sorted(kinds.items())) or "none"
    if n["missed"] == 0:
        summary = "COVERAGE OK: %d checked, %d covered, %d waived, 0 missed" % (n["checked"], n["covered"], n["waived"])
        rc = 0
    elif a.warn_only:
        summary = "COVERAGE WARN: %d missed (%s); %d checked, %d covered, %d waived (warn-only: not blocking)" % (
            n["missed"], detail, n["checked"], n["covered"], n["waived"])
        rc = 0
    else:
        summary = "COVERAGE FAIL: %d missed (%s); %d checked, %d covered, %d waived" % (
            n["missed"], detail, n["checked"], n["covered"], n["waived"])
        rc = 1
    os.makedirs(a.outdir, exist_ok=True)
    L = []
    for r in rows:
        if r.get("waived"):
            L.append("WAIVED %s %s (%s): %s [reason: %s]" % (r["pid"], r["kind"], r["src"], r["text"], r["waived"]))
        else:
            L.append("MISS %s %s (%s): %s [needs date %s and one of %s, or a WAIVED entry]" % (
                r["pid"], r["kind"], r["src"], r["text"], r.get("date"), ", ".join(r.get("keys") or [])))
    L.append(summary)
    open(os.path.join(a.outdir, "coverage_gate.txt"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({"date": a.date, "counts": n, "by_kind": kinds, "rows": rows},
              open(os.path.join(a.outdir, "coverage_gate.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(summary)
    return rc


def add_args(p):
    p.add_argument("synth"); p.add_argument("census"); p.add_argument("outdir")
    p.add_argument("--date", required=True); p.add_argument("--day-updates"); p.add_argument("--service-list")
    p.add_argument("--cultures"); p.add_argument("--days", type=int, default=1); p.add_argument("--warn-only", action="store_true")


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
