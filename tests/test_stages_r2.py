#!/usr/bin/env python3
"""Round 2 toolkit fixes T1 to T10 (run.py and the scripts it calls), fictional data only.

Usage: test_stages_r2.py <toolkit idp/idp dir> <workdir> <stage dir of test_stages.py> <day-1 run dir> <day-2 run dir>
The stage dir is the one test_stages.py left after its prep / build / post (copied here, never changed).
Prints "CHECK <name> OK" per check; exit 1 on the first failure; "STAGES R2 TESTS OK" at the end.

  T1  feed tab reads gate (prep and post): empty dir, one missing tab, an empty tab, idp11 feed --strict, Verification
  T2  a prep re-run keeps "Applied as", addrule rows, review_replies, synth_delta.py, roster files
  T3  prep --skip-base; a failed base no longer stops the later prep steps
  T4  chain check (in/chain.txt): OK, sha mismatch (STAGE FAIL / --accept-chain + run item), wrong state, chaincheck
  T5  full base triggers in post: 6 patches, fallback base (also drive_state's fallback line), same-day base
  T6  out/verification_requests.json -> C- row ops
  T7  run.py sendcheck: EXACT / EQ_mod_trailing_ws / DIFF
  T8  NEW / READMISSION lines on the console
  T9  INDEX states USER_ENTERED; chkw compares the read-back verbatim
  T10 last_run_utc written at post, printed by prep
"""
import json, os, re, shutil, subprocess, sys

I, W, SRC, D1, D2 = [os.path.abspath(x) for x in sys.argv[1:6]]
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
PY = sys.executable
RUN = os.path.join(I, "run.py")
sys.path.insert(0, I)
S = os.path.join(W, "stage")
shutil.copytree(SRC, S)
DATE = "2026-09-07"


def ok(name, cond, detail=""):
    if not cond:
        print("CHECK %s FAILED%s" % (name, (": " + str(detail)[-2500:]) if detail else ""))
        sys.exit(1)
    print("CHECK %s OK" % name)


def run(*args):
    r = subprocess.run([PY] + [str(x) for x in args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def J(p, o=None):
    if o is None:
        return json.load(open(p, encoding="utf-8"))
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def P(*parts):
    return os.path.join(S, *parts)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(text)


def prep(*extra):
    return run(RUN, "prep", "--date", DATE, "--work", S, *extra)


def post(*extra):
    return run(RUN, "post", "--date", DATE, "--work", S, *extra)


def failed(rc, o, step):
    return rc == 1 and ("STAGE FAIL: %s: " % step) in o and "STAGE OK" not in o


FEED = P("in", "feed_now")
SAVE = os.path.join(W, "feed_now_saved")
shutil.copytree(FEED, SAVE)


def restore_feed():
    shutil.rmtree(FEED, ignore_errors=True)
    shutil.copytree(SAVE, FEED)
    shutil.rmtree(P("in", "feed_before"), ignore_errors=True)
    shutil.copytree(SAVE, P("in", "feed_before"))


# ======================================================================= T1 feed tab reads
shutil.rmtree(FEED)
os.makedirs(FEED)
rc, o = prep()
ok("t1_prep_empty_feed_dir", failed(rc, o, "feed reads") and "in/feed_now is empty" in o and "match:" not in o, o)
ok("t1_prep_gate_before_snapshot", len(os.listdir(P("in", "feed_before"))) == 10, os.listdir(P("in", "feed_before")))
shutil.rmtree(P("in", "feed_before"))
rc, o = post()
ok("t1_post_empty_feed_dir_no_ops", failed(rc, o, "feed reads") and "in/feed_now is empty" in o
   and not os.path.exists(P("out", "post_ops")) and not os.path.exists(P("out", "feed", "ops.json")), o)
restore_feed()
os.remove(os.path.join(FEED, "micro.json"))
rc, o = prep()
ok("t1_prep_missing_tab_named", failed(rc, o, "feed reads") and "in/feed_now/micro.json missing" in o
   and "antimicrobials.json" not in o.split("STAGE FAIL")[1], o)
restore_feed()
os.remove(P("in", "feed_before", "labcx.json"))
rc, o = post()
ok("t1_post_missing_tab_named_no_ops", failed(rc, o, "feed reads") and "in/feed_before/labcx.json missing" in o
   and not os.path.exists(P("out", "post_ops")), o)
restore_feed()
J(os.path.join(FEED, "answered.json"), {"values": []})
rc, o = prep()
ok("t1_prep_empty_tab", failed(rc, o, "feed reads") and "answered.json empty (no header row)" in o, o)
write(os.path.join(FEED, "answered.json"), "{not json")
rc, o = prep()
ok("t1_prep_unparsable_tab", failed(rc, o, "feed reads") and "answered.json does not parse" in o, o)
restore_feed()
J(P("in", "reg_Verification.json"), {"values": []})
rc, o = prep()
ok("t1_verification_read_empty", failed(rc, o, "feed reads") and "in/reg_Verification.json empty (no header row)" in o, o)
os.remove(P("in", "reg_Verification.json"))
part = os.path.join(W, "feed_part")
shutil.copytree(SAVE, part)
os.remove(os.path.join(part, "labcx.json"))
fo = os.path.join(W, "feed_strict")
rc, o = run(os.path.join(I, "idp11.py"), "feed", P("out", "state_new.json"), P("out", "census.json"), "MISSING", "MISSING", part, fo,
            "--date", DATE, "--strict")
ok("t1_idp11_feed_strict", rc == 1 and "FEED FAILED: tab read(s) labcx.json missing" in o and not os.path.exists(os.path.join(fo, "ops.json")), o)
rc, o = run(os.path.join(I, "idp11.py"), "feed", P("out", "state_new.json"), P("out", "census.json"), "MISSING", "MISSING", part, fo,
            "--date", DATE)
ok("t1_idp11_feed_default_unchanged", rc == 0 and os.path.exists(os.path.join(fo, "ops.json")), o)

# ======================================================================= T2 prep re-run keeps the judgment work
ar = J(P("out", "answered_rows.json"))
ok("t2_fixture", ar[0][4] == "noted, no change" and J(P("out", "rule_rows.json"))[-1][4] == "proposed")
ar[0][5] = "until discharge"
J(P("out", "answered_rows.json"), ar)
J(P("out", "review_replies.json"), {"2": {"reply": "accepted", "reason": "fixture"}})
sd = open(P("synth_delta.py")).read() + "# judgment marker\n"
write(P("synth_delta.py"), sd)
ro = open(P("out", "roster_out.txt")).read()
rc, o = prep()
ok("t2_prep_ok", rc == 0 and "STAGE OK: prep" in o, o)
ar2 = J(P("out", "answered_rows.json"))
ok("t2_applied_as_kept", len(ar2) == 1 and ar2[0][4] == "noted, no change" and ar2[0][5] == "until discharge", ar2)
rr = J(P("out", "rule_rows.json"))
ok("t2_addrule_kept", [(r[0], r[4]) for r in rr] == [(5, "active"), (6, "proposed")]
   and rr[1][2] == "A culture phoned by the lab counts as reported", rr)
ok("t2_files_kept", open(P("synth_delta.py")).read() == sd and J(P("out", "review_replies.json")) == {"2": {"reply": "accepted", "reason": "fixture"}}
   and open(P("out", "roster_out.txt")).read() == ro)
pl = [l for l in o.splitlines() if l.startswith("  preserved: ")]
ok("t2_preserved_printed", pl and all(x in pl[0] for x in ("synth_delta.py", "out/review_replies.json", "out/roster_out.txt", "in/roster.txt",
                                                            "out/answered_rows.json (1 'Applied as' kept)", "out/rule_rows.json (1 addrule row(s) kept)")), o)
ok("t2_backup_copies", os.path.exists(P("out", "prep_keep", "synth_delta.py")) and os.path.exists(P("out", "prep_keep", "out_answered_rows.json")))
os.remove(P("out", "review_replies.json"))

# ======================================================================= T8 NEW / READMISSION on the console
ok("t8_new_on_console", "  base: P0004 Golf Tester Seven: NEW (no carried entry), write it in full under NEW" in o
   and "  base: P0013 Lima Tester Ten: NEW (no carried entry)" in o, o)
import run as R  # noqa: E402
ok("t8_base_lines", R.base_lines("P0001 A: NEW (no carried entry), write it\nP0002 B: READMISSION, 1 earlier admission(s) in the register: k\n"
                                 "BASE OK: 1 carried, 1 new, 1 readmission(s)\n") ==
   ["P0001 A: NEW (no carried entry), write it", "P0002 B: READMISSION, 1 earlier admission(s) in the register: k"])

# ======================================================================= T3 --skip-base, base failure deferred
sb = open(P("synth_base.py")).read() + "# by hand\n"
write(P("synth_base.py"), sb)
rc, o = prep("--skip-base")
ok("t3_skip_base", rc == 0 and "  base: SKIPPED (--skip-base): synth_base.py kept as it is" in o and "BASE OK" not in o
   and open(P("synth_base.py")).read() == sb and "rules: PROMOTE OK" in o, o)
J(P("in", "register.json"), [1, 2])
rc, o = prep()
lines = o.strip().splitlines()
ok("t3_base_failure_deferred", rc == 1 and "  base: FAILED (STAGE FAIL deferred to the end of the stage)" in o
   and o.index("base: FAILED") < o.index("rules: PROMOTE OK") and lines[-1].startswith("STAGE FAIL: base: ")
   and "--skip-base" in lines[-1] and "STAGE OK" not in o, o)
os.remove(P("in", "register.json"))
rc, o = prep()
ok("t3_base_again", rc == 0 and "BASE OK" in o, o)

# ======================================================================= T4 chain check
CH = P("in", "chain.txt")
GOOD = "CHAIN OK: base 2026-09-06 + 0 patch(es) - -> state dated 2026-09-06, 10 patients\n"
write(CH, GOOD)
rc, o = prep()
ok("t4_chain_ok", rc == 0 and "chain check: CHAIN CHECK OK: base 2026-09-06 + 0 patch(es) -> state dated 2026-09-06 (yesterday)" in o, o)
write(CH, "chain: patch 2026-09-06 sha mismatch, chain stops at 2026-09-05\n" + GOOD)
rc, o = prep()
ok("t4_sha_mismatch_fails", failed(rc, o, "chain check") and "sha mismatch" in o and "--accept-chain" in o, o)
rc, o = prep("--accept-chain")
ok("t4_accept_chain_warns", rc == 0 and "chain check: WARN (--accept-chain): chain: patch 2026-09-06 sha mismatch" in o, o)
ok("t4_run_item_written", "State chain: chain: patch 2026-09-06 sha mismatch" in open(P("out", "run_items_prep.txt")).read())
rc, o = post()
rec = open(P("out", "recon.txt")).read()
ok("t4_run_item_in_recon", rc == 0 and re.search(r"\d+\. Run: State chain: chain: patch 2026-09-06 sha mismatch.*\[k[0-9a-f]{8}\]", rec)
   and "Run: possibly gone: P0010" in rec, rec)
write(CH, "chain: patch 2026-09-07 not applied (incomplete or no matching base)\n" + GOOD)
rc, o = prep()
ok("t4_not_applied_fails", failed(rc, o, "chain check") and "not applied" in o, o)
write(CH, GOOD.replace("state dated 2026-09-06", "state dated 2026-09-05"))
rc, o = prep()
ok("t4_state_not_chain_output", failed(rc, o, "chain check") and "in/state.json is dated 2026-09-06 but the chain output says 2026-09-05" in o, o)
write(CH, "CHAIN FAILED: no complete IDP State base\n")
rc, o = prep()
ok("t4_chain_failed", failed(rc, o, "chain check") and "no CHAIN OK line" in o, o)
os.remove(CH)
rc, o = prep()
ok("t4_no_chain_file_noted", rc == 0 and "no in/chain.txt (save the unpackchain output there): state dated 2026-09-06 checked only" in o
   and not open(P("out", "run_items_prep.txt")).read(), o)
cf = os.path.join(W, "chain.txt")
write(cf, GOOD)
rc, o = run(RUN, "chaincheck", cf, "--date", "2026-09-07", "--state", P("in", "state.json"))
ok("t4_chaincheck_ok", rc == 0 and o.startswith("CHAIN CHECK OK: base 2026-09-06 + 0 patch(es)"), o)
rc, o = run(RUN, "chaincheck", cf, "--date", "2026-09-08")
ok("t4_chaincheck_not_yesterday_warns", rc == 0 and o.startswith("CHAIN CHECK WARN: the state is dated 2026-09-06, not yesterday 2026-09-07"), o)
rc, o = run(RUN, "chaincheck", cf, "--date", "2026-09-06")
ok("t4_chaincheck_today_fails", rc == 1 and o.startswith("CHAIN CHECK FAIL: the state is dated 2026-09-06, not before today"), o)
write(cf, "chain: patch 2026-09-06 sha mismatch, chain stops at 2026-09-05\n" + GOOD)
rc, o = run(RUN, "chaincheck", cf, "--date", "2026-09-07")
ok("t4_chaincheck_sha_fails", rc == 1 and "CHAIN CHECK FAIL" in o and "sha mismatch" in o, o)
rc, o = run(RUN, "chaincheck", cf, "--date", "2026-09-07", "--accept-chain")
ok("t4_chaincheck_sha_accepted", rc == 0 and o.startswith("CHAIN CHECK WARN") and "sha mismatch" in o, o)

# ======================================================================= T10 last_run_utc
rc, o = post()
st = J(P("out", "state_new.json"))
t0 = open(P("out", "run_start_utc.txt")).read().split()
ok("t10_written_at_post", rc == 0 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", st.get("last_run_utc", "")) and t0[0] == DATE
   and st["last_run_utc"] == t0[1] and "  last run: state last_run_utc = %s (this run's start" % t0[1] in o, (st.get("last_run_utc"), o))
ins = J(P("in", "state.json"))
ins["last_run_utc"] = "2026-09-06T05:31:00Z"
J(P("in", "state.json"), ins)
rc, o = prep()
ok("t10_printed_by_prep", rc == 0 and "  last run: state last_run_utc 2026-09-06T05:31:00Z" in o, o)

# ======================================================================= T5 full base triggers


def post_state(chain):
    write(CH, chain)
    rc, o = post()
    idx = open(P("out", "post_ops", "INDEX.txt")).read()
    sp = [n for n in os.listdir(P("out", "post_ops")) if n.endswith("_state_parts.json")]
    files = J(P("out", "post_ops", sp[0])) if sp else []
    return rc, o, idx, files


SIX = "CHAIN OK: base 2026-09-01 + 6 patch(es) 2026-09-01,2026-09-02,2026-09-03,2026-09-04,2026-09-05,2026-09-06 -> state dated 2026-09-06, 10 patients\n"
rc, o, idx, files = post_state(SIX)
ok("t5_six_patches_full_base", rc == 0 and "State: FULL BASE IDP State 2026-09-07, because: 6 patches already follow base 2026-09-01" in idx
   and "PATCH LARGE" not in idx and "state patch" not in o and files
   and all(f["title"] == "IDP State 2026-09-07 (part %d of %d)" % (i, len(files)) and f["bytes"] == os.path.getsize(P(f["path"]))
           for i, f in enumerate(files, 1)) and "| FULL BASE (6 patches" in idx, (o, idx))
rc, o, idx, files = post_state("chain: base 2026-09-06 incomplete (1 of 2 parts), skipped\nchain: fallback to base 2026-09-05 (newer base(s) "
                               "2026-09-06 unusable)\nCHAIN OK: base 2026-09-05 + 1 patch(es) 2026-09-06 -> state dated 2026-09-06, 10 patients\n")
ok("t5_fallback_full_base", rc == 0 and "because: the chain fell back to the older base 2026-09-05" in idx and files
   and files[0]["title"].startswith("IDP State 2026-09-07 (part 1 of"), idx)
rc, o, idx, files = post_state("CHAIN OK: base 2026-09-07 + 0 patch(es) - -> state dated 2026-09-07, 10 patients\n")
ok("t5_same_day_base_full", rc == 0 and "because: the chain's base is dated today (2026-09-07)" in idx, idx)
rc, o, idx, files = post_state("CHAIN OK: base 2026-09-05 + 1 patch(es) 2026-09-06 -> state dated 2026-09-06, 10 patients\n")
ok("t5_no_trigger_patch_tried", rc == 0 and "state patch: PATCH OK" in o and "patches already follow" not in idx
   and "fell back" not in idx, (o, idx))
os.remove(CH)
# drive_state unpackchain names the fallback: a newer base with a part missing
CHD = os.path.join(W, "chain")
os.makedirs(CHD)
for f in os.listdir(os.path.join(D1, "out", "state_parts")):
    shutil.copy(os.path.join(D1, "out", "state_parts", f), os.path.join(CHD, "d1_" + f))
rc, o = run(os.path.join(I, "state_io.py"), "pack", os.path.join(D2, "out", "state_new.json"), os.path.join(W, "newbase"), "6000")
newparts = sorted(f for f in os.listdir(os.path.join(W, "newbase")) if f.startswith("part"))
ok("t5_newer_base_packed", rc == 0 and len(newparts) > 1, (o, newparts))
for f in newparts[:-1]:   # the newer base without its last part
    shutil.copy(os.path.join(W, "newbase", f), os.path.join(CHD, "d2_" + f))
rc, o = run(os.path.join(I, "drive_state.py"), "unpackchain", CHD, os.path.join(W, "fb.json"))
ok("t5_unpackchain_fallback_line", rc == 0 and "chain: fallback to base 2026-09-06 (newer base(s) 2026-09-07 unusable)" in o
   and "CHAIN OK: base 2026-09-06 + 0 patch(es)" in o, o)
ok("t5_fallback_detected", R.chain_check(o, "2026-09-07")[3]["fallback"] is True and R.chain_check(GOOD, "2026-09-07")[3]["fallback"] is False)

# ======================================================================= T6 verification requests
import idp11  # noqa: E402
KEY = "MRN 100001 | P0001 | 01/09/26 to 06/09/26"
J(P("in", "reg_Verification.json"), {"values": [idp11.VER,
  ["C-20260907-0001", "07/09/26", "Claude", "Register", KEY, "MRN", "100002", "100001", "Feed Patients P0001", "wrong", "", "", "", "open"]]})
REQ = [{"key": "P0013 / P0002", "column": "pid", "value_checked": "P0013", "value_in_source": "P0002", "source": "AS list 07.09.2026",
        "severity": "merge request", "note": "same MRN, same admission"},
       {"key": KEY, "column": "MRN", "value_checked": "100002", "value_in_source": "100001", "source": "Feed Patients P0001",
        "severity": "wrong", "note": ""}]
J(P("out", "verification_requests.json"), REQ)
rc, o = post()
names = sorted(os.listdir(P("out", "post_ops")))
vf = [n for n in names if n.endswith("_verification_requests.json")]
idx = open(P("out", "post_ops", "INDEX.txt")).read()
ok("t6_post_ok", rc == 0 and "VREQUESTS OK: 2 request(s) -> 1 C- row(s) (1 already open, not repeated)" in o and vf, o)
ops = J(P("out", "post_ops", vf[0]))
ok("t6_c_row", ops == [{"range": "Verification!A3:N3", "values": [[
    "C-20260907-0002", "'07/09/26", "Claude", "Register", "P0013 / P0002", "pid", "P0013", "P0002",
    "AS list 07.09.2026; note: same MRN, same admission", "merge request", "", "", "", "open"]]}], ops)
ok("t6_index_register", re.search(r"\| %s \| IDP Discharge Register .*\| 1 call\(s\) \| chkw" % re.escape(vf[0]), idx), idx)
J(P("out", "verification_requests.json"), [{"key": "x", "column": "pid", "value_in_source": "y", "source": "z"}])
rc, o = post()
ok("t6_bad_request_fails", failed(rc, o, "verification requests") and "request 1 lacks severity" in o and not os.path.exists(P("out", "post_ops")), o)
os.remove(P("in", "reg_Verification.json"))
J(P("out", "verification_requests.json"), REQ)
rc, o = post()
ok("t6_no_verification_read_fails", failed(rc, o, "verification requests") and "in/reg_Verification.json was not read" in o, o)
os.remove(P("out", "verification_requests.json"))

# ======================================================================= T9 USER_ENTERED, chkw verbatim
rc, o = post()
idx = open(P("out", "post_ops", "INDEX.txt")).read()
ok("t9_index_user_entered", rc == 0 and "valueInputOption USER_ENTERED" in idx, idx)
rf = P("out", "post_ops", [n for n in os.listdir(P("out", "post_ops")) if n.endswith("_rule_rows.json")][0])
vals = J(rf)[0]["values"]
J(os.path.join(W, "rb_ue.json"), {"values": [[str(v)[1:] if str(v).startswith("'") else str(v) for v in r] for r in vals]})
rc, o = run(RUN, "chkw", rf, 1, os.path.join(W, "rb_ue.json"))
ok("t9_chkw_user_entered_match", rc == 0 and o.startswith("CHKW MATCH"), o)
J(os.path.join(W, "rb_raw.json"), {"values": [[str(v) for v in r] for r in vals]})
rc, o = run(RUN, "chkw", rf, 1, os.path.join(W, "rb_raw.json"))
ok("t9_chkw_raw_apostrophe_mismatch", rc == 1 and "CHKW MISMATCH" in o and "row 1 col 2" in o and "\"'07/09/26\"" in o, o)

# ======================================================================= T7 sendcheck
body = open(P("out", "recon.txt"), encoding="utf-8").read()
write(os.path.join(W, "subject.txt"), "ID Reconciliation 07.09.2026")
msg = {"id": "m1", "payload": {"headers": [{"name": "From", "value": "me"}, {"name": "Subject", "value": "ID Reconciliation 07.09.2026"}]},
       "plaintextBody": body}
J(os.path.join(W, "sent.json"), msg)
rc, o = run(RUN, "sendcheck", os.path.join(W, "sent.json"), "subject=" + os.path.join(W, "subject.txt"), "plaintextBody=" + P("out", "recon.txt"))
ok("t7_sendcheck_exact", rc == 0 and "subject: EXACT" in o and "plaintextBody: EXACT" in o and "SENDCHECK OK: 2 field(s)" in o, o)
msg["plaintextBody"] = body.rstrip("\n").replace("\n", "  \r\n") + "\r\n\r\n"
J(os.path.join(W, "sent_ws.json"), msg)
rc, o = run(RUN, "sendcheck", os.path.join(W, "sent_ws.json"), "plaintextBody=" + P("out", "recon.txt"))
ok("t7_sendcheck_trailing_ws", rc == 0 and "plaintextBody: EQ_mod_trailing_ws" in o and "SENDCHECK OK" in o, o)
lines = body.split("\n")
lines[2] = lines[2] + " (edited)"
msg["plaintextBody"] = "\n".join(lines)
J(os.path.join(W, "sent_diff.json"), msg)
rc, o = run(RUN, "sendcheck", os.path.join(W, "sent_diff.json"), "plaintextBody=" + P("out", "recon.txt"), "htmlBody=" + P("out", "recon.txt"))
ok("t7_sendcheck_diff", rc == 1 and "plaintextBody: DIFF" in o and "line 3:" in o and "htmlBody: MISSING" in o
   and "SENDCHECK FAIL: 2 of 2 field(s) differ" in o, o)

print("STAGES R2 TESTS OK")
