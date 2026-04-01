#!/usr/bin/env python3
"""
End-to-end evaluation of history note splitting.

Processes a subset of history notes with and without splitting enabled,
comparing the results. Requires a running vLLM server.

Usage:
    cd backend
    .venv/bin/python scripts/run_splitting_evaluation.py [--session-id ID] [--max-notes N] [--prompt-types TYPE1,TYPE2]
"""

import asyncio
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.history_detector import HistoryNoteDetector
from lib.note_splitter import split_history_note, clear_split_cache, build_sub_note
from lib.result_aggregator import aggregate_results
from services.vllm_client import get_vllm_client
from models.annotation_models import NoteSplitResult


SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
RESULTS_DIR = Path(__file__).parent.parent / "evaluation_results"
RESULTS_DIR.mkdir(exist_ok=True)


def load_session(session_id: str) -> dict:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        # Try partial match
        for p in SESSIONS_DIR.glob("*.json"):
            if session_id in p.stem:
                path = p
                break
    with open(path) as f:
        return json.load(f)


def find_history_notes(session: dict, detector: HistoryNoteDetector) -> list[dict]:
    """Return notes detected as history, sorted by confidence (highest first)."""
    results = []
    for note in session.get("notes", []):
        text = note.get("text", "")
        rt = note.get("report_type", "")
        details = detector.get_detection_details(text, rt)
        if details["is_history"]:
            results.append({
                "note": note,
                "detection": details,
            })
    results.sort(key=lambda x: x["detection"]["confidence"], reverse=True)
    return results


def get_repeatable_prompt_types(session: dict) -> list[str]:
    """Get prompt types for repeatable entities from session's prompt list."""
    from routes.annotate import _ensure_prompts_loaded, _PROMPTS, _load_entity_cardinality

    _ensure_prompts_loaded()
    cardinality = _load_entity_cardinality()

    repeatable = []
    for pt_name in session.get("prompt_types", []):
        prompt_info = _PROMPTS.get(pt_name, {})
        entity_mapping = prompt_info.get("entity_mapping", {})
        entity_type = entity_mapping.get("entity_type", "")
        base_entity = entity_type.split(".")[0] if entity_type else ""
        if base_entity and cardinality.get(base_entity, 1) == 0:
            repeatable.append(pt_name)
    return repeatable


async def process_note_without_splitting(
    note_text: str,
    prompt_type: str,
    csv_date: Optional[str],
    vllm_client: Any,
    session_data: dict,
    note_id: str,
) -> dict:
    """Process a note without splitting (baseline)."""
    from routes.annotate import _process_single_prompt, _ensure_prompts_loaded
    _ensure_prompts_loaded()

    result = await _process_single_prompt(
        prompt_type=prompt_type,
        note_text=note_text,
        csv_date=csv_date,
        vllm_client=vllm_client,
        use_structured=True,
        request_use_fewshots=False,
        request_fewshot_k=0,
        evaluation_mode="validation",
        session_data=session_data,
        note_id=note_id,
        fast_mode=False,
    )
    return {
        "annotation_text": result.annotation_text,
        "values": [v.value for v in result.values],
        "status": result.status,
        "reasoning": result.reasoning[:200] if result.reasoning else None,
    }


async def process_note_with_splitting(
    note_text: str,
    prompt_type: str,
    csv_date: Optional[str],
    vllm_client: Any,
    session_data: dict,
    note_id: str,
    split_result: NoteSplitResult,
) -> dict:
    """Process a note with splitting (experimental)."""
    from routes.annotate import _process_single_prompt, _ensure_prompts_loaded
    _ensure_prompts_loaded()

    sub_results = []
    sub_details = []
    for i, event in enumerate(split_result.events):
        sub_note = build_sub_note(split_result.shared_context, event)
        result = await _process_single_prompt(
            prompt_type=prompt_type,
            note_text=sub_note,
            csv_date=csv_date,
            vllm_client=vllm_client,
            use_structured=True,
            request_use_fewshots=False,
            request_fewshot_k=0,
            evaluation_mode="validation",
            session_data=session_data,
            note_id=note_id,
            fast_mode=False,
        )
        sub_results.append(result)
        sub_details.append({
            "event_index": i,
            "event_type": event.event_type,
            "event_date": event.event_date,
            "annotation_text": result.annotation_text,
            "status": result.status,
        })

    aggregated = aggregate_results(
        results=sub_results,
        prompt_type=prompt_type,
        total_events=len(split_result.events),
    )

    return {
        "annotation_text": aggregated.annotation_text,
        "values": [v.value for v in aggregated.values],
        "num_values": len(aggregated.values),
        "status": aggregated.status,
        "multi_value_info": aggregated.multi_value_info,
        "sub_note_details": sub_details,
        "reasoning": aggregated.reasoning[:300] if aggregated.reasoning else None,
    }


async def run_evaluation(args):
    print("=" * 70)
    print("HISTORY NOTE SPLITTING — END-TO-END EVALUATION")
    print("=" * 70)

    # Load session
    session = load_session(args.session_id)
    center = session.get("center", "unknown")
    print(f"\nSession: {session.get('session_id', '?')[:8]}... ({center})")
    print(f"Notes: {len(session.get('notes', []))}")

    # Check vLLM
    vllm_client = get_vllm_client()
    if not vllm_client.is_available():
        print("ERROR: vLLM server not available")
        return

    status = vllm_client.get_status()
    print(f"vLLM: {status.get('status', '?')} — model: {status.get('model', '?')}")

    # Detect history notes
    detector = HistoryNoteDetector()
    history_items = find_history_notes(session, detector)
    print(f"History notes detected: {len(history_items)}")

    if not history_items:
        print("No history notes found. Nothing to evaluate.")
        return

    # Limit notes
    history_items = history_items[: args.max_notes]
    print(f"Evaluating: {len(history_items)} notes")

    # Get prompt types
    if args.prompt_types:
        prompt_types = args.prompt_types.split(",")
    else:
        prompt_types = get_repeatable_prompt_types(session)
        if len(prompt_types) > 4:
            # Pick a representative subset
            preferred = ["surgerytype", "chemotherapy_start", "radiotherapy_start", "recurrencetype"]
            prompt_types = [pt for pt in prompt_types if any(p in pt for p in preferred)] or prompt_types[:4]

    print(f"Prompt types: {prompt_types}")
    print()

    # Run evaluation
    all_results = []
    for idx, item in enumerate(history_items):
        note = item["note"]
        detection = item["detection"]
        note_id = note["note_id"]
        note_text = note.get("text", "")
        csv_date = note.get("date")

        print(f"--- Note {idx + 1}/{len(history_items)} ---")
        print(f"  ID: {note_id[:60]}...")
        print(f"  Detection: confidence={detection['confidence']:.2f}, "
              f"dates={detection['date_count']}, markers={detection['event_marker_count']}, "
              f"treatments={detection['treatment_types_found']}")

        # Split the note
        clear_split_cache()
        t0 = time.time()
        split_result = await split_history_note(
            note_text=note_text,
            vllm_client=vllm_client,
            session_id=session.get("session_id", "eval"),
            note_id=note_id,
        )
        split_time = time.time() - t0

        print(f"  Split: {len(split_result.events)} events in {split_time:.1f}s "
              f"(was_split={split_result.was_split})")
        if split_result.was_split:
            for i, ev in enumerate(split_result.events):
                print(f"    Event {i}: type={ev.event_type}, date={ev.event_date}, "
                      f"text={ev.event_text[:80]}...")

        note_results = {
            "note_id": note_id[:60],
            "note_length": len(note_text),
            "detection": detection,
            "split_time_s": round(split_time, 2),
            "num_events": len(split_result.events),
            "was_split": split_result.was_split,
            "shared_context": split_result.shared_context[:200] if split_result.shared_context else "",
            "prompts": {},
        }

        for pt in prompt_types:
            print(f"\n  Processing '{pt}'...")
            try:
                # Baseline (no splitting)
                t0 = time.time()
                baseline = await process_note_without_splitting(
                    note_text, pt, csv_date, vllm_client, session, note_id
                )
                baseline_time = time.time() - t0

                # With splitting
                t0 = time.time()
                if split_result.was_split:
                    split_out = await process_note_with_splitting(
                        note_text, pt, csv_date, vllm_client, session, note_id, split_result
                    )
                else:
                    split_out = baseline.copy()
                    split_out["num_values"] = 1
                    split_out["multi_value_info"] = None
                    split_out["sub_note_details"] = []
                split_time_pt = time.time() - t0

                # Check if gold annotation exists
                gold = None
                ann = session.get("annotations", {}).get(note_id, {}).get(pt, {})
                if ann:
                    er = ann.get("evaluation_result", {})
                    if er:
                        gold = er.get("expected_annotation", "")

                comparison = {
                    "baseline": baseline,
                    "baseline_time_s": round(baseline_time, 2),
                    "with_splitting": split_out,
                    "splitting_time_s": round(split_time_pt, 2),
                    "gold_annotation": gold,
                    "improvement": {
                        "baseline_values": len(baseline.get("values", [])),
                        "splitting_values": split_out.get("num_values", len(split_out.get("values", []))),
                        "more_values": (
                            split_out.get("num_values", 1) > len(baseline.get("values", []))
                        ),
                    },
                }

                note_results["prompts"][pt] = comparison

                # Print summary
                bv = len(baseline.get("values", []))
                sv = split_out.get("num_values", 1)
                print(f"    Baseline: {bv} value(s) in {baseline_time:.1f}s — {baseline['annotation_text'][:80]}")
                print(f"    Split:    {sv} value(s) in {split_time_pt:.1f}s")
                if sv > 1:
                    for v in split_out.get("values", []):
                        print(f"      → {v[:80]}")
                else:
                    print(f"      → {split_out['annotation_text'][:80]}")
                if gold:
                    print(f"    Gold:     {gold[:80]}")

            except Exception as e:
                print(f"    ERROR: {e}")
                note_results["prompts"][pt] = {"error": str(e)}

        all_results.append(note_results)
        print()

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_baseline_values = 0
    total_split_values = 0
    more_values_count = 0
    total_comparisons = 0

    for nr in all_results:
        for pt, comp in nr["prompts"].items():
            if "error" in comp:
                continue
            total_comparisons += 1
            bv = comp["improvement"]["baseline_values"]
            sv = comp["improvement"]["splitting_values"]
            total_baseline_values += bv
            total_split_values += sv
            if comp["improvement"]["more_values"]:
                more_values_count += 1

    print(f"Total comparisons: {total_comparisons}")
    print(f"Baseline total values: {total_baseline_values}")
    print(f"Splitting total values: {total_split_values}")
    print(f"Cases with more values from splitting: {more_values_count}/{total_comparisons}")

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS_DIR / f"splitting_comparison_{timestamp}.json"
    with open(output_path, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "session_id": session.get("session_id"),
            "center": center,
            "prompt_types": prompt_types,
            "notes_evaluated": len(all_results),
            "summary": {
                "total_comparisons": total_comparisons,
                "baseline_total_values": total_baseline_values,
                "splitting_total_values": total_split_values,
                "more_values_count": more_values_count,
            },
            "results": all_results,
        }, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate history note splitting")
    parser.add_argument("--session-id", default="04779998",
                        help="Session ID (partial match OK)")
    parser.add_argument("--max-notes", type=int, default=3,
                        help="Max history notes to evaluate")
    parser.add_argument("--prompt-types", default=None,
                        help="Comma-separated prompt types (default: auto-select repeatable)")
    args = parser.parse_args()

    asyncio.run(run_evaluation(args))


if __name__ == "__main__":
    main()
