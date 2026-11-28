#!/usr/bin/env python3
"""Pre-send checks. Run after build.py, before the first send_message. Exit 1 = do not send.

Usage: preflight.py <outdir> <today ISO>
Checks every deliverable the run is about to type into a tool call:
  - files exist and are non-empty: delta2.html/.txt, recap_email.txt, state_parts/manifest.json + every part
    (no HTML handout since 28.11.2026: never emailed, nothing read it)
  - sizes: every single tool-call string under the transcription limits measured 14.09.2026
    (state part < 25000, recap < 30000, delta html < 30000)
  - no em/en dash anywhere, no "background:" in any HTML (Gmail deletes it)
  - every state part header carries today's date and the manifest sha256
Prints one PASS/FAIL line per check and "PREFLIGHT OK" at the end.
"""
import sys, os, json, re, datetime as dt

LIMITS = {"state_part": 25000, "recap_email.txt": 30000, "delta2.html": 30000,
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

    for f in ("delta2.html", "delta2.txt", "recap_email.txt", "state_parts/manifest.json"):
        t = rd(f)
        check(bool(t and t.strip()), "%s present and non-empty" % f)
    for f, lim in LIMITS.items():
        if f == "state_part":
            continue
        t = rd(f)
        if t is None:
            continue
        check("—" not in t and "–" not in t, "%s has no em/en dash" % f)
        if f.endswith(".html"):
            check("background:" not in t, "%s has no background: (Gmail deletes it)" % f)
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
    print("INFO archive_notes.txt: %s" % ("empty, nothing to upload" if not (an and an.strip()) else
          "%d chars: archive_split.py, then upload to ID_Archive_Notes; do NOT email (P2)" % len(an)))  # OVERLAY_6 4u
    print("INFO recipients for delta, handout, recap (no archive email, P2): chriselhadi@gmail.com only (Chris, 02.11.2026); state goes to Drive only")
    if fails:
        print("PREFLIGHT FAILED: %d check(s)" % len(fails)); sys.exit(1)
    print("PREFLIGHT OK")


if __name__ == "__main__":
    main()
