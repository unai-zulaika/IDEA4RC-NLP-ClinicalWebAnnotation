"""Tests that the /api/annotate/batch route is properly registered."""

import sys
from pathlib import Path

# Ensure the backend directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_batch_route_registered():
    """POST /api/annotate/batch should not return 404 (route must be registered)."""
    response = client.post(
        "/api/annotate/batch",
        json={"note_ids": ["note1"]},
        params={"session_id": "fake-session"},
    )
    assert response.status_code != 404, (
        f"Expected non-404 status but got {response.status_code}. "
        "The /batch route is not registered on the FastAPI app."
    )


def test_batch_route_requires_session_id():
    """POST /api/annotate/batch without session_id query param should return 422."""
    response = client.post(
        "/api/annotate/batch",
        json={"note_ids": ["note1"]},
    )
    assert response.status_code == 422


def test_batch_route_missing_body():
    """POST /api/annotate/batch with session_id but no body should return 422."""
    response = client.post(
        "/api/annotate/batch",
        params={"session_id": "fake-session"},
    )
    assert response.status_code == 422
