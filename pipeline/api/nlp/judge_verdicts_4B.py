#!/usr/bin/env python3
"""LLM-as-judge verdicts for the 4B PIPELINE and 4B BACKEND runs."""
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR

# 4B PIPELINE verdicts
PIPE: dict[int, tuple[str, str]] = {
    0:  ("C", "3 == 3"),
    1:  ("W", "format off: '- **Biopsy Type:** \"Biopsia\"' instead of template"),
    2:  ("W", "'differenziato' (differentiated) != 'undifferentiated' — opposite meaning"),
    3:  ("C", "150mm match"),
    4:  ("C", "Thoracic Wall match"),
    5:  ("W", "gold=surgery, pred=radiation"),
    6:  ("W", "completeness placeholder vs gold=complete"),
    7:  ("C", "46 match"),
    8:  ("C", "Leiomyosarcoma NOS match"),
    9:  ("C", "Utero match"),
    10: ("D", "gold has end info mislabeled as start"),
    11: ("W", "30mm vs 90mm"),
    12: ("W", "type wrong (therapeutic vs post-op), date wrong"),
    13: ("W", "wrong type+date+drug (still picking earlier regimen)"),
    14: ("W", "metastatic pelvic vs metastatic soft tissue (site differs)"),
    15: ("W", "progression vs stable disease"),
    16: ("W", "type wrong + date wrong"),
    17: ("W", "R0 vs R1 — model misread margin"),
    18: ("W", "date very wrong (02/08/2019 vs 28/07/2021)"),
    19: ("W", "type wrong + date wrong"),
    20: ("W", "date wrong + completeness missing"),
    21: ("C", "female match"),
    22: ("W", "drug wrong (adriamicina vs trabectedin)"),
    23: ("W", "type wrong + method placeholder"),
    24: ("W", "local vs metastatic"),
    25: ("W", "pre-op vs therapeutic + fractions wrong + date wrong"),
    26: ("W", "type placeholder while gold has it"),
    27: ("W", "type wrong + date placeholder"),
    28: ("W", "date very wrong (2022 vs 2024)"),
    29: ("W", "model emitted '### Response:' only — failed to generate"),
    30: ("W", "model emitted '### Response:' only"),
    31: ("W", "model emitted '### Response:' only"),
    32: ("W", "type+date+drug right, intent missing — strict W"),
    33: ("W", "wrong surgery picked (13/11/2019 is chemo date)"),
    34: ("W", "gave RT-end info for RT-start prompt"),
    35: ("W", "site detail missing (local vs local soft tissue)"),
    36: ("W", "reason wrong (completion vs unknown)"),
    37: ("C", "all fields match including reason 'completion'"),
    38: ("W", "type=recurrence OK but date wrong"),
    39: ("C", "46 match"),
    40: ("C", "Myxoid liposarcoma match"),
    41: ("C", "Buttock match"),
    42: ("C", "male match"),
    43: ("C", "female match"),
    44: ("C", "localized match"),
    45: ("C", "69 match"),
    46: ("C", "PEComa match (more verbose form)"),
    47: ("C", "Vescica (Italian) == Bladder"),
    48: ("C", "value 10 matches"),
    49: ("W", "completeness wrong (incomplete vs complete) + date slightly off"),
    50: ("W", "type wrong + all fields placeholder"),
    51: ("W", "date wrong + 'unknow' typo for completeness"),
    52: ("W", "gave RT-end info for start prompt"),
    53: ("C", "both gold and pred abstain on metastatic site"),
    54: ("W", "model emitted '### Response:' only"),
    55: ("W", "type wrong + date placeholder + cycles missing"),
    56: ("W", "type wrong + date very wrong"),
    57: ("D", "gold date only, pred status only"),
    58: ("C", "2 match"),
    59: ("W", "gave RT-end info for start prompt"),
    60: ("W", "reason missing (completion vs placeholder)"),
    61: ("W", "biopsy type missing in pred (uses placeholder)"),
    62: ("W", "gold=unknown, pred=localized"),
    63: ("W", "spindle vs undifferentiated histology"),
    64: ("C", "thigh == Leg (Italian/English equivalence)"),
    65: ("W", "date slightly off (14/05 vs 15/05) + completeness wrong"),
    66: ("W", "gave RT-end info for start prompt"),
    67: ("W", "partial response vs progression + type wrong"),
    68: ("C", "3 match"),
    69: ("C", "110mm match"),
    70: ("W", "forearm vs leg — wrong site"),
    71: ("C", "date right; pred fills completeness=complete where gold has placeholder"),
    72: ("C", "distant metastases (lung) is what note evidence supports"),
    73: ("C", "84 match"),
    74: ("W", "gold=distant metastases (lung), pred=localized"),
    75: ("W", "Sarcoma NOS vs Undifferentiated sarcoma (loses specificity)"),
}

# 4B BACKEND verdicts (post-prompt-fix prompt_wrapper applied to 4B model)
BACK: dict[int, tuple[str, str]] = {
    0:  ("W", "grade 1 vs gold 3 (model misread)"),
    1:  ("C", "date matches; pred fills place"),
    2:  ("C", "Italian leak + matches diagnosis + ICD 8805/3 correct"),
    3:  ("C", "150mm match"),
    4:  ("C", "Thoracic Wall + ICD"),
    5:  ("W", "over-predicts: 'radiation, surgery, other' vs just 'surgery'"),
    6:  ("C", "date matches (21.6.2019 == 21/06/2019); completeness 'complete' matches gold"),
    7:  ("C", "46 match"),
    8:  ("C", "Leiomyosarcoma NOS + correct ICD"),
    9:  ("C", "Uterus == Utero"),
    10: ("D", "gold mislabeled (end info as start)"),
    11: ("W", "16mm vs 90mm"),
    12: ("W", "all fields empty"),
    13: ("W", "type+date+drug wrong"),
    14: ("W", "metastatic liver/lung/bone vs metastatic soft tissue (different sites)"),
    15: ("W", "Not applicable"),
    16: ("W", "type wrong + date wrong"),
    17: ("W", "R0 vs R1"),
    18: ("W", "date wrong; completeness matches"),
    19: ("W", "type wrong + date wrong"),
    20: ("W", "date wrong; completeness matches"),
    21: ("W", "HALLUCINATION LOOP — pred is broken JSON repeating 'The note mentions...'"),
    22: ("W", "type+date+drug all wrong"),
    23: ("W", "gave RT-end info for start prompt"),
    24: ("W", "local vs metastatic"),
    25: ("W", "wrong end info entirely"),
    26: ("W", "Not applicable"),
    27: ("W", "broken JSON (truncated reasoning)"),
    28: ("W", "type wrong + date wrong"),
    29: ("D", "gold date only, pred status only"),
    30: ("W", "date very wrong (29/07/2018 vs 13/11/2019); drug missing"),
    31: ("W", "wrong surgery + completeness wrong"),
    32: ("W", "date wrong + place wrong"),
    33: ("W", "site detail missing"),
    34: ("W", "type wrong + date very wrong + reason missing"),
    35: ("C", "all fields match including 'completion'"),
    36: ("W", "date '01/01/0000' is nonsense"),
    37: ("C", "46 match"),
    38: ("W", "'Mixed liposarcoma' wrong (myxoid != mixed); wrong ICD"),
    39: ("C", "Buttock match"),
    40: ("C", "male match"),
    41: ("C", "female match"),
    42: ("C", "localized match"),
    43: ("C", "69 match"),
    44: ("W", "ICD behavior code wrong (/0 = benign vs gold /3 = malignant)"),
    45: ("C", "Vescica matches"),
    46: ("C", "value 10 matches"),
    47: ("W", "date wrong (09.03 vs 03/09); completeness missing"),
    48: ("W", "type+date+drug wrong"),
    49: ("W", "date wrong (09/2019 vs 28/05/2020); completeness matches"),
    50: ("W", "type wrong + date wrong"),
    51: ("C", "both abstain on metastatic site, type=local matches"),
    52: ("W", "Not applicable"),
    53: ("W", "broken JSON (truncated)"),
    54: ("W", "broken JSON (truncated)"),
    55: ("D", "gold date only, pred 'Not applicable'"),
    56: ("C", "2 match — IMPROVEMENT (was '1' in 27B pre-fix run)"),
    57: ("W", "date wrong; type matches"),
    58: ("W", "date wrong + reason missing"),
    59: ("C", "core-trucut + date + INT — fills placeholders correctly"),
    60: ("W", "gold=unknown, pred=localized"),
    61: ("C", "Italian + matches diagnosis + ICD"),
    62: ("C", "Thigh match"),
    63: ("W", "date wrong; completeness matches"),
    64: ("D", "gold is response annotation mislabeled as RT-start"),
    65: ("W", "'pre-operative' only — just setting, not response"),
    66: ("W", "grade 2 vs gold 3"),
    67: ("C", "110mm match"),
    68: ("C", "right leg specified, matches site"),
    69: ("C", "Amputation descriptive but accurate; date matches; both abstain on completeness"),
    70: ("C", "distant metastases (lung) matches"),
    71: ("C", "84 match"),
    72: ("C", "Undifferentiated sarcoma + ICD"),
}


def _aggregate(verdicts: dict, pairs_file: str, out_name: str) -> None:
    pairs = json.loads(Path(pairs_file).read_text())
    rows = []
    for p in pairs:
        v, reason = verdicts.get(p["idx"], ("?", "no verdict"))
        rows.append({
            "idx":         p["idx"],
            "prompt_type": p["prompt"],
            "p_id":        p["p_id"],
            "verdict":     v,
            "gold":        p["gold"],
            "pred":        p["pred"],
            "reason":      reason,
        })
    df = pd.DataFrame(rows)
    df.to_csv(NLP_DIR / f"judge_verdicts_{out_name}.csv", index=False)

    valid = df[df["verdict"].isin(["C", "W"])]
    agg = valid.groupby("prompt_type").agg(
        n_judged=("verdict", "size"),
        n_correct=("verdict", lambda s: (s == "C").sum()),
    )
    agg["judge_pct"] = (agg["n_correct"] / agg["n_judged"] * 100).round(1)
    data = df[df["verdict"] == "D"].groupby("prompt_type").size()
    if not data.empty:
        agg["data_issues"] = data
    agg = agg.fillna(0).sort_values("judge_pct", ascending=False)
    agg.to_csv(NLP_DIR / f"judge_per_prompt_{out_name}.csv")

    c = (df["verdict"] == "C").sum()
    w = (df["verdict"] == "W").sum()
    d = (df["verdict"] == "D").sum()
    print(f"=== {out_name} ===  Overall: {c}/{c+w} = {c/(c+w)*100:.1f}%   (data-issues: {d})")
    print(agg.to_string())
    print()


def main() -> None:
    _aggregate(PIPE, "/tmp/judge_pairs_4B_pipe.json", "4B_pipeline")
    _aggregate(BACK, "/tmp/judge_pairs_4B_back.json", "4B_backend")


if __name__ == "__main__":
    main()
