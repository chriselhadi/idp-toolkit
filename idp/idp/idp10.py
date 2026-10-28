#!/usr/bin/env python3
"""OVERLAY_10 (25.10.2026): carried synthesis, discharge register, culture watch.

  idp10.py base     <state.json|MISSING> <census.json> <register.json|MISSING> <out synth_base.py> --date YYYY-MM-DD
  idp10.py apply    <synth_base.py> <synth_delta.py> <out synth.py> --date YYYY-MM-DD
  idp10.py depart   <state_new.json> <ams_blocks.json|MISSING> <register.json|MISSING> <out dir> --date YYYY-MM-DD [--backlog 10]
  idp10.py verify   <out dir/register_rows.json> <readback.json>
  idp10.py strip    <state_new.json> <out dir/register_rows.json> --cultures out/cultures.json --date YYYY-MM-DD
  idp10.py watch    <state_new.json> <cultures.json> <register.json|MISSING> <out dir> --date YYYY-MM-DD
  idp10.py readmit  <census.json> <register.json|MISSING>
  idp10.py regjoin  <get_values Admissions json|MISSING> <get_values Late cultures json|MISSING> <out register.json>

Every command prints one final line ending in OK or FAILED.
"""
import sys, os, re, json, copy, argparse, pprint, datetime as dt

REG_HEADER = ["Key", "Status", "FELLOW", "Plan", "Plan Date", "Pt name", "MRN", "Age", "Room", "weight",
              "Creatinine", "CrCl", "Date of Admission", "Date of ID Consultation", "Chief complaint", "PMH",
              "Active Issues", "last hospitalization", "Abx history", "Imaging", "Pertinent labs",
              "Indication/ID Diagnosis", "Actual antibiotics", "Date started", "Date ended", "Released by ID",
              "Duration advice", "Attending", "Lines", "Discharge Abx", "Culture results/Notes",
              "Preliminary Results", "Organism", "Antibiogram", "notes"]           # A..AI, AMS columns 1..33 at C..AI
LATE_HEADER = ["Key", "MRN", "Name", "Added", "Collected", "Specimen", "Status", "Organism", "Antibiogram", "Result"]
WATCH_MAX_DAYS = 14
FIELDS = ("name", "one_liner", "issues", "abx_other", "micro", "micro_recap", "vitals", "pendings", "id_plan",
          "conflicts", "not_applied", "im_detail")

FOLD = {"–": "-", "—": "-", "→": "->", "←": "<-", "≤": "<=", "≥": ">=", " ": " ",
        "×": "x", "°": " deg", "⊕": "+", "⊖": "-", "’": "'", "‘": "'",
        "“": '"', "”": '"', "…": "...", "µ": "u"}
UNIT = r"(?:mg|mcg|ug|g|gr|gm|units?|iu|u|meq|mmol|ml/h)"
DOSE = re.compile(r" ?(?<![/\d.])\b\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?\s*" + UNIT + r"\b(?:\s*/\s*(?:kg|d|day|h))?", re.I)
BARE = re.compile(r"(?<![/\d.])\b\d+(?:[.,]\d+)?\s+(?=(?:proph|from|then|load|IV|PO|IM|SC|q\d+h|BID|TID|QID|OD|daily)\b)", re.I)
LAB = r"(?:Cr|CRP|PCT|K|Na|WBC|Hb|Hgb|Plt|ANC|BUN|LDH|ALT|AST|GGT|ALP|bili|INR|lactate|LA|Tmax|T|SpO2|FiO2|HR|BP|EF)"


def clean(s):
    """No doses, no en/em dashes, ASCII only (spec 0.3)."""
    if not isinstance(s, str):
        return s
    for k, v in FOLD.items():
        s = s.replace(k, v)
    s = DOSE.sub("", s)
    s = BARE.sub(lambda m: m.group(0) if re.search(LAB + r"\s*[:=]?\s*$", s[max(0, m.start() - 12):m.start()]) else "", s)
    s = re.sub(r" {3,}", " ", s)
    return s.encode("ascii", "replace").decode("ascii")


def sheet_safe(v):
    """Sheets evaluates a cell that starts with = + or @ even in a text column; a leading apostrophe keeps it text."""
    return ("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "@") else v


def jload(p):
    if not p or p.upper() == "MISSING" or not os.path.exists(p):
        return None
    txt = open(p, encoding="utf-8").read().strip()
    if not txt:
        return None
    try:
        return json.loads(txt)
    except ValueError:
        return json.loads(txt[txt.find("{"):txt.rfind("}") + 1])


def ddmm(iso):
    try:
        return dt.date.fromisoformat(iso).strftime("%d/%m/%y")
    except Exception:
        return iso or ""


def norm(s):
    s = re.sub(r"[^a-z ]", " ", (s or "").lower())
    s = s.replace("ou", "u").replace("k", "c").replace("q", "c").replace("ei", "ai")
    s = re.sub(r"(.)\1", r"\1", s)
    return " ".join(w for w in s.split() if len(w) > 1)


def name_match(a, b):
    A, B = set(norm(a).split()), set(norm(b).split())
    if not A or not B:
        return False
    return len(A & B) >= 2 or (A <= B or B <= A) and len(A & B) >= 1 and min(len(A), len(B)) >= 2


# ------------------------------------------------------------------ register read
def register_rows(reg):
    """register.json = the raw get_values JSON of 'Admissions'!A1:AI (and optionally 'late'). Returns (blocks, late)."""
    if not reg:
        return {}, []
    def vals(obj):
        if isinstance(obj, dict):
            for k in ("values", "rows"):
                if k in obj:
                    return obj[k]
            for k in ("valueRanges",):
                if k in obj:
                    return [r for vr in obj[k] for r in vr.get("values", [])]
        return obj or []
    adm = vals(reg.get("admissions", reg))
    late = vals(reg.get("late", []))
    blocks = {}
    for r in adm[1:] if adm and adm[0] and adm[0][0] == "Key" else adm:
        if not r or not r[0]:
            continue
        blocks.setdefault(r[0], []).append(r + [""] * (len(REG_HEADER) - len(r)))
    late = [r + [""] * (len(LATE_HEADER) - len(r)) for r in (late[1:] if late and late[0] and late[0][0] == "Key" else late) if r]
    return blocks, late


def find_admissions(blocks, name, mrn):
    hits = []
    for key, rows in blocks.items():
        r0 = rows[0]
        kmrn = (r0[6] or "").strip()
        if mrn and kmrn and str(mrn).strip() == kmrn:
            hits.append(key)
        elif name_match(name, r0[5]):
            hits.append(key)
    return hits


def prior_from_register(blocks, late, keys):
    """Material a readmission inherits: issues, antimicrobials and cultures of earlier admissions."""
    out = {"admissions": [], "micro_prior": [], "abx_prior": [], "issues_prior": []}
    for key in keys:
        rows = blocks[key]
        out["admissions"].append("%s (%s)" % (key.split(" | ")[-1] if " | " in key else key, rows[0][1]))
        if rows[0][16]:
            out["issues_prior"] += [x.strip() for x in re.split(r"\n|; ", rows[0][16]) if x.strip()]
        for r in rows:
            if r[22]:
                out["abx_prior"].append(" ".join(x for x in (r[22], r[23], "to " + r[24] if r[24] else "") if x).strip())
            if r[30] and r[32]:
                out["micro_prior"].append("prior adm %s %s%s" % (r[30], r[32], (" (" + r[33] + ")") if r[33] and r[33] != "-" else ""))
        for l in late:
            if l[0] == key:
                out["micro_prior"].append("prior adm %s %s %s %s" % (l[4], l[5], l[7] or l[9], ("AST " + l[8]) if l[8] else ""))
    out = {k: [clean(re.sub(r"\s+", " ", x).strip()) for x in v] for k, v in out.items()}
    return out


# ------------------------------------------------------------------ synthesis carry
def cmd_base(a):
    state = jload(a.state) or {"patients": {}}
    census = jload(a.census)
    blocks, late = register_rows(jload(a.register))
    yday = (dt.date.fromisoformat(a.date) - dt.timedelta(days=1)).strftime("%d/%m")
    base, prior, notes = {}, {}, []
    for c in census["patients"]:
        pid = c["pid"]; rec = state["patients"].get(pid) or {}
        sy = rec.get("synth") or {}
        if sy.get("issues") is not None and sy.get("one_liner"):
            e = {k: copy.deepcopy(sy.get(k)) for k in FIELDS if k in sy}
            e["name"] = c["name"]
            e.setdefault("abx_other", []); e.setdefault("micro", []); e.setdefault("pendings", [])
            e.setdefault("vitals", []); e.setdefault("id_plan", []); e.setdefault("conflicts", [])
            e.setdefault("not_applied", {}); e.setdefault("im_detail", [])
            if not e["micro"]:
                e.pop("micro_recap", None)
            e["updates"] = ["no change since %s handout" % yday]
            e["updates_nonid"] = []
            e["log_id"] = sy.get("carry", "") or ""
            e["log_im"] = ""
            base[pid] = e
        else:
            notes.append("%s %s: NEW (no carried entry), write it in full under NEW" % (pid, c["name"]))
        keys = find_admissions(blocks, c["name"], c.get("mrn") or rec.get("mrn"))
        if keys and (pid not in base or "new" in (c.get("tags") or [])):
            prior[pid] = prior_from_register(blocks, late, keys)
            notes.append("%s %s: READMISSION, %d earlier admission(s) in the register: %s"
                         % (pid, c["name"], len(keys), "; ".join(keys)))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("# synth_base.py, generated %s by idp10.py base. Do not edit: write synth_delta.py.\n" % a.date)
        f.write("BASE = " + pprint.pformat(base, width=160, sort_dicts=False) + "\n")
        f.write("PRIOR = " + pprint.pformat(prior, width=160, sort_dicts=False) + "\n")
    for n in notes:
        print(n)
    print("BASE OK: %d carried, %d new, %d readmission(s)" % (len(base), len(census["patients"]) - len(base), len(prior)))
    return 0


def _one(lst, prefix, what, pid):
    hits = [i for i, x in enumerate(lst) if (x if isinstance(x, str) else x.get("dx", "")).startswith(prefix)]
    if len(hits) != 1:
        raise ValueError("%s: %s prefix %r matches %d items" % (pid, what, prefix, len(hits)))
    return hits[0]


def _drug_slot(e, drug, pid):
    found = []
    for ii, iss in enumerate(e["issues"]):
        for j, l in enumerate(iss["abx"]):
            if l.split(" ", 1)[0] == drug:
                found.append(("issue", ii, j))
    for j, l in enumerate(e["abx_other"]):
        if l.split(" ", 1)[0] == drug:
            found.append(("other", None, j))
    if len(found) != 1:
        raise ValueError("%s: drug %r found %d times" % (pid, drug, len(found)))
    return found[0]


def apply_delta(e, d, pid):
    for k in ("updates", "updates_nonid", "one_liner", "id_plan", "vitals", "micro_recap", "conflicts",
              "not_applied", "im_detail", "log_id", "log_im"):
        if k in d:
            e[k] = d[k]
    for pre in d.get("pend_close", []):
        del e["pendings"][_one(e["pendings"], pre, "pend_close", pid)]
    for old, new in d.get("pend_set", {}).items():
        e["pendings"][_one(e["pendings"], old, "pend_set", pid)] = new
    e["pendings"] += d.get("pend_add", [])
    for old, new in d.get("micro_set", {}).items():
        e["micro"][_one(e["micro"], old, "micro_set", pid)] = new
    e["micro"] = d.get("micro_add", []) + e["micro"]
    for old, new in d.get("issue_set", {}).items():
        e["issues"][_one(e["issues"], old, "issue_set", pid)]["dx"] = new
    for pre in d.get("issue_drop", []):          # only for an issue that was never an issue (wrong patient, duplicate)
        i = _one(e["issues"], pre, "issue_drop", pid)
        if e["issues"][i]["abx"]:
            raise ValueError("%s: issue_drop %r still carries drug lines; move them first" % (pid, pre))
        del e["issues"][i]
    for iss in d.get("issue_add", []):
        e["issues"].append({"dx": iss["dx"], "abx": list(iss.get("abx", []))})
    if "issue_order" in d:
        order = [_one(e["issues"], p, "issue_order", pid) for p in d["issue_order"]]
        rest = [i for i in range(len(e["issues"])) if i not in order]
        e["issues"] = [e["issues"][i] for i in order + rest]
    for drug, line in d.get("abx_set", {}).items():
        kind, ii, j = _drug_slot(e, drug, pid)
        (e["issues"][ii]["abx"] if kind == "issue" else e["abx_other"])[j] = line
    for drug, target in d.get("abx_move", {}).items():
        kind, ii, j = _drug_slot(e, drug, pid)
        line = (e["issues"][ii]["abx"] if kind == "issue" else e["abx_other"]).pop(j)
        (e["abx_other"] if target == "abx_other" else e["issues"][_one(e["issues"], target, "abx_move", pid)]["abx"]).append(line)
    for target, lines in d.get("abx_add", {}).items():
        dest = e["abx_other"] if target == "abx_other" else e["issues"][_one(e["issues"], target, "abx_add", pid)]["abx"]
        for l in lines:
            drug = l.split(" ", 1)[0]
            try:
                _drug_slot(e, drug, pid)
                raise ValueError("%s: abx_add %r already present, use abx_set to append a segment" % (pid, drug))
            except ValueError as ex:
                if "already present" in str(ex):
                    raise
            dest.insert(0, l)
    if not e["micro"]:
        e.pop("micro_recap", None)
    return e


def cmd_apply(a):
    import importlib.util
    def load(p):
        spec = importlib.util.spec_from_file_location(os.path.basename(p)[:-3], p)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
    B, D = load(a.base), load(a.delta)
    base = copy.deepcopy(B.BASE)
    delta = getattr(D, "DELTA", {}); new = getattr(D, "NEW", {})
    errs, synth, untouched = [], {}, []
    for pid, d in delta.items():
        if pid not in base:
            errs.append("%s: in DELTA but has no carried entry (use NEW)" % pid)
    for pid in base:
        if pid in new:
            errs.append("%s: has a carried entry; use DELTA, not NEW" % pid)
    for pid, e in base.items():
        try:
            synth[pid] = apply_delta(e, delta.get(pid, {}), pid) if pid in delta else e
        except ValueError as ex:
            errs.append(str(ex))
        if pid not in delta:
            untouched.append("%s %s" % (pid, e["name"]))
    for pid, e in new.items():
        e = copy.deepcopy(e)
        e.setdefault("log_id", ""); e.setdefault("log_im", "")
        synth[pid] = e
    if errs:
        for x in errs:
            print("ERROR " + x)
        print("APPLY FAILED: %d error(s)" % len(errs)); return 1
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("# synth.py assembled %s by idp10.py apply from synth_base.py + synth_delta.py\n" % a.date)
        f.write("SYNTH = " + pprint.pformat(synth, width=160, sort_dicts=False) + "\n")
        for k in ("SIGNED_OFF", "FLAGS_EXTRA", "OBSERVATIONS", "WA"):
            f.write("%s = %s\n" % (k, pprint.pformat(getattr(D, k, {} if k in ("SIGNED_OFF", "WA") else []), width=160, sort_dicts=False)))
    for u in untouched:
        print("carried unchanged (no DELTA): " + u)
    print("APPLY OK: %d entries (%d delta, %d new, %d carried unchanged)" % (len(synth), len(delta), len(new), len(untouched)))
    return 0


# ------------------------------------------------------------------ discharge register
ABX_SPLIT = re.compile(r"^(?P<drug>\S+)(?P<rest>.*?)(?P<segs>(?:,? ?(?:x1 )?~?\d\d/\d\d-?(?:~?\d\d/\d\d)?|,? ?\?-)+)(?: \((?P<note>.*)\))?$")


def abx_row(line):
    m = ABX_SPLIT.match(line)
    if not m:
        return line, "", "", ""
    segs = re.findall(r"(x1 )?(~?\d\d/\d\d)(-?)(~?\d\d/\d\d)?|\?-", m.group("segs"))
    first = segs[0] if segs else None
    last = segs[-1] if segs else None
    start = (first[1] if first and first[1] else "?")
    if last and last[0]:
        end = last[1]
    elif last and last[3]:
        end = last[3]
    elif last and last[2] == "-":
        end = "Ongoing at discharge"
    else:
        end = "?"
    return (m.group("drug") + m.group("rest")).strip(), start, end, m.group("note") or ""


def micro_row(line):
    m = re.match(r"^(\d\d/\d\d|prior)\s+((?:[A-Z]\.\s?)?\S+(?:\s+(?:screen|cx|fluid|swab|tip))?)\s+(.*)$", line)  # OVERLAY_10b micro
    if not m:
        return "", "", line
    return m.group(1), m.group(2), m.group(3)


def rows_from_state(pid, rec, today):
    sy = rec.get("synth") or {}
    ol = [x.strip() for x in (sy.get("one_liner") or "").split(" ; ")]
    issues = sy.get("issues") or []
    abx = [(i.get("dx", "").split(" (")[0], l) for i in issues for l in i.get("abx", [])] + [("no linked issue", l) for l in sy.get("abx_other") or []]
    if not abx:
        abx = [(i, h.get("line", h.get("drug", ""))) for h in rec.get("abx_history", []) for i in [h.get("issue", "")]]
    cultures = [("micro", m) for m in sy.get("micro") or []] + [("pend", p) for p in sy.get("pendings") or []]
    n = max(1, len(abx), len(cultures))
    rows = [[""] * 33 for _ in range(n)]
    r0 = rows[0]
    r0[0] = sy.get("_fellow", ""); r0[1] = "; ".join(sy.get("id_plan") or []); r0[2] = ddmm(rec.get("last_seen"))
    r0[3] = rec.get("name", ""); r0[4] = rec.get("mrn") or ""; r0[6] = sy.get("_room", "")
    r0[11] = ddmm(rec.get("first_seen")); r0[13] = ol[0] if ol else ""
    r0[14] = "\n".join(i.get("dx", "") for i in issues); r0[15] = ol[1] if len(ol) > 1 else ""
    r0[17] = "\n".join((sy.get("vitals") or [])[1:]); r0[32] = sy.get("carry", "")
    if len(ol) > 2:
        r0[32] = (r0[32] + "\n" if r0[32] else "") + ol[2]
    for k, (ind, line) in enumerate(abx):
        drug, start, end, note = abx_row(line)
        ind = re.sub(r"\s*\((\d{1,2}/\d{1,2}\)?|prior\)|chronic\)|undated\))\s*$", "", (ind or "").split(" | ")[0].strip(" |"))  # OVERLAY_10b indication
        rows[k][19] = ind; rows[k][20] = drug; rows[k][21] = start; rows[k][22] = end
        if note:
            rows[k][24] = note
    for k, (kind, line) in enumerate(cultures):
        if kind == "micro":
            d, spec, res = micro_row(line)
            rows[k][28] = (d + " " + spec).strip(); rows[k][29] = "Preliminary" if "prelim" in res else "Final"; rows[k][30] = res; rows[k][31] = "-"
        else:
            rows[k][28] = line; rows[k][29] = "Pending at discharge"
    return rows


def rows_from_block(blk):
    rows = []
    for r in blk.get("rows", []):
        row = [""] * 33
        if isinstance(r, list):
            r = {i: v for i, v in enumerate(r)}
        for c, v in r.items():
            c = int(c)
            if 1 <= c <= 33:
                row[c - 1] = v if isinstance(v, str) else ("" if v is None else str(v))
        rows.append(row)
    return rows


def cmd_depart(a):
    state = jload(a.state); blocks_ams = jload(a.ams_blocks) or {}
    reg_blocks, _ = register_rows(jload(a.register))
    have = set(reg_blocks)
    amsb = dict(blocks_ams.get("patients") or {})
    ol = blocks_ams.get("off_list") or {}
    for k, v in (ol.items() if isinstance(ol, dict) else [(x["pid"], x["block"]) for x in ol]):
        amsb[k] = v
    today = a.date
    leaving, backlog = [], []
    recent = (dt.date.fromisoformat(today) - dt.timedelta(days=3)).isoformat()
    for pid, rec in state["patients"].items():
        if rec.get("registered") or rec.get("dup_of") or rec.get("active"):
            continue
        if (rec.get("archived_reason") or "").startswith(("ID consult in a handoff", "AS list standing therapy")):
            continue
        sent = rec.get("archive_note_sent")
        if not sent or sent >= today:
            continue      # gone for one run only: wait one more day so a false removal never reaches the register
        (leaving if sent >= recent else backlog).append(pid)
    backlog.sort(key=lambda p: state["patients"][p].get("last_seen") or "")
    chosen = leaving + backlog[:a.backlog]
    out_rows, entries = [], []
    for pid in chosen:
        rec = state["patients"][pid]
        _r0 = ((amsb.get(pid) or {}).get("rows") or [None])[0]  # OVERLAY_10b key MRN from the AMS block when the record has none
        _am = str((_r0.get(5) or _r0.get("5") or "") if isinstance(_r0, dict) else (_r0[5] if _r0 and len(_r0) > 5 else "") or "").strip()
        key = "MRN %s | %s | %s to %s" % (rec.get("mrn") or (_am if _am.isdigit() else "") or "none", pid, ddmm(rec.get("first_seen")), ddmm(rec.get("last_seen")))
        if key in have:
            print("%s already in the register as %s (marking registered)" % (pid, key))
            entries.append({"pid": pid, "key": key, "rows": 0, "already": True}); continue
        src = "AMS sheet block + ID record" if pid in amsb and amsb[pid].get("rows") else "ID record"
        rows = rows_from_block(amsb[pid]) if src.startswith("AMS") else rows_from_state(pid, rec, today)
        if src.startswith("AMS"):
            extra = rows_from_state(pid, rec, today)
            seen = {(r[20], r[21]) for r in rows} | {r[28] for r in rows}
            for r in extra:
                if (r[20] and (r[20], r[21]) not in seen) or (r[28] and r[28] not in seen):
                    rows.append([""] * 19 + r[19:])
        status = "Discharged %s" % ddmm(rec.get("last_seen")) + ("" if pid in leaving else " (registered %s)" % ddmm(today))
        for i, r in enumerate(rows):
            out_rows.append([key, status if i == 0 else ""] + [sheet_safe(clean(v if isinstance(v, str) else str(v))) for v in r])
        out_rows.append(["", "", "-" * 3] + [""] * 32)          # separator row, like the AMS sheet
        pend = [p["item"] for p in rec.get("pendings_state", [])]
        entries.append({"pid": pid, "key": key, "rows": len(rows), "source": src, "name": rec.get("name"),
                        "mrn": rec.get("mrn") or "", "discharged": rec.get("last_seen"), "pendings": pend,
                        "backlog": pid not in leaving})
        print("%s %-32s %s rows=%d (%s)%s" % (pid, (rec.get("name") or "")[:32], key, len(rows), src, " BACKLOG" if pid not in leaving else ""))
    os.makedirs(a.outdir, exist_ok=True)
    json.dump({"date": today, "entries": entries, "values": out_rows}, open(os.path.join(a.outdir, "register_rows.json"), "w"), ensure_ascii=True)
    # The write itself is done with Sheets append_values in pieces of at most 40 rows.
    chunks = [out_rows[i:i + 40] for i in range(0, len(out_rows), 40)]
    for n, ch in enumerate(chunks, 1):
        json.dump(ch, open(os.path.join(a.outdir, "register_chunk%d.json" % n), "w"), ensure_ascii=True)
    print("DEPART OK: %d recent departures, %d backlog registered (%d still waiting), %d rows in %d chunk(s)"
          % (len(leaving), len(chosen) - len(leaving), max(0, len(backlog) - a.backlog), len(out_rows), len(chunks)))
    return 0


def cmd_verify(a):
    exp = json.load(open(a.rows))["values"]
    reg_blocks, _ = register_rows(jload(a.readback))
    missing = []
    got = {}
    for r in exp:
        if r[0]:
            got.setdefault(r[0], []).append(r)
    for key, rows in got.items():
        back = reg_blocks.get(key)
        if not back or len(back) < len(rows):
            missing.append(key); continue
        for x, y in zip(rows, back[-len(rows):]):
            if [v.lstrip("'").strip() for v in x] != [v.strip() for v in y[:len(x)]]:
                missing.append(key); break
    for m in missing:
        print("MISMATCH " + m)
    print(("REGISTER MATCH: %d admission block(s)" % len(got)) if not missing else "REGISTER FAILED: %d block(s) differ" % len(missing))
    return 1 if missing else 0


def cmd_strip(a):
    state = jload(a.state); rr = json.load(open(a.rows))
    cx = jload(a.cultures) or {"specimens": []}
    watch = state.setdefault("watch", {})
    for e in rr["entries"]:
        pid = e["pid"]; rec = state["patients"].get(pid)
        if rec is None:
            continue
        if not e.get("already"):
            open_cx = list(e.get("pendings") or [])
            watch[pid] = {"name": rec.get("name"), "mrn": rec.get("mrn") or "", "aliases": rec.get("aliases", []),
                          "key": e["key"], "discharged": rec.get("last_seen"), "pendings": open_cx, "seen": [],
                          "until": (dt.date.fromisoformat(rec.get("last_seen") or a.date) + dt.timedelta(days=WATCH_MAX_DAYS)).isoformat()}
            _lo = (dt.date.fromisoformat(rec.get("first_seen") or rec.get("last_seen") or a.date) - dt.timedelta(days=5)).isoformat()
            watch[pid]["seen"] = sorted({spec_key(s) for s in patient_specimens(cx, watch[pid]) if (s.get("collected") or "") < _lo})  # OVERLAY_10b watch: every result of the stay goes to Late cultures
        del state["patients"][pid]
        print("removed %s %s from state (in the register as %s)" % (pid, rec.get("name"), e["key"]))
    json.dump(state, open(a.state, "w", encoding="utf-8"), ensure_ascii=False)
    print("STRIP OK: %d record(s) removed, %d on culture watch" % (len(rr["entries"]), len(watch)))
    return 0


def spec_key(s):
    org = ",".join(sorted((o if isinstance(o, str) else o.get("name", "")).lower() for o in s.get("organisms") or []))
    return "|".join([str(s.get("collected") or ""), re.sub(r"[^a-z]", "", (s.get("specimen") or "").lower())[:12],
                     "F" if s.get("final") else "P", org, re.sub(r"\s", "", str(s.get("ast_s") or "")),
                     re.sub(r"\s", "", str(s.get("ast_r") or ""))])


def patient_specimens(cx, w):
    return [s for s in cx.get("specimens", []) if (w["mrn"] and str(s.get("mrn") or "").strip() == w["mrn"])
            or (not s.get("mrn") and any(name_match(s.get("patient", ""), n) for n in [w["name"]] + w.get("aliases", [])))]


def cmd_watch(a):
    state = jload(a.state); cx = jload(a.cultures) or {"specimens": []}
    watch = state.get("watch") or {}
    rows, ended = [], []
    for pid, w in list(watch.items()):
        mine = patient_specimens(cx, w)
        adm = [s for s in mine if (s.get("collected") or "") <= (w["discharged"] or "9999")]
        for s in adm:
            k = spec_key(s)
            if k in w["seen"]:
                continue
            w["seen"].append(k)
            org = "; ".join(o if isinstance(o, str) else o.get("name", "") for o in s.get("organisms") or [])
            ast = " ".join(x for x in ("S: " + s["ast_s"] if s.get("ast_s") else "", "I: " + s["ast_i"] if s.get("ast_i") else "",
                                       "R: " + s["ast_r"] if s.get("ast_r") else "") if x)
            rows.append([w["key"], w["mrn"], w["name"], ddmm(a.date), ddmm(s.get("collected")), s.get("specimen", ""),
                         ("Final" if s.get("final") else "Preliminary") + (" " + ddmm(s["final_date"]) if s.get("final_date") else ""),
                         org, ast, s.get("result", "")])
        open_left = [s for s in adm if not s.get("final")]
        if (not open_left and adm) or a.date >= w["until"]:
            ended.append(pid)
            print("watch ended %s %s (%s)" % (pid, w["name"], "all admission cultures final" if not open_left and adm else "%d-day limit" % WATCH_MAX_DAYS))
            del watch[pid]
    rows = [[sheet_safe(clean(v)) for v in r] for r in rows]
    os.makedirs(a.outdir, exist_ok=True)
    json.dump({"date": a.date, "values": rows}, open(os.path.join(a.outdir, "late_rows.json"), "w"), ensure_ascii=True)
    state["watch"] = watch
    json.dump(state, open(a.state, "w", encoding="utf-8"), ensure_ascii=False)
    print("WATCH OK: %d new culture row(s), %d still watched, %d ended" % (len(rows), len(watch), len(ended)))
    return 0


def cmd_regjoin(a):
    adm, late = jload(a.adm), jload(a.late)
    out = {"admissions": adm or {"values": []}, "late": late or {"values": []}}
    json.dump(out, open(a.out, "w"), ensure_ascii=True)
    b, l = register_rows(out)
    print("REGJOIN OK: %d admission block(s), %d late culture row(s)" % (len(b), len(l)))
    return 0


def cmd_readmit(a):
    census = jload(a.census); blocks, late = register_rows(jload(a.register))
    n = 0
    for c in census["patients"]:
        keys = find_admissions(blocks, c["name"], c.get("mrn"))
        if keys:
            n += 1
            print("%s %s %s: %s" % (c["pid"], c["room"], c["name"], "; ".join(keys)))
    print("READMIT OK: %d census patient(s) with an earlier admission in the register" % n)
    return 0


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("base"); p.add_argument("state"); p.add_argument("census"); p.add_argument("register"); p.add_argument("out"); p.add_argument("--date", required=True)
    p = sp.add_parser("apply"); p.add_argument("base"); p.add_argument("delta"); p.add_argument("out"); p.add_argument("--date", required=True)
    p = sp.add_parser("depart"); p.add_argument("state"); p.add_argument("ams_blocks"); p.add_argument("register"); p.add_argument("outdir"); p.add_argument("--date", required=True); p.add_argument("--backlog", type=int, default=10)
    p = sp.add_parser("verify"); p.add_argument("rows"); p.add_argument("readback")
    p = sp.add_parser("strip"); p.add_argument("state"); p.add_argument("rows"); p.add_argument("--cultures", default="MISSING"); p.add_argument("--date", required=True)
    p = sp.add_parser("watch"); p.add_argument("state"); p.add_argument("cultures"); p.add_argument("register"); p.add_argument("outdir"); p.add_argument("--date", required=True)
    p = sp.add_parser("regjoin"); p.add_argument("adm"); p.add_argument("late"); p.add_argument("out")
    p = sp.add_parser("readmit"); p.add_argument("census"); p.add_argument("register")
    a = ap.parse_args()
    if not a.cmd:
        print(__doc__); return 2
    return {"base": cmd_base, "apply": cmd_apply, "depart": cmd_depart, "verify": cmd_verify, "strip": cmd_strip,
            "watch": cmd_watch, "readmit": cmd_readmit, "regjoin": cmd_regjoin}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
