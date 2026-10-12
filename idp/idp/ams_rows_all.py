#!/usr/bin/env python3
"""AMS rows for every resident (amendment Y2, Chris 11.10.2026): one book, everyone's blocks.

    python3 ams_rows_all.py <ams_spill.json|ams.xlsx|MISSING> out/state_new.json out --date YYYY-MM-DD \
        --fellow CH [--census out/census.json] [--edits in/edits.json]
    python3 ams_rows_all.py --check out/AMS_rows_YYYY-MM-DD.xlsx

Writes out/AMS_rows_<date>.xlsx with three sheets:
  "AMS rows"         the blocks of --fellow (Chris), exactly as ams_rows.py writes them;
  "Other residents"  every other resident's blocks, grouped under a "Fellow: XX" line ("Fellow: not assigned" when
                     the fellow is blank or "?");
  "Summary"          where each block sits and what changed, per fellow, plus the culture lines left out.
Same selection per fellow as ams_rows.py: census patients, plus off-list patients whose AMS block is not finalised
(signed-off and consult-only records stay out the same way). Then checks_R.py ams runs on both rows sheets; prints
AMS ROWS ALL OK, or CHECK FAILED with the cells to fix (fix them in the xlsx, then run --check until OK).
Delivered in the run session, never by email.
"""
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ams_rows as R  # noqa: E402

UNASSIGNED = ("", "?", None)


def check(path):
    p = subprocess.run([sys.executable, os.path.join(HERE, "checks_R.py"), "ams", path], capture_output=True, text=True)
    out = [l for l in p.stdout.splitlines() if l.startswith(("FAIL", "WARN"))]
    for l in out:
        print(l)
    if p.returncode == 0:
        print("AMS ROWS ALL OK: checks R passed on every rows sheet")
        return 0
    print("CHECK FAILED (%d): fix these cells in %s, then run --check again" % (sum(l.startswith("FAIL") for l in out), path))
    return 1


def fellows_of(state, today):
    """Every fellow with at least one block today, unassigned last."""
    seen = set()
    for p in state["patients"].values():
        f = (p.get("synth") or {}).get("_fellow")
        if (p.get("active") and (p.get("synth") or {}).get("_date") == today.isoformat()) or (not p.get("active") and p.get("archived")):
            seen.add(f if f not in UNASSIGNED else None)
    return sorted((f for f in seen if f), key=str) + ([None] if None in seen else [])


def main():
    a = sys.argv[1:]
    if a and a[0] == "--check":
        sys.exit(check(a[1]))
    ams, st, outdir = a[0], a[1], a[2]
    opt = dict(zip(a[3::2], a[4::2]))
    today = datetime.date.fromisoformat(opt["--date"])
    me = opt.get("--fellow", "CH")
    state = json.load(open(st, encoding="utf-8"))
    wb, entries, widths = R.open_book(ams)
    mine, c_me = R.build_items(state, entries, today, me, opt)
    groups, totals = [], {}
    for f in fellows_of(state, today):
        if f == me:
            continue
        items = []
        for value in ([f] if f else list(UNASSIGNED)):
            got, c = R.build_items(state, entries, today, value, opt)
            items += got
            for k, v in c.items():
                totals[k] = totals.get(k, 0) + v
        if items:
            groups.append(("Fellow: %s" % (f or "not assigned"), items))
    import openpyxl
    book = openpyxl.Workbook()
    R.rows_sheet(book.active, "AMS rows", mine, widths)
    others = book.create_sheet("Other residents")
    if groups:
        R.rows_sheet(others, "Other residents", [], widths, groups=groups)
    else:
        others.cell(1, 1, "No other resident has a block today.")
    R.summary_sheet(book, [("Fellow: %s" % me, mine)] + groups)
    path = os.path.join(outdir, "AMS_rows_%s.xlsx" % today.isoformat())
    R.clean_and_save(book, path)
    n_other = sum(len(i) for _, i in groups)
    print("AMS ROWS: %d mine (%d new entries), %d other residents in %d group%s (%d new entries), file %s"
          % (len(mine), c_me["new"], n_other, len(groups), "" if len(groups) == 1 else "s", totals.get("new", 0), path))
    sys.exit(check(path))


if __name__ == "__main__":
    main()
