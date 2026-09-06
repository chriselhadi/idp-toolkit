#!/usr/bin/env python3
"""Validate synth.py against the grammars. Errors block the build; warnings print.

Usage: validate_synth.py <synth.py> <census.json> <today ISO>   (exit 1 on any error)
"""
import sys, os, re, json, importlib.util, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import jload, iso_from_ddmm

FREQ = r"(OD|BID|TID|QID|q\d+h|x1|weekly|\?)"
ROUTE = r"(IV|PO|IM|inh|IT|SC|PR|topical)"
DATE = r"~?\d{2}/\d{2}"
SEG = r"(%s-(%s)?|x1 %s|\?-)" % (DATE, DATE, DATE)
ABX_RE = re.compile(r"^(?P<drug>[A-Z][A-Za-z0-9/]*)( (?P<route>%s))? (?P<freq>%s) (?P<segs>%s(, %s)*)( \((?P<note>[^()]*)\))?$" % (ROUTE, FREQ, SEG, SEG))
DX_RE = re.compile(r"^(?P<dx>.+?) \((?P<date>\d{2}/\d{2}|prior|chronic|undated)\) \| (?P<facts>.+?) \| (?P<status>.+)$")
MICRO_RE = re.compile(r"^(\d{2}/\d{2}|prior)\b.+")
PEND_RE = re.compile(r"^(?P<item>.+?) \((?P<date>\d{2}/\d{2})(, d\d+)?\)( -> (?P<gate>.+))?$")
UPD_RE = re.compile(r"^(o/n: .+|\d{2}/\d{2}: .+|no change since \d{2}/\d{2} handout|new to service today)$")
FORBID = re.compile(r"\b(consider(ed|ing)?|recommend(s|ed|ation)?|suggest(s|ed)?|advis(e|ed|es)|should|may need|would benefit)\b", re.I)
OWNER = re.compile(r"(\b[A-Z][A-Za-z]{1,7}\b[^.;|]{0,20}\b(plan|rec|asks?|wants?|requests?|to)\b|\bper [A-Z]|\b[A-Z]{2,5} (recommend|suggest|advis)|\bplan\b)")
DASH = "—"


def load_synth(path):
    spec = importlib.util.spec_from_file_location("synth", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def windows(s, n=30):
    s = re.sub(r"\s+", " ", s.lower()).strip()
    return {s[i:i + n] for i in range(0, max(0, len(s) - n + 1))}


def check_forbidden(text, where, errors):
    for m in FORBID.finditer(text):
        before = text[max(0, m.start() - 45):m.start()]
        if not OWNER.search(before):
            errors.append("%s: unattributed '%s' in: %s" % (where, m.group(0), text))


def validate(mod, census, today):
    errors, warns = [], []
    S = getattr(mod, "SYNTH", None)
    if not isinstance(S, dict):
        return ["SYNTH missing or not a dict"], warns
    cens = {p["pid"]: p for p in census["patients"]}
    for pid in cens:
        if pid not in S:
            errors.append("missing entry for %s (%s %s)" % (pid, cens[pid]["room"], cens[pid]["name"]))
    for pid in S:
        if pid not in cens:
            errors.append("entry %s is not on today's census: remove it" % pid)
    for pid, e in S.items():
        w = "%s" % pid
        if not isinstance(e, dict):
            errors.append(w + ": entry not a dict"); continue
        for k in ("name", "one_liner", "updates", "issues", "abx_other", "micro", "vitals", "pendings", "log_im", "log_id"):
            if k not in e:
                errors.append("%s: missing key %s" % (w, k))
        if errors and any(x.startswith(w + ": missing key") for x in errors):
            continue
        if pid in cens and e["name"] != cens[pid]["name"]:
            errors.append("%s: name '%s' differs from census name '%s'" % (w, e["name"], cens[pid]["name"]))
        if "non_id" in e:
            errors.append(w + ": non_id key is not allowed (non-ID lives in the one_liner)")
        ol = e["one_liner"]
        if not isinstance(ol, str) or "IM:" not in ol:
            errors.append(w + ": one_liner must be a string containing 'IM:'")
        else:
            check_forbidden(ol, w + " one_liner", errors)
            if len(ol) > 400: warns.append("%s: one_liner %d chars, long" % (w, len(ol)))
        if not isinstance(e["updates"], list) or not e["updates"]:
            errors.append(w + ": updates must be a non-empty list")
        else:
            for u in e["updates"]:
                if not UPD_RE.match(u): errors.append("%s: update grammar: %s" % (w, u))
                check_forbidden(u, w + " update", errors)
        drugs_seen = {}
        all_abx = []
        for i, iss in enumerate(e["issues"]):
            if not isinstance(iss, dict) or "dx" not in iss or "abx" not in iss:
                errors.append("%s: issue %d must be {dx, abx}" % (w, i + 1)); continue
            if not DX_RE.match(iss["dx"]):
                errors.append("%s: issue grammar '<dx> (<dd/mm|prior|chronic|undated>) | <facts or -> | <status>': %s" % (w, iss["dx"]))
            check_forbidden(iss["dx"], w + " issue", errors)
            if re.search(r"\d{2}/\d{2}-", iss["dx"]):
                errors.append("%s: drug window restated inside issue line: %s" % (w, iss["dx"]))
            for ab in iss["abx"]:
                all_abx.append(("issue%d" % (i + 1), ab))
        for ab in e["abx_other"]:
            all_abx.append(("abx_other", ab))
            warns.append("%s: unlinked antimicrobial in abx_other: %s" % (w, ab))
        for blk, ab in all_abx:
            m = ABX_RE.match(ab)
            if not m:
                errors.append("%s: abx grammar '<Drug> [route] <freq> <seg>[, <seg>] [(note)]': %s" % (w, ab)); continue
            d = m.group("drug")
            if d in drugs_seen:
                errors.append("%s: %s appears twice (%s and %s); every antimicrobial appears exactly once" % (w, d, drugs_seen[d], blk))
            drugs_seen[d] = blk
            if "~" in m.group("segs"): warns.append("%s: approximate AS-list start: %s" % (w, ab))
            if "?" in m.group("segs") or m.group("freq") == "?": warns.append("%s: undocumented freq/start: %s" % (w, ab))
            for seg in m.group("segs").split(", "):
                mm = re.match(r"^~?(\d{2}/\d{2})-~?(\d{2}/\d{2})$", seg)
                if mm:
                    a, b = iso_from_ddmm(mm.group(1), int(today[:4])), iso_from_ddmm(mm.group(2), int(today[:4]))
                    if a and b and b < a: errors.append("%s: segment ends before it starts: %s" % (w, ab))
        for mi in e["micro"]:
            if not MICRO_RE.match(mi): errors.append("%s: micro grammar '<dd/mm|prior> <specimen> <result>': %s" % (w, mi))
            check_forbidden(mi, w + " micro", errors)
        for pe in e["pendings"]:
            if not PEND_RE.match(pe): errors.append("%s: pending grammar '<item> (<dd/mm>[, d<n>]) -> <gate>': %s" % (w, pe))
            check_forbidden(pe, w + " pending", errors)
        for v in e["vitals"]:
            check_forbidden(v, w + " vitals", errors)
        # one fact, one place: 30-char repeats across blocks (updates and logs exempt)
        blocks = {"one_liner": [ol if isinstance(ol, str) else ""], "issues": [i["dx"] for i in e["issues"] if isinstance(i, dict) and "dx" in i],
                  "abx": [ab for _, ab in all_abx], "micro": list(e["micro"]), "vitals": list(e["vitals"]), "pendings": list(e["pendings"])}
        win = {k: set().union(*[windows(s) for s in v]) if v else set() for k, v in blocks.items()}
        keys = list(win)
        for x in range(len(keys)):
            for y in range(x + 1, len(keys)):
                rep = win[keys[x]] & win[keys[y]]
                if rep:
                    errors.append("%s: same fact in %s and %s: '...%s...'" % (w, keys[x], keys[y], sorted(rep)[0]))
        alltext = json.dumps(e, ensure_ascii=False)
        if DASH in alltext or "–" in alltext:
            errors.append(w + ": em/en dash present; use comma, colon, parentheses or a new sentence")
        size = sum(len(s) for s in [ol] + e["updates"] + [i.get("dx", "") for i in e["issues"] if isinstance(i, dict)] +
                   [ab for _, ab in all_abx] + e["micro"] + e["vitals"] + e["pendings"])
        if size > 1400: warns.append("%s: rendered block about %d chars, written in prose? rewrite tighter" % (w, size))
    for f in getattr(mod, "FLAGS_EXTRA", []):
        if DASH in f: errors.append("FLAGS_EXTRA: em dash")
    for o in getattr(mod, "OBSERVATIONS", []):
        if not isinstance(o, dict) or set(o) < {"date", "text", "mine"}: errors.append("OBSERVATIONS entries need date, text, mine")
    return errors, warns


def main():
    mod = load_synth(sys.argv[1]); census = jload(sys.argv[2]); today = sys.argv[3]
    errors, warns = validate(mod, census, today)
    for x in warns: print("WARN", x)
    for x in errors: print("ERROR", x)
    print("validate: %d errors, %d warnings" % (len(errors), len(warns)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
