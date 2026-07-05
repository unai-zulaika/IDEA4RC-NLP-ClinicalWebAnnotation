"""
Regression tests for absence handling in the normalized-table export.

The prompt-improvement work standardizes every prompt's abstention output on
"Not applicable" and, as defense-in-depth, broadens the export's absence
classifier so that any abstention phrasing a small LLM might emit (English or
Italian) is dropped from the normalized table rather than leaking in as data.

Two guarantees are tested:
  1. Every abstention/missing form is classified as absence and excluded.
  2. Real clinical values -- including legitimate negatives like "nessun
     residuo" / "R0" for margins -- are NOT dropped.

Run with:
    cd backend && python -m pytest test_export_absence.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from routes.sessions import _classify_absence, _build_export_rows  # noqa: E402


# --- abstention / missing forms that MUST be dropped on export ----------------
ABSENCE_VALUES = [
    "",
    "Not applicable",
    "not applicable",
    "N/A",
    "n/a",
    "n.a.",
    "Unknown",
    "unknown biopsy grading",
    "Not stated",
    "Not provided",
    "Not documented",
    "Not reported",
    "Not indicated",
    "Not evaluable",
    "Not assessable",
    "Not specified",
    "Not mentioned",
    "Not available",
    "Information not available in the note",
    "No information",
    # Italian phrasings (INT-SARC / INT-HNC notes are Italian)
    "non disponibile",
    "non specificato",
    "non valutabile",
    "non riportato",
    "non riferito",
    "non indicato",
    "non noto",
    "non documentato",
    "non applicabile",
    # Italian abbreviations / bare unknowns that a small model emits
    "n.d.",         # non disponibile — the everyday Italian abbreviation
    "n/d",
    "nd",
    "sconosciuto",
    "sconosciuta",
    "ignoto",
    # placeholder leaks
    "[biopsy type]",
    "[select value]",
    # full-line abstention forms emitted by the rewritten pilot prompts
    "Age at diagnosis: Not applicable.",
    "Biopsy grading (FNCLCC): Not applicable.",
    "Surgical specimen grading (FNCLCC): Not applicable.",
    # "<label> unknown." abstentions (batch 2): trailing 'unknown' must be dropped
    "Tumor longest diameter unknown.",
    "Tumor longest diameter unknown",
    "Tumor category unknown.",
    "Tumor category unknown",
]


# --- real values that MUST be preserved (never treated as absence) ------------
REAL_VALUES = [
    "1",
    "2",
    "3",
    "62",
    "65 years",
    "male",
    "female",
    "Other classification system high",
    "Other classification system low",
    "Liposarcoma (8850/3)",
    "Retroperitoneum (C48.0)",
    # legitimate clinical negatives that are REAL data, not abstentions:
    "R0",                 # clean surgical margins
    "nessun residuo",     # "no residual" -> R0, a real margin finding
    "negativo",           # a real negative result
    "assenza di necrosi", # descriptive, still a real finding
    "assente",            # bare "absent" is a real necrosis finding
    # "sconosciuta" is a bare-word absence, BUT inside a real phrase it is a
    # legitimate finding (carcinoma of unknown primary) and must be preserved:
    "sede primitiva sconosciuta",
    # "unknown" NOT at the end is a real finding (CUP), must survive the
    # trailing-unknown export guard added for "<label> unknown." abstentions:
    "carcinoma of unknown primary",
]


def test_absence_values_classified_as_absence():
    for v in ABSENCE_VALUES:
        reason = _classify_absence(v)
        assert reason, f"expected {v!r} to be classified as absence, got empty reason"


def test_real_values_not_classified_as_absence():
    for v in REAL_VALUES:
        reason = _classify_absence(v)
        assert reason == "", f"expected {v!r} to be kept, but was dropped as absence: {reason!r}"


def test_pilot_prompt_abstention_full_lines_dropped():
    """The exact abstention lines produced by the rewritten pilot prompts."""
    for line in (
        "Age at diagnosis: Not applicable.",
        "Biopsy grading (FNCLCC): Not applicable.",
        "Annotation: Surgical specimen grading (FNCLCC): Not applicable.",
    ):
        assert _classify_absence(line), f"abstention line not dropped: {line!r}"


# --- end-to-end through _build_export_rows -----------------------------------
def _session():
    notes = [
        {"note_id": "n1", "p_id": "P1", "date": "10/01/2020"},
        {"note_id": "n2", "p_id": "P2", "date": "11/01/2020"},
    ]
    annotations = {
        # P1: real values -> kept
        "n1": {
            "ageatdiagnosis-int-sarc": {"annotation_text": "Age at diagnosis 62 years."},
            "biopsygrading-int-sarc": {"annotation_text": "Biopsy grading (FNCLCC): 3."},
        },
        # P2: abstentions -> excluded from the normalized table
        "n2": {
            "ageatdiagnosis-int-sarc": {"annotation_text": "Age at diagnosis: Not applicable."},
            "biopsygrading-int-sarc": {"annotation_text": "Biopsy grading (FNCLCC): Not applicable."},
        },
    }
    return {"notes": notes, "annotations": annotations}


def test_build_export_rows_drops_abstentions_keeps_values():
    rows, excluded = _build_export_rows(_session())

    kept = {(r["patient_id"], r["_prompt_type"]) for r in rows}
    dropped = {(e["patient_id"], e["prompt_type"]) for e in excluded}

    # P1's real values survive to the normalized table
    assert ("P1", "ageatdiagnosis-int-sarc") in kept
    assert ("P1", "biopsygrading-int-sarc") in kept

    # P2's abstentions are excluded (missing values ignored, never exported)
    assert ("P2", "ageatdiagnosis-int-sarc") in dropped
    assert ("P2", "biopsygrading-int-sarc") in dropped
    assert ("P2", "ageatdiagnosis-int-sarc") not in kept
    assert ("P2", "biopsygrading-int-sarc") not in kept

    # And no abstention value ever appears in an exported row's value
    for r in rows:
        assert _classify_absence(r["value"]) == "", f"absence value leaked into export: {r['value']!r}"


def test_age_value_line_exports_clean_integer():
    """A stated age exports as the integer, and the abstention line is dropped."""
    from routes.sessions import _extract_value_from_annotation

    val = _extract_value_from_annotation("Age at diagnosis 62 years.", "ageatdiagnosis")
    assert val == "62", f"expected clean integer '62', got {val!r}"
    assert _classify_absence(val) == ""  # a real age is never dropped

    absent = _extract_value_from_annotation("Age at diagnosis: Not applicable.", "ageatdiagnosis")
    assert _classify_absence(absent), "age abstention must still be dropped"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
