// Invented data only: no real patient, name or MRN.
import { describe, expect, test } from "vitest";
import * as XLSX from "xlsx";
import { cleanMrn, matchByMrn, mrnRelation } from "@/lib/mrn";
import { abxSpans, parseAbxLine } from "@/lib/abx";
import { parseCellDate, ddmm, todayIso } from "@/lib/dates";
import { parseRound, roundAbxLines } from "@/lib/round";
import { newestFirst, parseCultures } from "@/lib/cultures";
import { blocksFromSheet, historyOrigin, newestStayFirst, withoutHistoryCopies, AMS_COLUMNS } from "@/lib/ams";
import { buildTimeline } from "@/lib/timeline";
import { isAllowed } from "@/lib/auth";

describe("MRN", () => {
  test("cleaning", () => {
    expect(cleanMrn("'00900 123")).toBe("900123");
    expect(cleanMrn(900123)).toBe("900123");
    expect(cleanMrn("none")).toBe("");
    expect(cleanMrn("0")).toBe("0");
  });
  test("exact first; one extra trailing digit only when nothing matches exactly", () => {
    expect(mrnRelation("900123", "9001230")).toBe("prefix");
    expect(mrnRelation("900123", "90012")).toBeNull();
    const rows = [{ m: "9001234" }, { m: "900123" }];
    expect(matchByMrn("900123", rows, (r) => r.m)).toEqual([{ item: rows[1], match: "exact" }]);
    expect(matchByMrn("900123", [rows[0]], (r) => r.m)).toEqual([{ item: rows[0], match: "prefix" }]);
    expect(matchByMrn("900123", [{ m: "800123" }], (r) => r.m)).toEqual([]);
  });
});

describe("antibiotic lines", () => {
  test("open and closed last ranges", () => {
    expect(parseAbxLine("Mero IV q8h 29/10-")).toMatchObject({ drug: "Mero", running: true, stopped: false });
    expect(parseAbxLine("Cefazolin IV q8h 27/10-29/10")).toMatchObject({ stopped: true, running: false });
    expect(parseAbxLine("Vanco IV 20/10-22/10, 25/10-")).toMatchObject({ running: true, ranges: [{ start: "20/10", end: "22/10" }, { start: "25/10", end: "" }] });
    expect(parseAbxLine("Fluconazole PO")).toMatchObject({ running: false, stopped: false, ranges: [] });
  });
  test("spans take the round's year; a range across New Year", () => {
    expect(abxSpans(parseAbxLine("Mero 29/10-"), "2026-10-30")).toEqual([{ start: "2026-10-29", end: "2026-10-30", open: true }]);
    expect(abxSpans(parseAbxLine("Pip 28/12-02/01"), "2027-01-03")).toEqual([{ start: "2026-12-28", end: "2027-01-02", open: false }]);
  });
});

describe("dates", () => {
  test("cells", () => {
    expect(parseCellDate("21/10/26")).toBe("2026-10-21");
    expect(parseCellDate("21/10/2026")).toBe("2026-10-21");
    expect(parseCellDate("31/02/26")).toBeNull();
    expect(parseCellDate("Ongoing")).toBeNull();
    expect(parseCellDate("05/11", "2026-10-30")).toBe("2026-11-05");
    expect(ddmm("2026-10-30")).toBe("30/10");
  });
  test("today is Beirut's", () => {
    expect(todayIso(new Date("2026-10-30T22:30:00Z"))).toBe("2026-10-31");
  });
});

const ROUND = {
  date: "2026-10-30",
  groups: [
    { header: "4th floor A", patients: [{ pid: "P0901", mrn: "'00900123", room: "707B", name: "Testa Patienta", new: true, uc: false, initials: "ZZ",
      one_liner: "70F, invented", updates_id: ["afebrile"], issues: [{ dx: "UTI", abx: ["Mero IV q8h 29/10-"] }], abx_other: ["Cefazolin IV 27/10-29/10"],
      conflicts: ["!! abx differs"] }] },
    { header: "ICU", patients: [] },
  ],
  off_list: [{ room: "512", name: "Fakeo Nobody", line: "seen once" }],
};

describe("round file", () => {
  test("kept in file order, fields as stored", () => {
    const r = parseRound(ROUND);
    expect(r.groups.map((g) => g.header)).toEqual(["4th floor A", "ICU"]);
    expect(r.groups[0].patients[0].mrn).toBe("'00900123");
    expect(roundAbxLines(r.groups[0].patients[0])).toEqual(["Mero IV q8h 29/10-", "Cefazolin IV 27/10-29/10"]);
    expect(r.off_list).toHaveLength(1);
    expect(() => parseRound({ date: "x" })).toThrow();
  });
});

describe("cultures", () => {
  const grid = [
    ["SID", "Patient", "DOB", "MRN", "Unit", "Specimen", "Collected", "Status", "Result", "Organism", "AST S", "AST R", "AST notes"],
    ["1", "Testa Patienta", "", "900123", "7", "urine", "21/10/26", "Final", "", "E. coli", "Meropenem, Amikacin", "Ceftriaxone, Cipro", "ESBL"],
    ["2", "Testa Patienta", "", "'0900123", "7", "blood", "25/10/26", "Final", "No growth", "", "", "", ""],
    ["3", "Fakeo Nobody", "", "800001", "ICU", "sputum", "20/10/26", "Final", "", "P. aeruginosa", "", "", ""],
  ];
  test("columns by header, newest first", () => {
    const rows = parseCultures(grid);
    const mine = matchByMrn("900123", rows, (r) => r.mrn).map((x) => x.item);
    expect(mine).toHaveLength(2);
    expect(newestFirst(mine).map((r) => r.specimen)).toEqual(["blood", "urine"]);
    expect(mine[0]).toMatchObject({ organism: "E. coli", astR: "Ceftriaxone, Cipro" });
  });
  test("columns moved: still found by name", () => {
    const moved = grid.map((r) => [r[3], ...r.slice(0, 3), ...r.slice(4)]);
    expect(parseCultures(moved)[0].organism).toBe("E. coli");
  });
});

// An AMS month tab: header, then blocks; the first row carries the patient.
const C = (name: string) => AMS_COLUMNS.indexOf(name as any);
const row = (vals: Record<string, string>) => { const r = Array(AMS_COLUMNS.length).fill(""); for (const [k, v] of Object.entries(vals)) r[C(k)] = v; return r; };
const tab = [
  ["", "AMS Oct 2026"],
  [...AMS_COLUMNS],
  row({ "FELLOW": "ZZ", "Pt name": "Testa Patienta", "MRN": "9001230", "Date of Admission": "20/10/26", "Indication/ID Diagnosis": "UTI", "Actual antibiotics": "Meropenem IV", "Date started": "21/10/26", "Date ended": "28/10/26", "Culture results/Notes": "21/10 urine", "Organism": "E. coli" }),
  row({ "Actual antibiotics": "Amikacin IV", "Date started": "21/10/26", "Date ended": "23/10/26", "Plan": "stop amikacin", "Plan Date": "23/10" }),
  Array(AMS_COLUMNS.length).fill(""),
  row({ "Pt name": "Fakeo Nobody", "MRN": "800001", "Date of Admission": "02/10/26" }),
];

describe("AMS blocks", () => {
  test("a block per patient row, continuation rows kept", () => {
    const b = blocksFromSheet(tab, "AMS 2025-2026", "Oct 2026")!;
    expect(b).toHaveLength(2);
    expect(b[0]).toMatchObject({ name: "Testa Patienta", mrn: "9001230", row: 3, admissionIso: "2026-10-20" });
    expect(b[0].abx.map((a) => a["Actual antibiotics"])).toEqual(["Meropenem IV", "Amikacin IV"]);
    expect(b[0].plans).toEqual([{ "Plan": "stop amikacin", "Plan Date": "23/10" }]);
    expect(b[0].cultures[0]).toMatchObject({ "Organism": "E. coli" });
    expect(blocksFromSheet([["notes"], ["x"]], "x", "Legend")).toBeNull();
  });

  test("the extra-digit MRN is found by prefix, and labelled", () => {
    const b = blocksFromSheet(tab, "AMS", "Oct 2026")!;
    expect(matchByMrn("900123", b, (x) => x.mrn).map((m) => m.match)).toEqual(["prefix"]);
  });

  const reg = [
    ["Key", "Status", ...AMS_COLUMNS],
    ["MRN 900123 | P0901 | 29/10/26 to (open)", "Active", ...row({ "Pt name": "Testa Patienta", "MRN": "900123", "Date of Admission": "29/10/26", "Actual antibiotics": "Meropenem IV", "Date started": "29/10/26" })],
    ["MRN 900123 | P0901 | 29/10/26 to (open)", "", ...row({ "Actual antibiotics": "Vancomycin IV", "Date started": "29/10/26", "Date ended": "30/10/26" })],
    ["---"],
    ["MRN 900123 | P0610 | 20/10/26 to 28/10/26", "Historical (LAU_AMS_x.xlsx, Oct 2026, row 3)", ...row({ "Pt name": "Testa Patienta", "MRN": "900123", "Date of Admission": "20/10/26" })],
    ["---"],
  ];

  test("register blocks: Key starts, --- ends; History copies of workbook blocks dropped", () => {
    const r = blocksFromSheet(reg, "IDP Discharge Register", "Register", true)!;
    expect(r.map((b) => [b.status, b.abx.length])).toEqual([["Active", 2], ["Historical (LAU_AMS_x.xlsx, Oct 2026, row 3)", 0]]);
    const h = r.map((b, i) => (i === 1 ? { ...b, tab: "History" } : b));
    expect(historyOrigin(h[1].status)).toEqual({ tab: "Oct 2026", row: 3 });
    const books = blocksFromSheet(tab, "AMS 2025-2026", "Oct 2026")!.map((b) => ({ ...b, mrn: b.mrn === "9001230" ? "900123" : b.mrn }));
    const all = withoutHistoryCopies([...books, ...h]);
    expect(all.filter((b) => b.tab === "History")).toHaveLength(0);
    expect(newestStayFirst(all)[0].status).toBe("Active");
  });

  test("timeline: a track per drug, open only in an Active block or a running round line", () => {
    const r = blocksFromSheet(reg, "R", "Register", true)!;
    const books = blocksFromSheet(tab, "B", "Oct 2026")!;
    const t = buildTimeline([...r, ...books], ["Mero IV q8h 29/10-"], "2026-10-30", "2026-10-30");
    const mero = t.tracks.find((x) => x.drug === "Meropenem")!;
    expect(mero.segments.some((s) => s.open && s.end === "2026-10-30")).toBe(true);
    expect(t.tracks.find((x) => x.drug === "Mero")).toBeDefined();
    expect(t.min).toBe("2026-10-21");
  });
});

describe("who may sign in", () => {
  test("listed addresses and domains only; nobody when both lists are empty", () => {
    expect(isAllowed("a.b@lau.edu", [], ["lau.edu"])).toBe(true);
    expect(isAllowed("A.B@LAU.EDU", [], ["lau.edu"])).toBe(true);
    expect(isAllowed("x@gmail.com", ["x@gmail.com"], [])).toBe(true);
    expect(isAllowed("y@gmail.com", ["x@gmail.com"], ["lau.edu"])).toBe(false);
    expect(isAllowed("x@notlau.edu", [], ["lau.edu"])).toBe(false);
    expect(isAllowed("x@gmail.com", [], [])).toBe(false);
  });
});

describe("xlsx round-trip", () => {
  test("a workbook tab read as text keeps dd/mm/yy cells as typed", () => {
    const ws = XLSX.utils.aoa_to_sheet([["MRN", "Collected"], ["'900123", "21/10/26"]]);
    const grid = XLSX.utils.sheet_to_json<string[]>(ws, { header: 1, raw: false, defval: "" });
    expect(grid[1]).toEqual(["'900123", "21/10/26"]);
  });
});
