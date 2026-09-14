# ID Daily Pipeline: send + verify procedure

Changed 08.09.2026 after a morning that pushed ~1.1 MB of text through the model,
almost all of it mechanical copying. Changed again 14.09.2026: handout as HTML email
body (no attachment ever again), compact recap, delta baseline = last SENT delta.

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
4. **Archive notes** - body is `out/archive_notes.txt`, subject `ID handoff <dd.mm.yyyy>
   archive notes`. Plain text, ONE email. **Skip this email entirely when the file is empty**,
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
