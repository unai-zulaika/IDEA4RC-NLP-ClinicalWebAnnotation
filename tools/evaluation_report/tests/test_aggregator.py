"""Spec section 'Aggregator': match_type counts and rates aggregate correctly,
skipped annotations don't pollute rates, by_report_type cross-tab matches by-hand
calculation, histogram only emitted for short-value prompts.
"""
import json
from pathlib import Path

import pytest

from aggregator import aggregate, load_session

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_session.json"


@pytest.fixture
def session():
    return load_session(FIXTURE)


@pytest.fixture
def metrics(session):
    return aggregate(session, center="MSCI")


def test_totals(metrics):
    # 35 annotations with evaluation_result, 1 skipped (5001 has eval_result=null)
    assert metrics["totals"]["annotations"] == 34
    assert metrics["totals"]["skipped"] == 1
    assert metrics["totals"]["prompt_types"] == 4  # gender, tumorsite, tumordepth, histological


def test_center_suffix_stripped(metrics):
    assert "gender" in metrics["by_prompt"]
    assert "tumorsite" in metrics["by_prompt"]
    assert "gender-msci" not in metrics["by_prompt"]


def test_gender_counts(metrics):
    g = metrics["by_prompt"]["gender"]
    assert g["total"] == 10
    assert g["counts"]["match"] == 9
    assert g["counts"]["mismatch"] == 1
    assert g["counts"]["false_positive"] == 0
    assert g["counts"]["false_negative"] == 0
    assert g["counts"]["both_empty"] == 0
    assert g["match_rate"] == pytest.approx(0.9)
    # No abstentions for gender in this fixture → correctness == match
    assert g["correctness_rate"] == pytest.approx(0.9)
    assert g["fp_rate"] == 0.0


def test_correctness_includes_both_empty(metrics):
    """tumordepth has 1 match + 9 both_empty in 10 cases. Match rate is 10%
    (extraction-only) but correctness rate is 100% — the model abstained
    correctly when there was nothing to extract.
    """
    d = metrics["by_prompt"]["tumordepth"]
    assert d["match_rate"] == pytest.approx(0.1)
    assert d["correctness_rate"] == pytest.approx(1.0)


def test_correctness_per_report_type():
    """The per-report-type cross-tab must also include correctness_rate."""
    # Use the existing fixture; gender has data under multiple report types
    metrics = aggregate(load_session(FIXTURE), center="MSCI")
    g = metrics["by_prompt"]["gender"]
    for rt, m in g["by_report_type"].items():
        assert "correctness_rate" in m
        assert "match_rate" in m


def test_tumorsite_counts(metrics):
    t = metrics["by_prompt"]["tumorsite"]
    assert t["total"] == 10
    assert t["counts"]["match"] == 7
    assert t["counts"]["mismatch"] == 2
    assert t["counts"]["false_positive"] == 1
    assert t["match_rate"] == pytest.approx(0.7)
    assert t["fp_rate"] == pytest.approx(0.1)


def test_tumordepth_high_abstention(metrics):
    d = metrics["by_prompt"]["tumordepth"]
    assert d["counts"]["both_empty"] == 9
    assert d["counts"]["match"] == 1
    assert d["abstention_rate"] == pytest.approx(0.9)


def test_histological_low_support(metrics):
    h = metrics["by_prompt"]["histological"]
    assert h["total"] == 4
    assert h["counts"]["match"] == 3
    assert h["counts"]["mismatch"] == 1


def test_by_report_type_crosstab_for_gender(metrics):
    """gender appears under 'Visit note' and 'Pathology'. The mismatch (1010) is
    under Pathology, so Pathology's match_rate should be lower.
    """
    rts = metrics["by_prompt"]["gender"]["by_report_type"]
    assert "Visit note" in rts
    assert "Pathology" in rts
    # Visit note: 7 anns, all match
    assert rts["Visit note"]["total"] == 7
    assert rts["Visit note"]["match_rate"] == 1.0
    # Pathology: 3 anns, 2 match + 1 mismatch
    assert rts["Pathology"]["total"] == 3
    assert rts["Pathology"]["match_rate"] == pytest.approx(2 / 3)


def test_histogram_emitted_for_short_values(metrics):
    """All gender predictions are short enumeration values → histogram present."""
    g = metrics["by_prompt"]["gender"]
    assert g["predicted_value_histogram"] is not None
    # 7 female + 3 male in 10 annotations (all matches keep predicted = expected)
    assert g["predicted_value_histogram"]["Patient's gender female."] == 7
    assert g["predicted_value_histogram"]["Patient's gender male."] == 3


def test_avg_predicted_length(metrics):
    """All values in this fixture are short. avg ≤ 30 chars."""
    for prompt_name, p in metrics["by_prompt"].items():
        # tumordepth has many empty predictions which aren't counted; if there are
        # any non-empty preds, avg should be reasonable.
        if p["avg_predicted_length"] > 0:
            assert p["avg_predicted_length"] <= 50, f"{prompt_name} avg pred length {p['avg_predicted_length']}"


def test_field_metrics(metrics):
    """gender has field_results; tumorsite does not. Field counts come from
    annotations where expected is non-empty.
    """
    g = metrics["by_prompt"]["gender"]
    assert len(g["field_metrics"]) == 1
    fm = g["field_metrics"][0]
    assert fm["field"] == "[male/female/unknown]"
    assert fm["filled"] == 10
    assert fm["matched"] == 9


def test_unknown_evaluation_mode_is_fatal():
    """A session not run in evaluation mode should fail aggregation."""
    session = {"evaluation_mode": "manual", "annotations": []}
    with pytest.raises(ValueError, match="evaluation_mode"):
        aggregate(session, center="MSCI")


def test_zero_eval_results_is_fatal():
    session = {
        "evaluation_mode": "evaluation",
        "annotations": [
            {"note_id": "1", "prompt_type": "x-msci", "evaluation_result": None}
        ],
    }
    with pytest.raises(ValueError, match="No annotations with evaluation_result"):
        aggregate(session, center="MSCI")


def test_unknown_match_type_counted_under_other():
    session = {
        "evaluation_mode": "evaluation",
        "annotations": [
            {
                "note_id": "1",
                "prompt_type": "weird-msci",
                "report_type": "X",
                "evaluation_result": {
                    "match_type": "totally_unknown",
                    "similarity_score": 0.5,
                },
            },
        ],
    }
    m = aggregate(session, center="MSCI")
    assert m["by_prompt"]["weird"]["counts"]["other"] == 1
    assert m["by_prompt"]["weird"]["counts"]["match"] == 0


def test_aggregator_never_reads_note_text(session):
    """Privacy: the aggregator output must not contain the sentinel from
    note_original_text.
    """
    metrics = aggregate(session, center="MSCI")
    serialized = json.dumps(metrics)
    assert "SENSITIVE_NOTE_TEXT_DO_NOT_LEAK" not in serialized
