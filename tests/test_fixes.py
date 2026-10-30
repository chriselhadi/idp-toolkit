#!/usr/bin/env python3
"""Regression checks for four fixes, fictional data only.

Usage: test_fixes.py <toolkit idp/idp dir> <workdir> <day-2 run dir of the e2e run>
Prints "CHECK <name> OK" per check; exit 1 on the first failure.

  1. AMS block boundaries: a block followed by 800 empty rows ends at its own last row (ams_rows.index_entries,
     parse_ams.parse_sheet); 3 empty rows or a repeated header row end a block.
  2. export.py: no file over --max-file, the whole export within --max-total, oldest history days trimmed first,
     empty and repeated rows left out, the final EXPORT OK line.
  3. match.parse_roster: a line whose room is a word ("OBGYN Jane Doe CH") is a patient, not a heading.
  4. idp9.apply_id_list: two patients in one room are matched by name, none left out.
"""
import glob, json, os, re, shutil, subprocess, sys

I, W, D2 = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, I)
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)


def ok(name, cond, detail=""):
    if not cond:
        print("CHECK %s FAILED%s" % (name, (": " + detail) if detail else ""))
        sys.exit(1)
    print("CHECK %s OK" % name)


# ---------------- 1. AMS block boundaries ----------------
import openpyxl  # noqa: E402
import ams_rows as A  # noqa: E402
import parse_ams  # noqa: E402

HEAD = [""] * A.COLS
HEAD[A.C_NAME - 1], HEAD[A.C_MRN - 1], HEAD[A.C_ABX - 1], HEAD[A.C_START - 1] = "Pt name", "MRN", "Actual antibiotics", "Date started"


def row(name="", mrn="", abx="", start=""):
    r = [None] * A.COLS
    for c, v in ((A.C_NAME, name), (A.C_MRN, mrn), (A.C_ABX, abx), (A.C_START, start)):
        if v:
            r[c - 1] = v
    return r


wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Main sheet Oct 2026"
ws.append(HEAD)                                                   # 1
ws.append(row("Alpha Example", "900001", "Mero", "01/10/2026"))   # 2
ws.append(row(abx="Vanco", start="02/10/2026"))                   # 3
for _ in range(800):                                              # 4..803 fully empty
    ws.append([None] * A.COLS)
ws.append(row(abx="Stray drug", start="05/10/2026"))              # 804: after the gap, belongs to no block
ws.append(row("Bravo Example", "900002", "Erta", "03/10/2026"))   # 805
ws.append([None] * A.COLS)                                        # 806 one empty row: still Bravo's block
ws.append(row(abx="Cipro", start="04/10/2026"))                   # 807
ws.append(HEAD)                                                   # 808 repeated header row
ws.append(row(abx="After header", start="06/10/2026"))            # 809
ws.append(row("Charlie Example", "900003", "Linezolid", "07/10/2026"))  # 810
for _ in range(800):                                              # the last entry, then 800 empty rows to the end
    ws.append([None] * A.COLS)
ws.cell(row=1611, column=1, value=None)
ent = {str(r[s - 1][A.C_MRN - 1].value): (s, e) for _, s, e, r in A.index_entries(wb)}
ok("ams_block_800_empty_rows", ent.get("900001") == (2, 3), repr(ent))
ok("ams_block_one_empty_row_kept", ent.get("900002") == (805, 807), repr(ent))
ok("ams_block_last_entry_no_tail", ent.get("900003") == (810, 810), repr(ent))
ok("ams_header_not_an_entry", set(ent) == {"900001", "900002", "900003"}, repr(ent))
blocks, _ = parse_ams.parse_sheet(ws, "2026-10-27")
by = {b["mrn"]: [a["drug"] for a in b["abx"]] for b in blocks}
ok("parse_ams_800_empty_rows", by.get("900001") == ["Mero", "Vanco"], repr(by))
ok("parse_ams_header_ends_block", by.get("900002") == ["Erta", "Cipro"] and by.get("900003") == ["Linezolid"], repr(by))

# ---------------- 2. export.py stays small ----------------
run = os.path.join(W, "run")
shutil.copytree(os.path.join(D2, "out"), os.path.join(run, "out"))
for p in glob.glob(os.path.join(run, "out", "export*")):
    shutil.rmtree(p, ignore_errors=True)
sp = os.path.join(run, "out", "state_new.json")
st = json.load(open(sp, encoding="utf-8"))
pid = next(k for k, r in st["patients"].items() if r["name"] == "Alpha Tester One")
sy = st["patients"][pid]["synth"]
filler = "febrile overnight, cultures sent, plan reviewed with the team " * 20
old = ["%02d/%02d: %s" % (d, m, filler) for m in (6, 7, 8) for d in range(1, 29)]   # 84 old days, ~1250 chars each
sy["updates"] = old * 3 + sy["updates"] + sy["updates"]                            # every entry repeated
n_micro = len(sy.get("micro", []))
sy["micro"] = sy.get("micro", []) + sy.get("micro", [])  # same-day sets with the same text: two results each
json.dump(st, open(sp, "w", encoding="utf-8"))
bp = os.path.join(run, "out", "ams_blocks.json")
bl = json.load(open(bp, encoding="utf-8"))
b = bl["patients"][pid]
nrows = len(b["rows"])
b["rows"] += [[""] * len(b["header"]) for _ in range(800)]
b["tsv"] += "\n" + "\n".join("\t" * (len(b["header"]) - 1) for _ in range(800))
json.dump(bl, open(bp, "w", encoding="utf-8"))

ex = lambda out, *extra: subprocess.run([sys.executable, os.path.join(I, "export.py"), run, "--date", "2026-09-07",
                                         "--out", os.path.join(W, out)] + list(extra), capture_output=True, text=True)
raw = ex("export_uncapped", "--max-total", "0", "--max-file", "0", "--part-chars", "0")
size_raw = sum(os.path.getsize(p) for p in glob.glob(os.path.join(W, "export_uncapped", "**", "*.*"), recursive=True))
ok("export_fixture_is_large", raw.returncode == 0 and size_raw > 120000, "uncapped export %d chars" % size_raw)
r = ex("export_capped")
ok("export_capped_runs", r.returncode == 0, r.stdout[-800:] + r.stderr[-800:])
last = r.stdout.strip().splitlines()[-1]
m = re.fullmatch(r"EXPORT OK: (\d+) patients, (\d+) files, (\d+) chars", last)
ok("export_final_line", bool(m), last)
files = [p for p in glob.glob(os.path.join(W, "export_capped", "**", "*.*"), recursive=True)]
sizes = {os.path.relpath(p, W): len(open(p, encoding="utf-8").read()) for p in files}
ok("export_no_file_over_20000", max(sizes.values()) <= 20000, repr(sorted(sizes.items(), key=lambda x: -x[1])[:3]))
ok("export_total_within_120000", sum(sizes.values()) <= 120000 and int(m.group(3)) == sum(sizes.values())
   and int(m.group(2)) == len(files), "%d chars in %d files; %s" % (sum(sizes.values()), len(files), last))
ok("export_trim_reported", "TRIMMED dashboard: dropped" in r.stdout, r.stdout[-600:])
sys.path.insert(0, I)
import export  # noqa: E402
ps = sorted(glob.glob(os.path.join(W, "export_capped", "IDP Dashboard 2026-09-07*.json")),
            key=lambda p: int(re.search(r"part (\d+) of", p).group(1)) if "part" in p else 0)
dash = export.unslim(json.loads("".join(open(p, encoding="utf-8").read() for p in ps)))
alpha = next(p for p in dash["patients"] if p["pid"] == pid)
ok("export_newest_days_kept", alpha["updates"] and alpha["updates"][-1].startswith("07/09")
   and not any(u.startswith("01/06") for u in alpha["updates"]), repr(alpha["updates"][:2]))
ok("export_no_repeated_entries", len(alpha["updates"]) == len(set(alpha["updates"])))
ok("export_micro_lookalikes_kept", n_micro > 0 and len(alpha["micro"]) == 2 * n_micro, repr(alpha["micro"]))
ok("export_ams_block_no_empty_tail", len(alpha["ams_block"]["rows"]) == nrows
   and any(c for c in alpha["ams_block"]["rows"][-1]), "%d rows, expected %d" % (len(alpha["ams_block"]["rows"]), nrows))
micro_rows = [l for p in glob.glob(os.path.join(W, "export_capped", "tables", "micro 2026-09-07*.csv"))
              for l in open(p, encoding="utf-8").read().splitlines()[1:]]
ok("export_table_micro_lookalikes_kept", len([l for l in micro_rows if ",%s," % pid in l]) == 2 * n_micro, repr(micro_rows))
id_rows = [l for p in glob.glob(os.path.join(W, "export_capped", "tables", "abx_courses 2026-09-07*.csv"))
           for l in open(p, encoding="utf-8").read().splitlines()[1:]]
ok("export_table_no_repeated_rows", len(id_rows) == len(set(id_rows)), repr(id_rows))
cx = {"date": "2026-09-05", "family": "blood", "text": "BCx GNB", "status": "prelim", "organism": "", "ast": "", "positive": True}
pr = {"issues": [], "abx_other": [], "micro": [], "ams": {"courses": [], "cultures": [dict(cx, row=4), dict(cx, row=5), dict(cx, row=4)]}}
got = [c["row"] for c in export.compact_patient(pr)["ams"]["cultures"]]
ok("export_ams_cultures_same_row_only", got == [4, 5], repr(got))
small = ex("export_small", "--max-total", "60000", "--max-file", "5000")
sizes = [len(open(p, encoding="utf-8").read()) for p in glob.glob(os.path.join(W, "export_small", "**", "*.*"), recursive=True)]
ok("export_flags", small.returncode == 0 and max(sizes) <= 5000 and sum(sizes) <= 60000,
   "max %d, total %d; %s" % (max(sizes), sum(sizes), small.stdout[-400:]))
tiny = ex("export_tiny", "--max-total", "10000")
tiny_tables = {os.path.basename(p): open(p, encoding="utf-8").read()
               for p in glob.glob(os.path.join(W, "export_tiny", "tables", "*.csv"))}
full_tables = {os.path.basename(p): open(p, encoding="utf-8").read()
               for p in glob.glob(os.path.join(W, "export_capped", "tables", "*.csv"))}
tsizes = [len(open(p, encoding="utf-8").read()) for p in glob.glob(os.path.join(W, "export_tiny", "**", "*.*"), recursive=True)]
ok("export_budget_unreachable_warns", tiny.returncode == 0 and "OVER TARGET" in tiny.stdout and "SIZE dashboard" in tiny.stdout
   and tiny.stdout.strip().splitlines()[-1].startswith("EXPORT OK") and max(tsizes) <= 20000, tiny.stdout[-400:])
ok("export_tables_kept_when_dashboard_over", tiny_tables == full_tables and "TRIMMED tables: dropped" not in tiny.stdout,
   tiny.stdout[-400:])

# ---------------- 3. roster: a word in the room slot is a patient ----------------
import match  # noqa: E402
rp = os.path.join(W, "roster.txt")
open(rp, "w", encoding="utf-8").write("\n".join([
    "Floors:", "708B Alpha Example CH", "OBGYN Jane Doe CH", "Room unknown Lea Example MJ", "OBGYN", "Room unknown"]) + "\n")
ro = match.parse_roster(rp)
jane = [x for x in ro if x["name"] == "Jane Doe"]
ok("roster_word_room_kept", len(jane) == 1 and jane[0]["room"] == "?" and jane[0]["room_hint"] == "OBGYN"
   and jane[0]["fellow"] == "CH", repr(ro))
lea = [x for x in ro if x["name"] == "Lea Example"]
ok("roster_room_unknown_kept", len(lea) == 1 and lea[0]["room"] == "?" and lea[0]["fellow"] == "MJ", repr(ro))
ok("roster_headings_dropped", [x["name"] for x in ro] == ["Alpha Example", "Jane Doe", "Lea Example"], repr(ro))

# ---------------- 4. ID list: two patients in one room ----------------
import idp9  # noqa: E402
census = {"patients": [
    {"pid": "Q1", "room": "ICU6D", "name": "Juliet Example Haddock", "group": "ICU#D"},
    {"pid": "Q2", "room": "ICU6D", "name": "Juliet Example", "group": "ICU#D"},
    {"pid": "Q3", "room": "405", "name": "Kilo Example", "group": "4th floor"}]}
for label, lines in (("vague_line_first", ["ICU6D Juliet CH", "ICU6D Juliet Example MJ"]),
                     ("exact_line_first", ["ICU6D Juliet Example MJ", "ICU6D Juliet CH"])):
    open(os.path.join(W, "id_list_email.txt"), "w", encoding="utf-8").write(
        "4th floor A:\n405 Kilo Example CH\n\nICU D:\n" + "\n".join(lines) + "\n")
    c = idp9.apply_id_list(json.loads(json.dumps(census)), W, quiet=True)
    rep = open(os.path.join(W, "idlist_order.txt"), encoding="utf-8").read()
    got = {l.split(" | ")[1].split(" -> ")[0]: l.split(" -> ")[1].split()[0] for l in rep.splitlines() if " -> " in l}
    ok("idlist_same_room_%s" % label, sorted(x["pid"] for x in c["patients"]) == ["Q1", "Q2", "Q3"]
       and "LEFT OUT" not in rep and "UNMATCHED" not in rep
       and got.get("ICU6D Juliet Example") == "Q2" and got.get("ICU6D Juliet") == "Q1", rep)
# ---------------- 5. Overlay 10 in the repo: idp10, idp11, tools/wa_handout.py, tools/recap_html.py ----------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(I)))
TOOLS = os.path.join(ROOT, "tools")
for f in ("match.py", "state_io.py", "idp10.py"):
    ok("overlay10_in_%s" % f.replace(".", "_"), "OVERLAY_10" in open(os.path.join(I, f), encoding="utf-8").read())
r = subprocess.run([sys.executable, os.path.join(I, "idp11.py")], capture_output=True, text=True)
ok("idp11_loads_idp10", r.returncode == 0 and "regjoin2" in r.stdout, r.stderr[-300:])
cen = os.path.join(W, "wa_census.json")
json.dump({"patients": [{"pid": "Q1", "room": "ICU6D", "name": "Juliet Example Haddock"},
                        {"pid": "Q2", "room": "ICU6D", "name": "Juliet Example"},
                        {"pid": "Q3", "room": "405", "name": "Kilo Example"}]}, open(cen, "w"))
syn = os.path.join(W, "wa_synth.py")
open(syn, "w").write('WA = {"Q1": ["70F, line for Q1"], "Q2": ["60M, line for Q2"], "Q3": ["50F, line for Q3"]}\n')
for label, lines in (("vague_line_first", ["*ICU6D* Juliet CH", "ICU6D Juliet Example MJ"]),
                     ("exact_line_first", ["ICU6D Juliet Example MJ", "*ICU6D* Juliet CH"])):
    idl = os.path.join(W, "wa_idlist.txt")
    open(idl, "w").write("4th floor A:\n405 Kilo Example CH\n\nICU D:\n" + "\n".join(lines) + "\n")
    wo = os.path.join(W, "wa_out.txt")
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "wa_handout.py"), idl, cen, syn, wo, "28.10.2026"],
                       capture_output=True, text=True)
    txt = open(wo).read() if os.path.exists(wo) else ""
    ok("wa_same_room_%s" % label, r.stdout.startswith("WA OK: 3 patients")
       and "Juliet Example MJ\n60M, line for Q2" in txt and "Juliet CH\n70F, line for Q1" in txt, r.stdout + txt)
rt = os.path.join(W, "recap.txt")
open(rt, "w").write("ID Daily Recap\n\n*ICU D:*\nICU6D Juliet Example [MJ]\n60M, history\nUpdate (ID): afebrile\n!! Conflict: x vs y\n")
r = subprocess.run([sys.executable, os.path.join(TOOLS, "recap_html.py"), rt, os.path.join(W, "recap.html")], capture_output=True, text=True)
ok("recap_html_runs", r.stdout.startswith("RECAP HTML OK"), r.stdout + r.stderr[-300:])
print("FIXES TESTS OK")
# ---------------- 6. Register coverage and Schema (29.10.2026): fictional pids only ----------------
import importlib.util  # noqa: E402
_s = importlib.util.spec_from_file_location("idp11", os.path.join(I, "idp11.py")); X = importlib.util.module_from_spec(_s); _s.loader.exec_module(X)
ok("idp11_apostrophe", X.cell("123456") == "'123456" and X.cell("05/10") == "'05/10" and X.cell("=1+1") == "'=1+1"
   and X.cell("Mero IV q8h") == "Mero IV q8h" and X.bare("'05/10") == "05/10")
ok("idp11_dates_ddmmyy", X.dmy("2026-10-29") == "29/10/26")
hdr = X.TABS["Feed Patients"][0]
ok("idp11_feed_header_v2", hdr[-2:] == ["AMS block", "Updated"] and X.SCHEMA_VERSION == "2")
des = {"Feed Patients": [["Q9001", "'900001", "Alpha Example", "Active"] + [""] * 18,
                         ["Q9002", "'900002", "Beta Example", "Discharged 20/10/26"] + [""] * 18]}
cv = X.coverage({"Feed Patients": [[r[0].replace("Q", "P")] + r[1:] for r in des["Feed Patients"]]},
                [X.INDEX_HDR, ["900001", "Alpha Example", "", "MRN 900001 | P9001 | 28/10/26 to", "", "", "", "", "", "N"]])
ok("idp11_coverage", cv["n"] == 2 and cv["missing"] == 1 and cv["bad"][0][0] == "P9002", str(cv))
sr = X.schema_rows("feed") + X.schema_rows("register")
ok("idp11_schema_rows", all(len(r) == 4 for r in sr) and not any(re.search("[\u2013\u2014]", " ".join(r)) for r in sr)
   and any(r[0] == "Feed Patients" and "AMS block" in r[2] for r in sr))
# a feed read back with the apostrophes kept as text must still match what was written
fp = os.path.join(W, "feed_rb.json")
json.dump({"values": [["pid", "MRN"], ["P9001", "'900001"], ["P9002", "900002"]]}, open(fp, "w"))
ok("idp11_readback_apostrophe", X.raw_values(fp)[1:] == [["P9001", "900001"], ["P9002", "900002"]], str(X.raw_values(fp)))
print("REGISTER TESTS OK")
