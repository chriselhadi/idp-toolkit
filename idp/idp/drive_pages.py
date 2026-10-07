#!/usr/bin/env python3
"""Drive listings must be complete (overlay 6, 07.10.2026, item 4r).

  drive_pages.py <out.json> <page1 result> [<page2 result> ...]

Each input is one search_files result (JSON, as saved from the tool result). Refuses (exit 1) when
the LAST page still carries a nextPageToken: fetch the next page first. Otherwise writes the merged
"files" list (deduplicated by id) to <out.json> and prints the count per title prefix.
"""
import sys, json


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); return 2
    files, last = {}, None
    for p in sys.argv[2:]:
        t = open(p, encoding="utf-8").read()
        o = json.loads(t[t.find("{"):t.rfind("}") + 1])
        for f in o.get("files", []):
            files[f["id"]] = f
        last = o
    if last and last.get("nextPageToken"):
        print("drive_pages: INCOMPLETE, the last page has a nextPageToken; call search_files with pageToken and add it")
        return 1
    json.dump(list(files.values()), open(sys.argv[1], "w", encoding="utf-8"))
    pre = {}
    for f in files.values():
        k = " ".join(f.get("title", "").split()[:2]); pre[k] = pre.get(k, 0) + 1
    print("drive_pages: COMPLETE, %d files (%s)" % (len(files), ", ".join("%s %d" % kv for kv in sorted(pre.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
