#!/usr/bin/env python3
"""Daily reconciliation (Chris, 27.11.2026): one list of every discrepancy between the tasks that share IDP data
(culture digest, AMS app, daily run, Gemini, history audit), each either settled by the run or marked for Chris.

Usage:
  recon.py --date YYYY-MM-DD --out out/recon.txt
           [--svc in/service_list.json --roster-yday in/roster_yday.txt]
           [--recaps in/recaps_yday.txt]          lines "<ISO send time>|<subject>" of yesterday's recap emails
           [--state out/state_new.json --census out/census.json]
           [--coverage out/feed/coverage.txt] [--vqueue out/vqueue.txt]
           [--queue in/reg_queue.json] [--glog in/reg_glog.json]
           [--digest in/digest.txt --cultures in/cultures.txt]   digest plain text: first line "Culture Digest dd/mm/yyyy"
           [--missing out/missing_cultures.txt] [--fixed out/fixed.txt]
           [--reg-sheet in/reg_Register.json --feed-dir in/feed_now]   register (read this morning) vs the feed Gemini had (read before the run wrote it)
           [--evolution out/evolution.json]      idp10 evolve: counts of NEW / AMENDED / RETRACTED, unexplained (CHECKED)
           [--review in/feed_now/review.json]    Gemini Review tab: Escalated rows and rejected points (NEEDS YOU)

Every input is optional: a missing one is reported as "not checked". Writes the text body to --out and a JSON
summary next to it. Exit 0 always; prints RECON OK with counts.
"""
import argparse, datetime as dt, json, os, re


def load(p):
    if not p or not os.path.exists(p):
        return None
    t = open(p, encoding="utf-8", errors="ignore").read()
    if p.endswith(".json"):
        try:
            return json.loads(t[t.find("{") if t.lstrip()[:1] != "[" else t.find("["):])
        except Exception:
            return None
    return t


def toks(name):
    return {t for t in re.sub(r"[^a-z ]+", " ", (name or "").lower()).split() if len(t) >= 3}


def same_person(a, b):
    ta, tb = toks(a), toks(b)
    return bool(ta and tb) and len(ta & tb) >= min(2, len(ta), len(tb))


def sheet_rows(o):
    if isinstance(o, dict):
        return o.get("values") or []
    return o or []


def roster_names(text):
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip().strip("*")
        if not ln or ln.endswith(":"):
            continue
        ln = re.sub(r"\*", "", ln)
        parts = ln.split()
        if len(parts) < 2:
            continue
        name = re.sub(r"\((new|UC[^)]*)\)", "", " ".join(parts[1:]))
        name = re.sub(r"\s+[A-Z?]{1,3}$", "", name.strip())
        out.append(name.strip())
    return out


def main():
    ap = argparse.ArgumentParser()
    for k in ("date", "out", "svc", "roster_yday", "recaps", "state", "census", "coverage", "vqueue", "queue", "glog",
              "digest", "cultures", "missing", "fixed", "reg_sheet", "feed_dir", "evolution", "review"):
        ap.add_argument("--" + k.replace("_", "-"), dest=k, required=k in ("date", "out"))
    a = ap.parse_args()
    today = a.date
    yday = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
    need, ok, fixed, notchk = [], [], [], []

    # 1. AMS app took yesterday's list and yesterday's recap
    svc, ry = load(a.svc), load(a.roster_yday)
    if svc is None or ry is None:
        notchk.append("AMS app import (service list or yesterday's roster missing)")
    else:
        held = [q.get("name", "") for q in (svc.get("patients") or [])] + [q.get("name", "") for q in (svc.get("removed") or [])]
        miss = [n for n in roster_names(ry) if not any(same_person(n, h) for h in held)]
        if miss:
            need.append("AMS app: %d patient(s) of yesterday's ID list missing from the app's list with no removal record: %s"
                        % (len(miss), ", ".join(miss)))
        else:
            ok.append("AMS app holds every patient of yesterday's ID list (%d on its list, %d removed)"
                      % (len(svc.get("patients") or []), len(svc.get("removed") or [])))
        rec = load(a.recaps)
        if rec:
            corr = [l.split("|", 1) for l in rec.splitlines() if "|" in l and "corrected" in l.lower()]
            last = max([q.get("updated_at") or "" for q in (svc.get("patients") or [])] + [svc.get("last_edit_at") or ""])
            for t, subj in corr:
                if last and last < t:
                    need.append("AMS app: no change in the app after the corrected recap (%s, sent %s); it may still show the first version"
                                % (subj.strip(), t[11:16] + "Z"))

    # 2. Gemini applied yesterday's feed
    cov = load(a.coverage)
    if cov:
        m = re.search(r"register: (\d+) admissions, (\d+) without a block", cov)
        if m and int(m.group(2)):
            need.append("Gemini: " + cov.strip().splitlines()[-1])
        elif m:
            ok.append("Gemini: every feed admission has a register block (%s admissions)" % m.group(1))
    else:
        notchk.append("Gemini register coverage")

    # 3. Gemini queue and log
    q = sheet_rows(load(a.queue))
    if q:
        hdr = [h.strip().lower() for h in q[0]]
        ix = {h: i for i, h in enumerate(hdr)}
        st = ix.get("status", 7)
        cnt = {}
        held_rows = []
        for r in q[1:]:
            s = (r[st] if len(r) > st else "").strip().lower()
            if s and s not in ("open", "done", "confirmed", "reviewed", "held", "conflict", "skipped"):
                s = "other"
            if s:
                cnt[s] = cnt.get(s, 0) + 1
            if s in ("held", "conflict"):
                held_rows.append((r[0] if r else "").lstrip("'"))
        if held_rows:
            need.append("Gemini queue: %d order(s) held or in conflict: %s" % (len(held_rows), ", ".join(held_rows[:12])
                                                                          + (" ..." if len(held_rows) > 12 else "")))
        ok.append("Gemini queue: " + ", ".join("%s %d" % (k, v) for k, v in sorted(cnt.items())))
    else:
        notchk.append("Gemini queue")
    lg = sheet_rows(load(a.glog))
    if lg:
        dd = dt.date.fromisoformat(yday).strftime("%d/%m/%Y")
        td = dt.date.fromisoformat(today).strftime("%d/%m/%Y")
        recent = [r for r in lg[1:] if r and r[0].lstrip("'") in (dd, td)]
        for r in recent:
            tab = r[2] if len(r) > 2 else ""
            orders = r[1] if len(r) > 1 else ""
            if re.search(r"(^|,\s*)History(\s*,|$)", tab):
                need.append("Gemini edited the old History backup tab (log %s, orders %s); it is read only" % (r[0].lstrip("'"), orders))
            elif "History" in tab and not re.search(r"\b13\.", orders):
                need.append("Gemini edited frozen History outside the full-audit orders (log %s, orders %s, tab %s)"
                            % (r[0].lstrip("'"), orders, tab))
        ok.append("Gemini log: %d entr(ies) since yesterday checked" % len(recent))
    else:
        notchk.append("Gemini log")

    # 4. Verification items for Chris
    vq = load(a.vqueue)
    if vq:
        part = vq.split("== For Chris", 1)[1] if "== For Chris" in vq else ""
        rows = [l for l in part.splitlines()[1:] if l.startswith("row ")]
        for l in rows:
            m = re.match(r"row (\d+) (\S+) (\S+) (.*)", l)
            need.append("Verification %s (row %s): %s" % (m.group(2), m.group(1), m.group(4)[:160]) if m else l[:180])
        if not rows:
            ok.append("Verification: nothing waiting for Chris")

    # 5. Culture digest vs Daily Cultures file
    dg, cx = load(a.digest), load(a.cultures)
    if dg and cx:
        m = re.search(r"Culture Digest (\d\d)/(\d\d)/(\d{4})", dg)
        benches = sorted(set(re.findall(r"(?<!\d)(\d{4,5})(?!\d)", dg.split("Daily Report", 1)[-1])))
        sec = ""
        if m:
            title = "Cultures %s-%s-%s" % (m.group(3), m.group(2), m.group(1))
            s0 = cx.find("### " + title)
            sec = cx[s0:cx.find("\n### ", s0 + 5)] if s0 >= 0 else ""
            if not sec:
                need.append("Culture digest %s/%s has no matching Daily Cultures file (%s)" % (m.group(1), m.group(2), title))
        if sec:
            years = {str(y) for y in range(2020, 2031)}
            lost = [b for b in benches if b not in sec and b not in years]
            if lost:
                need.append("Culture digest %s/%s: %d bench number(s) not in the Daily Cultures file: %s"
                            % (m.group(1), m.group(2), len(lost), ", ".join(lost[:15])))
            else:
                ok.append("Culture digest %s/%s matches its Daily Cultures file (%d bench numbers)" % (m.group(1), m.group(2), len(benches)))
    else:
        notchk.append("culture digest vs Daily Cultures")

    # 6. Clinical discrepancies held in today's records (ID list patients)
    stt, cen = load(a.state), load(a.census)
    if stt and cen:
        for p in cen.get("patients") or []:
            sy = (stt.get("patients", {}).get(p["pid"]) or {}).get("synth") or {}
            nm = " ".join(w.capitalize() if w.isupper() else w for w in (p.get("name", "") or "").split())
            for c in sy.get("conflicts") or []:
                need.append("%s: conflict: %s" % (nm, c))
            for d, why in (sy.get("not_applied") or {}).items():
                need.append("%s: plan not applied: %s, %s" % (nm, d, why))
    mc = load(a.missing)
    for l in (mc or "").splitlines():
        if l.strip():
            need.append("Possible missing culture: " + l.strip().lstrip("- "))
    for l in (load(a.fixed) or "").splitlines():
        if l.strip():
            fixed.append(l.strip().lstrip("- "))


    # 7. Register blocks hold every course and culture the feed holds (catches rows written over, 27.11.2026)
    rs = sheet_rows(load(a.reg_sheet))
    fd = None
    if a.feed_dir and os.path.isdir(a.feed_dir):
        un = lambda rows: [[(c[1:] if isinstance(c, str) and c.startswith("'") else c) for c in r] for r in rows[1:]]
        fd = {"Feed Patients": un(sheet_rows(load(os.path.join(a.feed_dir, "patients.json")))),
              "Feed Antimicrobials": un(sheet_rows(load(os.path.join(a.feed_dir, "antimicrobials.json")))),
              "Feed Cultures": un(sheet_rows(load(os.path.join(a.feed_dir, "labcx.json"))))}
    if rs and fd and fd["Feed Patients"]:
        ALIAS = {"piptazo": "pip", "zavi": "avibac|zavi", "bactrim": "trimeth|bactrim|tmp|smx", "tavanic": "levo|tavanic",
                 "flagyl": "metro|flagyl", "augmentin": "clav|augment", "amphob": "ampho", "ecalta": "anidul|ecalta",
                 "ceftriax": "ceftriax|rocephin", "cefe": "cefep", "zerb": "tolozan|zerb", "tige": "tige", "valganci": "valgan",
                 "colistin": "colis", "hydrocort": "hydrocort"}
        blocks, cur = {}, None
        for r in rs[1:]:
            k = (r[0] if r else "").strip()
            if k:
                m = re.search(r"\|\s*(P\d{4})\s*\|", k)
                cur = m.group(1) if m else None
                if cur:
                    blocks.setdefault(cur, [])
            if cur and len(r) > 2 and r[2].strip() == "---":
                cur = None; continue
            if cur:
                blocks[cur].append(r)
        active = {r[0] for r in fd.get("Feed Patients", []) if len(r) > 3 and r[3] == "Active"}
        gaps = []
        for r in fd.get("Feed Antimicrobials", []):
            if len(r) < 2:
                continue
            pid, drug = r[0], (r[1] or "").split(" #")[0]
            if pid not in active or pid not in blocks or not drug:
                continue
            txt = " ".join((x[22] if len(x) > 22 else "") + " " + (x[18] if len(x) > 18 else "") for x in blocks[pid]).lower()
            pat = ALIAS.get(drug.lower(), re.escape(drug.lower()[:4]))
            if not re.search(pat, txt):
                gaps.append("%s %s" % (pid, drug))
        for r in fd.get("Feed Cultures", []):
            if len(r) < 3:
                continue
            pid, col = r[0], (r[1] or "")
            if pid not in active or pid not in blocks or not col or not (len(r) > 9 and r[9].startswith("Final")):
                continue
            txt = " ".join(x[30] if len(x) > 30 else "" for x in blocks[pid])
            if col[:5] not in txt:
                gaps.append("%s culture %s %s" % (pid, col, r[2] if len(r) > 2 else ""))
        if gaps:
            need.append("Register blocks missing %d item(s) the feed holds (course or final culture written over or never added): %s"
                        % (len(gaps), "; ".join(gaps[:20]) + (" ..." if len(gaps) > 20 else "")))
        else:
            ok.append("Register blocks of today's list hold every course and final culture in the feed")
    else:
        notchk.append("Register blocks vs feed")
    # 8. Notes evolve, never rewritten (28.11.2026): what changed against yesterday's synthesis, and Gemini's review
    ev = load(a.evolution)
    if isinstance(ev, dict) and "counts" in ev:
        c = ev.get("counts") or {}
        ok.append("Evolution: %d change(s) to yesterday's synthesis explained (NEW %d, AMENDED %d, RETRACTED %d), %d unexplained"
                  % (ev.get("explained", 0), c.get("NEW", 0), c.get("AMENDED", 0), c.get("RETRACTED", 0), ev.get("unexplained", 0)))
    else:
        notchk.append("Evolution (no evolution.json)")
    rv = sheet_rows(load(a.review))
    if rv:
        hdr = [x.strip() for x in rv[0][:2]] == ["Date", "pid"]
        npts = nesc = nrej = 0
        for n, r in enumerate(rv[1:] if hdr else rv, 2 if hdr else 1):
            r = [("" if x is None else str(x)).lstrip("'") for x in r] + [""] * 11
            if not (r[5].strip() or r[4].strip()):
                continue
            npts += 1
            esc, rej = r[10].strip().upper() == "Y", r[7].strip().lower() == "rejected"
            if esc or rej:
                nesc += esc; nrej += rej
                need.append("Gemini review row %d (%s %s, %s, %s): %s%s%s" % (
                    n, r[1], r[2], r[3], r[4], r[5][:160], " ; Claude %s: %s" % (r[7], r[8][:160]) if r[7] else " ; no reply yet",
                    " [escalated]" if esc else ""))
        ok.append("Gemini review: %d point(s), %d escalated, %d rejected" % (npts, nesc, nrej))
    else:
        notchk.append("Gemini review")
    d = dt.date.fromisoformat(today).strftime("%d.%m.%Y")
    lines = ["ID Reconciliation %s" % d, "", "NEEDS YOU (%d)" % len(need)]
    lines += ["%d. %s" % (i + 1, x) for i, x in enumerate(need)] or ["none"]
    lines += ["", "SETTLED BY THE RUN (%d)" % len(fixed)] + (["- " + x for x in fixed] or ["none"])
    lines += ["", "CHECKED, IN AGREEMENT"] + (["- " + x for x in ok] or ["none"])
    if notchk:
        lines += ["", "NOT CHECKED TODAY"] + ["- " + x for x in notchk]
    body = "\n".join(lines).replace("—", ",").replace("–", ",") + "\n"
    open(a.out, "w", encoding="utf-8").write(body)
    json.dump({"need": need, "fixed": fixed, "ok": ok, "not_checked": notchk},
              open(os.path.splitext(a.out)[0] + ".json", "w"), ensure_ascii=False, indent=1)
    print("RECON OK: %d need Chris, %d settled, %d checks in agreement, %d not checked" % (len(need), len(fixed), len(ok), len(notchk)))


if __name__ == "__main__":
    main()
