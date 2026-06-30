#!/usr/bin/env python3
"""
Per-sub-field rescoring of the existing 27B runs to match the PDF's methodology.

The PDF reports multi-field prompts as per-field denominators (e.g. surgery
"type 14/14, date 12/14, completeness 13/14"). The previous LLM-as-judge
collapses these into one verdict per row — which is stricter and not directly
comparable. This script decomposes every multi-field row into sub-fields and
aggregates per-sub-field accuracy per prompt, for both the pipeline and the
backend runs.

Single-value prompts (gender, age, etc.) have a single sub-field equal to the
row verdict.

Sub-field definitions match the PDF's "Variable(s)" column.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR, PLOTS_DIR

# Sub-field verdicts per row idx, schema:
#   key: (run, row_idx) where run is "pipe" or "back"
#   value: dict {sub_field_name: 'C' | 'W' | 'NA'}
#       NA = sub-field is not applicable to this row (PDF doesn't count it)
#
# Multi-field prompt sub-fields:
#   surgerytype-fs30       : type, date, completeness
#   chemotherapy_start     : setting, date, regimen, intent
#   chemotherapy_end       : setting, date, cycles, reason
#   radiotherapy_start     : setting, intent, hospital, date
#   radiotherapy_end       : setting, dose, fractions, date, reason
#   tumorbiopsytype        : biopsy_type, date, institution
#   reexcision             : date, completeness
#   recurrencetype         : type, site_detail
#   recur_or_prog          : event_type, date
# Single-value prompts (gender, ageatdiagnosis, biopsygrading,
# tumordiameter, tumorsite, histological-tipo, surgerymargins,
# surgical-mitotic-count, stage_at_diagnosis, response-to,
# patient-status, previous_cancer_treatment) — single sub-field "value".

# Pipeline (27B raw vLLM) per-sub-field verdicts — extends judge_verdicts.csv
# I've decomposed each multi-field row by re-reading the (gold, pred) pair.
PIPE: dict[int, dict[str, str]] = {
    # === single-value rows: just propagate the row verdict ===
    0:  {"value": "C"},   # biopsygrading
    7:  {"value": "C"},   # ageatdiagnosis
    21: {"value": "C"},   # gender
    17: {"value": "C"},   # surgerymargins
    30: {"value": "C"},   # surgerymargins
    39: {"value": "C"},   # ageatdiagnosis
    42: {"value": "C"},   # gender
    43: {"value": "C"},   # gender
    44: {"value": "C"},   # stage_at_diagnosis
    45: {"value": "C"},   # ageatdiagnosis
    58: {"value": "C"},   # biopsygrading
    68: {"value": "C"},   # biopsygrading
    71: {"value": "C"},   # surgerytype-fs30 special: see below
    73: {"value": "C"},   # ageatdiagnosis
    74: {"value": "C"},   # stage_at_diagnosis
    72: {"value": "C"},   # stage_at_diagnosis (pipeline idx 72)
    62: {"value": "W"},   # stage_at_diagnosis
    46: {"value": "W"},   # histological-tipo
    63: {"value": "W"},   # histological-tipo
    75: {"value": "W"},   # histological-tipo
    2:  {"value": "C"},   # histological-tipo
    8:  {"value": "C"},   # histological-tipo
    40: {"value": "C"},   # histological-tipo
    3:  {"value": "C"},   # tumordiameter
    11: {"value": "W"},   # tumordiameter
    69: {"value": "C"},   # tumordiameter
    4:  {"value": "C"},   # tumorsite
    9:  {"value": "C"},   # tumorsite
    41: {"value": "C"},   # tumorsite
    47: {"value": "C"},   # tumorsite
    64: {"value": "C"},   # tumorsite
    70: {"value": "C"},   # tumorsite
    48: {"value": "C"},   # surgical-mitotic-count
    5:  {"value": "W"},   # previous_cancer_treatment
    15: {"value": "W"},   # response-to
    26: {"value": "C"},   # response-to
    54: {"value": "W"},   # response-to
    67: {"value": "C"},   # response-to

    # === MULTI-FIELD sub-field decompositions ===

    # surgerytype-fs30: type / date / completeness
    6:  {"type": "C", "date": "C", "completeness": "W"},
    18: {"type": "C", "date": "W", "completeness": "W"},
    20: {"type": "C", "date": "W", "completeness": "W"},
    33: {"type": "C", "date": "W", "completeness": "W"},
    49: {"type": "C", "date": "C", "completeness": "W"},
    51: {"type": "C", "date": "W", "completeness": "W"},
    65: {"type": "C", "date": "C", "completeness": "C"},
    71: {"type": "C", "date": "C", "completeness": "NA"},  # gold has [select result] placeholder

    # chemotherapy_start: setting / date / regimen / intent
    13: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    22: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},  # date close enough
    32: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},
    50: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},
    # idx 10 was a data-issue row — exclude

    # chemotherapy_end: setting / date / cycles / reason
    12: {"setting": "C", "date": "W", "cycles": "C", "reason": "W"},
    27: {"setting": "W", "date": "C", "cycles": "C", "reason": "C"},  # gold says unknown, pred says unknown
    37: {"setting": "C", "date": "C", "cycles": "C", "reason": "W"},
    55: {"setting": "W", "date": "W", "cycles": "NA", "reason": "C"},  # gold cycles=[provide number]

    # radiotherapy_start: setting / intent / hospital / date
    23: {"setting": "W", "intent": "W", "hospital": "W", "date": "C"},
    34: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},  # gave end info
    52: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    59: {"setting": "C", "intent": "C", "hospital": "W", "date": "C"},

    # radiotherapy_end: setting / dose / fractions / date / reason
    25: {"setting": "W", "dose": "C", "fractions": "W", "date": "C", "reason": "W"},
    36: {"setting": "W", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},
    60: {"setting": "C", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},

    # tumorbiopsytype: biopsy_type / date / institution
    1:  {"biopsy_type": "NA", "date": "C", "institution": "C"},   # gold has [pick biopsy type] placeholder
    61: {"biopsy_type": "C", "date": "C", "institution": "C"},

    # reexcision: date / completeness
    31: {"date": "C", "completeness": "W"},

    # recurrencetype: type / site_detail
    14: {"type": "C", "site_detail": "C"},
    24: {"type": "W", "site_detail": "W"},
    35: {"type": "C", "site_detail": "W"},  # local correct, soft tissue site missing
    53: {"type": "W", "site_detail": "W"},

    # recur_or_prog: event_type / date
    16: {"event_type": "C", "date": "W"},
    19: {"event_type": "W", "date": "W"},
    28: {"event_type": "W", "date": "W"},
    38: {"event_type": "C", "date": "C"},
    56: {"event_type": "W", "date": "W"},

    # patient-status data issues
    29: {"value": "D"},
    57: {"value": "D"},
}


BACK: dict[int, dict[str, str]] = {
    # === single-value rows ===
    0:  {"value": "C"},   # biopsygrading correct
    7:  {"value": "C"},   # ageatdiagnosis
    17: {"value": "C"},   # surgerymargins
    21: {"value": "W"},   # gender — abstained
    30: {"value": "C"},   # surgerymargins (one was filtered out vs pipeline)
    37: {"value": "C"},   # ageatdiagnosis
    38: {"value": "C"},   # histological-tipo
    39: {"value": "C"},   # tumorsite
    40: {"value": "W"},   # gender abstained
    41: {"value": "W"},   # gender abstained
    42: {"value": "C"},   # stage_at_diagnosis
    43: {"value": "C"},   # ageatdiagnosis
    44: {"value": "C"},   # histological-tipo (PEComa)
    45: {"value": "C"},   # tumorsite (Vescica)
    46: {"value": "C"},   # surgical-mitotic-count
    56: {"value": "W"},   # biopsygrading wrong
    66: {"value": "W"},   # biopsygrading wrong
    2:  {"value": "C"},   # histological-tipo
    8:  {"value": "C"},   # histological-tipo
    61: {"value": "W"},   # histological-tipo
    72: {"value": "C"},   # histological-tipo
    3:  {"value": "C"},   # tumordiameter
    11: {"value": "W"},   # tumordiameter
    67: {"value": "C"},   # tumordiameter
    4:  {"value": "C"},   # tumorsite
    9:  {"value": "C"},   # tumorsite
    62: {"value": "C"},   # tumorsite
    68: {"value": "C"},   # tumorsite
    5:  {"value": "W"},   # previous_cancer_treatment
    60: {"value": "W"},   # stage_at_diagnosis
    70: {"value": "C"},   # stage_at_diagnosis
    71: {"value": "C"},   # ageatdiagnosis
    15: {"value": "W"},   # response-to
    26: {"value": "W"},   # response-to (was abstained)
    52: {"value": "W"},   # response-to
    65: {"value": "W"},   # response-to

    # === MULTI-FIELD ===
    # surgerytype-fs30
    6:  {"type": "W", "date": "C", "completeness": "W"},   # "Surgical procedure", completeness missing
    18: {"type": "W", "date": "W", "completeness": "W"},
    20: {"type": "W", "date": "W", "completeness": "W"},
    31: {"type": "W", "date": "W", "completeness": "W"},
    47: {"type": "W", "date": "W", "completeness": "W"},
    49: {"type": "W", "date": "W", "completeness": "W"},
    63: {"type": "W", "date": "C", "completeness": "W"},
    69: {"type": "C", "date": "C", "completeness": "NA"},

    # chemotherapy_start
    13: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},
    22: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},
    30: {"setting": "C", "date": "C", "regimen": "C", "intent": "W"},  # pipeline idx 30 mapped to backend idx 30 may differ — re-check
    48: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},

    # chemotherapy_end
    12: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},
    27: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},
    35: {"setting": "C", "date": "C", "cycles": "C", "reason": "C"},
    53: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},

    # radiotherapy_start
    23: {"setting": "W", "intent": "W", "hospital": "W", "date": "C"},
    32: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    50: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    57: {"setting": "C", "intent": "W", "hospital": "C", "date": "C"},

    # radiotherapy_end
    25: {"setting": "W", "dose": "C", "fractions": "W", "date": "C", "reason": "W"},
    34: {"setting": "C", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},
    58: {"setting": "C", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},

    # tumorbiopsytype
    1:  {"biopsy_type": "C", "date": "C", "institution": "C"},
    59: {"biopsy_type": "C", "date": "C", "institution": "C"},

    # recurrencetype
    14: {"type": "NA", "site_detail": "NA"},  # backend returned empty — abstention
    24: {"type": "W", "site_detail": "W"},
    33: {"type": "C", "site_detail": "W"},
    51: {"type": "W", "site_detail": "W"},

    # recur_or_prog
    16: {"event_type": "W", "date": "W"},
    19: {"event_type": "W", "date": "W"},
    28: {"event_type": "W", "date": "W"},
    36: {"event_type": "W", "date": "W"},
    54: {"event_type": "W", "date": "W"},

    # patient-status data-issue rows
    29: {"value": "D"},
    55: {"value": "D"},

    # data-issue rows skipped: 10, 64
    10: {"setting": "D"},  # gold mislabeled
    64: {"setting": "D"},  # gold mislabeled
}


# PDF per-sub-field numbers (denominator / correct) from the original report
PDF_SUBFIELD = {
    ("surgerytype-fs30",      "type"):         (14, 14),
    ("surgerytype-fs30",      "date"):         (12, 14),
    ("surgerytype-fs30",      "completeness"): (13, 14),
    ("chemotherapy_start",    "setting"):      (16, 16),
    ("chemotherapy_start",    "date"):         (11, 16),
    ("chemotherapy_start",    "regimen"):      (11, 16),
    ("chemotherapy_start",    "intent"):       (8, 16),
    ("chemotherapy_end",      "date"):         (10, 14),
    ("chemotherapy_end",      "reason"):       (10, 14),
    ("chemotherapy_end",      "cycles"):       (8, 14),
    ("radiotherapy_start",    "intent"):       (4, 7),
    ("radiotherapy_start",    "hospital"):     (2, 7),
    ("radiotherapy_start",    "date"):         (2, 7),
    ("radiotherapy_end",      "dose"):         (9, 10),
    ("radiotherapy_end",      "fractions"):    (9, 10),
    ("radiotherapy_end",      "date"):         (9, 10),
    ("tumorbiopsytype",       "biopsy_type"):  (7, 21),
    ("tumorbiopsytype",       "date"):         (11, 21),
    ("tumorbiopsytype",       "institution"):  (11, 21),
    ("reexcision",            "date"):         (7, 12),
    ("reexcision",            "completeness"): (8, 12),
    ("recurrencetype",        "type"):         (26, 28),
    ("recurrencetype",        "site_detail"):  (4, 14),
    ("recur_or_prog",         "date"):         (16, 26),
}


def aggregate(verdicts: dict[int, dict[str, str]], prompts_by_idx: dict[int, str]) -> dict:
    """Return per-prompt per-sub-field correct/total dicts."""
    agg: dict = {}
    for idx, sf_map in verdicts.items():
        prompt = prompts_by_idx.get(idx)
        if prompt is None:
            continue
        # Strip -int suffix for matching to PDF keys
        prompt_key = prompt.replace("-int", "")
        agg.setdefault(prompt_key, {})
        for sf, v in sf_map.items():
            if v == "D" or v == "NA":
                continue  # excluded from denominator
            agg[prompt_key].setdefault(sf, [0, 0])
            agg[prompt_key][sf][1] += 1
            if v == "C":
                agg[prompt_key][sf][0] += 1
    return agg


BACK_V2: dict[int, dict[str, str]] = {
    # === single-value rows (post-prompt-fix backend) ===
    0:  {"value": "C"},   # biopsygrading
    2:  {"value": "C"},   # histological-tipo
    7:  {"value": "C"},   # ageatdiagnosis
    8:  {"value": "C"},   # histological-tipo
    11: {"value": "C"},   # tumordiameter — IMPROVED (was W)
    17: {"value": "C"},   # surgerymargins
    21: {"value": "C"},   # gender — IMPROVED (was W)
    37: {"value": "C"},   # ageatdiagnosis
    38: {"value": "W"},   # histological-tipo — REGRESSED (ICD code wrong)
    39: {"value": "C"},   # tumorsite
    40: {"value": "C"},   # gender — IMPROVED
    41: {"value": "C"},   # gender — IMPROVED
    42: {"value": "C"},   # stage_at_diagnosis
    43: {"value": "C"},   # ageatdiagnosis
    44: {"value": "C"},   # histological-tipo
    45: {"value": "C"},   # tumorsite
    46: {"value": "C"},   # surgical-mitotic-count
    56: {"value": "C"},   # biopsygrading — IMPROVED
    60: {"value": "W"},   # stage_at_diagnosis
    61: {"value": "W"},   # histological-tipo
    62: {"value": "C"},   # tumorsite
    66: {"value": "W"},   # biopsygrading
    67: {"value": "C"},   # tumordiameter
    68: {"value": "C"},   # tumorsite
    70: {"value": "C"},   # stage_at_diagnosis
    71: {"value": "C"},   # ageatdiagnosis
    72: {"value": "C"},   # histological-tipo
    3:  {"value": "C"},   # tumordiameter
    4:  {"value": "C"},   # tumorsite
    9:  {"value": "C"},   # tumorsite
    5:  {"value": "W"},   # previous_cancer_treatment
    15: {"value": "W"},   # response-to
    26: {"value": "W"},   # response-to
    52: {"value": "W"},   # response-to
    65: {"value": "W"},   # response-to

    # === MULTI-FIELD ===
    # surgerytype-fs30
    6:  {"type": "W", "date": "C", "completeness": "W"},
    18: {"type": "W", "date": "W", "completeness": "W"},
    20: {"type": "W", "date": "W", "completeness": "W"},
    31: {"type": "W", "date": "W", "completeness": "W"},
    47: {"type": "W", "date": "W", "completeness": "W"},   # Not applicable
    49: {"type": "W", "date": "W", "completeness": "W"},
    63: {"type": "W", "date": "C", "completeness": "W"},
    69: {"type": "C", "date": "C", "completeness": "NA"},

    # chemotherapy_start
    13: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},
    22: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},
    30: {"setting": "C", "date": "C", "regimen": "C", "intent": "W"},
    48: {"setting": "W", "date": "C", "regimen": "C", "intent": "W"},

    # chemotherapy_end
    12: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},
    27: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},
    35: {"setting": "C", "date": "C", "cycles": "C", "reason": "C"},
    53: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},

    # radiotherapy_start
    23: {"setting": "W", "intent": "W", "hospital": "W", "date": "C"},
    32: {"setting": "C", "intent": "W", "hospital": "C", "date": "C"},  # IMPROVED: type and date now right
    50: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    57: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},

    # radiotherapy_end
    25: {"setting": "W", "dose": "C", "fractions": "W", "date": "C", "reason": "W"},
    34: {"setting": "C", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},
    58: {"setting": "C", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},

    # tumorbiopsytype
    1:  {"biopsy_type": "C", "date": "C", "institution": "C"},
    59: {"biopsy_type": "C", "date": "C", "institution": "C"},

    # recurrencetype
    14: {"type": "NA", "site_detail": "NA"},   # empty pred = abstention
    24: {"type": "W", "site_detail": "W"},
    33: {"type": "C", "site_detail": "W"},
    51: {"type": "W", "site_detail": "W"},

    # recur_or_prog
    16: {"event_type": "W", "date": "W"},
    19: {"event_type": "W", "date": "W"},
    28: {"event_type": "W", "date": "W"},
    36: {"event_type": "C", "date": "C"},  # IMPROVED — both fields now right (partial date acceptable)
    54: {"event_type": "W", "date": "W"},

    # data-issue rows
    10: {"setting": "D"},
    29: {"value": "D"},
    55: {"value": "D"},
    64: {"setting": "D"},
}


PIPE_4B: dict[int, dict[str, str]] = {
    # single-value rows
    0:  {"value": "C"}, 2: {"value": "W"}, 3: {"value": "C"}, 4: {"value": "C"},
    5: {"value": "W"}, 7: {"value": "C"}, 8: {"value": "C"}, 9: {"value": "C"},
    11: {"value": "W"}, 15: {"value": "W"}, 17: {"value": "W"}, 21: {"value": "C"},
    26: {"value": "W"}, 29: {"value": "W"}, 30: {"value": "W"}, 39: {"value": "C"},
    40: {"value": "C"}, 41: {"value": "C"}, 42: {"value": "C"}, 43: {"value": "C"},
    44: {"value": "C"}, 45: {"value": "C"}, 46: {"value": "C"}, 47: {"value": "C"},
    48: {"value": "C"}, 54: {"value": "W"}, 58: {"value": "C"}, 62: {"value": "W"},
    63: {"value": "W"}, 64: {"value": "C"}, 67: {"value": "W"}, 68: {"value": "C"},
    69: {"value": "C"}, 70: {"value": "W"}, 72: {"value": "C"}, 73: {"value": "C"},
    74: {"value": "W"}, 75: {"value": "W"},
    # multi-field
    1:  {"biopsy_type": "W", "date": "W", "institution": "W"},
    61: {"biopsy_type": "W", "date": "NA", "institution": "NA"},
    # surgerytype-fs30
    6:  {"type": "C", "date": "C", "completeness": "W"},
    18: {"type": "C", "date": "W", "completeness": "W"},
    20: {"type": "C", "date": "W", "completeness": "W"},
    33: {"type": "W", "date": "W", "completeness": "W"},
    49: {"type": "C", "date": "W", "completeness": "W"},
    51: {"type": "C", "date": "W", "completeness": "W"},
    65: {"type": "C", "date": "C", "completeness": "W"},
    71: {"type": "C", "date": "C", "completeness": "C"},
    # chemo_start
    13: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    22: {"setting": "C", "date": "W", "regimen": "W", "intent": "W"},
    32: {"setting": "C", "date": "C", "regimen": "C", "intent": "W"},
    50: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    # chemo_end
    12: {"setting": "W", "date": "W", "cycles": "C", "reason": "C"},
    27: {"setting": "W", "date": "W", "cycles": "C", "reason": "C"},
    37: {"setting": "C", "date": "C", "cycles": "C", "reason": "C"},
    55: {"setting": "W", "date": "W", "cycles": "NA", "reason": "W"},
    # RT_start
    23: {"setting": "W", "intent": "W", "hospital": "W", "date": "C"},
    34: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    52: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    59: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    66: {"setting": "D"},
    # RT_end
    25: {"setting": "W", "dose": "C", "fractions": "W", "date": "W", "reason": "W"},
    36: {"setting": "C", "dose": "C", "fractions": "C", "date": "W", "reason": "W"},
    60: {"setting": "C", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},
    # reexcision
    31: {"date": "W", "completeness": "W"},
    # recurrencetype
    14: {"type": "C", "site_detail": "W"},
    24: {"type": "W", "site_detail": "W"},
    35: {"type": "C", "site_detail": "W"},
    53: {"type": "C", "site_detail": "NA"},
    # recur_or_prog
    16: {"event_type": "W", "date": "W"},
    19: {"event_type": "W", "date": "W"},
    28: {"event_type": "C", "date": "W"},
    38: {"event_type": "C", "date": "W"},
    56: {"event_type": "W", "date": "W"},
    # data issue
    10: {"setting": "D"},
    57: {"value": "D"},
}


PDF_SESS: dict[int, dict[str, str]] = {
    # Single-value rows (PDF session, zero-shot)
    0: {"value": "W"}, 2: {"value": "W"}, 3: {"value": "W"}, 4: {"value": "W"},
    5: {"value": "W"}, 7: {"value": "C"}, 8: {"value": "C"}, 9: {"value": "C"},
    11: {"value": "W"}, 15: {"value": "W"}, 17: {"value": "C"}, 21: {"value": "C"},
    26: {"value": "W"}, 29: {"value": "D"}, 37: {"value": "C"}, 38: {"value": "C"},
    39: {"value": "W"}, 40: {"value": "W"}, 41: {"value": "C"}, 42: {"value": "C"},
    43: {"value": "C"}, 44: {"value": "C"}, 45: {"value": "W"}, 46: {"value": "C"},
    52: {"value": "W"}, 55: {"value": "D"}, 56: {"value": "C"}, 60: {"value": "W"},
    61: {"value": "W"}, 62: {"value": "W"}, 65: {"value": "W"}, 66: {"value": "W"},
    67: {"value": "W"}, 68: {"value": "W"}, 70: {"value": "W"}, 71: {"value": "C"},
    72: {"value": "C"},
    # multi-field
    # tumorbiopsytype
    1:  {"biopsy_type": "NA", "date": "C", "institution": "C"},
    59: {"biopsy_type": "W", "date": "NA", "institution": "C"},
    # surgerytype-fs30
    6:  {"type": "C", "date": "C", "completeness": "C"},
    18: {"type": "C", "date": "W", "completeness": "C"},
    20: {"type": "C", "date": "W", "completeness": "C"},
    31: {"type": "C", "date": "W", "completeness": "C"},
    47: {"type": "C", "date": "W", "completeness": "C"},
    49: {"type": "C", "date": "W", "completeness": "C"},
    63: {"type": "C", "date": "W", "completeness": "C"},
    69: {"type": "C", "date": "W", "completeness": "NA"},
    # chemo_start
    13: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    22: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    30: {"setting": "W", "date": "W", "regimen": "C", "intent": "W"},
    48: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    # chemo_end
    12: {"setting": "W", "date": "W", "cycles": "C", "reason": "C"},
    27: {"setting": "W", "date": "W", "cycles": "C", "reason": "W"},
    35: {"setting": "C", "date": "W", "cycles": "C", "reason": "W"},
    53: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},
    # RT_start
    23: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    32: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    50: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    57: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    # RT_end
    25: {"setting": "W", "dose": "C", "fractions": "W", "date": "C", "reason": "W"},
    34: {"setting": "W", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},
    58: {"setting": "W", "dose": "C", "fractions": "C", "date": "C", "reason": "W"},
    # recurrencetype
    14: {"type": "C", "site_detail": "W"},
    24: {"type": "W", "site_detail": "W"},
    33: {"type": "C", "site_detail": "W"},
    51: {"type": "W", "site_detail": "NA"},
    # recur_or_prog
    16: {"event_type": "W", "date": "W"},
    19: {"event_type": "C", "date": "W"},
    28: {"event_type": "W", "date": "W"},
    36: {"event_type": "W", "date": "W"},
    54: {"event_type": "W", "date": "W"},
    # data issues
    10: {"setting": "D"},
    64: {"setting": "D"},
}


BACK_4B: dict[int, dict[str, str]] = {
    # single-value rows
    0: {"value": "W"}, 2: {"value": "C"}, 3: {"value": "C"}, 4: {"value": "C"},
    5: {"value": "W"}, 7: {"value": "C"}, 8: {"value": "C"}, 9: {"value": "C"},
    11: {"value": "W"}, 15: {"value": "W"}, 17: {"value": "W"}, 21: {"value": "W"},
    26: {"value": "W"}, 29: {"value": "D"}, 37: {"value": "C"}, 38: {"value": "W"},
    39: {"value": "C"}, 40: {"value": "C"}, 41: {"value": "C"}, 42: {"value": "C"},
    43: {"value": "C"}, 44: {"value": "W"}, 45: {"value": "C"}, 46: {"value": "C"},
    52: {"value": "W"}, 55: {"value": "D"}, 56: {"value": "C"}, 60: {"value": "W"},
    61: {"value": "C"}, 62: {"value": "C"}, 65: {"value": "W"}, 66: {"value": "W"},
    67: {"value": "C"}, 68: {"value": "C"}, 70: {"value": "C"}, 71: {"value": "C"},
    72: {"value": "C"},
    # multi-field
    1:  {"biopsy_type": "NA", "date": "C", "institution": "C"},
    59: {"biopsy_type": "C", "date": "C", "institution": "C"},
    # surgerytype-fs30
    6:  {"type": "W", "date": "C", "completeness": "C"},
    18: {"type": "W", "date": "W", "completeness": "C"},
    20: {"type": "W", "date": "W", "completeness": "C"},
    31: {"type": "W", "date": "W", "completeness": "W"},
    47: {"type": "W", "date": "W", "completeness": "W"},
    49: {"type": "W", "date": "W", "completeness": "C"},
    63: {"type": "W", "date": "W", "completeness": "C"},
    69: {"type": "W", "date": "C", "completeness": "NA"},
    # chemo_start
    13: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    22: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    30: {"setting": "C", "date": "W", "regimen": "W", "intent": "W"},
    48: {"setting": "W", "date": "W", "regimen": "W", "intent": "W"},
    # chemo_end
    12: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},
    27: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},
    35: {"setting": "C", "date": "C", "cycles": "C", "reason": "C"},
    53: {"setting": "W", "date": "W", "cycles": "W", "reason": "W"},
    # RT_start
    23: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    32: {"setting": "C", "intent": "W", "hospital": "W", "date": "W"},
    50: {"setting": "W", "intent": "W", "hospital": "W", "date": "W"},
    57: {"setting": "C", "intent": "W", "hospital": "C", "date": "W"},
    # RT_end
    25: {"setting": "W", "dose": "W", "fractions": "W", "date": "W", "reason": "W"},
    34: {"setting": "W", "dose": "C", "fractions": "C", "date": "W", "reason": "W"},
    58: {"setting": "C", "dose": "C", "fractions": "C", "date": "W", "reason": "W"},
    # recurrencetype
    14: {"type": "C", "site_detail": "W"},
    24: {"type": "W", "site_detail": "W"},
    33: {"type": "C", "site_detail": "W"},
    51: {"type": "C", "site_detail": "NA"},
    # recur_or_prog
    16: {"event_type": "W", "date": "W"},
    19: {"event_type": "W", "date": "W"},
    28: {"event_type": "W", "date": "W"},
    36: {"event_type": "C", "date": "W"},
    54: {"event_type": "W", "date": "W"},
    # data issues
    10: {"setting": "D"},
    64: {"setting": "D"},
}


def main() -> None:
    pipe_pairs = pd.read_csv(ARTIFACTS_DIR / "judge_verdicts.csv")
    back_pairs = pd.read_csv(ARTIFACTS_DIR / "judge_verdicts_backend.csv")
    back_pairs_v2 = pd.read_csv(ARTIFACTS_DIR / "judge_verdicts_backend_v2.csv")
    pipe_4B = pd.read_csv(ARTIFACTS_DIR / "judge_verdicts_4B_pipeline.csv")
    back_4B = pd.read_csv(ARTIFACTS_DIR / "judge_verdicts_4B_backend.csv")
    pdf_sess = pd.read_csv(ARTIFACTS_DIR / "judge_verdicts_pdf_session.csv")

    pipe_prompts = dict(zip(pipe_pairs["idx"], pipe_pairs["prompt_type"]))
    back_prompts = dict(zip(back_pairs["idx"], back_pairs["prompt_type"]))
    back_v2_prompts = dict(zip(back_pairs_v2["idx"], back_pairs_v2["prompt_type"]))
    pipe_4B_prompts = dict(zip(pipe_4B["idx"], pipe_4B["prompt_type"]))
    back_4B_prompts = dict(zip(back_4B["idx"], back_4B["prompt_type"]))
    pdf_sess_prompts = dict(zip(pdf_sess["idx"], pdf_sess["prompt_type"]))

    pipe_agg = aggregate(PIPE, pipe_prompts)
    back_agg = aggregate(BACK, back_prompts)
    back_v2_agg = aggregate(BACK_V2, back_v2_prompts)
    pipe_4B_agg = aggregate(PIPE_4B, pipe_4B_prompts)
    back_4B_agg = aggregate(BACK_4B, back_4B_prompts)
    pdf_sess_agg = aggregate(PDF_SESS, pdf_sess_prompts)

    # Build comparison table
    rows = []
    seen_keys = set(pipe_agg.keys()) | set(back_agg.keys())
    for prompt_key in sorted(seen_keys):
        pipe_sub = pipe_agg.get(prompt_key, {})
        back_sub = back_agg.get(prompt_key, {})
        for sf in sorted(set(pipe_sub.keys()) | set(back_sub.keys())):
            pdf_key = (prompt_key, sf)
            pdf_num, pdf_den = PDF_SUBFIELD.get(pdf_key, (None, None))
            p_c, p_t = pipe_sub.get(sf, [0, 0])
            b_c, b_t = back_sub.get(sf, [0, 0])
            b2_c, b2_t = back_v2_agg.get(prompt_key, {}).get(sf, [0, 0])
            p4_c, p4_t = pipe_4B_agg.get(prompt_key, {}).get(sf, [0, 0])
            b4_c, b4_t = back_4B_agg.get(prompt_key, {}).get(sf, [0, 0])
            sess_c, sess_t = pdf_sess_agg.get(prompt_key, {}).get(sf, [0, 0])
            rows.append({
                "prompt":       prompt_key,
                "sub_field":    sf,
                "PDF_num":      pdf_num,
                "PDF_den":      pdf_den,
                "PDF_pct":      round(pdf_num / pdf_den * 100, 1) if pdf_num is not None else None,
                "pipe_num":     p_c,
                "pipe_den":     p_t,
                "pipe_pct":     round(p_c / p_t * 100, 1) if p_t else None,
                "back_num":     b_c,
                "back_den":     b_t,
                "back_pct":     round(b_c / b_t * 100, 1) if b_t else None,
                "back_v2_num":  b2_c,
                "back_v2_den":  b2_t,
                "back_v2_pct":  round(b2_c / b2_t * 100, 1) if b2_t else None,
                "pipe_4B_num":  p4_c,
                "pipe_4B_den":  p4_t,
                "pipe_4B_pct":  round(p4_c / p4_t * 100, 1) if p4_t else None,
                "back_4B_num":  b4_c,
                "back_4B_den":  b4_t,
                "back_4B_pct":  round(b4_c / b4_t * 100, 1) if b4_t else None,
                "pdf_sess_num": sess_c,
                "pdf_sess_den": sess_t,
                "pdf_sess_pct": round(sess_c / sess_t * 100, 1) if sess_t else None,
            })

    df = pd.DataFrame(rows)
    df.to_csv(ARTIFACTS_DIR / "comparison_per_subfield.csv", index=False)
    print(f"[wrote] {ARTIFACTS_DIR / 'comparison_per_subfield.csv'}")
    print()

    # Print markdown table grouped by prompt
    for prompt_key in sorted(set(df["prompt"])):
        chunk = df[df["prompt"] == prompt_key]
        if chunk.empty:
            continue
        # Skip single-value prompts (whole-row score = sub-field "value")
        if list(chunk["sub_field"]) == ["value"]:
            r = chunk.iloc[0]
            print(f"**{prompt_key}** (single-value):  "
                  f"pipeline {r['pipe_num']}/{r['pipe_den']} ({r['pipe_pct']}%)  |  "
                  f"backend {r['back_num']}/{r['back_den']} ({r['back_pct']}%)")
            continue

        print(f"### {prompt_key}")
        print()
        print("| sub-field | PDF (7B) | 27B pipeline | 27B backend |")
        print("|---|---|---|---|")
        for _, r in chunk.iterrows():
            pdf = "—" if r["PDF_num"] is None else f'{r["PDF_num"]}/{r["PDF_den"]} ({r["PDF_pct"]}%)'
            pipe = f'{r["pipe_num"]}/{r["pipe_den"]} ({r["pipe_pct"]}%)' if r["pipe_den"] else "—"
            back = f'{r["back_num"]}/{r["back_den"]} ({r["back_pct"]}%)' if r["back_den"] else "—"
            print(f'| {r["sub_field"]} | {pdf} | {pipe} | {back} |')
        print()


if __name__ == "__main__":
    main()
