#!/usr/bin/env python3
"""LLM-as-judge verdicts for the POST-PROMPT-FIX backend run (v2)."""
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR

VERDICTS: dict[int, tuple[str, str]] = {
    0:  ("C", "3 == 3"),
    1:  ("C", "fills date+place from note"),
    2:  ("C", "Italian leak; diagnosis matches; ICD 8805/3 matches"),
    3:  ("C", "150mm matches; placeholder filled"),
    4:  ("C", "Thoracic Wall + ICD"),
    5:  ("W", "gold=surgery, pred=radiation,other"),
    6:  ("W", "completeness missing"),
    7:  ("C", "46 == 46"),
    8:  ("C", "Leiomyosarcoma NOS + ICD 8890/3"),
    9:  ("C", "Utero + ICD"),
    10: ("D", "gold for chemo_start has end info (mislabeled)"),
    11: ("C", "now 90mm (was 30mm pre-fix) — IMPROVEMENT"),
    12: ("W", "type wrong + empty fields"),
    13: ("W", "type wrong + date partial + intent missing"),
    14: ("W", "empty pred"),
    15: ("W", "pred only setting, not response"),
    16: ("W", "pred 'no progression/recurrence' — gold says recurrence"),
    17: ("C", "R1 == R1"),
    18: ("W", "date wrong + completeness missing"),
    19: ("W", "type wrong + date wrong"),
    20: ("W", "date wrong + completeness missing"),
    21: ("C", "female == female — IMPROVEMENT (was 'Not applicable')"),
    22: ("W", "type wrong + intent missing"),
    23: ("W", "type wrong + intent missing"),
    24: ("W", "metastatic vs local"),
    25: ("W", "type wrong + fractions missing + reason missing"),
    26: ("W", "pred only setting, not response"),
    27: ("W", "type wrong + empty fields"),
    28: ("W", "type wrong + date wrong"),
    29: ("D", "gold date only, pred status only"),
    30: ("W", "type+date+drug right, intent missing — strict W"),
    31: ("W", "wrong surgery picked + completeness missing"),
    32: ("W", "type+date+location right, intent missing — strict W; IMPROVED vs pre-fix (was gave end info)"),
    33: ("W", "type=local correct, site detail missing"),
    34: ("W", "all right except reason missing"),
    35: ("C", "all fields match including reason 'completion'"),
    36: ("C", "type=recurrence matches; date partial (10/2018 ~ note evidence) — IMPROVEMENT"),
    37: ("C", "46 == 46"),
    38: ("W", "ICD 8800/3 instead of 8852/3 — backend ICD lookup regressed (pre-fix had 8852/3 right)"),
    39: ("C", "Buttock + ICD"),
    40: ("C", "male — IMPROVEMENT"),
    41: ("C", "female — IMPROVEMENT"),
    42: ("C", "localized"),
    43: ("C", "69 == 69"),
    44: ("C", "PEComa == Perivascular epithelioid cell tumor + ICD"),
    45: ("C", "Bladder + ICD"),
    46: ("C", "mitotic count value 10 matches"),
    47: ("W", "'Not applicable' for surgery that's clearly in the note"),
    48: ("W", "type wrong (post-op vs therapeutic); date+drug ok; intent missing"),
    49: ("W", "wrong date + completeness missing"),
    50: ("W", "gave end info for start prompt"),
    51: ("W", "'None' vs 'local'"),
    52: ("W", "pred only setting"),
    53: ("W", "type wrong + empty fields"),
    54: ("W", "type wrong + date wrong"),
    55: ("D", "gold date only, pred status only"),
    56: ("C", "2 == 2 — IMPROVEMENT (was '1' pre-fix)"),
    57: ("W", "gave end info for start prompt"),
    58: ("W", "reason missing"),
    59: ("C", "fills placeholders with note data"),
    60: ("W", "gold=unknown, pred=distant metastases"),
    61: ("W", "spindle cell vs undifferentiated"),
    62: ("C", "thigh == Upper leg"),
    63: ("W", "completeness missing"),
    64: ("D", "gold is response annotation mislabeled as RT-start"),
    65: ("W", "'Not applicable' instead of progression"),
    66: ("W", "grade 1 vs gold 3 — model misread"),
    67: ("C", "110mm + date filled"),
    68: ("C", "leg + Leg + ICD"),
    69: ("C", "both abstain on completeness; date right"),
    70: ("C", "distant metastases (lung)"),
    71: ("C", "84 == 84"),
    72: ("C", "Undifferentiated sarcoma + ICD"),
}


def main() -> None:
    pairs = json.loads(Path("/tmp/judge_pairs_backend_v2.json").read_text())
    rows = []
    for p in pairs:
        v, reason = VERDICTS.get(p["idx"], ("?", "no verdict"))
        rows.append({
            "idx":         p["idx"],
            "prompt_type": p["prompt"],
            "p_id":        p["p_id"],
            "verdict":     v,
            "history":     p.get("history", False),
            "gold":        p["gold"],
            "pred":        p["pred"],
            "reason":      reason,
        })
    df = pd.DataFrame(rows)

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

    print("=== Per-prompt LLM-as-judge accuracy (27B BACKEND v2 — post-prompt-fix) ===")
    print(agg.to_string())
    print()
    total_c = (df["verdict"] == "C").sum()
    total_w = (df["verdict"] == "W").sum()
    total_d = (df["verdict"] == "D").sum()
    print(f"Overall: {total_c}/{total_c+total_w} = {total_c/(total_c+total_w)*100:.1f}% "
          f"(data issues excluded: {total_d})")

    df.to_csv(ARTIFACTS_DIR / "judge_verdicts_backend_v2.csv", index=False)
    agg.to_csv(ARTIFACTS_DIR / "judge_per_prompt_backend_v2.csv")


if __name__ == "__main__":
    main()
