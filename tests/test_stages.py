#!/usr/bin/env python3
"""Stage commands and the 28.11.2026 decisions (A to E), fictional data only.

Usage: test_stages.py <toolkit idp/idp dir> <workdir> <day-1 run dir> <day-2 run dir>   (dirs of the e2e run)
Prints "CHECK <name> OK" per check; exit 1 on the first failure; "STAGES TESTS OK" at the end.

  A. run.py prep / build / post on the e2e day-2 fixture: STAGE OK lines, post_ops INDEX, chkw, a failed gate
  B. membership (match.py): removal only by a fellow removal, a sign-off email or a newer full roster block;
     absence alone = "possibly gone"; re-entry by AS list, handoff Cs ID row or email dated after the removal
  C. AS list missing by 08:00: rooms from yesterday's list, one-line Delta Report, missed day carried to the next delta
  D. learned rules: plain-answer rules "proposed", RULE: lines "active", promote after one email, undo, active_rules
  E. coverage gate: misses, waivers, tolerant matching
"""
import json, os, re, runpy, shutil, subprocess, sys

I, W, D1, D2 = sys.argv[1:5]
I = os.path.abspath(I)
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
PY = sys.executable
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, I)


def ok(name, cond, detail=""):
    if not cond:
        print("CHECK %s FAILED%s" % (name, (": " + str(detail)[-2500:]) if detail else ""))
        sys.exit(1)
    print("CHECK %s OK" % name)


def run(*args, cwd=None):
    r = subprocess.run([PY] + [str(x) for x in args], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def J(p, o=None):
    if o is None:
        return json.load(open(p, encoding="utf-8"))
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(text)


RUN = os.path.join(I, "run.py")

# ======================================================================= A. stages on the e2e day-2 fixture
S = os.path.join(W, "stage")
os.makedirs(os.path.join(S, "in", "feed_now"))
for f in ("wards.json", "ams.json", "as_today.json"):
    shutil.copy(os.path.join(D2, "in", f), os.path.join(S, "in", f))
shutil.copy(os.path.join(D2, "in", "roster.txt"), os.path.join(S, "in", "roster.txt"))
shutil.copy(os.path.join(D2, "in", "id_email.txt"), os.path.join(S, "in", "email_today.txt"))
shutil.copy(os.path.join(D1, "out", "state_new.json"), os.path.join(S, "in", "state.json"))
J(os.path.join(S, "in", "bfq.json"), {})
write(os.path.join(S, "in", "cultures.txt"),
      "### Cultures 2026-09-07 (f1, modified 2026-09-07T09:00:00Z)\n*Micro Digest 07/09/2026*\n"
      "*Alpha Tester One* (DOB _01/01/1956_ | MRN _100001_ | _R708B_)\n"
      "- [POS] *Blood I* (SID _900101_, coll. _05/09_, DR 5001): GNB. Final 07/09.\n"
      "  - *_Klebsiella pneumoniae_*: *S:* _Mero_, *R:* _Ceftri_\n")
# yesterday's reconciliation as sent (one item without a key), Chris's reply, the Learned Rules tab as read
write(os.path.join(S, "in", "recon_prev.txt"),
      "ID Reconciliation 06.09.2026\n\nNEEDS YOU (2)\n1. Possible missing culture: Alpha Tester One BCx coll. 05/09 [k1234abcd]\n"
      "2. AMS app: 1 patient(s) of yesterday's ID list missing from the app's list with\nno removal record: Kilo\n\n"
      "SETTLED BY THE RUN (0)\nnone\n\nRULES LEARNED FROM YOUR ANSWERS (1)\nL2. Rule two (from item k1234abcd; proposed, binds tomorrow unless you reply undo)\n\n"
      "HOW TO ANSWER: reply to this email.\n")
write(os.path.join(S, "in", "recon_reply.txt"), "1: known, the lab phoned it\nRULE: A phoned result counts as reported\nL2 undo\n")
J(os.path.join(S, "in", "feed_now", "rules.json"), {"values": [
    ["No", "Date", "Rule", "From", "Status", "Notes"],
    ["1", "'05/09/26", "Rule one, proposed two days ago", "k00000001", "proposed", ""],
    ["2", "'06/09/26", "Rule two", "k1234abcd", "proposed", ""],
    ["3", "'01/09/26", "Rule three", "RULE", "active", ""],
    ["4", "'07/09/26", "Rule four, proposed today", "k00000004", "proposed", ""]]})
J(os.path.join(S, "in", "feed_now", "answered.json"), {"values": [["Key", "Date answered", "Item", "Chris answer", "Applied as", "Until"]]})

rc, o = run(RUN, "prep", "--date", "2026-09-07", "--work", S)
ok("prep_stage_ok", rc == 0 and "STAGE OK: prep 2026-09-07" in o and "STAGE FAIL" not in o, o)
ok("prep_one_line_per_step", all(l.startswith(("STAGE ", "  ")) for l in o.strip().splitlines()), o)
ok("prep_feed_snapshot", os.path.exists(os.path.join(S, "in", "feed_before", "rules.json")), o)
ok("prep_membership_removed", "1 removed line(s)" in o, o)
pj = J(os.path.join(S, "in", "recon_prev.json"))
import hashlib  # noqa: E402
k2 = "k" + hashlib.sha1(pj["need"][1]["text"].encode()).hexdigest()[:8]
ok("recon_prev_parsed", [x["key"] for x in pj["need"]] == ["k1234abcd", k2] and pj["need"][1]["text"].endswith("no removal record: Kilo")
   and pj["learned"][0]["n"] == "L2" and pj["date"] == "2026-09-06", pj)
ca = J(os.path.join(S, "out", "chris_answers.json"))
ok("recon_reply_in_prep", [x["key"] for x in ca["answers"]] == ["k1234abcd"] and ca["undo"] == ["L2"], ca)
ok("rule_line_active", [r[4] for r in J(os.path.join(S, "out", "rule_rows.json"))] == ["active"])
ar = open(os.path.join(S, "in", "active_rules.txt")).read()
ok("active_rules_bind", ar.startswith("L1 | Rule one") and "L3 | Rule three" in ar and "Rule two" not in ar and "Rule four" not in ar, ar)
ok("promote_ops", J(os.path.join(S, "out", "promote_ops.json")) == [{"range": "'Learned Rules'!E2", "values": [["active"]]}])
ok("undo_ops", J(os.path.join(S, "out", "undo_ops.json")) == [{"range": "'Learned Rules'!E3", "values": [["undone"]]}])
from recon_reply import active_rules  # noqa: E402
ok("active_rules_helper", [r["n"] for r in active_rules(os.path.join(S, "in", "feed_now", "rules.json"))] == ["L3"])
ok("day_updates_written", "=== P0001" in open(os.path.join(S, "out", "day_updates.txt")).read())

# the agent's part: synth_delta.py from the fixture, the ID list lines, an answer's "Applied as", a plain-answer rule
shutil.copy(os.path.join(TESTS, "synth_fixture.py"), os.path.join(S, "fixture_synth.py"))
F = runpy.run_path(os.path.join(S, "fixture_synth.py"))
BASE = runpy.run_path(os.path.join(S, "synth_base.py"))["BASE"]
SY = F["SYNTH"]
delta = {}
for pid in BASE:
    e = SY[pid]
    d = {"updates": e["updates"], "id_plan": e["id_plan"]}
    if not BASE[pid].get("issues") and e.get("issues"):
        d.update(issue_add=e["issues"], vitals=e["vitals"])
    delta[pid] = d
alpha = F["PID"]["Alpha Tester One"]
write(os.path.join(S, "synth_delta.py"), "\n".join([
    "DELTA = %r" % delta,
    "NEW = %r" % {pid: e for pid, e in SY.items() if pid not in BASE},
    "SIGNED_OFF = %r" % F["SIGNED_OFF"], "FLAGS_EXTRA = []", "OBSERVATIONS = %r" % F["OBSERVATIONS"],
    "WA = %r" % {pid: ["Test patient, line one", "Plan: as per the test"] for pid in SY},
    "CHANGES = {}",
    "WAIVED = %r" % {alpha: [{"item": "Blood I 900101: Klebsiella pneumoniae", "reason": "fixture: blood isolate left out on purpose"}]},
    ""]))
write(os.path.join(S, "out", "roster_out.txt"),   # the agent resolves the room and initials of the consult-note patient
      open(os.path.join(D2, "in", "roster.txt")).read().replace("*?* Lima Tester Ten (new) ?", "*206* Lima Tester Ten (new) CH"))
rc, o = run(RUN, "build", "--date", "2026-09-07", "--long-date", "07 September 2026", "--work", S)
ok("build_stage_ok", rc == 0 and "STAGE OK: build 2026-09-07" in o, o)
ok("build_gates_seen", all(x in o for x in ("APPLY OK", "0 errors", " 0 unexplained", "COVERAGE OK: ", "1 waived", "BUILD OK",
                                            "RECAP HTML OK", "WA OK", "CHECKS R OK")), o)
ok("no_html_handout", not os.path.exists(os.path.join(S, "out", "handout.html")), o)

# a failed gate: an unexplained change stops the build with one STAGE FAIL line
sd = open(os.path.join(S, "synth_delta.py")).read()
write(os.path.join(S, "synth_delta.py"), sd.replace("DELTA = {", "DELTA = {%r: {'one_liner': 'rewritten for style', 'updates': ['x'], 'id_plan': ['y']}, " % alpha, 1)
      .replace("%r: {'updates'" % alpha, "'unused': {'updates'", 1))
rc, o2 = run(RUN, "build", "--date", "2026-09-07", "--long-date", "07 September 2026", "--work", S)
ok("build_stops_at_first_failed_gate", rc == 1 and "STAGE FAIL: " in o2 and "STAGE OK" not in o2 and "BUILD OK" not in o2, o2)
write(os.path.join(S, "synth_delta.py"), sd)
rc, o = run(RUN, "build", "--date", "2026-09-07", "--long-date", "07 September 2026", "--work", S)
ok("build_again_ok", rc == 0, o)

ar = J(os.path.join(S, "out", "answered_rows.json"))
ar[0][4] = "noted, no change"
J(os.path.join(S, "out", "answered_rows.json"), ar)
rc, o = run(os.path.join(I, "recon_reply.py"), "addrule", os.path.join(S, "out"), "--date", "2026-09-07", "--from", "k1234abcd",
            "--rules-tab", os.path.join(S, "in", "feed_now", "rules.json"), "A culture phoned by the lab counts as reported")
ok("addrule_proposed", rc == 0 and "L6 proposed" in o and J(os.path.join(S, "out", "rule_rows.json"))[-1][4] == "proposed", o)
write(os.path.join(S, "out", "run_items.txt"), "possibly gone: P0010 Juliet Example, not on the AS list since 06/09\n\nmerge P0013 into P0002\n")
rc, o = run(RUN, "post", "--date", "2026-09-07", "--work", S)
ok("post_stage_ok", rc == 0 and "STAGE OK: post 2026-09-07" in o, o)
recon = open(os.path.join(S, "out", "recon.txt")).read()
ok("recon_learned_proposed", "L6. A culture phoned by the lab counts as reported (from item k1234abcd; proposed, binds tomorrow unless you reply undo)" in recon
   and "L5. A phoned result counts as reported (general rule)" in recon and "Rule two" not in recon, recon)
rneed = recon.split("NEEDS YOU", 1)[1].split("SETTLED", 1)[0]
ok("recon_run_items", re.search(r"\d+\. Run: possibly gone: P0010 Juliet Example, not on the AS list since 06/09 \[k[0-9a-f]{8}\]", rneed)
   and re.search(r"\d+\. Run: merge P0013 into P0002 \[k[0-9a-f]{8}\]", rneed), rneed)
ok("recon_answered_not_repeated", "k1234abcd]" not in recon.split("SETTLED")[0], recon)
idx = open(os.path.join(S, "out", "post_ops", "INDEX.txt")).read()
names = sorted(os.listdir(os.path.join(S, "out", "post_ops")))
ok("post_ops_files", names[0].startswith("01_feed_ops") and "INDEX.txt" in names
   and [n.split("_", 1)[1] for n in names if n != "INDEX.txt"][-5:] == ["answered_rows.json", "rule_rows.json", "undo_ops.json",
                                                                       "rule_promote.json", "state_parts.json"], names)
ok("post_ops_index", idx.startswith("POST OPS 2026-09-07") and "NN | file | target | calls | verify" in idx and "feedcheck" in idx
   and "drive part MATCH" in idx and "IDP Feed <id: spec section 2>" in idx, idx)
ok("post_ops_keep_per_op_files", os.path.exists(os.path.join(S, "out", "feed", "ops.json")))
rr = J(os.path.join(S, "out", "post_ops", [n for n in names if "rule_rows" in n][0]))
ok("rule_rows_append_range", rr[0]["range"] == "'Learned Rules'!A6:F7" and [r[4] for r in rr[0]["values"]] == ["active", "proposed"], rr)
# chkw: a read-back with Sheets' apostrophes and trailing blanks dropped matches; a changed cell does not
f1 = os.path.join(S, "out", "post_ops", [n for n in names if "rule_rows" in n][0])
J(os.path.join(W, "rb.json"), {"range": "x", "values": [[str(v).lstrip("'") for v in r[:5]] for r in rr[0]["values"]]})
rc, o = run(RUN, "chkw", f1, 1, os.path.join(W, "rb.json"))
ok("chkw_match", rc == 0 and o.startswith("CHKW MATCH"), o)
bad = J(os.path.join(W, "rb.json")); bad["values"][1][2] = "changed"; J(os.path.join(W, "rb_bad.json"), bad)
rc, o = run(RUN, "chkw", f1, 1, os.path.join(W, "rb_bad.json"))
ok("chkw_mismatch", rc == 1 and "CHKW MISMATCH" in o and "row 2 col 3" in o, o)

# ======================================================================= B. membership
M = os.path.join(W, "member")
os.makedirs(M)


def rec(name, mrn, active=True, archived=None, room="701"):
    return {"name": name, "aliases": [], "mrn": mrn, "first_seen": "2026-11-20", "last_seen": "2026-11-27", "active": active,
            "archived": archived, "archived_reason": "x" if archived else "", "abx_history": [], "pendings_state": [],
            "synth": {"_room": room, "_group": "7th floor", "_fellow": "CH", "_tags": [], "one_liner": "60M"}}


def as_pt(name, mrn, room):
    return {"mrn": mrn, "name": name, "room": room, "group": "7th floor", "age": "60", "flags": [], "once_only": False,
            "drugs": ["Mero"], "standing_drugs": ["Mero"], "orders": [{"drug": "Mero", "freq": "q8h", "valid_from": "2026-11-27", "once": False}]}


state = {"version": 2, "date": "2026-11-27", "next_pid": 20, "observations": [], "roster_last": None,
         "as_snapshot": {"list_date": "2026-11-27", "patients": [as_pt("Alpha Example", "900001", "701")]},
         "patients": {"P0001": rec("Alpha Example", "900001"), "P0002": rec("Bravo Example", "900002", room="702"),
                      "P0003": rec("Charlie Example", "900003"), "P0004": rec("Delta Example", "900004"),
                      "P0005": rec("Echo Example", "900005", False, "2026-11-20"),
                      "P0006": rec("Foxtrot Example", "900006", False, "2026-11-20"),
                      "P0007": rec("Golf Example", "900007", False, "2026-11-20", room="707"),
                      "P0008": rec("Hotel Example", "900008"),
                      "P0009": rec("India Example", "900009", False, "2026-11-27")}}
J(os.path.join(M, "state.json"), state)
J(os.path.join(M, "as_yday.json"), {"list_date": "2026-11-27", "patients": [as_pt("Alpha Example", "900001", "701")]})
J(os.path.join(M, "as_today.json"), {"list_date": "2026-11-28", "patients": [as_pt("Alpha Example", "900001", "701"),
                                                                              as_pt("Echo Example", "900005", "705")]})


def ward(name, room, text, consult=True):
    return {"doc": "floors", "section": "", "room": room, "name": name, "cells": {"SYNTHESIS": text}, "text": text,
            "dated_lines": [], "id_consult": consult, "uc_id": False, "active": []}


J(os.path.join(M, "wards.json"), [ward("Foxtrot Example", "706", "27/11: ID consulted again for new fever"),
                                  ward("India Example", "709", "26/11: ID consulted earlier"),
                                  ward("Hotel Example", "708", "27/11: afebrile", consult=False)])
J(os.path.join(M, "ams.json"), [])
write(os.path.join(M, "roster.txt"), "701 Alpha Example CH\n708 Hotel Example CH\n")
write(os.path.join(M, "email.txt"), "Good morning,\nDelta Example: ID signed off today.\nGolf Example readmitted overnight, we follow her again.\n")
J(os.path.join(M, "svc.json"), {"last_edit_at": "2026-11-27T16:00:00+00:00",
                                "patients": [{"pid": "P0001", "name": "Alpha Example", "updated_at": "2026-11-27T15:00:00+00:00"},
                                             {"pid": "P0008", "name": "Hotel Example", "updated_at": "2026-11-27T15:00:00+00:00"}],
                                "removed": [{"pid": "P0003", "name": "Charlie Example", "removed_at": "2026-11-27T10:00:00+00:00"}]})


def match(out, *extra, email="email.txt", state_p="state.json", as_t="as_today.json"):
    rc, o = run(os.path.join(I, "match.py"), os.path.join(M, state_p), os.path.join(M, as_t) if as_t != "MISSING" else "MISSING",
                os.path.join(M, "wards.json"), os.path.join(M, "ams.json"), os.path.join(M, out), "--date", "28.11.2026",
                "--roster", os.path.join(M, "roster.txt"), "--as-yday", os.path.join(M, "as_yday.json"), "--allow-orphans",
                "--update-text", os.path.join(M, email), os.path.join(M, "svc.json"), *extra)
    ok("match_runs_" + out, rc == 0, o)
    c = J(os.path.join(M, out, "census.json"))
    fl = open(os.path.join(M, out, "flags.txt")).read()
    return {p["pid"]: p for p in c["patients"]}, c, fl


cen, c, fl = match("m1")
ok("member_fellow_removal", "P0003" not in cen and "removed: Charlie Example (P0003): removed by a fellow in the service list" in fl, fl)
ok("member_signed_off_email", "P0004" not in cen and "signed off" in fl.split("(P0004)")[1].splitlines()[0], fl)
ok("member_absence_never_removes", "P0002" in cen and "possibly gone: P0002 absent from AS list, handoffs and emails" in fl
   and cen["P0002"]["room"] == "702", fl)
ok("member_kept_flag", "kept: Bravo Example (P0002)" in fl, fl)
ok("member_not_possibly_gone_when_seen", "possibly gone: P0001" not in fl and "possibly gone: P0008" not in fl, fl)
ok("member_reentry_as_list", "P0005" in cen and "re-entered: P0005 AS list standing therapy new since removal" in fl
   and cen["P0005"]["reentered"].startswith("AS list"), fl)
ok("member_reentry_handoff", "P0006" in cen and "re-entered: P0006 handoff floors Cs ID row 27/11" in fl and cen["P0006"]["room"] == "706", fl)
ok("member_reentry_email", "P0007" in cen and "re-entered: P0007 update email 2026-11-28" in fl and cen["P0007"]["room"] == "707", fl)
ok("member_old_row_stays_off", "P0009" not in cen and any(o["pid"] == "P0009" for o in c["cs_id_offlist"]), c["cs_id_offlist"])
st = J(os.path.join(M, "m1", "state_matched.json"))
ok("member_removed_state", st["patients"]["P0003"]["active"] is False and st["patients"]["P0003"]["archived"] == "2026-11-28"
   and "removed by a fellow" in st["patients"]["P0003"]["archived_reason"])
# a full roster block in a newer update email decides; an email older than the service list's last edit does not
write(os.path.join(M, "email_block.txt"), "701 Alpha Example CH\n702 Bravo Example MA\n705 Echo Example CH\n")
cen, c, fl = match("m2", email="email_block.txt")
ok("member_roster_block_omits", "P0008" not in cen and "omitted from the full roster block" in fl and "P0002" in cen, fl)
write(os.path.join(M, "email_old.txt"), "=== 2026-11-27T08:00:00\n701 Alpha Example CH\n702 Bravo Example MA\n705 Echo Example CH\n")
cen, c, fl = match("m3", email="email_old.txt")
ok("member_old_block_ignored", "P0008" in cen and "omitted from" not in fl, fl)
# the service list put a removed patient back later: not removed
sv = J(os.path.join(M, "svc.json"))
sv["patients"].append({"pid": "P0003", "name": "Charlie Example", "updated_at": "2026-11-27T12:00:00+00:00"})
J(os.path.join(M, "svc.json"), sv)
cen, c, fl = match("m4")
ok("member_readded_by_fellow", "P0003" in cen, fl)

# ======================================================================= C. AS list missing by 08:00
cen, c, fl = match("c1", "--as-missing", as_t="MISSING")
d = J(os.path.join(M, "c1", "delta.json"))
ok("as_missing_delta", d.get("as_missing") and not d["computed"]
   and d["reason"] == "AS list 28.11.2026 not received by 08:00; delta follows when it arrives", d)
ok("as_missing_rooms_from_yday", cen["P0001"]["room"] == "701" and cen["P0001"]["room_source"] == "as" and "P0005" not in cen, cen.get("P0001"))
ok("as_missing_state_marked", J(os.path.join(M, "c1", "state_matched.json")).get("as_missing_days") == ["2026-11-28"])
rc, o = run(os.path.join(I, "render_delta.py"), os.path.join(M, "c1", "delta.json"), "MISSING", os.path.join(M, "c1", "new_mrns.json"),
            os.path.join(M, "c1", "delta2.html"), os.path.join(M, "c1", "delta2.txt"))
txt = open(os.path.join(M, "c1", "delta2.txt")).read()
ok("as_missing_delta_report_one_line", rc == 0 and txt == "AS LIST DELTA REPORT\nAS list 28.11.2026 not received by 08:00; delta follows when it arrives\n"
   and "not received by 08:00" in open(os.path.join(M, "c1", "delta2.html")).read(), txt)
# next morning: the list arrives; the delta is taken against the last list consumed (27.11) and names the missed day
st = J(os.path.join(M, "c1", "state_matched.json"))
J(os.path.join(M, "state_c2.json"), st)
J(os.path.join(M, "as_d3.json"), {"list_date": "2026-11-29", "patients": [as_pt("Alpha Example", "900001", "701"),
                                                                           as_pt("Echo Example", "900005", "705")]})
rc, o = run(os.path.join(I, "match.py"), os.path.join(M, "state_c2.json"), os.path.join(M, "as_d3.json"), os.path.join(M, "wards.json"),
            os.path.join(M, "ams.json"), os.path.join(M, "c2"), "--date", "29.11.2026", "--roster", os.path.join(M, "roster.txt"),
            "--allow-orphans", "--last-delta-sent", "28.11.2026")
d2 = J(os.path.join(M, "c2", "delta.json"))
ok("as_missing_next_delta", rc == 0 and d2["computed"] and d2["yday_date"] == "2026-11-27" and d2["missed_dates"] == ["2026-11-28"]
   and d2.get("late_days") == ["2026-11-28"] and [p["mrn"] for p in d2["new"]] == ["900005"], (o, d2))
ok("as_missing_cleared", "as_missing_days" not in J(os.path.join(M, "c2", "state_matched.json")))

# ======================================================================= D. learned rules in recon
rt = os.path.join(W, "rules_tab.json")
J(rt, {"values": [["No", "Date", "Rule", "From", "Status", "Notes"], ["1", "'27/11/26", "Plain rule", "kabcdef01", "proposed", ""],
                  ["2", "'28/11/26", "Typed rule", "RULE", "active", ""], ["3", "'28/11/26", "Undone rule", "RULE", "undone", ""]]})
rc, o = run(os.path.join(I, "recon.py"), "--date", "2026-11-28", "--out", os.path.join(W, "r.txt"), "--learned", rt)
t = open(os.path.join(W, "r.txt")).read()
ok("recon_rules_learned", "L1. Plain rule (from item kabcdef01; proposed, binds tomorrow unless you reply undo)" in t
   and "L2. Typed rule (general rule)" in t and "Undone rule" not in t, t)
rc, o = run(os.path.join(I, "recon_reply.py"), "promote", os.path.join(W, "pr"), "--date", "2026-11-28", "--rules-tab", rt)
ok("promote_after_one_email", rc == 0 and J(os.path.join(W, "pr", "promote_ops.json")) == [{"range": "'Learned Rules'!E2", "values": [["active"]]}], o)
rc, o = run(os.path.join(I, "recon_reply.py"), "promote", os.path.join(W, "pr2"), "--date", "2026-11-27", "--rules-tab", rt)
ok("no_promote_same_day", J(os.path.join(W, "pr2", "promote_ops.json")) == [] and "1 still proposed" in o, o)

# ======================================================================= E. coverage gate
CV = os.path.join(W, "cov")
os.makedirs(CV)
J(os.path.join(CV, "census.json"), {"patients": [{"pid": "Q1", "name": "Kilo Example", "mrn": "800001", "as_admission": "2026-11-20"}]})
write(os.path.join(CV, "day_updates.txt"), "=== Q1 | 701 | Kilo Example | x\n[SYNTHESIS] 27/11: CT abdomen collection, drain placed. "
      "28/11 febrile 38.9 o/n, BCx sent. 28/11: no need for MRI brain\n[PENDINGS] Monitor fever 28/11\n")
J(os.path.join(CV, "cultures.json"), {"specimens": [
    {"mrn": "800001", "patient": "Kilo Example", "final": True, "collected": "2026-11-25", "final_date": "2026-11-27", "specimen": "Urine",
     "specimen_short": "urine", "organisms": ["Pseudomonas aeruginosa"], "sid": "1", "result": "", "source": "Cultures 2026-11-27"},
    {"mrn": "800001", "patient": "Kilo Example", "final": True, "collected": "2026-11-24", "final_date": "2026-11-26", "specimen": "Wound",
     "specimen_short": "wound", "organisms": ["Staphylococcus aureus"], "sid": "2", "result": "", "source": "Cultures 2026-11-26"},
    {"mrn": "800001", "patient": "Kilo Example", "final": True, "collected": "2026-10-01", "final_date": "2026-10-03", "specimen": "Blood",
     "specimen_short": "blood", "organisms": ["Candida albicans"], "sid": "3", "result": "", "source": "earlier admission"}]})
syn = ('SYNTH = {"Q1": {"name": "Kilo Example", "one_liner": "50M", "updates": ["28/11: fever 38.9 overnight 27/11, BCx x2"],'
       ' "issues": [{"dx": "Liver abscess (27/11) | CT 27/11 collection, drain", "abx": []}], "micro": [%s], "pendings": []}}\n'
       'WA = {}\nWAIVED = %s\n')
write(os.path.join(CV, "s1.py"), syn % ('"25/11 UCx P. aeruginosa S Cipro"', "{}"))
rc, o = run(os.path.join(I, "idp10.py"), "coverage", os.path.join(CV, "s1.py"), os.path.join(CV, "census.json"), os.path.join(CV, "o1"),
            "--date", "2026-11-28", "--day-updates", os.path.join(CV, "day_updates.txt"), "--cultures", os.path.join(CV, "cultures.json"))
g = open(os.path.join(CV, "o1", "coverage_gate.txt")).read()
ok("coverage_miss_blocks", rc == 1 and "COVERAGE FAIL: 1 missed (final culture 1)" in o and "Staphylococcus aureus" in g, g)
ok("coverage_tolerant", "UCx" not in g and "febrile" not in g and "MRI" not in g and "Monitor" not in g and "Candida" not in g, g)
write(os.path.join(CV, "s2.py"), syn % ('"25/11 UCx P. aeruginosa S Cipro", "24/11 Wound MSSA (final 26/11)"', "{}"))
rc, o = run(os.path.join(I, "coverage_gate.py"), os.path.join(CV, "s2.py"), os.path.join(CV, "census.json"), os.path.join(CV, "o2"),
            "--date", "2026-11-28", "--day-updates", os.path.join(CV, "day_updates.txt"), "--cultures", os.path.join(CV, "cultures.json"))
ok("coverage_abbreviation_mssa", rc == 0 and o.startswith("COVERAGE OK: ") and "0 waived, 0 missed" in o, o)
write(os.path.join(CV, "s3.py"), syn % ('"25/11 UCx P. aeruginosa S Cipro"', '{"Q1": [{"item": "Wound 2: Staphylococcus aureus", "reason": "test"}]}'))
rc, o = run(os.path.join(I, "coverage_gate.py"), os.path.join(CV, "s3.py"), os.path.join(CV, "census.json"), os.path.join(CV, "o3"),
            "--date", "2026-11-28", "--day-updates", os.path.join(CV, "day_updates.txt"), "--cultures", os.path.join(CV, "cultures.json"))
ok("coverage_waiver", rc == 0 and "1 waived" in o and "WAIVED Q1" in open(os.path.join(CV, "o3", "coverage_gate.txt")).read(), o)
rc, o = run(os.path.join(I, "coverage_gate.py"), os.path.join(CV, "s1.py"), os.path.join(CV, "census.json"), os.path.join(CV, "o4"),
            "--date", "2026-11-28", "--day-updates", os.path.join(CV, "day_updates.txt"), "--cultures", os.path.join(CV, "cultures.json"), "--warn-only")
ok("coverage_warn_only", rc == 0 and o.startswith("COVERAGE WARN: 1 missed"), o)
print("STAGES TESTS OK")
