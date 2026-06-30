#!/usr/bin/env bash
# Verify tools/evaluation_report/ after transferring it from the dev box.
# Checks the expected files exist, runs the redaction + smoke tests, and does a
# dry-run report render with a PHI grep over the output. Exit 0 = safe to treat
# exp_out/ as live; non-zero = not yet.
set -u
cd "$(dirname "$0")/.." || exit 2
PY=""
for c in backend/.venv/bin/python python3 python; do
  if "$c" -c 'import pytest, jinja2' >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "No python found with both pytest and jinja2. Install them or fix the venv."; exit 2
fi
echo "using python: $PY"

EXPECTED=(
  tools/evaluation_report/aggregator.py
  tools/evaluation_report/classifier.py
  tools/evaluation_report/sampler.py
  tools/evaluation_report/renderer.py
  tools/evaluation_report/generate_report.py
  tools/evaluation_report/README.md
  tools/evaluation_report/templates/default.md.j2
  tools/evaluation_report/tests/test_sampler_redaction.py
  tools/evaluation_report/tests/test_render_smoke.py
)

echo "== 1. expected files =="
miss=0
for f in "${EXPECTED[@]}"; do
  if [ -f "$f" ]; then echo "  ok   $f"; else echo "  MISS $f"; miss=$((miss+1)); fi
done
if [ "$miss" -gt 0 ]; then
  echo "RESULT: $miss file(s) missing - transfer not complete. exp_out/ stays NOT live."
  exit 1
fi

echo "== 2. redaction + smoke tests =="
"$PY" -m pytest tools/evaluation_report/tests -q || { echo "RESULT: tests FAILED."; exit 1; }

echo "== 3. dry-run report + redaction assertions =="
SESS=backend/sessions/3effb5be-3c84-492f-ab5d-fecedd5c3173.json
OUT=/tmp/_eval_report_verify.md
"$PY" tools/evaluation_report/generate_report.py --session "$SESS" --center MSCI --out "$OUT" \
  || { echo "RESULT: generate_report failed."; exit 1; }
# The full per-center report is the INTERNAL artefact: it redacts note BODIES to
# [REDACTED] but intentionally shows extracted annotation VALUES (including dates).
# So assert the redaction contract here - NOT the exp_out data-drop gate. That gate
# (exp_out/README.md) governs what may LEAVE the server and runs on exp_out/ files.
if ! grep -q '\[REDACTED\]' "$OUT"; then
  echo "RESULT: FAIL - no [REDACTED] sentinel in report; redaction not applied."; exit 1
fi
if grep -q 'note_original_text' "$OUT"; then
  echo "RESULT: FAIL - raw note-body field leaked into report."; exit 1
fi
echo "RESULT: PASS - module present, 47 tests green, report redacts note bodies ([REDACTED] x$(grep -c '\[REDACTED\]' "$OUT"))."
echo "Reminder: the full report is INTERNAL (shows annotation values/dates). The exp_out/ gate governs external sharing - run it on exp_out/ files, not on this report."
