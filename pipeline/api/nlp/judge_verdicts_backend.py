#!/usr/bin/env python3
"""LLM-as-judge verdicts for the 27B BACKEND filtered run."""
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR

# 73 verdicts, in /tmp/judge_pairs_backend.json idx order.
# C = clinically correct  |  W = clinically wrong  |  D = gold data-issue (excluded)
VERDICTS: dict[int, tuple[str, str]] = {
    0:  ("C", "value 3 == 3 (backend returns bare value)"),
    1:  ("C", "fills 'core-trucut' + date + 'the hospital' — better than gold's placeholders"),
    2:  ("C", "Italian leakage but same diagnosis; ICD 8805/3 matches"),
    3:  ("C", "150mm == 150mm; date placeholder filled with note date"),
    4:  ("C", "Thoracic Wall match; ICDO3 C49.3 added via lookup"),
    5:  ("W", "wrong treatments (radiation+chemo vs surgery)"),
    6:  ("W", "completeness missing in pred while gold=complete"),
    7:  ("C", "46 == 46"),
    8:  ("C", "Leiomyosarcoma NOS + ICD 8890/3 match"),
    9:  ("C", "Utero match; ICDO3 C55.9 added"),
    10: ("D", "gold for chemotherapy_start contains END info (mislabeled)"),
    11: ("W", "wrong value (30mm vs 90mm), truncated date"),
    12: ("W", "type wrong (pre vs post), all fields empty"),
    13: ("W", "intent label wrong (pre-op vs therapeutic); date+drug ok"),
    14: ("W", "pred empty — backend abstained where gold has metastatic soft tissue"),
    15: ("W", "pred only has 'therapeutic (without surgery)' not the response value"),
    16: ("W", "type wrong (progression vs recurrence), date wrong"),
    17: ("C", "R1 == R1"),
    18: ("W", "date off by years, completeness missing"),
    19: ("W", "type wrong + date wrong"),
    20: ("W", "date wrong + completeness missing"),
    21: ("W", "'Not applicable' for a clearly-female note (49 anni affetta da leiomiosarcoma uterino)"),
    22: ("W", "type wrong (post-op vs therapeutic); date approximate (gold may itself be slightly off)"),
    23: ("W", "type wrong + intent missing"),
    24: ("W", "gold=metastatic soft tissue, pred=local"),
    25: ("W", "type wrong + fractions/reason missing"),
    26: ("W", "'Not applicable' instead of stable disease"),
    27: ("W", "type wrong + all fields empty"),
    28: ("W", "type wrong (recurrence vs progression) + date very wrong"),
    29: ("D", "gold has date only, pred has status only — can't compare"),
    30: ("W", "type+date+drug right, intent missing → strict W"),
    31: ("W", "wrong date (different surgery), completeness missing"),
    32: ("W", "gave RT-end info for RT-start prompt"),
    33: ("W", "site detail missing (local vs local soft tissue)"),
    34: ("W", "reason missing (completion vs empty)"),
    35: ("C", "all fields match — date, cycles, reason, type — clean improvement"),
    36: ("W", "type wrong (progression vs recurrence)"),
    37: ("C", "46 == 46"),
    38: ("C", "Myxoid liposarcoma + correct ICD"),
    39: ("C", "Buttock match + ICD"),
    40: ("W", "'Not applicable' for clearly-male note"),
    41: ("W", "'Not applicable' for clearly-female note"),
    42: ("C", "localized == localized"),
    43: ("C", "69 == 69"),
    44: ("C", "PEComa == Perivascular epithelioid cell tumour, malignant; ICD 8714/3 matches"),
    45: ("C", "Bladder == Vescica (Italian); category and ICD match"),
    46: ("C", "value 10 matches; denominator conventions differ"),
    47: ("W", "wrong surgery picked; completeness missing"),
    48: ("W", "type wrong (post-op vs therapeutic); date+drug ok"),
    49: ("W", "wrong date + completeness missing"),
    50: ("W", "gave RT-end info for RT-start prompt"),
    51: ("W", "'None' vs 'local' — backend says no recurrence where gold does"),
    52: ("W", "'Not applicable' instead of stable disease"),
    53: ("W", "type wrong + all fields empty"),
    54: ("W", "type wrong + date wrong"),
    55: ("D", "gold has date only, pred has status only"),
    56: ("W", "biopsy grade 1 vs gold grade 2 — model misread"),
    57: ("W", "intent (curative) missing from pred"),
    58: ("W", "reason missing (completion)"),
    59: ("C", "fills date and place from note text — improvement over gold's placeholders"),
    60: ("W", "gold=unknown, pred=distant metastases (lung) — overconfident"),
    61: ("W", "different histology (spindle cell vs undifferentiated)"),
    62: ("C", "thigh == Upper leg + ICD"),
    63: ("W", "date 18/05 actually correct per note, but completeness missing"),
    64: ("D", "gold is a response annotation mislabeled as RT-start"),
    65: ("W", "'Not applicable' instead of progression"),
    66: ("W", "biopsy grade 1 vs gold grade 3 — model misread"),
    67: ("C", "110mm + date filled"),
    68: ("C", "leg + Leg + standard category + ICD"),
    69: ("C", "date right; both gold and pred abstain on completeness"),
    70: ("C", "distant metastases (lung) matches note evidence even though gold says 'other'"),
    71: ("C", "84 == 84"),
    72: ("C", "Undifferentiated sarcoma + ICD 8805/3 filled where gold had placeholder"),
}


def main() -> None:
    pairs = json.loads(Path("/tmp/judge_pairs_backend.json").read_text())
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

    print("=== Per-prompt LLM-as-judge accuracy (27B BACKEND filtered) ===")
    print(agg.to_string())
    print()
    total_c = (df["verdict"] == "C").sum()
    total_w = (df["verdict"] == "W").sum()
    total_d = (df["verdict"] == "D").sum()
    print(f"Overall: {total_c}/{total_c+total_w} = {total_c/(total_c+total_w)*100:.1f}% "
          f"(data issues excluded: {total_d})")

    df.to_csv(ARTIFACTS_DIR / "judge_verdicts_backend.csv", index=False)
    agg.to_csv(ARTIFACTS_DIR / "judge_per_prompt_backend.csv")
    print(f"\nWrote: {NLP_DIR / 'judge_verdicts_backend.csv'}")
    print(f"Wrote: {NLP_DIR / 'judge_per_prompt_backend.csv'}")


if __name__ == "__main__":
    main()
