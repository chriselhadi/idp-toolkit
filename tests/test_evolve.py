#!/usr/bin/env python3
"""Notes evolve, never rewritten (Chris, 28.11.2026): idp10 evolve and assemble, the Evolution and Gemini Review feed
tabs, idp11 review / reviewreply, and the recon additions. Fictional data only.

Usage: test_evolve.py <toolkit idp/idp dir> <workdir> <day-2 run dir of the e2e run>
Prints "CHECK <name> OK" per check; exit 1 on the first failure; "EVOLVE TESTS OK" at the end.
"""
import importlib.util, json, os, pprint, shutil, subprocess, sys

I, W, D2 = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
PY = sys.executable


def ok(name, cond, detail=""):
    if not cond:
        print("CHECK %s FAILED%s" % (name, (": " + str(detail)[-1500:]) if detail else ""))
        sys.exit(1)
    print("CHECK %s OK" % name)


def run(*args):
    r = subprocess.run([PY] + [str(x) for x in args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def mod(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


YDAY = {
    "name": "Mike Example One", "one_liner": "68F, DM2; adm 20/11 via ER; IM: none active.",
    "issues": [{"dx": "Cellulitis L leg (20/11) | BCx neg | improving", "abx": ["Cefazolin IV q8h 20/11-"]}],
    "abx_other": [], "micro": ["20/11 BCx neg x2"], "micro_recap": "BCx 20/11 neg",
    "vitals": ["afebrile since 22/11 | no pressors | RA"], "pendings": ["Wound cx (21/11) -> narrow"],
    "id_plan": ["IV to PO when afebrile 48 h (ID attending)"], "conflicts": [], "not_applied": {},
    "im_detail": [], "steroids": [], "devices": ["PIV L arm 20/11"], "updates": ["new to service today"],
    "log_id": "", "log_im": ""}
state = {"patients": {"P9101": {"name": "Mike Example One", "synth": YDAY},
                      "P9102": {"name": "November Example Two", "synth": dict(YDAY, name="November Example Two")}}}
sp = os.path.join(W, "state.json")
json.dump(state, open(sp, "w"))


def synth_file(name, synth, changes=None):
    p = os.path.join(W, name)
    with open(p, "w") as f:
        f.write("SYNTH = %s\n" % pprint.pformat(synth, width=160))
        if changes is not None:
            f.write("CHANGES = %s\n" % pprint.pformat(changes, width=160))
    return p


def today(**k):
    e = json.loads(json.dumps(YDAY)); e.update(k); return e


# 1. nothing changed: 0 / 0, exit 0; a pid new today is not compared
p = synth_file("s_same.py", {"P9101": today(), "P9103": today(name="Oscar Example Three")})
rc, out = run(os.path.join(I, "idp10.py"), "evolve", p, sp, os.path.join(W, "e0"), "--date", "2026-11-23")
ok("evolve_no_change", rc == 0 and "EVOLVE OK: 0 changes explained, 0 unexplained" in out, out)
ev = json.load(open(os.path.join(W, "e0", "evolution.json")))
ok("evolve_new_pid_not_compared", ev["new_today"] == 1 and ev["carried"] == 1, ev)

# 2. list add / remove / edit, all explained -> exit 0, kinds right
t = today(micro=["22/11 Wound cx S. aureus MSSA", "20/11 BCx neg x2"],          # NEW item
          pendings=[],                                                          # RETRACTED item
          issues=[{"dx": "Cellulitis L leg (20/11) | BCx neg, wound MSSA | improving", "abx": ["Cefazolin IV q8h 20/11-"]}],  # AMENDED dx
          micro_recap="BCx 20/11 neg; wound 22/11 MSSA")
ch = {"P9101": [
    {"field": "micro", "kind": "NEW", "old": "", "new": "22/11 Wound cx S. aureus MSSA", "source": "Daily Cultures 23/11"},
    {"field": "pendings", "kind": "RETRACTED", "old": "Wound cx (21/11) -> narrow", "new": "", "source": "Daily Cultures 23/11 (final)"},
    {"field": "dx", "kind": "AMENDED", "old": "Cellulitis L leg (20/11) | BCx neg | improving",
     "new": "Cellulitis L leg (20/11) | BCx neg, wound MSSA | improving", "source": "Daily Cultures 23/11"},
    {"field": "micro_recap", "kind": "AMENDED", "old": "BCx 20/11 neg", "new": "BCx 20/11 neg; wound 22/11 MSSA", "source": "Daily Cultures 23/11"}]}
p = synth_file("s_ok.py", {"P9101": t}, ch)
rc, out = run(os.path.join(I, "idp10.py"), "evolve", p, sp, os.path.join(W, "e1"), "--date", "2026-11-23")
ok("evolve_explained", rc == 0 and "EVOLVE OK: 4 changes explained, 0 unexplained" in out, out)
ev = json.load(open(os.path.join(W, "e1", "evolution.json")))
kinds = sorted((c["field"], c["kind"]) for c in ev["patients"]["P9101"]["changes"])
ok("evolve_list_kinds", kinds == [("issues", "AMENDED"), ("micro", "NEW"), ("micro_recap", "AMENDED"), ("pendings", "RETRACTED")], kinds)
txt = open(os.path.join(W, "e1", "evolution.txt")).read()
ok("evolve_txt_sources", "NEW micro: '22/11 Wound cx S. aureus MSSA' [source: Daily Cultures 23/11]" in txt and "UNEXPLAINED" not in txt, txt)

# 3. a wording-only rewrite of yesterday's one-liner and an edited drug line with no CHANGES entry -> unexplained, exit 1
t = today(one_liner="68 y/o F with DM2, admitted 20/11 via the ER; IM: nothing active.",
          issues=[{"dx": YDAY["issues"][0]["dx"], "abx": ["Cefazolin IV q8h 20/11-23/11"]}],
          abx_other=["Doxy PO BID 23/11-"])
p = synth_file("s_bad.py", {"P9101": t}, {"P9101": [
    {"field": "abx", "kind": "NEW", "old": "", "new": "Doxy PO BID 23/11-", "source": ""}]})   # no source: still unexplained
rc, out = run(os.path.join(I, "idp10.py"), "evolve", p, sp, os.path.join(W, "e2"), "--date", "2026-11-23")
ok("evolve_unexplained_exit1", rc == 1 and "EVOLVE OK: 0 changes explained, 3 unexplained" in out, out)
txt = open(os.path.join(W, "e2", "evolution.txt")).read()
ok("evolve_rewrite_unexplained", "UNEXPLAINED AMENDED one_liner" in txt and "UNEXPLAINED AMENDED abx" in txt
   and "CHANGES entry has no source" in txt, txt)
ev = json.load(open(os.path.join(W, "e2", "evolution.json")))
ok("evolve_unexplained_by_field", ev["unexplained_by_field"] == {"one_liner": 1, "abx": 2}, ev["unexplained_by_field"])

# 4. a CHANGES entry that matches nothing is reported, not counted
p = synth_file("s_unused.py", {"P9101": today()}, {"P9101": [{"field": "vitals", "kind": "AMENDED", "old": "x", "new": "y", "source": "z"}]})
rc, out = run(os.path.join(I, "idp10.py"), "evolve", p, sp, os.path.join(W, "e3"), "--date", "2026-11-23")
ok("evolve_unused_entry", rc == 0 and "WARN unused CHANGES entry P9101 AMENDED vitals" in out, out)

# 5. assemble carries CHANGES from synth_delta.py into synth.py
base = os.path.join(W, "synth_base.py")
open(base, "w").write("BASE = %s\nPRIOR = {}\n" % pprint.pformat({"P9101": dict(YDAY)}))
delta = os.path.join(W, "synth_delta.py")
open(delta, "w").write("DELTA = {'P9101': {'pend_close': ['Wound cx']}}\nNEW = {}\nCHANGES = %s\n" % pprint.pformat(
    {"P9101": [{"field": "pendings", "kind": "RETRACTED", "old": "Wound cx (21/11) -> narrow", "new": "", "source": "Daily Cultures 23/11"}]}))
rc, out = run(os.path.join(I, "idp10.py"), "assemble", base, delta, os.path.join(W, "synth_asm.py"), "--date", "2026-11-23")
S = mod("synth_asm", os.path.join(W, "synth_asm.py"))
ok("assemble_carries_changes", rc == 0 and S.CHANGES["P9101"][0]["kind"] == "RETRACTED" and S.SYNTH["P9101"]["pendings"] == [], out)
rc, out = run(os.path.join(I, "idp10.py"), "evolve", os.path.join(W, "synth_asm.py"), sp, os.path.join(W, "e4"), "--date", "2026-11-23")
ok("assemble_then_evolve", rc == 0 and "EVOLVE OK: 1 changes explained, 0 unexplained" in out, out)

# 6. feed: the Evolution tab (today's rows appended, no duplicate on a rerun) and the Gemini Review header only when absent
X = mod("idp11_t", os.path.join(I, "idp11.py"))
ok("feed_schema_6", X.SCHEMA_VERSION == "6" and X.EVOLUTION == ["pid", "Date", "Field", "Kind", "Old", "New", "Source", "Updated"]
   and X.REVIEW == ["Date", "pid", "Patient", "Field", "View", "Statement", "Evidence", "Claude reply", "Claude reason", "Resolved", "Escalated"]
   and any(r[0] == "Evolution" for r in X.schema_rows("feed")) and any(r[0] == "Gemini Review" for r in X.schema_rows("feed")))
fd = os.path.join(W, "feedrun"); now = os.path.join(fd, "now"); os.makedirs(now)
ev = json.load(open(os.path.join(W, "e1", "evolution.json")))
ev["patients"]["P9101"]["changes"].append({"field": "vitals", "kind": "AMENDED", "old": "a", "new": "b", "source": "", "explained": False})
json.dump(ev, open(os.path.join(fd, "evolution.json"), "w"))
args = [os.path.join(I, "idp11.py"), "feed", os.path.join(D2, "out", "state_new.json"), os.path.join(D2, "out", "census.json"),
        "MISSING", "MISSING", now, os.path.join(fd, "feed"), "--date", "2026-11-23"]
rc, out = run(*args)
ops = json.load(open(os.path.join(fd, "feed", "ops.json")))
evo = [o for o in ops if o["range"].startswith("'Evolution'")]
rev = [o for o in ops if o["range"].startswith("'Gemini Review'")]
rows = [r for o in evo[1:] for r in o["values"]]
ok("feed_evolution_rows", rc == 0 and "5 evolution row(s)" in out and evo[0]["values"] == [X.EVOLUTION]
   and evo[1]["range"] == "'Evolution'!A2:H6" and rows[1][:4] == ["P9101", "'23/11/26", "micro", "NEW"]
   and rows[-1][6] == "UNEXPLAINED" and all(len(r) == 8 and r[7] == "'23/11/26" for r in rows), out + json.dumps(evo)[:800])
ok("feed_review_header_when_absent", rev == [{"range": "'Gemini Review'!A1:K1", "values": [X.REVIEW]}], rev)
hdr_now = [list(X.TABS[t][0]) for t in X.TABS]
ok("feed_existing_headers_unchanged", hdr_now[0][:3] == ["pid", "MRN", "Name"] and len(hdr_now[0]) == 28 and X.CHANGES == ["Date", "pid", "Tab", "Key", "Field", "Old", "New"])
# rerun the same day with the Evolution tab already holding yesterday's and today's rows, and Gemini's tab present
json.dump({"values": [X.EVOLUTION, ["P9101", "'22/11/26", "one_liner", "AMENDED", "x", "y", "AS list", "'22/11/26"]]
           + rows}, open(os.path.join(now, "evolution.json"), "w"))
json.dump({"values": [X.REVIEW, ["22/11/26", "P9101", "Mike Example One", "issues", "disagree", "Cellulitis is resolving, not improving", "Ward note 22/11"]]},
          open(os.path.join(now, "review.json"), "w"))
rc, out = run(*args)
ops = json.load(open(os.path.join(fd, "feed", "ops.json")))
ok("feed_rerun_no_duplicates", rc == 0 and "0 evolution row(s)" in out and not any(o["range"].startswith("'Evolution'") for o in ops), out)
ok("feed_never_touches_review_tab", not any("Gemini Review" in o["range"] for o in ops), [o["range"] for o in ops])

# 7. review and reviewreply: answers go to H..K only; an unanswered point older than one round is escalated
rvp = os.path.join(W, "review.json")
json.dump({"values": [X.REVIEW,
                      ["27/11/26", "P9101", "Mike Example One", "issues", "disagree", "Improving is too strong", "Wound photo 27/11"],
                      ["27/11/26", "P9102", "November Example Two", "pendings", "missing", "Wound cx not listed", "Daily Cultures 27/11"],
                      ["25/11/26", "P9102", "November Example Two", "abx", "suggestion", "Note planned stop date", "AMS sheet"],
                      ["26/11/26", "P9101", "Mike Example One", "micro", "agree", "MSSA recorded", "Daily Cultures", "accepted", "matches", "27/11/26", ""]]},
          open(rvp, "w"))
rc, out = run(os.path.join(I, "idp11.py"), "review", rvp, os.path.join(W, "rv"), "--date", "2026-11-28")
txt = open(os.path.join(W, "rv", "review_open.txt")).read()
ok("review_open_list", rc == 0 and "REVIEW OK: 3 open, 1 open more than one round" in out and "row 2 |" in txt and "row 4 |" in txt
   and "row 5 |" not in txt and "OPEN MORE THAN ONE ROUND" in txt, out + txt)
rp = os.path.join(W, "review_replies.json")
json.dump({"2": {"reply": "rejected", "reason": "Ward note 27/11 documents improvement"},
           "3": {"reply": "accepted", "reason": "Wound cx 21/11 added to pendings"}}, open(rp, "w"))
rc, out = run(os.path.join(I, "idp11.py"), "reviewreply", rp, rvp, os.path.join(W, "rvo"), "--date", "2026-11-28")
rops = json.load(open(os.path.join(W, "rvo", "review_ops.json")))
cells = {}
for o in rops:
    rng = o["range"].split("!")[1]
    a, b = rng.split(":")
    ok("reviewreply_columns_%s" % rng.replace(":", "_"), a[0] == "H" and b[0] == "K" and all(len(v) == 4 for v in o["values"]), o)
    for k, v in enumerate(o["values"]):
        cells[int(a[1:]) + k] = v
ok("reviewreply_values", rc == 0 and cells[2] == ["rejected", "Ward note 27/11 documents improvement", "", "Y"]
   and cells[3] == ["accepted", "Wound cx 21/11 added to pendings", "'28/11/26", ""]
   and cells[4] == [None, None, None, "Y"] and 5 not in cells, out + json.dumps(cells))
ok("reviewreply_counts", "REVIEWREPLY OK: 2 repl(ies), 2 escalated" in out, out)
json.dump({"5": {"reply": "rejected", "reason": "x"}}, open(rp, "w"))
rc, out = run(os.path.join(I, "idp11.py"), "reviewreply", rp, rvp, os.path.join(W, "rvo2"), "--date", "2026-11-28")
ok("reviewreply_refuses_answered_row", rc == 1 and "already has a Claude reply" in out, out)
json.dump({"2": {"reply": "maybe", "reason": "x"}}, open(rp, "w"))
rc, out = run(os.path.join(I, "idp11.py"), "reviewreply", rp, rvp, os.path.join(W, "rvo3"), "--date", "2026-11-28")
ok("reviewreply_refuses_bad_reply", rc == 1 and "REVIEWREPLY FAILED" in out, out)

# 8. recon: Evolution summary under CHECKED, escalated and rejected review rows under NEEDS YOU
json.dump({"values": [X.REVIEW,
                      ["27/11/26", "P9101", "Mike Example One", "issues", "disagree", "Improving is too strong", "Wound photo", "rejected", "Ward note documents improvement", "", "Y"],
                      ["25/11/26", "P9102", "November Example Two", "abx", "suggestion", "Note planned stop date", "AMS sheet", "", "", "", "Y"],
                      ["26/11/26", "P9101", "Mike Example One", "micro", "agree", "MSSA recorded", "Daily Cultures", "accepted", "matches", "27/11/26", ""]]},
          open(os.path.join(W, "review_after.json"), "w"))
rc, out = run(os.path.join(I, "recon.py"), "--date", "2026-11-28", "--out", os.path.join(W, "recon.txt"),
              "--evolution", os.path.join(W, "e2", "evolution.json"), "--review", os.path.join(W, "review_after.json"))
txt = open(os.path.join(W, "recon.txt")).read()
need = txt.split("NEEDS YOU", 1)[1].split("SETTLED", 1)[0]
chk = txt.split("CHECKED, IN AGREEMENT", 1)[1]
ok("recon_evolution_checked", "Evolution: 0 change(s) to yesterday's synthesis explained (NEW 1, AMENDED 2, RETRACTED 0), 3 unexplained" in chk, txt)
ok("recon_review_needs_you", "Gemini review row 2 (P9101" in need and "Claude rejected: Ward note documents improvement" in need
   and "Gemini review row 3 (P9102" in need and "[escalated]" in need and "row 4" not in need
   and "Gemini review: 3 point(s), 2 escalated, 1 rejected" in chk, txt)
rc, out = run(os.path.join(I, "recon.py"), "--date", "2026-11-28", "--out", os.path.join(W, "recon0.txt"))
ok("recon_without_inputs", "Evolution (no evolution.json)" in open(os.path.join(W, "recon0.txt")).read() and "Gemini review" in open(os.path.join(W, "recon0.txt")).read())
print("EVOLVE TESTS OK")
