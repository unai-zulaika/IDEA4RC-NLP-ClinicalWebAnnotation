#!/usr/bin/env python3
"""
LLM-as-judge verdicts for the 27B run, one per (note, prompt) pair where the
gold has a value. Verdicts are mine (Claude) after reading the gold and
predicted strings.

Verdict codes:
  C  — clinically correct (matches gold semantically; punctuation, ICD-O-3
       LLM placeholders, English/Italian drug-name variants, and trailing
       periods are ignored)
  W  — clinically wrong (substantive field differs, e.g. pre-op vs post-op,
       recurrence vs progression, wrong date, wrong site, missing required
       field where gold has a value)
  D  — data-quality issue in the gold (annotation mislabeled or incomplete;
       excluded from accuracy denominator)
"""
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR

# Verdicts keyed by the row idx in /tmp/judge_pairs.json
VERDICTS: dict[int, tuple[str, str]] = {
    0:  ("C", "FNCLCC 3 == FNCLCC 3"),
    1:  ("C", "date matches (27/9/19 == 27/09/2019); pred fills 'the hospital' for [select place], acceptable"),
    2:  ("C", "Undifferentiated sarcoma matches; ICD-O-3 code placeholder OK (PDF says don't trust LLM ICD codes)"),
    3:  ("C", "150mm == 150mm"),
    4:  ("C", "Thoracic Wall == Thoracic Wall"),
    5:  ("W", "gold=surgery, pred=radiation — wrong treatment"),
    6:  ("W", "completeness missing in pred ([select result]) while gold=complete"),
    7:  ("C", "46 == 46"),
    8:  ("C", "Leiomyosarcoma NOS matches; ICD code placeholder OK"),
    9:  ("C", "Utero == Utero"),
    10: ("D", "gold for chemotherapy_start contains END info (mislabeled); cannot judge fairly"),
    11: ("W", "gold=90mm, pred=30mm — different value"),
    12: ("W", "reason mismatch: gold=completion, pred=unknown"),
    13: ("W", "intent wrong (post-op vs therapeutic), date wrong, regimen wrong, malformed 'Response:' prefix"),
    14: ("C", "metastatic soft tissue == metastatic soft tissue"),
    15: ("W", "gold=stable disease, pred=partial response"),
    16: ("W", "date wrong: gold=15/02/2021, pred=02/02/2021"),
    17: ("C", "R1 == R1"),
    18: ("W", "wrong date by years (gold=28/07/2021, pred=06/2019) and wrong completeness"),
    19: ("W", "type wrong (recurrence vs progression), date wrong"),
    20: ("W", "wrong date and wrong completeness"),
    21: ("C", "female == female"),
    22: ("W", "intent wrong (therapeutic vs post-op), date debatable; drug correct"),
    23: ("W", "intent wrong (therapeutic vs post-op); date correct, but type misclassification is clinically substantive"),
    24: ("W", "gold=metastatic soft tissue, pred=local"),
    25: ("W", "type wrong (therapeutic vs post-op), fractions placeholder, reason placeholder"),
    26: ("C", "stable disease == stable disease"),
    27: ("W", "type wrong (therapeutic vs post-op); other fields OK"),
    28: ("W", "type wrong (progression vs recurrence), date wrong"),
    29: ("D", "gold has only date, pred has only status — different sub-fields, can't compare"),
    30: ("C", "R0 == R0"),
    31: ("W", "completeness missing in pred (gold=complete, pred=[select result])"),
    32: ("W", "type wrong (pre-op gold vs post-op pred)"),
    33: ("W", "completely wrong surgery picked (date off by years)"),
    34: ("W", "model gave RT-end info for start prompt"),
    35: ("W", "missing site detail: gold=local soft tissue, pred=local"),
    36: ("W", "type wrong (pre-op vs post-op), reason wrong (completion vs unknown)"),
    37: ("W", "reason wrong: gold=completion, pred=unknown"),
    38: ("C", "type=recurrence both; date semantically equivalent (10/2018 matches note evidence 'Ott. 2018'; gold's '15/10/2018' is an arbitrary day choice)"),
    39: ("C", "46 == 46"),
    40: ("C", "Myxoid liposarcoma matches; ICD code placeholder OK"),
    41: ("C", "Buttock == Buttock"),
    42: ("C", "male == male"),
    43: ("C", "female == female"),
    44: ("C", "localized == localized"),
    45: ("C", "69 == 69"),
    46: ("W", "gold=PEComa, pred=Epithelioid leiomyosarcoma — wrong histology"),
    47: ("C", "Bladder == Bladder"),
    48: ("C", "mitotic count value 10 matches; denominator notation differs (10/1mm2 vs 10/10HPF) — clinically equivalent"),
    49: ("W", "completeness wrong (gold=complete, pred=incomplete)"),
    50: ("W", "type wrong (therapeutic vs post-op), intent missing"),
    51: ("W", "wrong date (different surgery picked), completeness missing"),
    52: ("W", "model gave RT-end info for start prompt, also wrong type"),
    53: ("W", "type wrong (gold=local, pred=metastatic)"),
    54: ("W", "gold=stable disease, pred=progression"),
    55: ("W", "date off by 3 days (26/09 vs 29/09), type label missing"),
    56: ("W", "type wrong (recurrence vs progression), date wrong"),
    57: ("D", "gold has only date, pred has only status — different sub-fields, can't compare"),
    58: ("C", "2 == 2"),
    59: ("W", "model gave RT-end info for start prompt"),
    60: ("W", "reason missing (gold=completion, pred=[select reason])"),
    61: ("C", "core-trucut matches; pred FILLS placeholders with correct data from note (08/01/2020, INT) — better than gold"),
    62: ("W", "gold=unknown stage, pred=localized — model overconfident"),
    63: ("W", "gold=Undifferentiated sarcoma, pred=Spindle cell sarcoma NOS — different histology"),
    64: ("C", "thigh == Upper leg (equivalent anatomical terms)"),
    65: ("C", "type label OK, completeness OK, date 18/05/2020 is what the note actually says (gold's 15/05/2020 refers to MRI, not surgery) — model more accurate"),
    66: ("D", "gold annotation is a RESPONSE annotation mislabeled as radiotherapy_start"),
    67: ("C", "Response to pre-operative radiotherapy: progression == progression"),
    68: ("C", "3 == 3"),
    69: ("C", "110mm == 110mm"),
    70: ("C", "site detail leg == Leg; pred's category (Upper and Lower limbs) is the standard one (gold uses 'Other' inconsistently)"),
    71: ("C", "date OK, type OK, gold's [select result] ~ pred's 'unknown' (both = no info)"),
    72: ("C", "metastatic to lung; gold says 'other' but note clearly says lung — pred is more accurate"),
    73: ("C", "84 == 84"),
    74: ("C", "distant metastases (lung) == distant metastases (lung)"),
    75: ("W", "gold=Undifferentiated sarcoma, pred=Sarcoma NOS — loses specificity vs note's 'sarcoma indifferenziato'"),
}


def main() -> None:
    pairs = json.loads((Path("/tmp/judge_pairs.json")).read_text())
    rows = []
    for p in pairs:
        v, reason = VERDICTS.get(p["idx"], ("?", "no verdict"))
        rows.append({
            "idx":           p["idx"],
            "prompt_type":   p["prompt"],
            "p_id":          p["p_id"],
            "verdict":       v,
            "gold":          p["gold"],
            "pred":          p["pred"],
            "reason":        reason,
        })
    df = pd.DataFrame(rows)

    # Per-prompt aggregation, excluding data-issue rows from denominator
    valid = df[df["verdict"].isin(["C", "W"])]
    agg = valid.groupby("prompt_type").agg(
        n_judged=("verdict", "size"),
        n_correct=("verdict", lambda s: (s == "C").sum()),
    )
    agg["judge_pct"] = (agg["n_correct"] / agg["n_judged"] * 100).round(1)

    data_issues = df[df["verdict"] == "D"].groupby("prompt_type").size()
    if not data_issues.empty:
        agg["data_issues"] = data_issues
    agg = agg.fillna(0).sort_values("judge_pct", ascending=False)
    print("=== Per-prompt LLM-as-judge accuracy (27B, INT data) ===")
    print(agg.to_string())
    print()
    total_judged = (df["verdict"] == "C").sum() + (df["verdict"] == "W").sum()
    total_correct = (df["verdict"] == "C").sum()
    total_data = (df["verdict"] == "D").sum()
    print(f"Overall: {total_correct}/{total_judged} = {total_correct/total_judged*100:.1f}%")
    print(f"Data-quality issues excluded: {total_data}")

    df.to_csv(NLP_DIR / "judge_verdicts.csv", index=False)
    print(f"\nWrote per-row verdicts -> {NLP_DIR / 'judge_verdicts.csv'}")

    agg.to_csv(NLP_DIR / "judge_per_prompt.csv")
    print(f"Wrote per-prompt accuracy -> {NLP_DIR / 'judge_per_prompt.csv'}")


if __name__ == "__main__":
    main()
