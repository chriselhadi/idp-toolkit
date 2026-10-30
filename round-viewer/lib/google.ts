// Read-only Google Drive access. Two ways in, from the deployment's environment:
//   1. The AMS Register app's access (preferred when set): the same OAuth client and refresh token,
//      GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN. That token also carries other scopes;
//      this app only ever sends GET requests to Drive, so it reads and never writes.
//   2. A service account limited to drive.readonly: GOOGLE_SERVICE_ACCOUNT_EMAIL, GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY.
import { createSign } from "node:crypto";
import "server-only";

const SCOPE = "https://www.googleapis.com/auth/drive.readonly";
const TOKEN_URL = "https://oauth2.googleapis.com/token";
const DRIVE = "https://www.googleapis.com/drive/v3";

let token: { value: string; expires: number } | null = null;

const b64url = (s: string | Buffer) => Buffer.from(s).toString("base64url");

async function exchange(body: URLSearchParams, who: string): Promise<string> {
  const res = await fetch(TOKEN_URL, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body, cache: "no-store",
  });
  if (!res.ok) throw new Error(`Google refused ${who} (${res.status}).`);
  const j = (await res.json()) as { access_token: string; expires_in: number };
  token = { value: j.access_token, expires: Date.now() + j.expires_in * 1000 };
  return token.value;
}

async function accessToken(): Promise<string> {
  if (token && token.expires > Date.now() + 60_000) return token.value;
  const { GOOGLE_CLIENT_ID: id, GOOGLE_CLIENT_SECRET: secret, GOOGLE_REFRESH_TOKEN: refresh } = process.env;
  if (id && secret && refresh) {
    return exchange(new URLSearchParams({ client_id: id, client_secret: secret, refresh_token: refresh, grant_type: "refresh_token" }),
      "the app's Drive access key (GOOGLE_REFRESH_TOKEN)");
  }
  const email = process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL;
  const key = process.env.GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY?.replace(/\\n/g, "\n");
  if (!email || !key) throw new Error("Drive access is not configured: set GOOGLE_REFRESH_TOKEN (with GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET), or a service account.");
  const now = Math.floor(Date.now() / 1000);
  const head = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claims = b64url(JSON.stringify({ iss: email, scope: SCOPE, aud: TOKEN_URL, iat: now, exp: now + 3600 }));
  const signer = createSign("RSA-SHA256");
  signer.update(`${head}.${claims}`);
  const assertion = `${head}.${claims}.${b64url(signer.sign(key))}`;
  return exchange(new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion }), "the service account");
}

async function drive(path: string): Promise<Response> {
  const res = await fetch(`${DRIVE}${path}`, { headers: { Authorization: `Bearer ${await accessToken()}` }, cache: "no-store" });
  if (!res.ok) {
    const why = res.status === 404 ? "not found, or not visible to the app's Google account" : `Drive error ${res.status}`;
    throw new Error(why);
  }
  return res;
}

export type DriveFile = { id: string; name: string; mimeType: string; modifiedTime: string };
const FIELDS = "files(id,name,mimeType,modifiedTime),nextPageToken";

/** Files matching a Drive query, every page. */
export async function listFiles(q: string): Promise<DriveFile[]> {
  const out: DriveFile[] = [];
  let page = "";
  for (let i = 0; i < 10; i++) {
    const res = await drive(`/files?q=${encodeURIComponent(q)}&fields=${encodeURIComponent(FIELDS)}&pageSize=1000`
      + `&supportsAllDrives=true&includeItemsFromAllDrives=true&orderBy=name${page ? `&pageToken=${page}` : ""}`);
    const j = (await res.json()) as { files: DriveFile[]; nextPageToken?: string };
    out.push(...j.files);
    if (!j.nextPageToken) break;
    page = j.nextPageToken;
  }
  return out;
}

export const quote = (s: string) => s.replace(/\\/g, "\\\\").replace(/'/g, "\\'");

export async function fileMeta(id: string): Promise<DriveFile> {
  const res = await drive(`/files/${id}?fields=id,name,mimeType,modifiedTime&supportsAllDrives=true`);
  return (await res.json()) as DriveFile;
}

export async function downloadText(id: string): Promise<string> {
  return (await drive(`/files/${id}?alt=media&supportsAllDrives=true`)).text();
}

const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** An .xlsx file's bytes, or a Google Sheet exported as .xlsx (every tab, unlike the CSV export). */
export async function downloadWorkbook(file: DriveFile): Promise<ArrayBuffer> {
  const path = file.mimeType === "application/vnd.google-apps.spreadsheet"
    ? `/files/${file.id}/export?mimeType=${encodeURIComponent(XLSX_MIME)}`
    : `/files/${file.id}?alt=media&supportsAllDrives=true`;
  return (await drive(path)).arrayBuffer();
}
