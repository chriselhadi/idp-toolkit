#!/usr/bin/env python3
"""Verify the single handout attachment that arrived in Gmail against the local DOCX.

Usage: verify_handout.py <outdir> <message_id>
Reads out/handout_manifest.json for the expected filename and sha256, finds the
get_message RAW result for <message_id> (spilled tool-result file or transcript),
decodes the MIME and compares. Prints handout MATCH / handout MISMATCH.
"""
import sys, os, json, base64, hashlib, email
from email import policy
sys.path.insert(0, os.path.dirname(__file__))
from verify_part import find_raw


def main():
    out, mid = sys.argv[1], sys.argv[2]
    man = json.load(open(os.path.join(out, "handout_manifest.json")))
    raw = find_raw(mid)
    if not raw:
        print("handout UNVERIFIED: no RAW result found for %s" % mid); sys.exit(1)
    msg = email.message_from_bytes(
        base64.urlsafe_b64decode(raw["raw"] + "=" * (-len(raw["raw"]) % 4)), policy=policy.default)
    got = None
    for part in msg.walk():
        fn = part.get_filename()
        if fn and fn.strip() == man["file"]:
            got = part.get_payload(decode=True)
            break
    if got is None:
        print("handout MISMATCH: attachment %r not present" % man["file"]); sys.exit(1)
    h = hashlib.sha256(got).hexdigest()
    if h == man["sha256"] and len(got) == man["bytes"]:
        print("handout MATCH (%d bytes, sha256 %s)" % (len(got), h[:16])); return
    print("handout MISMATCH: got %d bytes sha256 %s, expected %d bytes sha256 %s"
          % (len(got), h[:16], man["bytes"], man["sha256"][:16]))
    sys.exit(1)


if __name__ == "__main__":
    main()
