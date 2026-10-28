#!/usr/bin/env python3
"""Score the cells the backend left without evaluation_result and write <session>_scored.json.

Repeatable variables in long (chunked) notes get their chunk answers merged by
aggregate_multi_value_results, which skips the evaluator (routes/annotate.py). The answer is
there, it was just never compared. Same evaluator and same expected-value lookup as the backend.
Self-check: re-scores already-scored cells and requires the same match type.

Then applies the empty-answer rule. The tidy step misses answers that give no value, either
"No ... mentioned" / "Not applicable" or the answer template with every slot blank (the model
writes [provide date] etc. and the placeholders are stripped). Such an answer is an abstention,
so a false_positive becomes both_empty and a mismatch becomes false_negative. The backend label
is kept in match_type_backend.

Finally aligns wordings. The annotation keeps the template frame ("Smoking status: Former smoker
(at least for 12 months).") while the answer may give the bare value ("Former smoker"). A
mismatch becomes a match when the value part is identical, ignoring case, punctuation and
parentheses. No near-matches.

Run from backend/ with the backend venv:  .venv/bin/python hnc_rescore.py sessions/a.json ...
"""
import json
import random
import re
import sys

sys.path.insert(0, ".")
from routes import annotate as A  # noqa: E402
from services.evaluation_service import evaluate_annotation_with_template as evaluate  # noqa: E402


NOT_REPORTED = re.compile(r"^\W*no\b.*\bmentioned\W*$|\bnot (applicable|mentioned|reported|specified|available|stated|documented)\b", re.I)


SLOT = re.compile(r"\[[^\]]*\]?|<[A-Z_ ]+>")  # a placeholder, [provide date] or <DATE>, also one cut off at the end


def norm(t):
    t = SLOT.sub("", t)
    return re.sub(r"[^a-z0-9]", "", t.lower()).removeprefix("annotation")


def words(t):
    return set(re.findall(r"[a-z]+", SLOT.sub(" ", t).lower())) - {"annotation"}


def frames(tmpl):
    """Answer-template lines. Two or more placeholders, so option lists like 'Tumor site: Larynx - [please select].' are left out."""
    return [line for line in tmpl.splitlines() if len(SLOT.findall(line)) >= 2]


def empty(text, fr):
    """True when the answer gives no value. Any digit (other than an appended ICD-O code) counts as a value."""
    text = re.sub(r"\(\d{4}/\d\)", "", text or "")
    if re.search(r"\d", text):
        return False
    w = words(text)
    return bool(NOT_REPORTED.search(text)) or not w or any(norm(text) == norm(f) or w <= words(f) for f in fr)


def bare(t):
    t = re.sub(r"\([^)]*\)", "", t or "")
    return re.sub(r"[^a-z0-9]", "", t.rsplit(": ", 1)[-1].lower())


def same_value(exp, pred):
    return bool(bare(exp)) and bare(exp) == bare(pred)


def expected(annotations, pt):
    """Same lookup as routes/annotate.py: first part whose key contains the prompt type or vice versa."""
    for part in str(annotations or "").split("|"):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip().lower()
            if pt.lower() in k or k in pt.lower():
                return v.strip()
    return ""


def score(gold, nid, pt, a):
    tmpl = (A._PROMPTS.get(pt) or {}).get("template", "")
    assert tmpl, f"no template for {pt}"
    return evaluate(expected=expected(gold[nid], pt), predicted=a["annotation_text"], template=tmpl,
                    note_id=nid, prompt_type=pt)


def run(path):
    s = json.load(open(path))
    gold = {str(n["note_id"]): n.get("annotations") for n in s["notes"]}
    cells = [(nid, pt, a) for nid, pm in s["annotations"].items() for pt, a in pm.items()]
    done = [c for c in cells if (c[2].get("evaluation_result") or {}).get("match_type")]
    todo = [c for c in cells if c not in done]
    check = random.Random(42).sample(done, min(300, len(done)))
    same = sum(score(gold, *c)["match_type"] == c[2]["evaluation_result"]["match_type"] for c in check)
    assert same == len(check), f"{path}: offline scorer disagrees with backend on {len(check) - same}/{len(check)}"
    for nid, pt, a in todo:
        a["evaluation_result"] = {**score(gold, nid, pt, a), "scored_offline": True}
    sk = {pt: frames((A._PROMPTS.get(pt) or {}).get("template", "")) for pt in s["prompt_types"]}
    moved = aligned = 0
    for nid, pt, a in cells:
        r = a["evaluation_result"]
        new = {"false_positive": "both_empty", "mismatch": "false_negative"}.get(r["match_type"])
        if new and empty(a.get("annotation_text"), sk[pt]):
            r["match_type_backend"], r["match_type"] = r["match_type"], new
            moved += 1
        elif r["match_type"] == "mismatch" and same_value(expected(gold[nid], pt), a.get("annotation_text")):
            r["match_type_backend"], r["match_type"] = "mismatch", "match"
            aligned += 1
    out = path.removesuffix(".json") + "_scored.json"
    json.dump(s, open(out, "w"), ensure_ascii=False, indent=2)
    print(f"{path}: check {same}/{len(check)} agree, scored {len(todo)} cells, {moved} empty answers, {aligned} aligned -> {out}")


if __name__ == "__main__":
    assert expected("tumorsite-int-hnc: a | histological-tipo-int-hnc: b", "histological-tipo-int-hnc") == "b"
    rt = frames("Radiotherapy in total of [put total dose]Gy in [put number of] fractions ended on [provide date].")
    assert empty("Radiotherapy in total ofGy in fractions ended on.", rt)
    assert not empty("Radiotherapy in total of 60Gy in fractions ended on.", rt)
    ns = frames("[select laterality] neck surgery was performed on [provide date].")
    assert empty("neck surgery was performed on.", ns) and not empty("Ipsilateral neck surgery was performed on.", ns)
    assert empty("No systemic treatment end mentioned.", []) and empty("Not applicable (8000/3)", [])
    assert not empty("Stage 4", []) and not empty("Transoral", [])
    ts = frames("Tumor site: Nasopharynx - [please select].\nAnnotation: Tumor site ([select category]): [select site].")
    assert empty("Tumor site: [please select].", ts) and not empty("Tumor site: Nasopharynx - [please select].", ts)
    se = frames("Systemic treatment ended on [provide date] after [provide number] of cycles because of [select reason].")
    assert empty("Systemic treatment ended on of cycles because of.", se)
    assert empty("Systemic treatment ended on of cycles because of.", frames("Systemic treatment ended on <DATE> after <NUMBER> cycles because of <REASON>."))
    assert same_value("Smoking status: Former smoker (at least for 12 months).", "Former smoker")
    assert same_value("Margins after surgery: R0.", "R0") and not same_value("Margins after surgery: R0.", "R1")
    assert not same_value("Staging classification (clinical): IVA.", "Stage 4") and not same_value("", "")
    A._ensure_prompts_loaded()
    for p in sys.argv[1:]:
        run(p)
