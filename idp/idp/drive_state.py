#!/usr/bin/env python3
"""State parts in Google Drive (Chris, 28.09.2026): Gmail no longer carries state.

  drive_state.py unpack <file or dir of download/read results> ... <out.json>
      Each input is a tool result for one part file: {"content": <base64>} from
      download_file_content, or {"fileContent": <text>} from read_file_content.
      Rebuilds the newest complete state and checks its sha256.
  drive_state.py verify <download result> <local part file>
      Prints 'drive part MATCH' when the stored file equals the local part.
"""
import sys, os, json, glob, base64, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import state_io


def body_of(path):
    txt = open(path, encoding="utf-8").read()
    if txt.lstrip().startswith(("IDP-STATE", "IDP-PATCH")):
        return txt.lstrip()
    try:
        obj = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    except Exception:
        return txt if txt.startswith("IDP-STATE") else ""
    if obj.get("content"):
        return base64.b64decode(obj["content"] + "=" * (-len(obj["content"]) % 4)).decode("utf-8", "replace")
    return obj.get("fileContent") or obj.get("textContent") or ""


def unpack(inputs, out_p):
    files = []
    for x in inputs:
        files += sorted(glob.glob(os.path.join(x, "*"))) if os.path.isdir(x) else [x]
    tmp = tempfile.mkdtemp()
    for i, f in enumerate(files):
        b = body_of(f)
        if b.lstrip().startswith("IDP-STATE"):
            json.dump({"body": b}, open(os.path.join(tmp, "p%03d.json" % i), "w"))
    try:
        return state_io.unpack([tmp], out_p)
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)  # OVERLAY_7: no state copy left behind


def verify(res, local):
    got, exp = body_of(res), open(local, encoding="utf-8").read()
    if state_io.norm(got) == state_io.norm(exp):
        print("drive part MATCH (%d chars)" % len(got)); return 0
    print("drive part MISMATCH (%d vs %d chars)" % (len(got), len(exp))); return 1


def asbaseline(inputs, out_p):
    """Newest AS list found in any state files (overlay 4, 05.10.2026): IDP-STATE parts, complete
    set or not (parts 1..k contiguous), or the as_history addition inside any IDP-PATCH part."""
    import re
    files = []
    for x in inputs:
        files += sorted(glob.glob(os.path.join(x, "*"))) if os.path.isdir(x) else [x]
    parts, cands = {}, []
    for f in files:
        b = body_of(f)
        m = re.match(r"\s*IDP-STATE (\S+) part (\d+)/(\d+)", b)
        if m:
            parts.setdefault(m.group(1), {})[int(m.group(2))] = b.split("\n", 1)[1]
            continue
        m = re.match(r"\s*IDP-PATCH (\S+) base", b)
        if m:
            for l in b.split("\n")[1:]:
                if '"op":"shift"' in l and '"as_history"' in l:
                    try:
                        o = json.loads(l)
                    except ValueError:
                        continue
                    if o.get("path") == ["as_history"] and o.get("add"):
                        cands.append((m.group(1), "patch %s" % m.group(1), o["add"][-1]))
    keyre = re.compile(r'"as_snapshot":\s*')
    for date in sorted(parts, reverse=True):
        P = parts[date]; text = ""; k = 1
        while k in P:
            text += P[k]; k += 1
        mm = keyre.search(text)
        if not mm:
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[mm.end():])
        except ValueError:
            continue
        if obj and obj.get("patients"):
            cands.append((date, "state %s (parts 1-%d)" % (date, k - 1), obj))
            break
    if not cands:
        print("AS BASELINE NONE: no AS list in the files given")
        return 1
    date, src, obj = max(cands, key=lambda c: c[0])
    json.dump(obj, open(out_p, "w"), ensure_ascii=False)
    print("AS BASELINE OK: from %s, list %s, %d patients" % (src, obj.get("list_date"), len(obj["patients"])))
    return 0


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(obj):
    import hashlib
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


def _klist_op(path, key, a, b):
    """Keyed list (abx_history by drug, pendings_state by item): order + per-item changed fields."""
    if not all(isinstance(x, dict) and key in x for x in a + b):
        return None
    A = {x[key]: x for x in a}
    merge = {}
    for x in b:
        y = A.get(x[key])
        if y is None:
            merge[x[key]] = x
            continue
        if set(y) - set(x):
            return None  # a field disappeared: send the list whole
        d = {k: v for k, v in x.items() if y.get(k) != v}
        if d:
            merge[x[key]] = d
    if len({x[key] for x in b}) != len(b):
        return None
    bump = {}
    for k2, d in list(merge.items()):
        if k2 in A and list(d) == ["last"]:
            bump.setdefault(d["last"], []).append(k2); del merge[k2]
    return {"op": "klist", "path": path, "key": key, "order": [x[key] for x in b], "merge": merge, "bump": bump}


def _list_shift(path, a, b):
    """new = old[-keep:] + add (as_history, observations)."""
    for k in range(min(len(a), len(b)), -1, -1):
        if (k == 0 or a[-k:] == b[:k]):
            return {"op": "shift", "path": path, "keep": k, "add": b[k:]}


def make_patch(old, new):
    ops = []
    for k in sorted(set(old) | set(new)):
        if k not in new:
            ops.append({"op": "del", "path": [k]}); continue
        if k in old and old[k] == new[k]:
            continue
        if k in ("as_history", "observations") and isinstance(old.get(k), list) and isinstance(new[k], list):
            ops.append(_list_shift([k], old[k], new[k])); continue
        if k == "as_snapshot" and isinstance(new.get("as_history"), list) and new["as_history"] and new[k] == new["as_history"][-1]:
            ops.append({"op": "snap_last"}); continue
        if k == "patients" and isinstance(old.get(k), dict):
            P, Q = old[k], new[k]
            for pid in sorted(set(P) | set(Q)):
                if pid not in Q:
                    ops.append({"op": "del", "path": ["patients", pid]}); continue
                if pid not in P:
                    ops.append({"op": "set", "path": ["patients", pid], "v": Q[pid]}); continue
                a, b = P[pid], Q[pid]
                if a == b:
                    continue
                for f in sorted(set(a) | set(b)):
                    if f not in b:
                        ops.append({"op": "del", "path": ["patients", pid, f]}); continue
                    if a.get(f) == b[f] and f in a:
                        continue
                    if f == "synth" and isinstance(a.get(f), dict) and isinstance(b[f], dict):
                        for s in sorted(set(a[f]) | set(b[f])):
                            if s not in b[f]:
                                ops.append({"op": "del", "path": ["patients", pid, f, s]})
                            elif a[f].get(s) != b[f][s] or s not in a[f]:
                                ops.append({"op": "set", "path": ["patients", pid, f, s], "v": b[f][s]})
                        continue
                    if f in ("abx_history", "pendings_state") and isinstance(a.get(f), list) and isinstance(b[f], list):
                        op = _klist_op(["patients", pid, f], "drug" if f == "abx_history" else "item", a[f], b[f])
                        if op:
                            ops.append(op); continue
                    ops.append({"op": "set", "path": ["patients", pid, f], "v": b[f]})
            continue
        ops.append({"op": "set", "path": [k], "v": new[k]})
    return ops


def _getp(obj, path):
    for p in path:
        obj = obj[p]
    return obj


def apply_patch(state, ops):
    import copy
    s = copy.deepcopy(state)
    for o in ops:
        t = o["op"]
        if t == "set":
            _getp(s, o["path"][:-1])[o["path"][-1]] = o["v"]
        elif t == "del":
            _getp(s, o["path"][:-1]).pop(o["path"][-1], None)
        elif t == "shift":
            par = _getp(s, o["path"][:-1]); old = par.get(o["path"][-1]) or []
            par[o["path"][-1]] = (old[-o["keep"]:] if o["keep"] else []) + o["add"]
        elif t == "snap_last":
            s["as_snapshot"] = copy.deepcopy(s["as_history"][-1])
        elif t == "klist":
            par = _getp(s, o["path"][:-1]); old = {x[o["key"]]: x for x in (par.get(o["path"][-1]) or [])}
            out = []
            bumped = {k: v for v, ks in (o.get("bump") or {}).items() for k in ks}
            for k in o["order"]:
                x = dict(old.get(k, {})); x.update(o["merge"].get(k, {}))
                if k in bumped: x["last"] = bumped[k]
                out.append(x)
            par[o["path"][-1]] = out
        else:
            raise ValueError("unknown patch op %r" % t)
    return s


def patch_write(prev_p, new_p, pdir, maxc=25000):
    """IDP State Patch parts: today's changes against yesterday's state. Verified by applying."""
    import glob as _g
    old = json.load(open(prev_p, encoding="utf-8")); new = json.load(open(new_p, encoding="utf-8"))
    ops = make_patch(old, new)
    if apply_patch(old, ops) != new:
        print("PATCH FAILED: applying the patch does not reproduce the new state"); return 1
    os.makedirs(pdir, exist_ok=True)
    for f in _g.glob(os.path.join(pdir, "patch*.txt")): os.remove(f)
    lines = [_canon(o) for o in ops]
    chunks, cur, size = [], [], 0
    for ln in lines:
        if size + len(ln) + 1 > maxc - 160 and cur:
            chunks.append(cur); cur, size = [], 0
        cur.append(ln); size += len(ln) + 1
    if cur or not chunks: chunks.append(cur)
    N = len(chunks); sha = _sha(new); full = len(_canon(new))
    for i, ch in enumerate(chunks, 1):
        body = "IDP-PATCH %s base %s part %d/%d sha256=%s\n" % (new.get("date"), old.get("date"), i, N, sha) + "\n".join(ch) + "\n"
        open(os.path.join(pdir, "patch%d.txt" % i), "w", encoding="utf-8").write(body)
    tot = sum(len(open(os.path.join(pdir, "patch%d.txt" % i), encoding="utf-8").read()) for i in range(1, N + 1))
    print("PATCH OK: %d ops, %d part(s), %d chars (full state %d chars, %.0f%%), base %s -> %s"
          % (len(ops), N, tot, full, 100.0 * tot / max(full, 1), old.get("date"), new.get("date")))
    if tot > 0.6 * full:
        print("PATCH LARGE: over 60% of the full state; write a full IDP State set instead")
    return 0


def unpackchain(inputs, out_p):
    """Newest state = newest complete IDP-STATE base + every complete IDP-PATCH chained after it."""
    import re, hashlib, tempfile
    files = []
    for x in inputs:
        files += sorted(glob.glob(os.path.join(x, "*"))) if os.path.isdir(x) else [x]
    bases, patches = {}, {}
    for f in files:
        b = body_of(f)
        m = re.match(r"\s*IDP-STATE (\S+) part (\d+)/(\d+) sha256=([0-9a-f]{64})", b)
        if m:
            bases.setdefault((m.group(1), int(m.group(3)), m.group(4)), {})[int(m.group(2))] = f
            continue
        m = re.match(r"\s*IDP-PATCH (\S+) base (\S+) part (\d+)/(\d+) sha256=([0-9a-f]{64})", b)
        if m:
            patches.setdefault((m.group(1), m.group(2), int(m.group(4)), m.group(5)), {})[int(m.group(3))] = b.split("\n", 1)[1]
    state = None
    for key in sorted(bases, key=lambda k: k[0], reverse=True):
        date, N, sha = key
        if set(bases[key]) != set(range(1, N + 1)):
            print("chain: base %s incomplete (%d of %d parts), skipped" % (date, len(bases[key]), N)); continue
        tmp = tempfile.mkdtemp()
        ok = unpack([bases[key][i] for i in range(1, N + 1)], os.path.join(tmp, "s.json")) == 0
        if ok:
            state = json.load(open(os.path.join(tmp, "s.json"), encoding="utf-8"))
        import shutil; shutil.rmtree(tmp, ignore_errors=True)  # OVERLAY_7: no state copy left behind
        if ok:
            break
    if state is None:
        print("CHAIN FAILED: no complete IDP State base"); return 1
    base_date = state.get("date"); steps = []
    while True:
        nxt = [k for k in patches if k[1] == state.get("date") and set(patches[k]) == set(range(1, k[2] + 1))]
        if not nxt:
            break
        k = max(nxt, key=lambda k: k[0])
        ops = [json.loads(l) for i in range(1, k[2] + 1) for l in patches[k][i].splitlines() if l.strip()]
        s2 = apply_patch(state, ops)
        if _sha(s2) != k[3]:
            print("chain: patch %s sha mismatch, chain stops at %s" % (k[0], state.get("date"))); break
        state = s2; steps.append(k[0])
    for k in patches:
        if k[0] not in steps and k[0] > (state.get("date") or ""):
            print("chain: patch %s not applied (incomplete or no matching base)" % k[0])
    json.dump(state, open(out_p, "w", encoding="utf-8"), ensure_ascii=False)
    print("CHAIN OK: base %s + %d patch(es) %s -> state dated %s, %d patients"
          % (base_date, len(steps), ",".join(steps) or "-", state.get("date"), len(state.get("patients", {}))))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):  # OVERLAY_6 4g
        print(__doc__); print("Also: asbaseline <dirs...> <out.json> | patch <old.json> <new.json> <outdir> | unpackchain <dirs...> <out.json>")
        sys.exit(2)
    cmd, a = sys.argv[1], sys.argv[2:]
    if cmd == "unpack": sys.exit(unpack(a[:-1], a[-1]))
    elif cmd == "verify": sys.exit(verify(a[0], a[1]))
    elif cmd == "asbaseline": sys.exit(asbaseline(a[:-1], a[-1]))
    elif cmd == "patch": sys.exit(patch_write(a[0], a[1], a[2]))
    elif cmd == "unpackchain": sys.exit(unpackchain(a[:-1], a[-1]))
    else: print(__doc__)
