#!/usr/bin/env python3
"""Build the DOCX and split it into email-sized parts, each a complete, verified document.

Usage: split_docx.py <outdir> "<DD Month YYYY>" [max_b64_chars=13000]
Reads outdir/render.json; writes outdir/parts/partN.docx, partN.b64 (single line), manifest.json.
"""
import sys, os, json, base64, hashlib, subprocess, shutil
sys.path.insert(0, os.path.dirname(__file__))
from common import WARD_ORDER, jload
from build_docx import build

HERE = os.path.dirname(os.path.abspath(__file__))


def verify(docx, render, groups):
    cmd = [sys.executable, os.path.join(HERE, "verify_docx.py"), docx, render]
    if groups: cmd += ["--groups", ",".join(groups)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return "RESULT: ALL CHECKS PASSED" in r.stdout, r.stdout


def main():
    out = sys.argv[1]; date_label = sys.argv[2]; maxc = int(sys.argv[3]) if len(sys.argv) > 3 else 13000
    rpath = os.path.join(out, "render.json"); render = jload(rpath)
    pdir = os.path.join(out, "parts"); shutil.rmtree(pdir, ignore_errors=True); os.makedirs(pdir)
    date_file = date_label.replace(" ", "_")
    groups_present = [g for g in WARD_ORDER if any(p["group"] == g for p in render["patients"])]

    def make(n, groups, label, total):
        fn = "ID_Handout_%s%s.docx" % (date_file, ("_part%d" % n) if total > 1 else "")
        path = os.path.join(pdir, "part%d.docx" % n)
        build(render, path, date_label, groups, label)
        data = open(path, "rb").read(); b64 = base64.b64encode(data).decode()
        open(os.path.join(pdir, "part%d.b64" % n), "w").write(b64)
        ok, log = verify(path, rpath, groups)
        return {"n": n, "filename": fn, "label": label, "groups": groups or groups_present, "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "b64_chars": len(b64), "verify": "PASS" if ok else "FAIL", "log": log.strip().splitlines()[-2:]}

    # try one part first
    m = make(1, None, "", 1)
    parts = [m]
    if m["b64_chars"] > maxc:
        # greedy by ward group; a single group too big gets split by patient halves within it
        chunks, cur = [], []
        for g in groups_present:
            trial = cur + [g]
            tmp = os.path.join(pdir, "trial.docx"); build(render, tmp, date_label, trial, "")
            if len(base64.b64encode(open(tmp, "rb").read())) > maxc and cur:
                chunks.append(cur); cur = [g]
            else:
                cur = trial
        if cur: chunks.append(cur)
        for f in os.listdir(pdir): os.remove(os.path.join(pdir, f))
        parts = [make(i + 1, ch, "part %d of %d: %s" % (i + 1, len(chunks), ", ".join(ch)), len(chunks)) for i, ch in enumerate(chunks)]
    for p in parts:
        p.pop("log", None)
    json.dump({"date": date_label, "parts": parts}, open(os.path.join(pdir, "manifest.json"), "w"), indent=1)
    for p in parts:
        print("part%d %s bytes=%d b64=%d verify=%s groups=%s" % (p["n"], p["filename"], p["bytes"], p["b64_chars"], p["verify"], ",".join(p["groups"])))
    return 0 if all(p["verify"] == "PASS" for p in parts) else 1


if __name__ == "__main__":
    sys.exit(main())
