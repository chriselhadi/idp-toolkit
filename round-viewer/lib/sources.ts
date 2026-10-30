// The three sources, read from Drive (read-only) and cached for 10 minutes. Each loader returns its data or an
// error message naming the source, so one unreadable file never blanks the rest of a screen.
import "server-only";
import * as XLSX from "xlsx";
import { cached } from "./cache";
import { downloadText, downloadWorkbook, fileMeta, listFiles, quote, type DriveFile } from "./google";
import { ROUND_FILE_RE, parseRound, type RoundDay } from "./round";
import { parseCultures, type CultureRow } from "./cultures";
import { blocksFromSheet, withoutHistoryCopies, type AmsBlock } from "./ams";
import type { Grid } from "./sheet-rows";

const IDP_DATA = process.env.IDP_DATA_FOLDER_ID || "1kNvxUpXlgXFFjcL9v_76arZeZPq9chQC";
const CULTURES_FOLDER = process.env.CULTURES_FOLDER_ID || "1rJ7F0-t_28RvROKJ66OvnU1TmdaxT2yB";
const CULTURES_NAME = "Daily Cultures Archive";
const CULTURES_TAB = "Finalised results";
const AMS_2024_ID = process.env.AMS_2024_2025_FILE_ID || "1_VOfykZ7ePRx-Y9563XNIka5FXTiWbqO";
const REGISTER_ID = process.env.REGISTER_FILE_ID || "1fbnZdqW0U_L19kcvIG47CvUOM90w9YxMA-DQjRrRRxM";

export type Loaded<T> = { ok: true; data: T } | { ok: false; source: string; error: string };

async function attempt<T>(source: string, load: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { ok: true, data: await load() };
  } catch (e) {
    return { ok: false, source, error: e instanceof Error ? e.message : String(e) };
  }
}

const gridOf = (ws: XLSX.WorkSheet): Grid =>
  XLSX.utils.sheet_to_json<string[]>(ws, { header: 1, raw: false, defval: "", blankrows: true }) as Grid;

const readBook = async (f: DriveFile) => XLSX.read(new Uint8Array(await downloadWorkbook(f)), { type: "array", dense: true });

// ---- round files -------------------------------------------------------------------------------------------------

export type RoundFile = { date: string; id: string };

export function roundFiles(): Promise<Loaded<RoundFile[]>> {
  return attempt("IDP Round files (IDP_Data)", () => cached("round-files", async () => {
    const files = await listFiles(`'${IDP_DATA}' in parents and name contains 'IDP Round ' and trashed = false`);
    return files.flatMap((f) => {
      const m = ROUND_FILE_RE.exec(f.name);
      return m ? [{ date: m[1], id: f.id }] : [];
    }).sort((a, b) => b.date.localeCompare(a.date));
  }));
}

/** The round of `date`, or the newest one. */
export async function roundDay(date?: string | null): Promise<Loaded<RoundDay | null>> {
  const files = await roundFiles();
  if (!files.ok) return files;
  const f = date ? files.data.find((x) => x.date === date) : files.data[0];
  if (!f) {
    return date
      ? { ok: false, source: `IDP Round ${date}.json`, error: "no round file for that date" }
      : { ok: true, data: null };
  }
  return attempt(`IDP Round ${f.date}.json`, () => cached(`round:${f.id}`, async () => parseRound(JSON.parse(await downloadText(f.id)))));
}

// ---- cultures ----------------------------------------------------------------------------------------------------

export function cultures(): Promise<Loaded<CultureRow[]>> {
  return attempt(`${CULTURES_NAME} (${CULTURES_TAB})`, () => cached("cultures", async () => {
    const [file] = await listFiles(`'${CULTURES_FOLDER}' in parents and name = '${quote(CULTURES_NAME)}' and trashed = false`);
    if (!file) throw new Error("not found in its folder");
    const wb = await readBook(file);
    const ws = wb.Sheets[CULTURES_TAB];
    if (!ws) throw new Error(`no tab named "${CULTURES_TAB}"`);
    return parseCultures(gridOf(ws));
  }));
}

// ---- AMS workbooks and the register ------------------------------------------------------------------------------

async function amsFile2025(): Promise<DriveFile> {
  if (process.env.AMS_2025_2026_FILE_ID) return fileMeta(process.env.AMS_2025_2026_FILE_ID);
  const hits = (await listFiles("name contains '2025_2026' and name contains 'cleaned_in_original_format' and trashed = false"))
    .filter((f) => /^LAU_AMS_.*2025_2026_cleaned_in_original_format\.xlsx$/i.test(f.name));
  if (!hits.length) throw new Error("no file named LAU_AMS_…2025_2026_cleaned_in_original_format.xlsx");
  return hits.sort((a, b) => b.modifiedTime.localeCompare(a.modifiedTime))[0];
}

async function blocksOfBook(file: DriveFile, label: string, onlyTabs?: string[]): Promise<AmsBlock[]> {
  const wb = await readBook(file);
  const out: AmsBlock[] = [];
  for (const tab of wb.SheetNames) {
    if (onlyTabs && !onlyTabs.some((t) => t.toLowerCase() === tab.trim().toLowerCase())) continue;
    const b = blocksFromSheet(gridOf(wb.Sheets[tab]), label, tab, !!onlyTabs);
    if (b) out.push(...b);
  }
  return out;
}

export type AmsLoad = { blocks: AmsBlock[]; problems: { source: string; error: string }[] };

/** Every admission block from the two workbooks and the register, History copies of workbook blocks removed. */
export function amsBlocks(): Promise<AmsLoad> {
  return cached("ams", async () => {
    const parts = await Promise.all([
      attempt("LAU_AMS_2024_2025 workbook", async () => blocksOfBook(await fileMeta(AMS_2024_ID), "AMS 2024-2025")),
      attempt("LAU_AMS_2025_2026 workbook", async () => blocksOfBook(await amsFile2025(), "AMS 2025-2026")),
      attempt("IDP Discharge Register (Register, History)", async () => blocksOfBook(await fileMeta(REGISTER_ID), "IDP Discharge Register", ["Register", "History"])),
    ]);
    const blocks: AmsBlock[] = [];
    const problems: { source: string; error: string }[] = [];
    for (const p of parts) p.ok ? blocks.push(...p.data) : problems.push({ source: p.source, error: p.error });
    return { blocks: withoutHistoryCopies(blocks), problems };
  });
}
