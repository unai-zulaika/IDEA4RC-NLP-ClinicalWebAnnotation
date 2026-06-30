# FBK setup + our methodology, all 25 MSCI variables

**Question we set out to answer:** if you take FBK's exact setup
(Llama-3.1-8B-Instruct + their strict-template prompts + RAG-selected
few-shots) but score it with **our** evaluation methodology
(match / mismatch / FP / FN / both_empty on real notes including ones with no
gold annotation), how does it compare to our system on the same 60-note
session?

## Headline numbers

Means across the 25 MSCI variables (filtered scoring, same `report_type_mapping`
our filtered report uses):

| Metric | OURS (MedGemma + our prompts) | FBK setup (Llama-3.1-8B + strict prompt) |
|---|---:|---:|
| **Correct%** = (match + both_empty) / N | **32.0%** | 16.7% |
| **Extract%** = strict match / N | 10.0% | 10.1% |
| **FP%** = false_positive / N | 56.8% | **71.7%** |

The key finding: **Extract% is essentially tied (10.0 vs 10.1)** — both systems
get the right value when there *is* a gold answer with about the same hit rate.
**FBK's setup loses ground on Correct% because it almost never abstains**: when
shown a note with no relevant info for the target variable, it still fills in
the template (often hallucinating dates / values). Our methodology penalizes
that; FBK's reproduction metric (cosine PM) doesn't.

## Per-variable comparison (filtered)

Sorted by Correct% under FBK setup:

| Variable | OURS Correct% (N) | FBK setup Correct% (N) | Δ |
|---|---:|---:|---:|
| `surgerytype` | 92% (12) | 83% (12) | -9 |
| `radiotherapy_start` | 55% (20) | 50% (22) | -5 |
| `previous_cancer_treatment` | 50% (12) | 33% (12) | -17 |
| `biopsymitoticcount` | 42% (12) | 25% (12) | -17 |
| `occurrence_cancer` | 50% (12) | 25% (12) | -25 |
| `gender` | 67% (12) | 25% (12) | -42 |
| `chemotherapy_end` | 33% (9) | 25% (12) | -8 |
| `histological` | 42% (12) | 17% (12) | -25 |
| `necrosis_in_surgical` | 25% (12) | 17% (12) | -8 |
| `recurrencetype` | 9% (11) | 17% (12) | +8 |
| `last_contact_date` | 42% (12) | 17% (12) | -25 |
| `tumorbiopsytype` | 50% (12) | 17% (12) | -33 |
| `radiotherapy_end` | 0% (9) | 17% (12) | +17 |
| `patient-status` | 25% (24) | 12% (24) | -12 |
| `stage_at_diagnosis` | 8% (12) | 8% (12) | 0 |
| `chemotherapy_start` | 33% (9) | 8% (12) | -25 |
| `patient-bmi` | 33% (12) | 8% (12) | -25 |
| `biopsygrading` | 8% (12) | 8% (12) | 0 |
| `tumorsite` | 4% (24) | 4% (24) | 0 |
| `necrosis_in_biopsy` | 8% (12) | 0% (12) | -8 |
| `tumordiameter` | 42% (12) | 0% (12) | -42 |
| `ageatdiagnosis` | 50% (12) | 0% (12) | -50 |
| `recur_or_prog` | 0% (11) | 0% (12) | 0 |
| `patient-weightheight` | 33% (12) | 0% (12) | -33 |
| `surgerymargins` | 0% (12) | 0% (12) | 0 |

Tally: **OURS wins on 18 variables**, **5 ties**, **FBK setup wins on 2**
(`recurrencetype` +8, `radiotherapy_end` +17).

## What's driving the gap

Looking at the breakdown per variable (full table in
`experiments/fbk_reproduction/full25/comparison.md`), the FBK setup's failure
mode is almost always the same:

- **FP% = 100%** on six variables (`tumordiameter`, `ageatdiagnosis`,
  `recur_or_prog`, `patient-weightheight`, `surgerymargins`,
  `necrosis_in_biopsy`). The model fills the template even when the note
  contains no relevant information. None of those predictions match a real
  gold annotation — every prediction is FP.
- **FP% > 80%** on another four (`patient-bmi`, `radiotherapy_end`,
  `stage_at_diagnosis`, `tumorsite`).
- The FBK strict prompt does include "if not stated, output Unknown X" — but
  the few-shot pool only contains positive examples, so the model defaults to
  extracting rather than abstaining.

By contrast our system uses prompts that include explicit Unknown / Not
applicable values in their few-shot pool and reasoning, which gives the
model a clearer signal to abstain.

## Variables where FBK setup beats us

- `radiotherapy_end` (+17): we get 0% — broken in our system on this
  variable. Worth investigating. FBK setup gets 17% mostly from
  abstentions, not real extractions (Extract% = 0, both_empty = 2/12).
- `recurrencetype` (+8): similar — FBK setup picks up 2/12 correct
  abstentions vs our 1/11.

In both cases the FBK lead is entirely from better abstention, not better
extraction. There's no variable on which FBK setup *extracts* better than
ours under this scoring.

## Take-home

If you score with our methodology — i.e. on a realistic note mix, with
penalties for over-prediction — **our system is roughly twice as good**
on aggregate (32% vs 17%), and it's better or tied on 23 of 25 variables.
The 100% claims in FBK's slides disappear entirely; under fair scoring
they're 17% on average.

The other way to say it: **FBK's pipeline is good at producing well-
formatted text, but bad at knowing when *not* to.** Their evaluation
protocol never exposed that because it only ever showed the model notes
where a gold annotation existed.

## Files

- `full25/predictions.jsonl` — all 1500 (note, variable, gold, predicted) rows.
- `full25/per_variable.json` — unfiltered per-variable counts.
- `full25/comparison.json` — both unfiltered and filtered aggregates + ours.
- `full25/comparison.md` — the full markdown comparison table.
- `full_25_templates.py` — the 25 FBK-style prompt templates we used.
- `run_full_25.py`, `rerun_errors.py` — runners.
- `score_full_25_filtered.py` — scorer + report generator.
