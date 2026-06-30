#!/usr/bin/env python3
"""Three-way comparison: PDF (7B baseline) vs 27B-pipeline vs 27B-backend."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR

PDF_PCT = {
    "histological-tipo-int":         76,
    "stage_at_diagnosis-int":        75,
    "surgerytype-fs30-int":          93,
    "radiotherapy_end-int":          90,
    "chemotherapy_end-int":          66,
    "chemotherapy_start-int":        72,
    "gender-int":                    75,
    "recurrencetype-int":            93,
    "recur_or_prog-int":             62,
    "reexcision-int":                63,
    "tumorbiopsytype-int":           46,
    "radiotherapy_start-int":        38,
    "response-to-int":               0,
    "occurrence_cancer-int":         38,
    "tumordepth-int":                14,
    "surgical-specimen-grading-int": 7,
}

TIER = {
    "histological-tipo-int":         "reliable",
    "necrosis_in_biopsy-int":        "reliable",
    "biopsymitoticcount-int":        "reliable",
    "surgical-mitotic-count-int":    "reliable",
    "stage_at_diagnosis-int":        "reliable",
    "previous_cancer_treatment-int": "reliable",
    "patient-status-int":            "reliable",
    "surgerytype-fs30-int":          "reliable",
    "radiotherapy_end-int":          "reliable",
    "chemotherapy_end-int":          "reliable",
    "chemotherapy_start-int":        "reliable",
    "surgerymargins-int":            "reliable",
    "ageatdiagnosis-int":            "usable",
    "gender-int":                    "usable",
    "tumorsite-int":                 "usable",
    "biopsygrading-int":             "usable",
    "tumordiameter-int":             "usable",
    "recurrencetype-int":            "usable",
    "recur_or_prog-int":             "usable",
    "reexcision-int":                "usable",
    "tumorbiopsytype-int":           "usable",
    "radiotherapy_start-int":        "usable",
    "response-to-int":               "unreliable",
    "occurrence_cancer-int":         "unreliable",
    "tumordepth-int":                "unreliable",
    "surgical-specimen-grading-int": "unreliable",
    "necrosis_in_surgical-int":      "unreliable",
}
TIER_ORDER = {"reliable": 0, "usable": 1, "unreliable": 2}


def main() -> None:
    pipe = pd.read_csv(ARTIFACTS_DIR / "judge_per_prompt.csv").set_index("prompt_type")
    back = pd.read_csv(ARTIFACTS_DIR / "judge_per_prompt_backend.csv").set_index("prompt_type")

    rows = []
    for key, tier in TIER.items():
        pdf_pct = PDF_PCT.get(key)
        if key in pipe.index:
            r = pipe.loc[key]
            pipe_pct = float(r["judge_pct"])
            pipe_str = f'{int(r["n_correct"])}/{int(r["n_judged"])}'
        else:
            pipe_pct = None
            pipe_str = "—"
        if key in back.index:
            r = back.loc[key]
            back_pct = float(r["judge_pct"])
            back_str = f'{int(r["n_correct"])}/{int(r["n_judged"])}'
        else:
            back_pct = None
            back_str = "—"
        rows.append({
            "tier":        tier,
            "prompt_key":  key,
            "PDF_pct":     pdf_pct,
            "pipeline_str": pipe_str,
            "pipeline_pct": pipe_pct,
            "backend_str": back_str,
            "backend_pct": back_pct,
            "delta_back_vs_pipe": (None if (back_pct is None or pipe_pct is None) else round(back_pct - pipe_pct, 1)),
            "delta_back_vs_pdf":  (None if (back_pct is None or pdf_pct is None) else round(back_pct - pdf_pct, 1)),
        })
    df = pd.DataFrame(rows)
    df["tier_order"] = df["tier"].map(TIER_ORDER)
    df = df.sort_values(["tier_order", "backend_pct"], ascending=[True, False]).drop(columns="tier_order")
    df.to_csv(ARTIFACTS_DIR / "comparison_3way.csv", index=False)
    print(f"[wrote] {NLP_DIR / 'comparison_3way.csv'}")
    print()

    for tier in ["reliable", "usable", "unreliable"]:
        chunk = df[df["tier"] == tier]
        if chunk.empty:
            continue
        print(f"### {tier.upper()}")
        print()
        print("| variable | PDF % | 27B pipeline | 27B backend | Δ back vs pipe |")
        print("|---|---|---|---|---|")
        for _, r in chunk.iterrows():
            pdf = "" if r["PDF_pct"] is None or pd.isna(r["PDF_pct"]) else f'{int(r["PDF_pct"])}%'
            pipe_str = "—" if r["pipeline_str"] == "—" else f'{r["pipeline_str"]} ({r["pipeline_pct"]:.0f}%)'
            back_str = "—" if r["backend_str"] == "—" else f'{r["backend_str"]} ({r["backend_pct"]:.0f}%)'
            delta = ""
            if r["delta_back_vs_pipe"] is not None and not pd.isna(r["delta_back_vs_pipe"]):
                sign = "+" if r["delta_back_vs_pipe"] >= 0 else ""
                delta = f'{sign}{r["delta_back_vs_pipe"]}'
            print(f'| {r["prompt_key"]} | {pdf} | {pipe_str} | {back_str} | {delta} |')
        print()


if __name__ == "__main__":
    main()
