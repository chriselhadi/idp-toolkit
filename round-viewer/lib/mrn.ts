// MRNs as the sources store them: some with a leading apostrophe (forced text), spaces, leading zeros, and some
// AMS rows with one extra trailing digit (6532350 for 653235). Joining is on MRN only, never on a name.

/** "'00653 235" -> "653235". Anything without a digit -> "". */
export function cleanMrn(raw: unknown): string {
  const s = String(raw ?? "").trim().replace(/^'+/, "").replace(/\s+/g, "");
  if (!/\d/.test(s)) return "";
  return s.replace(/^0+(?=\d)/, "");
}

export type MrnMatch = "exact" | "prefix";

/**
 * How a stored MRN relates to the patient's: "exact", "prefix" (the stored one is the patient's with one digit
 * added at the end), or null. A prefix link is only offered when the caller found no exact one.
 */
export function mrnRelation(patient: string, stored: string): MrnMatch | null {
  if (!patient || !stored) return null;
  if (stored === patient) return "exact";
  if (stored.length === patient.length + 1 && stored.slice(0, -1) === patient) return "prefix";
  return null;
}

/** The items for one patient: exact matches, or, only if there are none, the prefix matches, labelled. */
export function matchByMrn<T>(patient: string, items: T[], mrnOf: (t: T) => string): { item: T; match: MrnMatch }[] {
  const exact = items.filter((t) => mrnRelation(patient, mrnOf(t)) === "exact");
  if (exact.length) return exact.map((item) => ({ item, match: "exact" as const }));
  return items.filter((t) => mrnRelation(patient, mrnOf(t)) === "prefix").map((item) => ({ item, match: "prefix" as const }));
}
