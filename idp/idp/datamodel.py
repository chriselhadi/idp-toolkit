#!/usr/bin/env python3
"""Structured reading of the synth.py grammars (issues, abx lines, micro, pendings, status line).

The pipeline stores each fact as a short typed string (see the pipeline instructions, section 4). This module turns
those strings into records with real dates, so the dashboard, the research tables and the cross-day verification all
read the same structure. Pure functions, no I/O, no patient data.
"""
import datetime as dt
import re

ROUTES = {"IV", "PO", "IM", "SC", "INH", "NEB", "IT", "TOP"}
FREQ_RE = re.compile(r"^(OD|BID|TID|QID|q\d+h|x\d+|weekly|daily|\?)$", re.I)
DM_RE = re.compile(r"(~?)(\d{1,2})/(\d{1,2})")
SEG_RE = re.compile(r"^(x1\s+)?(~?\d{1,2}/\d{1,2}|\?)(-)?(~?\d{1,2}/\d{1,2})?$")
DOSE_RE = re.compile(r"\b\d+(\.\d+)?\s?(mg|g|mcg|µg|units?|IU|mL/h|mg/kg)\b", re.I)


def iso(d):
    return d.isoformat() if d else None


def parse_day(token, ref):
    """'03/09' or '~03/09' -> (date, approx). The year is the one that puts the date no more than 31 days after ref."""
    m = DM_RE.fullmatch(token.strip())
    if not m:
        return None, False
    approx, dd, mm = m.group(1) == "~", int(m.group(2)), int(m.group(3))
    for y in (ref.year, ref.year - 1, ref.year + 1):
        try:
            d = dt.date(y, mm, dd)
        except ValueError:
            continue
        if d <= ref + dt.timedelta(days=31) and d > ref - dt.timedelta(days=330):
            return d, approx
    return None, approx


def parse_abx(line, ref, issue=None):
    """'Piptazo IV q6h 29/08-02/09, 04/09- (note)' -> course record with segments and the day count."""
    raw = line.strip()
    note = ""
    m = re.search(r"\s*\(([^()]*)\)\s*$", raw)
    if m:
        note, raw = m.group(1), raw[:m.start()]
    toks = raw.split()
    rec = {"line": line.strip(), "drug": toks[0] if toks else "", "route": "", "freq": "", "segments": [],
           "note": note, "issue": issue, "running": False, "days": 0, "start": None, "stop": None,
           "start_approx": False, "parse_ok": True}
    i = 1
    if i < len(toks) and toks[i].upper() in ROUTES:
        rec["route"] = toks[i].upper(); i += 1
    if i < len(toks) and FREQ_RE.match(toks[i]):
        rec["freq"] = toks[i]; i += 1
    rest = " ".join(toks[i:])
    for seg in [s.strip() for s in rest.split(",") if s.strip()]:
        sm = SEG_RE.match(seg)
        if not sm:
            rec["parse_ok"] = False
            continue
        single, a, dash, b = sm.group(1), sm.group(2), sm.group(3), sm.group(4)
        s_date, s_approx = (None, False) if a == "?" else parse_day(a, ref)
        if single or (not dash and not b):            # x1 03/09 or a bare date: one dose
            e_date, e_approx, is_open = s_date, s_approx, False
        elif dash and not b:                            # 03/09- running
            e_date, e_approx, is_open = None, False, True
        else:
            e_date, e_approx = parse_day(b, ref)
            is_open = False
        days = 0
        if s_date:
            end = e_date or ref
            days = max(0, (end - s_date).days + 1)
        rec["segments"].append({"start": iso(s_date), "start_approx": s_approx, "end": iso(e_date),
                                "end_approx": e_approx, "open": is_open, "single": bool(single) or (not dash and not b),
                                "days": days})
    if rec["segments"]:
        rec["running"] = rec["segments"][-1]["open"]
        rec["days"] = sum(s["days"] for s in rec["segments"])
        rec["start"] = rec["segments"][0]["start"]
        rec["start_approx"] = rec["segments"][0]["start_approx"]
        rec["stop"] = None if rec["running"] else rec["segments"][-1]["end"]
    else:
        rec["parse_ok"] = False
    return rec


def parse_issue(text, ref):
    parts = [p.strip() for p in text.split("|")]
    head = parts[0]
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", head)
    dx, when = (m.group(1), m.group(2)) if m else (head, "")
    d, _ = parse_day(when, ref) if DM_RE.fullmatch(when or "x") else (None, False)
    return {"dx": dx, "onset": iso(d), "onset_text": when, "facts": parts[1] if len(parts) > 1 else "",
            "status": parts[2] if len(parts) > 2 else "", "text": text}


MICRO_STATUS = [
    ("pending", re.compile(r"\bpend", re.I)),
    ("prelim", re.compile(r"\bprelim|\bGram\b|\bflagged\b|\bID pending|\bAST pending", re.I)),
    ("negative", re.compile(r"\bneg\b|\bnegative\b|no growth|\bNG\b|sterile|normal flora|commensal", re.I)),
]


def parse_micro(text, ref):
    toks = text.split(None, 2)
    rec = {"text": text, "date": None, "prior": False, "specimen": "", "result": "", "status": "positive",
           "verify": "(?)" in text or "to verify" in text}
    if not toks:
        return rec
    if toks[0].lower() == "prior":
        rec["prior"] = True
    else:
        d, _ = parse_day(toks[0], ref)
        rec["date"] = iso(d)
    rec["specimen"] = toks[1] if len(toks) > 1 else ""
    rec["result"] = toks[2] if len(toks) > 2 else ""
    for status, rx in MICRO_STATUS:
        if rx.search(rec["result"]):
            rec["status"] = status
            break
    return rec


def parse_pending(text, ref):
    m = re.match(r"^(.*?)\s*\((~?\d{1,2}/\d{1,2})\)\s*(?:->\s*(.*))?$", text.strip())
    if not m:
        return {"text": text, "item": text.strip(), "since": None, "gate": "", "age_days": None}
    d, _ = parse_day(m.group(2), ref)
    return {"text": text, "item": m.group(1), "since": iso(d), "gate": m.group(3) or "",
            "age_days": (ref - d).days if d else None}


def parse_status(text):
    parts = [p.strip() for p in (text or "").split("|")]
    while len(parts) < 3:
        parts.append("")
    return {"fever": parts[0], "pressors": parts[1], "resp": parts[2], "text": text or ""}


def patient_record(pid, rec, ref):
    """One state patient (state_new.json 'patients' value) -> the structured record the dashboard shows."""
    s = rec.get("synth") or {}
    issues, courses = [], []
    for it in s.get("issues") or []:
        i = parse_issue(it.get("dx", ""), ref)
        i["abx"] = [parse_abx(a, ref, issue=i["dx"]) for a in it.get("abx") or []]
        courses += i["abx"]
        issues.append(i)
    other = [parse_abx(a, ref, issue=None) for a in s.get("abx_other") or []]
    courses += other
    vitals = s.get("vitals") or []
    return {
        "pid": pid, "mrn": rec.get("mrn", ""), "name": s.get("name") or rec.get("name", ""),
        "aliases": rec.get("aliases") or [], "active": bool(rec.get("active")),
        "first_seen": rec.get("first_seen"), "last_seen": rec.get("last_seen"),
        "archived": rec.get("archived"), "archived_reason": rec.get("archived_reason", ""),
        "room": s.get("_room", ""), "group": s.get("_group", ""), "fellow": s.get("_fellow", ""),
        "tags": s.get("_tags") or [], "one_liner": s.get("one_liner", ""),
        "updates": s.get("updates") or [], "updates_nonid": s.get("updates_nonid") or [],
        "issues": issues, "abx_other": other, "courses": courses,
        "micro": [parse_micro(m, ref) for m in s.get("micro") or []], "micro_recap": s.get("micro_recap", ""),
        "status": parse_status(vitals[0] if vitals else ""), "imaging": vitals[1:],
        "pendings": [parse_pending(p, ref) for p in s.get("pendings") or []],
        "conflicts": s.get("conflicts") or [], "not_applied": s.get("not_applied") or {},
        "im_detail": s.get("im_detail") or [],
    }
