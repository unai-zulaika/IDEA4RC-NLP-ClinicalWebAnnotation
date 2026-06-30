#!/usr/bin/env python3
"""LLM-as-judge verdicts for the original PDF session (4B, zero-shot, Mar 26)."""
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR

VERDICTS: dict[int, tuple[str, str]] = {
    0:  ("W", "grade 1 vs gold 3"),
    1:  ("C", "date matches, both abstain on type, 'the hospital' for place"),
    2:  ("W", "'Sarcoma NOS' vs 'Undifferentiated sarcoma'; wrong ICD"),
    3:  ("W", "15mm vs 150mm (missing zero!)"),
    4:  ("W", "'Wall' less specific than 'Thoracic Wall'"),
    5:  ("W", "wrong treatments"),
    6:  ("C", "type label non-standard but date+completeness both match"),
    7:  ("C", "46 == 46"),
    8:  ("C", "Leiomyosarcoma matches; ICD wrong"),
    9:  ("C", "Utero + ICD"),
    10: ("D", "gold has end info mislabeled as start"),
    11: ("W", "16mm vs 90mm"),
    12: ("W", "type wrong (pre vs post), date partial wrong"),
    13: ("W", "type+date+drug+intent all wrong"),
    14: ("W", "type matches, site detail missing"),
    15: ("W", "Not applicable"),
    16: ("W", "type wrong + date wrong"),
    17: ("C", "R1 == R1"),
    18: ("W", "wrong date (05-08-2019 vs 28/07/2021)"),
    19: ("W", "type matches but date wrong (24-06-2021 vs 12/04/2022)"),
    20: ("W", "wrong date"),
    21: ("C", "female == female"),
    22: ("W", "model produced empty/placeholder fields"),
    23: ("W", "type wrong + date missing"),
    24: ("W", "local vs metastatic"),
    25: ("W", "type wrong + fractions wrong + reason garbage"),
    26: ("W", "Not applicable"),
    27: ("W", "type wrong + date partial + reason wrong"),
    28: ("W", "type wrong + date wrong"),
    29: ("D", "gold date only, pred 'Not applicable'"),
    30: ("W", "type wrong + date wrong + intent wrong"),
    31: ("W", "wrong surgery picked (25/10/2019)"),
    32: ("W", "Not applicable for clear RT info"),
    33: ("W", "type=local matches, site missing"),
    34: ("W", "type wrong + reason wrong (tumor progression vs completion)"),
    35: ("W", "type matches + cycles matches; date wrong + reason wrong"),
    36: ("W", "type wrong + date wrong"),
    37: ("C", "46 == 46"),
    38: ("C", "Liposarcoma mixoid (typo for myxoid) matches gold; ICD wrong"),
    39: ("W", "'Gluteus' anatomically matches Buttock, but category 'Trunk wall' wrong"),
    40: ("W", "'female' for male patient"),
    41: ("C", "female == female"),
    42: ("C", "localized"),
    43: ("C", "69 == 69"),
    44: ("C", "PEComa matches; ICD wrong"),
    45: ("W", "Utero vs Bladder (model confused)"),
    46: ("C", "value 10 matches"),
    47: ("W", "wrong date (09/03/2020 vs 03/09/2019)"),
    48: ("W", "empty fields"),
    49: ("W", "wrong date"),
    50: ("W", "Not applicable for clear RT info"),
    51: ("W", "metastatic vs local"),
    52: ("W", "Not applicable"),
    53: ("W", "type wrong + date wrong + cycles wrong + reason garbage"),
    54: ("W", "type wrong + date wrong"),
    55: ("D", "gold date only, pred status only"),
    56: ("C", "2 == 2"),
    57: ("W", "type wrong + date missing"),
    58: ("W", "type wrong + reason wrong"),
    59: ("W", "biopsy type missing (uses placeholder vs gold core-trucut)"),
    60: ("W", "overconfident (gold=unknown)"),
    61: ("W", "Italian description matches note, gold says undifferentiated"),
    62: ("W", "completely wrong location (Trunk wall vs Upper/Lower limbs)"),
    63: ("W", "wrong date (28/04 vs 15/05)"),
    64: ("D", "gold is response annotation mislabeled"),
    65: ("W", "Not applicable"),
    66: ("W", "grade 1 vs gold 3"),
    67: ("W", "11mm vs 110mm (missing zero)"),
    68: ("W", "incomplete output (no site name)"),
    69: ("W", "date close (20 vs 12 of Feb) but wrong day"),
    70: ("W", "metastatic (nodal) vs distant metastases (other)"),
    71: ("C", "84 == 84"),
    72: ("C", "Sarcoma indifferenziato (Italian) matches Undifferentiated; ICD wrong"),
}


def main() -> None:
    pairs = json.loads(Path("/tmp/judge_pairs_pdf_session.json").read_text())
    rows = []
    for p in pairs:
        v, reason = VERDICTS.get(p["idx"], ("?", "no verdict"))
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

    print("=== Per-prompt LLM-as-judge accuracy (4B PDF session, zero-shot, Mar 26) ===")
    print(agg.to_string())
    c = (df["verdict"] == "C").sum()
    w = (df["verdict"] == "W").sum()
    d = (df["verdict"] == "D").sum()
    print(f"\nOverall: {c}/{c+w} = {c/(c+w)*100:.1f}% (data-issues: {d})")

    df.to_csv(ARTIFACTS_DIR / "judge_verdicts_pdf_session.csv", index=False)
    agg.to_csv(ARTIFACTS_DIR / "judge_per_prompt_pdf_session.csv")


if __name__ == "__main__":
    main()
