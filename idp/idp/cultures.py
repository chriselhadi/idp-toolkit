#!/usr/bin/env python3
"""Read the micro digests (Daily_Cultures) into structured culture results, per specimen and per patient.

    python3 cultures.py <in/cultures.txt | dir of "Cultures YYYY-MM-DD" files> out/census.json out --date YYYY-MM-DD \
        [--archive <archive sheet: get_values JSON, TSV or CSV>]

The digests are written by the clinical micro extractor skill (micro/SKILL.md) in a fixed WhatsApp format:
  Part A  *Daily Report DD/MM/YYYY*   - <bench no> *Name* (b. _YYYY_ | _unit_): Sample: preliminary result
  Part B  *Micro Digest DD/MM/YYYY*   *Name* (DOB _DD/MM/YYYY_ | MRN _XXXXXX_ | _Unit_)
                                      - [POS|PRELIM|SCREEN +|SCREEN -|NEG] *Specimen* (SID _n_, coll. _DD/MM_, DR n): result
                                        - <organism>: *S:* _drugs_, *R:* _drugs_      (one indented line per organism)
  Part C  *Verify*                    one line per uncertain reading
The run's in/cultures.txt (amendment L1b) holds every file under a "### <title> (<fileId>, modified <time>)" header;
a folder of the files themselves works too.

Precedence for one specimen (SID): a row in the archive sheet's "Finalised results" tab > the newest digest that
carries the SID > older digests (amendment L1c). A reading marked (?) stays flagged "to verify".

Writes out/cultures.json (every specimen with patient, MRN, specimen, collection date, status, final or not,
organisms, S and R drugs, result text, source) and out/cultures_packets.txt (per census patient, matched by MRN, the
specimens as micro lines ready for synthesis, final ones first). Prints CULTURES OK with counts. Read only.
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re

TITLE_RE = re.compile(r"^###\s+(.+?)\s+\(")
FILE_RE = re.compile(r"Cultures (\d{4}-\d{2}-\d{2})")
DIGEST_RE = re.compile(r"^\*Micro Digest (\d{2})/(\d{2})/(\d{4})\*")
REPORT_RE = re.compile(r"^\*Daily Report (\d{2})/(\d{2})/(\d{4})\*")
VERIFY_RE = re.compile(r"^\*Verify\*")
HEADER_RE = re.compile(r"^\*(?P<name>[^*]+)\*\s*\((?P<inside>[^)]*)\)\s*$")
SPEC_RE = re.compile(r"^- \[(?P<tag>POS|PRELIM|SCREEN \+|SCREEN -|NEG)\]\s*\*(?P<spec>[^*]+)\*\s*\((?P<inside>[^)]*)\):?\s*(?P<rest>.*)$")
SUB_RE = re.compile(r"^\s{2,}- (?P<rest>.+)$")
DR_RE = re.compile(r"^- (?P<bench>\d[\d/]*)(?:\s*\(\?\))?\s*\*(?P<name>[^*]+)\*\s*(?:\((?P<inside>[^)]*)\))?:\s*(?P<rest>.*)$")
ORG_RE = re.compile(r"\*_([^_*]+)_(\s*\([^)]*\))?\*")  # *_E. coli_* or *_E. coli_ (ESBL)*
S_RE = re.compile(r"\*S:\*\s*_([^_]+)_")
R_RE = re.compile(r"\*R:\*\s*_([^_]+)_")
I_RE = re.compile(r"\*I:\*\s*_([^_]+)_")
STATUS = {"POS": "POS", "PRELIM": "PRELIM", "SCREEN +": "SCREEN+", "SCREEN -": "SCREEN-", "NEG": "NEG"}
FAMILIES = (("blood", r"blood|bcx|bactec|\bbl\b"), ("urine", r"urine|ucx"), ("respiratory", r"sput|dta|\bbal\b|trache|bronch|resp"),
            ("screen", r"rectal|nasal|nose|axill|\bax\b|ing|screen|mdro|throat"), ("stool", r"stool|c\.? ?diff|feces"),
            ("csf", r"csf"), ("catheter", r"tip|catheter|\bkt\b"), ("wound", r"wound|pus|swab|abscess|tissue|bone"),
            ("fluid", r"pleural|ascit|fluid|drain|synov|perito"))


def plain(s):
    """Text without the WhatsApp marks."""
    return re.sub(r"[*_]", "", s or "").strip()


def family(s):
    t = (s or "").lower()
    for fam, rx in FAMILIES:
        if re.search(rx, t):
            return fam
    return "other" if t.strip() else ""


def day(ddmm, ref):
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", ddmm or "")
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = int(m.group(3)) if m.group(3) else ref.year
    y = y + 2000 if y < 100 else y
    try:
        v = dt.date(y, mo, d)
    except ValueError:
        return None
    if not m.group(3) and v > ref + dt.timedelta(days=31):
        v = v.replace(year=v.year - 1)
    return v


def field(inside, label):
    m = re.search(r"%s\s*_?([^_|,)]+)_?" % label, inside)
    return m.group(1).strip() if m else ""


def split_files(text):
    """[(title, text)] from the run's concatenated in/cultures.txt; a single file without headers is one item."""
    out, title, buf = [], None, []
    for line in text.splitlines():
        m = TITLE_RE.match(line)
        if m:
            if title is not None:
                out.append((title, "\n".join(buf)))
            title, buf = m.group(1), []
        else:
            buf.append(line)
    if title is not None:
        out.append((title, "\n".join(buf)))
    return out or [("", text)]


def parse_digest(title, text):
    """Specimens, Daily Report rows and Verify lines of one digest file."""
    fm = FILE_RE.search(title or "")
    ref = dt.date.fromisoformat(fm.group(1)) if fm else None
    part, patient, spec = None, None, None
    specimens, report, verify, unparsed = [], [], [], []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = DIGEST_RE.match(line)
        if m:
            part = "B"
            ref = ref or dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            continue
        m = REPORT_RE.match(line)
        if m:
            part = "A"
            ref = ref or dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            continue
        if VERIFY_RE.match(line):
            part = "C"
            continue
        ref_ = ref or dt.date.today()
        if part == "A":
            m = DR_RE.match(line)
            if m:
                ins = m.group("inside") or ""
                report.append({"bench": m.group("bench"), "patient": plain(m.group("name")),
                               "birth_year": field(ins, "b\\."), "result": plain(m.group("rest")),
                               "unit": plain(ins.split("|")[-1]) if "|" in ins else "", "file": title})
            elif line.startswith("- "):
                unparsed.append(line)
            continue
        if part == "C":
            if line.startswith("- "):
                verify.append(plain(line[2:]))
            continue
        if part != "B":
            continue
        m = SPEC_RE.match(line)
        groups = []
        tm = re.match(r"^- \[(?P<tag>POS|PRELIM|SCREEN \+|SCREEN -|NEG)\]\s*(?P<body>.+)$", line)
        if tm and patient:
            body = tm.group("body")
            cut = body.rfind("):")
            head, rest_all = (body[:cut + 1], body[cut + 2:].strip()) if cut >= 0 else (body, "")
            # one line may carry several sites, each with its own (SID/coll.) group: "*Rectal* and *Nasal* (coll. ...)"
            groups = [(g.group("spec"), g.group("ins")) for g in re.finditer(
                r"(?P<spec>(?:\*[^*]+\*[\s,]*(?:and\s+)?)+)\s*\((?P<ins>(?:SID|coll)[^)]*)\)", head)]
        if groups and not m:
            for spec_txt, ins in groups:
                fake = "- [%s] *%s* (%s): %s" % (tm.group("tag"), plain(spec_txt).replace("*", ""), ins, rest_all)
                m2 = SPEC_RE.match(fake)
                if m2:
                    m = m2
                    ins_, rest = m2.group("inside"), m2.group("rest")
                    coll = day(field(ins_, "coll\\."), ref or dt.date.today())
                    tag = STATUS[m2.group("tag")]
                    specimens.append({
                        "sid": field(ins_, "SID"), "dr": field(ins_, "DR"), **patient,
                        "specimen": plain(m2.group("spec")), "specimen_short": family(m2.group("spec")),
                        "collected": coll.isoformat() if coll else None, "status": tag,
                        "final": tag in ("NEG", "SCREEN-", "SCREEN+") and not re.search(r"pending|ongoing", rest, re.I),
                        "final_date": None, "updated": None, "unchanged_since": None, "result": plain(rest),
                        "organisms": [plain(o + (ph or "")) for o, ph in ORG_RE.findall(rest)], "ast_s": "", "ast_r": "", "ast_i": "",
                        "verify": "(?)" in rest, "source": title, "file_date": ref.isoformat() if ref else None,
                    })
            spec = specimens[-1] if specimens else None
            continue
        if m and patient:
            ins, rest = m.group("inside"), m.group("rest")
            coll = day(field(ins, "coll\\."), ref_)
            fin = re.search(r"Final (\d{1,2}/\d{1,2})", rest)
            upd = re.search(r"Updated (\d{1,2}/\d{1,2})", rest)
            unch = re.search(r"Unchanged since (\d{1,2}/\d{1,2})", rest)
            tag = STATUS[m.group("tag")]
            spec = {
                "sid": field(ins, "SID"), "dr": field(ins, "DR"), **patient,
                "specimen": plain(m.group("spec")), "specimen_short": family(m.group("spec")),
                "collected": coll.isoformat() if coll else None, "status": tag,
                "final": bool(fin) or tag in ("NEG", "SCREEN-", "SCREEN+") and not re.search(r"pending|ongoing", rest, re.I),
                "final_date": day(fin.group(1), ref_).isoformat() if fin and day(fin.group(1), ref_) else None,
                "updated": day(upd.group(1), ref_).isoformat() if upd and day(upd.group(1), ref_) else None,
                "unchanged_since": day(unch.group(1), ref_).isoformat() if unch and day(unch.group(1), ref_) else None,
                "result": plain(rest), "organisms": [plain(o + (ph or "")) for o, ph in ORG_RE.findall(rest)],
                "ast_s": ", ".join(plain(x) for x in S_RE.findall(rest)),
                "ast_r": ", ".join(plain(x) for x in R_RE.findall(rest)),
                "ast_i": ", ".join(plain(x) for x in I_RE.findall(rest)),
                "verify": "(?)" in rest, "source": title, "file_date": ref.isoformat() if ref else None,
            }
            specimens.append(spec)
            continue
        m = SUB_RE.match(raw)
        if m and spec is not None and not line.lstrip().startswith("- ["):
            rest = m.group("rest")
            spec["organisms"] += [plain(o + (ph or "")) for o, ph in ORG_RE.findall(rest)]
            spec["ast_s"] = ", ".join(x for x in (spec["ast_s"], *[plain(x) for x in S_RE.findall(rest)]) if x)
            spec["ast_r"] = ", ".join(x for x in (spec["ast_r"], *[plain(x) for x in R_RE.findall(rest)]) if x)
            spec["result"] += " | " + plain(rest)
            spec["verify"] = spec["verify"] or "(?)" in rest
            continue
        m = HEADER_RE.match(line)
        if m and ("MRN" in m.group("inside") or "DOB" in m.group("inside") or "|" in m.group("inside")):
            ins = m.group("inside")
            parts = [plain(x) for x in ins.split("|")]
            unit = next((x for x in parts if x and not x.startswith("DOB") and not x.startswith("MRN")), "")
            patient = {"patient": plain(m.group("name")), "dob": field(ins, "DOB"),
                       "mrn": re.sub(r"\D", "", field(ins, "MRN")), "unit": unit}
            spec = None
            continue
        if line.startswith("- "):
            unparsed.append(line)
    return specimens, report, verify, unparsed


ARCHIVE_COLS = ["SID", "Patient", "DOB", "MRN", "Unit", "Specimen", "Collected", "Status", "Result", "Organism",
                "AST S", "AST R", "AST notes", "Sign-off", "Daily Report no.", "First reported", "Last updated"]


def read_archive(path, ref):
    """Rows of the archive sheet's 'Finalised results' tab: Sheets get_values JSON, TSV or CSV."""
    if not path or path == "MISSING" or not os.path.exists(path):
        return []
    txt = open(path, encoding="utf-8").read()
    try:
        d = json.loads(txt[txt.find("{"):])
        rows = d.get("values") or []
    except Exception:
        rows = list(csv.reader(io.StringIO(txt), delimiter="\t" if "\t" in txt.splitlines()[0] else ","))
    head_i = next((i for i, r in enumerate(rows) if r and str(r[0]).strip().lstrip("'") == "SID"), None)
    if head_i is None:
        return []
    head = [str(h).strip() for h in rows[head_i]]
    out = []
    for r in rows[head_i + 1:]:
        rec = {h: str(r[i]).strip().lstrip("'") if i < len(r) else "" for i, h in enumerate(head)}
        if not rec.get("SID"):
            continue
        coll = day(rec.get("Collected", ""), ref)
        out.append({"sid": rec["SID"], "patient": rec.get("Patient", ""), "dob": rec.get("DOB", ""),
                    "mrn": re.sub(r"\D", "", rec.get("MRN", "")), "unit": rec.get("Unit", ""),
                    "specimen": rec.get("Specimen", ""), "specimen_short": family(rec.get("Specimen", "")),
                    "collected": coll.isoformat() if coll else None,
                    "status": rec.get("Status", "").replace(" ", "").upper() or "POS", "final": True,
                    "final_date": (day(rec.get("Sign-off", ""), ref) or day(rec.get("Last updated", ""), ref) or ref).isoformat(),
                    "result": rec.get("Result", ""), "organisms": [o.strip() for o in rec.get("Organism", "").split("|") if o.strip()],
                    "ast_s": rec.get("AST S", ""), "ast_r": rec.get("AST R", ""), "ast_i": "", "dr": rec.get("Daily Report no.", ""),
                    "verify": "(?)" in " ".join(rec.values()), "source": "Daily Cultures Archive",
                    "file_date": None, "updated": None, "unchanged_since": None})
    return out


def micro_line(s):
    """The specimen as a micro line in the synthesis grammar: '<dd/mm> <specimen> <result>'."""
    d = s["collected"]
    when = "%s/%s" % (d[8:10], d[5:7]) if d else "prior"
    what = "; ".join(s["organisms"]) if s["organisms"] else s["result"][:120]
    if s["ast_r"] or s["ast_s"]:
        what += " (%s)" % "; ".join(x for x in ("R " + s["ast_r"] if s["ast_r"] else "", "S " + s["ast_s"] if s["ast_s"] else "") if x)
    state = "" if s["final"] else (" prelim" if s["status"] == "PRELIM" else " pending")
    return "%s %s%s %s%s" % (when, s["specimen"], state, what, " (to verify)" if s["verify"] else "")


def run(a):
    ref = dt.date.fromisoformat(a.date)
    if os.path.isdir(a.source):
        items = [(os.path.basename(p)[:-4] if p.endswith(".txt") else os.path.basename(p), open(p, encoding="utf-8").read())
                 for p in sorted(os.path.join(a.source, f) for f in os.listdir(a.source)) if FILE_RE.search(os.path.basename(p))]
    else:
        items = [x for x in split_files(open(a.source, encoding="utf-8").read()) if FILE_RE.search(x[0]) or not x[0]]
    census = json.load(open(a.census, encoding="utf-8")) if a.census and a.census != "MISSING" else {"patients": []}
    by_sid, reports, verify, unparsed, files = {}, [], [], [], []
    # oldest file first, so a newer digest replaces the same SID
    for title, text in sorted(items, key=lambda x: (FILE_RE.search(x[0]).group(1) if FILE_RE.search(x[0]) else "")):
        sp, rep, ver, unp = parse_digest(title, text)
        files.append({"title": title, "specimens": len(sp), "report_rows": len(rep), "unparsed": len(unp)})
        for s in sp:
            key = s["sid"] or "%s|%s|%s" % (s["mrn"], s["collected"], s["specimen"])
            by_sid[key] = s
        reports += rep
        verify += [{"file": title, "line": v} for v in ver]
        unparsed += [{"file": title, "line": u} for u in unp]
    archived = read_archive(a.archive, ref)
    for s in archived:  # the archive sheet's finalised row wins
        prev = by_sid.get(s["sid"])
        # an archive row with no organism or result keeps those fields (empty), so every specimen has every field
        by_sid[s["sid"]] = {**s, **(prev or {}), **{k: v for k, v in s.items() if v not in ("", None, [])}}
    specimens = sorted(by_sid.values(), key=lambda s: (s.get("mrn") or "", s.get("collected") or ""), reverse=True)
    mrns = {str(c.get("mrn") or "").strip(): c for c in census.get("patients") or [] if c.get("mrn")}
    on = [s for s in specimens if s.get("mrn") in mrns]
    off = sorted({"%s (MRN %s)" % (s.get("patient", "?"), s.get("mrn") or "?") for s in specimens
                  if s.get("mrn") and s["mrn"] not in mrns and s.get("collected") and
                  s["collected"] >= (ref - dt.timedelta(days=7)).isoformat()})
    os.makedirs(a.out, exist_ok=True)
    json.dump({"date": a.date, "files": files, "specimens": specimens, "daily_report": reports, "verify": verify,
               "unparsed": unparsed, "off_census": off, "archive_rows": len(archived)},
              open(os.path.join(a.out, "cultures.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lines = []
    for mrn, c in mrns.items():
        mine = [s for s in on if s["mrn"] == mrn]
        if not mine:
            continue
        mine.sort(key=lambda s: (not s["final"], s.get("collected") or ""), reverse=False)
        lines.append("=== %s %s (%s, MRN %s): %d specimens" % (c.get("room") or "?", c.get("name") or "", c["pid"], mrn, len(mine)))
        lines += ["  %s%s  [SID %s, %s]" % ("" if s["final"] else "OPEN ", micro_line(s), s.get("sid") or "-", s.get("source") or "")
                  for s in mine]
    open(os.path.join(a.out, "cultures_packets.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("CULTURES OK: %d files, %d specimens (%d final, %d open, %d to verify), %d archive rows; %d for %d census "
          "patients, %d recent results off the census; %d Daily Report rows; %d lines not understood"
          % (len(files), len(specimens), sum(1 for s in specimens if s["final"]), sum(1 for s in specimens if not s["final"]),
             sum(1 for s in specimens if s.get("verify")), len(archived), len(on), len({s["mrn"] for s in on}), len(off),
             len(reports), len(unparsed)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source"); ap.add_argument("census"); ap.add_argument("out")
    ap.add_argument("--date", required=True); ap.add_argument("--archive", default="")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
