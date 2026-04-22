"""
Tests for the bulk conflict-resolution endpoint:
    POST /api/sessions/{session_id}/conflicts/resolve

Run with:
    cd backend && .venv/bin/python -m pytest test_conflict_resolution.py -v
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


def _ann(note_id: str, prompt_type: str, text: str):
    """Build a minimal annotation dict that `_build_export_rows` will accept."""
    return {
        "note_id": note_id,
        "prompt_type": prompt_type,
        "annotation_text": text,
        "values": [{"value": text, "evidence_spans": [], "reasoning": None}],
        "edited": False,
        "status": "success",
        "evidence_spans": [],
    }


def _session_with_gender_conflict():
    """Two notes for patient P001 — one says Male, the other Female.
    Patient is a non-repeatable entity → conflict."""
    return {
        "session_id": "conflict-test",
        "name": "Conflict test",
        "description": "",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "notes": [
            {
                "text": "First note", "date": "2024-01-01", "p_id": "P001",
                "note_id": "N1", "report_type": "CCE", "annotations": "",
            },
            {
                "text": "Second note", "date": "2024-02-01", "p_id": "P001",
                "note_id": "N2", "report_type": "CCE", "annotations": "",
            },
        ],
        "annotations": {
            "N1": {"gender-int-sarc": _ann("N1", "gender-int-sarc", "Male")},
            "N2": {"gender-int-sarc": _ann("N2", "gender-int-sarc", "Female")},
        },
        "prompt_types": ["gender-int-sarc"],
        "center": "INT-SARC",
        "evaluation_mode": "validation",
    }


@pytest.fixture
def sessions_dir(tmp_path):
    session = _session_with_gender_conflict()
    (tmp_path / f"{session['session_id']}.json").write_text(
        json.dumps(session), encoding="utf-8"
    )
    with patch("routes.sessions._get_sessions_dir", return_value=tmp_path):
        yield tmp_path


def test_validate_reports_conflict_before_resolution(sessions_dir):
    """Sanity check: the fixture really produces a conflict."""
    r = client.get("/api/sessions/conflict-test/export/validate")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert len(body["conflicts"]) >= 1


def test_resolve_deletes_entries_and_clears_conflict(sessions_dir):
    """Posting both conflicting entries wipes them and returns valid=True."""
    r = client.post(
        "/api/sessions/conflict-test/conflicts/resolve",
        json={"entries": [
            {"note_id": "N1", "prompt_type": "gender-int-sarc"},
            {"note_id": "N2", "prompt_type": "gender-int-sarc"},
        ]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 2
    assert body["not_found_count"] == 0
    assert body["valid"] is True
    assert body["remaining_conflicts"] == []

    # Verify the session file was actually modified on disk
    on_disk = json.loads((sessions_dir / "conflict-test.json").read_text())
    assert "gender-int-sarc" not in on_disk["annotations"]["N1"]
    assert "gender-int-sarc" not in on_disk["annotations"]["N2"]


def test_resolve_partial_still_conflicts(sessions_dir):
    """Deleting only one side leaves the other as a valid annotation (no conflict)."""
    r = client.post(
        "/api/sessions/conflict-test/conflicts/resolve",
        json={"entries": [{"note_id": "N1", "prompt_type": "gender-int-sarc"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deleted_count"] == 1
    # Single remaining annotation means no cardinality conflict
    assert body["valid"] is True


def test_resolve_skips_missing_entries(sessions_dir):
    """Entries referring to annotations that don't exist are counted as not_found, not errors."""
    r = client.post(
        "/api/sessions/conflict-test/conflicts/resolve",
        json={"entries": [
            {"note_id": "NOT-A-NOTE", "prompt_type": "gender-int-sarc"},
            {"note_id": "N1", "prompt_type": "nonexistent-prompt"},
            {"note_id": "N1", "prompt_type": "gender-int-sarc"},  # real
        ]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deleted_count"] == 1
    assert body["not_found_count"] == 2


def test_resolve_404_on_missing_session(tmp_path):
    with patch("routes.sessions._get_sessions_dir", return_value=tmp_path):
        r = client.post(
            "/api/sessions/does-not-exist/conflicts/resolve",
            json={"entries": []},
        )
    assert r.status_code == 404


def test_resolve_empty_entries_is_noop(sessions_dir):
    """Empty list deletes nothing but still returns current conflict state."""
    r = client.post(
        "/api/sessions/conflict-test/conflicts/resolve",
        json={"entries": []},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deleted_count"] == 0
    assert body["not_found_count"] == 0
    # Conflict still present
    assert body["valid"] is False
