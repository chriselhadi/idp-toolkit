#!/usr/bin/env python3
"""Amendment AD (18.10.2026, Chris): handout and recap layout. Installed by overlay_patch_9.py.

1. ORDER AND MEMBERSHIP. The handout and the recap list exactly the patients of today's ID list
   email (out/id_list_email.txt), in its groups and its order. Census patients not on that list
   are left out of both (still kept in state). Off-list patients (handoff "ID consulted" rows, AS-list standing
   therapy) appear only in a block at the foot of the recap, one ID-oriented line each (SIGNED_OFF).
2. POOLED UPDATES. Sunday's recap pools Friday, Saturday and Saturday o/n; Monday's pools Friday,
   Saturday, Sunday and Sunday o/n. Mechanically: on Sunday and Monday the previous email's update
   entries are carried in front of today's (state keeps them as updates_pooled). Other days: today's
   entries only (the past day + o/n).
3. ID PLAN. One "ID Plan:" line per patient (synth key id_plan, list of "dd/mm: <plan> (<source>)"),
   pooling the plans of every active issue. Issue lines carry no plan.
4. MICRO = RESULTS ONLY (prelim or final), in micro and micro_recap. Anything awaited is a pending.
5. ROOM ONCE. The current room is in the header only; the one_liner keeps past units ("adm via ER,
   ICU3B 06/10-10/10") but never the current room.
"""
import os, re, datetime as dt

ID_LIST_FILE = "id_list_email.txt"
GROUP_HDR = re.compile(r"^(?P<g>[^:*]+):\s*$")
WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PLAN_RE = re.compile(r"^(\d{2}/\d{2}|prior): \S.*$")
ISSUE_PLAN_RE = re.compile(r"\bID\s*(plan\b|recs?\b|recommend|advis|\d{2}/\d{2}|:)")
MICRO_PENDING_RE = re.compile(r"\b(pend|pending|awaited|awaiting|sent|in process|in progress|to follow)\b", re.I)


def _room_norm(r):
    r = (r or "").replace("*", "").strip().upper()
    return r


def _room_eq(a, b):
    a, b = _room_norm(a), _room_norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # ICU4 == ICU4B (common.py convention); CSU3 == CSU3D
    return (a.startswith(("ICU", "CSU", "CCU")) and b.startswith(a[:3]) and (a + "B" == b or b + "B" == a or a + "D" == b or b + "D" == a))


def parse_id_list(path):
    """[(group, room, name)] in list order. Line: '<room> <name> [(new)] [(UC ...)] <initials>' with * marks."""
    rows, g = [], "Room unknown"
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if GROUP_HDR.match(line):
            g = GROUP_HDR.match(line).group("g").strip(); continue
        t = line.replace("*", " ").split()
        if not t:
            continue
        room = t[0]
        rest = re.sub(r"\([^)]*\)", " ", " ".join(t[1:])).split()
        if rest and (rest[-1] == "?" or re.match(r"^[A-Z]{2,3}$", rest[-1])):
            rest = rest[:-1]
        rows.append((g, room, " ".join(rest)))
    return rows


def apply_id_list(census, out_dir, quiet=False, keep_offlist=False):
    """Reorder and filter census["patients"] to the ID list; set each patient's group to its ID-list
    group; empty cs_id_offlist. Mutates common.WARD_ORDER in place to the ID-list group order so the
    existing renderers iterate it unchanged. Writes out/idlist_order.txt. Returns census."""
    import common
    from common import name_sim
    p = os.path.join(out_dir, ID_LIST_FILE)
    if not os.path.exists(p):
        if not quiet:
            print("WARN AD: %s missing, handout/recap keep ward order and full census" % ID_LIST_FILE)
        return census
    rows = parse_id_list(p)
    pats = list(census["patients"])
    # Several census patients in one room (two ICU6D lines): pair the room's lines and patients by name, best pairs
    # first, over the whole list rather than line by line, so an early line with a vague name cannot take the
    # patient a later line names exactly and leave that line unmatched.
    shared = {}
    for i, (g, room, name) in enumerate(rows):
        cand = [c for c in pats if _room_eq(c["room"], room)]
        if len(cand) > 1:
            shared.setdefault(tuple(sorted(c["pid"] for c in cand)), []).append((i, name, cand))
    paired, taken = {}, set()
    for lines in shared.values():
        pairs = sorted(((name_sim(name, c["name"]), -i, c["pid"]) for i, name, cand in lines for c in cand), reverse=True)
        for _, ni, pid in pairs:
            if -ni not in paired and pid not in taken:
                paired[-ni] = pid; taken.add(pid)
    used, ordered, groups, report = set(), [], [], []
    for i, (g, room, name) in enumerate(rows):
        cand = [c for c in pats if c["pid"] not in used and _room_eq(c["room"], room)]
        best = None
        if i in paired and paired[i] not in used:
            best = next(c for c in pats if c["pid"] == paired[i])
        elif len(cand) == 1:
            best = cand[0]
        elif cand:
            best = max(cand, key=lambda c: name_sim(name, c["name"]))
        else:
            sims = [(name_sim(name, c["name"]), c) for c in pats if c["pid"] not in used]
            sims = [x for x in sims if x[0] >= 0.6]
            if sims:
                best = max(sims, key=lambda x: x[0])[1]
        if best is None:
            report.append("UNMATCHED list line: %s %s (%s)" % (room, name, g))
            continue
        used.add(best["pid"])
        c = dict(best); c["group"] = g
        ordered.append(c)
        if g not in groups:
            groups.append(g)
        report.append("%s | %s %s -> %s %s %s" % (g, room, name, best["pid"], best["room"], best["name"]))
    left = [c for c in pats if c["pid"] not in used]
    for c in left:
        report.append("LEFT OUT (not on ID list): %s %s %s" % (c["pid"], c["room"], c["name"]))
    census = dict(census)
    census["patients"] = ordered
    # Off-list patients (handoff "ID consulted" rows, AS-list standing therapy not on the ID list): printed only at
    # the foot of the recap (keep_offlist=True), never in the handout; never one who is on the ID list.
    on = {c["pid"] for c in ordered}
    census["cs_id_offlist"] = [o for o in census.get("cs_id_offlist", []) if o.get("pid") not in on] if keep_offlist else []
    common.WARD_ORDER[:] = groups + ["Other"]
    open(os.path.join(out_dir, "idlist_order.txt"), "w", encoding="utf-8").write("\n".join(report) + "\n")
    if not quiet:
        print("AD order: %d on ID list, %d matched, %d census left out, %d list lines unmatched"
              % (len(rows), len(ordered), len(left), sum(1 for r in report if r.startswith("UNMATCHED"))))
    return census


# ---------- pooled updates (Sun, Mon) ----------
PLACEHOLDER = re.compile(r"^(no change since .*|new to service today)$")


def _pool(prev_list, prev_date, today_list, today):
    t = dt.date.fromisoformat(today)
    if t.weekday() not in (6, 0) or not prev_list or not prev_date:
        return list(today_list or [])
    try:
        pd = dt.date.fromisoformat(prev_date)
    except ValueError:
        return list(today_list or [])
    if (t - pd).days != 1:
        return list(today_list or [])
    night = WEEKDAY[(pd - dt.timedelta(days=1)).weekday()]
    carried = []
    for u in prev_list:
        if u.startswith("no change since"):
            continue
        if u == "new to service today":
            u = "new to service %s" % pd.strftime("%d/%m")
        elif u.startswith("o/n: "):
            u = "%s o/n: %s" % (night, u[5:])
        carried.append(u)
    now = list(today_list or [])
    if carried:
        now = [u for u in now if not u.startswith("no change since")]
    out = []
    for u in carried + now:
        if u not in out:
            out.append(u)
    return out or list(today_list or [])


def pooled_fields(e, prev_synth, today):
    """Fields stored in state so Monday can carry Sunday's pool."""
    ps = prev_synth or {}
    pdate = ps.get("_date")
    return {
        "updates_pooled": _pool(ps.get("updates_pooled", ps.get("updates")), pdate, e.get("updates"), today),
        "updates_nonid_pooled": _pool(ps.get("updates_nonid_pooled", ps.get("updates_nonid")), pdate, e.get("updates_nonid"), today),
    }


def pooled_entry(e, prev_synth, today):
    f = pooled_fields(e, prev_synth, today)
    e2 = dict(e)
    e2["updates"] = f["updates_pooled"]
    if f["updates_nonid_pooled"]:
        e2["updates_nonid"] = f["updates_nonid_pooled"]
    return e2


# ---------- ID Plan ----------
def plan_line(e):
    plans = e.get("id_plan") or []
    return "ID Plan: " + ("; ".join(plans) if plans else "none documented")


# ---------- validator extras ----------
def validate_extra(S, cens, today, errors, warns, windows):
    for pid, e in S.items():
        if not isinstance(e, dict):
            continue
        w = pid
        ip = e.get("id_plan")
        if ip is None:
            errors.append("%s: missing key id_plan (AD3: list of 'dd/mm: <plan> (<source>)', [] when no source states one)" % w)
            ip = []
        elif not (isinstance(ip, list) and all(isinstance(x, str) for x in ip)):
            errors.append("%s: id_plan must be a list of strings" % w); ip = []
        for x in ip:
            if not PLAN_RE.match(x):
                errors.append("%s: id_plan grammar 'dd/mm: <plan> (<source>)': %s" % (w, x))
        for i, iss in enumerate(e.get("issues") or []):
            dx = iss.get("dx", "") if isinstance(iss, dict) else ""
            m = ISSUE_PLAN_RE.search(dx)
            if m:
                errors.append("%s: issue %d carries an ID plan ('%s'); move it to id_plan (AD3): %s" % (w, i + 1, m.group(0), dx))
        for mi in (e.get("micro") or []) + ([e["micro_recap"]] if isinstance(e.get("micro_recap"), str) else []):
            m = MICRO_PENDING_RE.search(mi)
            if m:
                errors.append("%s: micro holds results only (AD4); '%s' is awaited, move it to pendings: %s" % (w, m.group(0), mi))
        c = cens.get(pid) or {}
        room = _room_norm(c.get("room"))
        ol = e.get("one_liner") if isinstance(e.get("one_liner"), str) else ""
        if room and re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(room), ol, re.I):
            errors.append("%s: one_liner repeats the current room %s (AD5: room in the header only; keep past units): %s" % (w, room, ol[:160]))
        if ip:
            pw = set().union(*[windows(x) for x in ip])
            for k, v in (("issues", [i.get("dx", "") for i in e.get("issues") or [] if isinstance(i, dict)]), ("pendings", e.get("pendings") or [])):
                if v:
                    rep = pw & set().union(*[windows(s) for s in v])
                    if rep:
                        errors.append("%s: same fact in id_plan and %s: '...%s...'" % (w, k, sorted(rep)[0]))
