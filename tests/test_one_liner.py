#!/usr/bin/env python3
"""The one-liner's shape check (validate_synth.one_liner_shape). Invented text only. Run: python3 tests/test_one_liner.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "idp", "idp"))
from validate_synth import one_liner_shape, one_liner_segments


def check(ol):
    e, w = [], []
    one_liner_shape(ol, "P1", e, w)
    return e, w


assert one_liner_segments("70M, a (b; c) ; adm 01/10 ; IM: x") == ["70M, a (b; c)", "adm 01/10", "IM: x"]
e, w = check("71M, DM2, CKD 3b ; prior adm 01/2026 urosepsis ; adm 02/11 via ER w/ fever ; IM: insulin")
assert not e and not w, (e, w)
e, w = check("4F, cerebral palsy ; adm 05/11 to PICU w/ vomiting, IM: NPO")
assert e and "own last segment" in e[0], e
e, w = check("4F, cerebral palsy, prior adm 01/2025 ; adm 05/11 to PICU ; IM: NPO")
assert not e and any("earlier stays" in x for x in w), w
e, w = check("no age here ; something else ; IM: none")
assert not e and len(w) == 3, w
print("ONE-LINER TESTS OK")
