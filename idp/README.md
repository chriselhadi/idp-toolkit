# idp-toolkit

Python toolkit for the ID service daily handout pipeline (LAU Medical Center AMS service). Contains no patient data and no document IDs: those live in the scheduled task prompt.

Runs in a fresh cloud container each morning: `bash bootstrap.sh <repo_url> /tmp/idp` clones this repo to `/tmp/idp/toolkit`.

## Scripts (`idp/`)

| Script | Role |
|---|---|
| `recover.py` | Pull an inline tool result out of the session transcript (`--needle`, `--gmail-raw`) so nothing is retyped |
| `parse_as.py` | Pharmacy AS list email (RAW) -> patients + orders; reads attachments and inline HTML tables |
| `parse_wards.py` | Ward handoff Google Docs (`read_file_content` spills) -> patient rows with HDR/MEDS/PENDINGS/SYNTHESIS cells; `--probe` shows shape |
| `parse_ams.py` | AMS workbook xlsx (`download_file_content` spill) -> archive blocks with fellow, last date, to-dos; `--probe` shows sheets |
| `match.py` | Membership, stable `pid`, room resolution, AMS audit, AS delta; writes `census.json`, `delta.json`, `flags.txt`, `packets.txt` |
| `validate_synth.py` | Grammar and voice checks on the hand-written `synth.py`; errors block the build |
| `render.py` | Column 1 text per patient (handout with `Update:`, recap without), day counts and pending ages computed |
| `build_html.py` / `verify_handout.py` | The handout as a printable HTML email body (since 14.09.2026, no attachment) and the check that the sent text matches |
| `verify_part.py` | Byte-level check of what arrived in Gmail (state parts) |
| `build_docx.py` / `verify_docx.py` / `split_docx.py` | Retired DOCX attachment path, kept for reference only |
| `report.py` | Run-status line, Delta Report text + HTML with the AMS block, flags for the handout email |
| `state_io.py` | `finalize` today's state, `pack` it into plain-text email parts, `verify-part` a sent part, `unpack` tomorrow |
| `preflight.py` | Pre-send checks on every deliverable (sizes, dashes, background:, state headers); `build.py` runs it last |
| `build.py` | Orchestrator: validate -> report -> render -> HTML handout -> state -> coverage -> recap + `handout_body.txt` |

## Dry run

`tests/run_e2e.sh` builds a fictional census end to end and must print `E2E OK`.
