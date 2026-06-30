"""Spec section 'Classifier': bucket boundary cases, rule priority, threshold validation."""
from pathlib import Path

import pytest

from aggregator import aggregate, load_session
from classifier import ClassifierConfig, classify_all, classify_prompt

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_session.json"


@pytest.fixture
def metrics():
    return aggregate(load_session(FIXTURE), center="MSCI")


@pytest.fixture
def cfg():
    return ClassifierConfig()  # defaults: reliable=0.70, usable=0.40, fp_cap=0.10


def test_gender_is_reliable(metrics, cfg):
    """match_rate=0.9, fp_rate=0, only 1 wrong (insufficient for default-bias)."""
    classify_all(metrics, cfg)
    assert metrics["by_prompt"]["gender"]["bucket"] == "reliable"


def test_tumorsite_demoted_by_default_bias(metrics, cfg):
    """match_rate=0.7 hits the reliable threshold, but 3 wrong predictions all
    say 'Upper limb' → default_bias flag → Usable.
    """
    classify_all(metrics, cfg)
    t = metrics["by_prompt"]["tumorsite"]
    assert t["bucket"] == "usable"
    assert any(f.startswith("default_bias") for f in t["flags"])


def test_tumordepth_unreliable_high_abstention(metrics, cfg):
    classify_all(metrics, cfg)
    d = metrics["by_prompt"]["tumordepth"]
    assert d["bucket"] == "unreliable"
    assert "high_abstention" in d["flags"]


def test_histological_unreliable_low_support(metrics, cfg):
    classify_all(metrics, cfg)
    h = metrics["by_prompt"]["histological"]
    assert h["bucket"] == "unreliable"
    assert "low_support" in h["flags"]


def test_bucket_tally(metrics, cfg):
    classify_all(metrics, cfg)
    assert metrics["bucket_counts"] == {"reliable": 1, "usable": 1, "unreliable": 2}


def test_summary_sentence(metrics, cfg):
    classify_all(metrics, cfg)
    assert "1 variables reliably extracted" in metrics["summary_sentence"]
    assert "1 usable" in metrics["summary_sentence"]
    assert "2 unreliable" in metrics["summary_sentence"]


def test_threshold_inversion_rejected():
    """Reliable cannot be ≤ usable."""
    with pytest.raises(ValueError, match="inversion"):
        ClassifierConfig(reliable_threshold=0.5, usable_threshold=0.7).validate()


def test_threshold_boundary_match_rate_exactly_at_reliable():
    """A prompt at exactly reliable_threshold passes."""
    p = _mock_prompt(total=20, counts_match=14, counts_mismatch=6, fp=0)
    result = classify_prompt("x", p, ClassifierConfig())
    assert result["bucket"] == "reliable"


def test_threshold_boundary_match_rate_exactly_at_usable():
    """Exactly at usable threshold = Usable, not Unreliable."""
    p = _mock_prompt(total=20, counts_match=8, counts_mismatch=12, fp=0)
    result = classify_prompt("x", p, ClassifierConfig())
    # 8/20 = 0.40 exactly. Per rule "match_rate < usable_threshold" → Unreliable.
    # 0.40 < 0.40 is False, so this prompt should NOT go to Unreliable on the
    # low-match rule. It should fall through to the Usable bucket.
    assert result["bucket"] == "usable"


def test_high_fp_demotes_to_usable():
    """match_rate ≥ 0.70 but fp_rate > 0.10 → Usable."""
    p = _mock_prompt(total=20, counts_match=15, counts_mismatch=2, fp=3)
    result = classify_prompt("x", p, ClassifierConfig())
    assert result["bucket"] == "usable"
    assert "high_fp" in result["flags"]


def test_default_bias_needs_minimum_wrong_predictions():
    """A single wrong prediction shouldn't trigger default_bias."""
    p = _mock_prompt(
        total=20, counts_match=19, counts_mismatch=1, fp=0,
        avg_pred_len=15,
        histogram={"foo": 20},  # all 20 predictions converge on 'foo'
    )
    # Only 1 wrong → below MIN_WRONG_FOR_DEFAULT_BIAS=3 → no flag
    result = classify_prompt("x", p, ClassifierConfig())
    assert result["bucket"] == "reliable"


def test_long_predictions_not_flagged_for_default_bias():
    """avg predicted length > 30 chars → free text → no default_bias even if all converge."""
    p = _mock_prompt(
        total=20, counts_match=10, counts_mismatch=8, fp=2,
        avg_pred_len=120,
        histogram={"some long sentence here ...........": 20},
    )
    result = classify_prompt("x", p, ClassifierConfig())
    # Falls through to Usable (match_rate=0.5, fp_rate=0.1)
    assert result["bucket"] == "usable"
    assert not any(f.startswith("default_bias") for f in result["flags"])


def test_report_type_skew_flag():
    """When a prompt has reasonable rate overall but tanks on one report_type."""
    p = _mock_prompt(total=20, counts_match=16, counts_mismatch=4, fp=0)
    p["by_report_type"] = {
        "Visit note": {"total": 15, "counts": {}, "match_rate": 0.93, "fp_rate": 0.0},
        "Pathology": {"total": 5, "counts": {}, "match_rate": 0.20, "fp_rate": 0.0},
    }
    result = classify_prompt("x", p, ClassifierConfig())
    assert any(f.startswith("report_type_skew") for f in result["flags"])


# ---------- helpers ----------


def _mock_prompt(
    total: int,
    counts_match: int,
    counts_mismatch: int,
    fp: int,
    fn: int = 0,
    both_empty: int = 0,
    avg_pred_len: float = 10,
    histogram: dict | None = None,
) -> dict:
    """Build a minimal metrics dict matching the aggregator's output shape."""
    return {
        "total": total,
        "counts": {
            "match": counts_match,
            "mismatch": counts_mismatch,
            "false_positive": fp,
            "false_negative": fn,
            "both_empty": both_empty,
            "other": 0,
        },
        "match_rate": counts_match / total if total else 0.0,
        "correctness_rate": (counts_match + both_empty) / total if total else 0.0,
        "fp_rate": fp / total if total else 0.0,
        "fn_rate": fn / total if total else 0.0,
        "abstention_rate": both_empty / total if total else 0.0,
        "avg_similarity": 0.8,
        "avg_predicted_length": avg_pred_len,
        "field_metrics": [],
        "by_report_type": {},
        "predicted_value_histogram": histogram,
    }


def test_correct_abstentions_count_toward_reliable():
    """A prompt with low extract rate but high correct abstention rate should
    still be Reliable, UNLESS abstention_rate exceeds the high-abstention cap.
    """
    # 12 match + 3 both_empty in 15 → correctness 100%, abstention 20%, match 80%
    p = _mock_prompt(total=15, counts_match=12, counts_mismatch=0, fp=0, both_empty=3)
    result = classify_prompt("x", p, ClassifierConfig())
    assert result["bucket"] == "reliable"


def test_high_abstention_still_unreliable_even_when_abstentions_are_correct():
    """The original PDF flagged variables with ≥80% 'Not applicable' as
    Unreliable even when the abstentions were correct, because the variable
    rarely produces a useful value. This must hold under correctness_rate too.
    """
    # 1 match + 9 both_empty in 10 → correctness 100%, but abstention 90%
    p = _mock_prompt(total=10, counts_match=1, counts_mismatch=0, fp=0, both_empty=9)
    result = classify_prompt("x", p, ClassifierConfig())
    assert result["bucket"] == "unreliable"
    assert "high_abstention" in result["flags"]
