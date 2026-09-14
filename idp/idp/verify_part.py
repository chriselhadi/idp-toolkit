#!/usr/bin/env python3
"""Verify that the DOCX part that arrived in Gmail is byte-identical to the local part.

Usage: verify_part.py <outdir> <N> <message_id>
Finds the get_message RAW result for <message_id> (spilled tool-result file or inline transcript result),
decodes the MIME, locates the attachment named in manifest.json and compares sha256. Prints partN MATCH / partN MISMATCH.
"""
import sys, os, re, glob, json, base64, hashlib, email
from email import policy
sys.path.insert(0, os.path.dirname(__file__))
from recover import transcript_paths, iter_results


def find_raw(message_id):
    cands = []
    for d in {os.path.dirname(p) for p in transcript_paths()}:
        cands += glob.glob(os.path.join(d, "*", "tool-results", "*get_message*"))
    for p in sorted(cands, key=os.path.getmtime, reverse=True):
        try:
            txt = open(p, encoding="utf-8").read()
        except Exception:
            continue
        if '"%s"' % message_id in txt and '"raw"' in txt:
            return json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    for p in transcript_paths():
        for b in iter_results(p):
            if '"raw"' in b and ('"id":"%s"' % message_id in b or '"id": "%s"' % message_id in b):
                return json.loads(b[b.find("{"):b.rfind("}") + 1])
    return None


def main():
    out, n, mid = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    man = json.load(open(os.path.join(out, "parts", "manifest.json")))
    part = next(p for p in man["parts"] if p["n"] == n)
    obj = find_raw(mid)
    if not obj:
        print("part%d MISMATCH (no RAW result found for %s: fetch it with get_message RAW first)" % (n, mid)); return 1
    raw = obj["raw"]; b = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    msg = email.message_from_bytes(b, policy=policy.default)
    tos = (msg.get("to") or "") + (msg.get("cc") or "") + (msg.get("bcc") or "")
    addrs = set(a.lower() for a in re.findall(r"[\w.+-]+@[\w.-]+", tos))
    if addrs != {"chriselhadi@gmail.com"}:
        print("part%d MISMATCH (recipients %s)" % (n, sorted(addrs))); return 1
    found = None
    for p in msg.walk():
        fn = p.get_filename() or ""
        if fn == part["filename"] or (fn.endswith(".docx") and found is None):
            data = p.get_payload(decode=True)
            if fn == part["filename"]: found = data; break
            found = data
    if found is None:
        print("part%d MISMATCH (attachment %s not in message)" % (n, part["filename"])); return 1
    h = hashlib.sha256(found).hexdigest()
    if h == part["sha256"] and len(found) == part["bytes"]:
        print("part%d MATCH (%d bytes, %s)" % (n, len(found), part["filename"])); return 0
    print("part%d MISMATCH (got %d bytes sha %s, expected %d bytes sha %s)" % (n, len(found), h[:12], part["bytes"], part["sha256"][:12])); return 1


if __name__ == "__main__":
    sys.exit(main())
