#!/usr/bin/env python3
"""Mechanical pass: membership, identity (pid), room resolution, AMS audit, AS delta, packets.

Usage: match.py <state.json|MISSING> <as_today.json|MISSING> <wards.json|MISSING> <ams.json|MISSING> <outdir>
                --date DD.MM.YYYY [--roster roster.txt] [--as-yday as_yday.json]
Writes outdir/census.json, delta.json, flags.txt, packets.txt, pending_check.txt. Prints counts only.
"""
import sys, os, re, json, argparse, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import (WARD_ORDER, parse_bed, room_key, norm_name, name_tokens, name_sim, parse_date, ddmm, jload, jdump)


def load_opt(p):
    if not p or p.upper() == "MISSING" or not os.path.exists(p):
        return None
    return jload(p)


def parse_roster(path):
    """Lines '<Room> <Name> [(new)|(UC)] <Initials>' -> list of dicts. Tolerates missing initials."""
    out = []
    for raw in open(path, encoding="utf-8"):
        line = raw.strip().replace("*", "").strip()
        if not line or len(line) < 4:
            continue
        m = re.match(r"^(\S+)\s+(.+?)\s*$", line)
        if not m:
            continue
        room_tok, rest = m.group(1), m.group(2)
        if room_tok.upper() == "ER" and re.match(r"^IN\s+", rest):  # OVERLAY_6 4j: 'ER IN <name>'
            rest = re.sub(r"^IN\s+", "", rest)
        tags = [t.lower() for t in re.findall(r"\(([^)]+)\)", rest)]
        rest = re.sub(r"\([^)]*\)", " ", rest).strip()
        fellow = ""
        mm = re.match(r"^(.*?)[\s,]+([A-Z]{2,3})$", rest)
        if mm and mm.group(1).strip():
            rest, fellow = mm.group(1).strip(), mm.group(2)
        room, grp, _ = parse_bed(room_tok)
        rest = re.sub(r"\s+\?+$", "", rest).strip()
        if grp == "Other" and not re.search(r"\d", room_tok) and not re.match(r"^(CCU|CSU|ER|NICU|PICU|SCT)", room_tok, re.I) and room_tok != "?":  # OVERLAY_6 4s
            continue  # a heading line, not a patient
        out.append({"room": room, "group": grp, "name": rest.strip(" -:"), "tags": tags, "fellow": fellow, "raw": line})
    return out


class Registry:
    def __init__(self, state):
        self.p = state["patients"]
        self.next = state.get("next_pid", 1)
        self.flags = []

    def find(self, name, mrn=None):
        nn = norm_name(name)
        if mrn:
            for pid, rec in self.p.items():
                if rec.get("mrn") and rec["mrn"] == mrn:
                    return pid, "mrn"
        for pid, rec in self.p.items():
            if nn and nn in [norm_name(a) for a in [rec["name"]] + rec.get("aliases", [])]:
                return pid, "name"
        toks = name_tokens(name)
        best, score = None, 0.0
        for pid, rec in self.p.items():
                  toks = name_tokens(name)
        best, score = None, 0.0
        for pid, rec in self.p.items():
            if mrn and rec.get("mrn") and rec["mrn"] != mrn:
                continue  # a different stored MRN vetoes a fuzzy name match
            for a in [rec["name"]] + rec.get("aliases", []):
                j = name_sim(name, a)
                if j > score:
                    best, score = pid, j
        self.last_score = score  # OVERLAY_6 4o
        if best and score >= 0.5 and len(toks) >= 2:
            self.flags.append("close match: '%s' -> %s (%s), jaccard %.2f: accepted, check" % (name, best, self.p[best]["name"], score))
            return best, "close"
        return None, None

    def add(self, name, mrn, today):
        pid = "P%04d" % self.next; self.next += 1
        self.p[pid] = {"name": name, "aliases": [], "mrn": mrn or "", "first_seen": today, "last_seen": today,
                       "active": True, "archived": None, "archived_reason": "", "synth": {}, "abx_history": [],
                       "pendings_state": []}
        return pid

    def alias(self, pid, name, mrn=None):
        rec = self.p[pid]
        if name and norm_name(name) not in [norm_name(a) for a in [rec["name"]] + rec["aliases"]]:
            rec["aliases"].append(name)
        if mrn and not rec.get("mrn"):
            rec["mrn"] = mrn


def row_is_fresh(row, today, days=4):
    """True when the newest dd/mm date in a handoff row is within `days` of today."""
    t0 = dt.date.fromisoformat(today); best = None
    txt = (row.get("text") or "") + " " + " ".join(row.get("dated_lines") or [])
    for d, m in re.findall(r"\b(\d{1,2})[./](\d{1,2})\b", txt):
        try:
            x = dt.date(t0.year, int(m), int(d))
        except ValueError:
            continue
        if x > t0 + dt.timedelta(days=2):
            continue
        best = x if best is None or x > best else best
    return best is not None and (t0 - best).days <= days


def ward_lookup(wards, name, room):
    """Find ward rows for a patient; owning doc wins over cardio/neuro duplicates."""
    if not wards:
        return []
    hits = []
    for row in wards:
        j = name_sim(name, row.get("name", ""))
        if j >= 0.5 or (row.get("room") and room and row["room"].upper() == room.upper() and j >= 0.34):
            hits.append((j, row))
              # Once one row's room confirms the patient's room, distrust rows that contradict it:
    # a fuzzy name match alone has attached other patients' rows (a 707A cardiology row
    # onto an ICU6B patient). Rows with no room recorded are still kept.
    if room:
        ru = room.upper()
        if any(h[1].get("room") and h[1]["room"].upper() == ru for h in hits):
            hits = [h for h in hits if not (h[1].get("room") and h[1]["room"].upper() not in (ru, "?"))]
    # A second-doc row (cardio/neuro) with no room to confirm it and a different admission date
    # from the owning floors/ICU row is another patient with a similar name (27.09.2026: a
    # cardiology bigeminy row, DOA 26/09, attached to a 709B patient admitted 24/09). Near-exact
    # names (>= 0.8) are kept.
    own_doa = {h[1]["doa"] for h in hits if h[1].get("doc") in ("floors", "icu") and h[1].get("doa")}
    if own_doa:
        ru = (room or "").upper()
        hits = [h for h in hits if h[1].get("doc") in ("floors", "icu") or h[0] >= 0.8
                or not h[1].get("doa") or h[1]["doa"] in own_doa
                or (ru and (h[1].get("room") or "").upper() == ru)]
    hits.sort(key=lambda h: (-(h[1].get("doc") in ("floors", "icu")), -h[0]))
    return [h[1] for h in hits]


def ams_lookup(ams, name, mrn, today):
    if not ams:
        return None, "absent"
    toks = name_tokens(name)
    best, score = None, 0.0
    for b in ams:
        if mrn and b.get("mrn") and b["mrn"] == mrn:
            best, score = b, 1.0; break
        j = name_sim(name, b.get("name", ""))
        if j > score:
            best, score = b, j
    if not best or score < 0.5:
        return None, "absent"
    ld = best.get("last_date")
    stale = "stale" if (ld and (dt.date.fromisoformat(today) - dt.date.fromisoformat(ld)).days > 3) else "present"
    return best, stale


def missed_dates(yday, today):
    """Calendar days strictly between the two list dates: the days that had no AS list.

    The baseline is the LAST AS LIST ACTUALLY CONSUMED (state as_snapshot), not the
    calendar's yesterday. When a day had no list the snapshot is not advanced, so the next
    list is compared with the day before, or the day before that, however many were
    missed in a row. The report names those days so nobody reads a two-day delta as one.
    """
    try:
        a, b = dt.date.fromisoformat(yday), dt.date.fromisoformat(today)
    except (TypeError, ValueError):
        return []
    return [(a + dt.timedelta(days=i)).isoformat() for i in range(1, (b - a).days)]


def delta_baseline(state, last_delta_sent):
    """The AS list the delta is taken against.

    Default: the last list consumed (as_snapshot). If the caller says which day's delta
    report was last actually sent, use the newest stored list dated on or before that day,
    so that a day whose delta never went out (no list, or a run that died before the send)
    is folded into today's report. as_history holds the last few lists for this.
    """
    snap = state.get("as_snapshot")
    if not last_delta_sent:
        return snap
    try:
        sent = parse_date(last_delta_sent)
    except Exception:
        return snap
    cands = [h for h in (state.get("as_history") or []) if (h.get("list_date") or "9999") <= sent]
    if snap and (snap.get("list_date") or "9999") <= sent:
        cands.append(snap)
    if not cands:
        return snap
    return max(cands, key=lambda h: h.get("list_date") or "")


def compute_delta(as_today, as_yday):
    if not as_today or not as_yday:
        return {"computed": False, "reason": "missing today" if not as_today else "no earlier AS list in state"}
    Y = {p["mrn"]: p for p in as_yday["patients"]}
    T = {p["mrn"]: p for p in as_today["patients"]}
    new = [T[m] for m in T if m not in Y and not T[m].get("once_only")]
    off = [Y[m] for m in Y if m not in T and not Y[m].get("once_only")]
    changes = []
    for m in T:
        if m in Y:
            a, b = set(Y[m].get("standing_drugs", [])), set(T[m].get("standing_drugs", []))
            started, stopped = sorted(b - a), sorted(a - b)
            moved = (Y[m].get("room"), T[m].get("room")) if Y[m].get("room") != T[m].get("room") else None
            if started or stopped or moved:
                changes.append({"mrn": m, "name": T[m]["name"], "room": T[m]["room"], "started": started,
                                "stopped": stopped, "moved": moved})
    return {"computed": True, "yday_date": as_yday.get("list_date"), "today_date": as_today.get("list_date"),
            "missed_dates": missed_dates(as_yday.get("list_date"), as_today.get("list_date")),
            "new": [{"mrn": p["mrn"], "name": p["name"], "room": p["room"], "drugs": p["standing_drugs"]} for p in new],
            "off": [{"mrn": p["mrn"], "name": p["name"], "room": p["room"], "drugs": p.get("standing_drugs", [])} for p in off],
            "changes": changes,
            "counts": {"today": len([p for p in T.values() if not p.get("once_only")]),
                       "yday": len([p for p in Y.values() if not p.get("once_only")]),
                       "new": len(new), "off": len(off), "changed": len(changes)}}


# Orphan guard thresholds. Six genuine orphans out of 27 is a normal morning here, so a
# flat count is useless. What signalled the 08.09.2026 parser fault was the JUMP: orphans
# went 6 -> 11 and ward rows fell 76 -> 62 between two runs of the same four documents.
ORPHAN_FRACTION = 0.40   # absolute ceiling: this many orphans is not a records failure
ORPHAN_JUMP = 4          # rise in orphan count vs the previous run
WARDROW_DROP = 0.15      # fractional fall in parsed ward rows vs the previous run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state"); ap.add_argument("as_today"); ap.add_argument("wards"); ap.add_argument("ams"); ap.add_argument("out")
    ap.add_argument("--date", required=True); ap.add_argument("--roster"); ap.add_argument("--allow-orphans", action="store_true",
                    help="proceed past the orphan guard once the ward parse is confirmed sound")
    ap.add_argument("--as-yday")
    ap.add_argument("--orphans-confirmed", help="file, one name per line: orphans confirmed absent from every ward doc")  # OVERLAY_6 4q
    ap.add_argument("--last-delta-sent", help="DD.MM.YYYY from the subject of the newest 'AS List Delta Report' already "
                    "in Gmail; the delta baseline becomes the newest stored AS list on or before that date")
    a = ap.parse_args()
    today = parse_date(a.date)
    os.makedirs(a.out, exist_ok=True)
    state = load_opt(a.state)
    cold = state is None
    if cold:
        state = {"version": 2, "date": None, "next_pid": 1, "patients": {}, "as_snapshot": None, "observations": [], "roster_last": None}
    as_today = load_opt(a.as_today); wards = load_opt(a.wards); ams = load_opt(a.ams)
    as_yday = load_opt(a.as_yday) or delta_baseline(state, a.last_delta_sent)
    roster = parse_roster(a.roster) if a.roster and os.path.exists(a.roster) else None
    reg = Registry(state)
    flags = list(reg.flags)
    if cold:
        flags.append("state rebuilt cold: no prior state found; every patient renders NEW to roster, no baseline")

    census = {}   # pid -> record
    archived_today = []

    def touch(pid, name, mrn, room, grp, prov, fellow="", tags=None):
        rec = census.setdefault(pid, {"pid": pid, "name": reg.p[pid]["name"], "mrn": reg.p[pid].get("mrn", ""), "room": None,
                                       "group": None, "room_source": None, "fellow": "", "tags": [], "provenance": [],
                                       "as_orders": [], "as_standing": [], "as_once_only": False, "new": reg.p[pid]["first_seen"] == today,
                                       "orphan": False})
        reg.alias(pid, name, mrn)
        if mrn and not rec["mrn"]:
            rec["mrn"] = mrn
        if prov not in rec["provenance"]:
            rec["provenance"].append(prov)
        if room and room != "?" and (rec["room"] in (None, "?") or PRIORITY[prov] < PRIORITY[rec["room_source"]]):
            rec["room"], rec["group"], rec["room_source"] = room, grp, prov
        if fellow:
            rec["fellow"] = fellow
        for t in (tags or []):
            if t not in rec["tags"]:
                rec["tags"].append(t)
        reg.p[pid]["last_seen"] = today
        reg.p[pid]["active"] = True
        return rec

    PRIORITY = {"as": 0, "roster": 1, "ward": 2, "prior": 3, None: 9}

    # 1. Membership: roster (if sent) is the service; else yesterday's actives carry forward.
    if roster:
        for r in roster:
            pid, how = reg.find(r["name"])
            if not pid:
                pid = reg.add(r["name"], None, today)
            touch(pid, r["name"], None, r["room"], r["group"], "roster", r["fellow"], r["tags"] + (["new"] if "new" in r["tags"] else []))
        on_list = set(census)
        for pid, rec in reg.p.items():
            if rec.get("active") and pid not in on_list and rec.get("last_seen") != today:
                rec["active"] = False; rec["archived"] = today; rec["archived_reason"] = "not on today's ID Active Patients list"
                archived_today.append("%s (%s)" % (rec["name"], pid))
        state["roster_last"] = {"date": today, "lines": [r["raw"] for r in roster]}
    else:
        for pid, rec in reg.p.items():
            if rec.get("active"):
                prev = rec.get("synth", {})
                touch(pid, rec["name"], rec.get("mrn"), prev.get("_room"), prev.get("_group"), "prior", prev.get("_fellow", ""), prev.get("_tags", []))
        if not cold:
            flags.append("no ID Active Patients email today: yesterday's list carried forward as today's list (%d patients)" % len(census))

    # 2. AS list: rooms first; new names enter as new consults (standing therapy or ward-doc match); ONCE-only names are shots.
    single_dose = []
    Y_MRNS = {q.get("mrn") for q in ((as_yday or {}).get("patients") or [])}
    if as_today:
        for p in as_today["patients"]:
            pid, how = reg.find(p["name"], p["mrn"])
            newly = bool(Y_MRNS) and bool(p.get("mrn")) and p["mrn"] not in Y_MRNS
            if newly and not p.get("once_only"):  # OVERLAY_R
                if not pid:
                    pid = reg.add(p["name"], p["mrn"], today)
                else:
                    reg.p[pid]["archived"] = None; reg.p[pid]["archived_reason"] = ""
                flags.append("new on today's AS list, added (%s)" % pid)
            elif not pid and "paeds" in p.get("flags", []):
                continue  # paeds never enter the adult census from the AS list; listed in the Delta Report instead
            if not pid:
                if p.get("once_only"):  # OVERLAY_R: once-only never enters, ward row or not
                    single_dose.append("%s %s: %s" % (p["room"], p["name"], ", ".join(p["drugs"])))
                    continue
                if not p.get("once_only") or ward_lookup(wards, p["name"], p["room"]):
                    pid = reg.add(p["name"], p["mrn"], today)
                else:
                    continue
            elif not reg.p[pid].get("active") and roster and not newly:
                continue  # came off Chris's list today: the AS list does not put them back
            rec = touch(pid, p["name"], p["mrn"], p["room"], p["group"], "as", "", ["paeds"] if "paeds" in p.get("flags", []) else [])
            rec["as_orders"] = p["orders"]; rec["as_standing"] = p["standing_drugs"]; rec["as_once_only"] = p.get("once_only", False)
            rec["as_age"] = p.get("age"); rec["as_admission"] = p.get("admission_date"); rec["as_crcl"] = p.get("crcl")
    else:
        flags.append("no AS list parsed today: rooms from roster > ward doc > prior state")

    # 2b. Handoff rows marked Cs ID / UC ID (Chris, 28.09.2026): a new name enters as a new
    # consult; a name that came off the ID list is listed once in cs_id_offlist.
    cs_offlist = []
    for row in (wards or []):
        if not (row.get("id_consult") or row.get("uc_id")):
            continue
        if not row_is_fresh(row, today):
            continue  # handoff docs keep old rows for weeks; only rows touched in the last 4 days count
        nm = (row.get("name") or "").strip()
        if len(nm) < 5 or re.search(r"patient x|template", nm, re.I):
            continue
        rr = parse_bed(row["room"])[0] if row.get("room") and row["room"] != "?" else None
        if any(ward_lookup([row], c["name"], c["room"]) and (not rr or not c.get("room") or c["room"] in ("?", rr))
               for c in census.values()):
            continue
        same = [c for c in census.values() if len(name_tokens(nm)) >= 2 and name_sim(nm, c["name"]) >= 0.5]
        if same:
            if rr and same[0].get("room") not in (None, "?", rr):
                flags.append("handoff doc room %s differs from today's list room %s for %s; kept today's room" % (rr, same[0].get("room"), same[0]["pid"]))
            continue
        pid, how = reg.find(nm)
        if pid and how == "close" and rr:
            cur = (census.get(pid) or {}).get("room") or (reg.p[pid].get("synth") or {}).get("_room")
            if cur and cur != "?" and rr != cur and reg.p[pid].get("archived") != today:
                if getattr(reg, "last_score", 0) >= 0.66:  # OVERLAY_6 4o: near-identical name, other room: same patient
                    flags.append("CONFLICT room: %s handoff says %s, %s (%s) is in %s; one record kept" % (
                        row.get("doc"), rr, pid, reg.p[pid]["name"], cur))
                else:
                    pid = None  # fuzzy name hit in another room: a different patient (not one who left the list today)
        if pid and pid in census:
            continue
        if pid and reg.p[pid].get("archived"):
            if not any(o["pid"] == pid for o in cs_offlist):
                prev0 = reg.p[pid].get("synth") or {}
                cs_offlist.append({"pid": pid, "name": reg.p[pid]["name"], "room": row.get("room") or prev0.get("_room") or "?",
                                   "doc": row.get("doc"), "archived": reg.p[pid].get("archived"), "row": row})
            continue
        if not pid:
            pid = reg.add(nm, None, today)
        rec0 = reg.p[pid]
        rec0["active"] = False; rec0["archived"] = rec0.get("archived") or today
        rec0["archived_reason"] = rec0.get("archived_reason") or "ID consult in a handoff, not on the ID Active Patients list"
        if not any(o["pid"] == pid for o in cs_offlist):
            cs_offlist.append({"pid": pid, "name": rec0["name"], "room": row.get("room") or "?",
                               "doc": row.get("doc"), "archived": rec0["archived"], "row": row})
        flags.append("ID consult in the %s handoff, not on the ID list: listed off-list only (%s)" % (row.get("doc"), pid))

    # 3. Ward rows enrich; AMS enriches and audits.
    for pid, rec in census.items():
        rows = ward_lookup(wards, rec["name"], rec["room"])
        rec["ward_rows"] = rows
        if rows[:1] and rows[0].get("uc_id") and "uc" not in rec["tags"]:
            rec["tags"].append("uc")
        if any(t.startswith("uc") for t in rec["tags"]) and "uc" not in rec["tags"]:
            rec["tags"].append("uc")
        if rows and (not rec["room"] or rec["room"] in ("?", "ER")):  # OVERLAY_6 4d: AS > ward row room > ward section
            r0 = next((x for x in rows if x.get("room") and x["room"] != "?"), rows[0])
            if r0.get("room") and r0["room"] != "?":
                room, grp, _ = parse_bed(r0["room"]); rec["room"], rec["group"], rec["room_source"] = room, grp, "ward"
            else:
                sec = (r0.get("section") or "").upper()
                for unit in ("NICU", "PICU", "CCU", "CSU"):
                    if unit in sec:
                        room, grp, _ = parse_bed(unit); rec["room"], rec["group"], rec["room_source"] = room, grp, "ward section"
                        break
        rec["orphan"] = not rows
        blk, status = ams_lookup(ams, rec["name"], rec["mrn"], today)
        rec["ams_status"] = status; rec["ams_block"] = blk
        rec["ams_fellow"] = (blk or {}).get("fellow", "")
        if not rec["room"]:
            rec["room"], rec["group"], rec["room_source"] = "?", "Other", None
            flags.append("no room for %s (%s) from any source" % (rec["name"], pid))
        if rec["room"] in ("?", "ER"):  # OVERLAY_6 4d
            flags.append("ROOM UNRESOLVED: %s (%s) room %s; list it in the closing note" % (rec["name"], pid, rec["room"]))
        if rec.get("as_standing") and not rec["fellow"] and not rec["ams_fellow"]:
            rec["no_fellow"] = True
        # carry display fields into the registry so tomorrow's no-list day still has room/fellow/tags
        s = reg.p[pid].setdefault("synth", {})
        s["_room"], s["_group"], s["_fellow"], s["_tags"] = rec["room"], rec["group"], rec["fellow"], rec["tags"]

    # 4. Pending continuity check (non-blocking).
    pend_lines = []
    for pid, rec in census.items():
        for pd in reg.p[pid].get("pendings_state", []):
            age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(pd["since"])).days if pd.get("since") else None
            pend_lines.append("%s %s: '%s' since %s (d%s) -> must resolve to micro, persist, or close with a stated reason" % (
                rec["room"], rec["name"], pd["item"], ddmm(pd.get("since")), age))

    # 5. Delta.
    delta = compute_delta(as_today, as_yday)
    if as_today and not delta["computed"]:
        flags.append("delta_computed=False: %s" % delta["reason"])

    # 6. Order and write.
    def okey(r):
        g = r["group"] if r["group"] in WARD_ORDER else "Other"
        return (WARD_ORDER.index(g), room_key(r["room"]))
    ordered = sorted(census.values(), key=okey)
    for r in ordered:
        r.pop("ward_rows_full", None)
    out_census = {"date": today, "cold": cold, "roster_sent": bool(roster), "list_date": (as_today or {}).get("list_date"),
                  "patients": [{k: v for k, v in r.items() if k not in ("ward_rows", "ams_block")} for r in ordered],
                  "archived_today": archived_today, "single_dose": single_dose,
                  "paeds": [r["name"] + " " + r["room"] for r in ordered if "paeds" in r["tags"]] + [
                      "%s %s (AS list, not on census)" % (p["room"], p["name"]) for p in (as_today or {}).get("patients", [])
                      if "paeds" in p.get("flags", []) and not any(c["mrn"] == p["mrn"] for c in ordered)],
                  "no_fellow": [r["name"] + " " + r["room"] for r in ordered if r.get("no_fellow")],
                  "ams_summary": {k: [r["name"] for r in ordered if r["ams_status"] == k] for k in ("present", "stale", "absent")}}
    jdump(out_census, os.path.join(a.out, "census.json"))
    # Rule E (Chris, 07.09.2026): "new to service" = on today's AS list and not yesterday's
    # AND no row in any ward handoff doc, OR named (new) on today's roster. Written here so
    # render_delta.py and the handout shading never depend on a hand-made list.
    delta_new = {p["mrn"] for p in delta.get("new", [])} if delta.get("computed") else set()
    new_mrns = sorted({r["mrn"] for r in ordered if r.get("mrn") and (
        (r["mrn"] in delta_new and r["orphan"]) or "new" in r["tags"])})
    jdump(new_mrns, os.path.join(a.out, "new_mrns.json"))
    # census "new" follows the same rule, so the handout shades exactly the rule-E patients.
    for r in ordered:
        r["new"] = bool(r.get("mrn") in new_mrns) if new_mrns or delta.get("computed") else r["new"]
    for r in ordered:  # OVERLAY_6 4c/4l: (new) only on the first day, unless today's email says (new); re-cs is never (new)
        if "re-cs" in r["tags"]:
            r["new"] = False
        elif (reg.p[r["pid"]].get("first_seen") or today) < today and "new" not in r["tags"]:
            r["new"] = False
    out_census["patients"] = [{k: v for k, v in r.items() if k not in ("ward_rows", "ams_block")} for r in ordered]
    out_census["cs_id_offlist"] = [{k: v for k, v in o.items() if k != "row"} for o in cs_offlist]
    jdump(out_census, os.path.join(a.out, "census.json"))
    jdump(delta, os.path.join(a.out, "delta.json"))
    jdump({r["pid"]: r["ward_rows"] for r in ordered}, os.path.join(a.out, "ward_rows.json"))
    state["next_pid"] = reg.next
    state["_census_pids"] = [r["pid"] for r in ordered]
    orphans = [r for r in ordered if r["orphan"]]
    nrows = len(wards) if wards else 0
    prev_stats = dict(state.get("run_stats") or {})   # keep the PREVIOUS run for the guard
    state["run_stats"] = {"orphans": len(orphans), "ward_rows": nrows, "census": len(ordered)}
    jdump(state, os.path.join(a.out, "state_matched.json"))
    flags += reg.flags[len(flags) and 0:]  # registry flags gathered during matching
    seen = set(); fl = [f for f in flags if not (f in seen or seen.add(f))]
    open(os.path.join(a.out, "flags.txt"), "w", encoding="utf-8").write("\n".join(fl) + ("\n" if fl else ""))
    open(os.path.join(a.out, "pending_check.txt"), "w", encoding="utf-8").write("\n".join(pend_lines) + ("\n" if pend_lines else ""))

    # 7. Packets: the only patient text the synthesiser reads.
    L = []
    for r in ordered:
        prev = reg.p[r["pid"]].get("synth", {})
        hdr = "=== %s | %s | %s | fellow:%s | tags:%s | %s | %s | prov:%s | AS:%s | AMS:%s" % (
            r["pid"], r["room"], r["name"], r["fellow"] or r.get("ams_fellow", "") or "?", ",".join(r["tags"]) or "-",
            "NEW" if r["new"] else "known", "ORPHAN(no ward row)" if r["orphan"] else "ward row",
            ">".join(r["provenance"]), "; ".join("%s %s %s" % (o["drug"], o["freq"], "~" + ddmm(o["valid_from"])) for o in r["as_orders"]) or "-",
            r["ams_status"])
        L.append(hdr)
        if r.get("as_age"):
            L.append("AS: age %s, admitted %s, CrCl %s" % (r.get("as_age"), ddmm(r.get("as_admission")), (r.get("as_crcl") or "?")[:12]))
        for row in r["ward_rows"][:2]:
            L.append("--- ward doc %s | room %s | DOA %s | UC %s | consults %s" % (row.get("doc"), row.get("room"), row.get("doa") or "?", row.get("uc") or "?", ", ".join(row.get("consults", [])) or "-"))
            for cell in ("HDR", "ACTIVE", "ABX", "MEDS", "PENDINGS", "SYNTHESIS", "OTHER"):
                if row.get("cells", {}).get(cell):
                    L.append("[%s] %s" % (cell, row["cells"][cell]))
            if not row.get("cells"):
                L.append("[TEXT] " + (row.get("text") or ""))
        if r["orphan"] and r.get("ams_block"):
            L.append("--- AMS archive (deep text, not current): " + (r["ams_block"].get("text") or "")[:3000])
        if prev.get("one_liner"):
            L.append("--- yesterday: " + prev["one_liner"])
            for i in prev.get("issues", []):
                L.append("  issue: %s | abx: %s" % (i.get("dx"), "; ".join(i.get("abx", []))))
            if prev.get("abx_other"): L.append("  abx_other: " + "; ".join(prev["abx_other"]))
            if prev.get("micro"): L.append("  micro: " + " || ".join(prev["micro"]))
            if prev.get("vitals"): L.append("  vitals: " + " || ".join(prev["vitals"]))
            if prev.get("pendings"): L.append("  pendings: " + " || ".join(prev["pendings"]))
            if prev.get("log_im"): L.append("  log_im: " + prev["log_im"])
            if prev.get("log_id"): L.append("  log_id: " + prev["log_id"])
        L.append("")
    for o in cs_offlist:
        L.append("=== OFFLIST %s | %s | %s | off the ID list since %s | still ID consulted or UC ID in the %s doc -> SIGNED_OFF one-liner only"
                 % (o["pid"], o["room"], o["name"], o.get("archived"), o.get("doc")))
        for cell in ("HDR", "ACTIVE", "ABX", "PENDINGS", "SYNTHESIS"):
            if o["row"].get("cells", {}).get(cell):
                L.append("[%s] %s" % (cell, o["row"]["cells"][cell]))
        prev0 = reg.p[o["pid"]].get("synth") or {}
        if prev0.get("one_liner"):
            L.append("--- last entry: " + prev0["one_liner"])
        L.append("")
    open(os.path.join(a.out, "packets.txt"), "w", encoding="utf-8").write("\n".join(L))
    print("census %d (new %d, orphans %d, archived today %d, single-dose shots %d), roster=%s, AS list=%s, wards rows=%s, AMS blocks=%s, delta_computed=%s, flags=%d, pending checks=%d, cold=%s" % (
        len(ordered), sum(r["new"] for r in ordered), sum(r["orphan"] for r in ordered), len(archived_today), len(single_dose),
        "sent" if roster else "none", (as_today or {}).get("list_date"), len(wards) if wards else 0, len(ams) if ams else 0,
        delta["computed"], len(fl), len(pend_lines), cold))

    # Orphan guard. On 08.09.2026 a parser fault silently dropped 14 ward rows and five
    # patients were published as "no documentation anywhere" when the ward docs held full
    # entries. A cluster of orphans is far more likely to be a parsing failure than a
    # hospital-wide documentation failure, so stop and make someone look.
    prev = prev_stats
    reasons = []
    if ordered and len(orphans) / len(ordered) > ORPHAN_FRACTION:
        reasons.append("%d of %d patients (%.0f%%) have no ward row, over the %.0f%% ceiling"
                       % (len(orphans), len(ordered), 100 * len(orphans) / len(ordered),
                          100 * ORPHAN_FRACTION))
    if prev.get("orphans") is not None and len(orphans) - prev["orphans"] >= ORPHAN_JUMP:
        reasons.append("orphans jumped %d -> %d since the last run" % (prev["orphans"], len(orphans)))
    if prev.get("ward_rows") and nrows < prev["ward_rows"] * (1 - WARDROW_DROP):
        reasons.append("parsed ward rows fell %d -> %d" % (prev["ward_rows"], nrows))
    if reasons:
        print("")
        print("ORPHAN ALERT: " + "; ".join(reasons) + ".")
        for r in orphans:
            print("   %-6s %-8s %s" % (r["pid"], r.get("room", "?"), r["name"][:34]))
        print("Check the ward-doc parser before building. Confirm each name really is absent "
              "from the floors, ICU, cardiology and neurology documents:")
        print("   for f in floors icu cardio neuro; do grep -ci '<surname>' in/$f.json; done")
        print("Re-run with --allow-orphans once the parse is confirmed sound.")
        if not a.allow_orphans:
            # OVERLAY_6 4q: grep the ward JSONs for each orphan's surname instead of all-or-nothing.
            wd = os.path.dirname(os.path.abspath(a.wards))
            blobs = [open(os.path.join(wd, f + ".json"), encoding="utf-8", errors="ignore").read().lower()
                     for f in ("floors", "icu", "cardio", "neuro") if os.path.exists(os.path.join(wd, f + ".json"))]
            conf = set()
            if a.orphans_confirmed and os.path.exists(a.orphans_confirmed):
                conf = {norm_name(l) for l in open(a.orphans_confirmed, encoding="utf-8") if l.strip()}
            unconfirmed = []
            for r in orphans:
                toks = [t for t in re.findall(r"[a-z]+", r["name"].lower()) if len(t) > 3]
                sur = toks[-1] if toks else ""
                hits = sum(b.count(sur) for b in blobs) if sur else -1
                ok = norm_name(r["name"]) in conf or (blobs and sur and hits == 0)
                print("   grep %-14s %s in %d ward docs: %s" % (sur or "?", hits, len(blobs), "absent, confirmed" if ok else "PRESENT or unchecked"))
                if not ok:
                    unconfirmed.append(r["name"])
            if unconfirmed:
                print("orphan guard: %d orphan(s) not confirmed absent: %s" % (len(unconfirmed), ", ".join(unconfirmed)))
                sys.exit(2)
            print("orphan guard: all %d orphans confirmed absent by grep or --orphans-confirmed; proceeding" % len(orphans))
    else:
        print("orphan guard: %d/%d orphans, %d ward rows, no jump vs last run"
              % (len(orphans), len(ordered), nrows))


if __name__ == "__main__":
    main()
