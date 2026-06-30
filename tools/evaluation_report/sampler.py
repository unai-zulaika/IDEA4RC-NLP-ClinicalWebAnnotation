"""Pick representative error cases per prompt_type for the report.

PRIVACY GATE: this module is the only place that reads per-annotation source
content beyond the `evaluation_result` dict. It DOES read `expected_annotation`
and `predicted_annotation` (annotation values, agreed shareable). It does NOT
read `note_original_text` or `note_text`. The result samples never carry a
`note_text` field — only `note_id` (an identifier) and `report_type`.
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Iterable

# Priority order: spec says mismatch most informative, both_empty least.
MATCH_TYPE_PRIORITY = ("mismatch", "false_positive", "false_negative", "both_empty")


def sample_errors(
    session: dict,
    metrics: dict,
    center: str,
    samples_per_prompt: int = 5,
    seed: int = 42,
) -> None:
    """Mutate metrics in-place: for each prompt_type, attach a `samples` list.

    Each sample is a dict with: note_id, report_type, match_type,
    expected (string), predicted (string). No note text fields.
    """
    rng = random.Random(seed)
    center_lower = center.lower()

    # Strip-suffix helper has to match aggregator behavior
    def _strip(slug: str) -> str:
        suf = f"-{center_lower}"
        if slug.endswith(suf):
            return slug[: -len(suf)]
        if slug.endswith("-int"):
            return slug[:-4]
        return slug

    # Build a shape-agnostic flat iterable. Real sessions store annotations as
    # dict[note_id, dict[prompt_type, ann]]; test fixtures use a flat list.
    note_index = {n["note_id"]: n for n in session.get("notes", [])}
    annotations_field = session.get("annotations")
    flat: list[tuple[str | None, str | None, str | None, dict]] = []
    if isinstance(annotations_field, list):
        for ann in annotations_field:
            flat.append((
                ann.get("note_id"), ann.get("prompt_type"),
                ann.get("report_type"), ann,
            ))
    elif isinstance(annotations_field, dict):
        for note_id, prompt_map in annotations_field.items():
            if not isinstance(prompt_map, dict):
                continue
            rt = (note_index.get(str(note_id)) or {}).get("report_type")
            for prompt_type, ann in prompt_map.items():
                if not isinstance(ann, dict):
                    continue
                flat.append((str(note_id), prompt_type, rt, ann))

    # Group error candidates by (prompt_name, match_type)
    candidates: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for note_id, prompt_type_raw, report_type, ann in flat:
        eval_result = ann.get("evaluation_result")
        if not eval_result or not isinstance(eval_result, dict):
            continue
        match_type = eval_result.get("match_type")
        # Skip clean matches — we only sample errors. We DO include both_empty
        # because it can surface "the prompt never fires" patterns, but with
        # the lowest priority.
        if match_type == "match":
            continue
        if match_type not in MATCH_TYPE_PRIORITY:
            continue

        prompt_name = _strip(prompt_type_raw or "")
        candidate = {
            "note_id": str(note_id or ""),
            "report_type": report_type or "(unknown)",
            "match_type": match_type,
            "expected": (eval_result.get("expected_annotation") or "").strip(),
            "predicted": (eval_result.get("predicted_annotation") or "").strip(),
        }
        candidates[(prompt_name, match_type)].append(candidate)

    # Per prompt: walk MATCH_TYPE_PRIORITY, take samples until we hit the cap.
    for prompt_name in metrics["by_prompt"]:
        chosen: list[dict] = []
        remaining = samples_per_prompt
        for mt in MATCH_TYPE_PRIORITY:
            if remaining <= 0:
                break
            pool = candidates.get((prompt_name, mt), [])
            if not pool:
                continue
            if len(pool) <= remaining:
                # Take all; seed-sort for determinism
                picked = sorted(pool, key=lambda c: c["note_id"])
            else:
                # Random sample, deterministic per seed
                picked = rng.sample(pool, remaining)
                picked.sort(key=lambda c: c["note_id"])
            chosen.extend(picked)
            remaining -= len(picked)
        metrics["by_prompt"][prompt_name]["samples"] = chosen
