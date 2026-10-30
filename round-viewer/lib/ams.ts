// Admission blocks from the AMS workbooks and the IDP Discharge Register.
//
// Workbook tabs (one per month): a header row, then one block of rows per admission. The block's first row carries
// the patient (Pt name and/or MRN); the rows under it continue the antibiotic, culture and plan columns.
// Register tabs (Register, History): the same columns preceded by Key and Status; a row holding --- ends a block,
// and a new Key starts one. Everything is kept as written: no cell is reinterpreted, only grouped.
import { cleanMrn } from "./mrn";
import { parseCellDate } from "./dates";
import { cellText, findHeader, normHeader, type Grid } from "./sheet-rows";

export const AMS_COLUMNS = [
  "FELLOW", "Plan", "Plan Date", "Pt name", "MRN", "Age", "Room", "weight", "Creatinine", "CrCl", "Date of Admission",
  "Date of ID Consultation", "Chief complaint", "PMH", "Active Issues", "last hospitalization", "Abx history", "Imaging",
  "Pertinent labs", "Indication/ID Diagnosis", "Actual antibiotics", "Date started", "Date ended", "Released by ID",
  "Duration advice", "Attending", "Lines", "Discharge Abx", "Culture results/Notes", "Preliminary Results", "Organism",
  "Antibiogram", "notes",
] as const;
type Col = (typeof AMS_COLUMNS)[number];

/** The per-row column groups: one antibiotic, one culture, one plan entry per row. */
const ABX: Col[] = ["Indication/ID Diagnosis", "Actual antibiotics", "Date started", "Date ended", "Released by ID", "Duration advice"];
const CULT: Col[] = ["Culture results/Notes", "Preliminary Results", "Organism", "Antibiogram"];
const PLAN: Col[] = ["Plan", "Plan Date"];
/** Columns that describe the patient or the stay as a whole. */
export const STAY_FIELDS: Col[] = ["FELLOW", "Attending", "Age", "Room", "weight", "Creatinine", "CrCl", "Date of Admission",
  "Date of ID Consultation", "Chief complaint", "PMH", "Active Issues", "last hospitalization", "Abx history", "Imaging",
  "Pertinent labs", "Lines", "Discharge Abx", "notes"];

export type AmsBlock = {
  source: string;          // workbook or sheet label
  tab: string;
  row: number;             // 1-based sheet row of the block's first row
  key: string; status: string; // register only
  name: string; mrn: string;
  admissionIso: string | null;
  /** STAY_FIELDS with every non-empty value found in the block, top to bottom. */
  stay: Partial<Record<Col, string[]>>;
  abx: Partial<Record<Col, string>>[];
  cultures: Partial<Record<Col, string>>[];
  plans: Partial<Record<Col, string>>[];
};

const isSeparator = (r: string[]) => r.some((c) => cellText(c) === "---") && r.every((c) => ["", "---"].includes(cellText(c)));

/** One worksheet -> its admission blocks. Returns null when the tab has no AMS header (a legend, a notes tab). */
export function blocksFromSheet(grid: Grid, source: string, tab: string, register = false): AmsBlock[] | null {
  const h = findHeader(grid, ["Pt name", "MRN"]);
  if (!h) return null;
  const at = (r: string[], c: string) => {
    const i = h.col.get(normHeader(c));
    return i == null ? "" : cellText(r[i]);
  };
  const out: AmsBlock[] = [];
  let cur: AmsBlock | null = null;
  const pick = (r: string[], cols: Col[]) => {
    const o: Partial<Record<Col, string>> = {};
    for (const c of cols) { const v = at(r, c); if (v) o[c] = v; }
    return Object.keys(o).length ? o : null;
  };

  grid.slice(h.row + 1).forEach((r, i) => {
    const sheetRow = h.row + 2 + i;
    if (isSeparator(r)) { cur = null; return; }
    if (!r.some((c) => cellText(c))) return;
    const key = register ? at(r, "Key") : "";
    const starts = register ? !!key && (!cur || key !== cur.key) : !!(at(r, "Pt name") || at(r, "MRN"));
    if (starts) {
      cur = {
        source, tab, row: sheetRow, key, status: register ? at(r, "Status") : "",
        name: at(r, "Pt name"), mrn: cleanMrn(at(r, "MRN") || (/MRN\s*([0-9' ]+)/i.exec(key)?.[1] ?? "")),
        admissionIso: null, stay: {}, abx: [], cultures: [], plans: [],
      };
      out.push(cur);
    }
    if (!cur) return; // rows above the first patient belong to no admission
    const b: AmsBlock = cur;
    if (!b.name) b.name = at(r, "Pt name");
    if (!b.mrn) b.mrn = cleanMrn(at(r, "MRN"));
    for (const c of STAY_FIELDS) {
      const v = at(r, c);
      if (v) (b.stay[c] ??= []).push(v);
    }
    const a = pick(r, ABX); if (a) b.abx.push(a);
    const cu = pick(r, CULT); if (cu) b.cultures.push(cu);
    const p = pick(r, PLAN); if (p) b.plans.push(p);
  });
  for (const b of out) {
    b.admissionIso = parseCellDate(b.stay["Date of Admission"]?.[0] ?? "")
      ?? parseCellDate(b.stay["Date of ID Consultation"]?.[0] ?? "")
      ?? parseCellDate(b.key.split("|")[2]?.trim() ?? "");
  }
  return out;
}

/** "Historical (LAU_AMS_x.xlsx, Oct 2024, row 2)" -> its tab and row. */
export function historyOrigin(status: string): { tab: string; row: number } | null {
  const m = /^Historical \((.+?),\s*([^,]+),\s*row\s+(\d+)\)/i.exec(status.trim());
  return m ? { tab: m[2].trim(), row: +m[3] } : null;
}

/**
 * Drops History copies of blocks already read from the workbooks themselves: the same tab and starting row (from the
 * copy's Status), or the same MRN and admission date. Register and workbook blocks are always kept.
 */
export function withoutHistoryCopies(blocks: AmsBlock[]): AmsBlock[] {
  const fromBooks = blocks.filter((b) => !b.key);
  const at = new Set(fromBooks.map((b) => `${b.tab.trim().toLowerCase()}|${b.row}|${b.mrn}`));
  const stay = new Set(fromBooks.filter((b) => b.mrn && b.admissionIso).map((b) => `${b.mrn}|${b.admissionIso}`));
  return blocks.filter((b) => {
    if (b.tab.toLowerCase() !== "history") return true;
    const o = historyOrigin(b.status);
    if (o && at.has(`${o.tab.toLowerCase()}|${o.row}|${b.mrn}`)) return false;
    if (b.mrn && b.admissionIso && stay.has(`${b.mrn}|${b.admissionIso}`)) return false;
    return true;
  });
}

/** Newest admission first; undated blocks last. */
export function newestStayFirst(blocks: AmsBlock[]): AmsBlock[] {
  return blocks.slice().sort((a, b) => (b.admissionIso ?? "").localeCompare(a.admissionIso ?? ""));
}
