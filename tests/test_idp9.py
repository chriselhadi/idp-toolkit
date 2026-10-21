#!/usr/bin/env python3
"""Checks for the layout rules of amendment AD (idp9.py, id_list.py groups), fictional data only.

Usage: test_idp9.py <toolkit idp/idp dir> <workdir>. Prints "CHECK <name> OK" per check; exit 1 on the first failure.
"""
import sys, os, json, subprocess, shutil

I, W = sys.argv[1], sys.argv[2]
sys.path.insert(0, I)
import common, idp9  # noqa: E402

shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)


def ok(name, cond, detail=""):
    if not cond:
        print("CHECK %s FAILED%s" % (name, (": " + detail) if detail else ""))
        sys.exit(1)
    print("CHECK %s OK" % name)


# 1. id_list.py groups: ER first, 4th floor split at 420, rooms sorted inside a group
roster = os.path.join(W, "roster.txt")
open(roster, "w").write("\n".join([
    "427B Delta Four MJ", "405 Alpha One CH", "ER3 Echo Five ?", "416 Bravo Two CZ", "420 Charlie Three AC",
    "254 Foxtrot Six MJ", "ICU7D Golf Seven CH", "419 Hotel Eight CH"]) + "\n")
out = subprocess.run([sys.executable, os.path.join(I, "id_list.py"), roster], capture_output=True, text=True).stdout
heads = [l[:-1] for l in out.splitlines() if l.endswith(":")]
ok("idlist_group_order", heads == ["ER", "2nd floor", "4th floor A", "4th floor D", "ICU D"], repr(heads))
blocks = out.split("\n\n")
fa = [b for b in blocks if b.startswith("4th floor A:")][0].splitlines()[1:]
fd = [b for b in blocks if b.startswith("4th floor D:")][0].splitlines()[1:]
ok("idlist_4A_rooms", [l.split()[0] for l in fa] == ["405", "416", "419"], repr(fa))
ok("idlist_4D_rooms", [l.split()[0] for l in fd] == ["420", "427B"], repr(fd))

# 2. apply_id_list: order and membership follow the list; off-list block kept only for the recap
open(os.path.join(W, "id_list_email.txt"), "w").write(out + "\n")
census = {"patients": [
    {"pid": "P1", "room": "405", "name": "ALPHA One", "group": "4th floor"},
    {"pid": "P2", "room": "427B", "name": "Delta Four", "group": "4th floor"},
    {"pid": "P3", "room": "ICU7D", "name": "Golf Seven", "group": "ICU#D"},
    {"pid": "P9", "room": "702", "name": "Zulu Notonlist", "group": "7th floor"}],
    "cs_id_offlist": [{"pid": "P8", "room": "710", "name": "Yankee Off"}, {"pid": "P2", "room": "427B", "name": "Delta Four"}]}
c1 = idp9.apply_id_list(json.loads(json.dumps(census)), W, quiet=True)
ok("order_follows_list", [c["pid"] for c in c1["patients"]] == ["P1", "P2", "P3"], repr([c["pid"] for c in c1["patients"]]))
ok("group_from_list", [c["group"] for c in c1["patients"]] == ["4th floor A", "4th floor D", "ICU D"])
ok("not_on_list_left_out", "P9" not in [c["pid"] for c in c1["patients"]])
ok("handout_no_offlist", c1["cs_id_offlist"] == [])
c2 = idp9.apply_id_list(json.loads(json.dumps(census)), W, quiet=True, keep_offlist=True)
ok("recap_offlist_kept", [o["pid"] for o in c2["cs_id_offlist"]] == ["P8"], repr(c2["cs_id_offlist"]))
ok("ward_order_mutated", common.WARD_ORDER[:2] == ["ER", "2nd floor"] or common.WARD_ORDER[0] in ("4th floor A", "ER"))

# 3. pooled updates: Sunday carries Saturday's email, Monday carries Sunday's pool, Tuesday does not
sat = {"_date": "2026-10-17", "updates": ["o/n: febrile 38.5", "17/10: BCx GNB"]}
sun_e = {"updates": ["o/n: afebrile", "18/10: Mero started"]}
sun = idp9.pooled_fields(sun_e, sat, "2026-10-18")
ok("sunday_pools", sun["updates_pooled"] == ["Fri o/n: febrile 38.5", "17/10: BCx GNB", "o/n: afebrile", "18/10: Mero started"],
   repr(sun["updates_pooled"]))
sun_state = dict(sun_e, _date="2026-10-18", **sun)
mon = idp9.pooled_fields({"updates": ["o/n: no events"]}, sun_state, "2026-10-19")
ok("monday_pools", mon["updates_pooled"][0] == "Fri o/n: febrile 38.5" and "Sat o/n: afebrile" in mon["updates_pooled"]
   and mon["updates_pooled"][-1] == "o/n: no events", repr(mon["updates_pooled"]))
tue = idp9.pooled_fields({"updates": ["19/10: BCx neg"]}, dict(mon, _date="2026-10-19"), "2026-10-20")
ok("tuesday_no_pool", tue["updates_pooled"] == ["19/10: BCx neg"], repr(tue["updates_pooled"]))
nochg = idp9.pooled_fields({"updates": ["no change since 17/10 handout"]}, sat, "2026-10-18")
ok("placeholder_dropped", nochg["updates_pooled"] == ["Fri o/n: febrile 38.5", "17/10: BCx GNB"], repr(nochg["updates_pooled"]))

# 4. validator extras: ID plan inside an issue, pending word in micro, current room in the one_liner
S = {"P1": {"one_liner": "70M ; adm 01/10 via ER, now 405 ; IM: none active", "id_plan": ["bad plan"],
            "issues": [{"dx": "CAP (01/10) | - | ID: stop Ceftriax", "abx": []}],
            "micro": ["01/10 BCx pend"], "micro_recap": "BCx 01/10 neg", "pendings": []}}
errs, warns = [], []
from validate_synth import windows  # noqa: E402
idp9.validate_extra(S, {"P1": {"room": "405"}}, "2026-10-02", errs, warns, windows)
txt = "\n".join(errs)
ok("val_plan_grammar", "id_plan grammar" in txt)
ok("val_issue_plan", "carries an ID plan" in txt)
ok("val_micro_pending", "micro holds results only" in txt)
ok("val_room_once", "repeats the current room 405" in txt)
ok("plan_line_empty", idp9.plan_line({}) == "ID Plan: none documented")
print("IDP9 TESTS OK")
