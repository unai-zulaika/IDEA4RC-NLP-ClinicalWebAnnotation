"""Spec section: 1_build_mapping.py heuristics produce expected (prompt_type, confidence)
for hand-picked sentences from the real codebook.
"""
import importlib.util
import json
import sys
from pathlib import Path

# Load 1_build_mapping.py — its filename starts with a digit so we have to use
# importlib rather than a plain `import`.
_HERE = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_mapping", _HERE / "1_build_mapping.py")
build_mapping = importlib.util.module_from_spec(_spec)
sys.modules["build_mapping"] = build_mapping
_spec.loader.exec_module(build_mapping)


# Minimal in-test prompts.json shaped like the real MSCI section.
_MSCI_PROMPTS = {
    "gender": {
        "entity_mapping": {
            "entity_type": "Patient.sex",
            "field_mappings": [{"field_name": "sex"}],
        }
    },
    "tumordiameter": {
        "entity_mapping": {
            "entity_type": "Tumor.diameter",
            "field_mappings": [{"field_name": "diameter"}],
        }
    },
    "histological": {
        "entity_mapping": {
            "entity_type": "Tumor.histology",
            "field_mappings": [{"field_name": "histological_type"}],
        }
    },
    "tumorsite": {
        "entity_mapping": {
            "entity_type": "Tumor.site",
            "field_mappings": [{"field_name": "site"}],
        }
    },
    "biopsygrading": {
        "entity_mapping": {
            "entity_type": "Biopsy.grade",
            "field_mappings": [{"field_name": "grade"}],
        }
    },
    "ageatdiagnosis": {
        "entity_mapping": {
            "entity_type": "Diagnosis.age",
            "field_mappings": [{"field_name": "age"}],
        }
    },
}


def _score(sentence: str):
    index = build_mapping.build_keyword_index(_MSCI_PROMPTS)
    return build_mapping.score_sentence(sentence, index)


def test_gender_matches():
    r = _score("Patient's gender [pick gender]")
    assert r.prompt_type == "gender"
    assert r.confidence == "high"


def test_tumor_diameter_matches():
    r = _score("Tumor longest diameter: [put value]mm (at initial imaging on [put date])")
    assert r.prompt_type == "tumordiameter"
    assert r.confidence == "high"


def test_histological_matches():
    r = _score("Histological type: Myxoid liposarcoma ([select ICD-O-3 code])")
    assert r.prompt_type == "histological"
    assert r.confidence in {"high", "medium"}


def test_tumor_site_matches():
    r = _score("Tumor site (Upper and Lower limbs): [select site]")
    assert r.prompt_type == "tumorsite"
    # Strong: 'tumor' + 'site' both hit
    assert r.confidence == "high"


def test_biopsy_grading_matches():
    r = _score("Biopsy grading (FNCLCC): [select grade]")
    assert r.prompt_type == "biopsygrading"
    assert r.confidence == "high"


def test_age_at_diagnosis_matches():
    r = _score("Age at diagnosis [put age] years")
    assert r.prompt_type == "ageatdiagnosis"
    assert r.confidence == "high"


def test_no_match_leaves_prompt_blank():
    r = _score("Charlson Comorbidity index [put value] points (evaluated at [put date])")
    assert r.prompt_type == ""
    assert r.confidence == "none"


def test_end_to_end_against_fixture(tmp_path):
    """Run the CLI against the fixture codebook + a synthetic prompts.json and
    confirm the output CSV is well-formed.
    """
    prompts_path = tmp_path / "prompts.json"
    prompts_path.write_text(json.dumps({"MSCI": _MSCI_PROMPTS}), encoding="utf-8")
    out_path = tmp_path / "mapping_msci.csv"
    fixture_codebook = _HERE / "tests" / "fixtures" / "data_items_def.json"

    rc = build_mapping.main([
        "--codebook", str(fixture_codebook),
        "--prompts", str(prompts_path),
        "--center", "MSCI",
        "--out", str(out_path),
    ])
    assert rc == 0
    assert out_path.exists()

    import csv as _csv
    with open(out_path, "r", encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    # 4 english entries; polish dict_id=110 filtered out
    assert len(rows) == 4
    node_ids = {int(r["node_id"]) for r in rows}
    assert node_ids == {56, 89, 70, 102}


def test_force_required_to_overwrite(tmp_path):
    """Spec: refuse to overwrite without --force (protects manual edits)."""
    prompts_path = tmp_path / "prompts.json"
    prompts_path.write_text(json.dumps({"MSCI": _MSCI_PROMPTS}), encoding="utf-8")
    out_path = tmp_path / "mapping_msci.csv"
    out_path.write_text("existing,content\n", encoding="utf-8")
    fixture_codebook = _HERE / "tests" / "fixtures" / "data_items_def.json"

    rc = build_mapping.main([
        "--codebook", str(fixture_codebook),
        "--prompts", str(prompts_path),
        "--center", "MSCI",
        "--out", str(out_path),
    ])
    assert rc == 1
    # Untouched
    assert out_path.read_text(encoding="utf-8") == "existing,content\n"

    # With --force it should overwrite
    rc = build_mapping.main([
        "--codebook", str(fixture_codebook),
        "--prompts", str(prompts_path),
        "--center", "MSCI",
        "--out", str(out_path),
        "--force",
    ])
    assert rc == 0
    assert "existing,content" not in out_path.read_text(encoding="utf-8")
