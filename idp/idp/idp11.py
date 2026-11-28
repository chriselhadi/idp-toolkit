#!/usr/bin/env python3
"""idp11 (Phase 2, 28.10.2026): the IDP Feed sheet, the check of Gemini's Register, the Verification exchange.

The morning run keeps patient facts in the Google Sheet "IDP Feed" (written here, changed rows only); Gemini turns them
into AMS-format blocks in the register's "Register" tab; each checks the other through the register's "Verification" tab.
A patient leaves the run's state only when Gemini's block for that admission is FINAL in "Index".

Commands (every input that is a sheet read is the raw get_values JSON saved from the spill or the transcript):
  feed      <state_new> <census> <ams_blocks|MISSING> <cultures|MISSING> <nowdir> <outdir> --date D
              nowdir holds patients.json antimicrobials.json micro.json changes.json (the Feed tabs as they are now;
              a missing file = empty tab). Writes outdir/feed_desired.json and outdir/ops.json; prints FEED OPS.
  op        <ops.json> <n>          print op n as {"range":..., "values":...} for update_values (n from 1)
  feedcheck <outdir>/feed_desired.json <nowdir> --date D    after the writes: FEED MATCH, then the Meta op
  final     <state_new> <index.json> <cultures|MISSING> --date D
              a departed record whose admission Key is FINAL = Y in Index leaves the state (culture watch starts)
  checkreg  <register_tab.json> <outdir>/feed_desired.json <verification.json> <cultures|MISSING> <outdir> --date D
              Claude's check of Gemini's Discharged blocks: C- rows (findings, or one "verified" row) -> outdir/vrows_ops.json
  vqueue    <verification.json> --date D     Gemini's open findings on Claude's data, and what goes to Chris
  vwrite    <verification.json> <replies.json> <outdir>    replies -> outdir/vreply_ops.json
  regjoin2  <out.json> <raw tab json>...     Register + History + Admissions -> one register.json for idp10 base/readmit
  backfill  <state_new> <index.json> <identifiers dir> --date D [--queue]
              admissions in the state or in the IDP_Data identifiers tables with no register block: count and date
              range; with --queue they go into state["backfill"] and enter the feed as Discharged, at most --backlog a day
  schema    --date D                 the Schema and Meta ops for IDP Feed and the Schema op for the register
  review    <review.json> <outdir> --date D     open Gemini Review rows (no Claude reply) -> outdir/review_open.txt
  reviewreply <review_replies.json> <review.json> <outdir> --date D
              {row_number: {reply, reason}} -> outdir/review_ops.json: update_values on H..K only (Claude reply, Claude
              reason, Resolved, Escalated); Gemini's columns A..G are never written

28.11.2026 (Chris): feed also appends today's rows of <outdir>/../evolution.json (or --evolution) to the "Evolution"
tab (nowdir/evolution.json = the tab now) and creates "Gemini Review" with its header only when nowdir/review.json is
absent or empty. Schema version 6.

29.10.2026 (Chris): every admission must have a register block from its first day on the service. The feed gives
Gemini each pid on its first morning (Status Active); checkreg checks coverage (every Feed pid has exactly one Index
Key) and writes "missing block" rows to Verification; Feed Patients carries "AMS block" (sheet!first row of a hand-made
AMS workbook block for the same admission) so Gemini reconciles rather than duplicates. Schema version 2.
"""
import sys, os, re, json, argparse, datetime as dt, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("idp10", os.path.join(HERE, "idp10.py"))
I = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(I)
clean, ddmm, jload, sheet_safe = I.clean, I.ddmm, I.jload, I.sheet_safe

AMS33 = I.REG_HEADER[2:]
TABS = {
    "Feed Patients": (["pid", "MRN", "Name", "Status", "Room", "Fellow", "UC", "First seen", "Last seen", "Age",
                       "Date of Admission", "CrCl", "Weight", "One-liner", "ID issues", "ID plan", "Status line", "Imaging",
                       "Micro recap", "Pendings", "Conflicts", "AMS block", "IM", "Steroids", "Lines", "Not applied",
                       "Updates today", "Updated"], 1, "patients"),
    "Feed Antimicrobials": (["pid", "Drug", "Line", "Issue", "Start", "End", "Running", "Updated"], 2, "antimicrobials"),
    "Feed Micro": (["pid", "Collected", "Specimen", "Result", "Status", "Late", "Updated"], 3, "micro"),
    # Chris 03.11.2026: every lab specimen of the stay straight from Daily Cultures, finalised AND latest-not-finalised,
    # never dropped; the Status label tells them apart ("Final dd/mm/yy" | "Not final, latest dd/mm/yy")
    # schema 4 (Chris 19.11.2026): structured columns so the app never splits free text; the raw bench text moves to Notes
    "Feed Cultures": (["pid", "Collected", "Specimen", "SID", "Summary", "Organisms", "S", "R", "Pattern", "Status", "Source", "Notes",
                       "Updated"], 4, "labcx"),
    # schema 4: Daily Report findings (bench preliminary line) while no culture row with that bench number exists yet
    "Feed Daily Report": (["pid", "Date", "Bench no.", "Specimen", "Preliminary result", "Updated"], 3, "dailyreport"),
}
CHANGES = ["Date", "pid", "Tab", "Key", "Field", "Old", "New"]
VER = ["Row ID", "Date found", "Found by", "Tab", "Key or pid", "Column", "Value checked", "Value in source", "Source",
       "Severity", "Reply by", "Reply", "Reply note", "State"]
# schema 6 (Chris 28.11.2026): notes evolve, never rewritten. "Evolution" = every change to yesterday's synthesis with its
# source (append only, from out/evolution.json); "Gemini Review" = Gemini's daily assessment (A..G, Gemini's) answered by the
# run the next morning (H..K, the run's). The feed step only creates the Gemini Review header when the tab is absent.
EVOLUTION = ["pid", "Date", "Field", "Kind", "Old", "New", "Source", "Updated"]
REVIEW = ["Date", "pid", "Patient", "Field", "View", "Statement", "Evidence", "Claude reply", "Claude reason", "Resolved",
          "Escalated"]
REVIEW_GEMINI = 7          # columns A..G are Gemini's; the run writes only H..K
REVIEW_VIEWS = ("agree", "disagree", "missing", "suggestion")
REVIEW_REPLIES = ("accepted", "rejected", "partly")
SCHEMA_VERSION = "6"        # bump whenever any header of IDP Feed or of the register changes; never rename a header without it
META_NOTE = ("Open a register block for a pid on its FIRST morning in Feed Patients (Status Active), not at discharge. "
             "AMS block = sheet!first row of a hand-made block in the AMS workbook for the same admission: reconcile into "
             "that admission, never a second block. Age, admission date, CrCl and weight come from the live AMS workbook block; read that block there for the "
             "other AMS columns. Status: Active | Off service dd/mm/yy (off the ID list, still seen by a source) | Discharged dd/mm/yy (no source shows the patient: "
             "finalise the block) | Watch dd/mm/yy (block final, late cultures still arriving). Late = Y: result final "
             "after discharge. A pid whose rows are cleared has left the feed. Gemini Review: write your daily assessment in "
             "Date..Evidence; the run answers in Claude reply..Escalated the next morning.")
COLS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"




def I_current_doa(one_liner, first_seen):
    """This admission's DOA from the one-liner when the AS list and the AMS block have none (02.11.2026)."""
    from common import current_doa
    d = current_doa(one_liner or "", first_seen)
    return (d + "/" + first_seen[2:4]) if d and first_seen else ""

def col(n):
    return COLS[n - 1] if n <= 26 else COLS[(n - 1) // 26 - 1] + COLS[(n - 1) % 26]


def raw_values(p):
    o = jload(p)
    if not o:
        return []
    if isinstance(o, dict):
        o = o.get("values", [])
    # A cell written with a leading apostrophe (cell(): MRNs, dd/mm) may read back with it or without it, depending on
    # how the write was taken; strip it on every read so the comparisons and feedcheck see the same text either way.
    return [[bare("" if c is None else str(c)) for c in r] for r in o]


def key_of(r, n):
    return tuple(x[1:] if x.startswith("'") else x for x in r[:n])


NUMLIKE = re.compile(r"^[\s\d.,/:%+\-<>()~]*\d[\s\d.,/:%+\-<>()~]*$")


def cell(v):
    """Text for a sheet cell. A leading apostrophe on anything Sheets would read as a number, date or formula
    (MRNs, dd/mm dates, values): the cell stays text exactly as written. Comparisons strip it again."""
    v = re.sub(r"\s*\n\s*", " ; ", v if isinstance(v, str) else ("" if v is None else str(v))).strip()
    v = sheet_safe(clean(v))[:4000]
    if v and not v.startswith("'") and (NUMLIKE.match(v) or v[:1] == "-"):
        v = "'" + v
    return v


def bare(v):
    return v[1:] if isinstance(v, str) and v.startswith("'") else v


def dmy(iso):
    try:
        return dt.date.fromisoformat(iso).strftime("%d/%m/%y")
    except Exception:
        return iso or ""


# ------------------------------------------------------------------ desired feed
def departed_status(rec, today):
    """Off service while any source still shows the patient in hospital; Discharged (dated the last day any source
    showed them) only once the archive note went out AND no source shows them today (Chris, 27.11.2026)."""
    sent = rec.get("archive_note_sent") or ""
    seen = rec.get("in_hospital_seen") or ""
    if sent and sent < today and seen < today:
        return "Discharged " + ddmm(max(rec.get("last_seen") or "", seen))
    return "Off service " + ddmm(rec.get("last_seen"))


def on_service_once(rec):
    return not (rec.get("archived_reason") or "").startswith(("ID consult in a handoff", "AS list standing therapy"))


def stay_specimens(cx, mrn, name, aliases, first, last):
    w = {"mrn": mrn or "", "name": name or "", "aliases": aliases or []}
    lo = (dt.date.fromisoformat(first or last) - dt.timedelta(days=5)).isoformat() if (first or last) else ""
    return [s for s in I.patient_specimens(cx, w) if lo <= (s.get("collected") or "") <= (last or "9999")]


def spec_row(pid, s, discharged):
    orgs = split_orgs(s)
    org = "; ".join(orgs)
    ast = " ".join(x for x in ("S: " + s["ast_s"] if s.get("ast_s") else "", "I: " + s["ast_i"] if s.get("ast_i") else "",
                               "R: " + s["ast_r"] if s.get("ast_r") else "") if x)
    res = " | ".join(x for x in (org, ast, s.get("result", "")) if x)
    late = "Y" if discharged and (s.get("final_date") or "") > discharged else "N"
    status = ("Final " + ddmm(s["final_date"])) if s.get("final") and s.get("final_date") else ("Final" if s.get("final") else "Preliminary")
    return [pid, ddmm(s.get("collected")), s.get("specimen", ""), res, status, late]


_NEG = re.compile(r"\b(no growth( so far)?|no organisms?( detected)?|negative|neg|all negative|no salmonella or shigella|no s\. aureus)\b", re.I)
_CDIFF = re.compile(r"C\.? ?diff\w*[^.;|]*", re.I)


def lab_summary(s, org):
    """One line in the card style: what grew (or the negative result) and the deciding AST, no bench shorthand."""
    txt = s.get("result", "") or ""
    cd = [m.group(0).strip() for m in _CDIFF.finditer(txt)]
    if org:
        out = org
        if s.get("ast_s"):
            out += " S " + s["ast_s"]
        if s.get("ast_r"):
            out += ", R " + s["ast_r"]
        return "; ".join([out] + [c for c in dict.fromkeys(cd) if c.lower() not in out.lower()])
    bits = list(cd)
    m = re.search(r"no growth( so far)?", txt, re.I) or _NEG.search(txt)
    if m and not bits:
        bits.append(m.group(0).lower())
    if not bits:
        bits.append(re.split(r"(?<=[a-z])\. ", txt)[0].strip()[:100])
    return "; ".join(dict.fromkeys(b for b in bits if b))

# Resistance pattern, by fixed rules from the lab's own S and R (Chris 20.11.2026). Never a guess: when the AST
# cannot be tied to one organism, or a drug is both S and R, the pattern says so instead.
_CARBA = {"erta", "mero", "imi"}
_CARBA_NF = {"mero", "imi"}
_3GC = {"ceftri", "ceftaz", "cefota"}
_FQ = {"cipro", "levo"}
_DTR = {"piptaz", "ceftaz", "cefep", "aztr", "mero", "imi", "cipro", "levo"}
_ECHINO = {"caspo", "mica", "anidula", "ecalta"}
_ENTERO = re.compile(r"\b(e\. ?coli|escherichia|klebsiella|k\. ?pneumo|enterobacter|citrobacter|serratia|proteus|morganella|m\. ?morganii|providencia|"
                     r"salmonella|shigella|hafnia|raoultella|pantoea|cronobacter|klebsiella|e\. ?cloacae)", re.I)


def _drugs(txt):
    out = set()
    for d in (txt or "").split(","):
        d = re.sub(r"\(.*?\)|\?", "", d).strip().lower()
        if d:
            out.add(d)
    return out


def _norm_org(o):
    return re.sub(r"\(.*?\)|\?", " ", o).replace(".", " ").lower().split()


def _org_in(org, text):
    """True when text names this organism (genus initial + species, or a single-word name)."""
    w, txt = _norm_org(org), " " + re.sub(r"[.,()?]", " ", text.lower()) + " "
    if not w:
        return False
    if len(w) == 1:
        return " %s " % w[0] in txt
    return (" %s " % w[1] in txt) and bool(re.search(r"\b%s" % re.escape(w[0][0]), txt))


def _ast_by_org(orgs, field):
    """{organism: drug set} when the AST field can be tied to each organism, else None."""
    if not field:
        return {o: set() for o in orgs}
    parts = [x.strip() for x in field.split(" | ")]
    if all(re.match(r"[^:]{2,60}: ", x) for x in parts):
        got = {}
        for x in parts:
            name, drugs = x.split(": ", 1)
            hits = [o for o in orgs if o not in got and _org_in(o, name)]
            if len(hits) != 1:
                return None
            got[hits[0]] = _drugs(drugs)
        return got
    return {orgs[0]: _drugs(field)} if len(orgs) == 1 else None


_BLOCK = re.compile(r"\bS: (.*?)(?:,\s*I: (.*?))?(?:,\s*R: (.*?))?(?:\.(?:\s|$)|$)")


def _ast_from_notes(orgs, txt):
    """Per-organism S and R from the bench blocks ('<organism>: S: ..., R: ...' between ' | ')."""
    got = {}
    for blk in (txt or "").split(" | ")[1:]:
        m = _BLOCK.search(blk) or re.search(r"\bR: ()()(.*?)(?:\.(?:\s|$)|$)", blk)
        if not m:
            continue
        hits = [o for o in orgs if _org_in(o, blk[:m.start()])]
        if len(hits) != 1 or hits[0] in got:
            continue
        got[hits[0]] = (_drugs(m.group(1)), _drugs(m.group(3)))
    return got


def _name_tags(org):
    tags = []
    for m in re.finditer(r"\b(ndm|kpc|oxa-?48|vim)\b", org, re.I):
        tags.append(m.group(1).upper().replace("OXA48", "OXA-48"))
    if re.search(r"\bampc\b", org, re.I):
        tags.append("AmpC")
    return tags


_INTRINSIC = [(re.compile(r"serratia|proteus|morganella|providencia", re.I), {"col", "tige", "nitro", "amp", "amoxi-clav", "amp-sulb", "cefox", "cefu",
                                                                                     "tetra"}),
              (re.compile(r"klebsiella|k\. ?pneumo", re.I), {"amp"}),
              (re.compile(r"enterobacter|citrobacter freundii|hafnia", re.I), {"amp", "amoxi-clav", "cefox", "cefu"}),
              (re.compile(r"pseudomonas|p\. ?aeru", re.I), {"amp", "amoxi-clav", "amp-sulb", "ceftri", "cefota", "cefox", "cefu", "erta",
                                                           "tige", "t/s", "tetra", "nal"}),
              (re.compile(r"enterococ|e\. ?faec", re.I), {"clinda", "t/s", "gent", "cefox", "oxa"})]


def org_pattern(org, s, r, final):
    """One organism's pattern from its own S and R drug sets."""
    o = org.lower()
    named = _name_tags(org)
    if s & r:
        return "AST conflicting, check"
    if not s and not r:
        if "(mrsa)" in o or ("aureus" in o and "(mr)" in o):
            return "MRSA"
        if "(mssa)" in o:
            return "MSSA"
        if "(esbl" in o:
            return ", ".join(["ESBL"] + named)
        if named:
            return ", ".join(named)
        return "no AST" if final else "AST pending"
    base = "ESBL" if "esbl" in o else ""
    tags = []
    if "candida" in o or "yeast" in o:
        if "fluco" in r:
            tags.append("fluconazole R")
        if r & _ECHINO:
            tags.append("echinocandin R")
        if "ampho" in r:
            tags.append("amphotericin R")
    elif "aureus" in o or "staph" in o or "cons" in o:
        mr = bool(r & {"oxa", "cefox"}) or "(mr" in o
        if "aureus" in o:
            tags.append("MRSA" if mr else "MSSA")
        elif mr:
            tags.append("methicillin R")
        if "vanco" in r:
            tags.append("vancomycin R")
    elif "enterococ" in o or "e faec" in " ".join(_norm_org(org)):
        if "vanco" in r:
            tags.append("VRE")
        if "amp" in r:
            tags.append("ampicillin R")
        if "gent-hl" in r:
            tags.append("HLAR")
    elif "pseudomonas" in o or "p. aeru" in o:
        tested = (s | r) & _DTR
        if len(tested) >= 6 and tested <= r:
            tags.append("DTR")
        elif r & _CARBA_NF:
            tags.append("carbapenem R")
        elif r & _FQ:
            tags.append("FQ R")
        if "cefta-avi" in r:
            tags.append("ceftazidime-avibactam R")
        if "ceftolo-taz" in r:
            tags.append("ceftolozane-tazobactam R")
    elif "acinetobacter" in o:
        tags.append("carbapenem R" if r & _CARBA_NF else "carbapenem S")
    elif "stenotrophomonas" in o:
        tags.append("T/S R" if "t/s" in r else "T/S S")
    elif _ENTERO.search(o):
        if r & _CARBA:
            tags.append("carbapenem R")
        elif base:
            tags.append(base)
        elif r & _3GC:
            tags.append("3rd-gen ceph R")
        if r & _FQ:
            tags.append("FQ R")
        if r & {"gent", "amik", "tobra"}:
            tags.append("aminoglycoside R")
        if "t/s" in r:
            tags.append("T/S R")
    tags = [x for x in dict.fromkeys(tags + [n for n in named if n not in tags]) if x]
    if not tags:
        extra = set(r)
        for rx, drugs in _INTRINSIC:
            if rx.search(o):
                extra -= drugs
        return "pan-S" if not extra else "no key resistance"
    return ", ".join(tags)


def split_orgs(s):
    """Organism names, one per entry ('A; B' strings split, 'colony type 1:' prefixes dropped)."""
    out = []
    for o in s.get("organisms") or []:
        o = o if isinstance(o, str) else o.get("name", "")
        for x in o.split("; "):
            x = re.sub(r"^colony types? [\d\- ]+:\s*", "", x.strip(), flags=re.I)
            if x:
                out.append(x)
    return out


def lab_pattern(orgs, s):
    """Pattern column: one entry per organism, in the Organisms order, joined by '; '."""
    if not orgs:
        return ""
    final = bool(s.get("final"))
    ss, rr = _ast_by_org(orgs, s.get("ast_s", "")), _ast_by_org(orgs, s.get("ast_r", ""))
    if ss is not None and rr is not None:
        return "; ".join(org_pattern(o, ss.get(o, set()), rr.get(o, set()), final) for o in orgs)
    notes = _ast_from_notes(orgs, s.get("result", ""))
    return "; ".join(org_pattern(o, *notes[o], final) if o in notes else "AST not split by organism" for o in orgs)


def lab_row(pid, s):
    """Feed Cultures row: one lab specimen, finalised or not, labelled so the two never mix (schema 4 columns)."""
    orgs = split_orgs(s)
    org = "; ".join(orgs)
    summ = lab_summary(s, org)
    if s.get("verify"):
        summ += " (to verify)"
    if s.get("final"):
        status = "Final " + ddmm(s["final_date"]) if s.get("final_date") else "Final"
    else:
        latest = s.get("updated") or s.get("unchanged_since") or s.get("file_date") or ""
        status = "Not final, latest " + ddmm(latest) if latest else "Not final"
    return [pid, ddmm(s.get("collected")), s.get("specimen", ""), s.get("sid") or "", summ, org, s.get("ast_s", ""),
            s.get("ast_r", ""), lab_pattern(orgs, s), status, s.get("source", ""), s.get("result", "")]


def daily_rows(pid, rec, cx, first):
    """Daily Report lines for this patient whose bench number has no culture row yet (Chris 19.11.2026)."""
    have = set()
    for s in cx.get("specimens", []):
        for b in re.split(r"[/,; ]+", str(s.get("dr") or "")):
            if b.strip():
                have.add(b.strip())
    names = [rec.get("name") or ""] + list(rec.get("aliases") or [])
    lo = (dt.date.fromisoformat(first) - dt.timedelta(days=5)).isoformat() if first else ""
    out = []
    for r in cx.get("daily_report", []):
        if not any(I.name_match(r.get("patient", ""), n) for n in names if n):
            continue
        m = re.search(r"(\d{4}-\d{2}-\d{2})", r.get("file", ""))
        day = m.group(1) if m else ""
        if lo and day and day < lo:
            continue
        if str(r.get("bench", "")).strip() in have:
            continue
        spec, _, res = (r.get("result", "") or "").partition(":")
        out.append([pid, ddmm(day), str(r.get("bench", "")), spec.strip(), res.strip()])
    return out


def build(state, census, ams, cx, today, infeed=(), backlog=10):
    rows = {t: [] for t in TABS}
    cen = {p["pid"]: p for p in census.get("patients", [])}
    amsb = dict((ams or {}).get("patients") or {})
    ol = (ams or {}).get("off_list") or {}
    for k, v in (ol.items() if isinstance(ol, dict) else []):
        amsb.setdefault(k, v)
    pts = []
    for pid, rec in state.get("patients", {}).items():
        if rec.get("dup_of") or rec.get("registered"):
            continue
        if pid in cen or rec.get("active"):
            pts.append((pid, rec, "Active"))
        elif rec.get("archive_note_sent") and on_service_once(rec):
            pts.append((pid, rec, departed_status(rec, today)))
    # departed records enter the feed when they leave (last 3 days) or, older ones, at most `backlog` a day (oldest first)
    recent = (dt.date.fromisoformat(today) - dt.timedelta(days=3)).isoformat()
    old = sorted([x for x in pts if x[2] != "Active" and x[0] not in infeed and (x[1].get("last_seen") or "") < recent],
                 key=lambda x: x[1].get("last_seen") or "")
    drop = {x[0] for x in old[backlog:]}
    pts = [x for x in pts if x[0] not in drop]
    # backfill (29.10.2026): past admissions with no register block, queued once by `backfill --queue`; they share the
    # daily cap with the departed backlog and stay in the feed (Discharged) until their block is FINAL in Index
    bf = state.get("backfill") or {}
    slots = max(0, backlog - min(len(old), backlog))
    have = {x[0] for x in pts}
    bf_rows = []
    for pid, e in sorted(bf.items(), key=lambda kv: kv[1].get("last") or ""):
        if pid in have:
            continue
        if pid not in infeed:
            if slots <= 0:
                continue
            slots -= 1
        rec = state.get("patients", {}).get(pid)
        if rec is not None:
            pts.append((pid, rec, "Discharged " + ddmm(rec.get("last_seen"))))
        else:
            bf_rows.append((pid, e))
    for pid, rec, status in sorted(pts):
        sy = rec.get("synth") or {}
        c = cen.get(pid, {})
        b = (amsb.get(pid) or {}).get("rows") or []
        r0 = b[0] if b else []
        a = lambda i: (r0[i] if len(r0) > i and r0[i] is not None else "")
        issues = sy.get("issues") or []
        vit = sy.get("vitals") or []
        loc = (amsb.get(pid) or {}).get("location") or {}
        amsloc = ("%s!%s" % (loc.get("sheet"), loc.get("first_row"))) if loc.get("sheet") and loc.get("first_row") else ""
        rows["Feed Patients"].append([pid, rec.get("mrn") or c.get("mrn") or (a(5) if str(a(5)).isdigit() else ""),
            rec.get("name") or c.get("name", ""), status, c.get("room") or sy.get("_room", ""), c.get("fellow") or sy.get("_fellow", ""),
            "Y" if "uc" in (c.get("tags") or sy.get("_tags") or []) else "", ddmm(rec.get("first_seen")), ddmm(rec.get("last_seen")),
            a(6), (ddmm(c["as_admission"]) if c.get("as_admission") else (a(11) or I_current_doa(sy.get("one_liner"), rec.get("first_seen")) or "")), a(10), a(8), sy.get("one_liner", ""), " ; ".join(i.get("dx", "") for i in issues),
            " ; ".join(sy.get("id_plan") or []), vit[0] if vit else "", " ; ".join(vit[1:]), sy.get("micro_recap", ""),
            " ; ".join(sy.get("pendings") or []), " ; ".join(sy.get("conflicts") or []), amsloc,
            " ; ".join(sy.get("im_detail") or []), " ; ".join(sy.get("steroids") or []), " ; ".join(sy.get("devices") or []),
            " ; ".join("%s: %s" % kv for kv in (sy.get("not_applied") or {}).items()),
            " ; ".join(sy.get("updates") or []) if status == "Active" else ""])
        abx = [(i.get("dx", "").split(" | ")[0], l) for i in issues for l in i.get("abx", [])] + [("no linked issue", l) for l in sy.get("abx_other") or []]
        if not abx:
            abx = [(h.get("issue", ""), h.get("line", h.get("drug", ""))) for h in rec.get("abx_history", [])]
        seen = {}
        for ind, line in abx:
            drug, start, end, note = I.abx_row(line)
            name = drug.split()[0] if drug else line.split()[0]
            k = name; seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                k = "%s #%d" % (name, seen[name])
            running = "Y" if end == "Ongoing at discharge" else "N"
            rows["Feed Antimicrobials"].append([pid, k, line, ind, start, "" if running == "Y" else end, running])
        mseen = {}
        for line in sy.get("micro") or []:
            d, spec, res = I.micro_row(line)
            k = (d, spec); mseen[k] = mseen.get(k, 0) + 1
            rows["Feed Micro"].append([pid, d, spec + ("" if mseen[k] == 1 else " #%d" % mseen[k]), res,
                                       "Preliminary" if "prelim" in res.lower() else "Final", "N"])
        for p in sy.get("pendings") or []:
            rows["Feed Micro"].append([pid, "", "Pending: " + p, "", "Pending", "N"])
    for pid, e in bf_rows:
        rows["Feed Patients"].append([pid, e.get("mrn", ""), e.get("name", ""), "Discharged " + ddmm(e.get("last")), e.get("room", ""),
                                      e.get("fellow", ""), "", ddmm(e.get("first")), ddmm(e.get("last"))] + [""] * 4 +
                                     [e.get("one_liner", "")] + [""] * 7 +
                                     [("%s!%s" % (e["ams_sheet"], e["ams_first_row"])) if e.get("ams_sheet") and e.get("ams_first_row") else ""] + [""] * 5)
    for pid, w in (state.get("watch") or {}).items():
        rows["Feed Patients"].append([pid, w.get("mrn", ""), w.get("name", ""), "Watch " + ddmm(w.get("discharged")), "", "", "",
                                      "", ddmm(w.get("discharged"))] + [""] * 18)
        for s in stay_specimens(cx, w.get("mrn"), w.get("name"), w.get("aliases"), None, w.get("discharged")):
            if (s.get("collected") or "") >= (dt.date.fromisoformat(w["discharged"]) - dt.timedelta(days=30)).isoformat() \
                    and (s.get("final_date") or "9999") > (w.get("discharged") or ""):
                rows["Feed Micro"].append(spec_row(pid, s, w.get("discharged")))
    # departed (not yet final) patients: their lab results of the stay too, so Gemini closes pendings
    for pid, rec, status in pts:
        if status != "Active" and cx:
            for s in stay_specimens(cx, rec.get("mrn"), rec.get("name"), rec.get("aliases"), rec.get("first_seen"), rec.get("last_seen")):
                if (s.get("final_date") or "9999") > (rec.get("last_seen") or ""):
                    rows["Feed Micro"].append(spec_row(pid, s, rec.get("last_seen")))
    # Feed Cultures: every specimen of the stay for each patient in the feed, final and not final alike
    for pid, rec, status in pts:
        if cx:
            adm = (cen.get(pid) or {}).get("as_admission")
            first = min(x for x in (adm, rec.get("first_seen")) if x) if (adm or rec.get("first_seen")) else None
            for s in stay_specimens(cx, rec.get("mrn"), rec.get("name"), rec.get("aliases"), first,
                                    None if status == "Active" else rec.get("last_seen")):
                rows["Feed Cultures"].append(lab_row(pid, s))
    # Feed Daily Report: bench preliminary lines not yet superseded by a culture row (active patients)
    for pid, rec, status in pts:
        if cx and status == "Active":
            adm = (cen.get(pid) or {}).get("as_admission")
            first = min(x for x in (adm, rec.get("first_seen")) if x) if (adm or rec.get("first_seen")) else None
            rows["Feed Daily Report"].extend(daily_rows(pid, rec, cx, first))
    for pid, w in (state.get("watch") or {}).items():
        for s in stay_specimens(cx, w.get("mrn"), w.get("name"), w.get("aliases"), None, None):
            if (s.get("collected") or "") >= (dt.date.fromisoformat(w["discharged"]) - dt.timedelta(days=30)).isoformat():
                rows["Feed Cultures"].append(lab_row(pid, s))
    out = {}
    for t, (hdr, nkey, _) in TABS.items():
        seen, lst = {}, []
        for r in rows[t]:
            r = [cell(v) for v in r] + [""] * (len(hdr) - 1 - len(r))
            k = key_of(r, nkey)
            if k in seen:                       # same key twice (e.g. same specimen from two sources): keep both, numbered
                seen[k] += 1
                r[nkey - 1] = "%s #%d" % (r[nkey - 1], seen[k])
                k = key_of(r, nkey)
            seen[k] = 1
            lst.append(r[:len(hdr) - 1])
        out[t] = lst
    return out


def cmd_feed(a):
    state, census = jload(a.state), jload(a.census) or {"patients": []}
    ams, cx = jload(a.ams_blocks), jload(a.cultures) or {"specimens": []}
    pnow0 = raw_values(os.path.join(a.nowdir, "patients.json"))
    desired = build(state, census, ams, cx, a.date, {r[0] for r in pnow0[1:] if r}, a.backlog)
    today = dmy(a.date)
    ops, changes, summary = [], [], []
    pnow = raw_values(os.path.join(a.nowdir, "patients.json"))
    known_pids = {r[0] for r in pnow[1:] if r}
    for t, (hdr, nkey, fname) in TABS.items():
        now = raw_values(os.path.join(a.nowdir, fname + ".json"))
        body = now[1:]
        start = 2
        migrating = bool(now) and [x.strip() for x in now[0]] != hdr[:len(now[0])]
        if not now or migrating:
            ops.append({"range": "'%s'!A1:%s1" % (t, col(len(hdr))), "values": [hdr]})
        cur = {}
        for i, r in enumerate(body):
            r = r + [""] * (len(hdr) - len(r))
            if any(r):
                cur[tuple(r[:nkey])] = (start + i, r)
        nxt = start + len(body)
        want = {key_of(r, nkey): r for r in desired[t]}
        upd = {}
        for k, r in want.items():
            if k in cur:
                rown, old = cur[k]
                if old[:len(hdr) - 1] != [bare(x) for x in r]:
                    upd[rown] = r + [today]
                    for h, o, n in zip(hdr, old, r):
                        if o != bare(n) and not (migrating and h == "AMS block"):
                            changes.append([today, r[0], t, " | ".join(k), h, o[:300], bare(n)[:300]])
            else:
                upd[nxt] = r + [today]; nxt += 1
                if r[0] in known_pids or t == "Feed Patients":
                    changes.append([today, r[0], t, " | ".join(k), "(new row)", "", ""])
        for k, (rown, old) in cur.items():
            if k not in want:
                upd[rown] = [""] * len(hdr)
                changes.append([today, old[0], t, " | ".join(k), "(removed)", "", ""])
        summary.append("%s %d" % (t, len(upd)))
        rws = sorted(upd)
        i = 0
        while i < len(rws):
            j = i
            while j + 1 < len(rws) and rws[j + 1] == rws[j] + 1 and j - i < 39:
                j += 1
            ops.append({"range": "'%s'!A%d:%s%d" % (t, rws[i], col(len(hdr)), rws[j]), "values": [upd[x] for x in rws[i:j + 1]]})
            i = j + 1
    ch = raw_values(os.path.join(a.nowdir, "changes.json"))
    if not ch:
        ops.append({"range": "'Feed Changes'!A1:G1", "values": [CHANGES]}); crow = 2
    else:
        crow = len(ch) + 1
    changes = [[cell(v) for v in r] for r in changes]
    for i in range(0, len(changes), 60):
        part = changes[i:i + 60]
        ops.append({"range": "'Feed Changes'!A%d:G%d" % (crow, crow + len(part) - 1), "values": part}); crow += len(part)
    evo = getattr(a, "evolution", None) or os.path.join(os.path.dirname(os.path.abspath(a.outdir)), "evolution.json")
    erows, eops = evolution_rows(jload(evo) if os.path.exists(evo) else None,
                                 raw_values(os.path.join(a.nowdir, "evolution.json")), a.date)
    ops += eops
    rnow = raw_values(os.path.join(a.nowdir, "review.json"))
    if not any(any(c for c in r) for r in rnow):           # Gemini's tab: header only when absent, never anything else
        ops.append({"range": "'Gemini Review'!A1:%s1" % col(len(REVIEW)), "values": [REVIEW]})
    os.makedirs(a.outdir, exist_ok=True)
    json.dump(desired, open(os.path.join(a.outdir, "feed_desired.json"), "w"), ensure_ascii=True)
    json.dump(ops, open(os.path.join(a.outdir, "ops.json"), "w"), ensure_ascii=True)
    print("FEED OPS: %d update_values call(s); changed rows: %s; %d change-log row(s); %d evolution row(s); %d patients in the feed"
          % (len(ops), ", ".join(summary), len(changes), len(erows), len(desired["Feed Patients"])))
    return 0


def evolution_rows(rep, now, date):
    """Rows for the Evolution tab from evolution.json (today's changes only), appended after the rows already there;
    a row already in the tab (same pid, Date, Field, Kind, Old, New) is not written twice (a rerun of the day)."""
    ops = []
    if not now:
        ops.append({"range": "'Evolution'!A1:%s1" % col(len(EVOLUTION)), "values": [EVOLUTION]})
    if not rep or rep.get("date") != date:
        return [], ops
    today = dmy(date)
    have = {tuple(r[:6]) for r in now[1:] if r}
    rows = []
    for pid, p in (rep.get("patients") or {}).items():
        for c in p.get("changes") or []:
            r = [cell(v) for v in (pid, today, c.get("field", ""), c.get("kind", ""), c.get("old", ""), c.get("new", ""),
                                   c.get("source", "") if c.get("explained") else "UNEXPLAINED", today)]
            if tuple(bare(x) for x in r[:6]) not in have:
                rows.append(r); have.add(tuple(bare(x) for x in r[:6]))
    start = max(len(now), 1) + 1
    for i in range(0, len(rows), 60):
        part = rows[i:i + 60]
        ops.append({"range": "'Evolution'!A%d:%s%d" % (start + i, col(len(EVOLUTION)), start + i + len(part) - 1), "values": part})
    return rows, ops


# ------------------------------------------------------------------ Gemini Review (28.11.2026)
def review_rows(vals):
    """[(sheet row number, row padded to 11)] for every row of the Gemini Review tab with a Statement."""
    out = []
    hdr = bool(vals) and [x.strip() for x in vals[0][:2]] == REVIEW[:2]
    for n, r in enumerate(vals[1:] if hdr else vals, 2 if hdr else 1):
        r = (r + [""] * len(REVIEW))[:len(REVIEW)]
        if r[5].strip() or r[4].strip():
            out.append((n, r))
    return out


def review_age(r, today):
    """Rounds a row has had: days since Gemini dated it."""
    return days(r[0], today) if r[0].strip() else 0


def cmd_review(a):
    rows = review_rows(raw_values(a.review))
    opn = [(n, r) for n, r in rows if not r[7].strip()]
    late = [(n, r) for n, r in opn if review_age(r, a.date) > 1]
    lines = ["Gemini Review %s: %d open point(s) to answer (reply accepted | rejected | partly, with the reason; check the sources first)"
             % (a.date, len(opn)), ""]
    for n, r in opn:
        lines.append("row %d | %s | %s %s | %s | %s | %s | evidence: %s%s" % (n, r[0], r[1], r[2], r[3], r[4], r[5], r[6],
                     " | OPEN MORE THAN ONE ROUND (will be escalated)" if review_age(r, a.date) > 1 else ""))
    unresolved = [(n, r) for n, r in rows if r[7].strip() and not r[9].strip()]
    if unresolved:
        lines += ["", "Answered but not resolved:"] + ["row %d | %s | %s | %s: %s" % (n, r[1], r[3], r[7], r[8]) for n, r in unresolved]
    os.makedirs(a.outdir, exist_ok=True)
    open(os.path.join(a.outdir, "review_open.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("REVIEW OK: %d open, %d open more than one round, %d answered but unresolved" % (len(opn), len(late), len(unresolved)))
    return 0


def cmd_reviewreply(a):
    rows = dict(review_rows(raw_values(a.review)))
    rep = jload(a.replies) or {}
    today = dmy(a.date)
    out, errs = {}, []
    for k, v in rep.items():
        try:
            n = int(k)
        except ValueError:
            errs.append("row %r is not a row number" % k); continue
        r = rows.get(n)
        reply = ((v or {}).get("reply") or "").strip().lower()
        reason = ((v or {}).get("reason") or "").strip()
        if r is None:
            errs.append("row %d is not a Gemini Review point" % n); continue
        if r[7].strip():
            errs.append("row %d already has a Claude reply (%s)" % (n, r[7])); continue
        if reply not in REVIEW_REPLIES or not reason:
            errs.append("row %d: reply must be accepted | rejected | partly, with a reason" % n); continue
        resolved = today if reply == "accepted" else ""
        esc = "" if resolved else "Y"          # rejected or partly: still unresolved after its round, for Chris
        out[n] = [reply, cell(reason), cell(resolved), esc]
    # an open point nobody answered for more than one round is escalated (only the Escalated cell is written)
    for n, r in rows.items():
        if n not in out and not r[7].strip() and not r[10].strip() and review_age(r, a.date) > 1:
            out[n] = [None, None, None, "Y"]
    if errs:
        for e in errs:
            print("ERROR " + e)
        print("REVIEWREPLY FAILED: %d error(s)" % len(errs)); return 1
    ops = []
    first, last = col(REVIEW_GEMINI + 1), col(len(REVIEW))
    rws = sorted(out)
    i = 0
    while i < len(rws):
        j = i
        while j + 1 < len(rws) and rws[j + 1] == rws[j] + 1 and j - i < 39:
            j += 1
        ops.append({"range": "'Gemini Review'!%s%d:%s%d" % (first, rws[i], last, rws[j]), "values": [out[x] for x in rws[i:j + 1]]})
        i = j + 1
    os.makedirs(a.outdir, exist_ok=True)
    json.dump(ops, open(os.path.join(a.outdir, "review_ops.json"), "w"), ensure_ascii=True)
    nrep = sum(1 for x in out.values() if x[0]); nesc = sum(1 for x in out.values() if x[3] == "Y")
    print("REVIEWREPLY OK: %d repl(ies), %d escalated, %d update_values call(s) in review_ops.json (columns %s..%s only; null cells are skipped by Sheets)"
          % (nrep, nesc, len(ops), first, last))
    return 0


def cmd_op(a):
    ops = json.load(open(a.ops))
    print(json.dumps(ops[a.n - 1], ensure_ascii=True))
    return 0


def cmd_feedcheck(a):
    desired = json.load(open(a.desired)); bad = []
    for t, (hdr, nkey, fname) in TABS.items():
        now = raw_values(os.path.join(a.nowdir, fname + ".json"))
        got = {}
        for r in now[1:]:
            r = r + [""] * (len(hdr) - len(r))
            if any(r):
                got[tuple(r[:nkey])] = r[:len(hdr) - 1]
        want = {key_of(r, nkey): r for r in desired[t]}
        for k, r in want.items():
            g = got.get(k)
            if g is None or [bare(x) for x in r] != g:
                bad.append("%s %s" % (t, " | ".join(k)))
        for k in got:
            if k not in want:
                bad.append("%s %s (should be cleared)" % (t, " | ".join(k)))
    for b in bad[:30]:
        print("MISMATCH " + b)
    if bad:
        print("FEED FAILED: %d row(s) differ" % len(bad)); return 1
    print("FEED MATCH. Meta op: " + json.dumps(meta_op(a.date), ensure_ascii=True))
    return 0


# ------------------------------------------------------------------ leaving the state
def index_final(index_vals):
    hdr = index_vals[0] if index_vals else []
    ki, fi = (hdr.index("Keys") if "Keys" in hdr else 3), (hdr.index("FINAL") if "FINAL" in hdr else 9)
    out = {}
    for r in index_vals[1:]:
        r = r + [""] * 12
        for k in re.split(r";\s*", r[ki]):
            m = re.search(r"\|\s*(P\d{3,5})\s*\|", k)
            if m:
                out.setdefault(m.group(1), []).append((k.strip(), r[fi].strip().upper() == "Y"))
    return out


def cmd_final(a):
    state = jload(a.state); idx = index_final(raw_values(a.index)); entries = []
    for pid, rec in state.get("patients", {}).items():
        if rec.get("active") or rec.get("dup_of") or not (rec.get("archive_note_sent") or pid in (state.get("backfill") or {})):
            continue
        if not on_service_once(rec):
            continue
        fin = [k for k, f in idx.get(pid, []) if f]
        if fin and (rec.get("archive_note_sent") or "") < a.date:
            entries.append({"pid": pid, "key": fin[-1], "pendings": [p.get("item") for p in rec.get("pendings_state", []) if isinstance(p, dict)]})
    rr = os.path.join(os.path.dirname(os.path.abspath(a.state)), "final_rows.json")
    json.dump({"entries": entries, "values": []}, open(rr, "w"))
    ns = argparse.Namespace(state=a.state, rows=rr, cultures=a.cultures, date=a.date)
    I.cmd_strip(ns)
    st = jload(a.state); bf = st.get("backfill") or {}
    done = [p for p in bf if any(f for _, f in idx.get(p, []))]
    if done:
        for p in done:
            bf.pop(p, None)
        json.dump(st, open(a.state, "w", encoding="utf-8"), ensure_ascii=False)
        print("backfill: %d admission(s) now FINAL in Index, %d still queued" % (len(done), len(bf)))
    print("FINAL OK: %d record(s) with a FINAL register block left the state" % len(entries))
    return 0


# ------------------------------------------------------------------ Claude checks Gemini's Register
DRUG = {"mero": ["merop"], "piptazo": ["pip", "tazo"], "erta": ["ertap"], "zavi": ["avibac", "zavic", "ceftazidime-avi"],
        "zerb": ["zerbax", "ceftoloz"], "cefe": ["cefepi"], "ceftriax": ["ceftriax"], "aztreo": ["aztreo"], "amik": ["amika"],
        "tige": ["tigec"], "vanco": ["vanco"], "teico": ["teico"], "tavanic": ["levoflox", "tavanic"], "cipro": ["ciproflox", "cipro"],
        "azithro": ["azithro"], "flagyl": ["metronid", "flagyl"], "bactrim": ["bactrim", "trimethoprim", "sulfameth", "cotrimox"],
        "augmentin": ["augmentin", "amoxicillin-clav", "amoxiclav", "clavul"], "amox": ["amox"], "fluco": ["flucon"],
        "vori": ["voricon"], "caspo": ["caspof"], "ecalta": ["anidulaf", "ecalta"], "amphob": ["amphot", "ambisome"],
        "valganci": ["valganc"], "ganci": ["ganciclo"], "fidaxo": ["fidaxo"], "colistin": ["colist"], "linez": ["linezo"],
        "dapto": ["dapto"], "fosfo": ["fosfo"]}


def drug_terms(d):
    d = re.sub(r"[^a-z]", "", (d or "").split("#")[0].lower())
    return (DRUG.get(d, []) + [d]) if d else []


def blocks_of(vals):
    blocks, order, cur = {}, [], None
    for r in vals[1:] if vals and vals[0][:1] == ["Key"] else vals:
        r = r + [""] * (35 - len(r))
        if r[0] == "---" or (not r[0] and r[2] == "---"):
            cur = None; continue
        if not r[0]:
            continue
        if r[0] != cur:
            cur = r[0]
            if cur in blocks:
                blocks[cur] = []                 # a later block with the same Key replaces the earlier one
            else:
                order.append(cur)
            blocks[cur] = []
        blocks[cur].append(r)
    return blocks, order


def next_ids(ver, prefix, date):
    tag = "%s-%s-" % (prefix, date.replace("-", ""))
    n = max([int(r[0][len(tag):]) for r in ver if r and r[0].startswith(tag) and r[0][len(tag):].isdigit()] or [0])
    while True:
        n += 1
        yield "%s%04d" % (tag, n)


def index_keys(index_vals):
    """pid -> list of Index Keys naming it (a Key is 'MRN x | Pnnnn | dd/mm/yy to dd/mm/yy')."""
    hdr = index_vals[0] if index_vals else []
    ki = hdr.index("Keys") if "Keys" in hdr else 3
    out = {}
    for r in index_vals[1:]:
        r = r + [""] * 12
        for k in re.split(r"\n|;\s*", r[ki]):
            m = re.search(r"\|\s*(P\d{3,5})\s*\|", k)
            if m:
                out.setdefault(m.group(1), []).append(k.strip())
    return out


def coverage(desired, index_vals, date=None):
    # a pid first seen today has not had Gemini's 09:30 morning yet: pending, not missing
    if index_vals is None:
        return None
    ik = index_keys(index_vals)
    today = dt.date.fromisoformat(date) if date else None
    bad, n, pending = [], 0, 0
    for r in desired["Feed Patients"]:
        n += 1
        k = ik.get(r[0], [])
        if not k and today:
            fs = pdate(bare(r[7]))
            if fs and fs >= today:
                pending += 1; continue
        if len(k) != 1:
            bad.append((r[0], len(k), "%s | MRN %s | %s to %s | %s" % (r[0], bare(r[1]), bare(r[7]), bare(r[8]), r[3])))
    return {"n": n, "bad": bad, "missing": sum(1 for b in bad if b[1] == 0), "dup": sum(1 for b in bad if b[1] > 1),
            "pending": pending}


def dm(v):
    """First dd/mm in a cell, zero-padded ('06/10/26, ~6/10, 06/10-09/10 -> 06/10); '' if none."""
    m = re.search(r"(\d{1,2})/(\d{1,2})", str(v or ""))
    return "%02d/%02d" % (int(m.group(1)), int(m.group(2))) if m else ""


def cmd_checkreg(a):
    os.makedirs(a.outdir, exist_ok=True)
    reg = raw_values(a.register); desired = json.load(open(a.desired)); ver = raw_values(a.verification)
    cx = jload(a.cultures) or {"specimens": []}
    blocks, order = blocks_of(reg)
    pts = {r[0]: r for r in desired["Feed Patients"]}
    abx = {}
    for r in desired["Feed Antimicrobials"]:
        abx.setdefault(r[0], []).append(r)
    mine = {}
    for r in ver[1:]:
        r = r + [""] * 14
        if r[2] == "Claude" and r[3] == "Register":
            mine.setdefault(r[4], []).append(r)
    ids = next_ids(ver, "C", a.date); today = dmy(a.date); rows = []; nver = nfind = 0
    for key in order:
        m = re.search(r"\|\s*(P\d{3,5})\s*\|", key)
        b = blocks[key]
        if not m or not b[0][1].startswith("Discharged"):
            continue
        prev = mine.get(key, [])
        if any(p[13] in ("open", "disputed") for p in prev) or (prev and prev[-1][13] == "verified"):
            continue
        pid = m.group(1); p = pts.get(pid)
        if not p or not p[3].startswith("Discharged"):     # only blocks of admissions that ended, with Claude's record at hand
            continue
        text = lambda c: " ".join(r[c] for r in b).lower()
        found = []
        if p[1] and b[0][6] and re.sub(r"\D", "", p[1]) != re.sub(r"\D", "", b[0][6]):
            found.append(("MRN", b[0][6], p[1], "Feed Patients " + pid, "wrong"))
        drugs = text(22)
        for r in abx.get(pid, []):
            terms = drug_terms(r[1])
            hit = [x for x in b if any(t in x[22].lower() for t in terms)]
            if terms and not hit:
                found.append(("Actual antibiotics", "", r[2], "Feed Antimicrobials " + pid, "missing"))
            elif hit and r[4] and r[4] not in ("?",):
                d = dm(r[4])                              # 30.10.2026: compare dd/mm only; cells carry ' and ~
                if d and not any(dm(x[23]) == d for x in hit):
                    found.append(("Date started", "; ".join(x[23] for x in hit), r[2], "Feed Antimicrobials " + pid, "doubtful"))
        orgtext = text(32) + " " + text(30) + " " + text(33) + " " + text(34)
        if cx and p[1]:
            for s in stay_specimens(cx, p[1], p[2], [], None, None):
                for o in s.get("organisms") or []:
                    o = (o if isinstance(o, str) else o.get("name", "")).lower()
                    words = [w for w in re.findall(r"[a-z]{4,}", o) if w not in ("ampc", "esbl", "type", "wild", "spp")]
                    if s.get("final") and words and not any(w in orgtext for w in words):
                        found.append(("Organism", "", "%s %s %s" % (ddmm(s.get("collected")), s.get("specimen", ""), o),
                                      "Daily Cultures %s" % s.get("source", ""), "missing"))
        found = list({(f[0], f[2]): f for f in found}.values())
        if found:
            for colname, got, want, src, sev in found:
                rows.append([next(ids), today, "Claude", "Register", key, colname, got, want, src, sev, "", "", "", "open"]); nfind += 1
        else:
            rows.append([next(ids), today, "Claude", "Register", key, "ALL", "MRN, every antimicrobial and start date, organisms",
                         "Claude's record and Daily Cultures", "IDP Feed, Daily Cultures", "", "", "", "", "verified"]); nver += 1
    # coverage (29.10.2026): every pid in Feed Patients has exactly one Index Key
    ipath = getattr(a, "index", None) or os.path.join(os.path.dirname(os.path.abspath(a.register)), "reg_Index.json")
    cov = coverage(desired, raw_values(ipath) if os.path.exists(ipath) else None, a.date)
    if cov is None:
        line = "register: index not read, coverage not checked"
    else:
        openrows = {(r[4], r[9]) for r in ver[1:] if len(r) > 13 and r[2] == "Claude" and r[3] == "Index" and r[13] == "open"}
        for pid, n, info in cov["bad"]:
            sev = "missing block" if n == 0 else "duplicate block"
            if (pid, sev) not in openrows:
                rows.append([next(ids), today, "Claude", "Index", pid, "Keys", "%d Key(s)" % n, info, "Feed Patients",
                             sev, "", "", "", "open"])
        line = "register: %d admissions, %d without a block%s%s" % (
            cov["n"], cov["missing"], (", %d with more than one" % cov["dup"]) if cov["dup"] else "",
            (", %d new today (block due at Gemini's 09:30)" % cov["pending"]) if cov["pending"] else "")
    print(line)
    open(os.path.join(a.outdir, "coverage.txt"), "w").write(line + "\n")
    rs = os.path.join(os.path.dirname(os.path.abspath(a.outdir)), "run_status.txt")
    if os.path.exists(rs):
        txt = open(rs).read()
        txt = re.sub(r"(?m)^register: .*\n?", "", txt)
        open(rs, "w").write(txt + ("" if txt.endswith("\n") or not txt else "\n") + line + "\n")
    start = len(ver) + 1 if ver else 2
    ops = []
    if not ver:
        ops.append({"range": "Verification!A1:N1", "values": [VER]})
    rows = [[cell(v) for v in r] for r in rows]
    for i in range(0, len(rows), 40):
        part = rows[i:i + 40]
        ops.append({"range": "Verification!A%d:N%d" % (start + i, start + i + len(part) - 1), "values": part})
    json.dump(ops, open(os.path.join(a.outdir, "vrows_ops.json"), "w"), ensure_ascii=True)
    last = start + len(rows) - 1
    print("CHECKREG OK: %d block(s) verified, %d finding(s); %d update_values call(s) in vrows_ops.json%s" % (
        nver, nfind, len(ops), (" (last row %d)" % last) if rows else ""))
    return 0


# ------------------------------------------------------------------ the Verification exchange
def days(d1, today):
    try:
        a = dt.datetime.strptime(d1, "%d/%m/%Y" if len(d1.strip()) == 10 else "%d/%m/%y").date()
        return (dt.date.fromisoformat(today) - a).days
    except Exception:
        return 0


def cmd_vqueue(a):
    ver = raw_values(a.verification); todo, chris, others = [], [], 0
    for n, r in enumerate(ver[1:], 2):
        r = r + [""] * 14
        if not r[0]:
            continue
        mine = r[3] in ("Admissions", "Late cultures") or r[3].startswith("Feed")
        if r[2] == "Gemini" and mine and r[13] == "open" and not r[11]:
            todo.append((n, r))
        if r[13] == "disputed" or (r[13] == "open" and days(r[1], a.date) > 2 and (r[2] == "Claude" or mine)):
            chris.append((n, r))
        elif r[13] == "open" and days(r[1], a.date) > 2:
            others = others + 1
    print("== Gemini findings on Claude's data, to answer (check each against the sources first) ==")
    for n, r in todo:
        print("row %d %s | %s | %s | %s | checked: %s | source says: %s | %s | %s" % (n, r[0], r[3], r[4], r[5], r[6][:200], r[7][:200], r[8][:120], r[9]))
    print("== For Chris (disputed, or open more than 2 days) ==")
    for n, r in chris:
        print("row %d %s %s %s %s: %s" % (n, r[0], r[13], r[4][:60], r[5], (r[12] or r[7])[:160]))
    if others:
        print("%d of Gemini's own findings (History, Register) open more than 2 days: one line for Chris, no detail" % others)
    print("VQUEUE OK: %d to answer, %d for Chris" % (len(todo), len(chris)))
    return 0


def cmd_vwrite(a):
    ver = raw_values(a.verification); rep = json.load(open(a.replies))
    rows = {int(x["row"]): ["Claude", x["reply"], cell(x.get("note", "")), x["state"]] for x in rep}
    for n in rows:
        r = (ver[n - 1] if n - 1 < len(ver) else []) + [""] * 14
        if r[2] != "Gemini":
            print("ERROR row %d is not a Gemini finding" % n); return 1
        if rows[n][1] not in ("agree", "disagree", "already fixed") or rows[n][3] not in ("fixed", "agreed", "disputed", "open"):
            print("ERROR row %d: reply or state not allowed" % n); return 1
    ops = []
    if rows:
        lo, hi = min(rows), max(rows)
        for s in range(lo, hi + 1, 40):
            e = min(hi, s + 39)
            ops.append({"range": "Verification!K%d:N%d" % (s, e), "values": [rows.get(i, [None] * 4) for i in range(s, e + 1)]})
    os.makedirs(a.outdir, exist_ok=True)
    json.dump(ops, open(os.path.join(a.outdir, "vreply_ops.json"), "w"), ensure_ascii=True)
    print("VWRITE OK: %d repl(ies), %d update_values call(s) in vreply_ops.json (null cells are skipped by Sheets)" % (len(rows), len(ops)))
    return 0


def cmd_regjoin2(a):
    vals = [I.REG_HEADER]
    for p in a.files:
        v = raw_values(p)
        vals += [r for r in (v[1:] if v and v[0][:1] == ["Key"] else v) if r and r[0] and r[0] != "---"]
    json.dump({"admissions": {"values": vals}, "late": {"values": []}}, open(a.out, "w"), ensure_ascii=True)
    b, _ = I.register_rows({"admissions": {"values": vals}})
    print("REGJOIN OK: %d admission block(s) from %d tab(s)" % (len(b), len(a.files)))
    return 0


# ------------------------------------------------------------------ backfill (once, after Chris's go)
def cmd_backfill(a):
    """Admissions known to the run (state, and the IDP_Data identifiers tables) that have no register block: by pid in
    an Index Key, or by an AMS-keyed Key with the same MRN whose dates overlap the stay (+-5 days). Consult-only and
    AS-list-only records are not admissions of the service. Prints the count and date range only (no names)."""
    import csv, glob, io
    state = jload(a.state); ik = index_keys(raw_values(a.index)); km = {}
    for r in raw_values(a.index)[1:]:
        r = r + [""] * 12
        for k in re.split(r"\n|;\s*", r[3]):
            m = re.match(r"MRN\s+'?(\S+)\s*\|\s*(\S+)\s*\|\s*(\S*)\s*to\s*(\S*)", k.strip())
            if m:
                km.setdefault(m.group(1), []).append((pdate(m.group(3)), pdate(m.group(4))))
    adm = {}
    for pid, r in state.get("patients", {}).items():
        if r.get("dup_of") or not on_service_once(r) or r.get("active"):
            continue
        adm[pid] = {"mrn": r.get("mrn", ""), "name": r.get("name", ""), "first": r.get("first_seen"), "last": r.get("last_seen"), "in_state": True}
    for f in sorted(glob.glob(os.path.join(a.tables, "identifiers*"))):
        for row in csv.DictReader(io.StringIO(open(f, encoding="utf-8").read().replace("\\_", "_"))):
            p = row.get("pid")
            if p and p not in state.get("patients", {}) and row.get("first_seen") and row.get("last_seen"):
                adm[p] = {"mrn": row.get("mrn", ""), "name": row.get("name", ""), "aliases": [x for x in (row.get("aliases") or "").split("; ") if x],
                          "first": row["first_seen"], "last": row["last_seen"], "ams_sheet": row.get("ams_sheet", ""),
                          "ams_first_row": row.get("ams_first_row", ""), "in_state": False}
    need = {}
    for p, e in adm.items():
        if ik.get(p):
            continue
        f, l = dt.date.fromisoformat(e["first"]), dt.date.fromisoformat(e["last"])
        if any(x[0] and (x[1] or dt.date(2099, 1, 1)) >= f - dt.timedelta(5) and x[0] <= l + dt.timedelta(5) for x in km.get(e["mrn"], [])):
            continue
        need[p] = e
    if not need:
        print("BACKFILL: 0 admissions without a register block"); return 0
    print("BACKFILL: %d admission(s) without a register block (of %d known); on the service %s to %s, left %s to %s; %d still in the state"
          % (len(need), len(adm), ddmm(min(e["first"] for e in need.values())), ddmm(max(e["last"] for e in need.values())),
             ddmm(min(e["last"] for e in need.values())), ddmm(max(e["last"] for e in need.values())), sum(e["in_state"] for e in need.values())))
    if a.queue:
        bf = state.setdefault("backfill", {})
        for p, e in need.items():
            bf.setdefault(p, dict(e, queued=a.date))
        json.dump(state, open(a.state, "w", encoding="utf-8"), ensure_ascii=False)
        print("BACKFILL QUEUED: %d in state[backfill]; they enter the feed at most --backlog a day, oldest first" % len(bf))
    return 0


def pdate(s):
    for f in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, f).date()
        except Exception:
            pass
    return None


# ------------------------------------------------------------------ Schema tabs (the app's contract)
INDEX_HDR = ["MRN", "Name", "Other spellings", "Keys", "Last discharge", "Last organism", "Verified by Claude",
             "Verified by Gemini", "Open findings", "FINAL"]
KEYFIX_HDR = ["old Key", "block start row", "new Key"]
SCHEMA_HDR = ["Tab", "Key", "Header row (in order)", "Meaning"]
RULES = ("Dates dd/mm/yy. Anything that looks like a number, date or formula is stored as text with a leading "
         "apostrophe. No doses. The app reads; it never writes to IDP Feed or the register.")


def schema_rows(which):
    j = lambda h: " | ".join(h)
    if which == "feed":
        fp = TABS["Feed Patients"][0]
        return [SCHEMA_HDR,
                ["Schema", "Tab", j(SCHEMA_HDR), "This contract. schema_version " + SCHEMA_VERSION + "; any header change bumps it. " + RULES],
                ["Meta", "Key", "Key | Value", "schema_version, status (live), last_run (dd/mm/yy), tabs (note for Gemini)"],
                ["Feed Patients", "pid", j(fp), "One row per admission the ID service follows (pid = one admission); the official copy of the day's round for every reader (AMS app, Gemini, audit). Written by the morning run, changed rows only. IM, Steroids, Lines, Not applied and Updates today are the recap card lines. AMS block = sheet!first row of a hand-made AMS workbook block for the same admission, blank if none."],
                ["Feed Patients", "Status = Active", "", "On the ID list today. Gemini opens the register block on the first morning it appears."],
                ["Feed Patients", "Status = Off service dd/mm/yy", "", "Off the ID list but still seen on the AS list, a handoff or an update email; dd/mm/yy = last day on the service."],
                ["Feed Patients", "Status = Discharged dd/mm/yy", "", "No source shows the patient any more (dd/mm/yy = last day seen), or a past admission fed back in by the backfill; Gemini finalises the block."],
                ["Feed Patients", "Status = Watch dd/mm/yy", "", "Block FINAL in Index; late cultures of the stay still arriving (Feed Micro, Late = Y)."],
                ["Feed Antimicrobials", "pid + Drug", j(TABS["Feed Antimicrobials"][0]), "One row per course; a second course of the same drug is 'Drug #2'. Start/End dd/mm, ~ approximate, ? not documented. Running Y/N."],
                ["Feed Micro", "pid + Collected + Specimen", j(TABS["Feed Micro"][0]), "One row per specimen or pending item. Status: Final | Final dd/mm/yy | Preliminary | Pending. Late = Y: final after discharge."],
                ["Feed Cultures", "pid + Collected + Specimen + SID", j(TABS["Feed Cultures"][0]), "Every lab specimen of the stay read from Daily Cultures, never dropped: Status 'Final dd/mm/yy' (finalised) or 'Not final, latest dd/mm/yy' (newest reading, still open). Not-final rows stay until their final arrives. Summary = one display line in the card style (organism with S and R, or the negative result); Organisms, S, R = the same parts split out; Pattern = the resistance pattern per organism, same order as Organisms, joined by '; ' (e.g. MRSA, MSSA, methicillin R, VRE, HLAR, ESBL or AmpC or NDM only when the lab wrote it, 3rd-gen ceph R, carbapenem R, DTR, FQ R, aminoglycoside R, T/S R, fluconazole R, echinocandin R, pan-S, no key resistance, AST pending, no AST, AST conflicting, check, AST not split by organism); show it as given, never infer; Notes = the raw bench text, never to be parsed."],
                ["Feed Daily Report", "pid + Date + Bench no.", j(TABS["Feed Daily Report"][0]), "Bench Daily Report preliminary lines (e.g. 'Blood' / 'GNB') for patients on the ID list, shown only while no Feed Cultures row carries that bench number; the row is cleared once the culture is updated."],
                ["Feed Changes", "(log, append only)", j(CHANGES), "Every cell the run changed: Old and New values. (new row) and (removed) for whole rows."],
                ["Evolution", "(log, append only)", j(EVOLUTION), "Notes evolve, never rewritten: every change the day made to yesterday's synthesis of a carried admission, one row per change. Field = one_liner, issues, abx, id_plan, im_detail, steroids, devices, micro, micro_recap, pendings, conflicts, not_applied, vitals. Kind: NEW | AMENDED | RETRACTED. Source = what made the change (UNEXPLAINED if none was given). Earlier days' rows are kept."],
                ["Gemini Review", "Date + pid + Field", j(REVIEW), "Gemini's daily assessment of the notes. Gemini writes Date..Evidence (View: agree | disagree | missing | suggestion); the morning run answers the next day in Claude reply (accepted | rejected | partly), Claude reason, Resolved (dd/mm/yy) and Escalated (Y when still unresolved after one round, for Chris). The run never writes Gemini's columns."],
                ["(any tab)", "a pid absent from Feed Patients", "", "The admission has left the feed: its block is FINAL and no culture is awaited."]]
    return [SCHEMA_HDR,
            ["Schema", "Tab", j(SCHEMA_HDR), "This contract, written by the morning run. schema_version " + SCHEMA_VERSION + "; any header change bumps it. " + RULES],
            ["Register", "Key", j(I.REG_HEADER), "Gemini's blocks, current admissions. Key + Status, then the 33 columns of LAU_AMS_Dec_2025_2026_cleaned_in_original_format in the same order. One block = rows sharing a Key; a row with --- ends a block."],
            ["Register", "Key format", "MRN <mrn> | <pid or AMS> | dd/mm/yy to dd/mm/yy", "pid Pnnnn for admissions the ID service followed (from IDP Feed); AMS for blocks taken from the hand-kept workbook. 'to' blank while the stay is open."],
            ["Register", "Status = Active (updated dd/mm/yy)", "", "Admission on the ID service; block opened on its first morning in IDP Feed and updated daily."],
            ["Register", "Status = Off service dd/mm/yy", "", "Left the ID list; still seen in hospital by a source."],
            ["Register", "Status = Discharged dd/mm/yy", "", "Stay ended; '(registered dd/mm/yy)' when the block was written after the discharge (backfill)."],
            ["Admissions", "Key", j(I.REG_HEADER), "Same layout as Register."],
            ["History", "Key", j(I.REG_HEADER), "Same layout; historical blocks from the AMS workbook (frozen .xlsx), read only."],
            ["Index", "MRN", j(INDEX_HDR), "One row per patient: every Key of that patient in Keys (one per admission). FINAL = Y: the latest block is final; the morning run then drops the record from its state."],
            ["Verification", "Row ID", j(VER), "Findings between Claude (C- rows) and Gemini (G- rows). Found by Claude | Gemini. Severity: missing | wrong | doubtful | missing block | duplicate block. State: open | agreed | disputed | fixed | verified."],
            ["Late cultures", "Key + Collected + Specimen", j(I.LATE_HEADER), "Results final after the stay, appended to the admission's Key."],
            ["Late cultures 2", "Key + Collected + Specimen", j(I.LATE_HEADER), "Same layout as Late cultures."],
            ["Key fixes", "old Key", j(KEYFIX_HDR), "Keys renamed by Gemini, with the block's first row."]]


def meta_op(date):
    return {"range": "'Meta'!A1:B5", "values": [["Key", "Value"], ["schema_version", SCHEMA_VERSION], ["status", "live"],
                                                 ["last_run", dmy(date)], ["tabs", META_NOTE]]}


def cmd_svccheck(a):
    """Incomplete app import (spec 5.9.4): roster names absent from both patients[] and removed[] of the service list."""
    sv = jload(a.service_list) or {}
    names = [p.get("name", "") for p in sv.get("patients", [])] + [p.get("name", "") for p in sv.get("removed", [])]
    missing, total = [], 0
    for ln in open(a.roster, encoding="utf-8"):
        t = re.sub(r"\*", "", ln).strip()
        if not t:
            continue
        t = re.sub(r"\((new|UC[^)]*)\)", "", t)
        parts = t.split()
        if len(parts) < 3:
            continue
        total += 1
        nm = " ".join(parts[1:-1])
        if not any(I.name_match(nm, n) for n in names if n):
            missing.append("%s %s" % (parts[0], nm))
    print("SVCCHECK: %d on the last ID list, %d in the service list, %d removed, %d missing without a removal record"
          % (total, len(sv.get("patients", [])), len(sv.get("removed", [])), len(missing)))
    for m in missing:
        print("MISSING " + m)
    if total and len(missing) * 3 > total:
        print("SVCCHECK WARN: more than a third of the list missing: incomplete app import")
    return 0


def cmd_schema(a):
    for which, name in (("feed", "IDP Feed"), ("register", "IDP Discharge Register")):
        rows = [[cell(v) for v in r] for r in schema_rows(which)]
        print("%s: %s" % (name, json.dumps({"range": "'Schema'!A1:D%d" % len(rows), "values": rows}, ensure_ascii=True)))
    print("IDP Feed Meta: " + json.dumps(meta_op(a.date), ensure_ascii=True))
    return 0


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("feed"); [p.add_argument(x) for x in ("state", "census", "ams_blocks", "cultures", "nowdir", "outdir")]; p.add_argument("--date", required=True); p.add_argument("--backlog", type=int, default=10); p.add_argument("--evolution")
    p = sp.add_parser("review"); p.add_argument("review"); p.add_argument("outdir"); p.add_argument("--date", required=True)
    p = sp.add_parser("reviewreply"); p.add_argument("replies"); p.add_argument("review"); p.add_argument("outdir"); p.add_argument("--date", required=True)
    p = sp.add_parser("op"); p.add_argument("ops"); p.add_argument("n", type=int)
    p = sp.add_parser("feedcheck"); p.add_argument("desired"); p.add_argument("nowdir"); p.add_argument("--date", required=True)
    p = sp.add_parser("final"); p.add_argument("state"); p.add_argument("index"); p.add_argument("cultures"); p.add_argument("--date", required=True)
    p = sp.add_parser("checkreg"); [p.add_argument(x) for x in ("register", "desired", "verification", "cultures", "outdir")]; p.add_argument("--date", required=True); p.add_argument("--index")
    p = sp.add_parser("backfill"); p.add_argument("state"); p.add_argument("index"); p.add_argument("tables"); p.add_argument("--date", required=True); p.add_argument("--queue", action="store_true")
    p = sp.add_parser("schema"); p.add_argument("--date", required=True)
    p = sp.add_parser("svccheck"); p.add_argument("service_list"); p.add_argument("roster")
    p = sp.add_parser("vqueue"); p.add_argument("verification"); p.add_argument("--date", required=True)
    p = sp.add_parser("vwrite"); p.add_argument("verification"); p.add_argument("replies"); p.add_argument("outdir")
    p = sp.add_parser("regjoin2"); p.add_argument("out"); p.add_argument("files", nargs="+")
    a = ap.parse_args()
    if not a.cmd:
        print(__doc__); return 0
    return {"feed": cmd_feed, "op": cmd_op, "feedcheck": cmd_feedcheck, "final": cmd_final, "checkreg": cmd_checkreg,
            "vqueue": cmd_vqueue, "vwrite": cmd_vwrite, "regjoin2": cmd_regjoin2, "backfill": cmd_backfill,
            "schema": cmd_schema, "svccheck": cmd_svccheck, "review": cmd_review, "reviewreply": cmd_reviewreply}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
