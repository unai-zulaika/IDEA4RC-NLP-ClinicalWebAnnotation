#!/usr/bin/env python3
"""Generate a per-center evaluation report from a completed session JSON.

Reads `backend/sessions/<id>.json` (after batch annotation in evaluation mode),
emits a Markdown draft shaped like docs/NLP_variables_analysis.pdf.

The tool never reads `note_original_text` / `note_text`. Aggregate metrics,
short-enumeration value histograms, and redacted-text error samples are the
only things that reach the output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aggregator import aggregate, load_session  # noqa: E402
from classifier import ClassifierConfig, classify_all  # noqa: E402
from renderer import DEFAULT_TEMPLATE_PATH, render_markdown, write_markdown  # noqa: E402
from sampler import sample_errors  # noqa: E402


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--session", required=True, help="Path to session JSON")
    ap.add_argument("--center", required=True, help="Center name (e.g. MSCI)")
    ap.add_argument("--out", required=True, help="Output Markdown path")
    ap.add_argument("--samples-per-prompt", type=int, default=5)
    ap.add_argument("--reliable-threshold", type=float, default=0.70)
    ap.add_argument("--usable-threshold", type=float, default=0.40)
    ap.add_argument("--fp-cap", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--template",
        default=str(DEFAULT_TEMPLATE_PATH),
        help=f"Jinja2 template path (default: {DEFAULT_TEMPLATE_PATH})",
    )
    args = ap.parse_args(argv)

    session_path = Path(args.session)
    if not session_path.exists():
        _stderr(f"ERROR: session file not found: {session_path}")
        return 1

    template_path = Path(args.template)
    if not template_path.exists():
        _stderr(f"ERROR: template not found: {template_path}")
        return 1

    cfg = ClassifierConfig(
        reliable_threshold=args.reliable_threshold,
        usable_threshold=args.usable_threshold,
        fp_cap=args.fp_cap,
    )
    try:
        cfg.validate()
    except ValueError as e:
        _stderr(f"ERROR: {e}")
        return 1

    try:
        session = load_session(session_path)
        metrics = aggregate(session, center=args.center)
    except ValueError as e:
        _stderr(f"ERROR: {e}")
        return 1
    except FileNotFoundError as e:
        _stderr(f"ERROR: {e}")
        return 1

    classify_all(metrics, cfg)
    sample_errors(
        session,
        metrics,
        center=args.center,
        samples_per_prompt=args.samples_per_prompt,
        seed=args.seed,
    )

    out_md = render_markdown(metrics, template_path=template_path)
    write_markdown(Path(args.out), out_md)

    # End-of-run summary to stderr
    bc = metrics["bucket_counts"]
    t = metrics["totals"]
    _stderr(
        f"Wrote {args.out}\n"
        f"  Annotations: {t['annotations']} ({t['skipped']} skipped)\n"
        f"  Notes: {t['notes']}\n"
        f"  Prompt types: {t['prompt_types']}\n"
        f"    Reliable: {bc['reliable']}\n"
        f"    Usable:   {bc['usable']}\n"
        f"    Unreliable: {bc['unreliable']}\n"
        f"Convert to PDF: pandoc {args.out} -o {args.out.replace('.md', '.pdf')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
