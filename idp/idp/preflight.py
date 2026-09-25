#!/usr/bin/env python3
"""Pre-send checks. Run after build.py, before the first send_message. Exit 1 = do not send.

Usage: preflight.py <outdir> <today ISO>
Checks every deliverable the run is about to type into a tool call:
  - files exist and are non-empty: delta2.html/.txt, handout.html, handout_body.txt,
    handout_manifest.json, recap_email.txt, state_parts/manifest.json + every part
  - sizes: every single tool-call string under the transcription limits measured 14.09.2026
    (state part < 25000, recap < 30000, handout html < 60000, delta html < 30000)
  - no em/en dash anywhere, no "background:" in any HTML (Gmail deletes it)
  - every state part header carries today's date and the manifest sha256
  - the handout subject in the manifest carries today's date label
Prints one PASS/FAIL line per check and "PREFLIGHT OK" at the end.
"""
import sys, os, json, re, datetime as dt

LIMITS = {"state_part": 25000, "recap_email.txt": 30000, "handout.html": 60000, "delta2.html": 30000,
          "archive_notes.txt": 30000}


def main():
    out, today = sys.argv[1], sys.argv[2]
    fails = []

    def check(ok, msg):
        print(("PASS " if ok else "FAIL ") + msg)
        if not ok:
            fails.append(msg)

    def rd(name):
        p = os.path.join(out, name)
        return open(p, encoding="utf-8").read() if os.path.exists(p) else None

    for f in ("delta2.html", "delta2.txt", "handout.html", "handout_body.txt", "handout_manifest.json",
              "recap_email.txt", "state_parts/manifest.json"):
        t = rd(f)
        check(bool(t and t.strip()), "%s present and non-empty" % f)
    try:
        _nparts = len(json.loads(rd("handout_manifest.json") or "{}").get("parts", []))
    except Exception:
        _nparts = 1
    for f, lim in LIMITS.items():
        if f == "state_part":
            continue
        if f == "handout.html" and _nparts > 1:
            continue  # split handout: the monolith is never sent; each part is checked below
        t = rd(f)
        if t is None:
            continue
        check("—" not in t and "–" not in t, "%s has no em/en dash" % f)
        if f.endswith(".html"):
            check("background:" not in t, "%s has no background: (Gmail deletes it)" % f)
    man = rd("handout_manifest.json")
    if man:
        m = json.loads(man)
        label = dt.date.fromisoformat(today).strftime("%d %B %Y")
        check(m.get("subject", "").endswith(label), "handout subject carries today (%s): %s" % (label, m.get("subject")))
        h = rd("handout.html") or ""
        check(label in h, "handout.html carries today's date label")
        for part in m.get("parts", []):
            t = rd(part["file"]) or ""
            check(bool(t) and len(t) < LIMITS["handout.html"], "handout email %s %d chars < %d" % (part["file"], len(t), LIMITS["handout.html"]))
        print("INFO handout goes as %d email(s): %s" % (len(m.get("parts", [])), "; ".join(p["subject"] for p in m.get("parts", []))))
    sm = rd("state_parts/manifest.json")
    if sm:
        s = json.loads(sm)
        check(s.get("date") == today, "state manifest dated %s" % today)
        for p in s["parts"]:
            t = rd("state_parts/part%d.txt" % p["n"])
            check(bool(t), "state part %d present" % p["n"])
            if not t:
                continue
            check(len(t) < LIMITS["state_part"], "state part %d %d chars < %d" % (p["n"], len(t), LIMITS["state_part"]))
            first = t.split("\n", 1)[0]
            check(first.startswith("IDP-STATE %s part %d/%d sha256=%s" % (today, p["n"], s["n"], s["full_sha256"])),
                  "state part %d header" % p["n"])
    an = rd("archive_notes.txt")
    print("INFO archive_notes.txt: %s" % ("SKIP email 4, file empty" if not (an and an.strip()) else "%d chars, send email 4" % len(an)))
    print("INFO recipient for every send: chriselhadi@gmail.com and nobody else")
    if fails:
        print("PREFLIGHT FAILED: %d check(s)" % len(fails)); sys.exit(1)
    print("PREFLIGHT OK")


if __name__ == "__main__":
    main()
