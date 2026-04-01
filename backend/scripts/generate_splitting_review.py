#!/usr/bin/env python3
"""
Generate a human-readable Markdown report from splitting evaluation results.

Reads the JSON output from run_splitting_evaluation.py and produces a
structured review document for manual quality assessment.

Usage:
    cd backend
    .venv/bin/python scripts/generate_splitting_review.py [--input FILE]

    If --input is not provided, uses the most recent file in evaluation_results/.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "evaluation_results"


def find_latest_result() -> Path:
    """Find the most recent evaluation result file."""
    files = sorted(RESULTS_DIR.glob("splitting_comparison_*.json"), reverse=True)
    if not files:
        print("No evaluation results found in evaluation_results/")
        sys.exit(1)
    return files[0]


def generate_report(data: dict) -> str:
    """Generate Markdown report from evaluation data."""
    lines = []

    # Header
    lines.append("# History Note Splitting — Evaluation Review")
    lines.append("")
    lines.append(f"**Date:** {data.get('timestamp', 'unknown')}")
    lines.append(f"**Session:** {data.get('session_id', '?')[:12]}... ({data.get('center', '?')})")
    lines.append(f"**Notes evaluated:** {data.get('notes_evaluated', 0)}")
    lines.append(f"**Prompt types:** {', '.join(data.get('prompt_types', []))}")
    lines.append("")

    # Summary
    summary = data.get("summary", {})
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total comparisons | {summary.get('total_comparisons', 0)} |")
    lines.append(f"| Baseline total values | {summary.get('baseline_total_values', 0)} |")
    lines.append(f"| Splitting total values | {summary.get('splitting_total_values', 0)} |")
    lines.append(f"| Cases with more values | {summary.get('more_values_count', 0)} |")
    if summary.get('total_comparisons', 0) > 0:
        pct = 100 * summary.get('more_values_count', 0) / summary['total_comparisons']
        lines.append(f"| Improvement rate | {pct:.0f}% |")
    lines.append("")

    # Per-note details
    lines.append("## Detailed Results")
    lines.append("")

    for i, result in enumerate(data.get("results", [])):
        lines.append(f"### Note {i + 1}: `{result.get('note_id', '?')}`")
        lines.append("")

        detection = result.get("detection", {})
        lines.append(f"**Detection:** confidence={detection.get('confidence', 0):.2f}, "
                      f"dates={detection.get('date_count', 0)}, "
                      f"markers={detection.get('event_marker_count', 0)}, "
                      f"treatments={detection.get('treatment_types_found', [])}")
        lines.append("")

        lines.append(f"**Split result:** {result.get('num_events', 0)} events "
                      f"(split_time={result.get('split_time_s', 0)}s, "
                      f"was_split={result.get('was_split', False)})")
        lines.append("")

        if result.get("shared_context"):
            lines.append(f"**Shared context:** {result['shared_context'][:200]}")
            lines.append("")

        # Per-prompt comparison
        prompts = result.get("prompts", {})
        if prompts:
            lines.append("#### Prompt Comparisons")
            lines.append("")

        for pt, comp in prompts.items():
            if "error" in comp:
                lines.append(f"**{pt}:** ERROR — {comp['error']}")
                lines.append("")
                continue

            baseline = comp.get("baseline", {})
            split_out = comp.get("with_splitting", {})
            improvement = comp.get("improvement", {})
            gold = comp.get("gold_annotation")

            bv = improvement.get("baseline_values", 0)
            sv = improvement.get("splitting_values", 0)
            better = "**+**" if sv > bv else ("=" if sv == bv else "-")

            lines.append(f"**{pt}** [{better}]")
            lines.append("")

            # Baseline
            lines.append(f"- **Baseline** ({bv} value, {comp.get('baseline_time_s', 0)}s):")
            lines.append(f"  - `{baseline.get('annotation_text', 'N/A')[:120]}`")

            # Split
            lines.append(f"- **With splitting** ({sv} values, {comp.get('splitting_time_s', 0)}s):")
            for j, v in enumerate(split_out.get("values", [])):
                lines.append(f"  - [{j+1}] `{v[:120]}`")

            # Sub-note details
            sub_details = split_out.get("sub_note_details", [])
            if sub_details:
                lines.append(f"- **Sub-note extractions:**")
                for sd in sub_details:
                    status_icon = "ok" if sd.get("status") == "success" else "err"
                    lines.append(f"  - Event {sd['event_index']} ({sd.get('event_type', '?')}, "
                                  f"date={sd.get('event_date', '?')}): "
                                  f"[{status_icon}] `{sd.get('annotation_text', 'N/A')[:100]}`")

            # Gold
            if gold and "[NO EXPECTED" not in gold:
                lines.append(f"- **Gold annotation:** `{gold[:120]}`")

            lines.append("")

        lines.append("---")
        lines.append("")

    # Scoring rubric
    lines.append("## Scoring Rubric")
    lines.append("")
    lines.append("For each note, assess:")
    lines.append("")
    lines.append("| Criterion | Score (1-5) | Notes |")
    lines.append("|-----------|-------------|-------|")
    lines.append("| **Split quality**: Were events correctly identified and separated? | | |")
    lines.append("| **Completeness**: Were all events in the note captured? | | |")
    lines.append("| **Extraction quality**: Were values correctly extracted from sub-notes? | | |")
    lines.append("| **Deduplication**: Were true duplicates removed without losing unique values? | | |")
    lines.append("| **Non-regression**: Did splitting NOT hurt any prompt type that worked in baseline? | | |")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate splitting review report")
    parser.add_argument("--input", default=None,
                        help="Path to evaluation JSON (default: latest)")
    parser.add_argument("--output", default=None,
                        help="Output path (default: evaluation_results/splitting_review_TIMESTAMP.md)")
    args = parser.parse_args()

    # Load data
    input_path = Path(args.input) if args.input else find_latest_result()
    print(f"Reading: {input_path}")
    with open(input_path) as f:
        data = json.load(f)

    # Generate report
    report = generate_report(data)

    # Save
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = RESULTS_DIR / f"splitting_review_{timestamp}.md"

    with open(output_path, "w") as f:
        f.write(report)
    print(f"Report saved to: {output_path}")


if __name__ == "__main__":
    main()
