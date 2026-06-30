"""Build per-variable train/test splits from the FBK MSCI CSV.

FBK's reproduction protocol (slides 27 / 31 / 35 / 38):
1. Pull all annotation rows for a variable.
2. Deduplicate by (note_id, annotation_text) — same annotation repeated on
   multiple sentences of the same note counts once. (This is what FBK's
   "Duplicates" column captures; their "Effective" total matches roughly with
   our post-dedupe count on each variable.) We do NOT dedupe across notes —
   e.g. multiple patients can each have "Patient's gender male." legitimately.
3. Split 80/20: 20% becomes the few-shot pool, 80% the test set.
4. The number of RAG examples per test instance equals the few-shot pool size,
   capped at 30 (their convention for large categories).

This script writes a JSONL per variable to splits/<variable>_<seed>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

VARIABLE_PREFIXES = {
    "biopsy_mitotic_count": ("Biopsy mitotic count:",),
    "necrosis_in_biopsy": ("Necrosis in biopsy",),
    "necrosis_in_surgical": ("Necrosis in surgical",),
    "patient_weight_height": ("Patient's weight",),
}


@dataclass
class Sample:
    note_id: str
    pid: str
    note_name: str
    note_date: str
    note_text: str
    annotation: str
    highlight: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    df = df.fillna("")
    return df


def filter_variable(df: pd.DataFrame, prefixes: tuple[str, ...]) -> list[Sample]:
    """Pull rows whose annotation column starts with any of the variable prefixes."""
    mask = df["annotation"].str.lstrip().str.startswith(prefixes)
    sub = df[mask]
    samples: list[Sample] = []
    seen_pair = set()
    for _, row in sub.iterrows():
        annot = row["annotation"].strip()
        note_id = row["internal_note_id"].strip()
        key = (note_id, annot)
        if key in seen_pair:
            continue
        seen_pair.add(key)
        # note_original_text is sometimes "None" string or empty — fall back.
        note_text = row.get("note_original_text", "").strip()
        if not note_text or note_text == "None":
            note_text = row.get("note_text", "").strip()
        samples.append(
            Sample(
                note_id=note_id,
                pid=row.get("pid", "").strip(),
                note_name=row.get("note_name", "").strip(),
                note_date=row.get("note_date", "").strip(),
                note_text=note_text,
                annotation=annot,
                highlight=row.get("text", "").strip(),
            )
        )
    return samples


def split_80_20(samples: list[Sample], seed: int) -> tuple[list[Sample], list[Sample]]:
    """20% few-shot pool, 80% test set."""
    rng = random.Random(seed)
    idx = list(range(len(samples)))
    rng.shuffle(idx)
    n_pool = max(1, round(len(samples) * 0.2))
    pool_idx = set(idx[:n_pool])
    pool = [samples[i] for i in range(len(samples)) if i in pool_idx]
    test = [samples[i] for i in range(len(samples)) if i not in pool_idx]
    return pool, test


def build(csv_path: Path, out_dir: Path, seed: int) -> dict[str, dict]:
    df = load_csv(csv_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    for var_name, prefixes in VARIABLE_PREFIXES.items():
        samples = filter_variable(df, prefixes)
        pool, test = split_80_20(samples, seed)
        path = out_dir / f"{var_name}_seed{seed}.jsonl"
        with path.open("w") as f:
            for s in pool:
                f.write(json.dumps({"split": "pool", **s.to_dict()}) + "\n")
            for s in test:
                f.write(json.dumps({"split": "test", **s.to_dict()}) + "\n")
        summary[var_name] = {
            "effective_total": len(samples),
            "pool": len(pool),
            "test": len(test),
            "rag_k": min(len(pool), 30),
            "path": str(path),
        }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        default="FBK_MSCI/MSCI_Data_25_patients.csv",
        help="Path to FBK MSCI consolidated CSV.",
    )
    ap.add_argument(
        "--out-dir",
        default="experiments/fbk_reproduction/splits",
        help="Where to write per-variable JSONL files.",
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    summary = build(Path(args.csv), Path(args.out_dir), args.seed)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
