"""Rescore an existing results.json at different PM thresholds, and also report
a 'value-only' accuracy that ignores the boilerplate template prefix.

The point: FBK's PM (cosine over the full annotation string) gives credit for
predictions where the template prefix matches but the actual value flipped
(e.g. gold='present' vs pred='absent'). This rescorer shows how the headline
accuracy collapses under stricter or smarter scoring.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rag_retriever import embed  # noqa: E402

import numpy as np


def value_after_colon(s: str) -> str:
    """Pull the part after the last ': ' — that's the actual extracted value,
    minus the template boilerplate. Falls back to the full string."""
    s = s.strip().rstrip(".")
    if ":" in s:
        return s.rsplit(":", 1)[-1].strip().lower()
    return s.strip().lower()


def value_em(g: str, p: str) -> bool:
    return value_after_colon(g) == value_after_colon(p)


def rescore(results_path: Path, thresholds: list[float]) -> dict:
    data = json.loads(results_path.read_text())
    out: dict = {"thresholds": thresholds, "per_seed": [], "aggregate": {}}

    by_var: dict = {}
    for seed_block in data["per_seed"]:
        seed = seed_block["seed"]
        seed_out = {"seed": seed, "variables": {}}
        for var, var_block in seed_block["variables"].items():
            samples = var_block["samples"]
            golds = [s["gold"].strip() for s in samples]
            preds = [s["predicted"].strip() for s in samples]

            g_emb = embed(golds)
            p_emb = embed(preds)
            sims = (g_emb * p_emb).sum(axis=1)

            row = {"n": len(samples)}
            em = sum(1 for g, p in zip(golds, preds) if g == p)
            row["em_rate"] = em / len(samples)
            row["value_em_rate"] = sum(
                1 for g, p in zip(golds, preds) if value_em(g, p)
            ) / len(samples)
            for t in thresholds:
                acc = sum(1 for g, p, s in zip(golds, preds, sims) if g == p or s >= t) / len(samples)
                row[f"acc@PM{t}"] = acc
            seed_out["variables"][var] = row
            by_var.setdefault(var, []).append(row)
        out["per_seed"].append(seed_out)

    for var, rows in by_var.items():
        agg = {"n_seeds": len(rows)}
        keys = [k for k in rows[0] if k != "n"]
        for k in keys:
            vals = [r[k] for r in rows]
            agg[f"{k}_mean"] = float(np.mean(vals))
            agg[f"{k}_std"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
        out["aggregate"][var] = agg

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--results",
        default="experiments/fbk_reproduction/results.json",
    )
    ap.add_argument(
        "--thresholds",
        nargs="+",
        type=float,
        default=[0.3, 0.6, 0.77, 0.9, 0.95],
    )
    ap.add_argument(
        "--out",
        default="experiments/fbk_reproduction/rescore.json",
    )
    args = ap.parse_args()

    out = rescore(Path(args.results), args.thresholds)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"Wrote: {args.out}\n")

    print("=== Accuracy under different PM thresholds (mean across seeds) ===")
    header = ["variable", "EM", "VAL-EM"] + [f"PM>={t}" for t in args.thresholds]
    print("  " + "  ".join(f"{h:>10s}" for h in header))
    for var, a in out["aggregate"].items():
        row = [
            var[:18],
            f"{a['em_rate_mean']*100:5.1f}",
            f"{a['value_em_rate_mean']*100:5.1f}",
        ]
        for t in args.thresholds:
            row.append(f"{a[f'acc@PM{t}_mean']*100:5.1f}")
        print("  " + "  ".join(f"{c:>10s}" for c in row))

    print()
    print("VAL-EM = exact match on the value AFTER the template prefix")
    print("        (i.e. ignoring boilerplate; 'absent' vs 'present' shows up correctly)")


if __name__ == "__main__":
    main()
