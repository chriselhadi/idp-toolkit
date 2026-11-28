# ID Daily Pipeline: send + verify procedure

Changed 08.09.2026 after a morning that pushed ~1.1 MB of text through the model,
almost all of it mechanical copying.

## Stage commands (28.11.2026): what the run executes

Since 28.11.2026 the daily run no longer types about forty commands by hand. The agent keeps every
MCP read and write (Gmail, Drive, Sheets) and the judgment (`in/roster.txt`, `synth_delta.py`,
`out/roster_out.txt`, the replies). Everything local runs through three stage commands, from `/tmp/idp`:

```
T=/tmp/idp/toolkit/idp/idp
python3 $T/run.py prep  --date YYYY-MM-DD [--as-missing] [--allow-orphans] [--skip-base] [--accept-chain]
python3 $T/run.py build --date YYYY-MM-DD --long-date "28 November 2026" [--coverage-warn]
python3 $T/run.py post  --date YYYY-MM-DD
python3 $T/run.py op         <ops.json> <k>
python3 $T/run.py chkw       <ops.json> <k> <readback.json>
python3 $T/run.py sendcheck  <sent_message.json> <field=file>...
python3 $T/run.py chaincheck in/chain.txt --date YYYY-MM-DD [--state in/state.json] [--accept-chain]
```

Each step prints one line (`  <step>: <result>`), its full output goes to `out/stage_logs/`. The first
failed gate prints `STAGE FAIL: <step>: <reason>` and exits 1: fix the input it names and run the
stage again (every stage can be re-run). A finished stage ends with `STAGE OK: <stage> <date>`.

**prep** (after the morning gather). Inputs in `in/`: `floors/icu/cardio/neuro.json` (or `wards.json`),
`ams_spill.json`, `ams2_spill.json`, `edits_dl/`, `state.json`, `reg_Register.json` + `reg_History_*.json`,
`roster.txt`, `as_today.json` (or `--as-missing`), `as_yday.json`, `last_delta_sent.txt` (dd.mm.yyyy),
`email_today.txt`, `service_list.json`, `cultures.txt`, `cx_archive.json`, `reg_Verification.json`,
`feed_now/` (feed tabs, `review.json`, `rules.json`, `answered.json`), `recon_prev.txt`, `recon_reply.txt`,
`roster_yday.txt`, `chain.txt` (the stdout of `drive_state.py unpackchain`, saved as it printed). Steps: feed snapshot (`in/feed_now` copied to `in/feed_before` before any feed
write), parse_wards, parse_ams x2 + merge, edits collect, state_merge --find (report only), regjoin2,
match.py, `out/day_updates.txt` and `out/app_handoffs.txt`, cultures.py, idp10 base, idp11 vqueue
(written to `out/vqueue.txt`), idp11 review, `recon_reply.py prev` (builds `in/recon_prev.json` from
`in/recon_prev.txt`; an item without a key gets `"k" + sha1(text)[:8]`), recon_reply.py (when the reply
is not empty), `recon_reply.py promote` (writes `out/promote_ops.json` and `in/active_rules.txt`, the
rules that bind today's synthesis), svccheck.

Round 2 additions to prep (28.11.2026):
- **Feed read gate (T1, first step).** Every `in/feed_now/<tab>.json` of `patients antimicrobials micro labcx
  dailyreport changes evolution review rules answered` must exist, parse and have a header row (and
  `in/reg_Verification.json`, when present). Otherwise `STAGE FAIL: feed reads: in/feed_now/<tab>.json missing |
  empty (no header row) | does not parse`, or `in/feed_now is empty`; nothing else runs and `in/feed_before` is not
  touched. Re-read the tab and run prep again. An empty directory is never a read.
- **State check (T4, T10).** `last run: state last_run_utc <UTC>` (or the fallback when the state has none). Then
  `in/chain.txt` against today: no `CHAIN OK` line, `in/state.json` not the chain's state, or a state dated today or
  later: `STAGE FAIL: chain check`. A `sha mismatch` or `not applied` line: `STAGE FAIL: chain check` unless
  `--accept-chain`, which prints `chain check: WARN (--accept-chain): ...` and raises a run item. A state not dated
  yesterday: `chain check: WARN: ...` and a run item. A fallback base: WARN (post writes a full base). Clean:
  `chain check: CHAIN CHECK OK: base X + n patch(es) -> state dated <yesterday> (yesterday)`. Without
  `in/chain.txt` only the state date is checked. prep's run items go to `out/run_items_prep.txt` (rewritten each
  prep); post adds them to `out/run_items.txt` for recon (`out/run_items_all.txt`). `run.py chaincheck` runs the same
  check alone: `CHAIN CHECK OK | WARN | FAIL`.
- **Base (T3, T8).** The NEW and READMISSION lines of idp10 base are printed (`  base: P0123 Name: NEW ...`). A failed
  base prints `base: FAILED (STAGE FAIL deferred to the end of the stage)`, every later step still runs, and prep ends
  `STAGE FAIL: base: ...`. `--skip-base` does not run the base at all (`base: SKIPPED (--skip-base)`): write
  `synth_base.py` by hand, the rest of prep runs as usual.
- **Re-run safety (T2).** A prep re-run never destroys judgment work: `synth_delta.py`, `out/review_replies.json`,
  `out/roster_out.txt`, `out/verification_requests.json`, `in/roster.txt`, `in/roster_yday.txt` are put back if a
  step changed them; "Applied as" and "Until" in `out/answered_rows.json` are kept by Key (rows no longer in the reply
  but already filled are kept); `proposed` (addrule) rows of `out/rule_rows.json` are kept, numbered after the tab and
  the new rows. Copies are left in `out/prep_keep/`. prep prints `preserved: <file> ..., out/answered_rows.json (n
  'Applied as' kept), out/rule_rows.json (n addrule row(s) kept)`.
- prep records the run's start in `out/run_start_utc.txt` (`<date> <UTC>`, first prep of the date only).

**build** (after `synth_delta.py` and `out/roster_out.txt`). idp10 apply (no "carried unchanged"),
validate_synth (`0 errors`), idp10 evolve (`0 unexplained`), the coverage gate (below), id_list.py +
checks_R idlist/text, build.py (gate on `PREFLIGHT OK` and `BUILD OK` on its own stdout, not on
`run_status.txt`), recap_html.py, wa_handout.py (`out/census_wa.json` when present), checks_R text on
`recap_email.txt/.html`, `wa_handout.txt`, `delta2.html/.txt`, `id_list_email.txt`. The HTML handout
(`out/handout.html`, `build_html.py`) is no longer built: it has not been emailed since 23.10.2026 and
nothing read it. The reconciliation is not built here.

**post** (after the sends; with `out/feed/replies.json`, `out/review_replies.json` and "Applied as" filled
in `out/answered_rows.json`). First: `out/post_ops/` and the per-op files of an earlier post are deleted, and the
feed read gate (T1) runs on `in/feed_before` and `in/feed_now` (and `in/reg_Verification.json`): a missing or empty
read is `STAGE FAIL: feed reads: ...` and no op file is written; idp11 feed runs with `--strict` (FEED FAILED rather
than treating a missing read as an empty tab). post writes `state["last_run_utc"]` into `out/state_new.json` (T10:
the run's start from `out/run_start_utc.txt`, else now), prints `last run: state last_run_utc = <UTC>`, and the
next prep prints it: it is the "since yesterday's run" cutoff. ams_blocks, idp11 final, idp10 watch, backfill key (`in/bfq.json` when the
key is missing), idp11 feed (pre-write state from `in/feed_before`), idp11 schema, checkreg, vwrite,
reviewreply, verification requests (T6: `out/verification_requests.json`, a list of `{key, column, value_checked,
value_in_source, source, severity, note}` (optional `tab`, default `Register`) written by the synthesis for merge
requests and register corrections -> `idp11.py vrequests` -> C- rows in the Verification format (Found by Claude,
State open, the note after the source), appended after checkreg's rows with ids continuing them; `VREQUESTS OK`;
a request already open is not repeated; requests without a Verification read, or lacking key, column,
value_in_source, source or severity: STAGE FAIL), drive_state patch or a full base (T5: post decides; a full base
on a cold start, PATCH LARGE, or from `in/chain.txt`: 6 or more patches already follow the base, the chain fell
back to an older base (`chain: fallback to base X` / `chain: base X incomplete ... skipped`), or the chain's base
is dated today; `state base: FULL BASE: <reasons>`), recon.py with every input
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

INDEX.txt also says `Input mode: update_values with valueInputOption USER_ENTERED` (T9: a leading apostrophe makes
the cell text and is not stored; chkw expects it so and compares the read-back verbatim, so a read-back still showing
the apostrophe, i.e. a RAW write, is a CHKW MISMATCH) and `State: FULL BASE IDP State <date>, because: <reasons>` or
`State: patch IDP State Patch <date> on the morning's chain`; a full base's NN_state_parts.json entries carry the
titles `IDP State <date> (part i of n)` and their bytes.

Order: feed_ops, feed_schema, register_schema, verification_rows, verification_requests, verification_replies, review_replies,
answered_rows, rule_rows, undo_ops, rule_promote, state_parts (files with no op are left out). The ids
come from `in/targets.json` (`{"feed": ..., "register": ..., "state_folder": ...}`, written by the agent,
never committed). `run.py op <file> <k>` prints op k. The per-op files (`out/feed/ops.json`,
`vrows_ops.json`, `vreq_ops.json`, ...) are still written.

**Send verification (T7).** After each send, `get_message` the sent email, save the result, and run
`python3 $T/run.py sendcheck <sent_message.json> subject=<file> plaintextBody=<file> [htmlBody=<file>]`: one line per
field, `EXACT` (byte-exact), `EQ_mod_trailing_ws` (only line endings and trailing blanks differ) or `DIFF` (with
the first differing line) or `MISSING`; `SENDCHECK OK: n field(s)` when none differs, else `SENDCHECK FAIL` (exit 1).
A field is a key of the result at any depth, or a `{name, value}` header (e.g. `Subject`).

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
2. **ID Daily Handout Notes** - body is `out/handout_body.txt` (two lines).
   ONE attachment: the file named in `out/handout_manifest.json`, base64 in `out/handout.b64`.
3. **ID Daily Recap** - body is `out/recap_email.txt` (the WhatsApp handoff, written by
   `render_wa.py`). Plain text, ONE email. Measured 10.09.2026: a 25264-char body goes in a
   single tool call byte-exact. Do not split it. If it ever does exceed 30000 chars, split
   into thread replies rather than separate emails.
4. **Archive notes** - body is `out/archive_notes.txt`, subject `ID handoff <dd.mm.yyyy>
   archive notes`. Plain text, ONE email. **Skip this email entirely when the file is empty**,
   which is the common case: most mornings nobody has left the service. Never send an empty
   or header-only archive email.

The handout is no longer split into five parts. That split existed only because the recap
used to ride in the email body and blew the 30000-char limit. The recap has its own email
now, so one DOCX goes out as one attachment.

## Verification policy

Measured on 08.09.2026: prose transcription 18/18 correct, base64 transcription 2 failures
in 7. Verify accordingly.

**Send every clinical email through the draft relay (added 10.09.2026).** Never send an
attachment or a long body directly. The relay makes one deliverable one email no matter how
many attempts the transcription takes:

1. `create_draft` with the full body and, for the handout, the whole of `out/handout.b64`
   as one attachment.
2. `get_draft` with `messageFormat: RAW`. Large drafts spill to a tool-result file;
   `draft_relay.py` reads either.
3. `draft_relay.py draft <draftId> <local file> attach <filename>` for the handout, or
   `... body` for a text email. It checks the recipient is chriselhadi@gmail.com and nobody
   else, then compares bytes. On a mismatch it prints the offset of the first bad character
   and the context either side.
4. On a mismatch, `update_draft` with the corrected string (attachments are NOT merged, so
   re-supply the attachment), then verify again. Repeat until MATCH.
5. `send_message` with `draftId`, then `draft_relay.py msg <messageId> ...` to confirm what
   was actually sent.

The repair loop happens in Drafts, so Chris never sees a corrupt email and never sees a
deliverable arrive in pieces. Splitting a deliverable is NOT a remedy for a transcription
error: on 10.09.2026 the handout went out as 5 emails and the recap as 3 for that reason,
and nothing involved was anywhere near Gmail's 25MB ceiling. Chris's standing rule about
halving an oversized email applies to genuine size limits only.
- **State parts: verify the first, the last, and any part whose send looked odd.** Spot
  checks, not all N. A wrong part is caught tomorrow by the sha256 in the header, which
  covers the whole state, so a miss costs a rebuild and not a wrong handout.
- **Plain-text clinical emails: no verification.**

## Guards that stop the build

- `match.py` exits 2 on ORPHAN ALERT: orphans over 40% of census, or a jump of 4+ since the
  last run, or parsed ward rows down 15%+. Any of these is far more likely to be a parser
  fault than a hospital-wide documentation failure. Confirm the names really are absent
  from all four ward docs before passing `--allow-orphans`.
- `validate_synth.py` must print `0 errors`.
- `verify_docx.py` must print `ALL CHECKS PASSED`.

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

It goes as its own email, number 4, decided by Chris 10.09.2026. It used to be specified as
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

## The WhatsApp handoff (email 3), changed 08.09.2026

`render_wa.py` writes `out/whatsapp.txt`, which becomes the body of email 3. It is a
bite-sized fellow-to-fellow handoff for whoever is on call, not a report.

Shape per patient:

```
ROOM NAME (new)
<age/sex, ID-relevant background only>. Adm <date>.
1. <dx> (<date>)
   Findings: <what was seen or grown>
   Rx: <drug> <start-stop>[, <start-stop>] D<n>; <drug> ...
   Why: <rationale, plan, who owns it>
Micro: ...
Labs: ...
Pending: ... (date, dN) -> <what it decides>
```

Content rules, set by Chris:

- ID only. Diagnoses, findings, treatments, rationale, pendings. Nothing else.
- **No dose, no frequency.** The renderer strips frequency from the abx grammar; keep
  writing the grammar as it is, the WhatsApp render drops it. Route prints only when it
  is not IV, so PO and IM stand out and IV is silent.
- Start and stop dates always. Day count is kept: it is the one number a fellow needs.
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

Inherit, do not rewrite. The block is a pure function of the synth entry, so an entry
that has not changed renders byte-identical to yesterday. Each morning, start from
yesterday's synth (it is in `state_matched.json`) and change only the fields a source
actually changed. `out/wa_diff.txt` lists every line that moved: read it before sending
and confirm every single change traces to something a source said today. A line that
moved because I reworded it is a defect, not an improvement.

Writing register. Short clauses. Abbreviations a fellow reads without pausing: RLL, GGO,
UCx, BCx, cx, neg, pos, R/L, wk, d. Drop articles and hedges. "CTA 26/08 loculated
bilateral effusions, new RLL/RML consolidation" not "pan CTA on 26/08 showed large
loculated right and large left pleural effusions with new right lower and middle lobe
consolidation".
