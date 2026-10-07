#!/usr/bin/env python3
"""Synthetic fixture (fictional names, example.org addresses) for the two-day end-to-end dry run.

Usage: make_fixture.py <workdir> <today ISO>      today is 2026-09-06 (day 1) or 2026-09-07 (day 2)

Writes <workdir>/in/:
  as.eml        AS list email: today's list as an XLSX attachment "AS list DD.MM.YYYY.XLSX", and the
                HTML body quoting YESTERDAY's list inside a Gmail-style quoted reply (the parser must
                pick the attachment, never the quoted table)
  wards.json    ward handoff rows (parse_wards.py output format)
  ams.json      AMS workbook blocks
  roster.txt    day 1 only: the ID Active Patients roster lines
  id_email.txt  day 2 only: the plain-text ID Active Patients email (email_roster.py makes roster.txt)
"""
import sys, os, io, json
from email.message import EmailMessage
import openpyxl

work, today = sys.argv[1], sys.argv[2]
DAY = {"2026-09-06": 1, "2026-09-07": 2}[today]
IN = os.path.join(work, "in")
os.makedirs(IN, exist_ok=True)


def dump(name, obj):
    with open(os.path.join(IN, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


def write(name, text):
    with open(os.path.join(IN, name), "w", encoding="utf-8") as f:
        f.write(text)


# ---- AS list rows: (MRN, name, age, bed, order description, duration, unit, valid from, admission) ----
MERO = "MERONEM 1 g INJ, I-VENOUS, 1000 MG (MEROPENEM), Q8H"
BASE = [
    ("100001", "ALPHA TESTER ONE", "70", "B708B", MERO + "5-13-21", "48", "H", "03/09/2026", "27/08/2026"),
    ("100001", "ALPHA TESTER ONE", "70", "B708B", "VANCOLON 500MG INJ, I-VENOUS, 1250 MG (VANCOMYCIN), ONCE", "1", "DOS", "03/09/2026", "27/08/2026"),
    ("100002", "BRAVO TESTER TWO", "55", "BICU4B", "PIPERACILLIN 4 g /TAZOBACTAM 0.5g INJ, I-VENOUS, 4.5 G (PIPERACILLIN/TAZOBACTAM), Q6H", "8808", "H", "29/08/2026", "27/08/2026"),
    ("100003", "CHARLIE TESTER THREE", "80", "B425", "INVANZ 1 g INJ, I-VENOUS, 1000 MG (ERTAPENEM), Q24H(18)", "768", "H", "29/08/2026", "28/08/2026"),
    ("100004", "DELTA SHOT ONLY", "60", "B301A", "AMICINE (AMIKACIN) 500MG INJ, I-VENOUS, 1000 MG (AMIKACIN), ONCE", "1", "DOS", "03/09/2026", "02/09/2026"),
    ("100005", "ECHO TESTER FIVE", "8", "BPICU2", MERO, "48", "H", "03/09/2026", "02/09/2026"),
    ("100006", "FOXTROT TESTER SIX", "66", "BCSU2D", "ZAVICEFTA 2.5 G INJECTABLE, I-VENOUS, 2.5 G (CEFTAZIDIME/AVIBACTAM), Q8H", "48", "H", "03/09/2026", "26/08/2026"),
    # bed "?" (empty bed): the roster room 312 must be kept
    ("100014", "OSCAR TESTER FOURTEEN", "66", "?", "CEFEPIME 2 g INJ, I-VENOUS, 2 G (CEFEPIME), Q8H", "48", "H", "01/09/2026", "31/08/2026"),
]
RANIYA = ("100011", "RANIYA KILO JULIET", "59", "B707A", "CIPROFLOXACIN 400MG INJ, I-VENOUS, 400 MG (CIPROFLOXACIN), Q12H", "48", "H", "03/09/2026", "02/09/2026")
LIMA = ("100010", "LIMA TESTER TEN", "45", "B206", "CEFTRIAXONE 2 g INJ, I-VENOUS, 2 G (CEFTRIAXONE), Q24H", "48", "H", "07/09/2026", "07/09/2026")
QUOTED_ONLY = ("100090", "QUEBEC QUOTED ONLY", "50", "B610", MERO, "48", "H", "01/09/2026", "30/08/2026")
AS_LISTS = {
    "2026-09-05": BASE[:3] + [QUOTED_ONLY],   # only ever seen quoted, inside day 1's reply
    "2026-09-06": BASE + [RANIYA],
    "2026-09-07": BASE + [LIMA],              # Raniya is off the AS list on day 2
}
HDR = ["MRN", "Ordering Physician Name", "Patient Name", "Age/(Day-Month-Year)", "Day/Month/Year", "Patient Weight",
       "Patient Weight Unit", "Bed", "Description of Order", "Order Duration", "Order Duration Unit", "Valid From Date",
       "Valid To Date", "Creatinine clearance", "Admission Date", "Template Name", "Template ID", "Order Number"]


def dmy(iso, sep="/"):
    return sep.join((iso[8:10], iso[5:7], iso[:4]))


def as_cells(r, list_day):
    return [r[0], "Dr Test", r[1], r[2], "Y", "70", "KG", r[3], r[4], r[5], r[6], r[7], dmy(list_day), "80 mL/min", r[8], "", "", "1"]


def as_html_table(list_day):
    tr = lambda cells: "<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in cells)
    return "<table>%s%s</table>" % (tr(HDR), "".join(tr(as_cells(r, list_day)) for r in AS_LISTS[list_day]))


def as_xlsx(list_day):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "AS list"
    ws.append(HDR)
    for r in AS_LISTS[list_day]:
        ws.append(as_cells(r, list_day))
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


yday = {1: "2026-09-05", 2: "2026-09-06"}[DAY]
html = ("<html><body><p>Dear All, kindly find attached today's AS list.</p>"
        '<div class="gmail_quote"><div>On %s at 08:02, Pharmacy &lt;pharmacy@example.org&gt; wrote:</div>'
        '<blockquote style="margin:0 0 0 .8ex"><p>Dear All, kindly find today\'s AS list.</p>%s</blockquote></div>'
        "</body></html>") % (dmy(yday), as_html_table(yday))
msg = EmailMessage()
msg["Subject"] = "RE: AS List %s" % dmy(yday, ".")   # stale subject date, as in a reply thread
msg["From"] = "pharmacy@example.org"; msg["To"] = "id-team@example.org"
msg["Date"] = {1: "Sun, 06 Sep 2026", 2: "Mon, 07 Sep 2026"}[DAY] + " 08:10:00 +0300"
msg.set_content("Dear All, kindly find attached today's AS list.")
msg.add_alternative(html, subtype="html")
msg.add_attachment(as_xlsx(today), maintype="application", subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   filename="AS list %s.XLSX" % dmy(today, "."))
with open(os.path.join(IN, "as.eml"), "wb") as f:
    f.write(bytes(msg))


# ---- Ward handoff rows ----
def row(doc, room, name, cells, text="", id_consult=False, section=""):
    return {"doc": doc, "section": section, "room": room, "name": name, "cells": cells, "text": text,
            "dated_lines": [], "id_consult": id_consult, "uc_id": False, "active": []}


wards = [
    row("floors", "708B", "Alpha Tester One", {"HDR": "70M, HTN, CKD3", "MEDS": "Mero 1g q8h since 03/09", "PENDINGS": "BCx 06/09 pending",
        "SYNTHESIS": "Adm 27/08 for urosepsis. 06/09: febrile 38.6 o/n, UCx ESBL E.coli reported 04/09."}),
    row("icu", "ICU4B", "Bravo Tester Two", {"HDR": "55F, DM2", "MEDS": "Piptazo 4.5g q6h 29/08-", "PENDINGS": "-",
        "SYNTHESIS": "HAP 29/08, improving, ICU team plans stop D7 per note 04/09."}),
    row("floors", "302", "Golf Tester Seven", {"HDR": "40M", "MEDS": "Augmentin PO BID 01/09-", "PENDINGS": "-", "SYNTHESIS": "Cellulitis left leg, improving."}),
    row("cardio", "CCU2", "Hotel Tester Eight", {"HDR": "62M, NSTEMI", "SYNTHESIS": "Line infection suspected 05/09, BCx sent."}, section="CCU"),
    row("floors", "311", "Mike Tester Eleven", {"HDR": "48M, DM2", "SYNTHESIS": "Diabetic foot, wound swab 02/09."}),
    # ward doc says 411, the roster says 409: one patient, one pid, the list room kept
    row("floors", "411", "November Tester Twelve", {"HDR": "71F, COPD", "SYNTHESIS": "CAP 04/09 on ceftriaxone."},
        text="06/09: ID consulted, CAP improving", id_consult=True),
    row("floors", "?", "Oscar Tester Fourteen", {"HDR": "66M", "SYNTHESIS": "HAP 01/09."}),
    # ID consulted in the ICU handoff, never on the ID list: SIGNED_OFF one-liner only
    row("icu", "ICU6B", "Papa Tester Fifteen", {"HDR": "77M", "SYNTHESIS": "Line infection, ID signed off 05/09."},
        text="06/09: ID consulted earlier for line infection", id_consult=True),
]
if DAY == 1:
    wards.append(row("floors", "707A", "Raniya Kilo Juliet", {"HDR": "59F", "SYNTHESIS": "Pyelonephritis 03/09 on cipro."}))
else:
    # spelling variant of the day-1 patient (off the ID list today) in another room: no new pid may be minted
    wards.append(row("floors", "405", "Rania Juliet", {"HDR": "59F", "SYNTHESIS": "Pyelonephritis, oral switch 07/09."},
                     text="07/09: ID consulted, oral switch", id_consult=True))
dump("wards.json", wards)
dump("ams.json", [
    {"name": "Alpha Tester One", "mrn": "100001", "fellow": "CH", "last_date": "2026-09-04", "text": "Mero for ESBL urosepsis", "todos": ["document stop date"]},
    {"name": "Bravo Tester Two", "mrn": "100002", "fellow": "MA", "last_date": "2026-08-30", "text": "Piptazo HAP", "todos": []}])

# ---- ID Active Patients ----
if DAY == 1:
    write("roster.txt", "\n".join([
        "*708B Alpha Tester One (UC)* CH",
        "ICU4 Bravo Tester Two MA",
        "425 Charlie Tester Three (new) MJ",
        "302 Golf Tester Seven CH",
        "CCU2 Hotel Tester Eight MJ",
        "ER IN India Tester Nine ?",
        "311 Mike Tester Eleven ?",
        "409 November Tester Twelve CH",
        "312 Oscar Tester Fourteen MA",
        "707A RANIYA Kilo JULIET MA",
    ]) + "\n")
else:
    # Real-email shape: roster lines (no roster block), a consult note opening with a name,
    # then *Updates* with a first-name line. Raniya is not mentioned: OFF today.
    write("id_email.txt", "\n".join([
        "Good morning all,", "",
        "*708B Alpha Tester One (UC)* CH",
        "ICU4B Bravo Tester Two MA",
        "425 Charlie Tester Three MJ",
        "302 Golf Tester Seven CH",
        "CCU2 Hotel Tester Eight MJ",
        "ER IN India Tester Nine ?",
        "311 Mike Tester Eleven",
        "409 November Tester Twelve CH",
        "312 Oscar Tester Fourteen MA", "",
        "Lima Tester Ten Admitted today with fever and flank pain, UCx sent, on ceftriaxone.", "",
        "*Updates*",
        "Alpha",
        "Afebrile today, BCx no growth so far.", "",
        "Fellow on call",
    ]) + "\n")
print("fixture day %d written to %s" % (DAY, work))
