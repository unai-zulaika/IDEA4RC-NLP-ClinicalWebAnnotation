"""Tests for note splitting and result aggregation."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from lib.note_splitter import (
    _parse_split_response,
    _build_split_prompt,
    build_sub_note,
    split_history_note,
    clear_split_cache,
    _split_cache,
)
from lib.result_aggregator import (
    aggregate_results,
    _normalize_for_dedup,
    _normalize_date,
    _is_null_result,
    _are_duplicates,
)
from models.annotation_models import ClinicalEvent, NoteSplitResult
from models.schemas import AnnotationResult, AnnotationValue


# --- Note Splitter Tests ---


class TestParseSplitResponse:
    """Test parsing of LLM split responses."""

    def test_valid_json_response(self):
        raw = json.dumps({
            "shared_context": "Patient with sarcoma of the right thigh",
            "events": [
                {"event_text": "Surgery on 15.03.2024", "event_type": "surgery", "event_date": "15/03/2024"},
                {"event_text": "Chemotherapy DXL+GCB started 01.06.2024", "event_type": "chemotherapy", "event_date": "01/06/2024"},
            ]
        })
        result = _parse_split_response(raw, "original note text")
        assert result.was_split is True
        assert len(result.events) == 2
        assert result.events[0].event_type == "surgery"
        assert result.events[1].event_type == "chemotherapy"
        assert result.shared_context == "Patient with sarcoma of the right thigh"

    def test_single_event_not_split(self):
        raw = json.dumps({
            "shared_context": "Patient info",
            "events": [
                {"event_text": "Only one event here", "event_type": "other"}
            ]
        })
        result = _parse_split_response(raw, "original")
        assert result.was_split is False
        assert len(result.events) == 1

    def test_empty_events_fallback(self):
        raw = json.dumps({"shared_context": "Patient", "events": []})
        result = _parse_split_response(raw, "original note")
        assert result.was_split is False
        assert len(result.events) == 1
        assert result.events[0].event_text == "original note"

    def test_invalid_json_fallback(self):
        raw = "This is not valid JSON at all"
        result = _parse_split_response(raw, "original note")
        assert result.was_split is False
        assert result.events[0].event_text == "original note"

    def test_markdown_wrapped_json(self):
        inner = json.dumps({
            "shared_context": "Patient",
            "events": [
                {"event_text": "Event 1", "event_type": "surgery"},
                {"event_text": "Event 2", "event_type": "chemotherapy"},
            ]
        })
        raw = f"Here's the result:\n```json\n{inner}\n```"
        result = _parse_split_response(raw, "original")
        assert result.was_split is True
        assert len(result.events) == 2

    def test_thinking_blocks_stripped(self):
        inner = json.dumps({
            "shared_context": "Patient",
            "events": [
                {"event_text": "Event 1", "event_type": "surgery"},
                {"event_text": "Event 2", "event_type": "radiotherapy"},
            ]
        })
        raw = f"<unused94>thinking some thought</unused94>{inner}"
        result = _parse_split_response(raw, "original")
        assert result.was_split is True
        assert len(result.events) == 2

    def test_empty_event_text_filtered(self):
        raw = json.dumps({
            "shared_context": "Patient",
            "events": [
                {"event_text": "Valid event", "event_type": "surgery"},
                {"event_text": "", "event_type": "other"},
                {"event_text": "   ", "event_type": "other"},
            ]
        })
        result = _parse_split_response(raw, "original")
        assert result.was_split is False  # Only 1 valid event
        assert len(result.events) == 1


class TestBuildSubNote:
    """Test sub-note construction."""

    def test_with_shared_context(self):
        result = build_sub_note("Patient diagnosed with sarcoma",
                                ClinicalEvent(event_text="Surgery on 15.03.2024", event_type="surgery"))
        assert result == "Patient diagnosed with sarcoma\n\nSurgery on 15.03.2024"

    def test_without_shared_context(self):
        result = build_sub_note("", ClinicalEvent(event_text="Surgery on 15.03.2024", event_type="surgery"))
        assert result == "Surgery on 15.03.2024"

    def test_whitespace_only_context(self):
        result = build_sub_note("   ", ClinicalEvent(event_text="Event text", event_type="other"))
        assert result == "Event text"


class TestBuildSplitPrompt:
    """Test prompt construction."""

    def test_prompt_contains_note_text(self):
        prompt = _build_split_prompt("This is the note text")
        assert "This is the note text" in prompt
        assert "clinical events" in prompt.lower()


@pytest.mark.asyncio
class TestSplitHistoryNote:
    """Test the async split function."""

    async def test_successful_split(self):
        mock_client = AsyncMock()
        mock_client.agenerate.return_value = {
            "raw": json.dumps({
                "shared_context": "Patient with sarcoma",
                "events": [
                    {"event_text": "Surgery 15.03.2024", "event_type": "surgery", "event_date": "15/03/2024"},
                    {"event_text": "Chemo started 01.06.2024", "event_type": "chemotherapy", "event_date": "01/06/2024"},
                ]
            })
        }

        clear_split_cache()
        result = await split_history_note("note text", mock_client, "sess1", "note1")
        assert result.was_split is True
        assert len(result.events) == 2
        mock_client.agenerate.assert_called_once()

    async def test_caching(self):
        mock_client = AsyncMock()
        mock_client.agenerate.return_value = {
            "raw": json.dumps({
                "shared_context": "Patient",
                "events": [
                    {"event_text": "Event 1", "event_type": "surgery"},
                    {"event_text": "Event 2", "event_type": "chemotherapy"},
                ]
            })
        }

        clear_split_cache()
        # First call
        result1 = await split_history_note("note text", mock_client, "sess1", "note1")
        assert mock_client.agenerate.call_count == 1

        # Second call should use cache
        result2 = await split_history_note("note text", mock_client, "sess1", "note1")
        assert mock_client.agenerate.call_count == 1  # Not called again
        assert result2.was_split == result1.was_split

    async def test_llm_failure_fallback(self):
        mock_client = AsyncMock()
        mock_client.agenerate.side_effect = Exception("LLM unavailable")

        clear_split_cache()
        result = await split_history_note("original note", mock_client, "sess1", "note1")
        assert result.was_split is False
        assert result.events[0].event_text == "original note"

    async def test_cache_clearing(self):
        clear_split_cache()
        _split_cache[("sess1", "note1")] = NoteSplitResult(
            shared_context="test", events=[], original_text="test", was_split=False
        )
        assert ("sess1", "note1") in _split_cache
        clear_split_cache("sess1")
        assert ("sess1", "note1") not in _split_cache


# --- Result Aggregator Tests ---


class TestNormalization:
    """Test text and date normalization."""

    def test_normalize_for_dedup(self):
        assert _normalize_for_dedup("  Hello World.  ") == "hello world"
        assert _normalize_for_dedup("SURGERY on 15.03.2024") == "surgery on 15.03.2024"

    def test_normalize_date_dd_mm_yyyy(self):
        assert _normalize_date("15/03/2024") == "2024-03-15"
        assert _normalize_date("15.03.2024") == "2024-03-15"

    def test_normalize_date_iso(self):
        assert _normalize_date("2024-03-15") == "2024-03-15"

    def test_normalize_date_mm_yyyy(self):
        assert _normalize_date("03/2024") == "2024-03"
        assert _normalize_date("03.2024") == "2024-03"

    def test_normalize_date_year_only(self):
        assert _normalize_date("2024") == "2024"

    def test_normalize_date_empty(self):
        assert _normalize_date("") is None
        assert _normalize_date(None) is None


class TestNullDetection:
    """Test null/empty result detection."""

    def test_null_patterns(self):
        assert _is_null_result("Unknown") is True
        assert _is_null_result("N/A") is True
        assert _is_null_result("Not mentioned") is True
        assert _is_null_result("Not applicable") is True
        assert _is_null_result("") is True

    def test_non_null(self):
        assert _is_null_result("Surgery on 15.03.2024") is False
        assert _is_null_result("Grade 2") is False


class TestDuplicateDetection:
    """Test annotation deduplication."""

    def test_exact_duplicates(self):
        assert _are_duplicates("Surgery on 15.03.2024", "surgery on 15.03.2024") is True

    def test_trailing_punctuation(self):
        assert _are_duplicates("Surgery on 15.03.2024.", "Surgery on 15.03.2024") is True

    def test_different_annotations(self):
        assert _are_duplicates("Surgery on 15.03.2024", "Chemotherapy started 01.06.2024") is False

    def test_substring_dedup(self):
        assert _are_duplicates(
            "Surgery on 15.03.2024 with resection",
            "Surgery on 15.03.2024 with resection of tumor margin"
        ) is True

    def test_same_date_similar_text(self):
        assert _are_duplicates(
            "Pre-operative chemotherapy started on 15/03/2024",
            "Pre-operative chemotherapy started on 15.03.2024"
        ) is True


class TestAggregateResults:
    """Test result aggregation."""

    def _make_result(self, text: str, status: str = "success", prompt_type: str = "surgery") -> AnnotationResult:
        return AnnotationResult(
            prompt_type=prompt_type,
            annotation_text=text,
            values=[AnnotationValue(value=text, evidence_spans=[])],
            evidence_spans=[],
            reasoning=f"Reasoning for {text}",
            status=status,
        )

    def test_single_result(self):
        results = [self._make_result("Surgery on 15.03.2024")]
        agg = aggregate_results(results, "surgery", total_events=1)
        assert agg.annotation_text == "Surgery on 15.03.2024"
        assert agg.multi_value_info is not None
        assert agg.multi_value_info["was_split"] is True

    def test_multiple_unique_results(self):
        results = [
            self._make_result("Surgery on 15.03.2024"),
            self._make_result("Surgery on 20.06.2023"),
            self._make_result("Surgery on 10.01.2022"),
        ]
        agg = aggregate_results(results, "surgery", total_events=3)
        assert len(agg.values) == 3
        assert agg.multi_value_info["unique_values_extracted"] == 3

    def test_deduplication(self):
        results = [
            self._make_result("Surgery on 15.03.2024"),
            self._make_result("Surgery on 15.03.2024"),  # Duplicate
            self._make_result("Surgery on 20.06.2023"),
        ]
        agg = aggregate_results(results, "surgery", total_events=3)
        assert len(agg.values) == 2
        assert agg.multi_value_info["unique_values_extracted"] == 2

    def test_null_results_filtered(self):
        results = [
            self._make_result("Surgery on 15.03.2024"),
            self._make_result("Unknown"),
            self._make_result("Not mentioned"),
        ]
        agg = aggregate_results(results, "surgery", total_events=3)
        assert len(agg.values) == 1
        assert agg.values[0].value == "Surgery on 15.03.2024"

    def test_all_null_results(self):
        results = [
            self._make_result("Unknown"),
            self._make_result("N/A"),
        ]
        agg = aggregate_results(results, "surgery", total_events=2)
        assert agg.multi_value_info["unique_values_extracted"] == 0

    def test_empty_results(self):
        agg = aggregate_results([], "surgery", total_events=0)
        assert agg.status == "error"
        assert agg.multi_value_info["unique_values_extracted"] == 0

    def test_chronological_ordering(self):
        results = [
            self._make_result("Surgery on 20.06.2024"),
            self._make_result("Surgery on 15.03.2022"),
            self._make_result("Surgery on 10.01.2023"),
        ]
        agg = aggregate_results(results, "surgery", total_events=3)
        # Values should be sorted by date (chronological)
        dates = [v.value for v in agg.values]
        assert "15.03.2022" in dates[0]  # Earliest first

    def test_status_success_if_any_success(self):
        results = [
            self._make_result("Surgery on 15.03.2024", status="success"),
            self._make_result("Error occurred", status="error"),
        ]
        agg = aggregate_results(results, "surgery", total_events=2)
        assert agg.status == "success"

    def test_reasoning_combined(self):
        results = [
            self._make_result("Surgery on 15.03.2024"),
            self._make_result("Surgery on 20.06.2023"),
        ]
        agg = aggregate_results(results, "surgery", total_events=2)
        assert agg.reasoning is not None
        assert " | " in agg.reasoning
