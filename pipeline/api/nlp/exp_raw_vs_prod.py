#!/usr/bin/env python3
"""
Save the raw-vs-production matched comparison for a model as an artifact.

  python exp_raw_vs_prod.py --model 4b
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from exp_registry import RESULTS_ROOT

ANALYSIS_DIR = RESULTS_ROOT / "_analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def _load(run: str):
    p = RESULTS_ROOT / run / "metrics.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return d["accuracy_pct"], d["hallucination_rate_pct"], d.get("translation_leak_rate_pct")


CELLS = [
    ("k=0",        "INT-SARC__{model}__{stack}__k0__all__filter1__reason1__pre"),
    ("k=1",        "INT-SARC__{model}__{stack}__k1__all__filter1__reason1__pre"),
    ("k=3",        "INT-SARC__{model}__{stack}__k3__all__filter1__reason1__pre"),
    ("k=5",        "INT-SARC__{model}__{stack}__k5__all__filter1__reason1__pre"),
    ("k=10",       "INT-SARC__{model}__{stack}__k10__all__filter1__reason1__pre"),
    ("filter-off", "INT-SARC__{model}__{stack}__k5__all__filter0__reason1__pre"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    args = ap.parse_args()

    rows = []
    for label, tmpl in CELLS:
        raw = _load(tmpl.format(model=args.model, stack="raw"))
        prod = _load(tmpl.format(model=args.model, stack="production"))
        if not (raw and prod):
            continue
        rows.append({
            "cell": label,
            "raw_acc": raw[0], "prod_acc": prod[0], "delta_acc": round(prod[0]-raw[0], 1),
            "raw_halluc": raw[1], "prod_halluc": prod[1], "delta_halluc": round(prod[1]-raw[1], 1),
        })
    if not rows:
        raise SystemExit(f"no matched cells found for {args.model}")
    df = pd.DataFrame(rows)
    out_csv = ANALYSIS_DIR / f"raw_vs_prod_{args.model}.csv"
    df.to_csv(out_csv, index=False)
    print(f"[wrote] {out_csv}")
    print(df.to_string(index=False))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))
    x = np.arange(len(df)); w = 0.4
    ax1.bar(x - w/2, df["raw_acc"], width=w, color="#999999", label="raw")
    ax1.bar(x + w/2, df["prod_acc"], width=w, color="#2f855a", label="production")
    ax1.set_xticks(x); ax1.set_xticklabels(df["cell"], rotation=15)
    ax1.set_ylabel("Accuracy %"); ax1.set_ylim(0, 60)
    ax1.set_title(f"Accuracy — {args.model} (raw vs production, INT-SARC)")
    ax1.legend(); ax1.yaxis.grid(color="#ddd", linewidth=0.5); ax1.set_axisbelow(True)

    ax2.bar(x - w/2, df["raw_halluc"], width=w, color="#999999", label="raw")
    ax2.bar(x + w/2, df["prod_halluc"], width=w, color="#c53030", label="production")
    ax2.set_xticks(x); ax2.set_xticklabels(df["cell"], rotation=15)
    ax2.set_ylabel("Hallucination %"); ax2.set_ylim(0, 105)
    ax2.set_title(f"Hallucination — {args.model} (raw vs production)")
    ax2.legend(); ax2.yaxis.grid(color="#ddd", linewidth=0.5); ax2.set_axisbelow(True)

    plt.tight_layout()
    out_png = ANALYSIS_DIR / f"raw_vs_prod_{args.model}.png"
    plt.savefig(out_png, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"[wrote] {out_png}")


if __name__ == "__main__":
    main()
