"""
Tests for the GET /api/upload/fewshots/download endpoint.

Verifies:
  - CSV download with correct columns and data
  - 404 when no fewshots exist for a center
  - Center-based filtering (only requested center returned)
  - Center suffix stripped from prompt_type in output
  - Legacy "-int" suffix handled for INT-SARC

Run with:
    cd backend && .venv/bin/python -m pytest test_fewshot_download.py -v
"""
import csv
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from main import app  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_csv(content: str):
    """Parse CSV content string into list of dicts."""
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


SAMPLE_FEWSHOTS = {
    "gender-int-sarc": [
        ("Patient is a 65-year-old male.", "Patient's gender male."),
        ("She is a 42-year-old woman.", "Patient's gender female."),
    ],
    "ageatdiagnosis-int-sarc": [
        ("Patient is a 65-year-old male.", "Age at diagnosis 65 years."),
    ],
    "gender-msci": [
        ("Il paziente e' un uomo di 70 anni.", "Genere del paziente maschile."),
    ],
    "tumorsite-int": [
        ("Tumor found in the left kidney.", "Tumor site: kidney."),
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFewshotDownload:
    """Tests for GET /api/upload/fewshots/download."""

    @patch("routes.upload._load_fewshots_from_disk", return_value=SAMPLE_FEWSHOTS)
    def test_download_returns_csv_with_correct_columns(self, _mock):
        resp = client.get("/api/upload/fewshots/download", params={"center": "INT-SARC"})
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        rows = _parse_csv(resp.text)
        assert len(rows) > 0
        assert list(rows[0].keys()) == ["prompt_type", "note_text", "annotation"]

    @patch("routes.upload._load_fewshots_from_disk", return_value=SAMPLE_FEWSHOTS)
    def test_download_content_matches_stored_data(self, _mock):
        resp = client.get("/api/upload/fewshots/download", params={"center": "INT-SARC"})
        rows = _parse_csv(resp.text)
        # INT-SARC matches "-int-sarc" suffix (2 gender + 1 ageatdiagnosis) and legacy "-int" (1 tumorsite)
        assert len(rows) == 4
        prompt_types = {r["prompt_type"] for r in rows}
        assert "gender" in prompt_types
        assert "ageatdiagnosis" in prompt_types
        assert "tumorsite" in prompt_types

    @patch("routes.upload._load_fewshots_from_disk", return_value=SAMPLE_FEWSHOTS)
    def test_download_strips_center_suffix(self, _mock):
        resp = client.get("/api/upload/fewshots/download", params={"center": "INT-SARC"})
        rows = _parse_csv(resp.text)
        for row in rows:
            assert not row["prompt_type"].endswith("-int-sarc")
            assert not row["prompt_type"].endswith("-int")

    @patch("routes.upload._load_fewshots_from_disk", return_value=SAMPLE_FEWSHOTS)
    def test_download_filters_by_center(self, _mock):
        resp = client.get("/api/upload/fewshots/download", params={"center": "MSCI"})
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == 1
        assert rows[0]["prompt_type"] == "gender"
        assert rows[0]["annotation"] == "Genere del paziente maschile."

    @patch("routes.upload._load_faiss_fewshots", return_value={})
    @patch("routes.upload._load_fewshots_from_disk", return_value=SAMPLE_FEWSHOTS)
    def test_download_404_when_no_fewshots_for_center(self, _mock_disk, _mock_faiss):
        resp = client.get("/api/upload/fewshots/download", params={"center": "VGR"})
        assert resp.status_code == 404

    @patch("routes.upload._load_faiss_fewshots", return_value={})
    @patch("routes.upload._load_fewshots_from_disk", return_value={})
    def test_download_404_when_no_fewshots_at_all(self, _mock_disk, _mock_faiss):
        resp = client.get("/api/upload/fewshots/download", params={"center": "INT-SARC"})
        assert resp.status_code == 404

    def test_download_requires_center_param(self):
        resp = client.get("/api/upload/fewshots/download")
        assert resp.status_code == 422  # FastAPI validation error

    @patch("routes.upload._load_fewshots_from_disk", return_value=SAMPLE_FEWSHOTS)
    def test_download_content_disposition_header(self, _mock):
        resp = client.get("/api/upload/fewshots/download", params={"center": "MSCI"})
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "fewshots_msci.csv" in resp.headers["content-disposition"]

    @patch("routes.upload._load_fewshots_from_disk", return_value=SAMPLE_FEWSHOTS)
    def test_download_legacy_int_suffix_only_matches_int_sarc(self, _mock):
        """Legacy '-int' suffix keys should only be included when center is INT-SARC."""
        resp_msci = client.get("/api/upload/fewshots/download", params={"center": "MSCI"})
        rows_msci = _parse_csv(resp_msci.text)
        msci_types = {r["prompt_type"] for r in rows_msci}
        assert "tumorsite" not in msci_types  # legacy "-int" should NOT match MSCI

    @patch("routes.upload._load_fewshots_from_disk", return_value=SAMPLE_FEWSHOTS)
    def test_download_csv_is_reuploadable(self, _mock):
        """Downloaded CSV should have the exact columns needed for re-upload."""
        resp = client.get("/api/upload/fewshots/download", params={"center": "INT-SARC"})
        reader = csv.reader(io.StringIO(resp.text))
        header = next(reader)
        assert header == ["prompt_type", "note_text", "annotation"]

    @patch("routes.upload._load_faiss_fewshots", return_value={
        "gender-int": [("Patient is male.", "Gender male.")],
    })
    @patch("routes.upload._load_fewshots_from_disk", return_value={})
    def test_download_falls_back_to_faiss(self, _mock_disk, _mock_faiss):
        """When simple fewshots are empty, FAISS parquet data is used."""
        resp = client.get("/api/upload/fewshots/download", params={"center": "INT-SARC"})
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == 1
        assert rows[0]["prompt_type"] == "gender"


class TestFewshotStatus:
    """Tests for GET /api/upload/fewshots/status with FAISS scanning."""

    @patch("routes.upload._scan_faiss_counts", return_value={"gender-int": 101, "ageatdiagnosis-int": 131})
    @patch("routes.upload._load_fewshots_from_disk", return_value={})
    def test_status_includes_faiss_counts(self, _mock_disk, _mock_faiss):
        resp = client.get("/api/upload/fewshots/status", params={"center": "INT-SARC"})
        data = resp.json()
        assert data["simple_fewshots_available"] is True
        assert data["total_examples"] == 232
        assert "gender-int" in data["counts_by_prompt"]

    @patch("routes.upload._scan_faiss_counts", return_value={})
    @patch("routes.upload._load_fewshots_from_disk", return_value={})
    def test_status_missing_when_no_source(self, _mock_disk, _mock_faiss):
        resp = client.get("/api/upload/fewshots/status", params={"center": "VGR"})
        data = resp.json()
        assert data["simple_fewshots_available"] is False
        assert data["total_examples"] == 0
