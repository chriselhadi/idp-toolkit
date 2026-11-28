# ID Daily Pipeline: send + verify procedure

Changed 08.09.2026 after a morning that pushed ~1.1 MB of text through the model,
almost all of it mechanical copying. Changed again 14.09.2026: handout as HTML email
body (no attachment ever again), compact recap, delta baseline = last SENT delta.

## Stage commands (28.11.2026): what the run executes

Since 28.11.2026 the daily run no longer types about forty commands by hand. The agent keeps every
MCP read and write (Gmail, Drive, Sheets) and the judgment (`in/roster.txt`, `synth_delta.py`,
`out/roster_out.txt`, the replies). Everything local runs through three stage commands, from `/tmp/idp`:

```
T=/tmp/idp/toolkit/idp/idp
python3 $T/run.py prep  --date YYYY-MM-DD [--as-missing] [--allow-orphans]
python3 $T/run.py build --date YYYY-MM-DD --long-date "28 November 2026" [--coverage-warn]
python3 $T/run.py post  --date YYYY-MM-DD
```

Each step prints one line (`  <step>: <result>`), its full output goes to `out/stage_logs/`. The first
failed gate prints `STAGE FAIL: <step>: <reason>` and exits 1: fix the input it names and run the
stage again (every stage can be re-run). A finished stage ends with `STAGE OK: <stage> <date>`.

**prep** (after the morning gather). Inputs in `in/`: `floors/icu/cardio/neuro.json` (or `wards.json`),
`ams_spill.json`, `ams2_spill.json`, `edits_dl/`, `state.json`, `reg_Register.json` + `reg_History_*.json`,
`roster.txt`, `as_today.json` (or `--as-missing`), `as_yday.json`, `last_delta_sent.txt` (dd.mm.yyyy),
`email_today.txt`, `service_list.json`, `cultures.txt`, `cx_archive.json`, `reg_Verification.json`,
`feed_now/` (feed tabs, `review.json`, `rules.json`, `answered.json`), `recon_prev.txt`, `recon_reply.txt`,
`roster_yday.txt`. Steps: feed snapshot (`in/feed_now` copied to `in/feed_before` before any feed
write), parse_wards, parse_ams x2 + merge, edits collect, state_merge --find (report only), regjoin2,
match.py, `out/day_updates.txt` and `out/app_handoffs.txt`, cultures.py, idp10 base, idp11 vqueue
(written to `out/vqueue.txt`), idp11 review, `recon_reply.py prev` (builds `in/recon_prev.json` from
`in/recon_prev.txt`; an item without a key gets `"k" + sha1(text)[:8]`), recon_reply.py (when the reply
is not empty), `recon_reply.py promote` (writes `out/promote_ops.json` and `in/active_rules.txt`, the
rules that bind today's synthesis), svccheck.

**build** (after `synth_delta.py` and `out/roster_out.txt`). idp10 apply (no "carried unchanged"),
validate_synth (`0 errors`), idp10 evolve (`0 unexplained`), the coverage gate (below), id_list.py +
checks_R idlist/text, build.py (gate on `PREFLIGHT OK` and `BUILD OK` on its own stdout, not on
`run_status.txt`), recap_html.py, wa_handout.py (`out/census_wa.json` when present), checks_R text on
`recap_email.txt/.html`, `wa_handout.txt`, `delta2.html/.txt`, `id_list_email.txt`. The HTML handout
(`out/handout.html`, `build_html.py`) is no longer built: it has not been emailed since 23.10.2026 and
nothing read it. The reconciliation is not built here.

**post** (after the sends; with `out/feed/replies.json`, `out/review_replies.json` and "Applied as" filled
in `out/answered_rows.json`). ams_blocks, idp11 final, idp10 watch, backfill key (`in/bfq.json` when the
key is missing), idp11 feed (pre-write state from `in/feed_before`), idp11 schema, checkreg, vwrite,
reviewreply, drive_state patch (or a full base on PATCH LARGE or a cold start), recon.py with every input
(`--feed-dir in/feed_before`, `--resolved` and `--learned` = this morning's tabs plus today's rows,
`--evolution`, `--review`), checks_R text `out/recon.txt`. It then writes **`out/post_ops/`**: the Drive and
Sheets writes the agent performs, in order, one file each (`NN_<what>.json`: a list of `{range, values}`
update_values ops, or for `state_parts` a list of `{title, path, bytes}` create_file entries), and
`INDEX.txt`:

```
POST OPS <date>: perform in this order, after every send. ...
Targets: feed = IDP Feed <id>; register = IDP Discharge Register <id>; state = IDP_State folder <id>
chkw = after op k of file NN_x.json: get_values on the op's range, save it as in/readback/NN_k.json, then
python3 $T/run.py chkw out/post_ops/NN_x.json k in/readback/NN_k.json must print CHKW MATCH ...
NN | file | target | calls | verify
01 | 01_feed_ops.json | IDP Feed <id> | 4 call(s) | chkw; after the last op re-read the six tabs ... feedcheck: FEED MATCH
02 | 02_feed_schema.json | IDP Feed <id> | 2 call(s) | chkw
...
NN | NN_state_parts.json | IDP_State folder <id> | 4 file(s) | create_file ...; fileSize == bytes; drive part MATCH
```

Order: feed_ops, feed_schema, register_schema, verification_rows, verification_replies, review_replies,
answered_rows, rule_rows, undo_ops, rule_promote, state_parts (files with no op are left out). The ids
come from `in/targets.json` (`{"feed": ..., "register": ..., "state_folder": ...}`, written by the agent,
never committed). `run.py op <file> <k>` prints op k. The per-op files (`out/feed/ops.json`,
`vrows_ops.json`, ...) are still written.

**Membership (rule B, Chris 28.11.2026, match.py).** The service is today's roster plus everyone on
yesterday's list. A patient leaves ONLY on (1) a fellow removal (service list `removed[]`, unless the
fellows put them back later), (2) an update email saying signed off or signed out, (3) a newer full
roster block (3 or more roster lines) in an update email that omits them (newer than the service list's
`last_edit_at`; an email may carry a `=== <ISO time>` line, else it counts as received today). Absence
from every source never removes: `possibly gone: <pid> absent from AS list, handoffs and emails` (kept on).
A removed patient re-enters when a source dated after the removal names them for ID: standing therapy
new on the AS list, a handoff Cs ID / UC ID row dated after the removal, or an update email naming them
(not a sign-off line): `re-entered: <pid> <source>`. All of these are in `out/flags.txt`.

**AS list deadline (rule C).** No AS list by 08:00 Beirut: `run.py prep --as-missing`. match.py takes
rooms from `in/as_yday.json` (or the state's last list), changes no membership from it and computes no
delta; build.py renders the one-line Delta Report `AS list dd.mm.yyyy not received by 08:00; delta follows
when it arrives`, and the state keeps `as_missing_days`, so the next run's delta is taken against the
last list consumed and names the missed day. A list that arrives later the same morning: run prep again
without the flag.

**Learned rules (decision D).** A `RULE:` line binds at once (Status `active`). A rule drawn from a
plain answer is added with `recon_reply.py addrule out --date D --from <item key> "<rule>"` as `proposed`;
recon.py lists it under RULES LEARNED with "binds tomorrow unless you reply undo"; the next prep promotes
it (`out/promote_ops.json`) unless the reply undid it. Only active rules bind: `in/active_rules.txt`
(python: `recon_reply.active_rules(rules.json)`).

**Coverage gate (decision E, review item 11).** `coverage_gate.py` (also `idp10.py coverage`): every
dated fragment (today or yesterday) of the ward-doc lines in `out/day_updates.txt` and of each app
write-up, and every final culture row of the current admission (negatives when they are 3 days old or
newer), must show in a rendered field of the patient's synth entry or WA lines, or be waived in
`synth_delta.py` with `WAIVED = {pid: [{"item": <source text or a distinctive part>, "reason": ...}]}`
(apply carries it into synth.py). Matching is tolerant: the date (plus or minus one day) and one key noun
(specimen, organism or its abbreviation, drug stem, imaging, procedure, event), or half the key nouns in
one item. Misses go to `out/coverage_gate.txt`; the build stops on any miss. `--coverage-warn` turns
it into a warning (use it only when a miss is a toolkit fault, and say so in the closing note).

The sections below are the older procedure and history; where they disagree with this section, this
section wins.

## Emails (up to four, in this order)

1. **AS List Delta Report** - `out/delta2.html` as htmlBody, `out/delta2.txt` as body.
   Subject `AS List Delta Report - dd.mm.yyyy`.
2. **ID Daily Handout** - `out/handout.html` as htmlBody, `out/handout_body.txt` as body,
   subject from `out/handout_manifest.json`. **The handout IS the email**: a printable A4
   three-column table with columns 2 and 3 blank for handwriting, built by `build_html.py`.
   There is no attachment. The DOCX path was retired 14.09.2026 after two months of
   corrupted attachments: base64 does not survive transcription past about 2,000
   characters (three identical single-character corruptions at offset 1833 on 14.09),
   while structured text goes through byte-exact at 25,000 and a 48,000-char HTML body
   arrived with every word intact the same morning. Never send a DOCX again.
3. **ID Daily Recap** - body is `out/recap_email.txt` (`render_wa.py`, compact form).
   Plain text, ONE email, about 14,000 chars for a 17-patient census. Do not split it.
4. **Archive notes: NO EMAIL (amendment P2, 03.10.2026).** `out/archive_notes.txt` is split with
   `archive_split.py` and each note is uploaded to the ID_Archive_Notes Drive folder. Never email it. The old rule was: skip it when the file is empty,
   which is the common case: most mornings nobody has left the service. Never send an empty
   or header-only archive email.

Then the IDP State parts (6 or so emails, `IDP-State` label only), then the run note.

## Verification policy

Measured on 08.09.2026 and again 14.09.2026: prose and HTML transcription byte-exact at
25,000 to 48,000 chars; base64 fails past ~2,000. Verify accordingly.

- **Handout (email 2):** `out/handout_manifest.json` lists the email(s): one (`handout.html`)
  normally, two by ward group when the HTML would exceed 55 K chars (`handout_part1.html`,
  `handout_part2.html`, subjects carry `part n of 2`). For each: `send_message` with `htmlBody` = that file, then
  `get_message` RAW on the returned id (it spills to a tool-result file; leave it there) and
  `verify_handout.py out <messageId> <file>`. It compares the VISIBLE TEXT of the sent HTML with
  the local file, recipient checked, and prints `handout MATCH`. Text and not bytes because
  Gmail rewrites markup in transit. On MISMATCH: fix the string and resend as a reply in
  the same thread, then trash the bad message. Never leave the handout unverified.
- **State parts:** send each, then `get_message` RAW and `state_io.py verify-part` on the
  first, the last, and any odd one. All six matched on 14.09 and the reassembled state was
  byte-identical to the local build, so a full check costs little: do all of them when time
  allows.
- **Delta, recap, archive notes: no verification.** Plain text and short HTML go through.
- `draft_relay.py` and the create_draft / update_draft loop are no longer used: they
  existed for the attachment.

## Writing register (Chris, 14.09.2026)

Highly abbreviated, straightforward, peer to peer. Jargon is fine, it is written for an ID
fellow. Articles and copulas dropped. "adm 12/09 w/ 2d fever 40, prod cough" not "admitted
on 12/09 with two days of fever to 40 and a productive cough". Standard short forms never
expanded: FN, CAP, HAP, VAP, PJI, CLABSI, SSTI, IAI, cUTI, PNA, BCx, UCx, cx, PCT, CRP, dc,
s/p, r/o, 2ry, proph, POD, o/n, RA, NC, HFNC, PRVC, FiO2, PEEP, NE (norad), SBP, MAP, ANC,
Plt, Cr, CrCl, LFTs, EF, RLL, GGO, dx, tx, hx, pt, bilat, w/, w/o, +/-.

## Vitals (Chris, 14.09.2026): status line always, routine labs never

`vitals[0]` is the STATUS line and is mandatory (the validator blocks the build without it):

```
<fever>  |  <haemodynamics>  |  <respiratory>
afebrile since 12/09 | no pressors | RA
Tmax 38.4 o/n, last fever 14/09 | NE 0.1 since 13/09 | intubated PRVC FiO2 40% PEEP 8 since 12/09
afebrile since 10/09 | off pressors since 12/09 | HFNC 60 L/50%
```

Fever state with the date of the last fever or since when afebrile; pressors yes/no and
since when; oxygen: RA, NC flow, HFNC, BIPAP, or intubated with mode and settings and since
when. Every other vitals line is imaging or a PIVOTAL lab, one that made the diagnosis
(lactate 11 on arrival, ANC 20, a trough that drove a switch). Routine labs (CrCl, Cr, Na,
Hb, Plt, LFTs, trop, CRP trends, INR) are NOT on the handout: the renderer drops them and
the validator warns. Prefix a line with `!` to keep a lab that the rule would drop.
The handout prints `Status:` then `Imaging/key labs:`; the recap prints `Status:` only.

## Delta report: mobile first (Chris, 14.09.2026)

`render_delta.py` renders one column of short lines per patient (bed, name, on / started /
stopped / now on). No tables, no fixed width: it reads the same on a phone. New to service
comes from `out/new_mrns.json`, which `match.py` now writes by rule E (new on the AS list
AND no ward row, OR `(new)` on the roster line). If the updates email names a new patient
who is not tagged on the roster, add `(new)` to that line in `in/roster.txt` and re-run
`match.py`; do not hand-edit new_mrns.json. `build.py` runs `render_delta.py` itself.

## Preflight (added 14.09.2026)

`build.py` ends with `preflight.py`, which checks every deliverable before the first send:
files present, sizes under the transcription limits, no dashes, no `background:`, state
headers carry today's date and the manifest sha256, handout subject carries today. The
build prints `PREFLIGHT OK` before `BUILD OK`; without both, nothing is sent.

## Guards that stop the build

- `match.py` exits 2 on ORPHAN ALERT: orphans over 40% of census, or a jump of 4+ since the
  last run, or parsed ward rows down 15%+. Any of these is far more likely to be a parser
  fault than a hospital-wide documentation failure. Confirm the names really are absent
  from all four ward docs before passing `--allow-orphans`.
- `validate_synth.py` must print `0 errors` (a missing or malformed status line in
  `vitals[0]` is an error).
- `preflight.py` must print `PREFLIGHT OK`.
- `build_html.py` must print `handout html ... patient rows` (it asserts no dashes and no `background:`).

## Delta baseline when a day had no AS list (added 14.09.2026, Chris's rule)

The delta is taken against the last AS list whose delta report was actually SENT, not
against the calendar's yesterday. `state_io.py finalize` keeps the last 7 lists in
`as_history`. Before `match.py`, search Gmail: `from:me subject:"AS List Delta Report"`
newest first, read the date in that subject, and pass it as `--last-delta-sent dd.mm.yyyy`.
`match.py` then picks the newest stored list on or before that date. So:

- no AS list on 13.09: the 14.09 report is 14.09 vs 12.09 and its subtitle says
  "no AS list on 13.09.2026, so this delta covers 2 days";
- two or more days missed in a row: same, all the missed days are named;
- a run that built but died before sending: the next morning's report covers both days.

A day with no AS list still gets no delta report of its own (there is nothing to diff);
the gap is reported on the next day that has a list.

## Things that silently break in Gmail

- `style="background:..."` is **deleted in transit**. Use the `bgcolor` attribute, and never
  let shading be the only carrier of meaning; add a text tag as well.
- `<div style="height:1px;background:#ccc">` renders as nothing. Use `border-top`.
- Space-padded columns in text/plain collapse: mail clients use a proportional font.
  One field per line instead.

## Archive notes (added 08.09.2026)

`out/archive_notes.txt` is written by `state_io.py finalize`. It holds one block per patient
who has left the service, emitted ONCE, on the first morning they are absent from the AS
list and all four ward docs.

Since 03.10.2026 (amendment P2) it is NOT emailed: archive_split.py splits it and each note goes to the
ID_Archive_Notes Drive folder. Until then it went as its own email, number 4, decided by Chris 10.09.2026. It used to be specified as
a section at the end of the recap, but the two together run to about 38500 chars on a normal
day and the recap alone is already 25000, so appending it forces a split of the one email
that must not be split. A separate email also keeps the sealing work in one place: this is
the note Chris works from, not something to scroll past at the end of the handoff.

Chris seals the AMS row block from this note by hand and the record is then deleted here.
So the note has to stand alone: the daily handout is a mid-stream snapshot and was never
written to close a case. The block carries the one-liner, every problem with its dates and
reasoning, the full antimicrobial course with start and stop dates, all microbiology, and
what was still outstanding on the day they left.

Order matters: the note is built from the last day the patient was on the census, so it is
written BEFORE the purge, not at it. A patient who vanishes without a final good day gets a
thinner note; nothing can be done about that.

## The recap / WhatsApp handoff (email 3), compact since 14.09.2026

`render_wa.py` writes `out/whatsapp.txt`, which becomes the body of email 3. It is the
handout's short form for whoever is on call. Chris, 14.09.2026: "very compact, at least
half the size". The verbose Findings/Labs/Micro form is gone; that content is on the handout.

Shape per patient:

```
ROOM NAME (new) (UC)
<age/sex, ID-relevant background only>; adm <date> with <why>, <room>.
1. <dx> (<date>); <Drug> <segs>; <Drug> <segs>. <status / plan>
2. ...
Rx (unlinked): ...
Pending: <item>; <item>
```

One line per issue: diagnosis and date, the drugs with their date segments (no frequency,
no day counter, no note, route only when not IV), then the status sentence from the synth.
Pending is item names only. No Findings, no Labs, no Micro, no Update line.

Content rules, set by Chris:

- ID only. Diagnoses, findings, treatments, rationale, pendings. Nothing else.
- **No dose, no frequency.** The renderer strips frequency from the abx grammar; keep
  writing the grammar as it is, the WhatsApp render drops it. Route prints only when it
  is not IV, so PO and IM stand out and IV is silent.
- Start and stop dates always. Day counts and drug notes are on the handout, not here.
- Switches go in the `Why` line, in words. The renderer no longer infers them from
  dates; an inferred switch between two unrelated agents is a lie.
- **No cap.** A four-problem ICU patient is allowed to run long. Do not compress a
  complex case to match a simple one.
- **No commentary.** Nothing about the AS list, the ward docs, the AMS workbook, the
  parser, what is missing from a source, what should be reconciled, or what I noticed.
  If a patient has no documentation, the block says the diagnosis is not documented and
  stops there. "carried by the AS list alone", "unreconciled", "no ward row in any
  handoff doc" and everything like it does not belong in a handoff.
- Non-ID vitals are filtered out to `out/wa_dropped.txt`. Read that file each morning:
  it is the only place a wrongly dropped line will show.

Inherit, do not rewrite. This is also what makes the morning fast. The block is a pure
function of the synth entry, so an entry that has not changed renders byte-identical to
yesterday. Each morning, start from yesterday's synth (it is in `state_matched.json`),
paste it, and change only the fields a source actually changed: the `updates` line, a new
segment on a drug, a new pending, a status sentence when the plan moved. Do not re-read
the whole admission and write the patient afresh; that is where the hours went. `out/wa_diff.txt` lists every line that moved: read it before sending
and confirm every single change traces to something a source said today. A line that
moved because I reworded it is a defect, not an improvement.

Writing register. Short clauses. Abbreviations a fellow reads without pausing: RLL, GGO,
UCx, BCx, cx, neg, pos, R/L, wk, d. Drop articles and hedges. "CTA 26/08 loculated
bilateral effusions, new RLL/RML consolidation" not "pan CTA on 26/08 showed large
loculated right and large left pleural effusions with new right lower and middle lobe
consolidation".

## Amendments O to T (07.10.2026)

The run follows IDP_amendments_NO.txt in the Drive overlay folder (O second AMS workbook, P ID list first and no archive email, Q overlay 4 and membership, R overlay 5, S strict rules and checks_R.py, T overlays 6 and 7 and the helper scripts). It overrides this file where they conflict. It stays on Drive because it names patients.

## Register coverage, backfill and Schema (29.10.2026, Chris)

Every admission the ID service follows has a block in the IDP Discharge Register from its first day on the service.
- `idp11.py feed` puts each pid in Feed Patients on its first morning (Status Active). New column "AMS block"
  (sheet!first row of a hand-made AMS workbook block for the same admission) before "Updated": schema_version 2.
  The existing read range 'Feed Patients'!A1:V5000 still covers every compared column (A..V); W is "Updated".
- `idp11.py checkreg` also checks coverage against `reg_Index.json` next to the register file (or `--index`): every
  Feed pid must have exactly one Index Key. Missing or duplicate ones become Verification rows ("missing block",
  "duplicate block", Found by Claude) in vrows_ops.json, and the line "register: N admissions, M without a block"
  goes to out/feed/coverage.txt and out/run_status.txt. Put that line in the closing note when M > 0.
- `idp11.py backfill <state_new> <reg_Index.json> <dir of identifiers CSVs> --date D` reports the admissions with no
  block (count and dates only). After Chris's go, the same command with `--queue` stores them in state["backfill"];
  `feed` then adds them as "Discharged dd/mm/yy", sharing the daily cap (--backlog, 10) with the departed backlog,
  oldest first, until `final` sees their block FINAL in Index.
- `idp11.py schema --date D` prints the Schema tab ops for both sheets and the Meta op. Rewrite them whenever a
  header changes, and bump SCHEMA_VERSION in idp11.py with it. Never rename a header without the bump.
- Cells that look like numbers, dates or formulas (MRNs, dd/mm) are written with a leading apostrophe; dates in
  Updated, Feed Changes, Verification and Meta are dd/mm/yy.

## Notes evolve, never rewritten; Gemini Review (28.11.2026, Chris)

Each day starts from yesterday's synthesis and amends only what today's sources change; every change is explained.
- synth_delta.py may carry `CHANGES = {pid: [{"field", "kind": NEW|AMENDED|RETRACTED, "old", "new", "source"}]}`;
  `idp10.py apply` (alias `assemble`) copies it into synth.py.
- `idp10.py evolve synth.py in/state.json out --date D` compares every carried pid field by field (one_liner, issues
  (dx), abx (issue and abx_other drug lines), id_plan, im_detail, steroids, devices, micro, micro_recap, pendings,
  conflicts, not_applied, vitals; lists item by item) and writes out/evolution.txt and out/evolution.json. It exits 1
  while any difference has no CHANGES entry with a source: add the entry or restore yesterday's text. A rewording of
  yesterday's text is a difference.
- `idp11.py feed` appends today's rows of out/evolution.json to the "Evolution" tab (nowdir/evolution.json = the tab
  as it is now; a rerun writes no duplicates) and creates "Gemini Review" with its header only when that tab is absent
  (nowdir/review.json empty). Schema version 6.
- Gemini writes Date..Evidence of "Gemini Review"; the run answers the next morning: `idp11.py review
  in/feed_now/review.json out --date D` lists open points in out/review_open.txt; write out/review_replies.json
  ({row: {reply: accepted|rejected|partly, reason}}), then `idp11.py reviewreply out/review_replies.json
  in/feed_now/review.json out/feed --date D` gives out/feed/review_ops.json (columns H..K only). An unresolved point
  (rejected, partly, or unanswered for more than one round) gets Escalated Y.
- `recon.py --evolution out/evolution.json --review in/feed_now/review.json`: the Evolution counts go under CHECKED;
  every Escalated row and every rejected Gemini point goes under NEEDS YOU.

## Chris answers the ID Reconciliation email (28.11.2026)
- Every NEEDS YOU line ends with a stable key `[k<8 hex>]` (sha1 of scope | kind | text without dates and times);
  out/recon.json "need" is a list of {n, key, text}. The body ends with the HOW TO ANSWER footer.
- Chris replies to the email (to himself). Next morning, before recon: save the reply's plaintextBody to
  in/recon_reply.txt and yesterday's recon.json to in/recon_yday.json, read the feed tabs 'Learned Rules' and
  'Answered Items' (get_values) into in/rules_tab.json and in/answered_tab.json, then
  `recon_reply.py in/recon_reply.txt in/recon_yday.json out --date D --rules-tab in/rules_tab.json --answered-tab in/answered_tab.json`
  (REPLY OK: a answers, r rules, u undo, x unparsed). Apply every answer in out/chris_answers.json; append
  out/answered_rows.json to 'Answered Items' (fill "Applied as"), out/rule_rows.json to 'Learned Rules', and run each
  op of out/undo_ops.json (Status undone). Show every "unparsed" line to Chris in the recon.
- Then `recon.py ... --resolved in/answered_tab.json --learned in/rules_tab.json` (re-read both tabs after the
  appends): answered keys are skipped while Until is empty or not passed, and new active rules are listed as L<No>.
