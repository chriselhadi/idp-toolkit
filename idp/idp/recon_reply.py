#!/usr/bin/env python3
"""Read Chris's reply to the daily ID Reconciliation email (Chris, 28.11.2026).

Usage:
  recon_reply.py <reply_plain.txt> <yesterday_recon.json> <outdir> --date YYYY-MM-DD
                 [--rules-tab <Learned Rules get_values json>] [--answered-tab <Answered Items get_values json>]

reply_plain.txt is the plain text of the reply (Gmail plaintextBody); quoted lines start with ">" (or "> >").
Read from the unquoted lines:
  "N: answer", "N. answer", "N) answer", "N - answer"   answer to item N of yesterday's recon.json
  lines written directly under a quoted "N. ..." item   answer to item N (consecutive lines joined)
  "RULE: text" (any case)                               a general rule; under an item ("N: RULE: text") it is
                                                        a rule learned from that item
  "L2: undo" (or "2: undo" when 2 is a learned rule)    drop learned rule L2
Gmail's "On <date> ... wrote:" line and a signature after "-- " are ignored.

Writes to outdir:
  chris_answers.json  {"answers": [{n, key, item, answer}], "rules": [text], "undo": ["L2"], "unparsed": [line]}
  chris_answers.txt   the same, readable
  resolved_add.json   [{key, until: ""}] per answered item (merged into the resolved list)
  answered_rows.json  rows to append to 'Answered Items': Key | Date answered | Item | Chris answer | Applied as | Until
  rule_rows.json      rows to append to 'Learned Rules': No | Date | Rule | From | Status | Notes
                      (No continues after the highest existing one, Status active, From "RULE" or the item key)
  undo_ops.json       update_values ops [{range, values}] setting Status "undone" on the undone rules
                      (needs --rules-tab for the row numbers; undone rules not found there are listed in chris_answers)
Prints "REPLY OK: a answers, r rules, u undo, x unparsed". Exit 2 on bad input.
"""
import argparse, datetime as dt, json, os, re, sys

NUM = re.compile(r"^\s*\(?(L?\d{1,3})\s*(?::\s*|[.)]\s+|\s+-\s+|\s+(?=undo\b))(.*)$", re.I)
RULE = re.compile(r"^\s*rule\s*:\s*(.*\S)\s*$", re.I)
QITEM = re.compile(r"^(L?\d{1,3})\.\s+(.*)$", re.I)
KEY = re.compile(r"\[(k[0-9a-f]{8})\]\s*$")
WROTE_START = re.compile(r"^\s*On\s.+")
UNDO = re.compile(r"^\s*undo\b[\s.!]*$", re.I)


def tab_rows(p, first):
    """[(sheet row number, cells)] of a get_values JSON, header row (first cell == `first`) skipped."""
    if not p or not os.path.exists(p):
        return []
    o = json.load(open(p, encoding="utf-8"))
    rows = o.get("values") if isinstance(o, dict) else o
    out = []
    for i, r in enumerate(rows or [], 1):
        r = [("" if c is None else str(c)).strip().lstrip("'").strip() for c in r]
        if i == 1 and r and r[0].lower() == first.lower():
            continue
        out.append((i, r + [""] * 6))
    return out


def quote_depth(line):
    m = re.match(r"^((?:\s*>)+)\s?(.*)$", line)
    return (m.group(1).count(">"), m.group(2)) if m else (0, line)


def parse(text, items, learned_nums):
    """items: {n: {n, key, text}}; learned_nums: set of "L<No>". Returns answers {n: [text]}, rules [(text, from)],
    undo [Ln], unparsed [line]."""
    answers, rules, undo, unparsed = {}, [], [], []
    by_key = {it["key"]: n for n, it in items.items() if it.get("key")}
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ctx = None          # ("item", n) or ("rule", "L2"): the quoted item the unquoted lines below answer
    in_sig = False
    i = 0
    while i < len(lines):
        raw = lines[i]; i += 1
        depth, body = quote_depth(raw)
        if depth:
            in_sig = False
            b = body.strip()
            m = QITEM.match(b)
            if m:
                tag = m.group(1).upper()
                k = KEY.search(b)
                if tag.startswith("L"):
                    ctx = ("rule", tag)
                elif k and k.group(1) in by_key:
                    ctx = ("item", by_key[k.group(1)])
                else:
                    ctx = ("item", int(tag)) if int(tag) in items else None
            elif not b or b.isupper() or b.startswith(("- ", "HOW TO ANSWER")) or re.match(r"^[A-Z ,]+\(\d+\)$", b):
                ctx = None   # blank quoted line, section heading, bullet or footer: the item ended
            continue         # a wrapped continuation of the quoted item keeps ctx
        s = body.rstrip()
        if s.strip() in ("--", "-- "):
            in_sig = True; continue
        if in_sig or not s.strip():
            continue
        # Gmail header "On Sat, 28 Nov 2026 at 07:10, X <x@y> wrote:" (may wrap onto the next line)
        if WROTE_START.match(s) and (s.rstrip().endswith("wrote:") or
                                     (i < len(lines) and lines[i].rstrip().endswith("wrote:") and not quote_depth(lines[i])[0])):
            if not s.rstrip().endswith("wrote:"):
                i += 1
            ctx = None
            continue
        m = RULE.match(s)
        if m:
            src = items[ctx[1]]["key"] if ctx and ctx[0] == "item" else "RULE"
            rules.append((m.group(1), src))
            if src != "RULE":   # a rule written under an item also answers it
                answers.setdefault(ctx[1], []).append(s.strip())
            continue
        m = NUM.match(s)
        if m:
            tag, ans = m.group(1).upper(), m.group(2).strip()
            if tag.startswith("L"):
                if UNDO.match(ans) and tag in learned_nums:
                    undo.append(tag)
                else:
                    unparsed.append(s.strip())
                continue
            n = int(tag)
            if UNDO.match(ans) and ("L%d" % n) in learned_nums:   # "undo" only ever answers a learned rule
                undo.append("L%d" % n); continue
            if n in items and ans:
                mr = RULE.match(ans)
                if mr:
                    rules.append((mr.group(1), items[n]["key"]))
                answers.setdefault(n, []).append(ans)
                continue
            if ctx is None:
                unparsed.append(s.strip()); continue
        if ctx:
            kind, ref = ctx
            if kind == "rule":
                if UNDO.match(s):
                    undo.append(ref) if ref in learned_nums else unparsed.append("%s: %s" % (ref, s.strip()))
                continue
            answers.setdefault(ref, []).append(s.strip())
    return answers, rules, list(dict.fromkeys(undo)), unparsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reply"); ap.add_argument("recon"); ap.add_argument("outdir")
    ap.add_argument("--date", required=True)
    ap.add_argument("--rules-tab"); ap.add_argument("--answered-tab")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.date)
    dmy = "'" + today.strftime("%d/%m/%y")
    try:
        rec = json.load(open(a.recon, encoding="utf-8"))
        text = open(a.reply, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        print("REPLY FAILED: %s" % e); return 2
    items = {}
    for i, x in enumerate(rec.get("need") or [], 1):
        x = x if isinstance(x, dict) else {"n": i, "key": "", "text": x}
        items[int(x.get("n") or i)] = {"n": int(x.get("n") or i), "key": x.get("key", ""), "text": x.get("text", "")}
    rules_tab = tab_rows(a.rules_tab, "No")
    active = {"L" + r[0].upper().lstrip("L"): row for row, r in rules_tab if r[0] and r[4].lower() in ("", "active")}
    learned_nums = set(active) | {r.get("n", "") for r in rec.get("learned") or []}
    answers, rules, undo, unparsed = parse(text, items, learned_nums)

    ans = [{"n": n, "key": items[n]["key"], "item": items[n]["text"], "answer": " ".join(v)} for n, v in sorted(answers.items())]
    out = {"answers": ans, "rules": [t for t, _ in rules], "undo": undo, "unparsed": unparsed,
           "rule_sources": [{"rule": t, "from": src} for t, src in rules],
           "undo_not_in_tab": [u for u in undo if u not in active] if a.rules_tab else []}
    os.makedirs(a.outdir, exist_ok=True)
    J = lambda name, o: json.dump(o, open(os.path.join(a.outdir, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    J("chris_answers.json", out)
    J("resolved_add.json", [{"key": x["key"], "until": ""} for x in ans if x["key"]])
    have = {r[0] for _, r in tab_rows(a.answered_tab, "Key")}
    J("answered_rows.json", [[x["key"], dmy, x["item"], x["answer"], "", ""] for x in ans if x["key"] and x["key"] not in have])
    nums = [int(r[0].upper().lstrip("L")) for _, r in rules_tab if re.fullmatch(r"L?\d+", r[0], re.I)]
    nums += [int(r["n"][1:]) for r in rec.get("learned") or [] if re.fullmatch(r"L\d+", r.get("n", ""))]
    nxt = max(nums or [0]) + 1
    J("rule_rows.json", [[nxt + j, dmy, t, src, "active", ""] for j, (t, src) in enumerate(rules)])
    J("undo_ops.json", [{"range": "'Learned Rules'!E%d" % active[u], "values": [["undone"]]} for u in undo if u in active])

    tl = ["Chris's answers to the ID Reconciliation of %s, read %s" % (rec.get("date", "yesterday"), a.date), ""]
    tl += ["ANSWERS (%d)" % len(ans)] + ["%d. [%s] %s\n   Chris: %s" % (x["n"], x["key"], x["item"], x["answer"]) for x in ans] or ["none"]
    tl += ["", "RULES (%d)" % len(rules)] + ["- %s (%s)" % (t, "general" if src == "RULE" else "from item " + src) for t, src in rules]
    tl += ["", "UNDO (%d)" % len(undo)] + ["- " + u for u in undo]
    tl += ["", "UNPARSED (%d)" % len(unparsed)] + ["- " + u for u in unparsed]
    open(os.path.join(a.outdir, "chris_answers.txt"), "w", encoding="utf-8").write("\n".join(tl) + "\n")
    print("REPLY OK: %d answers, %d rules, %d undo, %d unparsed" % (len(ans), len(rules), len(undo), len(unparsed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
