"""
Unit tests for session import/export endpoints.

Uses pytest + FastAPI TestClient + unittest.mock to isolate the filesystem.

Run with:
    cd backend && python -m pytest test_session_import_export.py -v
"""
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from main import app  # noqa: E402 — must come after sys.path insert

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared sample session data
# ---------------------------------------------------------------------------
SAMPLE_SESSION = {
    "session_id": "orig-id-123",
    "name": "Test Session",
    "description": "A test session",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00",
    "notes": [
        {
            "text": "Patient presents with brain tumor.",
            "date": "2024-01-01",
            "p_id": "P001",
            "note_id": "N001",
            "report_type": "CCE",
            "annotations": "",
        }
    ],
    "annotations": {
        "N001": {
            "tumorsite-int": {
                "note_id": "N001",
                "prompt_type": "tumorsite-int",
                "annotation_text": "Brain",
                "values": [{"value": "Brain", "evidence_spans": [], "reasoning": None}],
                "edited": False,
                "status": "success",
                "evidence_spans": [],
            }
        }
    },
    "prompt_types": ["tumorsite-int"],
    "center": "INT",
    "evaluation_mode": "validation",
    "report_type_mapping": {"CCE": ["tumorsite-int"]},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sessions_dir(tmp_path):
    """Create a temp sessions directory with one pre-seeded session file."""
    session_file = tmp_path / "orig-id-123.json"
    session_file.write_text(json.dumps(SAMPLE_SESSION), encoding="utf-8")
    with patch("routes.sessions._get_sessions_dir", return_value=tmp_path):
        yield tmp_path


def _make_upload(data: dict, filename: str = "session.json"):
    """Build the `files` dict for a TestClient multipart upload."""
    content = json.dumps(data).encode()
    return {"file": (filename, io.BytesIO(content), "application/json")}


# ===========================================================================
# Export tests
# ===========================================================================
class TestExportSessionJson:
    def test_success_status_and_content_type(self, sessions_dir):
        r = client.get("/api/sessions/orig-id-123/export/session")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]

    def test_response_contains_session_fields(self, sessions_dir):
        r = client.get("/api/sessions/orig-id-123/export/session")
        data = r.json()
        assert data["session_id"] == "orig-id-123"
        assert data["name"] == "Test Session"
        assert data["center"] == "INT"
        assert data["prompt_types"] == ["tumorsite-int"]

    def test_adds_export_metadata(self, sessions_dir):
        r = client.get("/api/sessions/orig-id-123/export/session")
        data = r.json()
        assert "exported_at" in data
        assert data["export_version"] == "1.0"

    def test_includes_notes(self, sessions_dir):
        r = client.get("/api/sessions/orig-id-123/export/session")
        data = r.json()
        assert len(data["notes"]) == 1
        assert data["notes"][0]["note_id"] == "N001"

    def test_includes_annotations(self, sessions_dir):
        r = client.get("/api/sessions/orig-id-123/export/session")
        data = r.json()
        assert "N001" in data["annotations"]
        assert "tumorsite-int" in data["annotations"]["N001"]

    def test_content_disposition_header(self, sessions_dir):
        r = client.get("/api/sessions/orig-id-123/export/session")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".json" in cd

    def test_not_found_returns_404(self, sessions_dir):
        r = client.get("/api/sessions/nonexistent-id/export/session")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()


# ===========================================================================
# Import tests
# ===========================================================================
class TestImportSession:
    def test_success_returns_200_and_session_info(self, sessions_dir):
        r = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Test Session"
        assert body["note_count"] == 1
        assert body["prompt_types"] == ["tumorsite-int"]
        assert body["center"] == "INT"
        # evaluation_mode is not part of SessionInfo (only in SessionData full response)

    def test_assigns_new_session_id(self, sessions_dir):
        r = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        assert r.status_code == 200
        new_id = r.json()["session_id"]
        assert new_id != "orig-id-123"
        # New ID should be a valid UUID-ish string (non-empty)
        assert len(new_id) > 0

    def test_two_imports_get_distinct_ids(self, sessions_dir):
        r1 = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        r2 = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        assert r1.json()["session_id"] != r2.json()["session_id"]

    def test_session_file_is_persisted(self, sessions_dir):
        r = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        new_id = r.json()["session_id"]
        session_file = sessions_dir / f"{new_id}.json"
        assert session_file.exists()

    def test_preserves_annotations(self, sessions_dir):
        r = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        new_id = r.json()["session_id"]
        saved = json.loads((sessions_dir / f"{new_id}.json").read_text())
        assert "N001" in saved["annotations"]
        assert "tumorsite-int" in saved["annotations"]["N001"]
        annotation = saved["annotations"]["N001"]["tumorsite-int"]
        assert annotation["annotation_text"] == "Brain"

    def test_preserves_notes(self, sessions_dir):
        r = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        new_id = r.json()["session_id"]
        saved = json.loads((sessions_dir / f"{new_id}.json").read_text())
        assert len(saved["notes"]) == 1
        assert saved["notes"][0]["p_id"] == "P001"

    def test_strips_export_metadata(self, sessions_dir):
        data = {
            **SAMPLE_SESSION,
            "exported_at": "2024-01-01T00:00:00",
            "export_version": "1.0",
        }
        r = client.post("/api/sessions/import", files=_make_upload(data))
        new_id = r.json()["session_id"]
        saved = json.loads((sessions_dir / f"{new_id}.json").read_text())
        assert "exported_at" not in saved
        assert "export_version" not in saved

    def test_invalid_json_returns_400(self, sessions_dir):
        bad = b"not {{ valid json"
        r = client.post(
            "/api/sessions/import",
            files={"file": ("s.json", io.BytesIO(bad), "application/json")},
        )
        assert r.status_code == 400
        assert "invalid json" in r.json()["detail"].lower()

    def test_non_json_extension_returns_400(self, sessions_dir):
        content = json.dumps(SAMPLE_SESSION).encode()
        r = client.post(
            "/api/sessions/import",
            files={"file": ("session.csv", io.BytesIO(content), "text/csv")},
        )
        assert r.status_code == 400
        assert ".json" in r.json()["detail"].lower()

    def test_missing_required_fields_returns_422(self, sessions_dir):
        incomplete = {"name": "Only a name, nothing else"}
        r = client.post("/api/sessions/import", files=_make_upload(incomplete))
        assert r.status_code == 422

    def test_missing_notes_field_returns_422(self, sessions_dir):
        no_notes = {k: v for k, v in SAMPLE_SESSION.items() if k != "notes"}
        r = client.post("/api/sessions/import", files=_make_upload(no_notes))
        assert r.status_code == 422

    def test_missing_annotations_field_returns_422(self, sessions_dir):
        no_ann = {k: v for k, v in SAMPLE_SESSION.items() if k != "annotations"}
        r = client.post("/api/sessions/import", files=_make_upload(no_ann))
        assert r.status_code == 422

    def test_empty_notes_accepted(self, sessions_dir):
        data = {**SAMPLE_SESSION, "notes": [], "annotations": {}}
        r = client.post("/api/sessions/import", files=_make_upload(data))
        assert r.status_code == 200
        assert r.json()["note_count"] == 0

    def test_preserves_original_created_at(self, sessions_dir):
        r = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        new_id = r.json()["session_id"]
        saved = json.loads((sessions_dir / f"{new_id}.json").read_text())
        assert saved["created_at"] == "2024-01-01T00:00:00"

    def test_updates_session_id_in_saved_file(self, sessions_dir):
        r = client.post("/api/sessions/import", files=_make_upload(SAMPLE_SESSION))
        new_id = r.json()["session_id"]
        saved = json.loads((sessions_dir / f"{new_id}.json").read_text())
        assert saved["session_id"] == new_id
        assert saved["session_id"] != "orig-id-123"


# ===========================================================================
# Round-trip test
# ===========================================================================
class TestRoundTrip:
    def test_export_then_import_preserves_session_data(self, sessions_dir):
        # Step 1: Export the seeded session
        r_export = client.get("/api/sessions/orig-id-123/export/session")
        assert r_export.status_code == 200

        # Step 2: Import the exported bytes
        r_import = client.post(
            "/api/sessions/import",
            files={"file": ("session.json", io.BytesIO(r_export.content), "application/json")},
        )
        assert r_import.status_code == 200
        info = r_import.json()

        # New session has a different ID
        assert info["session_id"] != "orig-id-123"

        # Core metadata is preserved
        assert info["name"] == "Test Session"
        assert info["note_count"] == 1
        assert info["prompt_types"] == ["tumorsite-int"]
        assert info["center"] == "INT"

        # Annotations are intact in the saved file
        new_id = info["session_id"]
        saved = json.loads((sessions_dir / f"{new_id}.json").read_text())
        assert saved["annotations"]["N001"]["tumorsite-int"]["annotation_text"] == "Brain"
        # Export metadata was stripped
        assert "exported_at" not in saved
        assert "export_version" not in saved

    def test_multiple_round_trips_each_get_unique_id(self, sessions_dir):
        r_export = client.get("/api/sessions/orig-id-123/export/session")
        ids = set()
        for _ in range(3):
            r = client.post(
                "/api/sessions/import",
                files={"file": ("s.json", io.BytesIO(r_export.content), "application/json")},
            )
            assert r.status_code == 200
            ids.add(r.json()["session_id"])
        assert len(ids) == 3, "Each import should produce a unique session ID"
