# Data Import Tools

Offline scripts that convert clinical-annotation-tool JSON exports from partner
centers into the CSV formats consumed by this project's FastAPI endpoints.

Currently only **MSCI** is implemented. The directory layout supports adding
sibling directories (`vgr/`, `int_sarc/`) that reuse the same pattern.

## MSCI

Source data lives in `texts/MSCI/` — four JSON files exported from the
annotation tool (annotated notes, codebook, annotation values, evidence
highlights). Outputs land in `out/MSCI/`.

### Pipeline

```
texts/MSCI/*.json
     │
     ▼ step 1 (once; you review/edit between steps)
  tools/data_import/msci/mapping_msci.csv
     │
     ▼ step 2
  out/MSCI/enriched_msci.jsonl
     │
     ▼ step 3
  out/MSCI/fewshots_msci.csv      ← evaluation upload (Path A schema)
  out/MSCI/fewshots_msci_faiss.csv ← FAISS retrieval upload (Path B schema)
  out/MSCI/upload_msci.csv        ← LLM annotation pool (Path A schema, no annotations)
```

### Step 1 — build the codebook → prompt_type mapping

```bash
backend/.venv/bin/python tools/data_import/msci/1_build_mapping.py \
  --codebook 'texts/MSCI/data_items_def_export_*.json' \
  --prompts backend/data/prompts/prompts.json \
  --center MSCI \
  --out tools/data_import/msci/mapping_msci.csv
```

Produces a CSV with one row per English-codebook entry (146 entries minus the
Polish ones). Each row has a `suggested_prompt_type` and `confidence` (high /
medium / none). Rows with `none` need manual review — open the CSV and fill in
the `suggested_prompt_type` column where possible, or leave it blank to skip
that codebook entry entirely.

The script refuses to overwrite an existing `mapping_msci.csv` (it contains
your manual edits). Pass `--force` to override.

### Step 2 — join records

```bash
backend/.venv/bin/python tools/data_import/msci/2_merge_records.py \
  --notes 'texts/MSCI/annotated_notes_export_*.json' \
  --items 'texts/MSCI/data_items_export_*.json' \
  --codebook 'texts/MSCI/data_items_def_export_*.json' \
  --out out/MSCI/enriched_msci.jsonl
```

Joins notes + data_items + codebook, marks each data_item as complete /
incomplete, emits one JSONL line per note. Inspect this file directly to debug
quality issues; it's grep-able by note_id.

### Step 3 — emit final CSVs

```bash
backend/.venv/bin/python tools/data_import/msci/3_split_csvs.py \
  --enriched out/MSCI/enriched_msci.jsonl \
  --mapping tools/data_import/msci/mapping_msci.csv \
  --center MSCI \
  --out-dir out/MSCI/ \
  --min-per-prompt 30 \
  --max-per-prompt 60 \
  --seed 42
```

By default the FAISS pool is **relaxed**: any data_item that has a usable
mapping (non-blank prompt_type in `mapping_msci.csv`) is eligible, even if its
`text_content` still has `[placeholder]` text. This guarantees every mapped
prompt_type ends up with few-shot examples — useful when the source export
has prompts whose entries are partially filled.

Pass `--faiss-strict` to require fully-filled placeholders. The
`fewshots_<center>.csv` evaluation file always allows incomplete items; this
flag affects only the FAISS file.

### Step 3b — sample a balanced evaluation set

The full `fewshots_msci.csv` has thousands of notes. For an evaluation run you
typically want the smallest sample that still gives ≥N annotations per prompt
under the report-type mapping. `sample_for_prompts.py` does this greedily —
much more efficient than random patient sampling for rare report types.

```bash
backend/.venv/bin/python tools/data_import/msci/sample_for_prompts.py \
  --in out/MSCI/fewshots_msci.csv \
  --mapping tools/data_import/msci/msci_report_type_mapping.json \
  --out out/MSCI/fewshots_msci_balanced.csv \
  --center MSCI \
  --target-n 12 \
  --seed 42
```

Typical MSCI result: ~60 notes from ~50 patients cover all 25 prompts at
N≥12. The output is a drop-in replacement for `/api/upload/csv`.

For purely random patient-level sampling (older workflow), use
`sample_patients.py --patients N` instead — useful if you want patient
coherence rather than per-prompt balance.

Selection rules:

| File | Rule |
|------|------|
| `fewshots_<center>.csv` | One row per note with ≥1 **usable** data_item (i.e. node_id has a non-blank mapping). Placeholders kept as-is in incomplete items. |
| `fewshots_<center>_faiss.csv` | One row per (note, prompt_type) where the item is both usable AND complete. Per prompt_type: up to `--max-per-prompt`. Below `--min-per-prompt` triggers a warning. |
| `upload_<center>.csv` | One row per note with zero usable data_items. Annotations column empty. |

A note never appears in both `upload_<center>.csv` and either fewshots file
(mutually exclusive by usable-item count). The same note can appear in both
fewshots files (different schemas serve different ingestion endpoints).

## Manual end-to-end check

After running steps 1–3:

1. Diff one `fewshots_msci.csv` row against `test_data/patients_notes_with_annotations_short.csv`
   to confirm format parity.
2. Upload `fewshots_msci.csv` via the regular `/api/upload/csv` endpoint — the
   UI should report `has_annotations=True` (evaluation mode).
3. Upload `fewshots_msci_faiss.csv` to `/api/upload/fewshots?center=MSCI` and
   confirm the prompt_type list and row count match the step 3 summary.

## Tests

```bash
backend/.venv/bin/python -m pytest tools/data_import/msci/tests -v
```

Pure offline transforms — no vLLM, no FastAPI, no FAISS dependencies.
