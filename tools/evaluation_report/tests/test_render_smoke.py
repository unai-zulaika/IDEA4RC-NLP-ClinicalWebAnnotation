"""Spec section 'Renderer': end-to-end smoke through the four modules, plus the
privacy sentinel check on the rendered Markdown.
"""
from pathlib import Path

import pytest

from aggregator import aggregate, load_session
from classifier import ClassifierConfig, classify_all
from renderer import render_markdown
from sampler import sample_errors

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_session.json"
SENTINEL = "SENSITIVE_NOTE_TEXT_DO_NOT_LEAK"


@pytest.fixture
def rendered():
    session = load_session(FIXTURE)
    metrics = aggregate(session, center="MSCI")
    classify_all(metrics, ClassifierConfig())
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=5, seed=42)
    return render_markdown(metrics)


def test_sentinel_not_in_rendered_markdown(rendered):
    """End-to-end privacy contract: no note text reaches the report."""
    assert SENTINEL not in rendered


def test_all_three_bucket_headers_present(rendered):
    assert "## Reliable" in rendered
    assert "## Usable as suggestions" in rendered
    assert "## Unreliable" in rendered


def test_summary_sentence_rendered(rendered):
    assert "1 variables reliably extracted" in rendered
    assert "1 usable" in rendered
    assert "2 unreliable" in rendered


def test_bucket_assignments(rendered):
    """gender → Reliable; tumorsite → Usable; tumordepth + histological → Unreliable."""
    # Check that prompts appear under their expected sections by ordering markers
    reliable_idx = rendered.index("## Reliable")
    usable_idx = rendered.index("## Usable as suggestions")
    unreliable_idx = rendered.index("## Unreliable")

    # gender appears between Reliable header and Usable header
    gender_idx = rendered.index("`gender`")
    assert reliable_idx < gender_idx < usable_idx

    # tumorsite appears between Usable and Unreliable
    tumorsite_idx = rendered.index("`tumorsite`")
    assert usable_idx < tumorsite_idx < unreliable_idx

    # tumordepth appears after Unreliable
    tumordepth_idx = rendered.index("`tumordepth`")
    assert unreliable_idx < tumordepth_idx


def test_sample_errors_section_includes_redacted_marker(rendered):
    """Every sample row uses [REDACTED] for the note text."""
    assert "`[REDACTED]`" in rendered


def test_observation_placeholder_present(rendered):
    """Every prompt's detail block has `_TODO_` observation; report has 3 trailing
    sections (Lessons learned, Production vs NLP, Key takeaway) using `_TODO:`.
    """
    assert rendered.count("_TODO_") == 4   # one per prompt
    # Trailing sections use the "TODO:" form with explanatory text
    assert "TODO: write 3" in rendered  # Lessons learned
    assert "TODO: optional" in rendered  # Production vs NLP
    assert "TODO: 2" in rendered  # Key takeaway


def test_empty_bucket_renders_none_placeholder():
    """Build a tiny session where all prompts go to Reliable, leaving Usable
    and Unreliable empty. Confirm the section headers still render with _None._
    """
    session = {
        "session_id": "tiny",
        "evaluation_mode": "evaluation",
        "annotations": [
            {
                "note_id": str(i),
                "prompt_type": "perfect-msci",
                "report_type": "X",
                "evaluation_result": {
                    "match_type": "match",
                    "similarity_score": 1.0,
                    "expected_annotation": "ok",
                    "predicted_annotation": "ok",
                    "field_results": [],
                },
            }
            for i in range(12)
        ],
    }
    metrics = aggregate(session, center="MSCI")
    classify_all(metrics, ClassifierConfig())
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=5, seed=42)
    out = render_markdown(metrics)
    assert "## Reliable" in out
    assert "## Usable" in out
    assert "## Unreliable" in out
    assert "_None._" in out  # empty buckets surface this placeholder


def test_pipe_escaped_in_table_cells():
    """Annotation values with `|` shouldn't break Markdown tables in the auto-reason cell."""
    session = {
        "session_id": "pipe-test",
        "evaluation_mode": "evaluation",
        "annotations": [
            {
                "note_id": str(i),
                "prompt_type": "pipey-msci",
                "report_type": "X",
                "evaluation_result": {
                    "match_type": "mismatch" if i < 5 else "match",
                    "similarity_score": 0.5,
                    "expected_annotation": "a | b | c",
                    "predicted_annotation": "x | y | z",
                    "field_results": [],
                },
            }
            for i in range(15)
        ],
    }
    # We need auto_reason to contain a pipe — but our auto-reason templates
    # don't usually contain |. Force-inject one and re-render.
    metrics = aggregate(session, center="MSCI")
    classify_all(metrics, ClassifierConfig())
    metrics["by_prompt"]["pipey"]["auto_reason"] = "rate is | a | b | c"
    sample_errors(session, metrics, center="MSCI", samples_per_prompt=5, seed=42)
    out = render_markdown(metrics)
    # The pipe inside the table cell must be escaped
    assert r"rate is \| a \| b \| c" in out


def test_strict_undefined_catches_missing_field():
    """If a required top-level field is absent from the metrics dict, the renderer
    should fail loudly (KeyError before Jinja2 even runs).
    """
    bad_metrics = {
        "center": "X",
        # missing generated_at, session_id, etc.
    }
    with pytest.raises((KeyError, Exception)):
        render_markdown(bad_metrics)
