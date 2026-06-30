#!/usr/bin/env python3
"""
Build a per-variable comparison between the PDF (NLP_variables_analysis.pdf)
and the latest evaluation run.

Outputs:
  comparison_to_pdf.csv   — full table sorted by tier then by 27B score
  comparison_to_pdf.md    — Markdown table grouped by PDF tier (printed to stdout)
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR

# PDF claims, hand-keyed from docs/NLP_variables_analysis.pdf.
# tier:    "reliable" | "usable" | "unreliable"
# pdf_pct: best single-number approximation of the PDF's "Accuracy" column,
#          using the dominant sub-field when the variable bundles several.
PDF: dict[str, dict] = {
    # === Reliable tier (12) ===
    "histological-tipo-int":         dict(tier="reliable",   pdf_pct=76,  pdf_note="~76% correct; ICD-O-3 morphology codes unreliable"),
    "necrosis_in_biopsy-int":        dict(tier="reliable",   pdf_pct=None,pdf_note="High specificity on positive cases"),
    "biopsymitoticcount-int":        dict(tier="reliable",   pdf_pct=None,pdf_note="Reliable when value explicitly in note"),
    "surgical-mitotic-count-int":    dict(tier="reliable",   pdf_pct=None,pdf_note="Reliable when value explicitly in note"),
    "stage_at_diagnosis-int":        dict(tier="reliable",   pdf_pct=75,  pdf_note="~75% after fix; localised vs locoregional vs metastatic"),
    "previous_cancer_treatment-int": dict(tier="reliable",   pdf_pct=None,pdf_note="Reliable with step-by-step reasoning"),
    "patient-status-int":            dict(tier="reliable",   pdf_pct=None,pdf_note="Reliable with reasoning; identifies metastasis sites"),
    "surgerytype-fs30-int":          dict(tier="reliable",   pdf_pct=100, pdf_note="Type 14/14, date 12/14, completeness 13/14"),
    "radiotherapy_end-int":          dict(tier="reliable",   pdf_pct=90,  pdf_note="Dose/fractions/date each 9/10"),
    "chemotherapy_end-int":          dict(tier="reliable",   pdf_pct=71,  pdf_note="Date 10/14, reason 10/14, cycles 8/14"),
    "chemotherapy_start-int":        dict(tier="reliable",   pdf_pct=100, pdf_note="Setting 16/16, date 11/16, intent 8/16"),
    "surgerymargins-int":            dict(tier="reliable",   pdf_pct=None,pdf_note="R0 in 56% / R1 in 44% of classified cases"),
    # === Usable as suggestions (10) ===
    "ageatdiagnosis-int":            dict(tier="usable",     pdf_pct=None,pdf_note="Works on clinical notes; confused on path/radiology"),
    "gender-int":                    dict(tier="usable",     pdf_pct=75,  pdf_note="Defaults to female ~75%; misses Italian masculine markers"),
    "tumorsite-int":                 dict(tier="usable",     pdf_pct=None,pdf_note="Site name often correct; ICD-O-3 topo wrong"),
    "biopsygrading-int":             dict(tier="usable",     pdf_pct=None,pdf_note="Correct when grade explicitly stated"),
    "tumordiameter-int":             dict(tier="usable",     pdf_pct=None,pdf_note="Systematic cm→mm unit conversion errors"),
    "recurrencetype-int":            dict(tier="usable",     pdf_pct=93,  pdf_note="Type 26/28; metastasis sites only 4/14"),
    "recur_or_prog-int":             dict(tier="usable",     pdf_pct=62,  pdf_note="Status works; date in 16/26"),
    "reexcision-int":                dict(tier="usable",     pdf_pct=58,  pdf_note="Date 7/12, completeness 8/12"),
    "tumorbiopsytype-int":           dict(tier="usable",     pdf_pct=52,  pdf_note="Date/institution 11/21; type only 7/21"),
    "radiotherapy_start-int":        dict(tier="usable",     pdf_pct=57,  pdf_note="Weakest multi-field; intent 4/7, hospital/date 2/7"),
    # === Unreliable (5) ===
    "response-to-int":               dict(tier="unreliable", pdf_pct=0,   pdf_note="0/28 — outputs 'Not applicable' always"),
    "occurrence_cancer-int":         dict(tier="unreliable", pdf_pct=38,  pdf_note="Confuses index sarcoma with 'other cancers' (5/13 ok)"),
    "tumordepth-int":                dict(tier="unreliable", pdf_pct=14,  pdf_note="86% 'Not applicable' (rarely stated explicitly)"),
    "surgical-specimen-grading-int": dict(tier="unreliable", pdf_pct=7,   pdf_note="93% 'Not applicable' (only in pathology reports)"),
    "necrosis_in_surgical-int":      dict(tier="unreliable", pdf_pct=None,pdf_note="Too few cases in test set"),
}

TIER_ORDER = {"reliable": 0, "usable": 1, "unreliable": 2}


def to_bool(s) -> bool:
    return str(s).strip().lower() in {"true", "1", "yes"}


def main() -> None:
    df = pd.read_csv(NLP_DIR / "llm_evaluation_detailed.csv",
                     sep=";", engine="python", on_bad_lines="skip")
    df["has_gold"] = df["expected_annotation"].notna() & (
        df["expected_annotation"].astype(str).str.strip() != ""
    )
    sub = df[df["has_gold"]].copy()
    sub["high_sim_b"] = sub["high_similarity"].apply(to_bool)
    sub["exact_b"] = sub["exact_match"].apply(to_bool)

    grouped = sub.groupby("prompt_type").agg(
        n=("prompt_type", "size"),
        high_sim=("high_sim_b", "sum"),
        exact=("exact_b", "sum"),
        avg_sim=("similarity_score", "mean"),
    ).reset_index()
    grouped["run_pct"] = (grouped["high_sim"] / grouped["n"] * 100).round(1)

    rows = []
    for key, meta in PDF.items():
        r = grouped[grouped["prompt_type"] == key]
        if len(r) == 0:
            rows.append({
                "tier":          meta["tier"],
                "prompt_key":    key,
                "n_with_gold":   0,
                "27B_high_sim":  None,
                "27B_pct":       None,
                "27B_avg_sim":   None,
                "PDF_pct":       meta["pdf_pct"],
                "PDF_note":      meta["pdf_note"],
                "delta_vs_PDF":  None,
            })
            continue
        r = r.iloc[0]
        delta = None
        if meta["pdf_pct"] is not None:
            delta = round(r["run_pct"] - meta["pdf_pct"], 1)
        rows.append({
            "tier":          meta["tier"],
            "prompt_key":    key,
            "n_with_gold":   int(r["n"]),
            "27B_high_sim":  int(r["high_sim"]),
            "27B_pct":       float(r["run_pct"]),
            "27B_avg_sim":   round(float(r["avg_sim"]), 3),
            "PDF_pct":       meta["pdf_pct"],
            "PDF_note":      meta["pdf_note"],
            "delta_vs_PDF":  delta,
        })

    out = pd.DataFrame(rows)
    out["tier_order"] = out["tier"].map(TIER_ORDER)
    out = out.sort_values(["tier_order", "27B_pct"], ascending=[True, False]).drop(columns="tier_order")
    out_path = ARTIFACTS_DIR / "comparison_to_pdf.csv"
    out.to_csv(out_path, index=False)
    print(f"[wrote] {out_path}")

    # Markdown view grouped by tier
    print()
    for tier_name in ["reliable", "usable", "unreliable"]:
        chunk = out[out["tier"] == tier_name]
        if chunk.empty:
            continue
        print(f"### {tier_name.upper()}  (PDF tier)")
        print()
        print("| variable | n | 27B high-sim | 27B % | PDF % | Δ | PDF note |")
        print("|---|---|---|---|---|---|---|")
        for _, r in chunk.iterrows():
            pdf_pct = "" if r["PDF_pct"] is None or pd.isna(r["PDF_pct"]) else f'{r["PDF_pct"]}%'
            run_pct = "—" if r["27B_pct"] is None or pd.isna(r["27B_pct"]) else f'{r["27B_pct"]}%'
            high = "—" if r["27B_high_sim"] is None or pd.isna(r["27B_high_sim"]) else f'{int(r["27B_high_sim"])}/{int(r["n_with_gold"])}'
            delta = ""
            if r["delta_vs_PDF"] is not None and not pd.isna(r["delta_vs_PDF"]):
                sign = "+" if r["delta_vs_PDF"] >= 0 else ""
                delta = f'{sign}{r["delta_vs_PDF"]}'
            n_disp = "0" if r["n_with_gold"] == 0 or pd.isna(r["n_with_gold"]) else str(int(r["n_with_gold"]))
            print(f'| {r["prompt_key"]} | {n_disp} | {high} | {run_pct} | {pdf_pct} | {delta} | {r["PDF_note"]} |')
        print()


if __name__ == "__main__":
    main()
