"""Read a session JSON, return a metrics dict keyed by prompt_type.

The aggregator NEVER reads `note_original_text` or `note_text`. It only accesses
per-annotation `evaluation_result` (which carries match_type, similarity,
expected/predicted annotation values) and the top-level note_id / report_type
keys. This is the first half of the privacy contract; the sampler is the other half.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Recognized match_type values (from backend/services/evaluation_service.py)
KNOWN_MATCH_TYPES = {"match", "mismatch", "false_positive", "false_negative", "both_empty"}

# Histogram threshold: only emit predicted_value_histogram for prompts whose
# non-empty predictions average ≤ this many chars. Keeps free-text out.
SHORT_VALUE_LEN_THRESHOLD = 30


def _strip_center_suffix(prompt_type: str, center_lower: str) -> str:
    """Drop trailing `-<center>` suffix from a prompt_type slug for display."""
    suffix = f"-{center_lower}"
    if prompt_type.endswith(suffix):
        return prompt_type[: -len(suffix)]
    # Also strip the legacy `-int` suffix used by INT-SARC
    if prompt_type.endswith("-int"):
        return prompt_type[:-4]
    return prompt_type


def _empty_counts() -> dict[str, int]:
    return {mt: 0 for mt in KNOWN_MATCH_TYPES} | {"other": 0}


def _empty_per_prompt() -> dict[str, Any]:
    return {
        "total": 0,
        "counts": _empty_counts(),
        "similarity_sum": 0.0,
        "similarity_n": 0,
        "field_filled": Counter(),     # field_name -> filled count
        "field_matched": Counter(),    # field_name -> matched count
        "by_report_type": defaultdict(_empty_per_report_type),
        "predicted_lengths": [],       # for short-value detection
        "predicted_value_counter": Counter(),  # all non-empty predicted values
    }


def _empty_per_report_type() -> dict[str, int]:
    return {"total": 0, "counts": _empty_counts()}


def aggregate(session: dict, center: str) -> dict:
    """Build the metrics dict from a loaded session.

    Raises ValueError on conditions the CLI should treat as fatal.
    """
    if not isinstance(session, dict):
        raise ValueError("Session JSON root is not an object")
    if session.get("evaluation_mode") != "evaluation":
        raise ValueError(
            f"Session evaluation_mode is {session.get('evaluation_mode')!r}, "
            f"expected 'evaluation'. This session may not have been uploaded "
            f"with gold annotations."
        )

    center_lower = center.lower()
    annotations_field = session.get("annotations")

    # Build a flat iterable of (note_id, report_type, ann_dict) tuples regardless
    # of which storage shape the session uses:
    #   - List of annotation dicts (synthetic fixtures used in tests)
    #   - Dict keyed by note_id, values = dict[prompt_type, annotation_dict]
    #     (real shape persisted by /annotate/sequential and /annotate/process)
    note_index = {n["note_id"]: n for n in session.get("notes", [])}
    flat_anns: list[tuple[str | None, str | None, dict]] = []
    if isinstance(annotations_field, list):
        for ann in annotations_field:
            flat_anns.append((ann.get("note_id"), ann.get("report_type"), ann))
    elif isinstance(annotations_field, dict):
        for note_id, prompt_map in annotations_field.items():
            if not isinstance(prompt_map, dict):
                continue
            note_meta = note_index.get(str(note_id), {})
            report_type = note_meta.get("report_type")
            for prompt_type, ann in prompt_map.items():
                if not isinstance(ann, dict):
                    continue
                # The per-prompt annotation dict in the real shape doesn't carry
                # note_id or prompt_type; we inject them so downstream code is
                # shape-agnostic.
                ann_view = dict(ann)
                ann_view.setdefault("note_id", note_id)
                ann_view.setdefault("prompt_type", prompt_type)
                flat_anns.append((str(note_id), report_type, ann_view))

    by_prompt_raw: dict[str, dict] = defaultdict(_empty_per_prompt)
    notes_seen: set[str] = set()
    skipped = 0
    total_with_eval = 0

    for note_id, report_type, ann in flat_anns:
        eval_result = ann.get("evaluation_result")
        if not eval_result or not isinstance(eval_result, dict):
            skipped += 1
            continue

        total_with_eval += 1
        prompt_type_raw = ann.get("prompt_type") or ""
        prompt_type = _strip_center_suffix(prompt_type_raw, center_lower)
        report_type = report_type or "(unknown)"
        if note_id is not None:
            notes_seen.add(str(note_id))

        match_type = eval_result.get("match_type")
        bucket_key = match_type if match_type in KNOWN_MATCH_TYPES else "other"

        p = by_prompt_raw[prompt_type]
        p["total"] += 1
        p["counts"][bucket_key] += 1

        sim = eval_result.get("similarity_score")
        if isinstance(sim, (int, float)):
            p["similarity_sum"] += float(sim)
            p["similarity_n"] += 1

        # Field-level: tally filled (non-empty expected) and matched within those.
        for fr in eval_result.get("field_results") or []:
            fname = fr.get("field_name")
            if not fname:
                continue
            expected = (fr.get("expected") or "").strip()
            if expected:
                p["field_filled"][fname] += 1
                if fr.get("match"):
                    p["field_matched"][fname] += 1

        # Cross-tab by report_type
        rt = p["by_report_type"][report_type]
        rt["total"] += 1
        rt["counts"][bucket_key] += 1

        # Predicted-value lengths + counter (used by histogram + default-bias)
        predicted = (eval_result.get("predicted_annotation") or "").strip()
        if predicted:
            p["predicted_lengths"].append(len(predicted))
            p["predicted_value_counter"][predicted] += 1

    # Build the public output dict
    by_prompt_out: dict[str, dict] = {}
    for prompt, p in by_prompt_raw.items():
        total = p["total"]
        counts = p["counts"]
        # match_rate: strict extraction-only (only when both gold and predicted
        # have content and agree).
        # correctness_rate: matches + correct abstentions (both_empty), which is
        # the metric the original NLP_variables_analysis.pdf used for "% correct"
        # and which the backend's evaluation engine already treats as
        # overall_match=True. Bucketing uses correctness_rate.
        match_rate = counts["match"] / total if total else 0.0
        correctness_rate = (counts["match"] + counts["both_empty"]) / total if total else 0.0
        fp_rate = counts["false_positive"] / total if total else 0.0
        fn_rate = counts["false_negative"] / total if total else 0.0
        abstention_rate = counts["both_empty"] / total if total else 0.0
        avg_sim = p["similarity_sum"] / p["similarity_n"] if p["similarity_n"] else 0.0

        # Average predicted length, for the short-value gate
        if p["predicted_lengths"]:
            avg_pred_len = sum(p["predicted_lengths"]) / len(p["predicted_lengths"])
        else:
            avg_pred_len = 0.0

        # Histogram only for enumeration-style outputs
        histogram = None
        if p["predicted_value_counter"] and avg_pred_len <= SHORT_VALUE_LEN_THRESHOLD:
            histogram = dict(p["predicted_value_counter"].most_common())

        # Field metrics
        field_metrics = []
        for fname in p["field_filled"]:
            filled = p["field_filled"][fname]
            matched = p["field_matched"][fname]
            field_metrics.append({
                "field": fname,
                "filled": filled,
                "matched": matched,
                "match_rate": matched / filled if filled else 0.0,
            })

        # Per-report-type breakdown
        by_rt_out = {}
        for rt_name, rt_data in p["by_report_type"].items():
            t = rt_data["total"]
            c = rt_data["counts"]
            by_rt_out[rt_name] = {
                "total": t,
                "counts": dict(c),
                "match_rate": c["match"] / t if t else 0.0,
                "correctness_rate": (c["match"] + c["both_empty"]) / t if t else 0.0,
                "fp_rate": c["false_positive"] / t if t else 0.0,
            }

        by_prompt_out[prompt] = {
            "total": total,
            "counts": dict(counts),
            "match_rate": match_rate,
            "correctness_rate": correctness_rate,
            "fp_rate": fp_rate,
            "fn_rate": fn_rate,
            "abstention_rate": abstention_rate,
            "avg_similarity": avg_sim,
            "avg_predicted_length": avg_pred_len,
            "field_metrics": field_metrics,
            "by_report_type": by_rt_out,
            "predicted_value_histogram": histogram,
        }

    if total_with_eval == 0:
        raise ValueError(
            "No annotations with evaluation_result found. Did the batch "
            "annotation step finish? Skipped (no eval_result): " + str(skipped)
        )

    return {
        "session_id": session.get("session_id", "(unknown)"),
        "center": center,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totals": {
            "annotations": total_with_eval,
            "notes": len(notes_seen),
            "prompt_types": len(by_prompt_out),
            "skipped": skipped,
        },
        "by_prompt": by_prompt_out,
    }


def load_session(path: Path) -> dict:
    """Read the session JSON. Raises FileNotFoundError / ValueError on bad input."""
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Session file is not valid JSON: {e}") from e
