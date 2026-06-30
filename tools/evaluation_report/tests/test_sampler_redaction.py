"""Spec section 'Sampler': the privacy contract test plus balance and determinism."""
import json
from pathlib import Path

import pytest

from aggregator import aggregate, load_session
from classifier import ClassifierConfig, classify_all
from sampler import sample_errors

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_session.json"
SENTINEL = "SENSITIVE_NOTE_TEXT_DO_NOT_LEAK"


@pytest.fixture
def session_and_metrics():
    session = load_session(FIXTURE)
    metrics = aggregate(session, center="MSCI")
    classify_all(metrics, ClassifierConfig())
    return session, metrics


def test_no_sentinel_in_samples_dict(session_and_metrics):
    """THE privacy contract: nothing from note_original_text reaches samples."""
    session, metrics = session_and_metrics
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=5, seed=42)
    serialized = json.dumps(metrics)
    assert SENTINEL not in serialized


def test_samples_have_no_note_text_field(session_and_metrics):
    """Structural: the samples dicts must not even HAVE a note_text key."""
    session, metrics = session_and_metrics
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=5, seed=42)
    for prompt_name, p in metrics["by_prompt"].items():
        for s in p.get("samples", []):
            assert "note_text" not in s
            assert "note_original_text" not in s
            # Whitelist: only these fields should ever appear
            assert set(s.keys()) == {"note_id", "report_type", "match_type", "expected", "predicted"}


def test_samples_include_annotation_values(session_and_metrics):
    """The privacy answer permits expected/predicted to leak — verify they're present."""
    session, metrics = session_and_metrics
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=5, seed=42)
    # tumorsite has 2 mismatch + 1 FP = 3 errors total
    tumorsite_samples = metrics["by_prompt"]["tumorsite"]["samples"]
    assert len(tumorsite_samples) == 3
    # The errors all predict "Tumor site: Upper limb"
    assert all("Upper limb" in s["predicted"] for s in tumorsite_samples)


def test_priority_order_mismatch_first(session_and_metrics):
    """When asked for 1 sample, take a mismatch over both_empty."""
    session, metrics = session_and_metrics
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=1, seed=42)
    # tumordepth has 9 both_empty + 1 match. No mismatches, FPs, or FNs.
    # With samples_per_prompt=1, we get 1 both_empty.
    depth_samples = metrics["by_prompt"]["tumordepth"]["samples"]
    assert len(depth_samples) == 1
    assert depth_samples[0]["match_type"] == "both_empty"

    # gender: 1 mismatch, 0 FP/FN/both_empty among errors → 1 mismatch.
    gender_samples = metrics["by_prompt"]["gender"]["samples"]
    assert len(gender_samples) == 1
    assert gender_samples[0]["match_type"] == "mismatch"


def test_balance_across_match_types(session_and_metrics):
    """tumorsite has 2 mismatch + 1 FP. With samples_per_prompt=5, all 3 are taken
    and they appear in priority order (mismatches first).
    """
    session, metrics = session_and_metrics
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=5, seed=42)
    samples = metrics["by_prompt"]["tumorsite"]["samples"]
    assert len(samples) == 3
    # First two should be mismatch type, last is false_positive
    types = [s["match_type"] for s in samples]
    assert types == ["mismatch", "mismatch", "false_positive"]


def test_seed_determinism(session_and_metrics):
    """Same seed → same samples even when sampling from a larger pool."""
    session, _ = session_and_metrics

    def _go(seed: int):
        m = aggregate(session, center="MSCI")
        classify_all(m, ClassifierConfig())
        sample_errors(session, m, center="MSCI", samples_per_prompt=2, seed=seed)
        return [s["note_id"] for s in m["by_prompt"]["tumordepth"]["samples"]]

    a = _go(42)
    b = _go(42)
    c = _go(99)
    assert a == b
    assert a != c


def test_clean_matches_never_sampled(session_and_metrics):
    """A note that matched cleanly should never appear as a sample."""
    session, metrics = session_and_metrics
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=5, seed=42)
    for prompt_name, p in metrics["by_prompt"].items():
        for s in p.get("samples", []):
            assert s["match_type"] != "match"
