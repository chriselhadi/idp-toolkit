#!/usr/bin/env python3
"""Cross-day verification: today's record against yesterday's, the census, the AS list and the culture files.

    python3 verify_days.py <state.json|MISSING> out/state_new.json out/census.json <as_today.json|MISSING> \
        <cultures.json|MISSING> out --date YYYY-MM-DD [--synth synth.py]

The validator checks one day's grammar. This checks that facts survive from one day to the next and agree across
sources, so nothing is silently lost while a patient's story evolves:
  * a running drug, a resulted culture or a pending item that existed yesterday must still be there today, or be
    accounted for (stopped segment, result in micro, closure stated in updates);
  * every restricted drug on today's AS list has a running course; every final culture in Daily_Cultures for a
    census patient is in that patient's micro list;
  * identity is stable (same pid, same MRN), nobody vanishes without being archived today;
  * computed changes (drug started or stopped, new culture, pending resolved) appear in `updates`.

Each finding has an id like E_DRUG_DROPPED:P0001:Mero. ERROR findings block the sends (exit 1) until fixed in
synth.py, or acknowledged there with a source-based reason:
    VERIFIED = {"E_DRUG_DROPPED:P0001:Mero": "updates email 10/10: Mero stopped 09/10"}
An acknowledgement without a reason, or for an id that no longer fires, is itself reported.
Writes out/verification.json and out/verification.txt; prints VERIFY OK or VERIFY FAILED.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datamodel import DOSE_RE, patient_record  # noqa: E402

LONG_COURSE_DAYS = 14
PENDING_STALE_DAYS = 3
PRELIM_STALE_DAYS = 5


def load(path):
    if not path or path == "MISSING" or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_verified(path):
    if not path or not os.path.exists(path):
        return {}
    ns = {"__file__": os.path.abspath(path), "__name__": "synth"}
    try:
        exec(compile(open(path, encoding="utf-8").read(), path, "exec"), ns)
    except Exception as e:  # the validator reports synth.py errors; here we only need VERIFIED
        print("WARN could not load VERIFIED from %s: %s" % (path, e))
        return {}
    v = ns.get("VERIFIED") or {}
    return v if isinstance(v, dict) else {}


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def micro_key(m):
    return (m["date"] or ("prior" if m["prior"] else ""), norm(m["specimen"]))


class Findings:
    def __init__(self):
        self.items = []

    def add(self, sev, code, pid, key, msg, name="", room=""):
        fid = "%s:%s:%s" % (code, pid or "-", key or "-")
        self.items.append({"id": fid, "severity": sev, "code": code, "pid": pid, "name": name, "room": room,
                           "key": key, "message": msg})


def computed_changes(prev, cur):
    """What moved between yesterday's and today's record, derived from the structure alone."""
    out = []
    pc = {c["drug"]: c for c in (prev or {}).get("courses", [])}
    for c in cur["courses"]:
        p = pc.get(c["drug"])
        if c["running"] and (not p or not p["running"]):
            out.append({"kind": "abx_started", "text": "%s started %s" % (c["drug"], c["start"] or "?")})
        if p and p["running"] and not c["running"]:
            out.append({"kind": "abx_stopped", "text": "%s stopped %s" % (c["drug"], c["stop"] or "?")})
    pm = {micro_key(m): m for m in (prev or {}).get("micro", [])}
    for m in cur["micro"]:
        k = micro_key(m)
        if k not in pm:
            out.append({"kind": "micro_new", "text": m["text"]})
        elif norm(pm[k]["result"]) != norm(m["result"]):
            out.append({"kind": "micro_changed", "text": "%s (was: %s)" % (m["text"], pm[k]["result"])})
    cp = {norm(p["item"]) for p in cur["pendings"]}
    for p in (prev or {}).get("pendings", []):
        if norm(p["item"]) not in cp:
            out.append({"kind": "pending_closed", "text": p["text"]})
    if prev and prev.get("room") and cur.get("room") and prev["room"] != cur["room"]:
        out.append({"kind": "moved", "text": "%s -> %s" % (prev["room"], cur["room"])})
    return out


def text_blob(r):
    parts = [r["one_liner"], r["micro_recap"]] + r["updates"] + r["updates_nonid"] + r["imaging"] + r["im_detail"]
    parts += [r["status"]["text"]] + r["conflicts"] + list(r["not_applied"].values())
    parts += [i["text"] for i in r["issues"]] + [c["line"] for c in r["courses"]]
    parts += [m["text"] for m in r["micro"]] + [p["text"] for p in r["pendings"]]
    return parts


def run(a):
    ref = dt.date.fromisoformat(a.date)
    prev_state = load(a.prev) or {}
    state = load(a.state) or {}
    census = load(a.census) or {}
    as_today = load(a.as_today)
    cultures = load(a.cultures)
    verified = load_verified(a.synth)
    yday = ref - dt.timedelta(days=1)
    F = Findings()

    prev_recs = {pid: patient_record(pid, r, yday) for pid, r in (prev_state.get("patients") or {}).items()}
    cur_recs = {pid: patient_record(pid, r, ref) for pid, r in (state.get("patients") or {}).items()}
    cpat = {p["pid"]: p for p in census.get("patients") or []}
    archived_today = {x.get("pid") if isinstance(x, dict) else x for x in census.get("archived_today") or []}
    off_block = {x.get("pid") if isinstance(x, dict) else x for x in census.get("cs_id_offlist") or []}
    changes = {}

    # identity and membership
    for pid, p in prev_recs.items():
        c = cur_recs.get(pid)
        if p["active"] and (not c or not c["active"]) and pid not in archived_today and pid not in off_block:
            F.add("ERROR", "E_PATIENT_VANISHED", pid, "", "active yesterday, not on today's census and not archived "
                  "today", p["name"], p["room"])
        if c and p["mrn"] and c["mrn"] and p["mrn"] != c["mrn"]:
            F.add("ERROR", "E_MRN_CHANGED", pid, c["mrn"], "MRN %s yesterday, %s today" % (p["mrn"], c["mrn"]),
                  c["name"], c["room"])

    for pid, cp in cpat.items():
        r = cur_recs.get(pid)
        if not r:
            F.add("ERROR", "E_NO_RECORD", pid, "", "on today's census, no record in state_new.json",
                  cp.get("name", ""), cp.get("room", ""))
            continue
        n, room = r["name"], r["room"] or cp.get("room", "")
        p = prev_recs.get(pid)
        if cp.get("room") and r["room"] and cp["room"] != r["room"]:
            F.add("WARN", "W_ROOM_MISMATCH", pid, "", "census room %s, record room %s" % (cp["room"], r["room"]), n, room)

        # one day's content
        if not r["status"]["text"]:
            F.add("ERROR", "E_NO_STATUS", pid, "", "no status line (vitals[0])", n, room)
        for c in r["courses"]:
            if not c["parse_ok"]:
                F.add("ERROR", "E_ABX_PARSE", pid, c["drug"], "drug line does not follow the grammar: %r" % c["line"],
                      n, room)
            if c["running"] and c["days"] >= LONG_COURSE_DAYS:
                F.add("INFO", "I_LONG_COURSE", pid, c["drug"], "%s running, D%d" % (c["drug"], c["days"]), n, room)
        running = [c["drug"] for c in r["courses"] if c["running"]]
        for d in sorted({d for d in running if running.count(d) > 1}):
            F.add("WARN", "W_DRUG_TWICE", pid, d, "%s has two running lines" % d, n, room)
        for t in text_blob(r):
            m = DOSE_RE.search(t or "")
            if m:
                F.add("ERROR", "E_DOSE", pid, m.group(0), "dose figure %r in %r" % (m.group(0), t[:80]), n, room)
        for pe in r["pendings"]:
            if pe["age_days"] is not None and pe["age_days"] > PENDING_STALE_DAYS:
                F.add("WARN", "W_PENDING_STALE", pid, norm(pe["item"]), "%s outstanding %d days"
                      % (pe["item"], pe["age_days"]), n, room)
        for m in r["micro"]:
            if m["status"] in ("prelim", "pending") and m["date"]:
                age = (ref - dt.date.fromisoformat(m["date"])).days
                if age > PRELIM_STALE_DAYS:
                    F.add("WARN", "W_PRELIM_STALE", pid, " ".join(micro_key(m)), "%s still %s after %d days"
                          % (m["specimen"], m["status"], age), n, room)
            if m["verify"]:
                F.add("WARN", "W_MICRO_TO_VERIFY", pid, " ".join(micro_key(m)), "reading marked (?) in the source: "
                      + m["text"], n, room)

        # AS list veto (J4): a restricted drug on today's list runs today
        for d in cp.get("as_standing") or []:
            if not any(c["running"] and norm(c["drug"]) == norm(d) for c in r["courses"]):
                F.add("ERROR", "E_AS_DRUG_NOT_RUNNING", pid, d, "%s is on today's AS list but has no running line" % d,
                      n, room)

        # survival from yesterday
        if p:
            today_drugs = {norm(c["drug"]): c for c in r["courses"]}
            for c in p["courses"]:
                if c["running"] and norm(c["drug"]) not in today_drugs:
                    F.add("ERROR", "E_DRUG_DROPPED", pid, c["drug"], "%s was running yesterday and has no line today "
                          "(close its segment instead of deleting it)" % c["drug"], n, room)
                t = today_drugs.get(norm(c["drug"]))
                if t and c["start"] and t["start"] and c["start"] != t["start"] and not c["start_approx"]:
                    F.add("WARN", "W_START_CHANGED", pid, c["drug"], "%s start %s yesterday, %s today"
                          % (c["drug"], c["start"], t["start"]), n, room)
            today_micro = {micro_key(m) for m in r["micro"]}
            for m in p["micro"]:
                if micro_key(m) not in today_micro:
                    F.add("ERROR", "E_MICRO_DROPPED", pid, " ".join(micro_key(m)), "culture line dropped: %r"
                          % m["text"], n, room)
            today_items = {norm(x["item"]) for x in r["pendings"]}
            words = norm(" ".join(text_blob(r)))
            for pe in p["pendings"]:
                k = norm(pe["item"])
                if k in today_items:
                    continue
                spec = k.split(" ")[0] if k else ""
                resolved = any(spec and spec in norm(m["specimen"] + " " + m["result"]) for m in r["micro"])
                if not resolved and k not in words:
                    F.add("ERROR", "E_PENDING_DROPPED", pid, k, "pending %r left the list with no result in micro and "
                          "no closure stated" % pe["text"], n, room)
        ch = computed_changes(p, r)
        changes[pid] = ch
        upd = " ".join(r["updates"]).lower()
        if ch and p and ("no change since" in upd) and any(x["kind"] != "pending_closed" for x in ch):
            F.add("ERROR", "E_UPDATE_MISSED", pid, "", "updates say no change, but: " + "; ".join(x["text"] for x in ch),
                  n, room)

    # Daily_Cultures: every final result for a census patient is carried
    if cultures:
        by_mrn = {str(cp.get("mrn") or ""): pid for pid, cp in cpat.items() if cp.get("mrn")}
        for row in cultures.get("specimens") or []:
            pid = by_mrn.get(str(row.get("mrn") or ""))
            if not pid or row.get("status") in ("PRELIM",) or not row.get("final"):
                continue
            r = cur_recs.get(pid)
            coll = row.get("collected") or ""
            spec = norm(row.get("specimen_short") or row.get("specimen") or "")
            hit = any(m["date"] == coll and (not spec or spec.split(" ")[0] in norm(m["specimen"] + " " + m["result"]))
                      for m in (r or {}).get("micro", []))
            if not hit:
                F.add("ERROR", "E_CULTURE_MISSING", pid, row.get("sid", ""), "final %s %s (SID %s, %s) from %s is not "
                      "in micro" % (row.get("specimen", ""), coll, row.get("sid", ""), row.get("status", ""),
                                    row.get("source", "Daily_Cultures")), (r or {}).get("name", ""),
                      (r or {}).get("room", ""))

    # AS list sanity: census and list agree on who is on restricted therapy
    if as_today:
        listed = {str(p.get("mrn")) for p in as_today.get("patients") or [] if p.get("mrn")}
        for pid, cp in cpat.items():
            if cp.get("as_standing") and str(cp.get("mrn")) not in listed:
                F.add("WARN", "W_AS_MISMATCH", pid, "", "census carries AS drugs but the MRN is not on today's list",
                      cp.get("name", ""), cp.get("room", ""))

    # acknowledgements
    fired = {x["id"] for x in F.items}
    for x in F.items:
        if x["id"] in verified:
            reason = str(verified[x["id"]] or "").strip()
            if reason:
                x["acknowledged"] = reason
            else:
                x["ack_error"] = "VERIFIED entry has no reason"
    for k in verified:
        if k not in fired:
            F.add("INFO", "I_STALE_ACK", "", k, "VERIFIED entry %r no longer fires; delete it" % k)

    blocking = [x for x in F.items if x["severity"] == "ERROR" and not x.get("acknowledged")]
    counts = {s: sum(1 for x in F.items if x["severity"] == s) for s in ("ERROR", "WARN", "INFO")}
    counts["acknowledged"] = sum(1 for x in F.items if x.get("acknowledged"))
    counts["blocking"] = len(blocking)
    res = {"date": a.date, "counts": counts, "findings": F.items, "changes": changes,
           "inputs": {"prev": bool(prev_state), "as_today": bool(as_today), "cultures": bool(cultures),
                      "verified": len(verified)}}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "verification.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    lines = ["Verification %s: %d errors (%d blocking, %d acknowledged), %d warnings, %d info"
             % (a.date, counts["ERROR"], counts["blocking"], counts["acknowledged"], counts["WARN"], counts["INFO"])]
    for x in sorted(F.items, key=lambda x: (order[x["severity"]], x["room"] or "", x["id"])):
        tail = "  [ack: %s]" % x["acknowledged"] if x.get("acknowledged") else ""
        lines.append("%-5s %s  %s %s: %s%s" % (x["severity"], x["id"], x["room"], x["name"], x["message"], tail))
    with open(os.path.join(a.out, "verification.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(lines[0])
    for x in blocking:
        print("BLOCK %s: %s" % (x["id"], x["message"]))
    print("VERIFY FAILED" if blocking else "VERIFY OK")
    return 1 if blocking else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prev"); ap.add_argument("state"); ap.add_argument("census"); ap.add_argument("as_today")
    ap.add_argument("cultures"); ap.add_argument("out"); ap.add_argument("--date", required=True)
    ap.add_argument("--synth", default="")
    sys.exit(run(ap.parse_args()))


if __name__ == "__main__":
    main()
