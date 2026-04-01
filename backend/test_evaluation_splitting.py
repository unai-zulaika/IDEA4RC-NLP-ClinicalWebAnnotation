"""Evaluation tests for history note splitting on real session data.

These tests validate detection accuracy and structural correctness
using real clinical notes from sessions. No LLM required.
"""

import json
import pytest
from pathlib import Path

from lib.history_detector import HistoryNoteDetector
from lib.result_aggregator import aggregate_results, _is_null_result
from models.schemas import AnnotationResult, AnnotationValue


SESSIONS_DIR = Path(__file__).parent / "sessions"
CARDINALITY_FILE = Path(__file__).parent / "data" / "entities_cardinality.json"


def _load_session(session_id: str) -> dict:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        pytest.skip(f"Session {session_id} not found")
    with open(path) as f:
        return json.load(f)


def _load_cardinality() -> dict:
    with open(CARDINALITY_FILE) as f:
        return json.load(f)


def _get_all_sessions() -> list[dict]:
    sessions = []
    for path in SESSIONS_DIR.glob("*.json"):
        with open(path) as f:
            sessions.append(json.load(f))
    return sessions


@pytest.fixture
def detector():
    return HistoryNoteDetector()


@pytest.fixture
def cardinality():
    return _load_cardinality()


# --- Detection on real session data ---


class TestDetectionOnSessions:
    """Validate detection accuracy on real clinical notes from sessions."""

    def test_detection_produces_results_for_all_sessions(self, detector):
        """Every session should be processable without errors."""
        sessions = _get_all_sessions()
        assert len(sessions) > 0, "No sessions found"
        for session in sessions:
            notes = session.get("notes", [])
            for note in notes:
                text = note.get("text", "")
                rt = note.get("report_type", "")
                result = detector.get_detection_details(text, rt)
                assert "is_history" in result
                assert "confidence" in result
                assert 0.0 <= result["confidence"] <= 1.0

    def test_italian_session_has_history_notes(self, detector):
        """INT-SARC Italian sessions should contain detectable history notes."""
        session = _load_session("04779998-49d1-481c-9b57-6e29a3a51876")
        notes = session.get("notes", [])
        detected = 0
        for note in notes:
            result = detector.get_detection_details(
                note.get("text", ""), note.get("report_type", "")
            )
            if result["is_history"]:
                detected += 1
        # We know this session has history notes from prior testing
        assert detected >= 5, f"Expected >=5 history notes, got {detected}"

    def test_non_history_notes_outnumber_history(self, detector):
        """Most notes should NOT be history — avoid over-detection."""
        session = _load_session("04779998-49d1-481c-9b57-6e29a3a51876")
        notes = session.get("notes", [])
        detected = sum(
            1 for n in notes
            if detector.is_history_note(n.get("text", ""), n.get("report_type", ""))
        )
        assert detected < len(notes) * 0.6, (
            f"Too many history detections: {detected}/{len(notes)} "
            f"({100*detected/len(notes):.0f}%) — possible over-detection"
        )

    def test_high_confidence_notes_have_multiple_signals(self, detector):
        """Notes detected with high confidence should match on multiple criteria."""
        session = _load_session("04779998-49d1-481c-9b57-6e29a3a51876")
        for note in session.get("notes", []):
            result = detector.get_detection_details(
                note.get("text", ""), note.get("report_type", "")
            )
            if result["confidence"] >= 0.8:
                assert len(result["detection_methods"]) >= 2, (
                    f"High-confidence detection with only {result['detection_methods']}"
                )

    def test_detection_summary_across_sessions(self, detector):
        """Print a detection summary for manual review (always passes)."""
        sessions = _get_all_sessions()
        print("\n=== Detection Summary ===")
        for session in sessions:
            sid = session.get("session_id", "unknown")[:8]
            center = session.get("center", "?")
            notes = session.get("notes", [])
            detected = 0
            for note in notes:
                r = detector.get_detection_details(
                    note.get("text", ""), note.get("report_type", "")
                )
                if r["is_history"]:
                    detected += 1
            print(f"  {sid}... ({center}): {detected}/{len(notes)} history notes")


# --- Aggregation with realistic data ---


class TestAggregationRealism:
    """Test aggregation behavior with patterns seen in real Italian notes."""

    def _make_result(self, text, status="success", prompt_type="surgerytype-int-sarc"):
        return AnnotationResult(
            prompt_type=prompt_type,
            annotation_text=text,
            values=[AnnotationValue(value=text, evidence_spans=[])],
            evidence_spans=[],
            reasoning=f"Extracted: {text}",
            status=status,
        )

    def test_italian_null_patterns_filtered(self):
        """Italian null patterns should be recognized."""
        assert _is_null_result("Not applicable") is True
        assert _is_null_result("Not mentioned") is True
        assert _is_null_result("Information not available") is True
        # Real values should not be filtered
        assert _is_null_result("intervento chirurgico di isteroannessectomia") is False

    def test_mixed_null_and_real_values(self):
        """When some sub-notes have no relevant info, only real values survive."""
        results = [
            self._make_result("Surgery performed on 06/03/2019: isteroannessectomia bilaterale"),
            self._make_result("Not applicable"),
            self._make_result("Surgery performed on 05/03/2020: asportazione della recidiva"),
            self._make_result("Not mentioned"),
        ]
        agg = aggregate_results(results, "surgerytype-int-sarc", total_events=4)
        assert len(agg.values) == 2
        assert agg.multi_value_info["unique_values_extracted"] == 2

    def test_italian_date_format_dedup(self):
        """Same surgery described with different date formats should dedup."""
        results = [
            self._make_result("Surgery on 06/03/2019"),
            self._make_result("Surgery on 06.03.2019"),
        ]
        agg = aggregate_results(results, "surgerytype-int-sarc", total_events=2)
        assert len(agg.values) == 1  # Same date, same text → dedup

    def test_different_events_preserved(self):
        """Genuinely different events should all be kept."""
        results = [
            self._make_result("isteroannessectomia bilaterale (06/2019)"),
            self._make_result("asportazione recidiva pelvica (03/2020)"),
            self._make_result("chemioterapia gemcitabina-dacarbazina (09/2019)"),
        ]
        agg = aggregate_results(results, "surgerytype-int-sarc", total_events=3)
        assert len(agg.values) == 3


# --- Export format validation ---


class TestExportMultiValue:
    """Test that multi-value annotation structure is correct for export."""

    def _make_result(self, text, status="success"):
        return AnnotationResult(
            prompt_type="surgerytype-int-sarc",
            annotation_text=text,
            values=[AnnotationValue(value=text, evidence_spans=[])],
            evidence_spans=[],
            reasoning=f"Extracted: {text}",
            status=status,
        )

    def test_aggregated_result_has_multi_value_info(self):
        results = [
            self._make_result("Surgery A on 01/01/2020"),
            self._make_result("Surgery B on 15/06/2021"),
        ]
        agg = aggregate_results(results, "surgerytype-int-sarc", total_events=2)
        assert agg.multi_value_info is not None
        assert agg.multi_value_info["was_split"] is True
        assert agg.multi_value_info["unique_values_extracted"] == 2
        assert agg.multi_value_info["split_method"] == "llm"

    def test_values_array_matches_unique_count(self):
        results = [
            self._make_result("Surgery A on 01/01/2020"),
            self._make_result("Surgery B on 15/06/2021"),
            self._make_result("Surgery A on 01/01/2020"),  # duplicate
        ]
        agg = aggregate_results(results, "surgerytype-int-sarc", total_events=3)
        assert len(agg.values) == agg.multi_value_info["unique_values_extracted"]

    def test_annotation_text_is_first_value(self):
        results = [
            self._make_result("Surgery on 15/06/2021"),
            self._make_result("Surgery on 01/01/2020"),  # earlier date
        ]
        agg = aggregate_results(results, "surgerytype-int-sarc", total_events=2)
        # After chronological sorting, earliest should be first
        assert agg.annotation_text == agg.values[0].value


# --- Cardinality correctness ---


class TestCardinalityMapping:
    """Verify entity cardinality is correctly used."""

    def test_repeatable_entities_are_cardinality_zero(self, cardinality):
        repeatable = ["Surgery", "SystemicTreatment", "Radiotherapy", "EpisodeEvent"]
        for entity in repeatable:
            assert cardinality.get(entity) == 0, f"{entity} should be cardinality 0"

    def test_non_repeatable_entities_are_cardinality_one(self, cardinality):
        non_repeatable = ["Patient", "Diagnosis", "ClinicalStage", "PathologicalStage"]
        for entity in non_repeatable:
            assert cardinality.get(entity) == 1, f"{entity} should be cardinality 1"
