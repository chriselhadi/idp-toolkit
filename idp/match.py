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
        tags = [t.lower() for t in re.findall(r"\(([^)]+)\)", rest)]
        rest = re.sub(r"\([^)]*\)", " ", rest).strip()
        fellow = ""
        mm = re.match(r"^(.*?)[\s,]+([A-Z]{2,3})$", rest)
        if mm and mm.group(1).strip():
            rest, fellow = mm.group(1).strip(), mm.group(2)
        room, grp, _ = parse_bed(room_tok)
        if grp == "Other" and not re.search(r"\d", room_tok):
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
            for a in [rec["name"]] + rec.get("aliases", []):
                j = name_sim(name, a)
                if j > score:
                    best, score = pid, j
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


def ward_lookup(wards, name, room):
    """Find ward rows for a patient; owning doc wins over cardio/neuro duplicates."""
    if not wards:
        return []
    hits = []
    for row in wards:
        j = name_sim(name, row.get("name", ""))
        if j >= 0.5 or (row.get("room") and room and row["room"].upper() == room.upper() and j >= 0.34):
            hits.append((j, row))
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


def compute_delta(as_today, as_yday):
    if not as_today or not as_yday:
        return {"computed": False, "reason": "missing today" if not as_today else "missing yesterday snapshot"}
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
            "new": [{"mrn": p["mrn"], "name": p["name"], "room": p["room"], "drugs": p["standing_drugs"]} for p in new],
            "off": [{"mrn": p["mrn"], "name": p["name"], "room": p["room"], "drugs": p.get("standing_drugs", [])} for p in off],
            "changes": changes,
            "counts": {"today": len([p for p in T.values() if not p.get("once_only")]),
                       "yday": len([p for p in Y.values() if not p.get("once_only")]),
                       "new": len(new), "off": len(off), "changed": len(changes)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state"); ap.add_argument("as_today"); ap.add_argument("wards"); ap.add_argument("ams"); ap.add_argument("out")
    ap.add_argument("--date", required=True); ap.add_argument("--roster"); ap.add_argument("--as-yday")
    a = ap.parse_args()
    today = parse_date(a.date)
    os.makedirs(a.out, exist_ok=True)
    state = load_opt(a.state)
    cold = state is None
    if cold:
        state = {"version": 2, "date": None, "next_pid": 1, "patients": {}, "as_snapshot": None, "observations": [], "roster_last": None}
    as_today = load_opt(a.as_today); wards = load_opt(a.wards); ams = load_opt(a.ams)
    as_yday = load_opt(a.as_yday) or state.get("as_snapshot")
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
        if room and (rec["room"] is None or PRIORITY[prov] < PRIORITY[rec["room_source"]]):
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
    if as_today:
        for p in as_today["patients"]:
            pid, how = reg.find(p["name"], p["mrn"])
            if not pid and "paeds" in p.get("flags", []):
                continue  # paeds never enter the adult census from the AS list; listed in the Delta Report instead
            if not pid:
                if p.get("once_only") and not ward_lookup(wards, p["name"], p["room"]):
                    single_dose.append("%s %s: %s" % (p["room"], p["name"], ", ".join(p["drugs"])))
                    continue
                if not p.get("once_only") or ward_lookup(wards, p["name"], p["room"]):
                    pid = reg.add(p["name"], p["mrn"], today)
                else:
                    continue
            elif not reg.p[pid].get("active") and roster:
                continue  # came off Chris's list today: the AS list does not put them back
            rec = touch(pid, p["name"], p["mrn"], p["room"], p["group"], "as", "", ["paeds"] if "paeds" in p.get("flags", []) else [])
            rec["as_orders"] = p["orders"]; rec["as_standing"] = p["standing_drugs"]; rec["as_once_only"] = p.get("once_only", False)
            rec["as_age"] = p.get("age"); rec["as_admission"] = p.get("admission_date"); rec["as_crcl"] = p.get("crcl")
    else:
        flags.append("no AS list parsed today: rooms from roster > ward doc > prior state")

    # 3. Ward rows enrich; AMS enriches and audits.
    for pid, rec in census.items():
        rows = ward_lookup(wards, rec["name"], rec["room"])
        rec["ward_rows"] = rows
        if rows and not rec["room"]:
            r0 = rows[0]
            if r0.get("room"):
                room, grp, _ = parse_bed(r0["room"]); rec["room"], rec["group"], rec["room_source"] = room, grp, "ward"
        rec["orphan"] = not rows
        blk, status = ams_lookup(ams, rec["name"], rec["mrn"], today)
        rec["ams_status"] = status; rec["ams_block"] = blk
        rec["ams_fellow"] = (blk or {}).get("fellow", "")
        if not rec["room"]:
            rec["room"], rec["group"], rec["room_source"] = "?", "Other", None
            flags.append("no room for %s (%s) from any source" % (rec["name"], pid))
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
    jdump(delta, os.path.join(a.out, "delta.json"))
    jdump({r["pid"]: r["ward_rows"] for r in ordered}, os.path.join(a.out, "ward_rows.json"))
    state["next_pid"] = reg.next
    state["_census_pids"] = [r["pid"] for r in ordered]
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
    open(os.path.join(a.out, "packets.txt"), "w", encoding="utf-8").write("\n".join(L))
    print("census %d (new %d, orphans %d, archived today %d, single-dose shots %d), roster=%s, AS list=%s, wards rows=%s, AMS blocks=%s, delta_computed=%s, flags=%d, pending checks=%d, cold=%s" % (
        len(ordered), sum(r["new"] for r in ordered), sum(r["orphan"] for r in ordered), len(archived_today), len(single_dose),
        "sent" if roster else "none", (as_today or {}).get("list_date"), len(wards) if wards else 0, len(ams) if ams else 0,
        delta["computed"], len(fl), len(pend_lines), cold))


if __name__ == "__main__":
    main()
