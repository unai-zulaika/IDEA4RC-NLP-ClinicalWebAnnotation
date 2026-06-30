"""Score the predictions.jsonl from run_full_25.py using OUR methodology:

For each (note, variable, gold, predicted):
  - both_empty     gold empty AND prediction empty/Unknown
  - false_positive gold empty AND prediction non-empty
  - false_negative gold present AND prediction empty/Unknown
  - match          gold present AND normalized strings equal
  - mismatch       gold present AND normalized strings differ

Then aggregate per variable into the same columns the filtered report uses:
  N, match, mismatch, FP, FN, both_empty,
  correct% = (match + both_empty) / N
  extract% = match / N
  abstain% = both_empty / N
  fp%      = FP / N
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from full_25_templates import VARIABLES  # noqa: E402


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split()).rstrip(".")


def _is_unknown(pred: str, unknown_fallback: str) -> bool:
    """Whether a prediction counts as 'empty/abstain'."""
    n = _norm(pred)
    if not n:
        return True
    fb = _norm(unknown_fallback)
    if n == fb or n.startswith("unknown ") or n == "unknown" or n.startswith("lack of information"):
        return True
    if "not applicable" in n:
        return True
    if "there was no progression" in n and "no progression" in fb:
        return True
    return False


def classify(gold: str, pred: str, unknown_fallback: str) -> str:
    g = _norm(gold)
    pred_empty = _is_unknown(pred, unknown_fallback)
    if not g:
        return "both_empty" if pred_empty else "false_positive"
    if pred_empty:
        return "false_negative"
    return "match" if _norm(pred) == g else "mismatch"


def aggregate(predictions_path: Path) -> dict:
    rows = [json.loads(l) for l in predictions_path.open()]
    by_var: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_var[r["variable"]].append(r)

    out: dict[str, dict] = {}
    for var_name, spec in VARIABLES.items():
        var_rows = by_var.get(var_name, [])
        counts = {"match": 0, "mismatch": 0, "false_positive": 0,
                  "false_negative": 0, "both_empty": 0}
        per_report_type: dict[str, dict[str, int]] = defaultdict(
            lambda: dict(counts))
        for r in var_rows:
            cat = classify(r.get("gold", ""), r.get("predicted", ""),
                           spec.unknown_fallback)
            counts[cat] += 1
            rt_counts = per_report_type[r["report_type"]]
            rt_counts[cat] = rt_counts.get(cat, 0) + 1

        n = sum(counts.values())
        out[var_name] = {
            "n": n,
            **counts,
            "correct_rate": (counts["match"] + counts["both_empty"]) / n if n else 0,
            "extract_rate": counts["match"] / n if n else 0,
            "abstain_rate": counts["both_empty"] / n if n else 0,
            "fp_rate": counts["false_positive"] / n if n else 0,
            "per_report_type": dict(per_report_type),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--predictions",
        default="experiments/fbk_reproduction/full25/predictions.jsonl",
    )
    ap.add_argument(
        "--out",
        default="experiments/fbk_reproduction/full25/per_variable.json",
    )
    args = ap.parse_args()

    agg = aggregate(Path(args.predictions))
    Path(args.out).write_text(json.dumps(agg, indent=2))

    # Print summary
    print(f"\nWrote: {args.out}\n")
    print(f"{'variable':<28} {'N':>3} {'Correct':>7} {'Extract':>7} "
          f"{'Abstain':>7} {'FP':>5} {'mat':>4} {'mis':>4} {'fp':>4} "
          f"{'fn':>4} {'be':>4}")
    print("-" * 95)
    for var, r in sorted(agg.items(), key=lambda kv: -kv[1]["correct_rate"]):
        print(f"{var:<28} {r['n']:>3} "
              f"{r['correct_rate']*100:>6.1f}% "
              f"{r['extract_rate']*100:>6.1f}% "
              f"{r['abstain_rate']*100:>6.1f}% "
              f"{r['fp_rate']*100:>4.1f}% "
              f"{r['match']:>4} {r['mismatch']:>4} "
              f"{r['false_positive']:>4} {r['false_negative']:>4} "
              f"{r['both_empty']:>4}")


if __name__ == "__main__":
    main()
