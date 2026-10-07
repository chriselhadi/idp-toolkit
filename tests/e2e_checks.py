#!/usr/bin/env python3
"""Assertions for run_e2e.sh. Usage: e2e_checks.py <check name> [args...]

Prints "CHECK <name> OK", or "CHECK <name> FAILED: <reason>" and exits 1. Run from a day's workdir.
"""
import sys, os, json, importlib.util


def jl(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def census():
    return jl("out/census.json")


def one(name, pats=None):
    hits = [p for p in (pats if pats is not None else census()["patients"]) if p["name"] == name]
    assert len(hits) == 1, "%d census rows named %r" % (len(hits), name)
    return hits[0]


def pids_like(state, token):
    """pids whose name or any alias contains token (case-insensitive)."""
    t = token.lower()
    return [pid for pid, r in state["patients"].items() if any(t in n.lower() for n in [r["name"]] + r.get("aliases", []))]


def load_synth(path="synth.py"):
    spec = importlib.util.spec_from_file_location("synth_under_test", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


# ---- checks ----
def as_rows_today(today, quoted_only_mrn, today_mrn):
    """parse_as picked today's XLSX attachment, not the table quoted in the reply."""
    a = jl("in/as_today.json")
    fn = "AS list %s.%s.%s.XLSX" % (today[8:10], today[5:7], today[:4])
    assert a["source_used"] == "attachment:" + fn, "source_used=%r" % a["source_used"]
    assert a["list_date"] == today, "list_date=%r" % a["list_date"]
    mrns = {p["mrn"] for p in a["patients"]}
    assert quoted_only_mrn not in mrns, "MRN %s from the quoted (yesterday's) table was parsed" % quoted_only_mrn
    assert today_mrn in mrns, "today's MRN %s missing" % today_mrn
    assert all(o["valid_to"] == today for p in a["patients"] for o in p["orders"]), "an order row is not from today's list"


def roster_lines():
    """'?' initials, a CCU line, an 'ER IN' line, roster room vs ward-doc room."""
    c = census(); st = jl("out/state_matched.json")
    mike = one("Mike Tester Eleven")
    assert mike["fellow"] == "" and mike["room"] == "311", "'?' initials line: %r" % mike
    hotel = one("Hotel Tester Eight")
    assert (hotel["room"], hotel["fellow"]) == ("CCU2", "MJ"), "CCU line: %r" % hotel
    india = one("India Tester Nine")
    assert india["room"] == "ER" and india["fellow"] == "", "ER IN line: %r" % india
    assert not [p for p in c["patients"] if p["name"].upper().startswith("IN ")], "'IN' parsed into a name"
    nov = one("November Tester Twelve")
    assert nov["room"] == "409" and nov["room_source"] == "roster", "roster room not kept: %r" % nov["room"]
    assert len(pids_like(st, "November")) == 1, "duplicate pid for November: %s" % pids_like(st, "November")
    flags = open("out/flags.txt", encoding="utf-8").read()
    assert "handoff doc room 411 differs from today's list room 409" in flags, "room-difference flag missing"


def blank_bed_keeps_roster_room():
    o = one("Oscar Tester Fourteen")
    assert "as" in o["provenance"], "Oscar not matched to the AS list: %r" % o["provenance"]
    assert (o["room"], o["room_source"]) == ("312", "roster"), "room %r from %r" % (o["room"], o["room_source"])


def synth_extras():
    """micro_recap, UC im_detail, SIGNED_OFF for every off-list entry, conflicts, not_applied; and they render."""
    c = census(); mod = load_synth(); S = mod.SYNTH
    assert any(e.get("micro") and e.get("micro_recap") for e in S.values()), "no micro_recap with non-empty micro"
    uc = [p["pid"] for p in c["patients"] if "uc" in p["tags"]]
    assert uc and all(S[p].get("im_detail") for p in uc), "UC patient without im_detail"
    off = c.get("cs_id_offlist", [])
    assert off, "census has no cs_id_offlist entry"
    assert all((mod.SIGNED_OFF.get(o["pid"]) or "").strip() for o in off), "SIGNED_OFF misses an off-list pid"
    assert sum(len(e.get("conflicts") or []) for e in S.values()) >= 1, "no conflicts entry"
    na = [(pid, d) for pid, e in S.items() for d in (e.get("not_applied") or {})]
    assert na, "no not_applied entry"
    for pid, d in na:
        lines = [a for i in S[pid]["issues"] for a in i["abx"]] + S[pid]["abx_other"]
        assert any(l.split()[0] == d for l in lines), "not_applied %s has no drug line" % d
    wa = open("out/whatsapp.txt", encoding="utf-8").read()
    for frag in ["Micro: ", "\nIM: ", "!! Conflict: ", "!! ID rec not applied, ", "*Off the ID list"] + \
                ["%s %s: %s" % (o["room"], o["name"], mod.SIGNED_OFF[o["pid"]]) for o in off]:
        assert frag in wa, "whatsapp.txt lacks %r" % frag


def spelling_variant_no_new_pid(d1_state):
    """'Rania Juliet' (handoff, ID consulted, room 405) is the day-1 'RANIYA Kilo JULIET' (707A, off the list today)."""
    s1 = jl(d1_state); s2 = jl("out/state_matched.json"); c = census()
    old = pids_like(s1, "raniya")
    assert len(old) == 1, "day-1 Raniya pids: %s" % old
    assert not pids_like(s2, "rania") or pids_like(s2, "rania") == old, "a pid was minted for Rania: %s" % pids_like(s2, "rania")
    off = [o for o in c["cs_id_offlist"] if o["pid"] == old[0]]
    assert off and off[0]["room"] == "405", "cs_id_offlist lacks %s in 405: %s" % (old[0], c["cs_id_offlist"])
    new = sorted(set(s2["patients"]) - set(s1["patients"]))
    assert [s2["patients"][p]["name"] for p in new] == ["Lima Tester Ten"], "new pids on day 2: %s" % new
    assert s2["next_pid"] == s1["next_pid"] + 1, "next_pid %s -> %s" % (s1["next_pid"], s2["next_pid"])


def chain_equal(rebuilt, day2_state):
    a, b = jl(rebuilt), jl(day2_state)
    assert a == b, "rebuilt chain state differs from day-2 state_new.json"


CHECKS = {f.__name__: f for f in (as_rows_today, roster_lines, blank_bed_keeps_roster_room, synth_extras,
                                  spelling_variant_no_new_pid, chain_equal)}

if __name__ == "__main__":
    name = sys.argv[1]
    try:
        CHECKS[name](*sys.argv[2:])
    except (AssertionError, KeyError, OSError, ValueError) as e:
        print("CHECK %s FAILED: %s: %s" % (name, e.__class__.__name__, e))
        sys.exit(1)
    print("CHECK %s OK" % name)
