"""
Tests for the /export/metadata endpoint and the removal of the
X-Excluded-Rows / X-Diagnosis-Warnings response headers from the CSV
export endpoints.

Background: the headers used to carry full JSON arrays of excluded rows
and diagnosis warnings, which exceeded reverse-proxy header buffers on
sessions with many conflicts. The data now lives in a dedicated JSON
endpoint and the CSV responses carry only Content-Disposition.

Run with:
    cd backend && python -m pytest test_export_metadata.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from main import app  # noqa: E402

client = TestClient(app)


def _excluded_row(patient_id="P1", variable="Patient.gender", value="Unknown",
                  reason="absence_value"):
    """Match the dict shape that _build_export_rows() emits in its excluded list."""
    return {
        "patient_id": patient_id,
        "core_variable": variable,
        "original_value": value,
        "reason": reason,
    }


def _make_session(session_id="sess-meta-1", patient_diagnoses=None):
    """Minimal session fixture sufficient for the metadata endpoint."""
    return {
        "session_id": session_id,
        "name": "Test",
        "description": "",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "notes": [],
        "annotations": {},
        "prompt_types": [],
        "center": "INT-SARC",
        "evaluation_mode": "validation",
        "patient_diagnoses": patient_diagnoses or {},
    }


@pytest.fixture
def sessions_dir(tmp_path):
    with patch("routes.sessions._get_sessions_dir", return_value=tmp_path):
        yield tmp_path


def _seed(sessions_dir, session):
    (sessions_dir / f"{session['session_id']}.json").write_text(
        json.dumps(session), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# /export/metadata
# ---------------------------------------------------------------------------

class TestExportMetadataEndpoint:

    def test_returns_excluded_rows(self, sessions_dir):
        session = _make_session()
        _seed(sessions_dir, session)

        excluded = [
            _excluded_row(patient_id="P1", variable="Patient.gender",
                          value="Unknown", reason="absence_value"),
            _excluded_row(patient_id="P2", variable="Patient.age",
                          value="N/A", reason="absence_value"),
        ]

        with patch("routes.sessions._build_export_rows",
                   return_value=([], excluded)):
            resp = client.get(f"/api/sessions/{session['session_id']}/export/metadata")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["excluded_rows"]) == 2
        assert data["excluded_rows"][0] == {
            "patient_id": "P1",
            "variable": "Patient.gender",
            "value": "Unknown",
            "reason": "absence_value",
        }
        assert data["diagnosis_warnings"] == []

    def test_returns_diagnosis_warnings_for_needs_review(self, sessions_dir):
        session = _make_session(patient_diagnoses={
            "P1": {
                "status": "needs_review",
                "review_reasons": ["Missing histology code", "Conflicting topography"],
            },
            "P2": {
                "status": "auto_resolved",
                "review_reasons": ["this should not appear"],
            },
            "P3": {
                "status": "needs_review",
                "review_reasons": [],
            },
        })
        _seed(sessions_dir, session)

        with patch("routes.sessions._build_export_rows",
                   return_value=([], [])):
            resp = client.get(f"/api/sessions/{session['session_id']}/export/metadata")

        assert resp.status_code == 200
        warnings = resp.json()["diagnosis_warnings"]
        # Only needs_review patients are included
        ids = {w["patient_id"] for w in warnings}
        assert ids == {"P1", "P3"}
        p1 = next(w for w in warnings if w["patient_id"] == "P1")
        assert p1["reasons"] == ["Missing histology code", "Conflicting topography"]

    def test_empty_session_returns_empty_lists(self, sessions_dir):
        session = _make_session()
        _seed(sessions_dir, session)

        with patch("routes.sessions._build_export_rows",
                   return_value=([], [])):
            resp = client.get(f"/api/sessions/{session['session_id']}/export/metadata")

        assert resp.status_code == 200
        assert resp.json() == {"excluded_rows": [], "diagnosis_warnings": []}

    def test_404_when_session_missing(self, sessions_dir):
        resp = client.get("/api/sessions/does-not-exist/export/metadata")
        assert resp.status_code == 404

    def test_handles_large_excluded_list_without_header_overflow(self, sessions_dir):
        """The whole point of moving this off headers: it must scale."""
        session = _make_session()
        _seed(sessions_dir, session)

        # 1000 excluded rows ~ 200KB of JSON, way past any nginx header buffer
        big_excluded = [
            _excluded_row(patient_id=f"P{i}", value=f"value_{i}")
            for i in range(1000)
        ]

        with patch("routes.sessions._build_export_rows",
                   return_value=([], big_excluded)):
            resp = client.get(f"/api/sessions/{session['session_id']}/export/metadata")

        assert resp.status_code == 200
        assert len(resp.json()["excluded_rows"]) == 1000

    def test_handles_missing_review_reasons_gracefully(self, sessions_dir):
        """Older session JSONs may have needs_review status but no review_reasons key."""
        session = _make_session(patient_diagnoses={
            "P1": {"status": "needs_review"},  # no review_reasons key at all
        })
        _seed(sessions_dir, session)

        with patch("routes.sessions._build_export_rows",
                   return_value=([], [])):
            resp = client.get(f"/api/sessions/{session['session_id']}/export/metadata")

        assert resp.status_code == 200
        assert resp.json()["diagnosis_warnings"] == [
            {"patient_id": "P1", "reasons": []}
        ]


# ---------------------------------------------------------------------------
# Header removal from CSV endpoints
# ---------------------------------------------------------------------------

class TestCsvEndpointsNoLargeHeaders:
    """The X-Excluded-Rows / X-Diagnosis-Warnings headers must not appear."""

    def _seed_minimal(self, sessions_dir):
        session = _make_session(session_id="sess-csv-1")
        _seed(sessions_dir, session)
        return session["session_id"]

    def test_export_validated_has_no_excluded_rows_header(self, sessions_dir):
        sid = self._seed_minimal(sessions_dir)
        big_excluded = [_excluded_row() for _ in range(500)]

        with patch("routes.sessions._build_export_rows",
                   return_value=([], big_excluded)):
            resp = client.get(f"/api/sessions/{sid}/export")

        assert resp.status_code == 200
        # Critical: headers must be small regardless of excluded list size
        assert "x-excluded-rows" not in {k.lower() for k in resp.headers.keys()}
        assert "x-diagnosis-warnings" not in {k.lower() for k in resp.headers.keys()}
        # Content-Disposition should still be there for download
        assert "content-disposition" in {k.lower() for k in resp.headers.keys()}

    def test_export_codes_has_no_excluded_rows_header(self, sessions_dir):
        sid = self._seed_minimal(sessions_dir)
        big_excluded = [_excluded_row() for _ in range(500)]

        with patch("routes.sessions._build_export_rows",
                   return_value=([], big_excluded)):
            resp = client.get(f"/api/sessions/{sid}/export/codes")

        assert resp.status_code == 200
        assert "x-excluded-rows" not in {k.lower() for k in resp.headers.keys()}
        assert "x-diagnosis-warnings" not in {k.lower() for k in resp.headers.keys()}
        assert "content-disposition" in {k.lower() for k in resp.headers.keys()}
