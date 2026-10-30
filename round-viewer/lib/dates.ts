// Dates as the team writes them: dd/mm, in Beirut time.
export const TZ = "Asia/Beirut";

/** Today in Beirut, ISO. */
export function todayIso(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** "2026-10-30" -> "30/10". */
export const ddmm = (iso: string | null | undefined) => (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : "");

/** "2026-10-30" -> "30/10/26". */
export const ddmmyy = (iso: string | null | undefined) => (iso ? `${ddmm(iso)}/${iso.slice(2, 4)}` : "");

/** A time as dd/mm HH:MM in Beirut. */
export function ddmmTime(d: Date): string {
  const p = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })
    .formatToParts(d);
  const g = (t: string) => p.find((x) => x.type === t)?.value ?? "";
  return `${g("day")}/${g("month")} ${g("hour")}:${g("minute")}`;
}

const valid = (y: number, m: number, d: number) => {
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
};
const iso = (y: number, m: number, d: number) => `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

/**
 * A date written in a cell -> ISO, or null. Accepts dd/mm/yy, dd/mm/yyyy, d-m-yy, ISO, and dd/mm alone (the year is
 * then the one that puts the date nearest before `ref`, allowing a month ahead for stop dates written early).
 * Only used to ORDER and DRAW; the text shown is always the cell as written.
 */
export function parseCellDate(text: string, ref?: string | null): string | null {
  const s = (text ?? "").trim().replace(/^~/, "");
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) return valid(+m[1], +m[2], +m[3]) ? iso(+m[1], +m[2], +m[3]) : null;
  m = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})\b/.exec(s);
  if (m) {
    const y = m[3].length === 2 ? 2000 + +m[3] : +m[3];
    return valid(y, +m[2], +m[1]) ? iso(y, +m[2], +m[1]) : null;
  }
  m = /^(\d{1,2})[/.](\d{1,2})$/.exec(s);
  if (m && ref) {
    const ry = +ref.slice(0, 4);
    for (const y of [ry, ry - 1, ry + 1]) {
      if (!valid(y, +m[2], +m[1])) continue;
      const cand = iso(y, +m[2], +m[1]);
      const days = (Date.parse(cand) - Date.parse(ref)) / 864e5;
      if (days <= 31 && days > -330) return cand;
    }
  }
  return null;
}
