#!/usr/bin/env python3
"""Verify a Gmail draft, or a sent message, byte for byte against the local artefact.

Why this exists (10.09.2026): a deliverable has to be hand-typed into the Gmail tool
call as one long string, and long strings acquire about one wrong character per 8-10K.
Splitting the deliverable to stay under that was the wrong fix: it shrank the payload
but multiplied the emails, and nothing was ever near Gmail's 25MB ceiling. The right
fix is to build the message as a DRAFT, compare the bytes Gmail actually stored against
the local file, repair the draft if they differ, and only then send. The repair loop
happens in Drafts, so one deliverable is one email however many attempts it takes.

Usage:
  draft_relay.py draft <draftId>   <local_path> attach <filename>
  draft_relay.py draft <draftId>   <local_path> body
  draft_relay.py msg   <messageId> <local_path> attach <filename>
  draft_relay.py msg   <messageId> <local_path> body

Fetch the RAW first (get_draft / get_message with messageFormat RAW), then run this.
Prints MATCH, or MISMATCH with the first differing offset and the context either side:
that offset is the whole repair, one character in one place.
"""
import sys, os, re, glob, json, base64, hashlib, email
from email import policy
sys.path.insert(0, os.path.dirname(__file__))
from recover import transcript_paths, iter_results

ONLY_RECIPIENT = "chriselhadi@gmail.com"


def find_raw(kind, ident):
    """The get_draft/get_message RAW result for exactly `ident`, or None.

    Spilled tool-result files first (large results land there), then inline results in the
    transcript. There is deliberately NO fallback to "the newest RAW result": on 10.09.2026
    that fallback matched the recap's RAW when asked about the handout's message id and
    reported a mismatch against an unrelated message. Worse, two deliverables carrying the
    same bytes would have produced a false MATCH. If the id is not found, say so and let the
    caller fetch it.
    """
    needle = "get_draft" if kind == "draft" else "get_message"
    cands = []
    for d in {os.path.dirname(p) for p in transcript_paths()}:
        cands += glob.glob(os.path.join(d, "*", "tool-results", "*%s*" % needle))
    for p in sorted(cands, key=os.path.getmtime, reverse=True):
        try:
            txt = open(p, encoding="utf-8").read()
        except Exception:
            continue
        if '"raw"' in txt and '"%s"' % ident in txt:
            return json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    for p in transcript_paths():
        for b in iter_results(p):
            if '"raw"' not in b:
                continue
            if ('"id":"%s"' % ident in b) or ('"id": "%s"' % ident in b):
                return json.loads(b[b.find("{"):b.rfind("}") + 1])
    return None


def parse(obj):
    raw = obj["raw"] if isinstance(obj, dict) and "raw" in obj else obj.get("message", {}).get("raw")
    b = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    return email.message_from_bytes(b, policy=policy.default)


def check_recipients(msg):
    tos = (msg.get("to") or "") + (msg.get("cc") or "") + (msg.get("bcc") or "")
    addrs = set(a.lower() for a in re.findall(r"[\w.+-]+@[\w.-]+", tos))
    return addrs == {ONLY_RECIPIENT}, sorted(addrs)


def first_diff(a, b):
    """(offset, context_a, context_b) for the first difference, or None."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            lo, hi = max(0, i - 20), i + 20
            return i, a[lo:hi], b[lo:hi]
    if len(a) != len(b):
        lo = max(0, n - 20)
        return n, a[lo:n + 20], b[lo:n + 20]
    return None


def show(x):
    return x.decode("utf-8", "replace") if isinstance(x, (bytes, bytearray)) else x


def main():
    kind, ident, local, mode = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    fname = sys.argv[5] if len(sys.argv) > 5 else None
    obj = find_raw(kind, ident)
    if not obj:
        print("MISMATCH (no RAW result found for %s: fetch it with get_%s messageFormat RAW first)"
              % (ident, "draft" if kind == "draft" else "message"))
        return 1
    msg = parse(obj)
    ok, addrs = check_recipients(msg)
    if not ok:
        print("MISMATCH (recipients %s, expected only %s)" % (addrs, ONLY_RECIPIENT))
        return 1

    if mode == "attach":
        want = open(local, "rb").read()
        got = None
        for p in msg.walk():
            fn = p.get_filename() or ""
            if fn == fname:
                got = p.get_payload(decode=True)
                break
            if fn.endswith(".docx") and got is None:
                got = p.get_payload(decode=True)
        if got is None:
            print("MISMATCH (attachment %s not in %s)" % (fname, kind))
            return 1
        if got == want:
            print("MATCH %s attachment %s (%d bytes, sha %s)"
                  % (kind, fname, len(got), hashlib.sha256(got).hexdigest()[:12]))
            return 0
        # The stored bytes differ, so the base64 that was typed differs. Report the
        # offset in the BASE64, because that is the string that gets retyped.
        gb, wb = base64.b64encode(got).decode(), base64.b64encode(want).decode()
        d = first_diff(gb, wb)
        print("MISMATCH %s attachment (%d bytes sha %s, expected %d bytes sha %s)"
              % (kind, len(got), hashlib.sha256(got).hexdigest()[:12],
                 len(want), hashlib.sha256(want).hexdigest()[:12]))
        if d:
            i, ga, wa = d
            print("  first bad base64 char at offset %d" % i)
            print("  sent  ...%s..." % ga)
            print("  local ...%s..." % wa)
        return 1

    want = open(local, encoding="utf-8").read().replace("\r\n", "\n").rstrip("\n")
    got = None
    for p in msg.walk():
        if p.get_content_type() == "text/plain":
            got = p.get_payload(decode=True).decode("utf-8", "replace")
            break
    if got is None:
        print("MISMATCH (no text/plain part in %s)" % kind)
        return 1
    got = got.replace("\r\n", "\n").rstrip("\n")
    if got == want:
        print("MATCH %s body (%d chars, sha %s)"
              % (kind, len(got), hashlib.sha256(got.encode()).hexdigest()[:12]))
        return 0
    print("MISMATCH %s body (%d chars sha %s, expected %d chars sha %s)"
          % (kind, len(got), hashlib.sha256(got.encode()).hexdigest()[:12],
             len(want), hashlib.sha256(want.encode()).hexdigest()[:12]))
    d = first_diff(got, want)
    if d:
        i, ga, wa = d
        print("  first difference at offset %d" % i)
        print("  sent  ...%s..." % show(ga).replace("\n", "\\n"))
        print("  local ...%s..." % show(wa).replace("\n", "\\n"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
