#!/usr/bin/env python3
"""State persistence: finalize today's state, pack it into email-sized text parts, verify what was sent, unpack tomorrow.

  state_io.py finalize <state_matched.json> <synth.py> <census.json> <as_today.json|MISSING> <today ISO> <state_new.json>
  state_io.py pack <state_new.json> <parts_dir> [maxchars=25000]      -> part1.txt .. partN.txt (+ manifest.json)
  state_io.py verify-part <parts_dir> <n> <message_id>                -> 'state part n MATCH' or MISMATCH
  state_io.py unpack <raw_dir_or_files...> <state.json>               -> rebuilds state.json from the RAW results of every part
The email body of part n is the file content verbatim; the first line is the header 'IDP-STATE <date> part n/N sha256=<full text hash>'.
"""
import sys, os, re, json, glob, base64, hashlib, email, datetime as dt
from email import policy
sys.path.insert(0, os.path.dirname(__file__))
from common import jload, jdump, iso_from_ddmm
from validate_synth import load_synth, ABX_RE, PEND_RE


def finalize(state_p, synth_p, census_p, as_p, today, out_p):
    state = jload(state_p); mod = load_synth(synth_p); census = jload(census_p)
    as_today = jload(as_p) if as_p and as_p.upper() != "MISSING" and os.path.exists(as_p) else None
    y = int(today[:4])
    for c in census["patients"]:
        pid = c["pid"]; e = mod.SYNTH[pid]; rec = state["patients"][pid]
        keep = {k: e[k] for k in e}
        keep.update({"_room": c["room"], "_group": c["group"], "_fellow": c.get("fellow", ""), "_tags": c.get("tags", []), "_date": today})
        rec["synth"] = keep
        old = {p["item"]: p for p in rec.get("pendings_state", [])}
        newp = []
        for pe in e["pendings"]:
            m = PEND_RE.match(pe)
            if not m: continue
            item = m.group("item"); since = iso_from_ddmm(m.group("date"), y) or today
            prev = old.get(item)
            newp.append({"item": item, "since": prev["since"] if prev else since, "gate": m.group("gate") or ""})
        rec["pendings_state"] = newp
        hist = {h["drug"]: h for h in rec.get("abx_history", [])}
        for blk, lines in [(i.get("dx", "")[:40], i.get("abx", [])) for i in e["issues"]] + [("abx_other", e["abx_other"])]:
            for ab in lines:
                m = ABX_RE.match(ab)
                if not m: continue
                hist[m.group("drug")] = {"drug": m.group("drug"), "line": ab, "issue": blk, "last": today}
        rec["abx_history"] = list(hist.values())
    if as_today:
        state["as_snapshot"] = {"list_date": as_today.get("list_date"), "patients": [
            {k: p.get(k) for k in ("mrn", "name", "room", "group", "drugs", "standing_drugs", "once_only")} for p in as_today["patients"]]}
    obs = state.get("observations", []) + [o for o in getattr(mod, "OBSERVATIONS", []) if isinstance(o, dict)]
    state["observations"] = obs[-20:]
    state["date"] = today; state.pop("_census_pids", None)
    jdump(state, out_p)
    print("state finalized: %d patients (%d active), %d bytes" % (len(state["patients"]), sum(1 for p in state["patients"].values() if p.get("active")), os.path.getsize(out_p)))


def pack(state_p, pdir, maxc=25000):
    os.makedirs(pdir, exist_ok=True)
    for f in glob.glob(os.path.join(pdir, "part*.txt")): os.remove(f)
    obj = jload(state_p); date = obj.get("date")
    text = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)
    full_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    lines = text.split("\n"); chunks, cur, size = [], [], 0
    for ln in lines:
        if size + len(ln) + 1 > maxc - 120 and cur:
            chunks.append(cur); cur, size = [], 0
        cur.append(ln); size += len(ln) + 1
    if cur: chunks.append(cur)
    N = len(chunks); man = []
    for i, ch in enumerate(chunks, 1):
        body = "IDP-STATE %s part %d/%d sha256=%s\n" % (date, i, N, full_sha) + "\n".join(ch) + "\n"
        p = os.path.join(pdir, "part%d.txt" % i); open(p, "w", encoding="utf-8").write(body)
        man.append({"n": i, "chars": len(body), "sha256": hashlib.sha256(norm(body).encode()).hexdigest(),
                    "subject": "IDP State %s (part %d/%d)" % (date, i, N)})
        print("state part %d/%d: %d chars, subject '%s'" % (i, N, len(body), man[-1]["subject"]))
    json.dump({"date": date, "n": N, "full_sha256": full_sha, "parts": man}, open(os.path.join(pdir, "manifest.json"), "w"), indent=1)


def norm(t):
    return "\n".join(l.rstrip() for l in t.replace("\r\n", "\n").split("\n")).strip() + "\n"


def norm_part(t):
    """Undo mail-transport damage on ONE state part without touching indentation.

    pack() splits on line boundaries, so the leading whitespace of a part's first
    line is real payload (the state is JSON at indent=1). norm() calls .strip(),
    which eats that indentation and also appends a newline per part, so joining
    norm()ed parts can never reproduce the packed text and the sha256 check fails
    every time. Only CRLF and trailing whitespace are transport artefacts.
    """
    t = t.replace("\r\n", "\n")
    t = "\n".join(l.rstrip() for l in t.split("\n"))
    return t[:-1] if t.endswith("\n") else t


def raw_to_msg(obj):
    raw = obj["raw"]; b = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    return email.message_from_bytes(b, policy=policy.default)


def plain_body(msg):
    for p in msg.walk():
        if p.get_content_type() == "text/plain":
            return p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
    return ""


def verify_part(pdir, n, mid):
    from verify_part import find_raw
    obj = find_raw(mid)
    if not obj: print("state part %d MISMATCH (no RAW result for %s)" % (n, mid)); return 1
    msg = raw_to_msg(obj)
    local = open(os.path.join(pdir, "part%d.txt" % n), encoding="utf-8").read()
    got = plain_body(msg)
    if norm(got) == norm(local): print("state part %d MATCH (%d chars)" % (n, len(got))); return 0
    a, b = norm(got).split("\n"), norm(local).split("\n")
    k = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
    print("state part %d MISMATCH at line %d: got %r expected %r" % (n, k + 1, a[k][:60] if k < len(a) else "", b[k][:60] if k < len(b) else "")); return 1


def unpack(inputs, out_p):
    files = []
    for x in inputs:
        files += glob.glob(os.path.join(x, "*")) if os.path.isdir(x) else [x]
    parts = {}
    for f in files:
        try:
            txt = open(f, encoding="utf-8").read(); obj = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
            body = plain_body(raw_to_msg(obj)) if "raw" in obj else obj.get("plaintext_body") or obj.get("body") or ""
        except Exception:
            continue
        m = re.match(r"\s*IDP-STATE (\S+) part (\d+)/(\d+) sha256=([0-9a-f]{64})", body)
        if not m: continue
        date, n, N, sha = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        parts.setdefault((date, N, sha), {})[n] = body.split("\n", 1)[1]
    if not parts: print("unpack: no IDP-STATE bodies found"); return 1
    key = max(parts, key=lambda k: k[0]); date, N, sha = key
    have = parts[key]
    if set(have) != set(range(1, N + 1)):
        print("unpack: state %s incomplete: have parts %s of %d" % (date, sorted(have), N)); return 1
    text = "\n".join(norm_part(have[i]) for i in range(1, N + 1))
    got = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if got != sha:
        # tolerate a lost trailing newline only
        if hashlib.sha256((text + "\n").encode("utf-8")).hexdigest() != sha:
            print("unpack: sha256 mismatch for state %s (got %s, expected %s)" % (date, got[:12], sha[:12])); return 1
    obj = json.loads(text); jdump(obj, out_p)
    print("unpacked state dated %s: %d patients -> %s" % (obj.get("date"), len(obj.get("patients", {})), out_p)); return 0


if __name__ == "__main__":
    cmd = sys.argv[1]; a = sys.argv[2:]
    if cmd == "finalize": finalize(*a)
    elif cmd == "pack": pack(a[0], a[1], int(a[2]) if len(a) > 2 else 25000)
    elif cmd == "verify-part": sys.exit(verify_part(a[0], int(a[1]), a[2]))
    elif cmd == "unpack": sys.exit(unpack(a[:-1], a[-1]))
    else: print(__doc__)
