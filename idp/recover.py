#!/usr/bin/env python3
"""Recover an inline tool result from the session transcript, so nothing is retyped.

Usage:
  recover.py --needle <substring> <out>          last tool result containing <substring>, written verbatim
  recover.py --gmail-raw <message_id> <out.json> the get_message RAW result for that id (JSON with 'raw')
  recover.py --spill <path> <out>                copy a spilled tool-result file (no-op convenience)
Exit 1 with a message when nothing matches.
"""
import sys, os, glob, json


def transcript_paths():
    pats = [os.path.expanduser("~/.claude/projects/*/*.jsonl"), "/root/.claude/projects/*/*.jsonl",
            "/home/*/.claude/projects/*/*.jsonl"]
    out = []
    for p in pats:
        out += glob.glob(p)
    return sorted(set(out), key=os.path.getmtime)


def iter_results(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if '"tool_result"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for it in content:
                if not (isinstance(it, dict) and it.get("type") == "tool_result"):
                    continue
                body = it.get("content")
                if isinstance(body, list):
                    body = "".join(b.get("text", "") for b in body if isinstance(b, dict))
                if isinstance(body, str):
                    yield body
            tur = d.get("toolUseResult")
            if isinstance(tur, str):
                yield tur
            elif isinstance(tur, (dict, list)):
                yield json.dumps(tur)


def find(needle):
    best = None
    for p in transcript_paths():
        for body in iter_results(p):
            if needle in body:
                best = body
    return best


def main(argv):
    if len(argv) < 3:
        print(__doc__); return 2
    mode, key, out = argv[0], argv[1], argv[2]
    if mode == "--spill":
        data = open(key, encoding="utf-8").read()
        open(out, "w", encoding="utf-8").write(data); print("copied", len(data), "chars"); return 0
    if mode == "--needle":
        body = find(key)
        if body is None:
            print("recover: no tool result contains", key); return 1
        open(out, "w", encoding="utf-8").write(body)
        print("recovered", len(body), "chars ->", out); return 0
    if mode == "--gmail-raw":
        body = None
        for p in transcript_paths():
            for b in iter_results(p):
                if ('"id":"%s"' % key in b or '"id": "%s"' % key in b) and '"raw"' in b:
                    body = b
        if body is None:
            print("recover: no RAW result for message", key); return 1
        start = body.find("{")
        obj = json.loads(body[start:body.rfind("}") + 1])
        json.dump(obj, open(out, "w", encoding="utf-8"))
        print("recovered RAW for", key, "raw chars", len(obj.get("raw", "")), "->", out); return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
