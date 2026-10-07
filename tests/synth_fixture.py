"""Synth fixture for the two-day e2e dry run (fictional patients, no doses anywhere).

Copied to <workdir>/synth.py. Entries are written by name; pids come from out/census.json next to
this file, so one file serves day 1 (2026-09-06) and day 2 (2026-09-07). PID maps name -> pid so a
test can patch a copy (see run_e2e.sh, dose checks).
"""
import os, json

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "out", "census.json"), encoding="utf-8") as _f:
    _CENSUS = json.load(_f)
DAY = _CENSUS["date"]
D1, D2 = "2026-09-06", "2026-09-07"
PID = {p["name"]: p["pid"] for p in _CENSUS["patients"] + _CENSUS.get("cs_id_offlist", [])}
STATUS = "afebrile since 04/09 | no pressors | RA"


def entry(name, one_liner, issues=(), abx_other=(), micro=(), vitals=(STATUS,), pendings=(), updates=None,
          log_id="", **extra):
    """One SYNTH entry with the default 'new today' / 'no change' update for the day."""
    e = {"name": name, "one_liner": one_liner,
         "updates": updates or (["new to service today"] if DAY == D1 else ["no change since 06/09 handout"]),
         "issues": [{"dx": dx, "abx": list(abx)} for dx, abx in issues], "abx_other": list(abx_other),
         "micro": list(micro), "vitals": list(vitals), "pendings": list(pendings), "log_im": "", "log_id": log_id}
    e.update(extra)
    return e


ALPHA = entry(
    "Alpha Tester One", "70M, HTN, CKD3; adm 27/08 via ER, 7th fl; IM: none active.",
    issues=[("Urosepsis (27/08) | UCx ESBL E.coli 04/09 | on Mero, AMS: stop date to document",
             ["Mero IV q8h 03/09-", "Vanco IV x1 x1 03/09"])],
    micro=["04/09 UCx E.coli ESBL"],
    micro_recap="UCx 04/09 E. coli ESBL, S Mero",
    vitals=["Tmax 38.6 06/09 | no pressors | RA"],
    pendings=["BCx (06/09) -> Mero stop date"],
    im_detail=["CKD3, creatinine at baseline", "HTN controlled on home regimen"],
    conflicts=["Mero start: ward doc 03/09, AMS sheet 02/09"],
    not_applied={"Vanco": "ID asked for a single shot 03/09, a repeat order was found 05/09"},
    updates=["o/n: febrile 38.6", "new to service today"] if DAY == D1 else ["07/09: afebrile, BCx no growth so far"],
    log_id="06/09: Mero q8h since 03/09 for ESBL urosepsis; BCx 06/09 pending.")

ENTRIES = [
    ((D1, D2), ALPHA),
    ((D1, D2), entry("Bravo Tester Two", "55F, DM2; adm 27/08, ICU4B; IM: none active.",
                     issues=[("HAP (29/08) | improving | ICU plan 04/09: stop D7", ["Piptazo IV q6h 29/08-"])])),
    ((D1, D2), entry("Charlie Tester Three", "80, no ward row (roster and AS list only); adm 28/08, 4th fl; IM: none documented.",
                     issues=[("Infection undetermined (undated) | - | on Erta per AS list, no ward detail", ["Erta OD ~29/08-"])])),
    ((D1,), entry("FOXTROT TESTER SIX", "66, AS list only, no ward row, not on roster; adm 26/08, CSU2D; IM: none documented.",
                  abx_other=["Zavi IV q8h ~03/09-"])),
    # Golf's day-1 record is slimmed in the state before day 2 (run_e2e.sh): render_wa must not crash
    ((D1, D2), entry("Golf Tester Seven", "40M; adm ?, 3rd fl; IM: none active.",
                     issues=[("Cellulitis L leg (01/09) | improving | on Augmentin", ["Augmentin PO BID 01/09-"])],
                     updates=None if DAY == D1 else ["07/09: back on the list, record rebuilt from the ward doc"])),
    ((D1, D2), entry("Hotel Tester Eight", "62M, NSTEMI, CCU2; IM: cardiology primary.",
                     issues=[("Line infection (05/09) | BCx sent | on Vanco per cardiology", ["Vanco IV q12h 05/09-"])],
                     pendings=["BCx (05/09) -> Vanco duration"])),
    ((D1, D2), entry("India Tester Nine", "55F, ER, bed pending; IM: none documented.",
                     issues=[("Fever undetermined (06/09) | - | no antimicrobial yet", [])])),
    ((D1, D2), entry("Mike Tester Eleven", "48M, DM2, 3rd fl; IM: DM2 on insulin.",
                     issues=[("Diabetic foot infection (02/09) | swab sent | on Clinda PO", ["Clinda PO TID 02/09-"])],
                     pendings=["Wound swab (02/09) -> narrow"])),
    ((D1, D2), entry("November Tester Twelve", "71F, COPD, 4th fl; IM: COPD.",
                     issues=[("CAP (04/09) | CXR RLL consolidation | on Ceftriax, improving", ["Ceftriax IV OD 04/09-"])])),
    ((D1, D2), entry("Oscar Tester Fourteen", "66M, 3rd fl, AS bed blank; IM: none documented.",
                     issues=[("HAP (01/09) | - | on Cefe per AS list", ["Cefe IV q8h ~01/09-"])])),
    ((D1,), entry("RANIYA Kilo JULIET", "59F, 7th fl; IM: none active.",
                  issues=[("Pyelonephritis (03/09) | UCx pending | on Cipro", ["Cipro IV q12h ~03/09-"])],
                  pendings=["UCx (03/09) -> oral switch"])),
    ((D2,), entry("Lima Tester Ten", "45F, adm 07/09, 2nd fl; IM: none active.",
                  issues=[("Pyelonephritis (07/09) | UCx sent | on Ceftriax", ["Ceftriax IV OD ~07/09-"])],
                  pendings=["UCx (07/09) -> narrow"], updates=["new to service today"])),
]
SYNTH = {PID[e["name"]]: e for days, e in ENTRIES if DAY in days}

_OFF = {"Papa Tester Fifteen": "Line infection, ID signed off 05/09, ICU team following cultures.",
        "RANIYA Kilo JULIET": "Pyelonephritis, off the ID list 07/09 after oral switch."}
# an unexpected off-list name gets no one-liner, so validate_synth.py reports it
SIGNED_OFF = {o["pid"]: _OFF.get(o["name"], "") for o in _CENSUS.get("cs_id_offlist", [])}
FLAGS_EXTRA = []
OBSERVATIONS = [{"date": DAY, "text": "dry run", "mine": True}]
