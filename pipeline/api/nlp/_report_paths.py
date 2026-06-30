"""
Centralised paths for report artifacts. Change `CENTER` (or set the
NLP_REPORT_CENTER env var) to retarget every script at a different center
(e.g. INT-HNC, MSCI, VGR) without per-script edits.

Outputs land in:
    docs/reports/<CENTER>/artifacts/   — judge verdicts, comparison CSVs
    docs/reports/<CENTER>/plots/       — PNGs
    docs/reports/<CENTER>/             — markdown sources + rendered PDFs
"""
from __future__ import annotations
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

CENTER = os.environ.get("NLP_REPORT_CENTER", "INT-SARC")

REPORT_DIR = REPO_ROOT / "docs" / "reports" / CENTER
ARTIFACTS_DIR = REPORT_DIR / "artifacts"
PLOTS_DIR = REPORT_DIR / "plots"

# Ensure folders exist (cheap, idempotent)
for _p in (ARTIFACTS_DIR, PLOTS_DIR):
    _p.mkdir(parents=True, exist_ok=True)
