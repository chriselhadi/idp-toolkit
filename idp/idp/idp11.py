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
                       "Micro recap", "Pendings", "Conflicts", "Updated"], 1, "patients"),
    "Feed Antimicrobials": (["pid", "Drug", "Line", "Issue", "Start", "End", "Running", "Updated"], 2, "antimicrobials"),
    "Feed Micro": (["pid", "Collected", "Specimen", "Result", "Status", "Late", "Updated"], 3, "micro"),
}
CHANGES = ["Date", "pid", "Tab", "Key", "Field", "Old", "New"]
VER = ["Row ID", "Date found", "Found by", "Tab", "Key or pid", "Column", "Value checked", "Value in source", "Source",
       "Severity", "Reply by", "Reply", "Reply note", "State"]
META_NOTE = ("Age, admission date, CrCl and weight come from the live AMS workbook block; read that block there for the "
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
    return [[("" if c is None else str(c)) for c in r] for r in o]


def key_of(r, n):
    return tuple(x[1:] if x.startswith("'") else x for x in r[:n])


def cell(v):
    v = re.sub(r"\s*\n\s*", " ; ", v if isinstance(v, str) else ("" if v is None else str(v))).strip()
    return sheet_safe(clean(v))[:4000]


def dmy(iso):
    try:
        return dt.date.fromisoformat(iso).strftime("%d/%m/%Y")
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
    for pid, rec, status in sorted(pts):
        sy = rec.get("synth") or {}
        c = cen.get(pid, {})
        b = (amsb.get(pid) or {}).get("rows") or []
        r0 = b[0] if b else []
        a = lambda i: (r0[i] if len(r0) > i and r0[i] is not None else "")
        issues = sy.get("issues") or []
        vit = sy.get("vitals") or []
        rows["Feed Patients"].append([pid, rec.get("mrn") or c.get("mrn") or (a(5) if str(a(5)).isdigit() else ""),
            rec.get("name") or c.get("name", ""), status, c.get("room") or sy.get("_room", ""), c.get("fellow") or sy.get("_fellow", ""),
            "Y" if "uc" in (c.get("tags") or sy.get("_tags") or []) else "", ddmm(rec.get("first_seen")), ddmm(rec.get("last_seen")),
            a(6), a(11), a(10), a(8), sy.get("one_liner", ""), " ; ".join(i.get("dx", "") for i in issues),
            " ; ".join(sy.get("id_plan") or []), vit[0] if vit else "", " ; ".join(vit[1:]), sy.get("micro_recap", ""),
            " ; ".join(sy.get("pendings") or []), " ; ".join(sy.get("conflicts") or [])])
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
    for pid, w in (state.get("watch") or {}).items():
        rows["Feed Patients"].append([pid, w.get("mrn", ""), w.get("name", ""), "Watch " + ddmm(w.get("discharged")), "", "", "",
                                      "", ddmm(w.get("discharged"))] + [""] * 12)
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
        if not now or now[0][:1] != [hdr[0]]:
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
                if old[:len(hdr) - 1] != [x[1:] if x.startswith("'") else x for x in r]:
                    upd[rown] = r + [today]
                    for h, o, n in zip(hdr, old, r):
                        if o != (n[1:] if n.startswith("'") else n):
                            changes.append([today, r[0], t, " | ".join(k), h, o[:300], n[:300]])
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
            if g is None or [x.lstrip("'") for x in r] != g:
                bad.append("%s %s" % (t, " | ".join(k)))
        for k in got:
            if k not in want:
                bad.append("%s %s (should be cleared)" % (t, " | ".join(k)))
    for b in bad[:30]:
        print("MISMATCH " + b)
    if bad:
        print("FEED FAILED: %d row(s) differ" % len(bad)); return 1
    meta = [["Key", "Value"], ["schema_version", "1"], ["status", "live"], ["last_run", dmy(a.date)], ["tabs", META_NOTE]]
    print("FEED MATCH. Meta op: " + json.dumps({"range": "'Meta'!A1:B5", "values": meta}, ensure_ascii=True))
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
        if rec.get("active") or rec.get("dup_of") or not rec.get("archive_note_sent"):
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


def cmd_checkreg(a):
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
    start = len(ver) + 1 if ver else 2
    ops = []
    if not ver:
        ops.append({"range": "Verification!A1:N1", "values": [VER]})
    rows = [[cell(v) for v in r] for r in rows]
    for i in range(0, len(rows), 40):
        part = rows[i:i + 40]
        ops.append({"range": "Verification!A%d:N%d" % (start + i, start + i + len(part) - 1), "values": part})
    os.makedirs(a.outdir, exist_ok=True)
    json.dump(ops, open(os.path.join(a.outdir, "vrows_ops.json"), "w"), ensure_ascii=True)
    print("CHECKREG OK: %d block(s) verified, %d finding(s); %d update_values call(s) in vrows_ops.json" % (nver, nfind, len(ops)))
    return 0


# ------------------------------------------------------------------ the Verification exchange
def days(d1, today):
    try:
        a = dt.datetime.strptime(d1, "%d/%m/%Y").date()
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


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("feed"); [p.add_argument(x) for x in ("state", "census", "ams_blocks", "cultures", "nowdir", "outdir")]; p.add_argument("--date", required=True); p.add_argument("--backlog", type=int, default=10)
    p = sp.add_parser("op"); p.add_argument("ops"); p.add_argument("n", type=int)
    p = sp.add_parser("feedcheck"); p.add_argument("desired"); p.add_argument("nowdir"); p.add_argument("--date", required=True)
    p = sp.add_parser("final"); p.add_argument("state"); p.add_argument("index"); p.add_argument("cultures"); p.add_argument("--date", required=True)
    p = sp.add_parser("checkreg"); [p.add_argument(x) for x in ("register", "desired", "verification", "cultures", "outdir")]; p.add_argument("--date", required=True)
    p = sp.add_parser("vqueue"); p.add_argument("verification"); p.add_argument("--date", required=True)
    p = sp.add_parser("vwrite"); p.add_argument("verification"); p.add_argument("replies"); p.add_argument("outdir")
    p = sp.add_parser("regjoin2"); p.add_argument("out"); p.add_argument("files", nargs="+")
    a = ap.parse_args()
    if not a.cmd:
        print(__doc__); return 0
    return {"feed": cmd_feed, "op": cmd_op, "feedcheck": cmd_feedcheck, "final": cmd_final, "checkreg": cmd_checkreg,
            "vqueue": cmd_vqueue, "vwrite": cmd_vwrite, "regjoin2": cmd_regjoin2}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
