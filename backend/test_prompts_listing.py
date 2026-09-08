"""
Tests for GET /api/prompts and the prompt data that feeds it.

A single hand-edited prompt (multifocality, in all four centres) omitted the
then-required `template_placeholder`, so EntityFieldMapping validation raised
inside list_prompts and the endpoint returned 500. The UI showed *no* prompts at
all for every centre — the catalogue disappeared because of one bad entry.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))

from main import app  # noqa: E402
from models.schemas import EntityFieldMapping  # noqa: E402

client = TestClient(app)

PROMPTS_ROOT = Path(__file__).parent / "data" / "latest_prompts"
FAST_PROMPTS_ROOT = Path(__file__).parent / "data" / "fast_prompts"


def _centres(root: Path):
    if not root.is_dir():
        return []
    return [d for d in sorted(root.iterdir()) if (d / "prompts.json").exists()]


# ---------------------------------------------------------------------------
# Endpoint behaviour
# ---------------------------------------------------------------------------

def test_centers_endpoint_lists_the_shipped_centres():
    resp = client.get("/api/prompts/centers")
    assert resp.status_code == 200
    assert set(resp.json()) >= {"INT-SARC", "MSCI", "VGR", "INT-HNC"}


@pytest.mark.parametrize("centre", ["INT-SARC", "MSCI", "VGR", "INT-HNC"])
def test_listing_succeeds_and_is_not_empty(centre):
    resp = client.get(f"/api/prompts?center={centre}")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) > 0, f"{centre} returned an empty prompt catalogue"


@pytest.mark.parametrize("centre", ["INT-SARC", "MSCI", "VGR", "INT-HNC"])
def test_multifocality_mapping_round_trips(centre):
    """The prompt that broke the endpoint must now list with its mapping intact."""
    resp = client.get(f"/api/prompts?center={centre}")
    assert resp.status_code == 200
    hits = [p for p in resp.json() if p["prompt_type"].startswith("multifocality")]
    assert hits, f"multifocality missing from {centre}"
    mapping = hits[0]["entity_mapping"]
    assert mapping is not None
    fm = mapping["field_mappings"][0]
    assert fm["entity_type"] == "Diagnosis"
    assert fm["field_name"] == "isMultifocalTumor"
    assert fm["template_placeholder"]


def test_one_bad_prompt_does_not_empty_the_catalogue(monkeypatch):
    """A prompt that cannot be parsed degrades itself, not the whole listing."""
    import routes.prompts as rp

    good = {"template": "Fine.", "entity_mapping": None}
    broken = {"template": "Broken.", "entity_mapping": {"field_mappings": [{"nope": 1}]}}
    monkeypatch.setattr(
        rp, "load_prompts_json",
        lambda mode="standard": {"TEST": {"good-test": good, "bad-test": broken}},
    )
    real_extract = rp._extract_template_and_mapping

    def explode(prompt_data):
        if isinstance(prompt_data, dict) and prompt_data.get("template") == "Broken.":
            raise ValueError("simulated bad mapping")
        return real_extract(prompt_data)

    monkeypatch.setattr(rp, "_extract_template_and_mapping", explode)

    resp = client.get("/api/prompts?center=TEST")
    assert resp.status_code == 200, resp.text
    by_type = {p["prompt_type"]: p for p in resp.json()}
    assert set(by_type) == {"good-test", "bad-test"}
    # The bad one still appears, with its template, just without the mapping.
    assert by_type["bad-test"]["template"] == "Broken."
    assert by_type["bad-test"]["entity_mapping"] is None


# ---------------------------------------------------------------------------
# Data integrity of the shipped prompt files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("root", [PROMPTS_ROOT, FAST_PROMPTS_ROOT], ids=["standard", "fast"])
def test_every_shipped_field_mapping_validates(root):
    """Catch a malformed prompt at test time rather than in the deployed UI."""
    failures = []
    for centre_dir in _centres(root):
        data = json.loads((centre_dir / "prompts.json").read_text(encoding="utf-8"))
        for prompt_type, prompt_data in data.items():
            if not isinstance(prompt_data, dict):
                continue
            mapping = prompt_data.get("entity_mapping") or {}
            for i, fm in enumerate(mapping.get("field_mappings", [])):
                try:
                    EntityFieldMapping(**fm)
                except Exception as e:
                    failures.append(f"{centre_dir.name}/{prompt_type} field_mappings[{i}]: {e}")
    assert not failures, "invalid field_mappings:\n  " + "\n  ".join(failures)


@pytest.mark.parametrize("root", [PROMPTS_ROOT, FAST_PROMPTS_ROOT], ids=["standard", "fast"])
def test_field_mappings_name_an_entity_and_field(root):
    """entity_type and field_name drive the export; a mapping without them emits nothing."""
    failures = []
    for centre_dir in _centres(root):
        data = json.loads((centre_dir / "prompts.json").read_text(encoding="utf-8"))
        for prompt_type, prompt_data in data.items():
            if not isinstance(prompt_data, dict):
                continue
            mapping = prompt_data.get("entity_mapping") or {}
            for i, fm in enumerate(mapping.get("field_mappings", [])):
                if not fm.get("entity_type") or not fm.get("field_name"):
                    failures.append(f"{centre_dir.name}/{prompt_type} field_mappings[{i}]")
    assert not failures, "field_mappings missing entity_type/field_name:\n  " + "\n  ".join(failures)


# ---------------------------------------------------------------------------
# Session listing must ignore the non-session file kept alongside sessions
# ---------------------------------------------------------------------------

def test_report_type_mappings_is_not_read_as_a_session(tmp_path, monkeypatch, capsys):
    from routes import sessions as s
    monkeypatch.setattr(s, "_get_sessions_dir", lambda: tmp_path)
    (tmp_path / "report_type_mappings.json").write_text('{"MSCI": {"histpat": ["gender-msci"]}}')
    s._save_session("11111111-1111-4111-8111-111111111111", {
        "session_id": "11111111-1111-4111-8111-111111111111",
        "name": "real session", "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00", "notes": [], "annotations": {},
    })

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert [x["name"] for x in resp.json()] == ["real session"]
    assert "Failed to load session" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# vLLM model-name mismatch must be reported, not silently 400 every request
# ---------------------------------------------------------------------------

class TestModelMismatchReporting:
    def _service_with(self, monkeypatch, served_ids, configured):
        from services import vllm_client as vc

        class FakeResponse:
            status_code = 200
            @staticmethod
            def json():
                return {"data": [{"id": i} for i in served_ids]}

        monkeypatch.setattr(vc.requests, "get", lambda *a, **k: FakeResponse())
        svc = object.__new__(vc.EnhancedVLLMClient)
        svc.config = {"vllm_endpoint": "http://vllm:8000/v1", "model_name": configured}
        svc._client = object()
        return svc

    def test_mismatch_is_flagged_with_an_actionable_message(self, monkeypatch):
        svc = self._service_with(monkeypatch, ["google/medgemma-4b-it"], "some/other-model")
        status = svc.get_status()
        assert status["status"] == "model_mismatch"
        assert status["served_models"] == ["google/medgemma-4b-it"]
        assert "google/medgemma-4b-it" in status["error"]
        assert "vllm_config.json" in status["error"]

    def test_matching_model_stays_available(self, monkeypatch):
        svc = self._service_with(monkeypatch, ["a/b", "c/d"], "c/d")
        status = svc.get_status()
        assert status["status"] == "available"
        assert "error" not in status

    def test_server_without_a_model_list_is_not_flagged(self, monkeypatch):
        """An empty list means the server did not tell us; do not guess a mismatch."""
        svc = self._service_with(monkeypatch, [], "anything")
        assert svc.get_status()["status"] == "available"


# ---------------------------------------------------------------------------
# Prompt <-> report-type pairing: both silent-drop cases must be reported
# ---------------------------------------------------------------------------

class TestPairingGapsAreReported:
    """Pairing is many-to-many and discretionary, but two gaps drop work silently:

    a report type with no prompts skips those notes, and a prompt mapped to no
    report type runs on nothing at all. Neither is visible from a single note's
    results, so both must be surfaced.
    """

    def test_report_type_with_no_prompts_is_flagged(self, caplog):
        import logging
        from routes.annotate import _get_applicable_prompts
        with caplog.at_level(logging.WARNING, logger="routes.annotate"):
            got = _get_applicable_prompts(
                note_id="N1", requested_prompt_types=["gender-msci"],
                report_type="radiology",
                report_type_mapping={"histpat": ["gender-msci"]},
                note_prompt_overrides={}, note_prompt_exclusions={},
            )
        assert got == []
        assert "no prompt types mapped" in caplog.text
        assert "radiology" in caplog.text

    def test_prompt_mapped_to_nothing_is_flagged(self, caplog):
        import logging
        from routes.annotate import _report_unpaired_prompts
        note_order = [
            ("N1", "t", ["gender-msci", "biopsygrading-msci"], "histpat"),
            ("N2", "t", ["gender-msci"], "cytology"),
        ]
        with caplog.at_level(logging.WARNING, logger="routes.annotate"):
            unpaired = _report_unpaired_prompts(
                ["gender-msci", "biopsygrading-msci", "tumorsite-msci"], note_order
            )
        assert unpaired == ["tumorsite-msci"]
        assert "tumorsite-msci" in caplog.text
        assert "NO annotations" in caplog.text

    def test_fully_paired_selection_reports_nothing(self, caplog):
        import logging
        from routes.annotate import _report_unpaired_prompts
        note_order = [("N1", "t", ["a", "b"], "histpat"), ("N2", "t", ["b"], "cytology")]
        with caplog.at_level(logging.WARNING, logger="routes.annotate"):
            assert _report_unpaired_prompts(["a", "b"], note_order) == []
        assert "not mapped to any report type" not in caplog.text

    def test_a_prompt_may_serve_several_report_types(self):
        """Many-to-many is allowed — nothing requires a 1:1 pairing."""
        from routes.annotate import _get_applicable_prompts
        mapping = {"histpat": ["gender-msci", "biopsygrading-msci"],
                   "cytology": ["gender-msci"]}
        common = dict(requested_prompt_types=["gender-msci", "biopsygrading-msci"],
                      report_type_mapping=mapping,
                      note_prompt_overrides={}, note_prompt_exclusions={})
        assert _get_applicable_prompts(note_id="N1", report_type="histpat", **common) == \
            ["gender-msci", "biopsygrading-msci"]
        assert _get_applicable_prompts(note_id="N2", report_type="cytology", **common) == \
            ["gender-msci"]

    def test_no_mapping_at_all_runs_everything(self):
        """Before any pairing is defined, every selected prompt runs on every note."""
        from routes.annotate import _get_applicable_prompts
        assert _get_applicable_prompts(
            note_id="N1", requested_prompt_types=["a", "b"], report_type="histpat",
            report_type_mapping=None, note_prompt_overrides={}, note_prompt_exclusions={},
        ) == ["a", "b"]
