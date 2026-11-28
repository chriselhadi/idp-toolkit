#!/usr/bin/env python3
"""Chris answers the ID Reconciliation email (Chris, 28.11.2026): stable item keys, --resolved, --learned (text file and
the 'Learned Rules' / 'Answered Items' feed tabs), the HOW TO ANSWER footer, and recon_reply.py. Fictional data only.

Usage: test_recon_reply.py <toolkit idp/idp dir> <workdir>
Prints "CHECK <name> OK" per check; exit 1 on the first failure; "RECON REPLY TESTS OK" at the end.
"""
import json, os, re, shutil, subprocess, sys

I, W = sys.argv[1], sys.argv[2]
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
PY = sys.executable
FOOTER = ("HOW TO ANSWER: reply to this email. Under any item, or anywhere, write its number and your answer, e.g. "
          "\"10: 10 days, the GI plan wins\". Start a line with RULE: to teach a general rule, e.g. \"RULE: BioFire Staph "
          "in 1 of several sets is a contaminant unless repeated\". Write \"undo\" after a learned rule's number to drop it. "
          "The next morning run applies every answer and lists what it learned.")


def ok(name, cond, detail=""):
    if not cond:
        print("CHECK %s FAILED%s" % (name, (": " + str(detail)[-1500:]) if detail else ""))
        sys.exit(1)
    print("CHECK %s OK" % name)


def run(*args):
    r = subprocess.run([PY] + [str(x) for x in args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def P(*n):
    return os.path.join(W, *n)


def write(name, text):
    open(P(name), "w", encoding="utf-8").write(text)
    return P(name)


# Two mornings with the same open issues; the Gemini log entry carries that day's date, the item must keep its key.
write("missing.txt", "- Mike Example One: BCx coll. 20/11 not in the Daily Cultures file\n"
                     "- November Example Two: urine coll. 21/11 not in the Daily Cultures file\n")
glog = lambda d: {"values": [["Date", "Orders", "Tab"], ["'" + d, "3.1, 4.2", "History"]]}
json.dump(glog("26/11/2026"), open(P("glog27.json"), "w"))
json.dump(glog("27/11/2026"), open(P("glog28.json"), "w"))


def recon(day, out, *extra):
    g = P("glog%s.json" % day[-2:])
    rc, o = run(os.path.join(I, "recon.py"), "--date", day, "--out", P(out), "--missing", P("missing.txt"), "--glog", g, *extra)
    ok("recon_runs_" + out, rc == 0 and "RECON OK" in o, o)
    return open(P(out), encoding="utf-8").read(), json.load(open(P(os.path.splitext(out)[0] + ".json")))


t27, j27 = recon("2026-11-27", "r27.txt")
t28, j28 = recon("2026-11-28", "r28.txt")
ok("need_is_list_of_dicts", all(set(x) == {"n", "key", "text"} for x in j28["need"]) and len(j28["need"]) == 3, j28["need"])
ok("keys_stable_across_days", [x["key"] for x in j27["need"]] == [x["key"] for x in j28["need"]]
   and j27["need"][0]["text"] != j28["need"][0]["text"], (j27["need"], j28["need"]))
ok("keys_distinct", len({x["key"] for x in j28["need"]}) == 3)
first = j28["need"][0]
ok("line_numbered_with_key", "\n1. %s [%s]\n" % (first["text"], first["key"]) in t28 and first["key"].startswith("k")
   and len(first["key"]) == 9, t28)
ok("footer_exact", t28.rstrip("\n").endswith("\n\n" + FOOTER), t28[-600:])
rc, o = run(os.path.join(I, "checks_R.py"), "text", P("r28.txt"))
ok("checks_R_text_body", rc == 0 and "CHECKS R OK" in o, o)

# --resolved: a list of {key, until}, and the 'Answered Items' tab
k1, k2, k3 = [x["key"] for x in j28["need"]]
json.dump([{"key": k1, "until": ""}, {"key": k2, "until": "2026-11-27"}, {"key": k3, "until": "2026-12-01"}], open(P("res.json"), "w"))
t, j = recon("2026-11-28", "rres.txt", "--resolved", P("res.json"))
ok("resolved_skips", [x["key"] for x in j["need"]] == [k2] and j["need"][0]["n"] == 1 and "\n1. " in t
   and "- 2 item(s) already answered by Chris, not repeated" in t, t)
json.dump({"values": [["Key", "Date answered", "Item", "Chris answer", "Applied as", "Until"],
                      [k1, "'27/11/26", "x", "known", "noted", ""], [k2, "'27/11/26", "x", "y", "noted", "'27/11/26"],
                      [k3, "'27/11/26", "x", "y", "noted", "'01/12/2026"]]}, open(P("answered_tab.json"), "w"))
t, j = recon("2026-11-28", "rtab.txt", "--resolved", P("answered_tab.json"))
ok("resolved_from_answered_tab", [x["key"] for x in j["need"]] == [k2] and "2 item(s) already answered" in t, t)

# --learned: text file and 'Learned Rules' tab; only rules dated yesterday or today, active ones
write("learned.txt", "20/11/2026 | Old rule never shown again | RULE\n"
                     "27/11/2026 | BioFire Staph in 1 of several sets is a contaminant unless repeated | RULE\n"
                     "28/11/2026 | A urine culture repeated within 48 h is one specimen | %s\n" % k2)
t, j = recon("2026-11-28", "rlearn.txt", "--learned", P("learned.txt"))
sec = t.split("RULES LEARNED FROM YOUR ANSWERS", 1)[1].split("HOW TO ANSWER", 1)[0] if "RULES LEARNED" in t else ""
ok("learned_section_text", "L2. BioFire Staph in 1 of several sets is a contaminant unless repeated (general rule)" in sec
   and "L3. A urine culture repeated within 48 h is one specimen (from item %s)" % k2 in sec and "Old rule" not in sec
   and [r["n"] for r in j["learned"]] == ["L2", "L3"], t)
json.dump({"values": [["No", "Date", "Rule", "From", "Status", "Notes"],
                      ["1", "'20/11/26", "Old rule", "RULE", "active", ""],
                      ["4", "'27/11/26", "Rule four", "RULE", "active", ""],
                      ["5", "'28/11/2026", "Rule five, undone", "RULE", "undone", ""],
                      ["6", "'28/11/26", "Rule six", k1, "active", ""]]}, open(P("rules_tab.json"), "w"))
t, j = recon("2026-11-28", "r.txt", "--learned", P("rules_tab.json"))
ok("learned_section_tab", "L4. Rule four (general rule)" in t and "L6. Rule six (from item %s)" % k1 in t
   and "Rule five" not in t and "Old rule" not in t, t)
rc, o = run(os.path.join(I, "checks_R.py"), "text", P("r.txt"))
ok("checks_R_text_body_learned", rc == 0, o)
t0, _ = recon("2026-11-28", "rnone.txt")
ok("no_learned_section_without_option", "RULES LEARNED" not in t0)

# recon_reply.py on a Gmail reply: numbered answers, inline answers under quoted items, RULE lines, undo, header, signature
q = lambda s: "> " + s
items = [x for x in t.split("NEEDS YOU", 1)[1].split("\n\n", 1)[0].splitlines()[1:]]
reply = "\n".join([
    "1: known, the lab reported it by phone",
    "7) no such item",
    "rule: Only flag a missing culture after 48 h",
    "L4 undo",
    "",
    "On Sat, 28 Nov 2026 at 07:12, Example Sender <sender@example.org>",
    "wrote:",
    q("ID Reconciliation 28.11.2026"), q(""), q("NEEDS YOU (3)"),
    q(items[1]),
    "Seen on the ward round,",
    "sample sent again today.",
    q(items[2]),
    "RULE: Gemini may edit History only for orders 13.x",
    q(""), q("RULES LEARNED FROM YOUR ANSWERS (2)"),
    q("L6. Rule six (from item %s)" % k1),
    "undo",
    q(""), q(FOOTER[:70]), q(FOOTER[70:]),
    "",
    "-- ",
    "Dr Example",
    "2: this signature line is not an answer",
])
write("reply.txt", reply)
rc, o = run(os.path.join(I, "recon_reply.py"), P("reply.txt"), P("r.json"), P("rep"), "--date", "2026-11-29",
            "--rules-tab", P("rules_tab.json"), "--answered-tab", P("answered_tab.json"))
ok("reply_runs", rc == 0 and "REPLY OK: 3 answers, 2 rules, 2 undo, 1 unparsed" in o, o)
A = json.load(open(P("rep", "chris_answers.json")))
by = {x["n"]: x for x in A["answers"]}
ok("reply_plain_numbered", by[1]["answer"] == "known, the lab reported it by phone" and by[1]["key"] == k1, A)
ok("reply_inline_joined", by[2]["answer"] == "Seen on the ward round, sample sent again today." and by[2]["key"] == k2, A)
ok("reply_inline_rule_from_item", by[3]["answer"].startswith("RULE:") and
   {"rule": "Gemini may edit History only for orders 13.x", "from": k3} in A["rule_sources"], A)
ok("reply_rule_lines", A["rules"] == ["Only flag a missing culture after 48 h", "Gemini may edit History only for orders 13.x"]
   and A["rule_sources"][0]["from"] == "RULE", A)
ok("reply_undo", A["undo"] == ["L4", "L6"], A)
ok("reply_unparsed", A["unparsed"] == ["7) no such item"], A)
ok("reply_header_and_signature_ignored", not any("wrote" in x or "signature" in x for x in A["unparsed"])
   and all("signature" not in x["answer"] and "Example Sender" not in x["answer"] for x in A["answers"]), A)
ok("resolved_add", json.load(open(P("rep", "resolved_add.json"))) == [{"key": k, "until": ""} for k in (k1, k2, k3)])
ar = json.load(open(P("rep", "answered_rows.json")))
ok("answered_rows_skip_known_keys", ar == [], ar)   # k1..k3 are already on the Answered Items tab given
rr = json.load(open(P("rep", "rule_rows.json")))
ok("rule_rows_next_no", [r[0] for r in rr] == [7, 8] and rr[0][1:] == ["'29/11/26", "Only flag a missing culture after 48 h", "RULE", "active", ""]
   and rr[1][3] == k3, rr)
ok("undo_ops", json.load(open(P("rep", "undo_ops.json"))) == [{"range": "'Learned Rules'!E3", "values": [["undone"]]},
                                                            {"range": "'Learned Rules'!E5", "values": [["undone"]]}])
# without the tabs: every answered key becomes an Answered Items row, rules start after the learned numbers seen
rc, o = run(os.path.join(I, "recon_reply.py"), P("reply.txt"), P("r.json"), P("rep2"), "--date", "2026-11-29")
ar = json.load(open(P("rep2", "answered_rows.json")))
ok("answered_rows_without_tab", [r[0] for r in ar] == [k1, k2, k3] and ar[1][3] == "Seen on the ward round, sample sent again today."
   and ar[0][1] == "'29/11/26", ar)
ok("rule_rows_without_tab", [r[0] for r in json.load(open(P("rep2", "rule_rows.json")))] == [7, 8])
txt = open(P("rep", "chris_answers.txt")).read()
ok("answers_txt", "ANSWERS (3)" in txt and "UNDO (2)" in txt and "UNPARSED (1)" in txt, txt)

# other answer styles and an empty reply
write("reply2.txt", "3 - repeat sent\n2. noted\n1) fine\n12: unknown item\nThanks\n")
rc, o = run(os.path.join(I, "recon_reply.py"), P("reply2.txt"), P("r.json"), P("rep3"), "--date", "2026-11-29")
A = json.load(open(P("rep3", "chris_answers.json")))
ok("reply_styles", "REPLY OK: 3 answers, 0 rules, 0 undo, 1 unparsed" in o and
   [x["answer"] for x in A["answers"]] == ["fine", "noted", "repeat sent"] and A["unparsed"] == ["12: unknown item"], o + str(A))
write("reply3.txt", "Thanks, all fine.\n\nOn Sat, 28 Nov 2026, X wrote:\n" + "\n".join(q(x) for x in t.splitlines()))
rc, o = run(os.path.join(I, "recon_reply.py"), P("reply3.txt"), P("r.json"), P("rep4"), "--date", "2026-11-29")
ok("reply_nothing", "REPLY OK: 0 answers, 0 rules, 0 undo, 0 unparsed" in o, o)
print("RECON REPLY TESTS OK")

# --items (28.11.2026): each non-empty line of out/run_items.txt is a NEEDS YOU item with a stable key
write("items27.txt", "possibly gone: P0123 Mike Example One, not on the AS list since 26/11\n\n"
                     "ROOM UNRESOLVED November Example Two (roster 708B, AS list blank)\n- merge P0001 into P0002\n   \n")
write("items28.txt", "possibly gone: P0123 Mike Example One, not on the AS list since 27/11\n"
                     "ROOM UNRESOLVED November Example Two (roster 708B, AS list blank)\nmerge P0001 into P0002\n")
rc, o = run(os.path.join(I, "recon.py"), "--date", "2026-11-27", "--out", P("ri27.txt"), "--items", P("items27.txt"))
ri27 = json.load(open(P("ri27.json")))
rc2, o2 = run(os.path.join(I, "recon.py"), "--date", "2026-11-28", "--out", P("ri28.txt"), "--items", P("items28.txt"))
ri28, rt28 = json.load(open(P("ri28.json"))), open(P("ri28.txt")).read()
ok("items_need_you", rc == 0 and rc2 == 0 and "RECON OK: 3 need Chris" in o2
   and [x["text"] for x in ri28["need"]] == ["Run: possibly gone: P0123 Mike Example One, not on the AS list since 27/11",
                                            "Run: ROOM UNRESOLVED November Example Two (roster 708B, AS list blank)",
                                            "Run: merge P0001 into P0002"], o2 + json.dumps(ri28["need"]))
ok("items_keys_stable", [x["key"] for x in ri27["need"]] == [x["key"] for x in ri28["need"]]
   and all(re.fullmatch(r"k[0-9a-f]{8}", x["key"]) for x in ri28["need"]) and len({x["key"] for x in ri28["need"]}) == 3, ri27["need"])
ok("items_lines_in_body", "3. Run: merge P0001 into P0002 [%s]" % ri28["need"][2]["key"] in rt28, rt28)
json.dump([{"key": ri28["need"][2]["key"], "until": ""}], open(P("ri_res.json"), "w"))
rc, o = run(os.path.join(I, "recon.py"), "--date", "2026-11-28", "--out", P("ri28b.txt"), "--items", P("items28.txt"), "--resolved", P("ri_res.json"))
ok("items_answered_skipped", "RECON OK: 2 need Chris" in o and "1 already answered" in o, o)
write("items_empty.txt", "\n  \n")
rc, o = run(os.path.join(I, "recon.py"), "--date", "2026-11-28", "--out", P("ri_e.txt"), "--items", P("items_empty.txt"))
ok("items_empty_file", "RECON OK: 0 need Chris" in o and "Run: no item raised for Chris" in open(P("ri_e.txt")).read(), o)
rc, o = run(os.path.join(I, "recon.py"), "--date", "2026-11-28", "--out", P("ri_m.txt"), "--items", P("no_such_items.txt"))
ok("items_missing_file", rc == 0 and "run items (no_such_items.txt missing)" in open(P("ri_m.txt")).read(), o)
rc, o = run(os.path.join(I, "recon.py"), "--date", "2026-11-28", "--out", P("ri_n.txt"))
ok("items_flag_absent", "run items" not in open(P("ri_n.txt")).read().lower() and "Run:" not in open(P("ri_n.txt")).read())
print("RECON ITEMS TESTS OK")
