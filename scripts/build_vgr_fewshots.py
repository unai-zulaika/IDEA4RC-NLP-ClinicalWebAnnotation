#!/usr/bin/env python3
"""
build_vgr_fewshots.py
=====================

Turn a VGR annotation export (the four ``*_export_*.json`` files produced by the
annotation tool) into a *few-shot CSV* that can be uploaded directly on the
platform's **Upload page → "Upload Few-Shots"** section for the **VGR** center.

The output CSV has exactly the three columns the platform expects::

    prompt_type,note_text,annotation

  * ``prompt_type`` — the *base* VGR prompt key (e.g. ``tumorsite``,
    ``histological``, ``surgerytype``).  Do **not** add a center suffix: the
    ``POST /api/upload/fewshots?center=VGR`` endpoint appends ``-vgr`` itself,
    and retrieval strips it back off when matching, so the bare key is correct.
  * ``note_text`` — the clinical note the model should read (the original,
    un-annotated note text).
  * ``annotation`` — the structured annotation sentence expected for that note
    and prompt type (the "answer").

How it works
------------
For each annotation it finds, the script pairs it with its note's *clean*
clinical text and decides which VGR prompt key it belongs to.  Annotations are
collected from two complementary sources and then de-duplicated, so the script
works whether or not the cross-file ``internal_note_id`` values line up:

  1. ``data_items_export*.json`` — the authoritative list of annotations
     (``text_content``), joined to its note via ``internal_note_id``.
  2. ``annotated_notes_export*.json`` — each note's ``note_text`` already has the
     English annotation sentences interleaved with the original (Swedish) text;
     those lines are parsed out and paired with ``note_original_text``.

The note text used in the CSV is always the *original* note (``note_original_text``,
or ``note_text`` with the annotation lines stripped) so the answer is never
leaked into the example input.

Usage
-----
    # Point it at the folder containing the four export files:
    python build_vgr_fewshots.py --input-dir texts/VGR_sample -o vgr_fewshots.csv

    # Or pass files explicitly:
    python build_vgr_fewshots.py \
        --notes        annotated_notes_export_7_*.json \
        --data-items   data_items_export_7_*.json \
        -o vgr_fewshots.csv

Only the Python standard library is required (no pandas / numpy).
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# VGR annotation -> prompt-key classifier
# ---------------------------------------------------------------------------
# Ordered list of (vgr_prompt_key, regex).  The FIRST pattern that matches an
# annotation sentence wins, so more specific rules come before generic ones
# (e.g. "...ended..." before "...started...").  Patterns are matched
# case-insensitively against the cleaned annotation text.
#
# These keys mirror the VGR prompt keys in
# backend/data/prompts/prompts.json -> "VGR" (and backend/data/fast_prompts/VGR).
# Edit this table if your export uses different annotation phrasings or if you
# add/rename VGR prompts.
VGR_PATTERNS: List[Tuple[str, str]] = [
    # --- grading (specific before generic) ---
    ("surgical-specimen-grading", r"surgical specimen grading"),
    ("biopsygrading",             r"biopsy grading"),

    # --- histology / site / depth / diameter / rupture ---
    ("histological",              r"^histological type"),
    ("tumorsite",                 r"^tumou?r site"),
    ("tumordepth",                r"^tumou?r depth"),
    ("tumordiameter",             r"^tumou?r longest diameter"),
    ("tumorrupture",              r"^tumou?r (did not rupture|ruptured|rupture)"),

    # --- staging ---
    ("stage_at_diagnosis",        r"stage at diagnosis|unknown stage"),

    # --- surgery ---
    ("surgerymargins",            r"^margins after surgery"),
    ("reexcision",                r"re-?excision|radicali[sz]ation"),
    ("surgerytype",               r"^(primary surgery|surgery) was (performed|not performed)"),

    # --- chemotherapy / radiotherapy (END before START) ---
    ("chemotherapy_end",          r"chemotherapy ended"),
    ("chemotherapy_start",        r"chemotherapy .*started"),
    ("radiotherapy_end",          r"radiotherapy .*(ended on|in total of)"),
    ("radiotherapy_start",        r"radiotherapy .*started"),

    # --- biopsy type ---
    ("tumorbiopsytype",           r"biopsy has been performed|baseline/primary tumou?r"),

    # --- recurrence / progression / patient status ---
    ("recur_or_prog",             r"^there was .*(progression|recurrence)|no progression/recurrence"),
    ("recurrencetype",            r"^type of recurrence"),
    ("patient-status",            r"status of the patient"),

    # --- previous / other treatment, other cancers ---
    ("previous_cancer_treatment", r"^(no )?previous cancer treatment"),
    ("other-systemic-therapy",    r"other systemic therapy"),
    ("occurrence_cancer",         r"occurrence of other cancer"
                                  r"|no previous or concurrent cancers"
                                  r"|no information about occurrence"),
]

_COMPILED_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (key, re.compile(pat, re.IGNORECASE)) for key, pat in VGR_PATTERNS
]

# An annotation that still contains an unresolved template placeholder such as
# "[select ICD-O-3 code]" or "[provide date]" makes a poor few-shot example.
_PLACEHOLDER_RE = re.compile(r"\[(select|provide|put|please select)[^\]]*\]", re.IGNORECASE)
# A bare CN_ID:<uuid> trailer that the tool appends to note_text.
_CN_ID_RE = re.compile(r"\s*CN_ID\s*:\s*\S+\s*$", re.IGNORECASE)


def classify_annotation(annotation: str) -> Optional[str]:
    """Return the VGR prompt key for an annotation sentence, or None if unknown."""
    text = annotation.strip()
    for key, pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            return key
    return None


def clean_annotation(text: str) -> str:
    """Normalise an annotation sentence: drop a leading 'Annotation:' label,
    collapse trailing whitespace/newlines."""
    text = text.strip()
    text = re.sub(r"^annotation\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def strip_annotation_lines(note_text: str) -> str:
    """Best-effort recovery of the original clinical text from a note_text that
    has annotation sentences interleaved: drop the CN_ID trailer and any line
    that classifies as a known annotation."""
    body = _CN_ID_RE.sub("", note_text)
    kept = [
        line for line in body.split("\n")
        if line.strip() and classify_annotation(line) is None
    ]
    return "\n".join(kept).strip()


# ---------------------------------------------------------------------------
# Loading the export files
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> object:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_one(pattern: Optional[str], input_dir: Optional[Path],
                 default_glob: str, label: str) -> Optional[Path]:
    """Resolve a single export file from an explicit path/glob or by globbing
    the input directory. Returns None if not found (callers decide if required)."""
    candidates: List[str] = []
    if pattern:
        candidates = sorted(glob.glob(pattern))
        if not candidates:
            sys.exit(f"[ERROR] No file matches --{label} pattern: {pattern}")
    elif input_dir is not None:
        candidates = sorted(glob.glob(str(input_dir / default_glob)))
    if not candidates:
        return None
    if len(candidates) > 1:
        print(f"[WARN] Multiple {label} files match; using the first:\n"
              f"       " + "\n       ".join(candidates))
    return Path(candidates[0])


def build_note_index(notes: List[dict]) -> Dict[str, str]:
    """Map internal_note_id -> clean clinical note text."""
    index: Dict[str, str] = {}
    for note in notes:
        nid = str(note.get("internal_note_id", "")).strip()
        if not nid:
            continue
        original = (note.get("note_original_text") or "").strip()
        if not original:
            original = strip_annotation_lines(note.get("note_text", ""))
        if original:
            index[nid] = original
    return index


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------
def collect_examples(
    notes: List[dict],
    data_items: Optional[List[dict]],
    drop_placeholders: bool,
) -> Tuple[List[Tuple[str, str, str]], Dict[str, int], List[str]]:
    """Return (rows, stats, unclassified_samples).

    rows are (prompt_type, note_text, annotation) tuples, de-duplicated.
    """
    note_index = build_note_index(notes)
    seen: set = set()
    rows: List[Tuple[str, str, str]] = []
    stats = {
        "from_data_items": 0,
        "from_inline": 0,
        "unresolved_join": 0,
        "unclassified": 0,
        "dropped_placeholder": 0,
    }
    unclassified: List[str] = []

    def add(prompt_type: str, note_text: str, annotation: str, source: str) -> None:
        key = (prompt_type, note_text, annotation)
        if key in seen:
            return
        seen.add(key)
        rows.append((prompt_type, note_text, annotation))
        stats[source] += 1

    def consider(annotation_raw: str, note_text: str, source: str) -> None:
        annotation = clean_annotation(annotation_raw)
        if not annotation or not note_text:
            return
        prompt_type = classify_annotation(annotation)
        if prompt_type is None:
            stats["unclassified"] += 1
            if len(unclassified) < 40:
                unclassified.append(annotation)
            return
        if drop_placeholders and _PLACEHOLDER_RE.search(annotation):
            stats["dropped_placeholder"] += 1
            return
        add(prompt_type, note_text, annotation, source)

    # Source 1: data_items_export joined to its note by internal_note_id.
    if data_items:
        for item in data_items:
            nid = str(item.get("internal_note_id", "")).strip()
            note_text = note_index.get(nid)
            if not note_text:
                stats["unresolved_join"] += 1
                continue
            consider(item.get("text_content", ""), note_text, "from_data_items")

    # Source 2: annotation sentences interleaved inside each note_text.
    for note in notes:
        original = (note.get("note_original_text") or "").strip()
        if not original:
            original = strip_annotation_lines(note.get("note_text", ""))
        if not original:
            continue
        body = _CN_ID_RE.sub("", note.get("note_text", ""))
        for line in body.split("\n"):
            consider(line, original, "from_inline")

    return rows, stats, unclassified


def write_csv(rows: List[Tuple[str, str, str]], out_path: Path, delimiter: str) -> None:
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["prompt_type", "note_text", "annotation"])
        for prompt_type, note_text, annotation in rows:
            writer.writerow([prompt_type, note_text, annotation])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a VGR few-shot CSV from an annotation export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input-dir", type=Path,
                   help="Folder containing the *_export_*.json files. The script "
                        "auto-detects the notes / data_items files inside it.")
    p.add_argument("--notes",
                   help="Path or glob for the annotated_notes export JSON "
                        "(overrides --input-dir auto-detection).")
    p.add_argument("--data-items",
                   help="Path or glob for the data_items export JSON "
                        "(the data_items_def file is NOT needed).")
    p.add_argument("-o", "--output", type=Path, default=Path("vgr_fewshots.csv"),
                   help="Output CSV path (default: vgr_fewshots.csv).")
    p.add_argument("--delimiter", default=",",
                   help="CSV delimiter (default ','; the platform also accepts ';').")
    p.add_argument("--max-per-type", type=int, default=0,
                   help="Cap the number of examples per prompt type (0 = no cap).")
    p.add_argument("--keep-placeholders", action="store_true",
                   help="Keep annotations that still contain template placeholders "
                        "like '[provide date]' (dropped by default).")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if not args.input_dir and not args.notes:
        sys.exit("[ERROR] Provide --input-dir, or at least --notes. See --help.")

    notes_path = _resolve_one(
        args.notes, args.input_dir, "*annotated_notes_export*.json", "notes")
    if notes_path is None:
        sys.exit("[ERROR] Could not find an annotated_notes export file. "
                 "Pass it explicitly with --notes.")
    data_items_path = _resolve_one(
        args.data_items, args.input_dir, "*data_items_export*.json", "data-items")

    print(f"[INFO] Notes file      : {notes_path}")
    print(f"[INFO] Data-items file : {data_items_path or '(none — using inline annotations only)'}")

    notes = _load_json(notes_path)
    if not isinstance(notes, list):
        sys.exit("[ERROR] Notes file is not a JSON list.")
    data_items = _load_json(data_items_path) if data_items_path else None
    if data_items is not None and not isinstance(data_items, list):
        sys.exit("[ERROR] Data-items file is not a JSON list.")

    rows, stats, unclassified = collect_examples(
        notes, data_items, drop_placeholders=not args.keep_placeholders)

    # Optional per-type cap.
    if args.max_per_type > 0:
        capped: List[Tuple[str, str, str]] = []
        per_type_count: Dict[str, int] = {}
        for row in rows:
            pt = row[0]
            if per_type_count.get(pt, 0) >= args.max_per_type:
                continue
            per_type_count[pt] = per_type_count.get(pt, 0) + 1
            capped.append(row)
        rows = capped

    write_csv(rows, args.output, args.delimiter)

    # --- Report ---
    by_type: Dict[str, int] = {}
    for pt, _, _ in rows:
        by_type[pt] = by_type.get(pt, 0) + 1

    print(f"\n[INFO] Wrote {len(rows)} few-shot rows -> {args.output}")
    print(f"[INFO] Prompt types covered: {len(by_type)}")
    for pt in sorted(by_type):
        print(f"         {pt:<28} {by_type[pt]}")
    print("\n[INFO] Source breakdown:")
    print(f"         from data_items (joined) : {stats['from_data_items']}")
    print(f"         from inline note_text    : {stats['from_inline']}")
    print(f"         unresolved join (skipped): {stats['unresolved_join']}")
    print(f"         dropped placeholders     : {stats['dropped_placeholder']}")
    print(f"         unclassified (skipped)   : {stats['unclassified']}")
    if unclassified:
        print("\n[INFO] Examples of unclassified annotations (extend VGR_PATTERNS to capture):")
        for sample in unclassified[:15]:
            print(f"         - {sample[:100]}")

    print("\n[NEXT] Upload on the platform: Upload page -> 'Upload Few-Shots', "
          "choose center 'VGR', and select this CSV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
