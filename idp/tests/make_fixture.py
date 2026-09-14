#!/usr/bin/env python3
"""Synthetic fixture (fictional names) for an end-to-end dry run. Usage: make_fixture.py <workdir> <today ISO>"""
import sys, os, json, email, base64
from email.message import EmailMessage

work, today = sys.argv[1], sys.argv[2]
os.makedirs(os.path.join(work, "in"), exist_ok=True)
d, m, y = today[8:10], today[5:7], today[:4]
rows = [
    ("100001", "ALPHA TESTER ONE", "70", "B708B", "MERONEM 1 g INJ, I-VENOUS, 1000 MG (MEROPENEM), Q8H5-13-21", "48", "H", "03/09/2026", "27/08/2026"),
    ("100001", "ALPHA TESTER ONE", "70", "B708B", "VANCOLON 500MG INJ, I-VENOUS, 1250 MG (VANCOMYCIN), ONCE", "1", "DOS", "03/09/2026", "27/08/2026"),
    ("100002", "BRAVO TESTER TWO", "55", "BICU4B", "PIPERACILLIN 4 g /TAZOBACTAM 0.5g INJ, I-VENOUS, 4.5 G (PIPERACILLIN/TAZOBACTAM), Q6H", "8808", "H", "29/08/2026", "27/08/2026"),
    ("100003", "CHARLIE TESTER THREE", "80", "B425", "INVANZ 1 g INJ, I-VENOUS, 1000 MG (ERTAPENEM), Q24H(18)", "768", "H", "29/08/2026", "28/08/2026"),
    ("100004", "DELTA SHOT ONLY", "60", "B301A", "AMICINE (AMIKACIN) 500MG INJ, I-VENOUS, 1000 MG (AMIKACIN), ONCE", "1", "DOS", "03/09/2026", "02/09/2026"),
    ("100005", "ECHO TESTER FIVE", "8", "BPICU2", "MERONEM 1 g INJ, I-VENOUS, 1000 MG (MEROPENEM), Q8H", "48", "H", "03/09/2026", "02/09/2026"),
    ("100006", "FOXTROT TESTER SIX", "66", "BCSU2D", "ZAVICEFTA 2.5 G INJECTABLE, I-VENOUS, 2.5 G (CEFTAZIDIME/AVIBACTAM), Q8H", "48", "H", "03/09/2026", "26/08/2026"),
]
hdr = ["MRN", "Ordering Physician Name", "Patient Name", "Age/(Day-Month-Year)", "Day/Month/Year", "Patient Weight", "Patient Weight Unit", "Bed",
       "Description of Order", "Order Duration", "Order Duration Unit", "Valid From Date", "Valid To Date", "Creatinine clearance", "Admission Date", "Template Name", "Template ID", "Order Number"]
tr = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in [r[0], "Dr X", r[1], r[2], "Y", "70", "KG", r[3], r[4], r[5], r[6], r[7], "05/09/2026", "80 mL/min", r[8], "", "", "1"]) for r in rows)
html = "<html><body><p>Dear All, kindly find today's AS list.</p><table><tr>%s</tr>%s</table></body></html>" % ("".join("<td>%s</td>" % h for h in hdr), tr)
msg = EmailMessage(); msg["Subject"] = "AS List %s.%s.%s" % (d, m, y); msg["From"] = "pharm@laumcrh.com"; msg["To"] = "chriselhadi@gmail.com"
msg.set_content("see html"); msg.add_alternative(html, subtype="html")
open(os.path.join(work, "in", "as.eml"), "wb").write(bytes(msg))
open(os.path.join(work, "in", "roster.txt"), "w").write("*708B Alpha Tester One (UC) CH*\nICU4 Bravo Tester Two MA\n425 Charlie Tester Three (new) MJ\n302 Golf Tester Seven CH\n")
wards = [
    {"doc": "floors", "room": "708B", "name": "Alpha Tester One", "cells": {"HDR": "70M, HTN, CKD3", "MEDS": "Mero 1g q8h since 03/09", "PENDINGS": "BCx %s/%s pending" % (d, m), "SYNTHESIS": "Adm 27/08 for urosepsis. %s/%s: febrile 38.6 o/n, UCx ESBL E.coli reported 04/09." % (d, m)}, "active": []},
    {"doc": "icu", "room": "ICU4B", "name": "Bravo Tester Two", "cells": {"HDR": "55F, DM2", "MEDS": "Piptazo 4.5g q6h 29/08-", "PENDINGS": "-", "SYNTHESIS": "HAP 29/08, improving, ICU team plans stop D7 per note 04/09."}, "active": []},
    {"doc": "floors", "room": "302", "name": "Golf Tester Seven", "cells": {"HDR": "40M", "MEDS": "Augmentin PO BID 01/09-", "PENDINGS": "-", "SYNTHESIS": "Cellulitis left leg, improving."}, "active": []},
]
json.dump(wards, open(os.path.join(work, "in", "wards.json"), "w"))
ams = [{"name": "Alpha Tester One", "mrn": "100001", "fellow": "CH", "last_date": "2026-09-04", "text": "Mero for ESBL urosepsis", "todos": ["document stop date"]},
       {"name": "Bravo Tester Two", "mrn": "100002", "fellow": "MA", "last_date": "2026-08-30", "text": "Piptazo HAP", "todos": []}]
json.dump(ams, open(os.path.join(work, "in", "ams.json"), "w"))
print("fixture written to", work)
