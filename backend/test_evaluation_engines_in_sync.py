"""
Guards that the pipeline's evaluation engine stays a mirror of the backend's.

The two files are separate on disk because the pipeline ships as its own
container and cannot import from the backend image. They had silently forked:
the pipeline copy lost the flexible-punctuation handling, so the same
prediction/gold pair scored differently in the "raw" and "production" stacks —
a systematic bias between two runs meant to control each other.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

BACKEND_ENGINE = Path(__file__).parent / "lib" / "evaluation_engine.py"
PIPELINE_ENGINE = (
    Path(__file__).parent.parent / "pipeline" / "api" / "nlp" / "evaluation_engine.py"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def engines():
    if not PIPELINE_ENGINE.exists():
        pytest.skip("pipeline evaluation_engine.py not present")
    return _load("_backend_eval", BACKEND_ENGINE), _load("_pipeline_eval", PIPELINE_ENGINE)


def _body(path: Path) -> str:
    """File content with the leading module docstring stripped.

    The two files differ only in that header: the pipeline copy carries a
    'do not edit here' notice pointing at the canonical file.
    """
    text = path.read_text()
    parts = text.split('"""', 2)
    return parts[2].lstrip("\n") if len(parts) == 3 else text


def test_bodies_are_identical():
    assert _body(PIPELINE_ENGINE) == _body(BACKEND_ENGINE), (
        "pipeline/api/nlp/evaluation_engine.py has diverged from "
        "backend/lib/evaluation_engine.py. Edit the backend file and copy it "
        "across; do not patch the mirror."
    )


def test_pipeline_header_names_the_canonical_file():
    head = PIPELINE_ENGINE.read_text()[:900]
    assert "backend/lib/evaluation_engine.py" in head
    assert "DO NOT EDIT HERE" in head


@pytest.mark.parametrize("expected,predicted", [
    ("Grade 2", "Grade 2."),
    ("FNCLCC Grade 1.", "FNCLCC Grade 1"),
    ("Tumor depth: deep", "Tumor depth: deep."),
    ("Not applicable", "Not applicable"),
    ("R0", "R1"),
    ("", ""),
])
def test_exact_match_agrees_across_stacks(engines, expected, predicted):
    backend, pipeline = engines
    assert backend.exact_match(expected, predicted) == pipeline.exact_match(expected, predicted)


@pytest.mark.parametrize("expected,predicted", [
    ("Age at diagnosis: 54 years.", "Age at diagnosis: 54 years"),
    ("Surgery date: 15/01/2024.", "Surgery date: 15/01/2024"),
    ("Gender: male.", "Gender: female."),
])
def test_evaluate_annotation_agrees_across_stacks(engines, expected, predicted):
    backend, pipeline = engines
    b = backend.evaluate_annotation(expected, predicted)
    p = pipeline.evaluate_annotation(expected, predicted)
    assert b["exact_match"] == p["exact_match"]
    assert b.get("similarity_score") == pytest.approx(p.get("similarity_score"))
