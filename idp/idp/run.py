#!/usr/bin/env python3
"""Stage commands for the daily run (Chris, 28.11.2026, decision A). Run from the work dir (/tmp/idp).

The agent keeps every MCP read and write (Gmail, Drive, Sheets) and the judgment (roster.txt, synth_delta.py,
roster_out.txt, replies); run.py only runs the local steps, in order, and stops at the first failed gate:

  run.py prep  --date YYYY-MM-DD [--as-missing] [--allow-orphans]
  run.py build --date YYYY-MM-DD --long-date "28 November 2026" [--coverage-warn]
  run.py post  --date YYYY-MM-DD
  run.py op    <ops.json> <n>                       print op n (from 1) of an ops file for update_values
  run.py chkw  <ops.json> <n> <readback.json>       compare op n with a get_values read-back: CHKW MATCH / MISMATCH

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
        self.name, self.work, self.n = name, work, 0
        self.logs = os.path.join(work, "out", "stage_logs")
        os.makedirs(self.logs, exist_ok=True)
        print("STAGE %s (%s)" % (name, work))

    def p(self, *parts):
        return os.path.join(self.work, *parts)

    def has(self, *parts):
        q = self.p(*parts)
        return os.path.exists(q) and (os.path.isdir(q) or os.path.getsize(q) > 0)

    def opt(self, *parts):
        return self.p(*parts) if self.has(*parts) else "MISSING"

    def fail(self, step, reason):
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
    D, W = a.date, S.work
    # feed snapshot before any feed write today (review item 1): post and recon read in/feed_before
    if S.has("in", "feed_now"):
        fb = S.p("in", "feed_before")
        shutil.rmtree(fb, ignore_errors=True)
        shutil.copytree(S.p("in", "feed_now"), fb)
        S.note("feed snapshot", "in/feed_now -> in/feed_before (%d tab files)" % len(os.listdir(fb)))
    else:
        S.note("feed snapshot", "no in/feed_now: nothing to snapshot (feed not read yet?)")
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
    S.run("base", [T("idp10.py"), "base", S.opt("in", "state.json"), S.p("out", "census.json"), S.opt("in", "register.json"),
                   S.p("synth_base.py"), "--date", D], ok="BASE OK")
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


def post(a, S):
    D = a.date
    for f in ("state_new.json", "census.json"):
        if not S.has("out", f):
            S.fail("post", "out/%s missing (run build first)" % f)
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
    nowdir = S.p("in", "feed_before") if S.has("in", "feed_before") else S.p("in", "feed_now")
    if not os.path.isdir(nowdir):
        S.fail("feed", "neither in/feed_before nor in/feed_now: read the feed tabs first")
    S.run("feed", [T("idp11.py"), "feed", S.p("out", "state_new.json"), S.p("out", "census.json"), S.opt("out", "ams_blocks.json"),
                   S.opt("out", "cultures.json"), nowdir, S.p("out", "feed"), "--date", D, "--evolution", S.p("out", "evolution.json")],
          ok="FEED OPS")
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
    if S.has("out", "review_replies.json"):
        if not S.has("in", "feed_now", "review.json"):
            S.fail("reviewreply", "out/review_replies.json present but in/feed_now/review.json missing")
        S.run("reviewreply", [T("idp11.py"), "reviewreply", S.p("out", "review_replies.json"), S.p("in", "feed_now", "review.json"),
                              S.p("out", "feed"), "--date", D], ok="REVIEWREPLY OK")
    # state for tomorrow: a patch on the morning's chain, or a full base
    full = not S.has("in", "state.json")
    shutil.rmtree(S.p("out", "patch_parts"), ignore_errors=True)
    if not full:
        o = S.run("state patch", [T("drive_state.py"), "patch", S.p("in", "state.json"), S.p("out", "state_new.json"), S.p("out", "patch_parts")],
                  ok="PATCH OK")
        full = "PATCH LARGE" in o
    if full:
        shutil.rmtree(S.p("out", "state_parts"), ignore_errors=True)
        S.run("state base", [T("state_io.py"), "pack", S.p("out", "state_new.json"), S.p("out", "state_parts"), "12000"])
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
    if os.path.exists(S.p("out", "run_items.txt")):
        argv += ["--items", S.p("out", "run_items.txt")]
    S.run("recon", argv, ok="RECON OK")
    S.run("checks_R recon", [T("checks_R.py"), "text", S.p("out", "recon.txt")], ok="CHECKS R OK")
    n, calls = write_post_ops(a, S)
    S.note("post ops", "out/post_ops/INDEX.txt: %d op files, %d write call(s) for the agent" % (n, calls))
    return "post ops %d files, %d calls" % (n, calls)


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
    add("verification_replies", "register", jload(S.p("out", "feed", "vreply_ops.json"), []) or [], chk)
    add("review_replies", "feed", jload(S.p("out", "feed", "review_ops.json"), []) or [] if S.has("out", "review_replies.json") else [],
        chk + " (columns H..K only)")
    arows = jload(S.p("out", "answered_rows.json"), []) or []
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
    add("state_parts", "state", files, "create_file per entry (title, parentId = target, text/plain, disableConversionToGoogleType "
        "true, textContent = the file verbatim); returned fileSize must equal bytes; download_file_content it and run "
        "drive_state.py verify <saved> <path>: drive part MATCH", kind="drive")
    L = ["POST OPS %s: perform in this order, after every send. Sheets ops: one update_values call per op, range and values "
         "verbatim (print op k with: python3 $T/run.py op out/post_ops/<file> <k>). Drive files: one create_file per entry." % D,
         "Targets: " + "; ".join("%s = %s %s" % (k, name[k], tid(k)) for k in ("feed", "register", "state")),
         "chkw = after op k of file NN_x.json: get_values on the op's range, save it as in/readback/NN_k.json, then "
         "python3 $T/run.py chkw out/post_ops/NN_x.json k in/readback/NN_k.json must print CHKW MATCH (mismatch: rewrite once).",
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
    v = "" if v is None else str(v)
    return v[1:] if v.startswith("'") else v


def trim(rows):
    out = [[norm_cell(c) for c in r] for r in rows]
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
    got = trim(tab_values(argv[2]))
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


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("op", "chkw"):
        return {"op": cmd_op, "chkw": cmd_chkw}[sys.argv[1]](sys.argv[2:])
    ap = argparse.ArgumentParser(description="IDP daily run stages")
    ap.add_argument("stage", choices=("prep", "build", "post"))
    ap.add_argument("--date", required=True); ap.add_argument("--long-date"); ap.add_argument("--work", default=".")
    ap.add_argument("--as-missing", action="store_true"); ap.add_argument("--allow-orphans", action="store_true")
    ap.add_argument("--coverage-warn", action="store_true", help="coverage gate reports misses without stopping the build")
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
