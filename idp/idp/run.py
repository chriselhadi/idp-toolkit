#!/usr/bin/env python3
"""Stage commands for the daily run (Chris, 28.11.2026, decision A). Run from the work dir (/tmp/idp).

The agent keeps every MCP read and write (Gmail, Drive, Sheets) and the judgment (roster.txt, synth_delta.py,
roster_out.txt, replies); run.py only runs the local steps, in order, and stops at the first failed gate:

  run.py prep  --date YYYY-MM-DD [--as-missing] [--allow-orphans] [--skip-base] [--accept-chain]
  run.py build --date YYYY-MM-DD --long-date "28 November 2026" [--coverage-warn]
  run.py post  --date YYYY-MM-DD
  run.py op    <ops.json> <n>                       print op n (from 1) of an ops file for update_values
  run.py chkw  <ops.json> <n> <readback.json>       compare op n with a get_values read-back: CHKW MATCH / MISMATCH
  run.py sendcheck <sent_message.json> <field=file>...   a sent email (Gmail get_message) against its files, per field
                                                    EXACT / EQ_mod_trailing_ws / DIFF; SENDCHECK OK
  run.py chaincheck <chain.txt> --date YYYY-MM-DD [--state in/state.json] [--accept-chain]
                                                    CHAIN CHECK OK / WARN / FAIL (the check prep runs on in/chain.txt)

Round 2 (28.11.2026): prep and post stop (STAGE FAIL: feed reads: ...) unless every in/feed_now/<tab>.json of
patients antimicrobials micro labcx dailyreport changes evolution review rules answered exists, parses and has a header
row (and in/reg_Verification.json, when present); no write op is ever emitted for a tab whose read is missing. A prep
re-run keeps the judgment work (synth_delta.py, out/review_replies.json, out/roster_out.txt, in/roster*.txt,
out/verification_requests.json; "Applied as" in out/answered_rows.json; addrule rows in out/rule_rows.json) and prints
"preserved: ...". prep checks in/chain.txt (the unpackchain output) and the state date (yesterday), prints the state's
last_run_utc and the NEW / READMISSION lines of the base; a failed base no longer stops the later steps (prep still
ends STAGE FAIL: base; --skip-base skips it). post writes state["last_run_utc"], turns out/verification_requests.json
into C- rows, and writes a full base when 6+ patches follow the base, the chain fell back, or the base is dated today.

Each step prints one summary line ("  <step>: <its result line>"); its full output goes to out/stage_logs/.
A failed gate prints "STAGE FAIL: <step>: <reason>" and exits 1; a finished stage prints "STAGE OK: <stage> ...".

prep (after the morning gather; inputs under in/):
  feed snapshot  in/feed_now -> in/feed_before (the feed as Gemini last had it, before any feed write today)
  parse_wards    in/floors.json in/icu.json in/cardio.json in/neuro.json -> in/wards.json
  parse_ams      in/ams_spill.json, in/ams2_spill.json -> in/ams.json (merged)
  edits          in/edits_dl/ -> in/edits.json (or {"edits": []})
  state_merge    in/state.json --find (report only)
  regjoin2       in/reg_Register.json + in/reg_History_*.json -> in/register.json (when the register was read)
  match          in/state.json in/as_today.json in/wards.json in/ams.json, --roster in/roster.txt,
                 --last-delta-sent $(cat in/last_delta_sent.txt), --as-yday in/as_yday.json (if present),
                 --update-text in/email_today.txt in/service_list.json; --as-missing: yesterday's list for rooms only,
                 no delta, the state records the missed day (rule C)
  day updates    out/packets.txt -> out/day_updates.txt; in/service_list.json -> out/app_handoffs.txt
  cultures       in/cultures.txt (--archive in/cx_archive.json) -> out/cultures.json, out/cultures_packets.txt
  base           idp10 base -> synth_base.py
  vqueue         in/reg_Verification.json -> out/vqueue.txt
  review         in/feed_now/review.json -> out/review_open.txt (if read)
  recon reply    in/recon_prev.txt -> in/recon_prev.json (parsed here); in/recon_reply.txt (if not empty) ->
                 out/chris_answers.*, answered_rows.json, rule_rows.json, undo_ops.json; then promote: proposed rules
                 shown in one email without an undo -> out/promote_ops.json and in/active_rules.txt (rules that bind)
  svccheck       in/service_list.json vs in/roster_yday.txt
build (after synth_delta.py and out/roster_out.txt are written):
  apply, validate_synth (0 errors), evolve (0 unexplained), coverage gate (out/coverage_gate.txt; synth.py WAIVED),
  id_list.py + checks_R idlist/text, build.py (PREFLIGHT OK and BUILD OK on its stdout), recap_html.py,
  wa_handout.py (out/census_wa.json when present), checks_R text on every output that is sent. No HTML handout.
post (after the sends, out/feed/replies.json, out/review_replies.json and out/answered_rows.json "Applied as"):
  ams_blocks, idp11 final, idp10 watch, backfill key, idp11 feed (pre-write state in/feed_before), schema, checkreg,
  vwrite, reviewreply, drive_state patch, recon.py (every input; --items out/run_items.txt when present), checks_R text out/recon.txt; then
  out/post_ops/NN_<what>.json and out/post_ops/INDEX.txt: the Drive/Sheets writes in order, their target and how to
  verify each. Targets: in/targets.json {"feed": id, "register": id, "state_folder": id} (kept out of the repo).
"""
import argparse, datetime as dt, glob, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PY = sys.executable
TOOLS_CANDIDATES = [os.path.join(HERE, "..", "..", "tools"), os.path.join(os.getcwd(), "tools")]


class StageFail(Exception):
    pass


class Stage:
    def __init__(self, name, work):
        self.name, self.work, self.n, self.soft = name, work, 0, False
        self.logs = os.path.join(work, "out", "stage_logs")
        os.makedirs(self.logs, exist_ok=True)
        print("STAGE %s (%s)" % (name, work))

    def p(self, *parts):
        return os.path.join(self.work, *parts)

    def has(self, *parts):
        q = self.p(*parts)
        if os.path.isdir(q):
            return bool(os.listdir(q))                  # round 2 T1: an empty directory is not a read
        return os.path.exists(q) and os.path.getsize(q) > 0

    def opt(self, *parts):
        return self.p(*parts) if self.has(*parts) else "MISSING"

    def fail(self, step, reason):
        if self.soft:                                   # a deferred gate (prep base): the later steps run first
            print("  %s: FAILED (STAGE FAIL deferred to the end of the stage): %s" % (step, reason))
            raise StageFail(reason)
        print("STAGE FAIL: %s: %s" % (step, reason))
        raise StageFail(step)

    def note(self, step, text):
        print("  %s: %s" % (step, text))

    def run(self, step, argv, ok=None, okrc=(0,), tee=None, must_not=None, summary=None, ok_any=None):
        """Run a toolkit script; gate on exit code and (optional) a token on stdout. Returns stdout."""
        self.n += 1
        r = subprocess.run([PY] + [str(x) for x in argv], capture_output=True, text=True, cwd=self.work)
        out = r.stdout + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")
        log = os.path.join(self.logs, "%s_%02d_%s.txt" % (self.name, self.n, re.sub(r"\W+", "_", step)))
        open(log, "w", encoding="utf-8").write(out)
        if tee:
            open(self.p(tee), "w", encoding="utf-8").write(r.stdout)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        tokens = list(ok) if isinstance(ok, (list, tuple)) else ([ok] if ok else [])   # every token must appear
        anyt = list(ok_any or [])                                                  # one of these must appear
        hit = [l for l in lines if any(t in l for t in tokens + anyt)] if tokens or anyt else []
        summ = (hit[-1] if hit else (lines[-1] if lines else "(no output)")).strip()
        if r.returncode not in okrc:
            err = [l for l in (r.stderr or "").splitlines() if l.strip()]
            why = (err[-1] if err and r.returncode == 1 and not lines else summ)
            self.fail(step, "exit %d: %s (log %s)" % (r.returncode, why[:300], os.path.relpath(log, self.work)))
        for t in tokens:
            if not any(t in l for l in lines):
                self.fail(step, "no '%s' in its output; last line: %s (log %s)" % (t, summ[:300], os.path.relpath(log, self.work)))
        if anyt and not hit:
            self.fail(step, "none of %s in its output; last line: %s (log %s)" % (" / ".join(anyt), summ[:300], os.path.relpath(log, self.work)))
        if must_not:
            bad = [l for l in lines if must_not in l]
            if bad:
                self.fail(step, "%d line(s) '%s', e.g. %s" % (len(bad), must_not, bad[0][:200]))
        self.note(step, (summary or summ)[:300])
        return r.stdout


def T(script):
    return os.path.join(HERE, script)


def tool(script):
    for d in TOOLS_CANDIDATES:
        if os.path.exists(os.path.join(d, script)):
            return os.path.abspath(os.path.join(d, script))
    return os.path.join(TOOLS_CANDIDATES[0], script)


def dmy(iso, sep="."):
    d = dt.date.fromisoformat(iso)
    return d.strftime("%d" + sep + "%m" + sep + "%Y")


def jload(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def tab_values(p):
    o = jload(p)
    if isinstance(o, dict):
        return o.get("values") or []
    return o if isinstance(o, list) else []


# ------------------------------------------------------------------ round 2 gates and helpers
# T1: every feed tab the run reads; prep and post stop (STAGE FAIL naming the tab) when one is missing, does not parse or
# has no header row, so no write op is ever emitted for a tab whose read is missing (a missing read written "by position"
# overwrites the live tab from row 1 or 2).
FEED_TABS = ("patients", "antimicrobials", "micro", "labcx", "dailyreport", "changes", "evolution", "review", "rules", "answered")


def read_problem(p):
    """None when p is a get_values result with at least a header row; else why not."""
    if not os.path.isfile(p):
        return "missing"
    try:
        o = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return "does not parse (%s)" % str(e)[:80]
    vals = o.get("values") if isinstance(o, dict) else o
    if not isinstance(vals, list):
        return "has no values list"
    if not vals or not isinstance(vals[0], list) or not any(str(c).strip() for c in vals[0] if c is not None):
        return "empty (no header row)"
    return None


def gate_reads(S, step, d, names=FEED_TABS):
    rel = os.path.relpath(d, S.work)
    if not os.path.isdir(d) or not os.listdir(d):
        S.fail(step, "%s is %s: read every feed tab first (%s); no write op is emitted for a tab whose read is missing"
               % (rel, "empty" if os.path.isdir(d) else "missing", ", ".join(n + ".json" for n in names)))
    bad = [(n, read_problem(os.path.join(d, n + ".json"))) for n in names]
    bad = [(n, w) for n, w in bad if w]
    if bad:
        S.fail(step, "feed tab read %s: re-read the tab(s) and run the stage again (no write op is emitted for a tab whose "
               "read is missing)" % "; ".join("%s/%s.json %s" % (rel, n, w) for n, w in bad))
    S.note(step, "%s: all %d feed tab reads present with a header row" % (rel, len(names)))


def gate_one(S, step, *parts):
    """A register tab read that the run writes after (Verification): present means it has a header row."""
    w = read_problem(S.p(*parts))
    if w:
        S.fail(step, "%s %s: re-read it (no write op is emitted for a tab whose read is missing)" % ("/".join(parts), w))


CHAIN_OK = re.compile(r"CHAIN OK: base (\S+) \+ (\d+) patch\(es\) (\S+) -> state dated (\S+?),")


def chain_check(text, date, state_date=None):
    """T4: the unpackchain output (in/chain.txt) against today's date -> (fails, chain_warns, warns, info).
    fails: no CHAIN OK, state.json not the chain's state, state dated today or later. chain_warns: 'sha mismatch' /
    'not applied' lines (STAGE FAIL in prep unless --accept-chain). warns: state not dated yesterday."""
    yday = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    info = {"base": None, "patches": None, "state": None, "fallback": False}
    fails, cw, warns = [], [], []
    m = CHAIN_OK.search(text or "")
    if m:
        info.update(base=m.group(1), patches=int(m.group(2)), state=m.group(4))
    elif text is not None:
        fails.append("no CHAIN OK line in in/chain.txt%s" % (" (CHAIN FAILED)" if "CHAIN FAILED" in text else ""))
    lines = (text or "").splitlines()
    info["fallback"] = any(re.match(r"chain: (base \S+ incomplete .*skipped|fallback\b)", l) for l in lines)
    cw = [l.strip() for l in lines if "sha mismatch" in l or "not applied" in l]
    if state_date and info["state"] and state_date != info["state"]:
        fails.append("in/state.json is dated %s but the chain output says %s (save the unpackchain output as in/state.json)"
                     % (state_date, info["state"]))
    st = info["state"] or state_date
    if st:
        if st >= date:
            fails.append("the state is dated %s, not before today %s (today's own output, or the wrong state)" % (st, date))
        elif st != yday:
            warns.append("the state is dated %s, not yesterday %s: a missed day or a chain that stopped early" % (st, yday))
    return fails, cw, warns, info


def utc_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_start(S, date):
    """T10: the run's start (first prep of the day, out/run_start_utc.txt '<date> <utc>'); None when not recorded."""
    try:
        d, t = open(S.p("out", "run_start_utc.txt"), encoding="utf-8").read().split()[:2]
        return t if d == date else None
    except Exception:
        return None


def base_lines(stdout):
    """T8: the NEW and READMISSION lines of idp10 base, shown on the console."""
    return [l.strip() for l in stdout.splitlines() if ": NEW (" in l or ": READMISSION," in l]


# T2: judgment work a prep re-run must never destroy
KEEP_FILES = [("synth_delta.py",), ("out", "review_replies.json"), ("out", "roster_out.txt"), ("out", "verification_requests.json"),
              ("in", "roster.txt"), ("in", "roster_yday.txt")]
KEEP_MERGE = [("out", "answered_rows.json"), ("out", "rule_rows.json")]


def keep_snapshot(S):
    snap, d = {}, S.p("out", "prep_keep")
    for parts in KEEP_FILES + KEEP_MERGE:
        if os.path.isfile(S.p(*parts)):
            snap[parts] = open(S.p(*parts), "rb").read()
            os.makedirs(d, exist_ok=True)                 # a copy on disk as well, for a by-hand recovery
            open(os.path.join(d, "_".join(parts)), "wb").write(snap[parts])
    return snap


def keep_restore(S, snap):
    """Put back what prep must not change; merge answered/rule rows: 'Applied as'/'Until' and addrule (proposed) rows."""
    msgs = []
    for parts in KEEP_FILES:
        if parts not in snap:
            continue
        p = S.p(*parts)
        cur = open(p, "rb").read() if os.path.isfile(p) else None
        if cur != snap[parts]:
            open(p, "wb").write(snap[parts])
            msgs.append("/".join(parts) + " (restored)")
        else:
            msgs.append("/".join(parts))
    k = ("out", "answered_rows.json")
    if k in snap:
        try:
            old = json.loads(snap[k].decode("utf-8")) or []
        except Exception:
            old = []
        new = jload(S.p(*k), []) or []
        by = {}
        for r in new:
            r += [""] * (6 - len(r))
            by[r[0]] = r
        na = nk = 0
        for r in old:
            r = list(r) + [""] * (6 - len(r))
            if r[0] in by:
                if r[4] and not by[r[0]][4]:
                    by[r[0]][4] = r[4]; na += 1
                if r[5] and not by[r[0]][5]:
                    by[r[0]][5] = r[5]
            elif r[4]:
                new.append(r); by[r[0]] = r; nk += 1
        json.dump(new, open(S.p(*k), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        msgs.append("out/answered_rows.json (%d 'Applied as' kept%s)" % (na + nk, (", %d row(s) no longer in the reply kept" % nk) if nk else ""))
    k = ("out", "rule_rows.json")
    if k in snap:
        try:
            old = json.loads(snap[k].decode("utf-8")) or []
        except Exception:
            old = []
        new = jload(S.p(*k), []) or []
        texts = {str(r[2]).strip() for r in new if len(r) > 2}
        tab = S.p("in", "feed_now", "rules.json")
        from recon_reply import _next_no
        na = 0
        for r in old:
            if len(r) > 4 and r[4] == "proposed" and str(r[2]).strip() not in texts:
                new.append([_next_no(tab if os.path.exists(tab) else None, new)] + list(r[1:]))
                texts.add(str(r[2]).strip()); na += 1
        json.dump(new, open(S.p(*k), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        msgs.append("out/rule_rows.json (%d addrule row(s) kept)" % na)
    return msgs


def add_run_items(S, items):
    """Run items prep raises (chain check): out/run_items_prep.txt, rewritten each prep; post hands them to recon --items."""
    p = S.p("out", "run_items_prep.txt")
    open(p, "w", encoding="utf-8").write("".join(i + "\n" for i in items))


# ------------------------------------------------------------------ prep
def write_day_updates(packets, out):
    """Spec 7.0 1b (was an awk line): headers of census packets with their [PENDINGS], [SYNTHESIS] and ward doc lines."""
    L, keep = [], False
    for ln in open(packets, encoding="utf-8", errors="ignore").read().splitlines():
        if ln.startswith("=== "):
            keep = "OFFLIST" not in ln
            if keep:
                L.append(ln)
            continue
        if keep and (ln.startswith("[PENDINGS]") or ln.startswith("[SYNTHESIS]") or ln.startswith("--- ward doc")):
            L.append(ln)
    open(out, "w", encoding="utf-8").write("\n".join(L) + ("\n" if L else ""))
    return sum(1 for l in L if l.startswith("=== "))


def write_app_handoffs(svc_p, out):
    """Spec 7.0 1a (was a python one-liner): every patient's service-list write-up, then the handoff text."""
    s = jload(svc_p, {}) or {}
    L = ["last_edit_at %s" % s.get("last_edit_at")]
    for q in s.get("patients") or []:
        L.append("\n## %s %s %s %s \n %s" % (q.get("pid"), q.get("room"), q.get("name"), q.get("updated_at"), q.get("handoff") or "(no write-up)"))
    L.append("\n## handoff_text\n %s" % s.get("handoff_text", ""))
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return len(s.get("patients") or []), sum(1 for q in s.get("patients") or [] if q.get("handoff"))


def prep(a, S):
    snap = keep_snapshot(S)
    ok = False
    try:
        res = prep_steps(a, S)
        ok = True
        return res
    finally:
        msgs = keep_restore(S, snap)
        if ok:
            S.note("preserved", ", ".join(msgs) if msgs else "nothing to preserve (first prep of the day)")


def prep_chain(a, S):
    """T4 and T10: the state the run starts from."""
    D = a.date
    st = jload(S.p("in", "state.json"), {}) if S.has("in", "state.json") else None
    if st is None:
        S.note("chain check", "no in/state.json (cold start): nothing to check")
        return []
    lr = st.get("last_run_utc")
    S.note("last run", "state last_run_utc %s" % lr if lr else
           "state has no last_run_utc: 'since yesterday's run' = the send time of the newest AS List Delta Report before today, else 24 h")
    text = open(S.p("in", "chain.txt"), encoding="utf-8", errors="ignore").read() if S.has("in", "chain.txt") else None
    fails, cw, warns, info = chain_check(text, D, st.get("date"))
    if fails:
        S.fail("chain check", "; ".join(fails))
    items = []
    if cw:
        if not a.accept_chain:
            S.fail("chain check", "%d chain line(s): %s. The state may be older than yesterday's run: find the missing or broken "
                   "part, or run prep --accept-chain (WARN and a run item)" % (len(cw), " | ".join(cw)[:300]))
        for l in cw:
            S.note("chain check", "WARN (--accept-chain): " + l)
            items.append("State chain: %s (accepted, state dated %s)" % (l, info["state"] or st.get("date")))
    for w in warns:
        S.note("chain check", "WARN: " + w)
        items.append("State chain: " + w)
    if info["fallback"]:
        S.note("chain check", "WARN: the chain fell back to the older base %s (post writes a full base)" % info["base"])
    if text is None:
        S.note("chain check", "no in/chain.txt (save the unpackchain output there): state dated %s checked only" % st.get("date"))
    elif not cw and not warns:
        S.note("chain check", "CHAIN CHECK OK: base %s + %d patch(es) -> state dated %s (yesterday)" % (info["base"], info["patches"], info["state"]))
    return items


def prep_steps(a, S):
    D, W = a.date, S.work
    # T1: every feed tab read present before anything else (an empty in/feed_now is not a read)
    gate_reads(S, "feed reads", S.p("in", "feed_now"))
    if S.has("in", "reg_Verification.json"):
        gate_one(S, "feed reads", "in", "reg_Verification.json")
    if run_start(S, D) is None:
        open(S.p("out", "run_start_utc.txt"), "w").write("%s %s\n" % (D, utc_now()))
    add_run_items(S, prep_chain(a, S))
    # feed snapshot before any feed write today (review item 1): post and recon read in/feed_before
    fb = S.p("in", "feed_before")
    shutil.rmtree(fb, ignore_errors=True)
    shutil.copytree(S.p("in", "feed_now"), fb)
    S.note("feed snapshot", "in/feed_now -> in/feed_before (%d tab files)" % len(os.listdir(fb)))
    docs = [S.opt("in", f + ".json") for f in ("floors", "icu", "cardio", "neuro")]
    if all(d == "MISSING" for d in docs) and S.has("in", "wards.json"):
        S.note("parse_wards", "no ward doc in in/: in/wards.json used as it is")
    else:
        S.run("parse_wards", [T("parse_wards.py")] + docs + [S.p("in", "wards.json"), "--probe"])
    if S.has("in", "ams_spill.json"):
        S.run("parse_ams", [T("parse_ams.py"), S.p("in", "ams_spill.json"), S.p("in", "ams.json"), "--probe", "--date=" + D])
        if S.has("in", "ams2_spill.json"):
            S.run("parse_ams2", [T("parse_ams.py"), S.p("in", "ams2_spill.json"), S.p("in", "ams2.json"), "--probe", "--date=" + D])
            A, B = jload(S.p("in", "ams.json"), []), jload(S.p("in", "ams2.json"), [])
            json.dump(A + B, open(S.p("in", "ams.json"), "w", encoding="utf-8"))
            S.note("ams merge", "%d + %d blocks -> in/ams.json" % (len(A), len(B)))
        else:
            S.note("ams merge", "no history workbook (in/ams2_spill.json): live workbook only")
    else:
        S.note("parse_ams", "no in/ams_spill.json: %s" % ("in/ams.json used as it is" if S.has("in", "ams.json") else "AMS MISSING"))
    if S.has("in", "edits_dl") and os.listdir(S.p("in", "edits_dl")):
        S.run("edits", [T("edits.py"), "collect", S.p("in", "edits_dl"), S.p("in", "edits.json")], ok="EDITS OK")
    elif not S.has("in", "edits.json"):
        json.dump({"edits": []}, open(S.p("in", "edits.json"), "w"))
        S.note("edits", "no app edit files: in/edits.json = {\"edits\": []}")
    else:
        S.note("edits", "no in/edits_dl: in/edits.json kept")
    if S.has("in", "state.json"):
        S.run("state_merge --find", [T("state_merge.py"), S.p("in", "state.json"), "--find"])
    else:
        S.note("state_merge --find", "no in/state.json (cold start)")
    if S.has("in", "reg_Register.json"):
        hist = sorted(glob.glob(S.p("in", "reg_History_*_H[12].json"))) or ([S.p("in", "reg_History.json")] if S.has("in", "reg_History.json") else [])
        S.run("regjoin2", [T("idp11.py"), "regjoin2", S.p("in", "register.json"), S.p("in", "reg_Register.json")] + hist, ok="REGJOIN OK")
    # match.py
    roster = S.p("in", "roster.txt")
    if not S.has("in", "roster.txt"):
        S.fail("match", "in/roster.txt missing (write it from the service list, spec 6.1)")
    argv = [T("match.py"), S.opt("in", "state.json"), "MISSING" if a.as_missing else S.opt("in", "as_today.json"),
            S.opt("in", "wards.json"), S.opt("in", "ams.json"), S.p("out"), "--date", dmy(D), "--roster", roster]
    if S.has("in", "last_delta_sent.txt"):
        argv += ["--last-delta-sent", open(S.p("in", "last_delta_sent.txt")).read().strip()]
    if S.has("in", "as_yday.json"):
        argv += ["--as-yday", S.p("in", "as_yday.json")]
    if a.as_missing:
        argv += ["--as-missing"]
    elif not S.has("in", "as_today.json"):
        S.fail("match", "in/as_today.json missing: wait for the AS list, or after 08:00 Beirut run prep --as-missing")
    upd = [S.p("in", f) for f in ("email_today.txt", "service_list.json") if S.has("in", f)]
    if upd:
        argv += ["--update-text"] + upd
    if a.allow_orphans:
        argv += ["--allow-orphans"]
    if S.has("in", "orphans_ok.txt"):
        argv += ["--orphans-confirmed", S.p("in", "orphans_ok.txt")]
    S.n += 1
    r = subprocess.run([PY] + argv, capture_output=True, text=True, cwd=W)
    open(os.path.join(S.logs, "prep_%02d_match.txt" % S.n), "w", encoding="utf-8").write(r.stdout + r.stderr)
    first = next((l for l in r.stdout.splitlines() if l.startswith("census ")), "")
    if r.returncode == 2:
        al = next((l for l in r.stdout.splitlines() if l.startswith("ORPHAN ALERT")), "orphan guard")
        S.fail("match", "%s (check the names printed PRESENT in out/stage_logs, then in/orphans_ok.txt or --allow-orphans)" % al)
    if r.returncode != 0 or not first:
        S.fail("match", "exit %d: %s" % (r.returncode, ((r.stderr or r.stdout).strip().splitlines() or ["no output"])[-1][:300]))
    S.note("match", first[:300])
    fl = open(S.p("out", "flags.txt"), encoding="utf-8").read().splitlines() if S.has("out", "flags.txt") else []
    for k in ("removed:", "re-entered:", "possibly gone:", "kept:"):
        c = sum(1 for f in fl if f.startswith(k))
        if c:
            S.note("membership", "%d %s line(s) in out/flags.txt" % (c, k.rstrip(":")))
    n = write_day_updates(S.p("out", "packets.txt"), S.p("out", "day_updates.txt"))
    S.note("day updates", "out/day_updates.txt: %d census packets" % n)
    if S.has("in", "service_list.json"):
        np_, nw = write_app_handoffs(S.p("in", "service_list.json"), S.p("out", "app_handoffs.txt"))
        S.note("app write-ups", "out/app_handoffs.txt: %d patients, %d with a write-up" % (np_, nw))
    if S.has("in", "cultures.txt"):
        S.run("cultures", [T("cultures.py"), S.p("in", "cultures.txt"), S.p("out", "census.json"), S.p("out"), "--date", D,
                           "--archive", S.opt("in", "cx_archive.json")], ok="CULTURES OK")
    else:
        S.note("cultures", "no in/cultures.txt: cultures not read")
    base_fail = None
    if a.skip_base:   # T3: the base by hand; every other prep step still runs
        S.note("base", "SKIPPED (--skip-base): %s" % ("synth_base.py kept as it is" if S.has("synth_base.py")
                                                      else "no synth_base.py yet: write it before build"))
    else:
        S.soft = True     # T3: a base failure no longer stops the later prep steps; prep still ends STAGE FAIL: base
        try:
            o = S.run("base", [T("idp10.py"), "base", S.opt("in", "state.json"), S.p("out", "census.json"), S.opt("in", "register.json"),
                               S.p("synth_base.py"), "--date", D], ok="BASE OK")
            for l in base_lines(o):   # T8
                S.note("base", l[:300])
        except StageFail as e:
            base_fail = str(e)
        finally:
            S.soft = False
    if S.has("in", "reg_Verification.json"):
        S.run("vqueue", [T("idp11.py"), "vqueue", S.p("in", "reg_Verification.json"), "--date", D], ok="VQUEUE OK", tee="out/vqueue.txt")
    else:
        S.note("vqueue", "no in/reg_Verification.json: Verification not read")
    if S.has("in", "feed_now", "review.json"):
        S.run("review", [T("idp11.py"), "review", S.p("in", "feed_now", "review.json"), S.p("out"), "--date", D])
    # Chris's reply to yesterday's reconciliation
    if S.has("in", "recon_prev.txt"):
        S.run("recon_prev", [T("recon_reply.py"), "prev", S.p("in", "recon_prev.txt"), S.p("in", "recon_prev.json")], ok="PREV OK")
    if S.has("in", "recon_reply.txt") and open(S.p("in", "recon_reply.txt"), encoding="utf-8", errors="ignore").read().strip():
        if not S.has("in", "recon_prev.json"):
            S.fail("recon_reply", "in/recon_reply.txt is not empty but in/recon_prev.txt (the email it answers) is missing")
        argv = [T("recon_reply.py"), S.p("in", "recon_reply.txt"), S.p("in", "recon_prev.json"), S.p("out"), "--date", D]
        if S.has("in", "feed_now", "rules.json"):
            argv += ["--rules-tab", S.p("in", "feed_now", "rules.json")]
        if S.has("in", "feed_now", "answered.json"):
            argv += ["--answered-tab", S.p("in", "feed_now", "answered.json")]
        S.run("recon_reply", argv, ok="REPLY OK")
    else:
        S.note("recon_reply", "no reply to yesterday's reconciliation")
        for f, v in (("answered_rows.json", []), ("rule_rows.json", []), ("undo_ops.json", [])):
            if not S.has("out", f):
                json.dump(v, open(S.p("out", f), "w"))
    argv = [T("recon_reply.py"), "promote", S.p("out"), "--date", D]
    if S.has("in", "feed_now", "rules.json"):
        argv += ["--rules-tab", S.p("in", "feed_now", "rules.json")]
    if S.has("out", "chris_answers.json"):
        argv += ["--answers", S.p("out", "chris_answers.json")]
    S.run("rules", argv, ok="PROMOTE OK")
    shutil.copy(S.p("out", "active_rules.txt"), S.p("in", "active_rules.txt"))
    if S.has("in", "service_list.json") and S.has("in", "roster_yday.txt"):
        S.run("svccheck", [T("idp11.py"), "svccheck", S.p("in", "service_list.json"), S.p("in", "roster_yday.txt")], ok="SVCCHECK")
    else:
        S.note("svccheck", "service list or in/roster_yday.txt missing: not checked")
    if base_fail:
        S.fail("base", "%s. Every later prep step ran; fix the cause and run prep again, or write synth_base.py by hand and "
               "run prep --skip-base" % base_fail[:300])
    return "census %s" % first.split()[1] if first else ""


# ------------------------------------------------------------------ build
def build(a, S):
    D = a.date
    if not S.has("synth_delta.py"):
        S.fail("apply", "synth_delta.py missing")
    S.run("apply", [T("idp10.py"), "apply", S.p("synth_base.py"), S.p("synth_delta.py"), S.p("synth.py"), "--date", D],
          ok="APPLY OK", must_not="carried unchanged (no DELTA)")
    S.run("validate_synth", [T("validate_synth.py"), S.p("synth.py"), S.p("out", "census.json"), D] +
          ([S.p("in", "state.json")] if S.has("in", "state.json") else []), ok="0 errors")
    if S.has("in", "state.json"):
        S.run("evolve", [T("idp10.py"), "evolve", S.p("synth.py"), S.p("in", "state.json"), S.p("out"), "--date", D], ok=" 0 unexplained")
    else:
        S.note("evolve", "cold start: nothing to compare")
    argv = [T("coverage_gate.py"), S.p("synth.py"), S.p("out", "census.json"), S.p("out"), "--date", D,
            "--day-updates", S.p("out", "day_updates.txt")]
    if S.has("in", "service_list.json"):
        argv += ["--service-list", S.p("in", "service_list.json")]
    if S.has("out", "cultures.json"):
        argv += ["--cultures", S.p("out", "cultures.json")]
    if a.coverage_warn:
        argv += ["--warn-only"]
    S.run("coverage gate", argv, ok_any=("COVERAGE OK", "COVERAGE WARN"))
    if not S.has("out", "roster_out.txt"):
        S.fail("id_list", "out/roster_out.txt missing (write the ID list lines, spec 8)")
    argv = [T("id_list.py"), S.p("out", "roster_out.txt"), "--date", D]
    if S.has("in", "state.json"):
        argv[2:2] = ["--state", S.p("in", "state.json")]
    o = S.run("id_list", argv, tee="out/id_list_email.txt", summary="out/id_list_email.txt written")
    S.note("id_list", "%d patient line(s) under %d group header(s)" % (
        sum(1 for l in o.splitlines() if l.strip() and not l.endswith(":")), sum(1 for l in o.splitlines() if l.endswith(":"))))
    S.run("checks_R idlist", [T("checks_R.py"), "idlist", S.p("out", "id_list_email.txt")], ok="CHECKS R OK")
    delta = jload(S.p("out", "delta.json"), {}) or {}
    as_today = "MISSING" if delta.get("as_missing") else S.opt("in", "as_today.json")
    out = S.run("build.py", [T("build.py"), S.work, a.long_date, "--date", D, "--as-today", as_today, "--ams", S.opt("in", "ams.json")],
                ok=("PREFLIGHT OK", "BUILD OK"))
    if not re.search(r"^BUILD OK$", out, re.M):
        S.fail("build.py", "no 'BUILD OK' line on its stdout")
    for l in dict.fromkeys(l.strip() for l in out.splitlines() if l.startswith("AD order:") or l.startswith("coverage:")):
        S.note("build.py", l[:300])
    S.run("recap_html", [tool("recap_html.py"), S.p("out", "recap_email.txt"), S.p("out", "recap_email.html")], ok="RECAP HTML OK")
    cen = S.p("out", "census_wa.json") if S.has("out", "census_wa.json") else S.p("out", "census.json")
    S.run("wa_handout", [tool("wa_handout.py"), S.p("out", "id_list_email.txt"), cen, S.p("synth.py"), S.p("out", "wa_handout.txt"),
                         dmy(D)], ok="WA OK")
    sent = ["recap_email.txt", "recap_email.html", "wa_handout.txt", "delta2.html", "delta2.txt", "id_list_email.txt"]
    S.run("checks_R text", [T("checks_R.py"), "text"] + [S.p("out", f) for f in sent], ok="CHECKS R OK")
    return "%s%s" % ("delta: AS list missing (one-line report) " if delta.get("as_missing") else "", "outputs to send: " + ", ".join("out/" + f for f in sent))


# ------------------------------------------------------------------ post
FEED_READS = ["'Feed Patients'!A1:AB5000 -> in/feed_now/patients.json", "'Feed Antimicrobials'!A1:H20000 -> antimicrobials.json",
              "'Feed Micro'!A1:G20000 -> micro.json", "'Feed Cultures'!A1:M20000 -> labcx.json",
              "'Feed Daily Report'!A1:F20000 -> dailyreport.json", "'Feed Changes'!A1:A100000 -> changes.json"]
ANSWERED_HDR = ["Key", "Date answered", "Item", "Chris answer", "Applied as", "Until"]
RULES_HDR = ["No", "Date", "Rule", "From", "Status", "Notes"]


def append_ops(tab, now_values, rows, hdr, width="F"):
    """update_values ops appending rows after the rows a tab holds now (header written when the tab is empty)."""
    if not rows:
        return []
    ops, start = [], len(now_values) + 1
    if not now_values:
        ops.append({"range": "'%s'!A1:%s1" % (tab, width), "values": [hdr]}); start = 2
    for i in range(0, len(rows), 40):
        part = rows[i:i + 40]
        ops.append({"range": "'%s'!A%d:%s%d" % (tab, start + i, width, start + i + len(part) - 1), "values": part})
    return ops


def merged_rules(S):
    """'Learned Rules' as read this morning, statuses as they will stand after today's writes, plus today's rows."""
    vals = [list(r) for r in tab_values(S.p("in", "feed_now", "rules.json"))]
    if not vals:
        vals = [RULES_HDR]
    undo = {o["range"] for o in jload(S.p("out", "undo_ops.json"), []) or []}
    prom = {o["range"] for o in jload(S.p("out", "promote_ops.json"), []) or []}
    for i, r in enumerate(vals, 1):
        rng = "'Learned Rules'!E%d" % i
        r += [""] * (6 - len(r))
        if rng in undo:
            r[4] = "undone"
        elif rng in prom:
            r[4] = "active"
    vals += [list(r) for r in jload(S.p("out", "rule_rows.json"), []) or []]
    return {"values": vals}


STALE_OPS = ("ops.json", "vrows_ops.json", "vreply_ops.json", "review_ops.json", "vreq_ops.json", "schema_feed_ops.json",
             "schema_reg_ops.json")


def post(a, S):
    D = a.date
    # T1: no op file of an earlier post may survive into this one, and none is written for a tab whose read is missing
    shutil.rmtree(S.p("out", "post_ops"), ignore_errors=True)
    for f in STALE_OPS:
        if os.path.exists(S.p("out", "feed", f)):
            os.remove(S.p("out", "feed", f))
    for f in ("state_new.json", "census.json"):
        if not S.has("out", f):
            S.fail("post", "out/%s missing (run build first)" % f)
    nowdir = S.p("in", "feed_before") if S.has("in", "feed_before") else S.p("in", "feed_now")
    gate_reads(S, "feed reads", nowdir)
    if nowdir != S.p("in", "feed_now"):
        gate_reads(S, "feed reads", S.p("in", "feed_now"))
    if S.has("in", "reg_Verification.json"):
        gate_one(S, "feed reads", "in", "reg_Verification.json")
    vreq = jload(S.p("out", "verification_requests.json"), None) if S.has("out", "verification_requests.json") else None
    if S.has("out", "verification_requests.json") and not isinstance(vreq, list):
        S.fail("verification requests", "out/verification_requests.json is not a JSON list of {key, column, value_checked, "
               "value_in_source, source, severity, note}")
    if vreq and not S.has("in", "reg_Verification.json"):
        S.fail("verification requests", "%d request(s) in out/verification_requests.json but in/reg_Verification.json was not "
               "read (read 'Verification'!A1:N5000 first)" % len(vreq))
    if S.has("in", "ams_spill.json"):
        S.run("ams_blocks", [T("ams_blocks.py"), S.p("in", "ams_spill.json"), S.p("out", "state_new.json"), S.p("out", "census.json"),
                             S.p("out"), "--date", D, "--edits", S.p("in", "edits.json")], ok="AMS BLOCKS OK")
    else:
        S.note("ams_blocks", "no live workbook (in/ams_spill.json): the feed gets MISSING")
    if S.has("in", "reg_Index.json"):
        S.run("final", [T("idp11.py"), "final", S.p("out", "state_new.json"), S.p("in", "reg_Index.json"), S.opt("out", "cultures.json"),
                        "--date", D], ok="FINAL OK")
    else:
        S.note("final", "no in/reg_Index.json: no record leaves the state today")
    S.run("watch", [T("idp10.py"), "watch", S.p("out", "state_new.json"), S.opt("out", "cultures.json"), S.opt("in", "register.json"),
                    S.p("out", "register"), "--date", D], ok="WATCH OK")
    st = jload(S.p("out", "state_new.json"), {}) or {}
    if "backfill" not in st:
        if not S.has("in", "bfq.json"):
            S.fail("backfill", "out/state_new.json has no backfill key and in/bfq.json is missing (download 'IDP Backfill Queue 2026-10-30')")
        st["backfill"] = jload(S.p("in", "bfq.json"))
        json.dump(st, open(S.p("out", "state_new.json"), "w"))
        S.note("backfill", "backfill key restored from in/bfq.json")
    else:
        S.note("backfill", "backfill key present")
    # T10: the run's own time, for tomorrow's "since yesterday's run" cutoff
    st = jload(S.p("out", "state_new.json"), {}) or {}
    st["last_run_utc"] = run_start(S, D) or utc_now()
    json.dump(st, open(S.p("out", "state_new.json"), "w"))
    S.note("last run", "state last_run_utc = %s (%s)" % (st["last_run_utc"], "this run's start, out/run_start_utc.txt"
                                                         if run_start(S, D) else "now: no prep start recorded for today"))
    S.run("feed", [T("idp11.py"), "feed", S.p("out", "state_new.json"), S.p("out", "census.json"), S.opt("out", "ams_blocks.json"),
                   S.opt("out", "cultures.json"), nowdir, S.p("out", "feed"), "--date", D, "--evolution", S.p("out", "evolution.json"),
                   "--strict"], ok="FEED OPS")
    sch = S.run("schema", [T("idp11.py"), "schema", "--date", D], ok="IDP Feed Meta:",
                summary="SCHEMA: Feed Schema + Feed Meta (feed), Register Schema (register) -> out/feed/schema_*_ops.json")
    feed_s, reg_s, meta = None, None, None
    for l in sch.splitlines():
        if l.startswith("IDP Feed Meta: "):
            meta = json.loads(l.split(": ", 1)[1])
        elif l.startswith("IDP Feed: "):
            feed_s = json.loads(l.split(": ", 1)[1])
        elif l.startswith("IDP Discharge Register: "):
            reg_s = json.loads(l.split(": ", 1)[1])
    json.dump([x for x in (feed_s, meta) if x], open(S.p("out", "feed", "schema_feed_ops.json"), "w"))
    json.dump([reg_s] if reg_s else [], open(S.p("out", "feed", "schema_reg_ops.json"), "w"))
    if S.has("in", "reg_Register.json") and S.has("in", "reg_Verification.json"):
        S.run("checkreg", [T("idp11.py"), "checkreg", S.p("in", "reg_Register.json"), S.p("out", "feed", "feed_desired.json"),
                           S.p("in", "reg_Verification.json"), S.opt("out", "cultures.json"), S.p("out", "feed"), "--date", D,
                           "--index", S.opt("in", "reg_Index.json")], ok="CHECKREG OK")
        if not S.has("out", "feed", "replies.json"):
            json.dump([], open(S.p("out", "feed", "replies.json"), "w"))
            S.note("replies", "out/feed/replies.json missing: written as [] (no Verification answers)")
        S.run("vwrite", [T("idp11.py"), "vwrite", S.p("in", "reg_Verification.json"), S.p("out", "feed", "replies.json"), S.p("out", "feed")],
              ok="VWRITE OK")
    else:
        S.note("checkreg", "register or Verification not read: register check skipped")
    if vreq:   # T6: the synthesis's Verification requests -> C- rows after checkreg's
        argv = [T("idp11.py"), "vrequests", S.p("in", "reg_Verification.json"), S.p("out", "verification_requests.json"),
                S.p("out", "feed"), "--date", D]
        if os.path.exists(S.p("out", "feed", "vrows_ops.json")):
            argv += ["--after", S.p("out", "feed", "vrows_ops.json")]
        S.run("verification requests", argv, ok="VREQUESTS OK")
    else:
        S.note("verification requests", "no out/verification_requests.json entries")
    if S.has("out", "review_replies.json"):
        if not S.has("in", "feed_now", "review.json"):
            S.fail("reviewreply", "out/review_replies.json present but in/feed_now/review.json missing")
        S.run("reviewreply", [T("idp11.py"), "reviewreply", S.p("out", "review_replies.json"), S.p("in", "feed_now", "review.json"),
                              S.p("out", "feed"), "--date", D], ok="REVIEWREPLY OK")
    # state for tomorrow: a patch on the morning's chain, or a full base (T5: post decides, the INDEX says why)
    a.full_reasons = full_base_reasons(S, D)
    shutil.rmtree(S.p("out", "patch_parts"), ignore_errors=True)
    if not a.full_reasons:
        o = S.run("state patch", [T("drive_state.py"), "patch", S.p("in", "state.json"), S.p("out", "state_new.json"), S.p("out", "patch_parts")],
                  ok="PATCH OK")
        if "PATCH LARGE" in o:
            a.full_reasons.append("PATCH LARGE (the patch is over 60% of the full state)")
            shutil.rmtree(S.p("out", "patch_parts"), ignore_errors=True)
    if a.full_reasons:
        shutil.rmtree(S.p("out", "state_parts"), ignore_errors=True)
        S.run("state base", [T("state_io.py"), "pack", S.p("out", "state_new.json"), S.p("out", "state_parts"), "12000"])
        S.note("state base", "FULL BASE: " + "; ".join(a.full_reasons))
    # reconciliation: the feed as Gemini had it, answered items and learned rules as they stand after today's writes
    ans = tab_values(S.p("in", "feed_now", "answered.json")) or [ANSWERED_HDR]
    ans = ans + (jload(S.p("out", "answered_rows.json"), []) or [])
    json.dump({"values": ans}, open(S.p("out", "answered_merged.json"), "w"), ensure_ascii=False)
    json.dump(merged_rules(S), open(S.p("out", "rules_merged.json"), "w"), ensure_ascii=False)
    for f in ("missing_cultures.txt", "fixed.txt"):
        if not os.path.exists(S.p("out", f)):
            open(S.p("out", f), "w").close()
    argv = [T("recon.py"), "--date", D, "--out", S.p("out", "recon.txt")]
    for flag, path in (("--svc", "in/service_list.json"), ("--roster-yday", "in/roster_yday.txt"), ("--recaps", "in/recaps_yday.txt"),
                       ("--state", "out/state_new.json"), ("--census", "out/census.json"), ("--coverage", "out/feed/coverage.txt"),
                       ("--vqueue", "out/vqueue.txt"), ("--queue", "in/reg_queue.json"), ("--glog", "in/reg_glog.json"),
                       ("--digest", "in/digest.txt"), ("--cultures", "in/cultures.txt"), ("--missing", "out/missing_cultures.txt"),
                       ("--fixed", "out/fixed.txt"), ("--reg-sheet", "in/reg_Register.json"), ("--evolution", "out/evolution.json"),
                       ("--review", "in/feed_now/review.json"), ("--resolved", "out/answered_merged.json"),
                       ("--learned", "out/rules_merged.json")):
        argv += [flag, S.p(*path.split("/"))]
    argv += ["--feed-dir", nowdir]
    items = [S.p("out", f) for f in ("run_items_prep.txt", "run_items.txt")
             if os.path.exists(S.p("out", f)) and (f == "run_items.txt" or S.has("out", f))]
    if items:   # prep's own run items (chain check) and the agent's
        open(S.p("out", "run_items_all.txt"), "w", encoding="utf-8").write(
            "\n".join(open(f, encoding="utf-8", errors="ignore").read().strip("\n") for f in items) + "\n")
        argv += ["--items", S.p("out", "run_items_all.txt")]
    S.run("recon", argv, ok="RECON OK")
    S.run("checks_R recon", [T("checks_R.py"), "text", S.p("out", "recon.txt")], ok="CHECKS R OK")
    n, calls = write_post_ops(a, S)
    S.note("post ops", "out/post_ops/INDEX.txt: %d op files, %d write call(s) for the agent" % (n, calls))
    return "post ops %d files, %d calls" % (n, calls)


def full_base_reasons(S, D):
    """T5: write a full base instead of a patch when the morning's chain says so (in/chain.txt) or there is no state."""
    if not S.has("in", "state.json"):
        return ["cold start (no in/state.json)"]
    if not S.has("in", "chain.txt"):
        S.note("state", "no in/chain.txt: full-base triggers (6 patches, fallback base, base dated today) not checked")
        return []
    _, _, _, info = chain_check(open(S.p("in", "chain.txt"), encoding="utf-8", errors="ignore").read(), D)
    r = []
    if info["patches"] is not None and info["patches"] >= 6:
        r.append("%d patches already follow base %s" % (info["patches"], info["base"]))
    if info["fallback"]:
        r.append("the chain fell back to the older base %s" % info["base"])
    if info["base"] == D:
        r.append("the chain's base is dated today (%s)" % D)
    return r


def write_post_ops(a, S):
    D = a.date
    tg = jload(S.p("in", "targets.json"), {}) or {}
    name = {"feed": "IDP Feed", "register": "IDP Discharge Register", "state": "IDP_State folder"}
    tid = lambda k: tg.get("state_folder" if k == "state" else k) or "<id: spec section 2>"
    d = S.p("out", "post_ops")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    chk = "chkw"
    entries = []

    def add(what, target, ops, verify, kind="sheet"):
        if not ops:
            return
        nn = "%02d" % (len(entries) + 1)
        f = "%s_%s.json" % (nn, what)
        json.dump(ops, open(os.path.join(d, f), "w", encoding="utf-8"), ensure_ascii=True)
        entries.append((nn, f, target, ops, verify.replace("{f}", f).replace("{nn}", nn), kind))

    feed_ops = jload(S.p("out", "feed", "ops.json"), []) or []
    add("feed_ops", "feed", feed_ops, chk + "; after the last op re-read the six tabs (" + "; ".join(FEED_READS) +
        ") and run idp11.py feedcheck out/feed/feed_desired.json in/feed_now --date %s: FEED MATCH (its Meta op is replaced by 02)" % D)
    add("feed_schema", "feed", jload(S.p("out", "feed", "schema_feed_ops.json"), []) or [], chk)
    add("register_schema", "register", jload(S.p("out", "feed", "schema_reg_ops.json"), []) or [], chk)
    add("verification_rows", "register", jload(S.p("out", "feed", "vrows_ops.json"), []) or [], chk)
    add("verification_requests", "register", jload(S.p("out", "feed", "vreq_ops.json"), []) or [], chk)
    add("verification_replies", "register", jload(S.p("out", "feed", "vreply_ops.json"), []) or [], chk)
    add("review_replies", "feed", jload(S.p("out", "feed", "review_ops.json"), []) or [] if S.has("out", "review_replies.json") else [],
        chk + " (columns H..K only)")
    arows = jload(S.p("out", "answered_rows.json"), []) or []
    for f in ("answered", "rules"):   # T1 (gated at the start of post): an append needs the tab's header row as read
        if read_problem(S.p("in", "feed_now", f + ".json")):
            S.fail("post ops", "in/feed_now/%s.json %s" % (f, read_problem(S.p("in", "feed_now", f + ".json"))))
    if any(not (r[4] if len(r) > 4 else "") for r in arows):
        print("  post ops: WARN %d answered row(s) without 'Applied as' (fill out/answered_rows.json, rerun post)"
              % sum(1 for r in arows if not (r[4] if len(r) > 4 else "")))
    add("answered_rows", "feed", append_ops("Answered Items", tab_values(S.p("in", "feed_now", "answered.json")), arows, ANSWERED_HDR), chk)
    add("rule_rows", "feed", append_ops("Learned Rules", tab_values(S.p("in", "feed_now", "rules.json")),
                                        jload(S.p("out", "rule_rows.json"), []) or [], RULES_HDR), chk)
    add("undo_ops", "feed", jload(S.p("out", "undo_ops.json"), []) or [], chk)
    add("rule_promote", "feed", jload(S.p("out", "promote_ops.json"), []) or [], chk)
    files = []
    if os.path.isdir(S.p("out", "patch_parts")) and glob.glob(S.p("out", "patch_parts", "patch*.txt")):
        parts = sorted(glob.glob(S.p("out", "patch_parts", "patch*.txt")), key=lambda p: int(re.search(r"(\d+)", os.path.basename(p)).group(1)))
        files = [{"title": "IDP State Patch %s (part %d of %d)" % (D, i, len(parts)), "path": os.path.relpath(p, S.work),
                  "bytes": os.path.getsize(p)} for i, p in enumerate(parts, 1)]
    elif os.path.isdir(S.p("out", "state_parts")):
        parts = sorted(glob.glob(S.p("out", "state_parts", "part*.txt")), key=lambda p: int(re.search(r"(\d+)", os.path.basename(p)).group(1)))
        files = [{"title": "IDP State %s (part %d of %d)" % (D, i, len(parts)), "path": os.path.relpath(p, S.work),
                  "bytes": os.path.getsize(p)} for i, p in enumerate(parts, 1)]
    reasons = getattr(a, "full_reasons", None) or []
    state_kind = ("FULL BASE (%s): " % "; ".join(reasons)) if reasons and files and "Patch" not in files[0]["title"] else \
        ("patch on the morning's chain: " if files else "")
    add("state_parts", "state", files, state_kind + "create_file per entry (title, parentId = target, text/plain, disableConversionToGoogleType "
        "true, textContent = the file verbatim); returned fileSize must equal bytes; download_file_content it and run "
        "drive_state.py verify <saved> <path>: drive part MATCH", kind="drive")
    L = ["POST OPS %s: perform in this order, after every send. Sheets ops: one update_values call per op, range and values "
         "verbatim (print op k with: python3 $T/run.py op out/post_ops/<file> <k>). Drive files: one create_file per entry." % D,
         "Targets: " + "; ".join("%s = %s %s" % (k, name[k], tid(k)) for k in ("feed", "register", "state")),
         "chkw = after op k of file NN_x.json: get_values on the op's range, save it as in/readback/NN_k.json, then "
         "python3 $T/run.py chkw out/post_ops/NN_x.json k in/readback/NN_k.json must print CHKW MATCH (mismatch: rewrite once).",
         "Input mode: update_values with valueInputOption USER_ENTERED: a value written with a leading apostrophe ('05/09/26, "
         "'100001) is stored as text without it; chkw expects it so (a read-back that still shows the apostrophe is a MISMATCH).",
         "State: " + (("FULL BASE IDP State %s, because: %s" % (D, "; ".join(reasons))) if reasons else
                      "patch IDP State Patch %s on the morning's chain" % D),
         "", "NN | file | target | calls | verify"]
    calls = 0
    for nn, f, target, ops, verify, kind in entries:
        calls += len(ops)
        L.append("%s | %s | %s %s | %d %s | %s" % (nn, f, name[target], tid(target), len(ops), "file(s)" if kind == "drive" else "call(s)", verify))
    if not entries:
        L.append("(nothing to write)")
    L += ["", "A failed write: retry once; a second failure is a FAIL for the closing note. Never write a cell no op names."]
    open(os.path.join(d, "INDEX.txt"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    return len(entries), calls


# ------------------------------------------------------------------ op / chkw
def norm_cell(v):
    """A desired cell as USER_ENTERED stores it: one leading apostrophe makes the cell text and is not stored."""
    v = "" if v is None else str(v)
    return v[1:] if v.startswith("'") else v


def read_cell(v):
    """A read-back cell, compared verbatim (T9: an apostrophe still there means the write was not USER_ENTERED)."""
    return "" if v is None else str(v)


def trim(rows, f=norm_cell):
    out = [[f(c) for c in r] for r in rows]
    for r in out:
        while r and r[-1] == "":
            r.pop()
    while out and not out[-1]:
        out.pop()
    return out


def cmd_op(argv):
    ops = jload(argv[0], [])
    n = int(argv[1])
    print(json.dumps(ops[n - 1], ensure_ascii=False))
    return 0


def cmd_chkw(argv):
    ops = jload(argv[0], [])
    n = int(argv[1])
    op = ops[n - 1]
    want = trim(op.get("values") or [])
    got = trim(tab_values(argv[2]), read_cell)
    if len(got) < len(want):
        got += [[] for _ in range(len(want) - len(got))]
    for i, (w, g) in enumerate(zip(want, got)):
        g = g + [""] * (len(w) - len(g))
        for j, (x, y) in enumerate(zip(w, g)):
            if x != y and not (x == "" and y == ""):
                print("CHKW MISMATCH %s op %d: row %d col %d: wrote %r, read %r" % (os.path.basename(argv[0]), n, i + 1, j + 1, x[:80], y[:80]))
                return 1
    print("CHKW MATCH %s op %d: %d row(s) %s" % (os.path.basename(argv[0]), n, len(want), op.get("range")))
    return 0


# ------------------------------------------------------------------ sendcheck / chaincheck
def find_field(o, name):
    """A field of a Gmail get_message result: a key (any depth, any case) or a {name, value} header."""
    lname = name.lower()
    if isinstance(o, dict):
        for k, v in o.items():
            if k.lower() == lname and isinstance(v, str):
                return v
        if str(o.get("name", "")).lower() == lname and isinstance(o.get("value"), str):
            return o["value"]
        for v in o.values():
            r = find_field(v, name)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_field(v, name)
            if r is not None:
                return r
    return None


def compare_sent(got, want):
    """EXACT (byte-exact) / EQ_mod_trailing_ws (line endings and trailing blanks only) / DIFF (first differing line)."""
    if got.encode("utf-8") == want.encode("utf-8"):
        return "EXACT", ""
    g = [l.rstrip() for l in got.replace("\r\n", "\n").split("\n")]
    w = [l.rstrip() for l in want.replace("\r\n", "\n").split("\n")]
    while g and not g[-1]:
        g.pop()
    while w and not w[-1]:
        w.pop()
    if g == w:
        return "EQ_mod_trailing_ws", ""
    for i in range(max(len(g), len(w))):
        x, y = (g[i] if i < len(g) else "<end>"), (w[i] if i < len(w) else "<end>")
        if x != y:
            return "DIFF", "line %d: sent %r, file %r" % (i + 1, x[:80], y[:80])
    return "DIFF", ""


def cmd_sendcheck(argv):
    """T7: run.py sendcheck <sent_message.json> <field=file>... : the sent email (a Gmail get_message result) against the
    files it was built from. One line per field; SENDCHECK OK when every field is EXACT or EQ_mod_trailing_ws."""
    if len(argv) < 2 or any("=" not in x for x in argv[1:]):
        print("usage: run.py sendcheck <sent_message.json> <field=file>...  (e.g. subject=out/subject.txt plaintextBody=out/recon.txt)")
        return 2
    msg = jload(argv[0])
    if msg is None:
        print("SENDCHECK FAIL: %s does not parse" % argv[0]); return 1
    bad = 0
    for spec in argv[1:]:
        field, path = spec.split("=", 1)
        got = find_field(msg, field)
        if got is None:
            print("%s: MISSING (no field %r in the sent message)" % (field, field)); bad += 1; continue
        try:
            want = open(path, encoding="utf-8", newline="").read()
        except Exception as e:
            print("%s: DIFF (file %s unreadable: %s)" % (field, path, e)); bad += 1; continue
        verdict, why = compare_sent(got, want)
        print("%s: %s %s%s" % (field, verdict, path, (" (" + why + ")") if why else ""))
        bad += verdict == "DIFF"
    print(("SENDCHECK OK: %d field(s)" % (len(argv) - 1)) if not bad else ("SENDCHECK FAIL: %d of %d field(s) differ" % (bad, len(argv) - 1)))
    return 1 if bad else 0


def cmd_chaincheck(argv):
    """T4: run.py chaincheck <chain.txt> --date YYYY-MM-DD [--state in/state.json] [--accept-chain]"""
    ap = argparse.ArgumentParser(prog="run.py chaincheck")
    ap.add_argument("chain"); ap.add_argument("--date", required=True); ap.add_argument("--state"); ap.add_argument("--accept-chain", action="store_true")
    a = ap.parse_args(argv)
    st = (jload(a.state, {}) or {}).get("date") if a.state else None
    text = open(a.chain, encoding="utf-8", errors="ignore").read() if os.path.exists(a.chain) else ""
    fails, cw, warns, info = chain_check(text, a.date, st)
    if cw and not a.accept_chain:
        fails += cw
    else:
        warns += cw
    if fails:
        print("CHAIN CHECK FAIL: " + "; ".join(fails)); return 1
    if warns:
        print("CHAIN CHECK WARN: " + "; ".join(warns) + " (a run item for the reconciliation)"); return 0
    print("CHAIN CHECK OK: base %s + %d patch(es) -> state dated %s (yesterday)%s" % (
        info["base"], info["patches"], info["state"], "; fallback base: post writes a full base" if info["fallback"] else ""))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("op", "chkw", "sendcheck", "chaincheck"):
        return {"op": cmd_op, "chkw": cmd_chkw, "sendcheck": cmd_sendcheck, "chaincheck": cmd_chaincheck}[sys.argv[1]](sys.argv[2:])
    ap = argparse.ArgumentParser(description="IDP daily run stages")
    ap.add_argument("stage", choices=("prep", "build", "post"))
    ap.add_argument("--date", required=True); ap.add_argument("--long-date"); ap.add_argument("--work", default=".")
    ap.add_argument("--as-missing", action="store_true"); ap.add_argument("--allow-orphans", action="store_true")
    ap.add_argument("--coverage-warn", action="store_true", help="coverage gate reports misses without stopping the build")
    ap.add_argument("--skip-base", action="store_true", help="prep: do not run idp10 base (synth_base.py written by hand)")
    ap.add_argument("--accept-chain", action="store_true", help="prep: continue past 'sha mismatch'/'not applied' chain lines (WARN + run item)")
    a = ap.parse_args()
    dt.date.fromisoformat(a.date)
    if a.stage == "build" and not a.long_date:
        a.long_date = dt.date.fromisoformat(a.date).strftime("%d %B %Y")
    S = Stage(a.stage, os.path.abspath(a.work))
    try:
        res = {"prep": prep, "build": build, "post": post}[a.stage](a, S)
    except StageFail:
        return 1
    print("STAGE OK: %s %s%s" % (a.stage, a.date, (": " + res) if res else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
