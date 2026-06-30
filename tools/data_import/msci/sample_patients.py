#!/usr/bin/env python3
"""Pick N patients at random from a Path-A CSV and emit the subset.

Preserves the exact CSV format (semicolon-delimited, double-quoted fields) so
the output is a drop-in replacement for /api/upload/csv.

Usage:
  python sample_patients.py \
    --in out/MSCI/fewshots_msci.csv \
    --out out/MSCI/fewshots_msci_sample.csv \
    --patients 8 \
    --seed 42
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="input", required=True)
    ap.add_argument("--out", dest="output", required=True)
    ap.add_argument("--patients", type=int, required=True, help="Number of patients to sample")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Group rows by p_id
    by_patient: dict[str, list[dict]] = defaultdict(list)
    fieldnames: list[str] = []
    with open(in_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            by_patient[row["p_id"]].append(row)

    if args.patients > len(by_patient):
        print(
            f"ERROR: --patients={args.patients} exceeds total patients={len(by_patient)}",
            file=sys.stderr,
        )
        return 1

    rng = random.Random(args.seed)
    chosen_ids = sorted(rng.sample(list(by_patient.keys()), args.patients))

    chosen_rows = []
    for pid in chosen_ids:
        chosen_rows.extend(by_patient[pid])

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter=";",
            quoting=csv.QUOTE_ALL,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in chosen_rows:
            writer.writerow(row)

    # Stats
    report_types = defaultdict(int)
    for row in chosen_rows:
        report_types[row["report_type"]] += 1
    print(
        f"Sampled {len(chosen_ids)} patients → {len(chosen_rows)} notes.\n"
        f"Wrote: {out_path}\n"
        f"Patients: {chosen_ids}\n"
        f"Report types in sample:"
    )
    for rt, n in sorted(report_types.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {rt}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
