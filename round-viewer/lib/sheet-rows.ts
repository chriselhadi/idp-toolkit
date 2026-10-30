// Turning one worksheet into rows of text, and finding columns by their header, never by position.
export type Grid = string[][];

/** Lower case, single spaces, no trailing colon: "Date of  Admission:" -> "date of admission". */
export const normHeader = (h: unknown) => String(h ?? "").trim().toLowerCase().replace(/\s+/g, " ").replace(/:$/, "");

/** The first row within the first `scan` rows that holds every one of `must`; its columns by header. */
export function findHeader(grid: Grid, must: string[], scan = 10): { row: number; col: Map<string, number> } | null {
  for (let r = 0; r < Math.min(scan, grid.length); r++) {
    const col = new Map<string, number>();
    grid[r].forEach((h, i) => {
      const k = normHeader(h);
      if (k && !col.has(k)) col.set(k, i);
    });
    if (must.every((m) => col.has(normHeader(m)))) return { row: r, col };
  }
  return null;
}

export const cellText = (v: unknown) => String(v ?? "").replace(/\r\n?/g, "\n").trim();
