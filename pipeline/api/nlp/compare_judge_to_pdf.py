#!/usr/bin/env python3
"""
Side-by-side: LLM-as-judge verdicts on the 27B run vs. PDF NLP analysis.

Reads:  judge_per_prompt.csv (from judge_verdicts.py)
        judge_verdicts.csv  (per-row verdicts incl. data-issue rows)
Writes: comparison_judge_vs_pdf.csv  (full table)
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR

PDF = {
    # Reliable
    "histological-tipo-int":         dict(tier="reliable",   pdf_pct=76),
    "necrosis_in_biopsy-int":        dict(tier="reliable",   pdf_pct=None),
    "biopsymitoticcount-int":        dict(tier="reliable",   pdf_pct=None),
    "surgical-mitotic-count-int":    dict(tier="reliable",   pdf_pct=None),
    "stage_at_diagnosis-int":        dict(tier="reliable",   pdf_pct=75),
    "previous_cancer_treatment-int": dict(tier="reliable",   pdf_pct=None),
    "patient-status-int":            dict(tier="reliable",   pdf_pct=None),
    "surgerytype-fs30-int":          dict(tier="reliable",   pdf_pct=93),   # avg of 14/14, 12/14, 13/14
    "radiotherapy_end-int":          dict(tier="reliable",   pdf_pct=90),
    "chemotherapy_end-int":          dict(tier="reliable",   pdf_pct=66),   # avg of 10/14, 10/14, 8/14
    "chemotherapy_start-int":        dict(tier="reliable",   pdf_pct=72),   # avg of 16/16, 11/16, 8/16
    "surgerymargins-int":            dict(tier="reliable",   pdf_pct=None),
    # Usable
    "ageatdiagnosis-int":            dict(tier="usable",     pdf_pct=None),
    "gender-int":                    dict(tier="usable",     pdf_pct=75),
    "tumorsite-int":                 dict(tier="usable",     pdf_pct=None),
    "biopsygrading-int":             dict(tier="usable",     pdf_pct=None),
    "tumordiameter-int":             dict(tier="usable",     pdf_pct=None),
    "recurrencetype-int":            dict(tier="usable",     pdf_pct=93),
    "recur_or_prog-int":             dict(tier="usable",     pdf_pct=62),
    "reexcision-int":                dict(tier="usable",     pdf_pct=63),
    "tumorbiopsytype-int":           dict(tier="usable",     pdf_pct=46),
    "radiotherapy_start-int":        dict(tier="usable",     pdf_pct=38),   # avg of 4/7, 2/7, 2/7
    # Unreliable
    "response-to-int":               dict(tier="unreliable", pdf_pct=0),
    "occurrence_cancer-int":         dict(tier="unreliable", pdf_pct=38),
    "tumordepth-int":                dict(tier="unreliable", pdf_pct=14),
    "surgical-specimen-grading-int": dict(tier="unreliable", pdf_pct=7),
    "necrosis_in_surgical-int":      dict(tier="unreliable", pdf_pct=None),
}

TIER_ORDER = {"reliable": 0, "usable": 1, "unreliable": 2}


def main() -> None:
    per = pd.read_csv(ARTIFACTS_DIR / "judge_per_prompt.csv").set_index("prompt_type")
    verdicts = pd.read_csv(ARTIFACTS_DIR / "judge_verdicts.csv")
    data_only_prompts = (
        verdicts[verdicts["verdict"] == "D"].groupby("prompt_type").size()
    )

    rows = []
    for key, meta in PDF.items():
        if key in per.index:
            r = per.loc[key]
            judged = int(r["n_judged"])
            correct = int(r["n_correct"])
            di = int(r.get("data_issues", 0) or 0)
            pct = float(r["judge_pct"])
        elif key in data_only_prompts.index:
            judged = 0
            correct = 0
            di = int(data_only_prompts[key])
            pct = None
        else:
            judged = 0
            correct = 0
            di = 0
            pct = None

        delta = None if (pct is None or meta["pdf_pct"] is None) else round(pct - meta["pdf_pct"], 1)
        rows.append({
            "tier":         meta["tier"],
            "prompt_key":   key,
            "n_judged":     judged,
            "n_correct":    correct,
            "27B_judge_pct": pct,
            "data_issues":  di,
            "PDF_pct":      meta["pdf_pct"],
            "delta_vs_PDF": delta,
        })

    df = pd.DataFrame(rows)
    df["tier_order"] = df["tier"].map(TIER_ORDER)
    df = df.sort_values(["tier_order", "27B_judge_pct"], ascending=[True, False]).drop(columns="tier_order")
    df.to_csv(ARTIFACTS_DIR / "comparison_judge_vs_pdf.csv", index=False)
    print(f"[wrote] {NLP_DIR / 'comparison_judge_vs_pdf.csv'}")
    print()

    for tier in ["reliable", "usable", "unreliable"]:
        chunk = df[df["tier"] == tier]
        if chunk.empty:
            continue
        print(f"### {tier.upper()}  (PDF tier)")
        print()
        print("| variable | judged | correct | 27B % | PDF % | Δ | data-issues |")
        print("|---|---|---|---|---|---|---|")
        for _, r in chunk.iterrows():
            pdf_pct = "" if r["PDF_pct"] is None or pd.isna(r["PDF_pct"]) else f'{int(r["PDF_pct"])}%'
            pct = "—" if r["27B_judge_pct"] is None or pd.isna(r["27B_judge_pct"]) else f'{r["27B_judge_pct"]}%'
            judged = "0" if pd.isna(r["n_judged"]) else str(int(r["n_judged"]))
            correct = "—" if r["n_judged"] == 0 else str(int(r["n_correct"]))
            delta = ""
            if r["delta_vs_PDF"] is not None and not pd.isna(r["delta_vs_PDF"]):
                sign = "+" if r["delta_vs_PDF"] >= 0 else ""
                delta = f'{sign}{r["delta_vs_PDF"]}'
            di = "" if pd.isna(r["data_issues"]) or r["data_issues"] == 0 else str(int(r["data_issues"]))
            print(f'| {r["prompt_key"]} | {judged} | {correct} | {pct} | {pdf_pct} | {delta} | {di} |')
        print()


if __name__ == "__main__":
    main()
