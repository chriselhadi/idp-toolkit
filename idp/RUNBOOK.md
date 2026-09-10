# ID Daily Pipeline: send + verify procedure

Changed 08.09.2026 after a morning that pushed ~1.1 MB of text through the model,
almost all of it mechanical copying.

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
