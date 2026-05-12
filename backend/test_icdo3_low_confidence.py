"""
Tests for the low-confidence flag on ICD-O-3 auto-selection.

Background: when the LLM's diagnosis text (e.g., "kidney cancer") doesn't
have a strong match in the SARC/HNC CSV, `find_top_candidates` falls back to
text-only fuzzy matching that scores 0.3-0.6. Before the fix, the system
unconditionally auto-selected `candidates[0]` regardless of score, producing
a confidently-wrong ICD-O-3 code. The fix flags any pick below
LOW_CONFIDENCE_THRESHOLD so the diagnosis resolver and the UI can treat it
as "needs review" instead of accepting the bad code.

Run with:
    cd backend && .venv/bin/python -m pytest test_icdo3_low_confidence.py -v
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from lib import icdo3_extractor  # noqa: E402
from services.diagnosis_resolver import _extract_code_from_annotation  # noqa: E402


# Threshold used by the SUT — pulled in so the test is decoupled from the
# specific numeric value but still asserts behavior right around the boundary.
THRESHOLD = icdo3_extractor.LOW_CONFIDENCE_THRESHOLD


def _csv_row(query="8120/3-C64.9", morph="8120/3", topo="C64.9",
             name="Transitional cell carcinoma, NOS"):
    """Shape of a row returned by the CSV indexer."""
    return {
        "Query": query,
        "Morphology": morph,
        "Topography": topo,
        "NAME": name,
        "ID": "12345",
    }


@pytest.fixture
def mock_csv_indexer():
    """Patch get_csv_indexer + the LLM extractor so we control the score."""
    mock_indexer = MagicMock()
    mock_indexer.find_top_candidates = MagicMock()
    # Both helpers are imported lazily inside the SUT, so patch at their
    # actual source modules.
    with patch("lib.icdo3_llm_extractor.extract_histology_topography_with_llm",
               return_value={
                   "histology_text": "kidney cancer",
                   "topography_text": "kidney",
                   "morphology_code": None,
                   "topography_code": None,
                   "query_code": None,
               }), \
         patch("lib.icdo3_csv_indexer.get_csv_indexer", return_value=mock_indexer):
        yield mock_indexer


class TestLowConfidenceFlag:
    """The low_confidence flag fires only below the threshold."""

    def test_high_confidence_match_not_flagged(self, mock_csv_indexer):
        # Exact query code match → score 1.0 → should NOT be flagged
        mock_csv_indexer.find_top_candidates.return_value = [
            (_csv_row(), 1.0, "exact"),
        ]
        result = icdo3_extractor._extract_with_llm_and_csv_match(
            text="Tumour site: kidney",
            prompt_type="tumorsite-int-sarc",
            note_text="History of kidney cancer.",
            vllm_client=MagicMock(),
        )
        assert result is not None
        assert result["low_confidence"] is False
        assert result["confidence"] == 1.0

    def test_combined_morph_topo_not_flagged(self, mock_csv_indexer):
        # Combined match scores 0.9 — clearly above any reasonable threshold
        mock_csv_indexer.find_top_candidates.return_value = [
            (_csv_row(), 0.9, "combined"),
        ]
        result = icdo3_extractor._extract_with_llm_and_csv_match(
            text="x", prompt_type="tumorsite-int-sarc",
            note_text="x", vllm_client=MagicMock(),
        )
        assert result["low_confidence"] is False

    def test_text_only_match_is_flagged(self, mock_csv_indexer):
        # Text-only matches cap at 0.6 — exactly the kidney-cancer scenario
        mock_csv_indexer.find_top_candidates.return_value = [
            (_csv_row(name="Soft tissue, NOS"), 0.55, "text"),
            (_csv_row(query="9120/3-C49.9", name="Hemangiosarcoma"), 0.45, "text"),
        ]
        result = icdo3_extractor._extract_with_llm_and_csv_match(
            text="Tumour site: kidney",
            prompt_type="tumorsite-int-sarc",
            note_text="History of kidney cancer.",
            vllm_client=MagicMock(),
        )
        assert result["low_confidence"] is True
        # The candidates list is still returned for user review
        assert len(result["candidates"]) == 2

    def test_topography_only_match_is_flagged(self, mock_csv_indexer):
        # Topography-only matches score 0.5-0.65 — below the 0.7 threshold
        mock_csv_indexer.find_top_candidates.return_value = [
            (_csv_row(), 0.6, "topography"),
        ]
        result = icdo3_extractor._extract_with_llm_and_csv_match(
            text="x", prompt_type="tumorsite-int-sarc",
            note_text="x", vllm_client=MagicMock(),
        )
        assert result["low_confidence"] is True

    def test_boundary_at_threshold_not_flagged(self, mock_csv_indexer):
        # Score equal to threshold is accepted (strict less-than)
        mock_csv_indexer.find_top_candidates.return_value = [
            (_csv_row(), THRESHOLD, "morphology"),
        ]
        result = icdo3_extractor._extract_with_llm_and_csv_match(
            text="x", prompt_type="tumorsite-int-sarc",
            note_text="x", vllm_client=MagicMock(),
        )
        assert result["low_confidence"] is False

    def test_just_below_threshold_is_flagged(self, mock_csv_indexer):
        eps_below = THRESHOLD - 0.01
        mock_csv_indexer.find_top_candidates.return_value = [
            (_csv_row(), eps_below, "morphology"),
        ]
        result = icdo3_extractor._extract_with_llm_and_csv_match(
            text="x", prompt_type="tumorsite-int-sarc",
            note_text="x", vllm_client=MagicMock(),
        )
        assert result["low_confidence"] is True


class TestDiagnosisResolverIgnoresLowConfidence:
    """The diagnosis resolver must not fall back to a low-confidence code."""

    def test_high_confidence_icdo3_used_when_text_has_no_code(self):
        ann = {
            "annotation_text": "Patient diagnosed with renal cell carcinoma.",
            "icdo3_code": {
                "morphology_code": "8312/3",
                "low_confidence": False,
            },
        }
        # The annotation text has no embedded morphology code, so the resolver
        # falls back to icdo3_code. Confidence is high, so the fallback is used.
        assert _extract_code_from_annotation(ann, "histology") == "8312/3"

    def test_low_confidence_icdo3_not_used_as_fallback(self):
        ann = {
            "annotation_text": "Patient diagnosed with renal cell carcinoma.",
            "icdo3_code": {
                # The kidney bug: a wrong code was force-picked from candidates
                "morphology_code": "8805/3",  # Sarcoma — wrong for kidney
                "low_confidence": True,
            },
        }
        # Resolver returns None → patient diagnosis ends up as needs_review
        # rather than auto-resolving to the wrong sarcoma code.
        assert _extract_code_from_annotation(ann, "histology") is None

    def test_regex_in_text_still_wins_over_low_confidence_icdo3(self):
        # If the annotation text itself contains a morphology code, that should
        # be used regardless of icdo3_code.low_confidence
        ann = {
            "annotation_text": "Histology: renal cell carcinoma (8312/3).",
            "icdo3_code": {
                "morphology_code": "8805/3",  # garbage from low-confidence pick
                "low_confidence": True,
            },
        }
        assert _extract_code_from_annotation(ann, "histology") == "8312/3"

    def test_missing_low_confidence_field_defaults_to_trusted(self):
        # Older session JSONs may not have low_confidence at all — those
        # predate the fix, so we keep the legacy "trust the code" behavior
        # rather than retroactively invalidating them.
        ann = {
            "annotation_text": "Patient diagnosed with renal cell carcinoma.",
            "icdo3_code": {
                "morphology_code": "8312/3",
                # no low_confidence field
            },
        }
        assert _extract_code_from_annotation(ann, "histology") == "8312/3"
