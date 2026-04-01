"""Tests for note_context_classifier.py — clinical context classification."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from lib.note_context_classifier import (
    NoteContextResult,
    derive_context_from_split,
    classify_note_context,
    get_cached_context,
    clear_context_cache,
    _parse_classify_response,
    VALID_CONTEXTS,
)
from models.annotation_models import ClinicalEvent, NoteSplitResult


# ---------------------------------------------------------------------------
# derive_context_from_split tests
# ---------------------------------------------------------------------------


class TestDeriveContextFromSplit:
    """Test context derivation from existing NoteSplitResult."""

    def test_diagnosis_only(self):
        """Split with only diagnosis events → initial_diagnosis."""
        split = NoteSplitResult(
            shared_context="Patient info",
            events=[
                ClinicalEvent(event_text="Biopsy confirmed sarcoma", event_type="diagnosis"),
            ],
            original_text="...",
            was_split=True,
        )
        result = derive_context_from_split(split)
        assert result.clinical_context == "initial_diagnosis"
        assert result.source == "derived_from_split"

    def test_recurrence_only(self):
        """Split with recurrence events → recurrence."""
        split = NoteSplitResult(
            shared_context="Patient info",
            events=[
                ClinicalEvent(event_text="Recidiva pelvica", event_type="recurrence"),
            ],
            original_text="...",
            was_split=True,
        )
        result = derive_context_from_split(split)
        assert result.clinical_context == "recurrence"

    def test_diagnosis_and_recurrence(self):
        """Split with both diagnosis and recurrence → mixed."""
        split = NoteSplitResult(
            shared_context="Patient info",
            events=[
                ClinicalEvent(event_text="Diagnosis confirmed 2019", event_type="diagnosis"),
                ClinicalEvent(event_text="Recurrence in 2021", event_type="recurrence"),
            ],
            original_text="...",
            was_split=True,
        )
        result = derive_context_from_split(split)
        assert result.clinical_context == "mixed"

    def test_diagnosis_with_treatments(self):
        """Split with diagnosis + treatment events → mixed (timeline note)."""
        split = NoteSplitResult(
            shared_context="Patient info",
            events=[
                ClinicalEvent(event_text="Diagnosed in 2020", event_type="diagnosis"),
                ClinicalEvent(event_text="Chemo started 2020", event_type="chemotherapy"),
                ClinicalEvent(event_text="Surgery 2021", event_type="surgery"),
            ],
            original_text="...",
            was_split=True,
        )
        result = derive_context_from_split(split)
        assert result.clinical_context == "mixed"

    def test_follow_up_only(self):
        """Split with only follow-up events → follow_up."""
        split = NoteSplitResult(
            shared_context="Patient info",
            events=[
                ClinicalEvent(event_text="Routine check", event_type="follow_up"),
            ],
            original_text="...",
            was_split=True,
        )
        result = derive_context_from_split(split)
        assert result.clinical_context == "follow_up"

    def test_empty_events(self):
        """Split with no events → unknown."""
        split = NoteSplitResult(
            shared_context="",
            events=[],
            original_text="...",
            was_split=False,
        )
        result = derive_context_from_split(split)
        assert result.clinical_context == "unknown"

    def test_none_input(self):
        """None input → unknown."""
        result = derive_context_from_split(None)
        assert result.clinical_context == "unknown"


# ---------------------------------------------------------------------------
# _parse_classify_response tests
# ---------------------------------------------------------------------------


class TestParseClassifyResponse:
    """Test parsing LLM classification responses."""

    def test_valid_json(self):
        raw = '{"clinical_context": "recurrence", "confidence": 0.85, "reasoning": "Note mentions recidiva"}'
        result = _parse_classify_response(raw)
        assert result.clinical_context == "recurrence"
        assert result.confidence == 0.85
        assert result.source == "llm"

    def test_json_in_code_block(self):
        raw = '```json\n{"clinical_context": "initial_diagnosis", "confidence": 0.9, "reasoning": "First presentation"}\n```'
        result = _parse_classify_response(raw)
        assert result.clinical_context == "initial_diagnosis"

    def test_invalid_context_fallback(self):
        raw = '{"clinical_context": "invalid_type", "confidence": 0.5, "reasoning": "test"}'
        result = _parse_classify_response(raw)
        assert result.clinical_context == "unknown"

    def test_unparseable_response(self):
        raw = "This is not JSON at all"
        result = _parse_classify_response(raw)
        assert result.clinical_context == "unknown"
        assert result.confidence == 0.0

    def test_thinking_block_stripped(self):
        raw = '<unused94>thinking about it</unused94>\n{"clinical_context": "progression", "confidence": 0.8, "reasoning": "Disease worsening"}'
        result = _parse_classify_response(raw)
        assert result.clinical_context == "progression"

    def test_all_valid_contexts(self):
        """Every valid context value should parse correctly."""
        for ctx in VALID_CONTEXTS:
            raw = f'{{"clinical_context": "{ctx}", "confidence": 0.7, "reasoning": "test"}}'
            result = _parse_classify_response(raw)
            assert result.clinical_context == ctx


# ---------------------------------------------------------------------------
# classify_note_context tests (with mocked LLM)
# ---------------------------------------------------------------------------


class TestClassifyNoteContext:
    """Test the LLM-based classification path."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        clear_context_cache()
        yield
        clear_context_cache()

    @pytest.mark.asyncio
    async def test_llm_classification(self):
        """Test successful LLM classification."""
        mock_client = MagicMock()
        mock_client.config = {}
        mock_client.agenerate = AsyncMock(return_value={
            "raw": '{"clinical_context": "recurrence", "confidence": 0.9, "reasoning": "Recidiva mentioned"}'
        })

        result = await classify_note_context(
            note_text="Paziente con recidiva pelvica",
            vllm_client=mock_client,
            session_id="test-session",
            note_id="test-note",
        )
        assert result.clinical_context == "recurrence"
        assert result.source == "llm"

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Second call for same note should use cache."""
        mock_client = MagicMock()
        mock_client.config = {}
        mock_client.agenerate = AsyncMock(return_value={
            "raw": '{"clinical_context": "initial_diagnosis", "confidence": 0.8, "reasoning": "test"}'
        })

        # First call
        result1 = await classify_note_context(
            note_text="Biopsy confirmed", vllm_client=mock_client,
            session_id="s1", note_id="n1",
        )
        # Second call — should hit cache
        result2 = await classify_note_context(
            note_text="Biopsy confirmed", vllm_client=mock_client,
            session_id="s1", note_id="n1",
        )

        assert result1.clinical_context == result2.clinical_context
        assert mock_client.agenerate.call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_llm_failure_returns_unknown(self):
        """LLM failure should return 'unknown' instead of raising."""
        mock_client = MagicMock()
        mock_client.config = {}
        mock_client.agenerate = AsyncMock(side_effect=Exception("Connection error"))

        result = await classify_note_context(
            note_text="Some note", vllm_client=mock_client,
            session_id="s1", note_id="n1",
        )
        assert result.clinical_context == "unknown"
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# NoteContextResult tests
# ---------------------------------------------------------------------------


class TestNoteContextResult:
    def test_to_dict(self):
        result = NoteContextResult(
            clinical_context="recurrence",
            confidence=0.85,
            reasoning="test",
            source="llm",
        )
        d = result.to_dict()
        assert d["clinical_context"] == "recurrence"
        assert d["confidence"] == 0.85
        assert d["source"] == "llm"


# ---------------------------------------------------------------------------
# Prompt placeholder tests
# ---------------------------------------------------------------------------


class TestPromptPlaceholderReplacement:
    """Test that {{clinical_context}} is properly replaced in prompts."""

    def test_placeholder_replaced(self):
        from lib.prompt_wrapper import update_prompt_placeholders

        prompt = "Context: {{clinical_context}}. Note: {{note_original_text}}"
        result = update_prompt_placeholders(
            prompt, note_text="test note", clinical_context="recurrence"
        )
        assert "recurrence" in result
        assert "{{clinical_context}}" not in result

    def test_placeholder_default_unknown(self):
        from lib.prompt_wrapper import update_prompt_placeholders

        prompt = "Context: {{clinical_context}}. Note: {{note_original_text}}"
        result = update_prompt_placeholders(prompt, note_text="test note")
        assert "unknown" in result

    def test_prompts_json_contains_placeholder(self):
        """Verify that modified prompts contain the {{clinical_context}} placeholder."""
        import json
        from pathlib import Path

        prompts_path = Path(__file__).parent.parent / "data" / "prompts" / "prompts.json"
        with open(prompts_path) as f:
            prompts = json.load(f)

        # Check all 3 centers for all 3 affected prompt types
        target_prompts = {
            "INT": ["stage_at_diagnosis-int", "recurrencetype-int", "recur_or_prog-int"],
            "MSCI": ["stage_at_diagnosis", "recurrencetype", "recur_or_prog"],
            "VGR": ["stage_at_diagnosis", "recurrencetype", "recur_or_prog"],
        }

        for center, prompt_keys in target_prompts.items():
            center_prompts = prompts.get(center, {})
            for key in prompt_keys:
                if key in center_prompts:
                    template = center_prompts[key].get("template", "")
                    assert "{{clinical_context}}" in template, (
                        f"Missing {{{{clinical_context}}}} in {center}/{key}"
                    )
