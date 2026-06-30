#!/usr/bin/env python3
"""Note-level stratified sampler for evaluation.

Picks notes from a Path-A CSV such that, under a `report_type → [prompt_type, ...]`
mapping, each mapped prompt_type has at least `--target-n` applicable notes in
the sample. Uses a greedy set-cover: at each step picks the note that satisfies
the most under-supplied prompts.

Preserves the exact CSV format (semicolon, double-quoted) so the output is a
drop-in replacement for /api/upload/csv.

Usage:
  python sample_for_prompts.py \
    --in out/MSCI/fewshots_msci.csv \
    --mapping tools/data_import/msci/msci_report_type_mapping.json \
    --out out/MSCI/fewshots_msci_balanced.csv \
    --center MSCI \
    --target-n 12 \
    --seed 42
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="input", required=True)
    ap.add_argument("--mapping", required=True, help="report_type → [prompt_type, ...] JSON")
    ap.add_argument("--out", dest="output", required=True)
    ap.add_argument("--center", default="MSCI",
                    help="Center suffix for prompt_types in the mapping (e.g. MSCI → -msci)")
    ap.add_argument("--target-n", type=int, default=12,
                    help="Minimum applicable notes per prompt_type (default 12)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-notes", type=int, default=0,
                    help="Hard cap on total notes; 0 = no cap.")
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    out_path = Path(args.output)
    mapping_path = Path(args.mapping)

    # Load mapping (report_type → list of prompt_type-msci slugs)
    with open(mapping_path, "r", encoding="utf-8") as f:
        rt_to_prompts: dict[str, list[str]] = json.load(f)

    # Build inverse: prompt_type → list of report_types
    prompt_to_rts: dict[str, set[str]] = defaultdict(set)
    for rt, prompts in rt_to_prompts.items():
        for p in prompts:
            prompt_to_rts[p].add(rt)
    all_prompts = sorted(prompt_to_rts.keys())

    # Load all candidate notes
    fieldnames: list[str] = []
    notes_by_rt: dict[str, list[dict]] = defaultdict(list)
    all_notes: list[dict] = []
    with open(in_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            all_notes.append(row)
            notes_by_rt[row["report_type"]].append(row)

    # For each note, precompute which prompts it would contribute to (the
    # mapped prompts of its report_type).
    def prompts_for(note: dict) -> set[str]:
        return set(rt_to_prompts.get(note["report_type"], []))

    # Diagnostic: how many notes are available per prompt in the population?
    avail_per_prompt = {
        p: sum(len(notes_by_rt.get(rt, [])) for rt in rts)
        for p, rts in prompt_to_rts.items()
    }
    print("Population coverage:", file=sys.stderr)
    for p in sorted(avail_per_prompt, key=avail_per_prompt.get):
        flag = "  ⚠ below target" if avail_per_prompt[p] < args.target_n else ""
        print(f"  {avail_per_prompt[p]:>5}  {p}{flag}", file=sys.stderr)

    # Greedy selection
    rng = random.Random(args.seed)
    chosen_ids: set[str] = set()
    chosen_rows: list[dict] = []
    counts: Counter = Counter()  # prompt → number of selected notes serving it
    # Shuffle once for deterministic but unbiased tie-breaks
    pool = list(all_notes)
    rng.shuffle(pool)

    def under_target_count(note: dict) -> int:
        """How many under-target prompts this note would contribute to."""
        return sum(1 for p in prompts_for(note) if counts[p] < args.target_n)

    while True:
        if args.max_notes and len(chosen_ids) >= args.max_notes:
            print(f"⚠ Hit --max-notes={args.max_notes} before all prompts reached target.", file=sys.stderr)
            break
        # Stop if every reachable prompt is satisfied
        unsatisfied = [p for p in all_prompts if counts[p] < min(args.target_n, avail_per_prompt[p])]
        if not unsatisfied:
            break
        # Score each remaining candidate by how many under-target prompts it serves
        best = None
        best_score = 0
        for note in pool:
            if note["note_id"] in chosen_ids:
                continue
            score = under_target_count(note)
            if score > best_score:
                best, best_score = note, score
        if best is None or best_score == 0:
            # No remaining note contributes to any unsatisfied prompt
            print(f"⚠ Cannot satisfy all targets; unsatisfied: {unsatisfied}", file=sys.stderr)
            break
        chosen_ids.add(best["note_id"])
        chosen_rows.append(best)
        for p in prompts_for(best):
            counts[p] += 1

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, delimiter=";",
            quoting=csv.QUOTE_ALL, extrasaction="ignore",
        )
        writer.writeheader()
        for row in chosen_rows:
            writer.writerow(row)

    # Summary
    rt_summary = Counter(r["report_type"] for r in chosen_rows)
    patients_in_sample = {r["p_id"] for r in chosen_rows}
    print(f"\nWrote {out_path}", file=sys.stderr)
    print(f"  Notes selected: {len(chosen_rows)}", file=sys.stderr)
    print(f"  Distinct patients: {len(patients_in_sample)}", file=sys.stderr)
    print(f"  Per-prompt coverage (target N={args.target_n}):", file=sys.stderr)
    for p in sorted(all_prompts):
        n = counts[p]
        marker = "✓" if n >= args.target_n else ("●" if n > 0 else "✗")
        print(f"    {marker} {n:>3}  {p}", file=sys.stderr)
    print(f"  Per-report_type counts in sample:", file=sys.stderr)
    for rt, n in sorted(rt_summary.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>3}  {rt}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
