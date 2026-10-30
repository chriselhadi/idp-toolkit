# ID round viewer

A read-only web app for the ID stewardship team at LAU Medical Center: today's ward round and each patient's full
history, on a phone. It never writes anything. It reads Google Drive with a service account that only has the
`drive.readonly` scope, and every page sits behind Google sign-in limited to the team.

## Screens

- **Round** (`/`): the newest `IDP Round YYYY-MM-DD.json` from IDP_Data, exactly as stored: groups and patients in file
  order, the recap email's fields in the email's order. Stopped antibiotics (last date range closed) are struck through;
  `!!` lines are red. Search by name, room or MRN. "Not on the ID list" at the bottom.
- **Patient** (`/patient/<MRN>`): the round card, then every finalised culture for the MRN (newest first, resistant
  results highlighted), every admission block from the two AMS workbooks and the register's Register and History tabs
  (newest first, collapsible), and an antibiotic timeline with one bar per drug.
- **Days** (`/days`): any earlier round file.

## Sources (read only)

| Source | Where | How |
|---|---|---|
| Round | IDP_Data folder `1kNvxUpXlgXFFjcL9v_76arZeZPq9chQC`, `IDP Round YYYY-MM-DD.json` | JSON |
| Cultures | "Daily Cultures Archive" in folder `1rJ7F0-t_28RvROKJ66OvnU1TmdaxT2yB`, tab "Finalised results" | exported as .xlsx, read with SheetJS, columns by header |
| AMS 2024-2025 | `1_VOfykZ7ePRx-Y9563XNIka5FXTiWbqO` | .xlsx, every monthly tab |
| AMS 2025-2026 | found by name `LAU_AMS_…2025_2026_cleaned_in_original_format.xlsx` | .xlsx, every monthly tab |
| Register | "IDP Discharge Register" `1fbnZdqW0U_L19kcvIG47CvUOM90w9YxMA-DQjRrRRxM`, tabs Register and History | exported as .xlsx |

History copies of blocks that are also read from the workbooks themselves are dropped (same tab and row from the
copy's Status, or same MRN and admission date), so an admission is not listed twice.

Joining is on MRN only: leading apostrophes, spaces and leading zeros removed. When no MRN matches exactly, an MRN with
one extra trailing digit is accepted and labelled "matched by MRN prefix". Never by name.

Drive reads are cached in memory for 10 minutes; **Refresh** clears the cache. A source that cannot be read is named in
a banner and the rest of the page still renders.

## Setup

1. **Service account (Drive access).** Google Cloud Console → IAM → Service accounts → create one, then Keys → Add key →
   JSON. Enable the Google Drive API in the same project. Share each source above, as **Viewer**, with the service
   account's email (sharing the two folders covers the files inside them).
2. **Sign-in client.** Google Auth Platform → Clients → create a "Web application" client. Authorized redirect URI:
   `https://<the app's domain>/api/auth/callback/google`.
3. **Vercel environment variables** (see `.env.example`): `GOOGLE_SERVICE_ACCOUNT_EMAIL`,
   `GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY` (the `private_key` from the JSON, `\n` escapes are fine), `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, `NEXTAUTH_SECRET` (`openssl rand -base64 32`), and `ALLOWED_EMAILS` and/or
   `ALLOWED_DOMAINS`. Nobody can sign in until one of the last two is set.
4. Vercel project root directory: `round-viewer`.

## Development

```
npm install
npm test          # parsers, on invented data only
npm run build
```

Tests use invented patients only. Never commit real patient data, exports or `.env` files.
