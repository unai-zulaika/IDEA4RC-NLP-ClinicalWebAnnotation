"""
Unit tests for duplicate text content detection and removal in the CSV upload route.

Tests cover:
  - _normalize_text helper directly
  - HTTP endpoint behaviour via TestClient

Run with:
    cd backend && .venv/bin/python -m pytest test_upload_duplicate_text.py -v
"""
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from main import app  # noqa: E402
from routes.upload import _normalize_text  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload(csv_content: str):
    """POST the CSV string to the upload endpoint and return the JSON response."""
    return client.post(
        "/api/upload/csv",
        files={"file": ("notes.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )


def _csv(*rows, header="text;date;p_id;note_id;report_type"):
    """Build a semicolon-delimited CSV string from a header and rows."""
    return header + "\n" + "\n".join(rows) + "\n"


# ---------------------------------------------------------------------------
# _normalize_text — unit tests
# ---------------------------------------------------------------------------

class TestNormalizeText:
    def test_strips_leading_trailing_whitespace(self):
        assert _normalize_text("  hello  ") == "hello"

    def test_collapses_internal_spaces(self):
        assert _normalize_text("hello   world") == "hello world"

    def test_collapses_newlines(self):
        assert _normalize_text("hello\nworld") == "hello world"

    def test_collapses_mixed_whitespace(self):
        assert _normalize_text("hello \t\n world") == "hello world"

    def test_lowercases(self):
        assert _normalize_text("PATIENT IS MALE") == "patient is male"

    def test_empty_string(self):
        assert _normalize_text("") == ""

    def test_whitespace_only(self):
        assert _normalize_text("   \n\t  ") == ""

    def test_identical_texts_produce_same_fingerprint(self):
        a = _normalize_text("Patient has brain tumour.")
        b = _normalize_text("  Patient  has  brain  tumour.  ")
        assert a == b

    def test_case_insensitive_same_fingerprint(self):
        assert _normalize_text("Note A") == _normalize_text("NOTE A")


# ---------------------------------------------------------------------------
# Upload endpoint — no duplicates
# ---------------------------------------------------------------------------

class TestNoDuplicates:
    def test_flag_is_false_when_all_text_unique(self):
        csv = _csv(
            "Note A;2024-01-01;P1;N001;CCE",
            "Note B;2024-01-01;P1;N002;CCE",
            "Note C;2024-01-01;P1;N003;CCE",
        )
        resp = _upload(csv)
        assert resp.status_code == 200
        data = resp.json()
        assert data["duplicate_text_detected"] is False
        assert data["duplicate_text_removed_count"] == 0
        assert data["duplicate_text_note_ids"] == []

    def test_row_count_unchanged_when_no_duplicates(self):
        csv = _csv(
            "Note A;2024-01-01;P1;N001;CCE",
            "Note B;2024-01-01;P1;N002;CCE",
        )
        resp = _upload(csv)
        assert resp.json()["row_count"] == 2


# ---------------------------------------------------------------------------
# Upload endpoint — exact duplicate text
# ---------------------------------------------------------------------------

class TestExactDuplicateText:
    def test_second_row_with_same_text_is_removed(self):
        csv = _csv(
            "Same clinical note;2024-01-01;P1;N001;CCE",
            "Same clinical note;2024-01-02;P2;N002;CCE",
        )
        resp = _upload(csv)
        assert resp.status_code == 200
        data = resp.json()
        assert data["duplicate_text_detected"] is True
        assert data["duplicate_text_removed_count"] == 1
        assert "N002" in data["duplicate_text_note_ids"]

    def test_first_occurrence_is_kept(self):
        csv = _csv(
            "Repeated note;2024-01-01;P1;N001;CCE",
            "Repeated note;2024-01-02;P2;N002;CCE",
        )
        data = _upload(csv).json()
        remaining_ids = [r["note_id"] for r in data["all_rows"]]
        assert "N001" in remaining_ids
        assert "N002" not in remaining_ids

    def test_row_count_reflects_removal(self):
        csv = _csv(
            "Dup;2024-01-01;P1;N001;CCE",
            "Dup;2024-01-02;P2;N002;CCE",
            "Unique;2024-01-03;P3;N003;CCE",
        )
        data = _upload(csv).json()
        assert data["row_count"] == 2
        assert data["duplicate_text_removed_count"] == 1

    def test_triple_duplicate_removes_two(self):
        csv = _csv(
            "Same;2024-01-01;P1;N001;CCE",
            "Same;2024-01-02;P2;N002;CCE",
            "Same;2024-01-03;P3;N003;CCE",
        )
        data = _upload(csv).json()
        assert data["row_count"] == 1
        assert data["duplicate_text_removed_count"] == 2
        assert set(data["duplicate_text_note_ids"]) == {"N002", "N003"}

    def test_all_rows_reflects_removal(self):
        csv = _csv(
            "Dup text;2024-01-01;P1;N001;CCE",
            "Dup text;2024-01-02;P2;N002;CCE",
        )
        data = _upload(csv).json()
        assert len(data["all_rows"]) == 1
        assert data["all_rows"][0]["note_id"] == "N001"

    def test_preview_reflects_removal(self):
        csv = _csv(
            "Note dup;2024-01-01;P1;N001;CCE",
            "Note dup;2024-01-02;P2;N002;CCE",
        )
        data = _upload(csv).json()
        preview_ids = [r["note_id"] for r in data["preview"]]
        assert "N001" in preview_ids
        assert "N002" not in preview_ids

    def test_message_mentions_removal(self):
        csv = _csv(
            "Dup;2024-01-01;P1;N001;CCE",
            "Dup;2024-01-02;P2;N002;CCE",
        )
        data = _upload(csv).json()
        assert "duplicate text" in data["message"].lower()


# ---------------------------------------------------------------------------
# Upload endpoint — normalization-based duplicates
# ---------------------------------------------------------------------------

class TestNormalizationDuplicates:
    def test_case_insensitive_detected_as_duplicate(self):
        csv = _csv(
            "Patient is male;2024-01-01;P1;N001;CCE",
            "PATIENT IS MALE;2024-01-02;P2;N002;CCE",
        )
        data = _upload(csv).json()
        assert data["duplicate_text_detected"] is True
        assert data["duplicate_text_removed_count"] == 1

    def test_extra_internal_spaces_detected_as_duplicate(self):
        csv = _csv(
            "Patient  is  male;2024-01-01;P1;N001;CCE",
            "Patient is male;2024-01-02;P2;N002;CCE",
        )
        data = _upload(csv).json()
        assert data["duplicate_text_detected"] is True

    def test_leading_trailing_whitespace_detected_as_duplicate(self):
        csv = _csv(
            "  Note text  ;2024-01-01;P1;N001;CCE",
            "Note text;2024-01-02;P2;N002;CCE",
        )
        data = _upload(csv).json()
        assert data["duplicate_text_detected"] is True


# ---------------------------------------------------------------------------
# Upload endpoint — interaction with note_id deduplication
# ---------------------------------------------------------------------------

class TestInteractionWithNoteIdDedup:
    def test_both_dedup_flags_can_be_true_simultaneously(self):
        """Duplicate note_ids AND duplicate text: both flags raised independently."""
        csv = _csv(
            "Same note;2024-01-01;P1;N001;CCE",
            "Same note;2024-01-02;P2;N001;CCE",  # same note_id AND same text
        )
        data = _upload(csv).json()
        assert data["duplicate_note_ids_detected"] is True
        assert data["duplicate_text_detected"] is True

    def test_note_id_dedup_runs_before_text_dedup(self):
        """Removed note_id in duplicate_text_note_ids is the *renamed* version."""
        csv = _csv(
            "Same text;2024-01-01;P1;N001;CCE",
            "Same text;2024-01-02;P2;N001;CCE",  # same note_id → renamed to N001_1
        )
        data = _upload(csv).json()
        # After note_id dedup: rows are N001_0 and N001_1
        # After text dedup: N001_1 is removed
        assert any("N001" in nid for nid in data["duplicate_text_note_ids"])


# ---------------------------------------------------------------------------
# Upload endpoint — three-row sample CSV (the manual test case)
# ---------------------------------------------------------------------------

class TestThreeRowSampleCSV:
    """End-to-end check with the sample CSV file created alongside these tests."""

    def test_sample_csv_duplicate_detected(self):
        # Row 1 and Row 3 have the same text; Row 2 is unique.
        csv = _csv(
            "Patient presents with glioblastoma multiforme grade IV.;2024-03-01;P101;NOTE001;CCE",
            "Biopsy confirms adenocarcinoma of the lung, stage IIIB.;2024-03-02;P102;NOTE002;Pathology",
            "Patient presents with glioblastoma multiforme grade IV.;2024-03-03;P103;NOTE003;CCE",
        )
        resp = _upload(csv)
        assert resp.status_code == 200
        data = resp.json()

        assert data["row_count"] == 2
        assert data["duplicate_text_detected"] is True
        assert data["duplicate_text_removed_count"] == 1
        assert data["duplicate_text_note_ids"] == ["NOTE003"]

        remaining_ids = [r["note_id"] for r in data["all_rows"]]
        assert "NOTE001" in remaining_ids
        assert "NOTE002" in remaining_ids
        assert "NOTE003" not in remaining_ids
