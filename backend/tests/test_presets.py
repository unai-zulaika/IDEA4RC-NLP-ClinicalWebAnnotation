"""Tests for Annotation Presets CRUD API."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app
from routes import presets as presets_module


@pytest.fixture(autouse=True)
def _redirect_presets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the presets storage to a temp directory."""
    monkeypatch.setattr(presets_module, "_get_presets_dir", lambda: tmp_path)


@pytest.fixture
def client():
    return TestClient(app)


VALID_PRESET = {
    "name": "Breast Cancer Standard",
    "center": "INT",
    "description": "Standard mapping for breast cancer reports",
    "report_type_mapping": {
        "pathology": ["histology-int", "grading-int"],
        "radiology": ["imaging-int"],
    },
}


class TestCreatePreset:
    def test_create_valid(self, client, tmp_path):
        resp = client.post("/api/presets", json=VALID_PRESET)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == VALID_PRESET["name"]
        assert data["center"] == "INT"
        assert data["report_type_mapping"] == VALID_PRESET["report_type_mapping"]
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data
        # Verify file written
        assert (tmp_path / f"{data['id']}.json").exists()

    def test_create_empty_name_422(self, client):
        body = {**VALID_PRESET, "name": ""}
        resp = client.post("/api/presets", json=body)
        assert resp.status_code == 422

    def test_create_missing_center_422(self, client):
        body = {k: v for k, v in VALID_PRESET.items() if k != "center"}
        resp = client.post("/api/presets", json=body)
        assert resp.status_code == 422


class TestListPresets:
    def test_empty_list(self, client):
        resp = client.get("/api/presets")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_created(self, client):
        client.post("/api/presets", json=VALID_PRESET)
        resp = client.get("/api/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == VALID_PRESET["name"]

    def test_filter_by_center(self, client):
        client.post("/api/presets", json=VALID_PRESET)
        other = {**VALID_PRESET, "name": "Other", "center": "VGR"}
        client.post("/api/presets", json=other)

        resp_int = client.get("/api/presets", params={"center": "INT"})
        assert len(resp_int.json()) == 1
        assert resp_int.json()[0]["center"] == "INT"

        resp_vgr = client.get("/api/presets", params={"center": "VGR"})
        assert len(resp_vgr.json()) == 1
        assert resp_vgr.json()[0]["center"] == "VGR"

        resp_all = client.get("/api/presets")
        assert len(resp_all.json()) == 2


class TestGetPreset:
    def test_found(self, client):
        create_resp = client.post("/api/presets", json=VALID_PRESET)
        preset_id = create_resp.json()["id"]
        resp = client.get(f"/api/presets/{preset_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == preset_id

    def test_not_found(self, client):
        resp = client.get("/api/presets/nonexistent-id")
        assert resp.status_code == 404


class TestUpdatePreset:
    def test_partial_update_name(self, client):
        create_resp = client.post("/api/presets", json=VALID_PRESET)
        preset_id = create_resp.json()["id"]
        resp = client.put(f"/api/presets/{preset_id}", json={"name": "Updated Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"
        assert resp.json()["center"] == "INT"  # unchanged

    def test_update_mapping(self, client):
        create_resp = client.post("/api/presets", json=VALID_PRESET)
        preset_id = create_resp.json()["id"]
        new_mapping = {"surgery": ["surgery-int"]}
        resp = client.put(f"/api/presets/{preset_id}", json={"report_type_mapping": new_mapping})
        assert resp.status_code == 200
        assert resp.json()["report_type_mapping"] == new_mapping

    def test_not_found(self, client):
        resp = client.put("/api/presets/nonexistent-id", json={"name": "X"})
        assert resp.status_code == 404


class TestDeletePreset:
    def test_delete_successfully(self, client, tmp_path):
        create_resp = client.post("/api/presets", json=VALID_PRESET)
        preset_id = create_resp.json()["id"]
        resp = client.delete(f"/api/presets/{preset_id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Verify file removed
        assert not (tmp_path / f"{preset_id}.json").exists()

    def test_not_found(self, client):
        resp = client.delete("/api/presets/nonexistent-id")
        assert resp.status_code == 404

    def test_list_updated_after_delete(self, client):
        create_resp = client.post("/api/presets", json=VALID_PRESET)
        preset_id = create_resp.json()["id"]
        client.delete(f"/api/presets/{preset_id}")
        resp = client.get("/api/presets")
        assert len(resp.json()) == 0
