#!/usr/bin/env python3
"""
Cross-cutting analysis: for one dimension, read the metrics.json of every run
that varies along it and produce a comparison table + bar plot.

  python exp_analyze.py --dimension fewshot_k
  python exp_analyze.py --all

Reads:  experiments/results/<run_id>/metrics.json
Writes: experiments/results/_analysis/<dimension>.csv  and .png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from exp_registry import RESULTS_ROOT, build_matrix, _vary

ANALYSIS_DIR = RESULTS_ROOT / "_analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def _load_metrics(run_id: str) -> dict | None:
    p = RESULTS_ROOT / run_id / "metrics.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _label_for(dimension: str, cfg) -> str:
    """Short label describing the varied value for this dimension."""
    return {
        "fewshot_k":    f"k={cfg.fewshot_k}",
        "filter":       "filter on" if cfg.filter else "filter off",
        "fewshot_mode": cfg.fewshot_mode,
        "model":        cfg.model,
        "reasoning":    f"{cfg.model} reason={'on' if cfg.reasoning else 'off'}",
    }.get(dimension, cfg.run_id())


def analyze(dimension: str, model: str | None = None, stack: str = "production") -> None:
    configs = build_matrix().get(dimension)
    if not configs:
        print(f"[skip] unknown dimension {dimension}")
        return
    # Re-key the dimension's configs to a specific model + stack. The matrix
    # anchors raw dimensions on 27b/raw; pass --model 4b --stack production to
    # analyze the 4b production sweep (the hospital-representative numbers).
    if model and dimension in ("fewshot_k", "filter", "fewshot_mode"):
        configs = [_vary(c, model=model, stack=stack) for c in configs]
    elif dimension == "reasoning" and model:
        configs = [_vary(c, model=model) for c in configs if c.model == "27b"] or configs
    suffix = f"_{model}_{stack}" if model else ""

    rows = []
    for cfg in configs:
        m = _load_metrics(cfg.run_id())
        if m is None:
            print(f"[warn] no metrics for {cfg.run_id()} (run + judge it first)")
            continue
        rows.append({
            "label":        _label_for(dimension, cfg),
            "run_id":       cfg.run_id(),
            "accuracy_pct": m.get("accuracy_pct"),
            "hallucination_rate_pct": m.get("hallucination_rate_pct"),
            "translation_leak_rate_pct": m.get("translation_leak_rate_pct"),
            "n_judged":     m.get("n_judged"),
        })
    if not rows:
        print(f"[skip] no completed runs for dimension {dimension}")
        return

    df = pd.DataFrame(rows)
    out_csv = ANALYSIS_DIR / f"{dimension}{suffix}.csv"
    df.to_csv(out_csv, index=False)
    print(f"[wrote] {out_csv}")
    print(df.to_string(index=False))

    # Bar plot: accuracy (+ hallucination as a second series)
    fig, ax = plt.subplots(figsize=(max(6, len(df) * 1.4), 5))
    x = np.arange(len(df))
    w = 0.38
    ax.bar(x - w / 2, df["accuracy_pct"].fillna(0), width=w, label="Accuracy %", color="#2b6cb0")
    ax.bar(x + w / 2, df["hallucination_rate_pct"].fillna(0), width=w,
           label="Hallucination %", color="#c53030")
    for i, v in enumerate(df["accuracy_pct"].fillna(0)):
        ax.text(x[i] - w / 2, v + 1, f"{v:.0f}", ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(df["label"], rotation=20, ha="right")
    ax.set_ylim(0, 105)
    ax.set_ylabel("%")
    ax.set_title(f"Dimension: {dimension}{(' — '+model) if model else ''}  (INT-SARC, LLM-as-judge auto-scored)")
    ax.legend()
    ax.yaxis.grid(color="#ddd", linewidth=0.5)
    ax.set_axisbelow(True)
    plt.tight_layout()
    out_png = ANALYSIS_DIR / f"{dimension}{suffix}.png"
    plt.savefig(out_png, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"[wrote] {out_png}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dimension", help="fewshot_k | filter | fewshot_mode | model | reasoning")
    ap.add_argument("--model", help="re-key dimensions to this model (e.g. 4b)")
    ap.add_argument("--stack", default="production", choices=["raw", "production"],
                    help="which stack to analyze (default: production = hospital report)")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all:
        for dim in build_matrix():
            print(f"\n===== {dim} =====")
            analyze(dim, model=args.model, stack=args.stack)
    elif args.dimension:
        analyze(args.dimension, model=args.model, stack=args.stack)
    else:
        raise SystemExit("specify --dimension or --all")


if __name__ == "__main__":
    main()
