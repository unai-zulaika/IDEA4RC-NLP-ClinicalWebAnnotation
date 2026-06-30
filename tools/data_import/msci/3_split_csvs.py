#!/usr/bin/env python3
"""Step 3: read enriched JSONL + mapping CSV, emit the three end-product CSVs.

- fewshots_<center>.csv      : Path A schema, one row per note with ≥1 usable item.
- fewshots_<center>_faiss.csv: Path B schema, sample 30-60 per prompt_type.
- upload_<center>.csv        : Path A schema, one row per note with zero usable items.

"Usable" = data_item whose node_id has a non-blank prompt_type in mapping.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    format_date,
    load_mapping,
    render_annotations_field,
    stderr,
    write_faiss_csv,
    write_path_a_csv,
)


def _iter_jsonl(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _build_path_a_row(note: dict, annotations: str) -> dict:
    return {
        "text": note["note_original_text"],
        "date": format_date(note.get("note_date", "")),
        "p_id": note.get("pid", ""),
        "note_id": note.get("internal_note_id", ""),
        "report_type": note.get("note_name", ""),
        "annotations": annotations,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--enriched", required=True, help="Path to enriched JSONL from step 2")
    ap.add_argument("--mapping", required=True, help="Path to reviewed mapping CSV from step 1")
    ap.add_argument("--center", required=True, help="Center key (e.g. MSCI)")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--min-per-prompt", type=int, default=30)
    ap.add_argument("--max-per-prompt", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--faiss-strict",
        action="store_true",
        help=(
            "Require data_items to be fully complete (no leftover [...] "
            "placeholders) to enter the FAISS pool. Default: relaxed — "
            "any usable data_item is eligible. The relaxed mode is what "
            "fills few-shots for prompts whose source export has no "
            "fully-complete entries (necrosis_in_biopsy, tumorbiopsytype, "
            "tumordiameter in MSCI's case)."
        ),
    )
    args = ap.parse_args(argv)

    enriched_path = Path(args.enriched)
    mapping_path = Path(args.mapping)
    out_dir = Path(args.out_dir)

    if not enriched_path.exists():
        stderr(f"ERROR: enriched file not found: {enriched_path}")
        return 1
    if not mapping_path.exists():
        stderr(
            f"ERROR: mapping file not found: {mapping_path}\n"
            f"Hint: run 1_build_mapping.py first, then review the CSV."
        )
        return 1

    mapping = load_mapping(mapping_path)
    center_lower = args.center.lower()

    fewshots_path = out_dir / f"fewshots_{center_lower}.csv"
    faiss_path = out_dir / f"fewshots_{center_lower}_faiss.csv"
    upload_path = out_dir / f"upload_{center_lower}.csv"

    # Pass 1: scan, classify each note, accumulate FAISS pools per prompt_type.
    fewshots_rows: list[dict] = []
    upload_rows: list[dict] = []
    faiss_pool: dict[str, list[tuple[dict, dict]]] = defaultdict(list)  # prompt_type -> [(note, data_item), ...]

    for note in _iter_jsonl(enriched_path):
        data_items = note.get("data_items", [])
        # Items are dicts at this point (we loaded from JSONL)
        usable_items = [it for it in data_items if mapping.get(it.get("node_id")) ]

        if usable_items:
            annotations_str = render_annotations_field(
                _DictItemAdapter.wrap_list(usable_items),
                mapping,
                center_lower,
            )
            fewshots_rows.append(_build_path_a_row(note, annotations_str))
        else:
            upload_rows.append(_build_path_a_row(note, ""))

        # FAISS pool: by default any usable item is eligible (relaxed mode).
        # With --faiss-strict, restrict to is_complete items.
        for it in usable_items:
            if args.faiss_strict and not it.get("is_complete"):
                continue
            prompt_type = mapping[it["node_id"]]
            faiss_pool[prompt_type].append((note, it))

    # Pass 2: sample for FAISS
    rng = random.Random(args.seed)
    faiss_rows: list[dict] = []
    per_prompt_counts: dict[str, int] = {}
    below_min: dict[str, int] = {}
    for prompt_type, candidates in sorted(faiss_pool.items()):
        n = len(candidates)
        if n <= args.max_per_prompt:
            selected = list(candidates)
            if n < args.min_per_prompt:
                below_min[prompt_type] = n
        else:
            selected = rng.sample(candidates, args.max_per_prompt)
        per_prompt_counts[prompt_type] = len(selected)
        for note, item in selected:
            faiss_rows.append({
                "prompt_type": prompt_type,
                "note_text": note["note_original_text"],
                "annotation": item["text_content"].strip(),
            })

    # Write outputs
    n_fewshots = write_path_a_csv(fewshots_path, fewshots_rows)
    n_faiss = write_faiss_csv(faiss_path, faiss_rows)
    n_upload = write_path_a_csv(upload_path, upload_rows)

    # Summary
    if per_prompt_counts:
        avg = sum(per_prompt_counts.values()) / len(per_prompt_counts)
    else:
        avg = 0
    below_min_str = ""
    if below_min:
        details = ", ".join(f"{p}={c}" for p, c in sorted(below_min.items()))
        below_min_str = f"\n  below-min ({args.min_per_prompt}): {details}"
    stderr(
        f"{fewshots_path.name}: {n_fewshots} rows\n"
        f"{faiss_path.name}: {n_faiss} rows across {len(per_prompt_counts)} prompt_types"
        f"\n  avg {avg:.1f}/prompt_type"
        f"{below_min_str}\n"
        f"{upload_path.name}: {n_upload} rows"
    )
    return 0


class _DictItemAdapter:
    """Bridge: render_annotations_field expects DataItem dataclasses with attribute access.
    The JSONL we load gives us dicts. Wrap them lightweight so the helper works for both.
    """
    __slots__ = ("_d",)

    def __init__(self, d: dict):
        self._d = d

    def __getattr__(self, name: str):
        return self._d.get(name, "")

    @classmethod
    def wrap_list(cls, items: list[dict]) -> list:
        return [cls(it) for it in items]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
