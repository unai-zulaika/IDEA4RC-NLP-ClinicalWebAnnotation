#!/usr/bin/env python3
"""Aggregate metrics for the head and neck paper from scored sessions (no note text is read or written).

Correct  = match / (match + mismatch), fields where the gold has a value and the model gave one.
Invented = false_positive / (false_positive + both_empty), fields where the gold is empty.
95% CIs by bootstrap over patients (2000 resamples, seed 42). McNemar exact test on paired cells.

usage: hnc_metrics.py OUT.json label=session.json [label=session.json ...]
"""
import json
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict

STAGE = {
    "Before treatment": ["smoking-status", "alcohol-habits", "before-treatment-patient-diagnosed",
                         "hpv-status", "plasmatic-ebv-dna-status"],
    "Tumour at diagnosis": ["histological-tipo", "tumorsite", "clinical-tnmstaging", "pathological-tnmstaging",
                            "staging-classification", "tumorbiopsytype", "surgical-specimen-grading"],
    "Treatment": ["radiotherapy_start", "radiotherapy_end", "radiotherapy_location", "beam-quality",
                  "chemotherapy_start", "systemic-treatment-started", "systemic-treatment-ended",
                  "neck-surgery-laterality", "surgery-reconstruction", "surgerymargins"],
    "Follow-up": ["patient-status", "last-followup-date", "disease-status", "site-of-metastatic"],
}
STAGE_OF = {v: s for s, vs in STAGE.items() for v in vs}
DATES = {"radiotherapy_start", "radiotherapy_end", "chemotherapy_start", "systemic-treatment-started",
         "systemic-treatment-ended", "last-followup-date"}
B = 2000
STRICT = os.environ.get("HNC_STRICT") == "1"  # backend labels only, before the rules of hnc_rescore.py
# Optional note-type filter {report_type: [variable]}. Fields the filter would not ask are dropped, and a gold value
# among them counts as missed, because the tool would not have looked for it.
FILTER = json.load(open(os.environ["HNC_FILTER"])) if os.environ.get("HNC_FILTER") else None


def var(pt):
    return pt.removesuffix("-int-hnc")


def looped(t):
    """Broken generation, same rule as exp_judge: a 30-char window repeated more than 4 times."""
    if not t or len(t) < 200:
        return False
    c = Counter(t[i:i + 30] for i in range(0, len(t) - 30, 5))
    return max(c.values()) > 4


def cells(path):
    """One row per (note, variable): patient, variable, match type, loop flag."""
    s = json.load(open(path))
    pid = {str(n["note_id"]): n["p_id"] for n in s["notes"]}
    rtype = {str(n["note_id"]): n.get("report_type") for n in s["notes"]}
    rows = []
    for nid, pm in s["annotations"].items():
        for pt, a in pm.items():
            r = a.get("evaluation_result") or {}
            mt = r.get("match_type_backend", r.get("match_type")) if STRICT else r.get("match_type")
            if FILTER is not None and rtype[nid] in FILTER and var(pt) not in FILTER[rtype[nid]]:
                if mt in ("false_positive", "both_empty"):
                    continue
                mt = "false_negative"
            rows.append((nid, pid[nid], var(pt), mt, looped(a.get("raw_response") or a.get("annotation_text") or "")))
    return rows


def ratio(rows, num, den):
    """k/n with a bootstrap-over-patients 95% CI."""
    per = defaultdict(lambda: [0, 0])
    for _, p, _, mt, _ in rows:
        if mt in den:
            per[p][1] += 1
            per[p][0] += mt in num
    k, n = sum(v[0] for v in per.values()), sum(v[1] for v in per.values())
    out = {"k": k, "n": n, "pct": round(100 * k / n, 1) if n else None, "patients": len(per)}
    if n:
        rnd, pts, est = random.Random(42), list(per.values()), []
        for _ in range(B):
            smp = [pts[rnd.randrange(len(pts))] for _ in pts]
            sn = sum(v[1] for v in smp)
            if sn:
                est.append(sum(v[0] for v in smp) / sn)
        est.sort()
        out["ci95"] = [round(100 * est[int(0.025 * len(est))], 1), round(100 * est[int(0.975 * len(est)) - 1], 1)]
    return out


def both(rows):
    return {"correct": ratio(rows, {"match"}, {"match", "mismatch"}),
            "invented": ratio(rows, {"false_positive"}, {"false_positive", "both_empty"})}


def mcnemar(a, b, num, den):
    """Exact McNemar on cells scored in both runs where the gold side agrees (den)."""
    A = {(r[0], r[2]): r[3] for r in a}
    pairs = [(A[(r[0], r[2])], r[3]) for r in b if (r[0], r[2]) in A and A[(r[0], r[2])] in den and r[3] in den]
    x = sum(1 for u, v in pairs if u in num and v not in num)
    y = sum(1 for u, v in pairs if u not in num and v in num)
    m = x + y
    p = min(1.0, 2 * sum(math.comb(m, i) for i in range(min(x, y) + 1)) / 2 ** m) if m else 1.0
    return {"pairs": len(pairs), "first_only": x, "second_only": y, "p_exact": round(p, 4)}


def summary(rows):
    out = {"notes": len({r[0] for r in rows}), "patients": len({r[1] for r in rows}), "cells": len(rows),
           "match_types": dict(Counter(r[3] for r in rows)), "unscored": sum(r[3] is None for r in rows),
           "looped": sum(r[4] for r in rows), "overall": both(rows),
           "overall_without_looped": both([r for r in rows if not r[4]])}
    out["by_variable"] = {v: both([r for r in rows if r[2] == v]) for v in sorted({r[2] for r in rows})}
    out["by_stage"] = {s: both([r for r in rows if STAGE_OF.get(r[2]) == s]) for s in STAGE}
    out["dates_vs_other"] = {"dates": both([r for r in rows if r[2] in DATES]),
                             "other": both([r for r in rows if r[2] not in DATES])}
    return out


def main():
    out_path, runs = sys.argv[1], dict(a.split("=", 1) for a in sys.argv[2:])
    data = {k: cells(p) for k, p in runs.items()}
    res = {k: summary(v) for k, v in data.items()}
    labels = list(data)
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            res[f"mcnemar {a} vs {b}"] = {
                "correct": mcnemar(data[a], data[b], {"match"}, {"match", "mismatch", "false_negative"}),
                "invented": mcnemar(data[a], data[b], {"false_positive"}, {"false_positive", "both_empty"})}
    json.dump(res, open(out_path, "w"), indent=1)
    for k in labels:
        o = res[k]["overall"]
        print(k, res[k]["notes"], "notes", "correct", o["correct"], "invented", o["invented"])


if __name__ == "__main__":
    assert looped("ion " * 80) and not looped("short text")
    main()
