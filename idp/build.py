#!/usr/bin/env python3
"""Orchestrator: validate -> report -> render -> DOCX parts (build + verify) -> state -> coverage -> handout body.

Usage: build.py <workdir> "<DD Month YYYY>" --date YYYY-MM-DD [--as-today in/as_today.json] [--ams in/ams.json] [--max-b64 13000]
Expects <workdir>/synth.py and <workdir>/out/ from match.py. Stops on the first validator error.
"""
import sys, os, re, json, base64, hashlib, argparse, subprocess, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import jload, ddmm
HERE = os.path.dirname(os.path.abspath(__file__))


def run(*args, must=None):
    r = subprocess.run([sys.executable] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr.strip():
        sys.stdout.write(r.stderr[-2000:])
    if r.returncode != 0 or (must and must not in r.stdout):
        print("BUILD STOPPED at", os.path.basename(args[0])); sys.exit(1)
    return r.stdout


def coverage(work, today):
    out = os.path.join(work, "out")
    rows = jload(os.path.join(out, "ward_rows.json")) if os.path.exists(os.path.join(out, "ward_rows.json")) else {}
    from validate_synth import load_synth
    S = load_synth(os.path.join(work, "synth.py")).SYNTH
    t = dt.date.fromisoformat(today); recent = {ddmm(t.isoformat()), ddmm((t - dt.timedelta(days=1)).isoformat())}
    missing = []
    for pid, rs in rows.items():
        e = S.get(pid)
        if not e: continue
        hay = re.sub(r"\s+", " ", json.dumps(e, ensure_ascii=False).lower())
        for r in rs[:1]:
            text = " ".join(r.get("cells", {}).values()) if r.get("cells") else r.get("text", "")
            for ln in re.split(r"[\n;]+|(?<=[.!?])\s+", text):
                ln = ln.strip()
                if len(ln) < 12 or not any(d in ln for d in recent): continue
                words = [w for w in re.findall(r"[a-z0-9]{4,}", ln.lower()) if w not in ("with", "that", "this", "from", "have", "been")]
                hit = sum(1 for w in words if w in hay)
                if words and hit / len(words) < 0.5:
                    missing.append("%s: %s" % (pid, ln[:160]))
    open(os.path.join(out, "coverage.txt"), "w", encoding="utf-8").write("\n".join(missing) + ("\n" if missing else ""))
    print("coverage: %d recent ward lines not reflected in synth (see out/coverage.txt)" % len(missing))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("work"); ap.add_argument("date_label"); ap.add_argument("--date", required=True)
    ap.add_argument("--as-today", default="MISSING"); ap.add_argument("--ams", default="MISSING"); ap.add_argument("--max-b64", type=int, default=13000)
    ap.add_argument("--single-docx", action="store_true", default=True)
    ap.add_argument("--split-docx", dest="single_docx", action="store_false")
    a = ap.parse_args()
    work = os.path.abspath(a.work); out = os.path.join(work, "out"); synth = os.path.join(work, "synth.py")
    run(os.path.join(HERE, "validate_synth.py"), synth, os.path.join(out, "census.json"), a.date, must="0 errors")
    run(os.path.join(HERE, "report.py"), out, synth, a.date, a.ams)
    run(os.path.join(HERE, "render.py"), synth, os.path.join(out, "census.json"), a.date, out)
    if a.single_docx:
        # One attachment, one transcription, one verification. The old 5-way split existed
        # because the EMAIL BODY exceeded 30000 chars, not because the DOCX was too big;
        # the recap now goes out as its own email so the body no longer forces a split.
        docx = os.path.join(out, "ID_Handout_%s.docx" % a.date_label.replace(" ", "_"))
        run(os.path.join(HERE, "build_docx.py"), os.path.join(out, "render.json"), docx, a.date_label)
        run(os.path.join(HERE, "verify_docx.py"), docx, os.path.join(out, "render.json"),
            must="ALL CHECKS PASSED")
        b = open(docx, "rb").read()
        b64 = base64.b64encode(b).decode()
        open(os.path.join(out, "handout.b64"), "w").write(b64)
        json.dump({"file": os.path.basename(docx), "bytes": len(b),
                   "sha256": hashlib.sha256(b).hexdigest(), "b64_chars": len(b64)},
                  open(os.path.join(out, "handout_manifest.json"), "w"), indent=1)
        print("handout: 1 attachment, %d bytes, %d base64 chars" % (len(b), len(b64)))
    else:
        run(os.path.join(HERE, "split_docx.py"), out, a.date_label, str(a.max_b64))
        for p in json.load(open(os.path.join(out, "parts", "manifest.json")))["parts"]:
            if p["verify"] != "PASS":
                print("BUILD STOPPED: DOCX part %d failed verification" % p["n"]); sys.exit(1)
    run(os.path.join(HERE, "state_io.py"), "finalize", os.path.join(out, "state_matched.json"), synth, os.path.join(out, "census.json"),
        a.as_today, a.date, os.path.join(out, "state_new.json"))
    run(os.path.join(HERE, "state_io.py"), "pack", os.path.join(out, "state_new.json"), os.path.join(out, "state_parts"))
    coverage(work, a.date)
    # Email 3 is the WhatsApp handoff: ID content only, no dose, no frequency, no
    # commentary, and no Flags block (house style; "Flags: none" used to be appended
    # here and was itself a house-style breach). recap_concise.txt is still written by
    # render.py but only backs the DOCX now; it is not sent.
    # Email 4 is out/archive_notes.txt, written above by state_io.py finalize. It is its
    # own email and is NOT appended here: the two together exceed the size at which the
    # recap would have to be split, and the recap must stay one email. Skip email 4 when
    # the file is empty, which is most mornings.
    run(os.path.join(HERE, "render_wa.py"), synth, os.path.join(out, "census.json"),
        os.path.join(out, "state_matched.json"), a.date, out)
    body = open(os.path.join(out, "whatsapp.txt"), encoding="utf-8").read().rstrip() + "\n"
    open(os.path.join(out, "recap_email.txt"), "w", encoding="utf-8").write(body)
    open(os.path.join(out, "handout_body.txt"), "w", encoding="utf-8").write(
        "ID Daily Handout Notes, %s. Full text in the recap email; columns 2 and 3 are "
        "left blank for handwriting.\n" % a.date_label)
    for f in ("recap_email.txt", "handout_body.txt"):
        n = len(open(os.path.join(out, f), encoding="utf-8").read())
        print("%s: %d chars%s" % (f, n, "  (OVER 30000: split into thread replies)" if n > 30000 else ""))
    if "\u2014" in body or "\u2013" in body:
        print("BUILD STOPPED: em or en dash in output"); sys.exit(1)
    print("BUILD OK")


if __name__ == "__main__":
    main()
