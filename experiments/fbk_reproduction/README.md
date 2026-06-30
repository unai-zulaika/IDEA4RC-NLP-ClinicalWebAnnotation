# FBK MSCI reproduction

Independent reproduction of FBK's reported MSCI numbers, scoped to the four
"100%" wins in their slide-39 table:

| Variable | FBK reported acc | FBK effective N | FBK few-shot k |
|---|---:|---:|---:|
| Biopsy Mitotic Count | 100 | 22 | 5 |
| Necrosis in Biopsy | 100 | 14 | 3 |
| Necrosis in Surgical Specimen | 100 | 10 | 2 |
| Patient's Weight & Height | 100 | 21 | 5 |

The goal is to *validate* FBK's numbers, not chase them. If we get 60% they're
not reproducible; if we get 95–100% they are.

## Why this isn't part of the main annotation pipeline

The two setups solve different tasks:

- **Our pipeline:** full-note open-set extraction with abstention. False
  positives on empty-gold notes are heavily penalized.
- **FBK:** per-annotation reproduction — the model is only ever shown notes
  that *do* have a gold annotation for the target variable, and partial
  matches via cosine similarity count as "correct".

So this reproduction is a strict per-annotation EM+PM task, not a real-world
performance estimate. Keep that distinction visible in any write-up.

## Prerequisites

1. **vLLM with Llama-3.1-8B-Instruct.** Launch:
   ```bash
   vllm serve meta-llama/Llama-3.1-8B-Instruct \
     --dtype bfloat16 \
     --max-model-len 8192 \
     --port 8000
   ```
   Requires HF token (gated model).

2. **Python dependencies** (in a venv):
   ```bash
   pip install -r experiments/fbk_reproduction/requirements.txt
   ```

## Run

From the repo root:

```bash
python experiments/fbk_reproduction/run_experiment.py \
  --csv FBK_MSCI/MSCI_Data_25_patients.csv \
  --vllm-url http://localhost:8000/v1 \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --seeds 42 7 123
```

Output: `experiments/fbk_reproduction/results.json` plus a console summary
showing accuracy mean ± std per variable, compared against FBK's reported 100.

To dry-run dataset building only (no vLLM needed):
```bash
python experiments/fbk_reproduction/build_dataset.py \
  --csv FBK_MSCI/MSCI_Data_25_patients.csv \
  --seed 42
```

## Files

- `build_dataset.py` — filter the FBK CSV to target variables, dedupe, 80/20
  split with fixed seed. Writes JSONL per variable.
- `prompts.py` — strict per-variable templates (FBK slide-11 style).
- `rag_retriever.py` — sentence-transformers/all-MiniLM-L6-v2 RAG selector.
- `evaluator.py` — EM + PM via cosine similarity, threshold configurable.
- `run_experiment.py` — orchestrator across variables × seeds.

## Known divergences from FBK's protocol

FBK does not publish their splits or the exact PM threshold per variable, so
exact reproduction is not possible. The script controls for this by:

- Running 3 seeds and reporting mean ± std.
- Using a single PM threshold (0.6) — tunable via `--pm-threshold`.
- Logging every (gold, predicted) pair in `results.json` so post-hoc analysis
  with a different threshold is possible without re-running the model.

If reproduction fails, check in this order:

1. Are our dedupe/split sizes the same as FBK's table? (`build_dataset.py`
   prints them.) If not, the dedupe rule may differ.
2. Are predictions polluted with reasoning/explanation despite the strict
   prompt? (Check `results.json` samples.) Llama can over-explain even when
   told not to.
3. Sweep `--pm-threshold` over {0.3, 0.5, 0.77} on the existing `results.json`
   (a follow-up `rescore.py` script can be added).
