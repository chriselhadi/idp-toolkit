// One track per drug across every admission: spans from the AMS blocks (Date started, Date ended) and today's round
// lines. Only used for DRAWING; each segment keeps the text it came from.
import { abxSpans, parseAbxLine } from "./abx";
import { parseCellDate } from "./dates";
import type { AmsBlock } from "./ams";

export type Segment = { start: string; end: string; open: boolean; from: string };
export type Track = { drug: string; segments: Segment[] };
export type Timeline = { tracks: Track[]; min: string; max: string; undrawn: number };

/** "Meropenem 1 g IV q8h" -> key "meropenem", label "Meropenem". */
function drugOf(text: string): { key: string; label: string } | null {
  const m = /[A-Za-z][A-Za-z-]*/.exec(text ?? "");
  return m ? { key: m[0].toLowerCase(), label: m[0][0].toUpperCase() + m[0].slice(1) } : null;
}

export function buildTimeline(blocks: AmsBlock[], roundLines: string[], roundDate: string | null, today: string): Timeline {
  const tracks = new Map<string, Track>();
  let undrawn = 0;
  const add = (drug: { key: string; label: string }, seg: Segment) => {
    if (!tracks.has(drug.key)) tracks.set(drug.key, { drug: drug.label, segments: [] });
    tracks.get(drug.key)!.segments.push(seg);
  };

  for (const b of blocks) {
    const ref = b.admissionIso ?? today;
    const stillOpen = /^active/i.test(b.status);
    for (const row of b.abx) {
      const text = row["Actual antibiotics"] ?? "";
      const drug = drugOf(text);
      const start = parseCellDate(row["Date started"] ?? "", ref);
      if (!drug || !start) { if (text) undrawn++; continue; }
      const endText = row["Date ended"] ?? "";
      let end = parseCellDate(endText, start);
      let open = false;
      // No stop date: still running only in a block the register marks Active; otherwise drawn as its start day.
      if (!end && stillOpen) { end = today; open = true; }
      if (!end || end < start) end = start;
      add(drug, { start, end, open, from: `${b.source} · ${b.tab}: ${text} ${row["Date started"] ?? ""} to ${endText || "?"}` });
    }
  }
  if (roundDate) {
    for (const line of roundLines) {
      const a = parseAbxLine(line);
      const drug = drugOf(a.drug);
      const spans = abxSpans(a, roundDate);
      if (!drug || !spans.length) { undrawn++; continue; }
      for (const s of spans) add(drug, { ...s, from: `Round ${roundDate}: ${line}` });
    }
  }
  const all = [...tracks.values()].flatMap((t) => t.segments);
  const min = all.reduce((m, s) => (s.start < m ? s.start : m), all[0]?.start ?? today);
  const max = all.reduce((m, s) => (s.end > m ? s.end : m), all[0]?.end ?? today);
  const list = [...tracks.values()].sort((a, b) =>
    a.segments.reduce((m, s) => (s.start < m ? s.start : m), "9999").localeCompare(b.segments.reduce((m, s) => (s.start < m ? s.start : m), "9999")));
  return { tracks: list, min, max, undrawn };
}
