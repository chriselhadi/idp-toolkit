// Antibiotic lines as the round writes them: "Mero IV q8h 29/10-" or "Cefazolin IV q8h 24/10-26/10, 28/10-".
// The last date range decides: open ("29/10-") = still running; closed ("27/10-29/10") = stopped.
import { parseCellDate } from "./dates";

const RANGE_RE = /(~?\d{1,2}\/\d{1,2})\s*-\s*(~?\d{1,2}\/\d{1,2})?/g;

export type AbxLine = {
  text: string;
  drug: string;
  /** Every date range in the line, in order: start and end as written ("" end = open). */
  ranges: { start: string; end: string }[];
  /** The last range is closed: the drug has stopped. */
  stopped: boolean;
  running: boolean;
};

export function parseAbxLine(text: string): AbxLine {
  const ranges = [...text.matchAll(RANGE_RE)].map((m) => ({ start: m[1], end: m[2] ?? "" }));
  const firstDate = text.search(/~?\d{1,2}\/\d{1,2}/);
  const head = (firstDate > 0 ? text.slice(0, firstDate) : text).trim();
  const drug = head.split(/\s+/)[0] ?? "";
  const last = ranges[ranges.length - 1];
  return { text, drug, ranges, stopped: !!last && !!last.end, running: !!last && !last.end };
}

/** A line's ranges as ISO dates for the timeline; the year comes from the round's date. Open ranges run to `ref`. */
export function abxSpans(line: AbxLine, ref: string): { start: string; end: string; open: boolean }[] {
  const out: { start: string; end: string; open: boolean }[] = [];
  for (const r of line.ranges) {
    const s = parseCellDate(r.start, ref);
    if (!s) continue;
    const e = r.end ? parseCellDate(r.end, ref) : ref;
    if (!e || e < s) continue;
    out.push({ start: s, end: e, open: !r.end });
  }
  return out;
}
