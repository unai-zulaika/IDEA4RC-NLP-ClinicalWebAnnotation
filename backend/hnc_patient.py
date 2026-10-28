#!/usr/bin/env python3
"""Score per patient instead of per note, with the backend's own evaluator. Writes aggregates only.

Per patient and variable, the reference is every gold value in any of the patient's notes.
The tool's answer is picked by a simple rule: pathology variables from the latest pathology
report, follow-up variables from the latest note, all others from the earliest note with a value.
Also counts note-level "invented" values that match a gold value in another note of the same patient,
and, as an upper bound for any selection rule, whether some note of the patient has a correct value.
Each measure is given for all variables, for dates and for the other variables.

Run from backend/ with the backend venv:  .venv/bin/python hnc_patient.py OUT.json label=session.json ...
"""
import json
import random
import sys
from collections import defaultdict
from functools import lru_cache

sys.path.insert(0, ".")
from routes import annotate as A  # noqa: E402
from services.evaluation_service import evaluate_annotation_with_template as evaluate  # noqa: E402
from hnc_rescore import same_value  # noqa: E402  same wording alignment as the per-note scores

PATHO = {"histological-tipo", "surgical-specimen-grading", "pathological-tnmstaging", "surgerymargins"}
FOLLOW = {"patient-status", "disease-status", "last-followup-date", "site-of-metastatic"}
VALUE = {"match", "mismatch", "false_positive"}  # the evaluator saw a value, not an abstention
DATES = {"radiotherapy_start", "radiotherapy_end", "chemotherapy_start", "systemic-treatment-started",
         "systemic-treatment-ended", "last-followup-date"}  # same as hnc_metrics.py


def gold(note, pt):
    out = []
    for part in (note.get("annotations") or "").split(" | "):
        if ": " in part and part.split(": ", 1)[0].strip() == pt:
            out.append(part.split(": ", 1)[1].strip())
    return out


@lru_cache(maxsize=None)
def same(pt, expected, predicted):
    tmpl = (A._PROMPTS.get(pt) or {}).get("template", "")
    r = evaluate(expected=expected, predicted=predicted, template=tmpl, prompt_type=pt)
    return r.get("match_type") == "match" or same_value(expected, predicted)


def pick(pt, cands):
    """cands: (date, report_type, text). Rule described in the docstring."""
    v = pt.removesuffix("-int-hnc")
    if v in PATHO:
        path = [c for c in cands if c[1] == "Pathology"]
        return max(path or cands)[2]
    return (max(cands) if v in FOLLOW else min(cands))[2]


def boot(per):
    """per: {patient: [k, n]} -> k, n, pct, 95% CI by bootstrap over patients."""
    pts = [v for v in per.values() if v[1]]
    k, n = sum(v[0] for v in pts), sum(v[1] for v in pts)
    if not n:
        return {"k": 0, "n": 0}
    rnd, est = random.Random(42), []
    for _ in range(2000):
        s = [pts[rnd.randrange(len(pts))] for _ in pts]
        est.append(sum(x[0] for x in s) / sum(x[1] for x in s))
    est.sort()
    return {"k": k, "n": n, "pct": round(100 * k / n, 1), "patients": len(pts),
            "ci95": [round(100 * est[50], 1), round(100 * est[1949], 1)]}


def run(path):
    s = json.load(open(path))
    notes = {str(n["note_id"]): n for n in s["notes"] if str(n["note_id"]) in s["annotations"]}
    by_pat = defaultdict(list)
    for nid, n in notes.items():
        by_pat[n["p_id"]].append(nid)
    groups = ("all", "dates", "other")
    c = {m: {g: defaultdict(lambda: [0, 0]) for g in groups}
         for m in ("correct", "correct_in_some_note", "invented", "note_invented_true_elsewhere")}

    def add(m, pt, p, hit):
        for g in ("all", "dates" if pt.removesuffix("-int-hnc") in DATES else "other"):
            c[m][g][p][1] += 1
            c[m][g][p][0] += bool(hit)

    for p, nids in by_pat.items():
        for pt in s["prompt_types"]:
            G = [g for nid in nids for g in gold(notes[nid], pt)]
            cands, scored = [], False
            for nid in nids:
                a = s["annotations"][nid].get(pt) or {}
                mt = (a.get("evaluation_result") or {}).get("match_type")
                scored |= mt is not None
                if mt in VALUE:
                    cands.append((notes[nid].get("date") or "", notes[nid].get("report_type") or "", a["annotation_text"]))
                if mt == "false_positive":  # invented in this note: is it true elsewhere for this patient?
                    add("note_invented_true_elsewhere", pt, p, any(same(pt, g, a["annotation_text"]) for g in G))
            if not scored:  # the evaluator skipped every note of this patient for this variable
                continue
            if G and cands:
                add("correct", pt, p, any(same(pt, g, pick(pt, cands)) for g in G))
                add("correct_in_some_note", pt, p, any(same(pt, g, x[2]) for g in G for x in cands))
            elif not G:
                add("invented", pt, p, cands)
    return {"patients": len(by_pat), "notes": len(notes),
            **{m: {g: boot(v) for g, v in d.items()} for m, d in c.items()}}


if __name__ == "__main__":
    assert pick("last-followup-date-int-hnc", [("2020", "CCE", "a"), ("2022", "CCE", "b")]) == "b"
    assert pick("histological-tipo-int-hnc", [("2020", "Pathology", "a"), ("2022", "CCE", "b")]) == "a"
    A._ensure_prompts_loaded()
    out = {k: run(v) for k, v in (a.split("=", 1) for a in sys.argv[2:])}
    json.dump(out, open(sys.argv[1], "w"), indent=1)
    print(json.dumps(out, indent=1))
