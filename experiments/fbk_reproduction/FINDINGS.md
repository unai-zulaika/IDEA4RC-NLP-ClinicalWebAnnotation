# FBK MSCI reproduction — findings

**Date:** 2026-05-26
**Setup:** Llama-3.1-8B-Instruct (BF16) via vLLM, FAISS-like RAG over MiniLM
embeddings, 80/20 train/test, 3 seeds (42, 7, 123), MSCI_Data_25_patients.csv.

## TL;DR

**FBK's 100% accuracy claim reproduces at their PM≥0.6 threshold — but the
metric is so permissive that wrong answers are counted correct.** Under
stricter scoring or value-only exact match (ignoring template boilerplate),
the underlying extraction quality is far below 100%, and in some cases (dates
on weight/height) is essentially zero.

## Reproduction at FBK's reported threshold

| Variable | FBK reported | Our reproduction (mean ± std) | Match |
|---|---:|---:|---|
| Biopsy Mitotic Count | 100 | 100.0 ± 0.0 | ✅ |
| Necrosis in Biopsy | 100 | 100.0 ± 0.0 | ✅ |
| Necrosis in Surgical Specimen | 100 | 100.0 ± 0.0 | ✅ |
| Patient's Weight & Height | 100 | 100.0 ± 0.0 | ✅ |

We hit FBK's numbers exactly. So their pipeline is real and reproducible
under the metric they used.

## The problem with the metric

FBK count an answer as "correct" if either:

- It exactly matches the gold (EM), **or**
- Its cosine similarity to gold is ≥ some threshold (PM).

For short categorical / templated outputs, the cosine vector is dominated by
the shared template prefix. Concrete examples from our reproduction:

| Variable | Gold | Predicted | FBK score |
|---|---|---|---|
| Necrosis in biopsy | `Necrosis in biopsy specimen (type of): present.` | `…(type of): absent.` | **counted correct (PM)** |
| Necrosis in surgical | `…(type of): 10%.` | `…(type of): present.` | **counted correct (PM)** |
| Necrosis in surgical | `…(type of): unknown.` | `…(type of): present.` | **counted correct (PM)** |
| Weight/Height | `…(evaluated on 18/03/2019).` | `…(evaluated on 03/02/2022).` | **counted correct (PM)** |
| Weight/Height | `…(evaluated on 11/10/2019).` | `…(evaluated on 01/01/2024).` | **counted correct (PM)** |

Two of those have the wrong clinical answer (absent vs. present). The
weight/height ones have hallucinated dates — the model frequently invents
defaults like `01/01/2024`.

## Accuracy under stricter scoring

Mean across 3 seeds. **EM** = exact string match; **VAL-EM** = exact match on
the value after the colon (ignores boilerplate); **PM≥t** = FBK-style
cosine-similarity threshold:

| Variable | EM | VAL-EM | PM≥0.3 | PM≥0.6 | PM≥0.77 | PM≥0.9 | PM≥0.95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Biopsy Mitotic Count | 43.8 | 43.8 | 100.0 | **100.0** | 100.0 | 95.8 | 85.4 |
| Necrosis in Biopsy | 36.4 | 36.4 | 100.0 | **100.0** | 100.0 | 100.0 | 93.9 |
| Necrosis in Surgical | 16.7 | 29.2 | 100.0 | **100.0** | 100.0 | 83.3 | 70.8 |
| Patient Weight & Height | **4.8** | **4.8** | 100.0 | **100.0** | 100.0 | 100.0 | 85.7 |

The bolded 0.6 column is FBK's reported number. Going one column right
(PM≥0.95) starts revealing what the model actually got right. VAL-EM is the
honest answer for what the model extracted correctly.

## What this tells us

1. **The model isn't doing better than ours; the metric is.** When you score
   only on whether the extracted value is correct (VAL-EM), Llama-3.1-8B
   produces the right answer 5–44% of the time — comparable to or worse than
   what our system delivers on the same variables on harder tasks (full-note
   extraction with abstention).

2. **The reported 100% is a property of cosine similarity over templated
   strings, not a property of the model.** Any model that produces something
   starting with the right template prefix scores high PM.

3. **Date extraction is broken.** For Patient's Weight & Height, only 1 in 20
   predictions across 3 seeds matched the gold date. The model defaults to
   common date strings (e.g. `01/01/2024`). FBK's metric never sees this.

4. **Categorical flips are invisible.** Necrosis variables in particular have
   a tiny set of values (`absent`, `present`, `unknown`, `10%`, etc.) — and
   the model gets these wrong 60-70% of the time on value-only matching, yet
   PM≥0.6 still rates it 100%.

## Side-by-side: ours vs FBK reproduction under the same metric

Pulling our system's (gold, predicted) pairs from the MSCI session JSONs,
keeping only cases where gold annotation actually exists (matches FBK's
filtering), and scoring with the same evaluator:

### Filtered session (3effb5be), MedGemma + our JSON-reasoning prompt

| Variable | Metric | OURS | FBK-repro | Δ |
|---|---|---:|---:|---:|
| biopsy_mitotic_count | EM | 16.7 | 43.8 | -27.1 |
| biopsy_mitotic_count | VAL-EM | 16.7 | 43.8 | -27.1 |
| biopsy_mitotic_count | PM≥0.95 | 66.7 | 85.4 | -18.8 |
| biopsy_mitotic_count | N | 6 | 16 | — |
| necrosis_in_surgical | EM | **33.3** | 16.7 | **+16.7** |
| necrosis_in_surgical | VAL-EM | **50.0** | 29.2 | **+20.8** |
| necrosis_in_surgical | PM≥0.95 | 33.3 | 70.8 | -37.5 |
| necrosis_in_surgical | N | 6 | 8 | — |
| necrosis_in_biopsy | — | (no gold in session) | 100 | — |
| patient_weight_height | — | (no gold in session) | 100 | — |

### What this means

1. **Test set bias is real and large.** Our session has zero gold-present
   cases for `necrosis_in_biopsy` and `patient_weight_height` — the 60-note
   sample our system was run on simply didn't include the histopathology /
   admission notes that contain those annotations. So you can't fairly
   compare on those two with existing data; a rerun on FBK's split would be
   needed.

2. **Where we *can* compare, the picture splits:**
   - On `biopsy_mitotic_count` FBK genuinely does better — VAL-EM 44% vs
     17%. This is a real model gap (Llama-3.1-8B vs MedGemma 4B W4A16) or a
     prompt-format gap (strict template vs our JSON-with-reasoning) or both.
   - On `necrosis_in_surgical` we actually do *better* on VAL-EM (50% vs
     29%) — when we get it right, we get the value flat-out correct. But our
     PM≥0.95 looks worse because our prediction text contains long reasoning
     JSON that drops cosine similarity even when the answer is right.

3. **Our JSON-with-reasoning output hurts cosine-based metrics.** Even when
   the extracted value is correct, the bloat around it lowers cosine
   similarity. If we want FBK-style PM numbers, we have to emit short
   text-only outputs like they do. That's a prompt-design choice, not a
   capability gap.

## Recommendation

- **The 100% claim is a metric artefact, not a quality result.** When scored
  on what was extracted (VAL-EM), FBK's Llama-3.1-8B gets 5-44% on the same
  test cases. That's the honest number to compare against.
- **For a true head-to-head**, we'd need to rerun our system on FBK's exact
  80/20 test set for each variable. That requires:
    - either swapping vLLM back to MedGemma and pointing our pipeline at the
      FBK CSV, or
    - keeping Llama-3.1-8B and just swapping our prompt templates in
      (isolates prompt effect, not model effect).
- **Dates need exact match, not cosine.** No matter what FBK says, scoring
  hallucinated dates as "correct" via cosine is wrong.

## Files

- `results.json` — every (gold, predicted) pair from the 3-seed reproduction.
- `rescore.json` — rescoring at multiple thresholds + VAL-EM.
- `comparison.json` — side-by-side numbers for ours vs FBK.
- `run.log` — original run output.
