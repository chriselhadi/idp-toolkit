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
                       "Micro recap", "Pendings", "Conflicts", "AMS block", "Updated"], 1, "patients"),
    "Feed Antimicrobials": (["pid", "Drug", "Line", "Issue", "Start", "End", "Running", "Updated"], 2, "antimicrobials"),
    "Feed Micro": (["pid", "Collected", "Specimen", "Result", "Status", "Late", "Updated"], 3, "micro"),
}
CHANGES = ["Date", "pid", "Tab", "Key", "Field", "Old", "New"]
VER = ["Row ID", "Date found", "Found by", "Tab", "Key or pid", "Column", "Value checked", "Value in source", "Source",
       "Severity", "Reply by", "Reply", "Reply note", "State"]
SCHEMA_VERSION = "2"        # bump whenever any header of IDP Feed or of the register changes; never rename a header without it
META_NOTE = ("Open a register block for a pid on its FIRST morning in Feed Patients (Status Active), not at discharge. "
             "AMS block = sheet!first row of a hand-made block in the AMS workbook for the same admission: reconcile into "
             "that admission, never a second block. Age, admission date, CrCl and weight come from the live AMS workbook block; read that block there for the "
             "other AMS columns. Status: Active | Off service dd/mm/yy (gone one run) | Discharged dd/mm/yy (gone two runs: "
             "finalise the block) | Watch dd/mm/yy (block final, late cultures still arriving). Late = Y: result final "
             "after discharge. A pid whose rows are cleared has left the feed.")
COLS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


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
    sent = rec.get("archive_note_sent") or ""
    return ("Discharged " if sent and sent < today else "Off service ") + ddmm(rec.get("last_seen"))


def on_service_once(rec):
    return not (rec.get("archived_reason") or "").startswith(("ID consult in a handoff", "AS list standing therapy"))


def stay_specimens(cx, mrn, name, aliases, first, last):
    w = {"mrn": mrn or "", "name": name or "", "aliases": aliases or []}
    lo = (dt.date.fromisoformat(first or last) - dt.timedelta(days=5)).isoformat() if (first or last) else ""
    return [s for s in I.patient_specimens(cx, w) if lo <= (s.get("collected") or "") <= (last or "9999")]


def spec_row(pid, s, discharged):
    org = "; ".join(o if isinstance(o, str) else o.get("name", "") for o in s.get("organisms") or [])
    ast = " ".join(x for x in ("S: " + s["ast_s"] if s.get("ast_s") else "", "I: " + s["ast_i"] if s.get("ast_i") else "",
                               "R: " + s["ast_r"] if s.get("ast_r") else "") if x)
    res = " | ".join(x for x in (org, ast, s.get("result", "")) if x)
    late = "Y" if discharged and (s.get("final_date") or "") > discharged else "N"
    status = ("Final " + ddmm(s["final_date"])) if s.get("final") and s.get("final_date") else ("Final" if s.get("final") else "Preliminary")
    return [pid, ddmm(s.get("collected")), s.get("specimen", ""), res, status, late]


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
            a(6), a(11), a(10), a(8), sy.get("one_liner", ""), " ; ".join(i.get("dx", "") for i in issues),
            " ; ".join(sy.get("id_plan") or []), vit[0] if vit else "", " ; ".join(vit[1:]), sy.get("micro_recap", ""),
            " ; ".join(sy.get("pendings") or []), " ; ".join(sy.get("conflicts") or []), amsloc])
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
                                     [("%s!%s" % (e["ams_sheet"], e["ams_first_row"])) if e.get("ams_sheet") and e.get("ams_first_row") else ""])
    for pid, w in (state.get("watch") or {}).items():
        rows["Feed Patients"].append([pid, w.get("mrn", ""), w.get("name", ""), "Watch " + ddmm(w.get("discharged")), "", "", "",
                                      "", ddmm(w.get("discharged"))] + [""] * 13)
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
    os.makedirs(a.outdir, exist_ok=True)
    json.dump(desired, open(os.path.join(a.outdir, "feed_desired.json"), "w"), ensure_ascii=True)
    json.dump(ops, open(os.path.join(a.outdir, "ops.json"), "w"), ensure_ascii=True)
    print("FEED OPS: %d update_values call(s); changed rows: %s; %d change-log row(s); %d patients in the feed"
          % (len(ops), ", ".join(summary), len(changes), len(desired["Feed Patients"])))
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


def coverage(desired, index_vals):
    if index_vals is None:
        return None
    ik = index_keys(index_vals)
    bad, n = [], 0
    for r in desired["Feed Patients"]:
        n += 1
        k = ik.get(r[0], [])
        if len(k) != 1:
            bad.append((r[0], len(k), "%s | MRN %s | %s to %s | %s" % (r[0], bare(r[1]), bare(r[7]), bare(r[8]), r[3])))
    return {"n": n, "bad": bad, "missing": sum(1 for b in bad if b[1] == 0), "dup": sum(1 for b in bad if b[1] > 1)}


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
                d = r[4].lstrip("~")[:5]
                if not any(x[23].lstrip("~")[:5] == d for x in hit):
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
    cov = coverage(desired, raw_values(ipath) if os.path.exists(ipath) else None)
    if cov is None:
        line = "register: index not read, coverage not checked"
    else:
        openrows = {(r[4], r[9]) for r in ver[1:] if len(r) > 13 and r[2] == "Claude" and r[3] == "Index" and r[13] == "open"}
        for pid, n, info in cov["bad"]:
            sev = "missing block" if n == 0 else "duplicate block"
            if (pid, sev) not in openrows:
                rows.append([next(ids), today, "Claude", "Index", pid, "Keys", "%d Key(s)" % n, info, "Feed Patients",
                             sev, "", "", "", "open"])
        line = "register: %d admissions, %d without a block%s" % (
            cov["n"], cov["missing"], (", %d with more than one" % cov["dup"]) if cov["dup"] else "")
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
    print("CHECKREG OK: %d block(s) verified, %d finding(s); %d update_values call(s) in vrows_ops.json" % (nver, nfind, len(ops)))
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
                ["Feed Patients", "pid", j(fp), "One row per admission the ID service follows (pid = one admission). Written by the morning run, changed rows only. AMS block = sheet!first row of a hand-made AMS workbook block for the same admission, blank if none."],
                ["Feed Patients", "Status = Active", "", "On the ID list today. Gemini opens the register block on the first morning it appears."],
                ["Feed Patients", "Status = Off service dd/mm/yy", "", "Gone from the ID list one run; dd/mm/yy = last day on the service."],
                ["Feed Patients", "Status = Discharged dd/mm/yy", "", "Gone two runs, or a past admission fed back in by the backfill; Gemini finalises the block."],
                ["Feed Patients", "Status = Watch dd/mm/yy", "", "Block FINAL in Index; late cultures of the stay still arriving (Feed Micro, Late = Y)."],
                ["Feed Antimicrobials", "pid + Drug", j(TABS["Feed Antimicrobials"][0]), "One row per course; a second course of the same drug is 'Drug #2'. Start/End dd/mm, ~ approximate, ? not documented. Running Y/N."],
                ["Feed Micro", "pid + Collected + Specimen", j(TABS["Feed Micro"][0]), "One row per specimen or pending item. Status: Final | Final dd/mm/yy | Preliminary | Pending. Late = Y: final after discharge."],
                ["Feed Changes", "(log, append only)", j(CHANGES), "Every cell the run changed: Old and New values. (new row) and (removed) for whole rows."],
                ["(any tab)", "a pid absent from Feed Patients", "", "The admission has left the feed: its block is FINAL and no culture is awaited."]]
    return [SCHEMA_HDR,
            ["Schema", "Tab", j(SCHEMA_HDR), "This contract, written by the morning run. schema_version " + SCHEMA_VERSION + "; any header change bumps it. " + RULES],
            ["Register", "Key", j(I.REG_HEADER), "Gemini's blocks, current admissions. Key + Status, then the 33 columns of LAU_AMS_Dec_2025_2026_cleaned_in_original_format in the same order. One block = rows sharing a Key; a row with --- ends a block."],
            ["Register", "Key format", "MRN <mrn> | <pid or AMS> | dd/mm/yy to dd/mm/yy", "pid Pnnnn for admissions the ID service followed (from IDP Feed); AMS for blocks taken from the hand-kept workbook. 'to' blank while the stay is open."],
            ["Register", "Status = Active (updated dd/mm/yy)", "", "Admission on the ID service; block opened on its first morning in IDP Feed and updated daily."],
            ["Register", "Status = Off service dd/mm/yy", "", "Left the ID list one run ago."],
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


def cmd_schema(a):
    for which, name in (("feed", "IDP Feed"), ("register", "IDP Discharge Register")):
        rows = [[cell(v) for v in r] for r in schema_rows(which)]
        print("%s: %s" % (name, json.dumps({"range": "'Schema'!A1:D%d" % len(rows), "values": rows}, ensure_ascii=True)))
    print("IDP Feed Meta: " + json.dumps(meta_op(a.date), ensure_ascii=True))
    return 0


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("feed"); [p.add_argument(x) for x in ("state", "census", "ams_blocks", "cultures", "nowdir", "outdir")]; p.add_argument("--date", required=True); p.add_argument("--backlog", type=int, default=10)
    p = sp.add_parser("op"); p.add_argument("ops"); p.add_argument("n", type=int)
    p = sp.add_parser("feedcheck"); p.add_argument("desired"); p.add_argument("nowdir"); p.add_argument("--date", required=True)
    p = sp.add_parser("final"); p.add_argument("state"); p.add_argument("index"); p.add_argument("cultures"); p.add_argument("--date", required=True)
    p = sp.add_parser("checkreg"); [p.add_argument(x) for x in ("register", "desired", "verification", "cultures", "outdir")]; p.add_argument("--date", required=True); p.add_argument("--index")
    p = sp.add_parser("backfill"); p.add_argument("state"); p.add_argument("index"); p.add_argument("tables"); p.add_argument("--date", required=True); p.add_argument("--queue", action="store_true")
    p = sp.add_parser("schema"); p.add_argument("--date", required=True)
    p = sp.add_parser("vqueue"); p.add_argument("verification"); p.add_argument("--date", required=True)
    p = sp.add_parser("vwrite"); p.add_argument("verification"); p.add_argument("replies"); p.add_argument("outdir")
    p = sp.add_parser("regjoin2"); p.add_argument("out"); p.add_argument("files", nargs="+")
    a = ap.parse_args()
    if not a.cmd:
        print(__doc__); return 0
    return {"feed": cmd_feed, "op": cmd_op, "feedcheck": cmd_feedcheck, "final": cmd_final, "checkreg": cmd_checkreg,
            "vqueue": cmd_vqueue, "vwrite": cmd_vwrite, "regjoin2": cmd_regjoin2, "backfill": cmd_backfill,
            "schema": cmd_schema}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
