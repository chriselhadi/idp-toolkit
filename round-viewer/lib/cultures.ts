// The "Finalised results" tab of the Daily Cultures Archive: one row per finalised specimen.
import { cleanMrn } from "./mrn";
import { parseCellDate } from "./dates";
import { cellText, findHeader, normHeader, type Grid } from "./sheet-rows";

export type CultureRow = {
  mrn: string;
  /** Every column of the row, by its header, as written. */
  cells: { header: string; value: string }[];
  collected: string; collectedIso: string | null;
  specimen: string; organism: string; result: string;
  astS: string; astR: string; astNotes: string;
};

const get = (cells: Map<string, string>, ...names: string[]) => {
  for (const n of names) {
    const v = cells.get(normHeader(n));
    if (v) return v;
  }
  return "";
};

export function parseCultures(grid: Grid): CultureRow[] {
  const h = findHeader(grid, ["MRN"]);
  if (!h) throw new Error("no header row with an MRN column");
  const headers = grid[h.row].map((x) => cellText(x));
  return grid.slice(h.row + 1)
    .filter((r) => r.some((c) => cellText(c)))
    .map((r) => {
      const byName = new Map<string, string>();
      headers.forEach((hd, i) => { if (hd) byName.set(normHeader(hd), cellText(r[i])); });
      const collected = get(byName, "Collected", "Collection date", "Date collected");
      return {
        mrn: cleanMrn(get(byName, "MRN")),
        cells: headers.map((hd, i) => ({ header: hd, value: cellText(r[i]) })).filter((c) => c.header && c.value),
        collected, collectedIso: parseCellDate(collected),
        specimen: get(byName, "Specimen"), organism: get(byName, "Organism"), result: get(byName, "Result"),
        astS: get(byName, "AST S"), astR: get(byName, "AST R"), astNotes: get(byName, "AST notes"),
      };
    });
}

/** Newest collection first; undated rows last, in sheet order. */
export function newestFirst(rows: CultureRow[]): CultureRow[] {
  return rows.map((r, i) => ({ r, i }))
    .sort((a, b) => (b.r.collectedIso ?? "").localeCompare(a.r.collectedIso ?? "") || a.i - b.i)
    .map((x) => x.r);
}
