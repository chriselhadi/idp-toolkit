---
name: "clinical-micro-extractor"
description: "Transcribes and consolidates clinical microbiology bench material (handwritten culture notebook pages, the lab's Daily Report sheet, Gram stains, AST stickers, antifungal MIC cards, nose/rectal MDRO screening panels) into a patient-grouped, WhatsApp-ready handover digest. Use this whenever the user uploads photos, scans, PDFs or text of micro lab notebooks, culture workups, bench logs, susceptibility cards or surveillance swab results and asks to read, extract, tabulate, summarise, consolidate or report them, or asks for a micro digest, AMS micro summary or micro handover, even if the word \"extract\" never appears."
---

# Clinical Microbiology Extractor

The output is a faithful transcription, not an interpretation. The reader is an infectious disease physician who acts on it, so a silently guessed organism, count or MIC is worse than an honest "(?)".

## Workflow

1. **Inventory every page.** Photos are often rotated 90 or 180 degrees; rotate and read each one before moving on (extract the embedded images and rotate them if the rendered page is sideways). Two source types:
   - *Daily Report sheet*: printed header and date, one row per specimen (bench number, triple name, birth year, sample, preliminary result in red ink, location).
   - *Bench notebook page*: printed barcode label (name, SID with collection date, DOB, sample type, MRN, last line = sample code, sex, I/O, unit), handwritten workup (Gram, media with growth marks, IDs, tests), a printed AST or screening sticker, and a sign-off tick with a date.
   - The same page is sometimes photographed twice (before and after the AST is filled in). Use the most complete version and note the duplicate in Verify.
2. **Match pages to patients** by MRN, then name plus DOB. Link Daily Report rows to bench pages by bench number (red number in the page margin) or name. Ditto marks on the Daily Report repeat the patient on the row above.
3. **Transcribe each specimen**, decoding shorthand with the Bench shorthand section below.
4. **Group everything by patient** (one block per patient), **carry forward the previous digest** (section below), and write the digest in the order under Output structure, then the Verify list.
5. **Self-check** (last section) and deliver.
6. **Archive to Drive** and **update the finalised-results database** (sections below).

## Reading rules

- Handwriting beats print: a value written over a blacked-out sticker value (e.g. "pos" over NEGATIVE) is the result.
- Never guess silently. Give your best reading followed by `(?)` and add the item to Verify. If nothing is readable, write `_illegible_`.
- Transcribe, don't infer: no organism from a Gram stain, no susceptibility from an organism name, no contaminant or colonisation calls. Plain factual counts (e.g. "2/2 sets GPC clusters") are fine.
- A sign-off tick with a date means final. No tick means still open, unless the result itself is terminal (no growth at 48h).
- Omit phone numbers, staff names and personal notes scribbled on pages.
- Use the printed SID as the specimen identifier on bench pages (it is typed, so reliable). Use the bench number only for Daily Report rows.
- Ignore labels only partly in frame (at a page edge) with no readable workup: leave them out of the digest entirely, including Verify.

## Output structure

The digest has three parts, in this order.

### Part A: Daily Report

Title line `*Daily Report DD/MM/YYYY*` (the date printed on the sheet). One line per row, in the sheet's order:

`- 5001 *Alpha Bravo Tester* (b. _1950_ | _702B_): Urine: >100,000 col/ml GNB`

Bench number, name, birth year, location (omit if blank), sample, the red preliminary result. Ditto rows get the patient's name written out. If there is no Daily Report in the upload, omit Part A.

### Part B: Patients

Title line `*Micro Digest DD/MM/YYYY*`. One block per patient. **Each patient appears exactly once**: the header is written one time and every specimen from that patient (cultures, AST, screening panels, negatives, pending work) sits under it. Never split a patient across sections and never repeat a header.

Patient header:
`*Full Name* (DOB _DD/MM/YYYY_ | MRN _XXXXXX_ | _Unit_)`. Omit unknown fields. Unit = the unit code from the label (copy raw); if none, write _Inpatient_ or _Outpatient_ from the I/O flag.

Specimen lines under the header, ordered within the patient as:
1. Positive cultures and identified organisms (with AST if done), positive antigen, toxin or PCR.
2. Preliminary or ongoing work (flagged bottles, Gram without ID, pending ID or AST).
3. Screening panels: positive panels name the positive marker(s) in bold; fully negative panels say `all negative`. Two or more negative panels collected the same day may share one line.
4. Negative cultures and commensals (no growth, normal/oral flora).

Each specimen line starts with a status tag so the reader can scan: `[POS]`, `[PRELIM]`, `[SCREEN +]`, `[SCREEN -]`, `[NEG]`.

`- [POS] *Urine* (SID _900001_, coll. _24/09_, DR 5001): numerous PMN, numerous GNB, >100,000 col/ml. Final 26/09.`

Multiple organisms from one specimen go on indented sub-lines beneath it.

A Daily Report row that matches a bench page is **not** restated in Part B: add its number as `DR nnnn` inside the specimen's parentheses and give the bench result only. If the Daily Report and the bench page disagree, give the bench result and put the discrepancy in Verify.

Order of patient blocks:
1. Patients with any `[POS]` specimen.
2. Patients with `[PRELIM]` but no `[POS]`.
3. Patients with `[SCREEN +]` only.
4. Patients whose results are all negative.
Within a tier, alphabetical by first name.

Part B contains only patients who have at least one bench page of their own. A patient who appears only on the Daily Report (no dedicated bench page) is never named in Part B or in Verify, and their preliminary result is not repeated there; their row in Part A is their only entry. The same holds for a Daily Report row whose specimen has no bench page: it stays in Part A only, even if that patient has a Part B block for other specimens.

### Carry-forward from the previous digest

Each digest must show the full, current culture picture for every patient in it, so the reader never has to open yesterday's message.

- Source: the most recent earlier digest, from this conversation or the latest `Cultures YYYY-MM-DD` file in Daily_Cultures.
- For every patient who is in today's Part B **and** in the previous digest's Part B, bring each of their previous specimens into today's block:
  - SID re-photographed today: use today's reading. If the result changed, end the line with `Updated DD/MM (was <old status or key finding>).`
  - SID not re-photographed today: copy the previous line as it was and end it with `Unchanged since DD/MM.` (DD/MM = the previous digest's date; if the line already says `Unchanged since`, keep its original date, and drop any old `Updated` note).
- Place carried lines by their status within the patient block, like any other line; tag and tier the patient on the combined set (a carried `[POS]` moves the patient into the POS tier).
- Patients only in the previous digest are not carried forward. Do not carry forward Part A rows.
- Add one Verify line listing carried-forward SIDs that were still open (PRELIM or unsigned), since their current status was not photographed.

### Part C: Verify

Title line `*Verify*`. Every `(?)` item from Part B, one line each: identifier (SID or DR number), what is uncertain, the candidate readings. Also: Daily Report vs bench discrepancies for Part B patients, duplicate photos, unknown card codes. Uncertain readings in Part A stay inline as `(?)` and get no Verify line.

## Formatting (WhatsApp)

WhatsApp renders `*bold*`, `_italic_`, `~strike~`. It does not render Markdown `#` headers, so titles are bold lines.

- Specimen line: `- [TAG] *Specimen* (SID _XXXXXX_, coll. _DD/MM_): result`
- Organism with phenotype: `*_E. coli_ (ESBL)*`
- AST as one dense line: `*S:* _Drug, Drug_, *I:* _Drug (MIC)_, *R:* _Drug, Drug_`. Put MICs in parentheses when the card gives them.
- Only single `*` and single `_`. Bullets are `- `. No em or en dashes: use colons, commas, parentheses or separate sentences.
- A blank line between patient blocks.
- No greeting, intro, commentary or sign-off.

Deliver the digest inside one plain code block in chat, because the chat renderer otherwise converts the asterisks and underscores before the user can copy them. If file tools exist, also save it as a `.txt`.

## Archive to Drive

The ID Daily Handout task reads this folder every morning and uses whatever was added since the previous day to update each patient's cultures, pendings and ID issues. So every digest must land there.

- Folder: Archive_Research / Daily_Cultures in the user's Google Drive (folder ID `CULTURES_FOLDER` from the run configuration; if absent or failing, search Drive for a folder titled `Daily_Cultures`).
- One plain-text file per day, title `Cultures YYYY-MM-DD` (the date on the Daily Report, or the digest date if there is none). Content = the full digest exactly as delivered (Part A, Part B, Verify). Create it with `contentMimeType: text/plain` and `disableConversionToGoogleType: true`.
- Overwrite rule: if a file with that day's title already exists and the digest changed (re-run, corrections, skill edits), create the new file first, then trash the old one. Drive cannot edit a file's content in place, and the new file's creation time is what makes the morning task pick it up. Never trash any other file in the folder.
- Apart from the Daily Cultures Archive sheet below, do not add spreadsheets, summaries or other files to the folder; the morning task reads everything new in it.
- If the Drive connector is off or the save fails, say so in one line and keep the local `.txt`.

## Finalised-results database

Google Sheet "Daily Cultures Archive" (ID `CULTURES_SHEET` from the run configuration, in Daily_Cultures), tab `Finalised results`. One row per specimen, keyed by SID. Only finalised specimens go in: a dated sign-off tick, or a terminal result (no growth at 48h). Preliminary, pending, unsigned and Daily-Report-only results never go in.

Columns, in order: SID | Patient | DOB | MRN | Unit | Specimen | Collected | Status | Result | Organism | AST S | AST R | AST notes | Sign-off | Daily Report no. | First reported | Last updated.

- Status is the digest tag without brackets (POS, SCREEN +, SCREEN -, NEG). Result is the specimen line's text without WhatsApp marks. AST S and AST R use the short drug names; with two organisms, write `Organism: drugs | Organism: drugs`. MICs stay in parentheses.
- Upsert: read column A with `get_values` first. SID already there and anything changed: overwrite that row in place, keep First reported, set Last updated to the digest date. New SID: append below the last row with both dates set to the digest date. Nothing changed: leave the row alone.
- Prefix SIDs, MRNs and dates with an apostrophe so Sheets keeps them as text.
- Never delete rows. Keep rows sorted by Patient, then Status.
- If the Sheets connector is off or the write fails, say so in one line.

## Drug abbreviations

Write drugs by these short forms, never the full generic name. A card code not in this table is written raw and listed once in Verify.

| Drug | Short | Card code |
|---|---|---|
| Amoxicillin-clavulanate | Amoxi-Clav | AMC, AUG |
| Ampicillin | Amp | AMP |
| Piperacillin-tazobactam | Piptaz | TZP, TAZ |
| Ceftriaxone | Ceftri | CRO |
| Cefepime | Cefep | FEP, CPM |
| Cefoxitin | Cefox | FOX |
| Ceftazidime | Ceftaz | CAZ |
| Cefuroxime | Cefu | CXM |
| Ceftazidime-avibactam | Cefta-Avi | CZA, AVI |
| Imipenem | Imi | IPM |
| Meropenem | Mero | MEM, MER |
| Ertapenem | Erta | ETP, ERTA, ERT |
| Amikacin | Amik | AK |
| Gentamicin | Gent | GT, GM |
| Gentamicin high-level (enterococci) | Gent-HL | GT on an enterococcal card |
| Colistin | Col | CS, COL |
| Tigecycline | Tige | TIG, TIGE |
| Fosfomycin | Fos | FOS |
| Nitrofurantoin | Nitro | NIT, FUR |
| Ciprofloxacin | Cipro | CIP |
| Levofloxacin | Levo | LEV |
| Norfloxacin | Norflox | NOR |
| Nalidixic acid | Nal | NA, NAL |
| Trimethoprim-sulfamethoxazole | T/S | T/S, SXT |
| Tetracycline | Tetra | TE |
| Azithromycin | Azith | AZM, AZIT, AZITHRO |
| Aztreonam | Aztr | ATM, AZTREONAM |
| Sulfamethoxazole | Sulfa | |
| Oxacillin | Oxa | OXA |
| Penicillin | Pen | PEN |
| Erythromycin | Erythro | ERY |
| Clindamycin | Clinda | CLIN |
| Linezolid | Line | LIZ, LZD |
| Vancomycin | Vanco | VAN |
| Teicoplanin | Teico | TEIC |
| Fusidic acid | Fus | FUS |
| Rifampin | Rifa | RIF |
| Fluconazole | Fluco | FLUCO |
| Voriconazole | Vorico | VORICO |
| Caspofungin | Caspo | CASPO |
| Micafungin | Mica | MICA |
| Amphotericin B | Ampho | AMPHO |
| Flucytosine | Flucy | FLUCY |

Still unconfirmed, write raw: CTZ (probably ceftolozane-tazobactam), SAM (probably ampicillin-sulbactam). A drug struck out on the card is not reported; note it in Verify.

Phenotype tags from the card itself: Oxa or Cefox R on a staphylococcus is `(MR)`; ESBL, AmpC, CRE only when the sticker or bench note says so.

## Bench shorthand (LAU Medical Center-Rizk Hospital micro lab)

When a new abbreviation turns up, transcribe it raw and list it under Verify.

Media
- BA: blood agar. Col: Columbia blood agar. PV, Choco PV: chocolate PolyViteX agar. Mac: MacConkey agar. Chap: Chapman (mannitol salt) agar, the S. aureus screen plate. Sab: Sabouraud agar, the yeast screen plate. SS: Salmonella-Shigella agar (stool). Schaedler: anaerobic agar. Bactec: broth culture bottle.

Growth marks
- ⊖ or a dash after a plate: no growth. Two ⊖ = read at 24h and 48h, both negative.
- ⊕: growth or positive test. "⊕ on 23/9" on a blood page: the bottle flagged positive that day.
- lac⊕ / lac⊖ / lac±: lactose fermenter / non-fermenter / weak or late.
- "→" followed by a test or plate: next workup step on that colony. "same" after a plate: same growth as the plate above.
- "Id ATB", "IdAG": sent for identification and antibiogram.

Gram stain
- R.: rare; few; mod; num or numerous. PMN, leuco: polymorphs; epith: squamous epithelial cells; no org: no organisms seen.
- GnB: Gram-negative bacilli; GPC: Gram-positive cocci (in clusters, in chains).
- Sputum quality: "<25 PMN/HPF, <10 epith/HPF" style counts are per high-power field.

Organisms and tests
- α strept: viridans streptococci; Nsp, Neiss sp: Neisseria species.
- "colonies ombiliquées" / umbilicated colonies → Opto (R or S): optochin test on umbilicated colonies.
- β-HS: beta-haemolytic streptococci. Hae: Haemophilus. S.a: Staphylococcus aureus; MSSA/MRSA as written.
- BLE: bile esculin; 6.5% NaCl: salt tolerance (enterococcal ID).
- C. Diff Ag: C. difficile antigen (GDH); Toxin A/B: C. difficile toxin. Rota, Adeno: stool rotavirus and adenovirus antigens.

Specimens and sites
- KT: catheter tip. ">15 col" is the semi-quantitative roll-plate count.
- bl ①, bl ②, Blood I, Blood II: first and second set. (cent), (art), (venous), (Right), (Left): draw site.
- Ax, Axill: axilla; Ing: inguinal (surveillance swabs, often labelled "Pus Swab").
- R/O MRSA on a nose page: MRSA screen.
- MYC on the label: mycology request.

Counts
- Urine counts are colonies per millilitre, whether written col/ml or col/l.

Printed label, last line
- Sample code, sex (M/F), I (inpatient) or O (outpatient), then unit codes (e.g. RICU7, BICU3, RCSU4D, R425 B425). Copy unit codes raw.

Screening sticker
- Six rows: ESBL, CRE, MDRO, AmpC, YEAST, STAPH AUREUS. A handwritten "pos" with NEGATIVE blacked out means that row is positive.

Unresolved (transcribe raw, list in Verify)
- "lac⊕ → VCE / JCE / VCG" on screening MacConkey.
- "SS lac⊖" on a stool page: lactose-negative colonies present, or none present.

## Self-check before delivering

- Part A comes first (if a Daily Report was uploaded), then Part B, then Verify.
- Every patient name appears as a Part B header at most once; no specimen appears under two headers.
- Every Daily Report row appears in Part A; matched rows carry their DR number on the Part B specimen line and are not restated.
- Every bench page in the inventory is accounted for in Part B (duplicates noted in Verify); partial edge labels are left out.
- No Daily-Report-only patient or Daily-Report-only specimen appears in Part B or Verify.
- Each AST line has the same number of drugs as its sticker (minus struck-out drugs).
- Positive screening markers are tagged `[SCREEN +]`, never `[SCREEN -]`.
- No `**`, `__`, `#`, em dash or en dash anywhere.
- Every `(?)` in Part B has a matching Verify line.
- The day's `Cultures YYYY-MM-DD` file is in Daily_Cultures, and any older file with the same title has been trashed.
- Every newly finalised specimen is in the Finalised results tab, and no preliminary specimen is.
- Every patient present in both today's and the previous digest shows all of their previous specimens, each marked `Updated` or `Unchanged since`.