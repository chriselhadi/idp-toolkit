#!/usr/bin/env python3
"""Verify the handout email that arrived in Gmail against the local out/handout.html.

Usage: verify_handout.py <outdir> <message_id> [<file>]
<file> defaults to handout.html; pass handout_part1.html / handout_part2.html when the
manifest lists two parts (one call per sent email).
Finds the get_message RAW result for <message_id> (spilled tool-result file or the
transcript), decodes the MIME, takes the text/html part and compares its VISIBLE TEXT
(tags stripped, whitespace collapsed) with the visible text of out/handout.html.

Text, not bytes, because Gmail rewrites the markup in transit: it deletes "background:"
declarations and can reflow attributes. The clinical content is what must be exact.
Prints "handout MATCH (<n> chars of text)" or "handout MISMATCH" with the first
difference and its context, exit 1.
"""
import sys, os, re, base64, email, difflib
from email import policy
from html import unescape
sys.path.insert(0, os.path.dirname(__file__))
from verify_part import find_raw


def visible(html_text):
    t = re.sub(r"<[^>]+>", " ", html_text)
    t = unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def main():
    out, mid = sys.argv[1], sys.argv[2]
    fn = sys.argv[3] if len(sys.argv) > 3 else "handout.html"
    local = open(os.path.join(out, fn), encoding="utf-8").read()
    raw = find_raw(mid)
    if not raw:
        print("handout UNVERIFIED: no RAW result found for %s" % mid); sys.exit(1)
    msg = email.message_from_bytes(
        base64.urlsafe_b64decode(raw["raw"] + "=" * (-len(raw["raw"]) % 4)), policy=policy.default)
    to = (msg.get("To") or "") + (msg.get("Cc") or "") + (msg.get("Bcc") or "")
    addrs = re.findall(r"[\w.+-]+@[\w.-]+", to)
    if set(addrs) != {"chriselhadi@gmail.com"}:
        print("handout MISMATCH: recipients %r" % addrs); sys.exit(1)
    got = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            got = part.get_content(); break
    if got is None:
        print("handout MISMATCH: no text/html part"); sys.exit(1)
    a, b = visible(local), visible(got)
    if a == b:
        print("handout MATCH (%s, %d chars of text)" % (fn, len(a))); return 0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            print("handout MISMATCH at text offset %d: local %r vs sent %r"
                  % (i1, a[max(0, i1 - 40):i2 + 40], b[max(0, j1 - 40):j2 + 40]))
            break
    sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
