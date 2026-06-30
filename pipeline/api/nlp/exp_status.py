#!/usr/bin/env python3
"""
Progress dashboard for the experiment matrix.

  python exp_status.py            # full matrix + raw-sweep-per-model, with status
  python exp_status.py --model 4b # just what needs the 4b served

Status per run:
  [ ] not started      (no predictions.csv)
  [P] predictions only (predictions.csv, no metrics.json)
  [J] judged           (metrics.json present, shows accuracy)
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from exp_registry import (
    MODEL_SERVED, RESULTS_ROOT, all_configs, raw_sweep_configs,
    production_sweep_configs,
)


def _status(run_id: str) -> tuple[str, str]:
    rdir = RESULTS_ROOT / run_id
    if not (rdir / "predictions.csv").exists():
        return "[ ]", ""
    metrics = rdir / "metrics.json"
    if not metrics.exists():
        return "[P]", ""
    m = json.loads(metrics.read_text())
    acc = m.get("accuracy_pct")
    halluc = m.get("hallucination_rate_pct")
    return "[J]", f"acc={acc}%  halluc={halluc}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="only show configs needing this model served")
    args = ap.parse_args()

    # Build the full set of distinct configs: the matrix + the raw sweep per model.
    configs = {c.run_id(): c for c in all_configs()}
    for model in MODEL_SERVED:
        for c in raw_sweep_configs(model):
            configs[c.run_id()] = c
        for c in production_sweep_configs(model):
            configs[c.run_id()] = c

    by_model: dict[str, list] = defaultdict(list)
    for c in configs.values():
        if args.model and c.model != args.model:
            continue
        by_model[c.model].append(c)

    grand_total = grand_done = 0
    for model in sorted(by_model):
        rows = sorted(by_model[model], key=lambda c: c.run_id())
        done = 0
        print(f"\n### serve: {model}  ({MODEL_SERVED.get(model,'?')})  — {len(rows)} runs")
        for c in rows:
            mark, detail = _status(c.run_id())
            if mark == "[J]":
                done += 1
            print(f"  {mark} {c.run_id():70s} {detail}")
        print(f"  ---- {done}/{len(rows)} judged ----")
        grand_total += len(rows)
        grand_done += done

    print(f"\n=== TOTAL: {grand_done}/{grand_total} runs judged ===")
    print("Legend: [ ] not started   [P] predictions only   [J] judged")


if __name__ == "__main__":
    main()
