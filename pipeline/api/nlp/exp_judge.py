#!/usr/bin/env python3
"""
Auto-judge an experiment run's predictions and compute metrics.

  python exp_judge.py --run-id <run_id>
  python exp_judge.py --all          # judge every run that has predictions.csv

Writes, into experiments/results/<run_id>/:
  verdicts.csv   — per (note, prompt) row verdict (C/W/D) from auto_judge
  metrics.json   — accuracy, per-prompt accuracy, hallucination rate,
                   translation (source-language leakage) rate
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from auto_judge import judge_pair, row_verdict
from exp_registry import RESULTS_ROOT, all_configs

# Italian/Polish/Swedish function words that signal source-language leakage in
# what should be an English structured output. Tuned per center as needed.
SOURCE_LANG_MARKERS = {
    "INT-SARC": [r"\bistolog", r"\btipo istolog", r"\bvescica\b", r"\butero\b",
                 r"\bpaziente\b", r"\bmaligno\b", r"\bsinistr", r"\bdestr",
                 r"\bindifferenziat", r"\bcellule\b"],
}


def _is_abstention(text: str) -> bool:
    t = (text or "").strip().lower()
    return (t == "" or "not applicable" in t or "unknown" in t
            or "not available" in t or "not specified" in t
            or "[no output]" in t or t == "none" or t == "nessun"
            or "no information" in t)


def _has_value(text: str) -> bool:
    """Pred carries a committed value (not abstention, not pure placeholder)."""
    if _is_abstention(text):
        return False
    stripped = re.sub(r"\[[^\]]*\]", "", text or "").strip().rstrip(".:,; ").strip()
    return len(stripped) > 0


def _is_loop_hallucination(text: str) -> bool:
    """Detect repetition-loop / broken-generation hallucinations.

    Triggers if any ~30-char window in the prediction repeats >4 times — the
    classic 'The note mentions X. The note mentions Y. The note mentions X. ...'
    pattern produced when the model gets stuck in a loop. Cheap, no false
    positives on normal templated outputs which are well under 200 chars.
    """
    if not text or len(text) < 200:
        return False
    counts: dict[str, int] = {}
    for i in range(0, len(text) - 30, 5):
        window = text[i:i + 30]
        counts[window] = counts.get(window, 0) + 1
    return max(counts.values(), default=0) > 4


def judge_run(run_id: str) -> dict:
    rdir = RESULTS_ROOT / run_id
    preds = pd.read_csv(rdir / "predictions.csv")
    center = run_id.split("__")[0]

    rows = []
    for idx, r in preds.reset_index(drop=True).iterrows():
        gold = str(r["gold"]) if pd.notna(r["gold"]) else ""
        pred = str(r["pred"]) if pd.notna(r["pred"]) else ""
        ptype = r["prompt_type"]
        has_gold = gold.strip() != ""
        sub = judge_pair(gold, pred, ptype, note_id=str(r.get("note_id", "")), idx=int(idx))
        verdict = row_verdict(sub) if has_gold else ""   # only score gold-present rows
        rows.append({
            "idx": int(idx), "note_id": r.get("note_id", ""), "prompt_type": ptype,
            "report_type": r.get("report_type", ""), "gold": gold, "pred": pred,
            "has_gold": has_gold, "verdict": verdict,
        })
    vdf = pd.DataFrame(rows)
    vdf.to_csv(rdir / "verdicts.csv", index=False)

    # --- Accuracy (gold-present rows only) ---
    judged = vdf[(vdf["has_gold"]) & (vdf["verdict"].isin(["C", "W"]))]
    n_correct = int((judged["verdict"] == "C").sum())
    n_judged = int(len(judged))
    accuracy = round(n_correct / n_judged * 100, 1) if n_judged else None

    per_prompt = {}
    for pt, grp in judged.groupby("prompt_type"):
        c = int((grp["verdict"] == "C").sum())
        n = int(len(grp))
        per_prompt[pt] = {"correct": c, "n": n, "pct": round(c / n * 100, 1)}

    # --- Hallucination (NEW definition): % of all predictions that exhibit a
    #     repetition loop / broken generation. Ground-truth-y: detected from the
    #     prediction text alone, zero false positives on normal templated outputs.
    #     The previous proxy (committed on gold-absent rows) conflated invention
    #     with annotator omission; that count is now reported as "uncertain"
    #     (informational, not penalized). ---
    n_total = int(len(vdf))
    n_halluc = int(vdf["pred"].apply(_is_loop_hallucination).sum())
    halluc_rate = round(n_halluc / n_total * 100, 1) if n_total else None

    # --- Uncertain: gold-absent rows where the model committed. Not labeled bad
    #     because annotators didn't always fill every variable, so some of these
    #     are legitimately the model finding something the annotator skipped.
    #     Report the count so reviewers know how much of the prediction set is
    #     unverifiable, but do not score it as hallucination. ---
    gold_absent = vdf[~vdf["has_gold"]]
    n_uncertain = int(gold_absent["pred"].apply(_has_value).sum())
    n_gold_absent = int(len(gold_absent))

    # --- Translation leakage: % of committed predictions containing source-lang markers ---
    markers = SOURCE_LANG_MARKERS.get(center, [])
    committed = vdf[vdf["pred"].apply(_has_value)]
    n_committed = int(len(committed))
    if markers and n_committed:
        pat = re.compile("|".join(markers), re.I)
        n_leak = int(committed["pred"].apply(lambda s: bool(pat.search(str(s)))).sum())
        leak_rate = round(n_leak / n_committed * 100, 1)
    else:
        n_leak, leak_rate = 0, None

    metrics = {
        "run_id": run_id,
        "accuracy_pct": accuracy,
        "n_correct": n_correct, "n_judged": n_judged,
        "hallucination_rate_pct": halluc_rate,
        "n_hallucinated": n_halluc, "n_total": n_total,
        "n_uncertain": n_uncertain, "n_gold_absent": n_gold_absent,
        "translation_leak_rate_pct": leak_rate,
        "n_leaked": n_leak, "n_committed": n_committed,
        "per_prompt": per_prompt,
    }
    (rdir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"[judge] {run_id}: acc={accuracy}% ({n_correct}/{n_judged})  "
          f"loop-halluc={halluc_rate}% ({n_halluc}/{n_total})  "
          f"uncertain={n_uncertain}/{n_gold_absent}  leak={leak_rate}%")
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.run_id:
        judge_run(args.run_id)
    elif args.all:
        for rdir in sorted(RESULTS_ROOT.iterdir()):
            if (rdir / "predictions.csv").exists():
                judge_run(rdir.name)
    else:
        raise SystemExit("specify --run-id or --all")


if __name__ == "__main__":
    main()
