#!/usr/bin/env python3
"""Step 2: join notes + data_items + codebook into per-note JSONL.

Each output line is one note with its data_items embedded (and an is_complete
flag per item). Step 3 reads this + the reviewed mapping to emit the final CSVs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ENGLISH_DICT_ID,
    check_completeness,
    load_codebook,
    load_items,
    load_notes,
    resolve_glob,
    stderr,
)


def _conflicts(items_by_key: dict[tuple[str, int], list]) -> list[tuple[str, int]]:
    """Return (internal_note_id, sentence_id) pairs that appear with conflicting text_content."""
    bad = []
    for key, items in items_by_key.items():
        if len(items) <= 1:
            continue
        texts = {it.text_content for it in items}
        if len(texts) > 1:
            bad.append(key)
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--notes", required=True, help="Path or glob to annotated_notes_*.json")
    ap.add_argument("--items", required=True, help="Path or glob to data_items_*.json")
    ap.add_argument("--codebook", required=True, help="Path or glob to data_items_def_*.json")
    ap.add_argument("--out", required=True, help="Output JSONL path")
    args = ap.parse_args(argv)

    try:
        notes_path = resolve_glob(args.notes)
        items_path = resolve_glob(args.items)
        codebook_path = resolve_glob(args.codebook)
    except (FileNotFoundError, ValueError) as e:
        stderr(f"ERROR: {e}")
        return 1

    notes = load_notes(notes_path)
    items = load_items(items_path)
    codebook = load_codebook(codebook_path)

    if not any(k[0] == ENGLISH_DICT_ID for k in codebook):
        stderr(f"ERROR: codebook has zero dict_id={ENGLISH_DICT_ID} entries — wrong file?")
        return 1

    # Sanity: detect same (note_id, sentence_id) with conflicting text_content
    items_by_key: dict[tuple[str, int], list] = defaultdict(list)
    for it in items:
        if it.sentence_id is not None:
            items_by_key[(it.internal_note_id, it.sentence_id)].append(it)
    conflicts = _conflicts(items_by_key)
    if conflicts:
        stderr(
            f"ERROR: {len(conflicts)} (internal_note_id, sentence_id) pairs have "
            f"conflicting text_content. Examples: {conflicts[:3]}"
        )
        return 1

    # Drop notes with empty text up-front
    notes_without_text = [nid for nid, n in notes.items() if not n.note_original_text.strip()]
    for nid in notes_without_text:
        del notes[nid]

    # Bucket items by note. Orphans (no matching note) are tracked, then dropped.
    items_by_note: dict[str, list] = defaultdict(list)
    dropped_orphan_items = 0
    for it in items:
        if it.internal_note_id not in notes:
            dropped_orphan_items += 1
            continue
        items_by_note[it.internal_note_id].append(it)

    # Compute completeness for every retained item
    reason_counts: Counter = Counter()
    complete_count = 0
    for note_items in items_by_note.values():
        for it in note_items:
            cb = codebook.get((it.dict_id, it.node_id))
            it.node_sentence = cb.node_sentence if cb else ""
            ok, reason = check_completeness(it, codebook)
            it.is_complete = ok
            it.incomplete_reason = reason
            if ok:
                complete_count += 1
            else:
                reason_counts[reason or "other"] += 1

    # Emit JSONL
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    notes_with_items = 0
    notes_without_items = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for nid, note in notes.items():
            note_items = items_by_note.get(nid, [])
            if note_items:
                notes_with_items += 1
            else:
                notes_without_items += 1
            record = {
                "internal_note_id": note.internal_note_id,
                "pid": note.pid,
                "note_original_text": note.note_original_text,
                "note_name": note.note_name,
                "note_date": note.note_date,
                "data_items": [asdict(it) for it in note_items],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    total_items = sum(len(v) for v in items_by_note.values())
    reasons_str = ", ".join(f"{r}={c}" for r, c in sorted(reason_counts.items()))
    stderr(
        f"{len(notes) + len(notes_without_text)} notes scanned "
        f"(dropped {len(notes_without_text)} with empty text)\n"
        f"  → {notes_with_items} have ≥1 data_item\n"
        f"  → {notes_without_items} have zero data_items\n"
        f"{total_items} data_items kept "
        f"({dropped_orphan_items} orphans dropped)\n"
        f"  → {complete_count} complete\n"
        f"  → {total_items - complete_count} incomplete ({reasons_str})\n"
        f"Output: {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
