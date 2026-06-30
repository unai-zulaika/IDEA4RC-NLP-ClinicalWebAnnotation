#!/usr/bin/env python3
"""Per-sub-field comparison plot — 4-column view:
  7B (PDF) | 27B pipeline | 27B backend (pre prompt-fix) | 27B backend (post prompt-fix)

Only the multi-field prompts (where the PDF reports per-sub-field denominators).
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

GREY     = "#999999"
PURPLE   = "#6b46c1"   # 4B raw
PINK     = "#b83280"   # 4B production
BLUE     = "#2b6cb0"   # 27B raw
GREEN    = "#2f855a"   # 27B production post-fix

MULTI_PROMPTS = [
    "surgerytype-fs30",
    "chemotherapy_start",
    "chemotherapy_end",
    "radiotherapy_start",
    "radiotherapy_end",
    "tumorbiopsytype",
    "reexcision",
    "recurrencetype",
    "recur_or_prog",
]


def main() -> None:
    df = pd.read_csv(ARTIFACTS_DIR / "comparison_per_subfield.csv")
    df = df[df["prompt"].isin(MULTI_PROMPTS)].reset_index(drop=True)

    labels: list[str] = []
    pdf_sess_vals: list[float | None] = []
    pipe_4B_vals: list[float | None] = []
    back_4B_vals: list[float | None] = []
    pipe_vals: list[float | None] = []
    back_v2_vals: list[float | None] = []
    prompt_breaks: list[int] = []

    last_prompt = None
    for _, r in df.iterrows():
        if r["prompt"] != last_prompt:
            prompt_breaks.append(len(labels))
            last_prompt = r["prompt"]
        labels.append(f'{r["prompt"]} · {r["sub_field"]}')
        pdf_sess_vals.append(None if pd.isna(r["pdf_sess_pct"]) else float(r["pdf_sess_pct"]))
        pipe_4B_vals.append(None if pd.isna(r["pipe_4B_pct"]) else float(r["pipe_4B_pct"]))
        back_4B_vals.append(None if pd.isna(r["back_4B_pct"]) else float(r["back_4B_pct"]))
        pipe_vals.append(None if pd.isna(r["pipe_pct"]) else float(r["pipe_pct"]))
        back_v2_vals.append(None if pd.isna(r["back_v2_pct"]) else float(r["back_v2_pct"]))

    n = len(labels)
    y = np.arange(n)
    h = 0.16  # tighter to fit 5 bars

    fig, ax = plt.subplots(figsize=(13, max(9, n * 0.42)))

    def _plot_bar(vals, offset, color):
        for i, v in enumerate(vals):
            if v is None:
                ax.text(-2, y[i] + offset, "n/a", va="center", ha="right",
                        color=GREY, fontsize=7, style="italic")
            elif v == 0:
                ax.plot([0, 0.5], [y[i] + offset, y[i] + offset],
                        color=color, linewidth=h * 18, solid_capstyle="butt")
                ax.text(2.5, y[i] + offset, "0", va="center", ha="left",
                        color=color, fontsize=7, fontweight="bold")
            else:
                ax.barh(y[i] + offset, v, height=h, color=color,
                        edgecolor="white", linewidth=0.4)
                if v >= 14:
                    ax.text(v - 2, y[i] + offset, f"{v:.0f}", va="center",
                            ha="right", color="white", fontsize=7, fontweight="bold")
                else:
                    ax.text(v + 1.5, y[i] + offset, f"{v:.0f}", va="center",
                            ha="left", color=color, fontsize=7, fontweight="bold")

    _plot_bar(pdf_sess_vals, +2.0 * h, GREY)
    _plot_bar(pipe_4B_vals,  +1.0 * h, PURPLE)
    _plot_bar(back_4B_vals,   0.0 * h, PINK)
    _plot_bar(pipe_vals,     -1.0 * h, BLUE)
    _plot_bar(back_v2_vals,  -2.0 * h, GREEN)

    for b in prompt_breaks[1:]:
        ax.axhline(b - 0.5, color="#bbb", linewidth=0.6, linestyle=":", zorder=1)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(-6, 110)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Per-sub-field accuracy (%) — same 28 INT-SARC notes, same gold annotations")
    ax.set_title("Per sub-field: PDF session (4B zero-shot, Mar 26)  vs  current 4B (5-shot)  vs  current 27B (5-shot)")
    ax.grid(axis="x", color="#ddd", linestyle="-", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    legend_elems = [
        mpatches.Patch(color=GREY,   label="PDF session (4B, zero-shot, Mar 26)"),
        mpatches.Patch(color=PURPLE, label="4B raw (5-shot, May 20)"),
        mpatches.Patch(color=PINK,   label="4B production (5-shot, post prompt-fix)"),
        mpatches.Patch(color=BLUE,   label="27B raw (5-shot)"),
        mpatches.Patch(color=GREEN,  label="27B production (5-shot, post prompt-fix)"),
    ]
    ax.legend(handles=legend_elems, loc="lower right", framealpha=0.95, fontsize=8.5)

    plt.tight_layout()
    out_path = PLOTS_DIR / "per_subfield.png"
    plt.savefig(out_path, dpi=170, bbox_inches="tight")
    print(f"[wrote] {out_path}")
    plt.close(fig)

    # 5-cell overall accuracy bar chart + per-variable 27B-vs-4B delta
    pdf_sess_overall = 17 / 69 * 100
    pipe_4B_overall = 26 / 74 * 100
    back_4B_overall = 28 / 69 * 100
    pipe_27B_overall = 35 / 72 * 100
    back_v2_overall = 31 / 69 * 100

    fig2, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 7),
                                     gridspec_kw={"width_ratios": [1.1, 1.4]})

    labels_overall = ["PDF session\n4B zero-shot\n(Mar 26)",
                      "4B raw\n5-shot",
                      "4B production\n5-shot",
                      "27B raw\n5-shot",
                      "27B production\n5-shot"]
    vals_overall = [pdf_sess_overall, pipe_4B_overall, back_4B_overall,
                    pipe_27B_overall, back_v2_overall]
    colors_overall = [GREY, PURPLE, PINK, BLUE, GREEN]
    bars = ax1.bar(labels_overall, vals_overall, color=colors_overall,
                   width=0.65, edgecolor="white", linewidth=2)
    for bar, v in zip(bars, vals_overall):
        ax1.text(bar.get_x() + bar.get_width() / 2, v + 1.2, f"{v:.1f}%",
                 ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax1.set_ylim(0, 65)
    ax1.set_ylabel("Overall LLM-as-judge accuracy (%)")
    ax1.set_title("Overall on the same 28 INT-SARC notes (≈73 gold pairs)")
    ax1.yaxis.grid(color="#ddd", linewidth=0.5)
    ax1.set_axisbelow(True)
    ax1.tick_params(axis="x", labelsize=9)

    # Per-variable 27B-vs-4B backend delta (model effect, same stack)
    j_4B = pd.read_csv(ARTIFACTS_DIR / "judge_per_prompt_4B_backend.csv").set_index("prompt_type")
    j_27B = pd.read_csv(ARTIFACTS_DIR / "judge_per_prompt_backend_v2.csv").set_index("prompt_type")
    common = sorted(set(j_4B.index) & set(j_27B.index))
    rows = []
    for k in common:
        v4 = float(j_4B.loc[k, "judge_pct"])
        v27 = float(j_27B.loc[k, "judge_pct"])
        rows.append((k, v27 - v4, v4, v27))
    rows.sort(key=lambda x: x[1])

    keys = [r[0] for r in rows]
    deltas = [r[1] for r in rows]
    colors = ["#c53030" if d < 0 else ("#2f855a" if d > 0 else GREY) for d in deltas]
    y2 = np.arange(len(rows))
    ax2.barh(y2, deltas, color=colors, edgecolor="white", linewidth=0.5)
    for i, d in enumerate(deltas):
        if abs(d) < 1:
            continue
        offset = 1.5 if d > 0 else -1.5
        ha = "left" if d > 0 else "right"
        ax2.text(d + offset, y2[i], f"{d:+.0f}", va="center", ha=ha,
                 fontsize=8.5, fontweight="bold")
    ax2.set_yticks(y2)
    ax2.set_yticklabels(keys, fontsize=8)
    ax2.axvline(0, color="black", linewidth=0.8)
    ax2.set_xlabel("Δ percentage points (27B production − 4B production, both post prompt-fix)")
    ax2.set_title("Model-size effect per variable (same stack)")
    ax2.set_xlim(-40, 110)
    ax2.grid(axis="x", color="#ddd", linewidth=0.5)
    ax2.set_axisbelow(True)

    plt.tight_layout()
    out_path2 = PLOTS_DIR / "summary.png"
    plt.savefig(out_path2, dpi=170, bbox_inches="tight")
    print(f"[wrote] {out_path2}")
    plt.close(fig2)


if __name__ == "__main__":
    main()
