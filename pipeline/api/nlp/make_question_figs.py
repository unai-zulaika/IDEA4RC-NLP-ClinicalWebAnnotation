#!/usr/bin/env python3
"""Charts for the 'other questions' (Q3 example quality, Q4 example count) from the
INT-SARC tuning matrix (small model, auto-judge scorer - relative effects, not headline accuracy).
Writes fig_q4_count.png + fig_q3_quality.png to docs/reports/figs/.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FIGS = Path("/home/zulaika/ClinicalAnnotationWeb/docs/reports/figs")
GREY, BLUE, GREEN, RED = "#9aa4b2", "#1a4f8b", "#1a7f37", "#b42318"
plt.rcParams.update({"font.size": 13, "axes.titlesize": 15, "axes.titleweight": "bold",
                     "figure.facecolor": "white"})

# Q4: few-shot COUNT (4B production sweep)
K = ["0", "1", "3", "5", "10"]
ACC = [25.0, 26.5, 38.2, 38.2, 36.8]


def fig_q4():
    fig, ax = plt.subplots(figsize=(9, 5.2))
    colors = [GREY, GREY, BLUE, BLUE, BLUE]
    ax.bar(range(len(K)), ACC, 0.62, color=colors)
    for i, v in enumerate(ACC):
        ax.text(i, v + 0.8, f"{v:.0f}%", ha="center", fontweight="bold")
    ax.axhline(38.2, ls="--", lw=1, color="#888")
    ax.set_xticks(range(len(K))); ax.set_xticklabels([f"{k}\nexamples" for k in K])
    ax.set_ylim(0, 50); ax.set_ylabel("Accuracy (%)")
    ax.set_title("Q4 - a few examples help a lot, then it plateaus")
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(2.0, 44, "jump from 0 -> 3 examples", color=GREEN, fontweight="bold", ha="center")
    fig.tight_layout(); fig.savefig(FIGS / "fig_q4_count.png", dpi=150); plt.close(fig)


# Q3: few-shot QUALITY (4B raw sweep)
CAT = ["Complete\n(clean)", "Mixed\n(as-is)", "Note\nonly", "Incomplete\n(placeholders)"]
QACC = [39.1, 37.7, 29.0, 10.1]


def fig_q3():
    fig, ax = plt.subplots(figsize=(9, 5.2))
    colors = [GREEN, BLUE, GREY, RED]
    ax.bar(range(len(CAT)), QACC, 0.62, color=colors)
    for i, v in enumerate(QACC):
        ax.text(i, v + 0.8, f"{v:.0f}%", ha="center", fontweight="bold")
    ax.set_xticks(range(len(CAT))); ax.set_xticklabels(CAT)
    ax.set_ylim(0, 50); ax.set_ylabel("Accuracy (%)")
    ax.set_title("Q3 - clean examples help; messy ones poison the output")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIGS / "fig_q3_quality.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    fig_q4(); fig_q3()
    print("wrote fig_q4_count.png + fig_q3_quality.png")
