# Evaluation Report Generator

Turns a completed evaluation-mode session JSON into a Markdown draft report
shaped like `docs/NLP_variables_analysis.pdf`. Use after running
`POST /api/annotate/batch` on a session that was uploaded with gold annotations
populated (e.g. `out/MSCI/fewshots_msci.csv`).

## Privacy contract

The tool reads `note_original_text` / `note_text` from the session JSON only to
discard it. Note text never reaches the metrics dict, the sampler output, or
the rendered report.

**Visible in the report:**
- Aggregate counts and percentages per prompt_type.
- Short-enumeration predicted-value histograms (only when avg predicted length ≤ 30 chars).
- Sample error cases — note text replaced with `[REDACTED]`; the annotation
  values `expected` and `predicted` are visible.

**Hidden in the report:**
- `note_original_text` / `note_text` fields.

Two unit tests (`test_sampler_redaction.py`, `test_render_smoke.py`) inject a
sentinel string into the fixture's note text and assert it does not appear in
any module's output.

## Workflow

```
1. backend annotation pipeline
   └─ upload fewshots_msci.csv to /api/upload/csv → session created
   └─ POST /api/annotate/batch → session JSON populated with evaluation_result

2. generate the report
   └─ python tools/evaluation_report/generate_report.py
         --session backend/sessions/<id>.json
         --center MSCI
         --out report_msci.md

3. fill in the placeholders (qualitative narrative)
   └─ open report_msci.md, write "Observations" per prompt, plus Lessons learned,
      Production-vs-NLP comparison, Key takeaway. Optionally paste sections to
      Claude — redacted samples + value histograms + flags are safe to share.

4. convert to PDF
   └─ pandoc report_msci.md -o report_msci.pdf
```

## CLI

```bash
backend/.venv/bin/python tools/evaluation_report/generate_report.py \
  --session backend/sessions/<id>.json \
  --center MSCI \
  --out report_msci.md \
  --samples-per-prompt 5 \
  --reliable-threshold 0.70 \
  --usable-threshold 0.40 \
  --fp-cap 0.10 \
  --seed 42
```

Flags:

| Flag | Default | Meaning |
|------|---------|---------|
| `--session` | required | Path to session JSON. |
| `--center` | required | Center name (drops the `-<center>` suffix from prompt_type display). |
| `--out` | required | Output Markdown path. Overwrites without prompting. |
| `--samples-per-prompt` | 5 | Max error samples per prompt_type. |
| `--reliable-threshold` | 0.70 | Min match_rate for the Reliable bucket. |
| `--usable-threshold` | 0.40 | Min match_rate for the Usable bucket (below this → Unreliable). |
| `--fp-cap` | 0.10 | Max false_positive_rate allowed for the Reliable bucket. |
| `--seed` | 42 | Sample-selection seed for reproducibility. |
| `--template` | `templates/default.md.j2` | Jinja2 template file. |

## Bucketing rules

Evaluated in order; first match wins:

1. `total < 10` → **Unreliable** (low support).
2. `abstention_rate ≥ 0.80` → **Unreliable** (abstention trap).
3. `match_rate < --usable-threshold` → **Unreliable** (low match).
4. Default-bias detected (see below) → **Usable** (demotion).
5. `match_rate ≥ --reliable-threshold` AND `fp_rate ≤ --fp-cap` → **Reliable**.
6. Otherwise → **Usable**.

**Default-bias detection:** prompt has enumeration-style outputs (avg predicted
length ≤ 30 chars) AND at least 3 wrong predictions AND more than 60% of those
wrong predictions share the same predicted_annotation value. The minimum-3
requirement avoids spurious flags from a single bad case.

## Manual end-to-end check

1. After `/api/annotate/batch` finishes, locate the session JSON in
   `backend/sessions/<id>.json`.
2. Run the tool against it (CLI above).
3. Spot-check that `report_msci.md` contains all expected prompt_types.
4. Grep the file for any substring you can think of from your notes:
   ```
   grep -F "<suspected text>" report_msci.md
   ```
   Should return nothing.
5. `pandoc report_msci.md -o report_msci.pdf` to render.

## Tests

```bash
backend/.venv/bin/python -m pytest tools/evaluation_report/tests -v
```

All four test files run against a synthetic session at
`tests/fixtures/synthetic_session.json` (no real data). The fixture's
`note_original_text` fields contain the sentinel
`SENSITIVE_NOTE_TEXT_DO_NOT_LEAK`; the sampler and renderer tests assert it
does not appear in their output.

## Modules

| File | Purpose |
|------|---------|
| `aggregator.py` | Reads session JSON → per-prompt metrics. Strips note text by construction. |
| `classifier.py` | Buckets each prompt + auto-reason + flags. Pure function. |
| `sampler.py` | Picks error samples per prompt. Enforces the redaction contract (note_text never copied). |
| `renderer.py` | Jinja2 strict-undefined rendering. |
| `templates/default.md.j2` | Markdown template mirroring the NLP_variables_analysis.pdf structure. |
| `generate_report.py` | CLI entry point. |
