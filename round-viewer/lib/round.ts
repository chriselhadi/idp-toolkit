// The day's round, "IDP Round YYYY-MM-DD.json", exactly as the pipeline writes it (the recap email's content).
export type RoundPatient = {
  pid: string; mrn: string; room: string; name: string;
  new?: boolean; uc?: boolean; initials?: string;
  one_liner?: string; updates_id?: string[]; updates_other?: string[]; im?: string[];
  issues?: { dx: string; abx?: string[] }[];
  abx_other?: string[]; micro_recap?: string; status?: string;
  pendings?: string[]; id_plan?: string; conflicts?: string[]; not_applied?: string[];
};
export type RoundGroup = { header: string; patients: RoundPatient[] };
export type RoundDay = { date: string; groups: RoundGroup[]; off_list?: { room: string; name: string; line: string }[] };

export const ROUND_FILE_RE = /^IDP Round (\d{4}-\d{2}-\d{2})\.json$/;

const arr = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x) => typeof x === "string") : []);
const str = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));

/** The file's JSON -> a round day, keeping the file's order. Throws on a file that is not a round. */
export function parseRound(json: unknown): RoundDay {
  const j = json as any;
  if (!j || typeof j !== "object" || !Array.isArray(j.groups)) throw new Error("the file has no groups");
  return {
    date: str(j.date),
    groups: j.groups.map((g: any) => ({
      header: str(g?.header),
      patients: (Array.isArray(g?.patients) ? g.patients : []).map((p: any): RoundPatient => ({
        pid: str(p?.pid), mrn: str(p?.mrn), room: str(p?.room), name: str(p?.name),
        new: !!p?.new, uc: !!p?.uc, initials: str(p?.initials),
        one_liner: str(p?.one_liner), updates_id: arr(p?.updates_id), updates_other: arr(p?.updates_other), im: arr(p?.im),
        issues: (Array.isArray(p?.issues) ? p.issues : []).map((i: any) => ({ dx: str(i?.dx), abx: arr(i?.abx) })),
        abx_other: arr(p?.abx_other), micro_recap: str(p?.micro_recap), status: str(p?.status),
        pendings: arr(p?.pendings), id_plan: str(p?.id_plan), conflicts: arr(p?.conflicts), not_applied: arr(p?.not_applied),
      })),
    })),
    off_list: (Array.isArray(j.off_list) ? j.off_list : []).map((o: any) => ({ room: str(o?.room), name: str(o?.name), line: str(o?.line) })),
  };
}

/** Every antibiotic line a patient has today, issue lines first. */
export const roundAbxLines = (p: RoundPatient) => [...(p.issues ?? []).flatMap((i) => i.abx ?? []), ...(p.abx_other ?? [])];
