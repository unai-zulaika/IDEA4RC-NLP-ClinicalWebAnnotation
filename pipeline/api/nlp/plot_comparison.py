#!/usr/bin/env python3
"""Generate review-friendly comparison plots:

  1. Per-variable horizontal bar chart: PDF (7B) | 27B pipeline | 27B backend
  2. Tier-level stacked summary: count of reliable / usable / unreliable per pipeline
  3. Δ heatmap: shows where 27B wins and where backend regressed

Outputs:  docs/plot_27B_vs_7B_per_variable.png
          docs/plot_27B_vs_7B_tiers.png
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR
DOCS_DIR = NLP_DIR.parents[2] / "docs"

GREY  = "#999999"
BLUE  = "#2b6cb0"
GREEN = "#2f855a"
RED   = "#c53030"


def to_pct(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def main() -> None:
    df = pd.read_csv(ARTIFACTS_DIR / "comparison_3way.csv")

    # Keep only variables that have data in at least one of the 27B runs
    df = df[df["pipeline_pct"].notna() | df["backend_pct"].notna()].copy()
    # Sort within tier by backend pct (falling back to pipeline pct)
    df["sort_key"] = df["backend_pct"].fillna(df["pipeline_pct"].fillna(-1))
    tier_order = {"reliable": 0, "usable": 1, "unreliable": 2}
    df["tier_order"] = df["tier"].map(tier_order)
    df = df.sort_values(["tier_order", "sort_key"], ascending=[True, False]).reset_index(drop=True)

    # ----------------------------------------------------------------------
    # PLOT 1 — per-variable bar chart (PDF / pipeline / backend)
    # ----------------------------------------------------------------------
    n = len(df)
    y = np.arange(n)
    h = 0.27

    fig, ax = plt.subplots(figsize=(11, max(6, n * 0.35)))

    pdf_vals  = [to_pct(v) for v in df["PDF_pct"]]
    pipe_vals = [to_pct(v) for v in df["pipeline_pct"]]
    back_vals = [to_pct(v) for v in df["backend_pct"]]

    def _plot_bar(vals, offset, color, label):
        for i, v in enumerate(vals):
            if v is None:
                # No data measured — em-dash to the left of the axis
                ax.text(-2, y[i] + offset, "n/a", va="center", ha="right",
                        color=GREY, fontsize=7.5, style="italic")
            elif v == 0:
                # Measured zero — distinguish from missing by drawing a small
                # tick at x=0 plus an explicit "0" label.
                ax.plot([0, 0.6], [y[i] + offset, y[i] + offset],
                        color=color, linewidth=h * 18, solid_capstyle="butt")
                ax.text(2.5, y[i] + offset, "0", va="center", ha="left",
                        color=color, fontsize=8, fontweight="bold")
            else:
                ax.barh(y[i] + offset, v, height=h, color=color, edgecolor="white", linewidth=0.5)
                if v >= 8:
                    ax.text(v - 2, y[i] + offset, f"{v:.0f}", va="center", ha="right",
                            color="white", fontsize=8, fontweight="bold")
                else:
                    # Small value — put the label to the right of the bar
                    ax.text(v + 1.5, y[i] + offset, f"{v:.0f}", va="center", ha="left",
                            color=color, fontsize=8, fontweight="bold")

    _plot_bar(pdf_vals,  +h, GREY,  "7B (PDF baseline)")
    _plot_bar(pipe_vals,  0, BLUE,  "27B pipeline (raw vLLM)")
    _plot_bar(back_vals, -h, GREEN, "27B backend (full stack)")

    ax.set_yticks(y)
    ax.set_yticklabels(df["prompt_key"], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(-6, 110)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("LLM-as-judge accuracy on INT-SARC test set (%)")
    ax.set_title("Per-variable accuracy: 7B baseline vs 27B (pipeline) vs 27B (backend)")
    ax.grid(axis="x", color="#ddd", linestyle="-", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    # Tier shading on background
    tier_colors = {"reliable": "#e6f5e6", "usable": "#fff5e6", "unreliable": "#fde6e6"}
    last_tier = None
    tier_start = 0
    for i, t in enumerate(df["tier"]):
        if t != last_tier and last_tier is not None:
            ax.axhspan(tier_start - 0.5, i - 0.5, color=tier_colors[last_tier], zorder=-1, alpha=0.55)
            tier_start = i
        last_tier = t
    ax.axhspan(tier_start - 0.5, len(df) - 0.5, color=tier_colors[last_tier], zorder=-1, alpha=0.55)

    legend_elems = [
        mpatches.Patch(color=GREY, label="7B (PDF baseline)"),
        mpatches.Patch(color=BLUE, label="27B pipeline (raw vLLM)"),
        mpatches.Patch(color=GREEN, label="27B backend (full stack, filtered)"),
        mpatches.Patch(color=tier_colors["reliable"],  label="PDF tier: reliable",   alpha=0.55),
        mpatches.Patch(color=tier_colors["usable"],    label="PDF tier: usable",     alpha=0.55),
        mpatches.Patch(color=tier_colors["unreliable"],label="PDF tier: unreliable", alpha=0.55),
    ]
    ax.legend(handles=legend_elems, loc="lower right", framealpha=0.95, fontsize=8.5)

    plt.tight_layout()
    out_path = PLOTS_DIR / "per_variable_legacy.png"
    plt.savefig(out_path, dpi=170, bbox_inches="tight")
    print(f"[wrote] {out_path}")
    plt.close(fig)

    # ----------------------------------------------------------------------
    # PLOT 2 — overall accuracy summary + delta-vs-pipeline chart
    # ----------------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6),
                                    gridspec_kw={"width_ratios": [1, 1.4]})

    # Overall accuracy bar
    overall_labels = ["27B\npipeline", "27B backend\n(structured output\n+ history split\n+ ICD lookup)"]
    overall_vals   = [48.6, 37.7]
    overall_colors = [BLUE, GREEN]
    bars = ax1.bar(overall_labels, overall_vals, color=overall_colors, width=0.55, edgecolor="white", linewidth=2)
    for bar, v in zip(bars, overall_vals):
        ax1.text(bar.get_x() + bar.get_width() / 2, v + 1.5, f"{v:.1f}%",
                ha="center", va="bottom", fontsize=14, fontweight="bold")
    ax1.set_ylim(0, 70)
    ax1.set_ylabel("Overall LLM-as-judge accuracy (%)")
    ax1.set_title("Overall accuracy (73-76 gold pairs)")
    ax1.yaxis.grid(color="#ddd", linewidth=0.5)
    ax1.set_axisbelow(True)
    ax1.text(0.5, 0.97,
             "PDF baseline reported per-variable\nrather than a single overall number",
             transform=ax1.transAxes, ha="center", va="top", fontsize=8.5,
             color="#666", style="italic")

    # Per-variable delta (backend - pipeline)
    df_d = df[df["delta_back_vs_pipe"].notna()].copy()
    df_d = df_d.sort_values("delta_back_vs_pipe")
    colors_d = [RED if v < 0 else (GREEN if v > 0 else GREY) for v in df_d["delta_back_vs_pipe"]]
    y2 = np.arange(len(df_d))
    ax2.barh(y2, df_d["delta_back_vs_pipe"], color=colors_d, edgecolor="white", linewidth=0.5)
    for i, v in enumerate(df_d["delta_back_vs_pipe"]):
        if abs(v) < 1:
            continue
        offset = 1.5 if v > 0 else -1.5
        ha = "left" if v > 0 else "right"
        ax2.text(v + offset, y2[i], f"{v:+.0f}", va="center", ha=ha, fontsize=8.5,
                 color="black", fontweight="bold")
    ax2.set_yticks(y2)
    ax2.set_yticklabels(df_d["prompt_key"], fontsize=8)
    ax2.axvline(0, color="black", linewidth=0.8)
    ax2.set_xlabel("Δ percentage points (backend − pipeline)")
    ax2.set_title("Per-variable impact of the backend stack")
    ax2.set_xlim(-110, 50)
    ax2.grid(axis="x", color="#ddd", linewidth=0.5)
    ax2.set_axisbelow(True)

    plt.tight_layout()
    out_path2 = PLOTS_DIR / "summary.png"
    plt.savefig(out_path2, dpi=170, bbox_inches="tight")
    print(f"[wrote] {out_path2}")
    plt.close(fig)


if __name__ == "__main__":
    main()
