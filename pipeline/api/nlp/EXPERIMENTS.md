# NLP evaluation experiment harness

Config-driven harness for the final-review study. Every run is described by an
`ExpConfig`; results land in `experiments/results/<run_id>/`.

## Components

| Script | Role |
|---|---|
| `exp_registry.py` | Defines `ExpConfig`, the per-center data locations, the model→served-name map, and the experiment matrix (one-factor-at-a-time around an anchor). Run it with no args to print the plan grouped by which model must be served. |
| `exp_build_fewshots.py` | Builds per-mode FAISS indexes (`all`, `complete`, `incomplete`, `note-only`) for the few-shot-quality dimension. Run once per center. |
| `exp_run.py` | Runs configs and writes `predictions.csv`. Validates the live vLLM model matches the config. Raw stack shells out to `evaluate_llm_int_prompts.py`; production stack to `evaluate_via_backend.py`. |
| `exp_judge.py` | Auto-judges predictions (via `auto_judge.py`) and writes `verdicts.csv` + `metrics.json` (accuracy, hallucination rate, translation-leak rate). |
| `exp_analyze.py` | Reads metrics across one dimension and writes a comparison CSV + bar plot to `experiments/results/_analysis/`. |

## Matrix size and progress tracking

The matrix is defined in `exp_registry.py` (`build_matrix()` + `raw_sweep_configs()`). To see it and track progress:

```bash
$PY exp_registry.py        # print the plan grouped by served model
$PY exp_status.py          # live dashboard: [ ] not started / [P] predictions / [J] judged
$PY exp_status.py --model 4b   # just the 4b runs
```

Run counts per model (INT-SARC):

| Model | Raw sweep (K + filter + few-shot mode) | Production (reasoning on/off) | Total |
|---|---|---|---|
| 4b | 9 | 2 | 11 |
| 27b | 9 | 2 | 11 |
| qwen8b | 9 | 0 (not in matrix yet) | 9 |
| **Total distinct** | | | **31** |

The 9 raw-sweep cells per model are: `k0, k1, k3, k5, k10` (few-shot K) + `filter0` (filter off) + `complete, incomplete, note-only` (few-shot mode). The `k5 / all / filter-on` anchor is shared across the K and mode sweeps so it isn't double-counted.

## One-time setup

```bash
cd /home/zulaika/ClinicalAnnotationWeb/pipeline/api/nlp
PY=/home/zulaika/ClinicalAnnotationWeb/backend/.venv/bin/python

# Build the few-shot FAISS indexes (needs the GPU for embeddings, ~1 min)
$PY exp_build_fewshots.py --center INT-SARC

# See the full run plan, grouped by which model you must serve
$PY exp_registry.py
```

## Which stack to report

**The production stack is the hospital-representative result** — it runs the real
prompts, structured-output schema, ICD-O-3 lookup, history splitting and the
production prompt wrapper, exactly as the clinic runs it. Report these numbers.

The **raw** stack (`--raw-sweep`) is an internal control only: it isolates the
model from the production pipeline (useful for "what does the production stack
add"), but it is NOT what hospitals run, so it does not go in the headline.

### Production sweep (no backend restart): K, filter, reasoning

```bash
# serve the model on :8000, point backend/config/vllm_config.json at it, start backend on :8001
$PY exp_run.py --model 4b --prod-sweep      # 7 cells (K-sweep 5 + filter-off + reason-off)
$PY exp_judge.py --all
```

### Few-shot mode on production (pseudo-automated)

The backend pool is loaded once with the original-with-placeholders file
(`extra_data/fewshot_examples_INT_with_missing.csv`). After that, the
`sanitize_fewshots` flag in `backend/config/vllm_config.json` covers the two
main Q3 contrasts without any further pool swap:

  - `sanitize_fewshots: true`  → placeholders stripped at render → **complete-effective**
  - `sanitize_fewshots: false` → placeholders kept → **incomplete-faithful**

The driver toggles the flag, waits for you to restart the backend, runs and
judges the cell, then moves on:

```bash
$PY exp_run_fewshot_mode.py --model 4b
#   it will prompt: "RESTART THE BACKEND NOW" between the two modes.
#   include note-only (needs a pool swap) with --include-note-only:
$PY exp_run_fewshot_mode.py --model 4b --include-note-only
# restore the pool when fully done:
$PY exp_load_backend_fewshots.py --restore
```

## Metrics

`exp_judge.py` writes per-run `metrics.json` with:

| Field | Meaning |
|---|---|
| `accuracy_pct` | % correct on gold-present rows (LLM-as-judge auto-scored, 95% agreement with manual verdicts). |
| `hallucination_rate_pct` | % of all predictions that exhibit a **repetition-loop / broken generation** (e.g. "The note mentions X. The note mentions Y. The note mentions X. ..."). Ground-truth detector; the raw stack reports 0% on every cell, the production stack with reasoning-on reports 7–12%. |
| `n_uncertain` / `n_gold_absent` | # of gold-absent rows where the model committed a value, out of total gold-absent. **Informational only, NOT penalized:** annotators didn't always fill every variable, so a committed value here may be the model correctly finding something the annotator skipped. |
| `translation_leak_rate_pct` | % of committed predictions containing source-language markers (Italian for INT-SARC) — flags when the model failed to translate. |

The previous "hallucination" metric measured over-commitment on gold-absent
rows, which conflated invention with annotator omission. It was retired
2026-05-28 in favour of loop-detection (clear ground truth) + the uncertain
count (informational).

## Running on a GPU

The harness can't switch the served model itself, so you serve one model, run
every config that needs it, then switch. The config-to-model grouping is what
`exp_registry.py` prints.

### Block A — serve the 27B (covers most of the raw matrix + 27B production)

```bash
# terminal 1: the model
CUDA_VISIBLE_DEVICES=3 vllm serve unaizulaika/medgemma-27b-text-it-W4A16-G128 \
  --max-model-len 16384 --max-num-seqs 32 --gpu-memory-utilization 0.85

# terminal 2: run every RAW config that needs 27b (fast: K-sweep, filter, fewshot-mode)
cd pipeline/api/nlp
$PY exp_run.py --model 27b --stack raw
$PY exp_judge.py --all

# for the 27B PRODUCTION runs (reasoning on/off), also start the backend:
#   cd backend && uvicorn main:app --port 8001
# then:
$PY exp_run.py --model 27b --stack production
$PY exp_judge.py --all
```

### Block B — serve the 4B (e.g. on GPU 2)

```bash
# terminal 1: the model on GPU 2, default port 8000
CUDA_VISIBLE_DEVICES=2 vllm serve unaizulaika/medgemma-1.5-4b-it-W4A16-G128 \
  --dtype auto --max-model-len 32768 --enable-chunked-prefill --gpu-memory-utilization 0.95

# terminal 2: the 9 raw-sweep cells (K, filter, few-shot mode) — a few min total on 4B
cd pipeline/api/nlp
$PY exp_run.py --model 4b --raw-sweep
$PY exp_judge.py --all
$PY exp_status.py --model 4b      # check progress

# the 2 production cells (reasoning on/off) also need the backend pointed at 4b:
#   edit backend/config/vllm_config.json model_name -> 4b, then: cd backend && uvicorn main:app --port 8001
$PY exp_run.py --model 4b --stack production
$PY exp_judge.py --all
```

`exp_run.py` auto-writes `vllm_config.json` to match the served model before each raw run, so you don't need to sync it by hand.

### Block C — serve Qwen3-8B

```bash
CUDA_VISIBLE_DEVICES=3 vllm serve Qwen/Qwen3-8B \
  --max-model-len 16384 --gpu-memory-utilization 0.85

$PY exp_run.py --model qwen8b
$PY exp_judge.py --all
```

### Analyze

```bash
$PY exp_analyze.py --all
# or one dimension:
$PY exp_analyze.py --dimension fewshot_k
```

Outputs land in `experiments/results/_analysis/<dimension>.{csv,png}`.

## Notes

- `exp_run.py` skips a config if its `predictions.csv` already exists (use `--force` to re-run).
- The raw stack is ~20x faster than production; the K-sweep / filter / fewshot-mode dimensions all run in a few minutes each on the 4B.
- The model name in a production config is a label only; the backend's `backend/config/vllm_config.json` is authoritative, so point it at the right model and restart the backend before a production block.
- Validation: seeding the existing 4B raw detailed CSV into the harness and judging it gives 36.1% vs the 35.1% hand-judged figure (within 1 point), confirming the auto-judge scoring path.

## Blocked dimensions (not in the matrix yet)

| Question | Blocker |
|---|---|
| Q1 languages (INT-HNC, MSCI, VGR) | gold note sets for those centers (same format as `extra_data/patients_notes_with_annotations_INT.csv`); add a `CenterData` entry in `exp_registry.py` |
| Q6 clinician prompt revisions | the workshop; once done, add `prompt_version="post"` configs |
| Q8 reasoning-quality (does reasoning support the answer?) | an LLM-as-judge pass over `(reasoning, final_output)` from the production runs; separate analyzer to be added |
