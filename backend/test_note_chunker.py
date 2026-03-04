"""Tests for sliding-window note chunker and related schemas."""
import pytest
from models.schemas import ChunkInfo, AnnotationResult


# ─────────────────────────────────────────────────────────────
# NoteChunker unit tests (added in Task 3)
# ─────────────────────────────────────────────────────────────
from lib.note_chunker import NoteChunker


@pytest.fixture
def chunker():
    """Chunker in approximation mode (no real tokenizer needed in tests)."""
    c = NoteChunker(context_window=100)
    c._using_approximation = True
    c._tokenizer = None
    return c


# ── count_tokens ──────────────────────────────────────────────────────────
def test_count_tokens_approximation(chunker):
    # 40 chars → 40//4 = 10 tokens
    assert chunker.count_tokens("a" * 40) == 10


def test_count_tokens_empty(chunker):
    assert chunker.count_tokens("") == 1  # max(1, 0//4)


# ── calculate_available_tokens ────────────────────────────────────────────
def test_calculate_available_tokens(chunker):
    # Use a larger context_window so result exceeds the 100-token minimum.
    # chunker.context_window=100; override to 400 for this test.
    chunker.context_window = 400
    # 200 chars prompt → 200//4 = 50 tokens overhead. output_buffer=20.
    # available = 400 - 50 - 20 = 330
    prompt = "x" * 200
    assert chunker.calculate_available_tokens(prompt, 20) == 330


def test_calculate_available_tokens_minimum(chunker):
    # Even if overhead is huge, at least 100 tokens returned
    huge_prompt = "x" * 10000
    assert chunker.calculate_available_tokens(huge_prompt, 100) == 100


# ── chunk_note: short note ────────────────────────────────────────────────
def test_chunk_note_fits_returns_single_chunk(chunker):
    short_note = "Patient is 45 years old."
    chunks = chunker.chunk_note(short_note, available_tokens=500)
    assert chunks == [short_note]


# ── chunk_note: long note ─────────────────────────────────────────────────
def test_chunk_note_splits_long_note(chunker):
    # Each sentence: ~10 chars → ~2 tokens. Available: 6 tokens.
    # So roughly 3 sentences per chunk.
    note = ". ".join([f"Sentence {i} here" for i in range(20)])
    chunks = chunker.chunk_note(note, available_tokens=6)
    assert len(chunks) > 1


def test_chunk_note_overlap(chunker):
    sentences = [f"Sentence number {i} with some text here." for i in range(30)]
    note = " ".join(sentences)
    chunks = chunker.chunk_note(note, available_tokens=20, overlap_sentences=2)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.strip()) > 0


def test_chunk_note_single_oversized_sentence(chunker):
    # A note that is one very long sentence (no sentence boundaries)
    # Should fall back to word splitting
    long_sentence = " ".join([f"word{i}" for i in range(200)])
    chunks = chunker.chunk_note(long_sentence, available_tokens=10)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.strip()) > 0


# ── is_confident_result ───────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("T2", True),
    ("Grade 3", True),
    ("Female", True),
    ("", False),
    ("unknown", False),
    ("Unknown", False),
    ("UNKNOWN", False),
    ("n/a", False),
    ("N/A", False),
    ("not mentioned", False),
    ("Not Mentioned", False),
    ("not found", False),
    ("not available", False),
    ("nessuno", False),
    ("non specificato", False),
    ("ERROR: timeout", False),
])
def test_is_confident_result(text, expected):
    assert NoteChunker.is_confident_result(text) is expected


def test_chunk_info_schema_fields():
    ci = ChunkInfo(was_chunked=True, total_chunks=3, answer_chunk_index=2, chunks_exhausted=False)
    assert ci.was_chunked is True
    assert ci.total_chunks == 3
    assert ci.answer_chunk_index == 2
    assert ci.chunks_exhausted is False


def test_chunk_info_defaults():
    ci = ChunkInfo()
    assert ci.was_chunked is False
    assert ci.total_chunks is None
    assert ci.answer_chunk_index is None
    assert ci.chunks_exhausted is False


def test_annotation_result_has_chunk_info():
    ar = AnnotationResult(prompt_type="test", annotation_text="M")
    assert ar.chunk_info is None  # optional, defaults to None
    ci = ChunkInfo(was_chunked=True, total_chunks=2, answer_chunk_index=1)
    ar2 = AnnotationResult(prompt_type="test", annotation_text="M", chunk_info=ci)
    assert ar2.chunk_info.was_chunked is True


# ─────────────────────────────────────────────────────────────
# Integration tests for _process_single_prompt() (Task 4)
# ─────────────────────────────────────────────────────────────
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def reset_chunker_singleton():
    """Ensure NoteChunker singleton is fresh for each test."""
    NoteChunker.reset_instance()
    yield
    NoteChunker.reset_instance()


def _make_mock_vllm(responses: list):
    """Return a mock vllm_client whose agenerate cycles through responses."""
    client = MagicMock()
    client.config = {
        "vllm_endpoint": "http://localhost:8000/v1",
        "model_name": "test-model",
    }
    call_count = {"n": 0}

    async def _agenerate(**kwargs):
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return {"raw": responses[idx], "normalized": responses[idx]}

    client.agenerate = AsyncMock(side_effect=_agenerate)
    return client, call_count


def test_short_note_no_chunking():
    """A note that fits the context window is NOT split (chunk_info is None)."""
    from routes.annotate import _process_single_prompt, _PROMPTS, _ensure_prompts_loaded
    _ensure_prompts_loaded()
    if not _PROMPTS:
        pytest.skip("No prompts loaded — skipping integration test")

    prompt_type = next(iter(_PROMPTS))
    short_note = "Patient is 45 years old. Female."

    mock_client, calls = _make_mock_vllm([
        '{"final_output": "Female", "evidence": "Female.", "reasoning": "stated", "is_negated": false, "date": null}'
    ])

    with patch("routes.annotate._vllm_semaphore", asyncio.Semaphore(10)):
        result = asyncio.run(
            _process_single_prompt(
                prompt_type=prompt_type,
                note_text=short_note,
                csv_date=None,
                vllm_client=mock_client,
                use_structured=False,
                request_use_fewshots=False,
                request_fewshot_k=0,
                fast_mode=True,
            )
        )

    assert result.chunk_info is None
    assert calls["n"] == 1  # Only one inference call


def test_long_note_chunked_early_stop():
    """
    A note too long to fit is split into chunks.
    Processing stops at the first confident answer.
    chunk_info reflects which chunk answered.
    """
    from routes.annotate import _process_single_prompt, _PROMPTS, _ensure_prompts_loaded
    _ensure_prompts_loaded()
    if not _PROMPTS:
        pytest.skip("No prompts loaded — skipping integration test")

    prompt_type = next(iter(_PROMPTS))
    # ~50,000 chars — definitely exceeds any context window
    long_note = " ".join([f"Sentence {i} contains clinical information." for i in range(3000)])

    # First chunk returns "unknown" (not confident), second returns a real answer
    responses = [
        '{"final_output": "unknown", "evidence": "", "reasoning": "not found", "is_negated": false, "date": null}',
        '{"final_output": "T2", "evidence": "tumor T2", "reasoning": "T2 stated", "is_negated": false, "date": null}',
    ]
    mock_client, calls = _make_mock_vllm(responses)

    with patch("routes.annotate._vllm_semaphore", asyncio.Semaphore(10)):
        result = asyncio.run(
            _process_single_prompt(
                prompt_type=prompt_type,
                note_text=long_note,
                csv_date=None,
                vllm_client=mock_client,
                use_structured=False,
                request_use_fewshots=False,
                request_fewshot_k=0,
                fast_mode=True,
            )
        )

    assert result.chunk_info is not None
    assert result.chunk_info.was_chunked is True
    assert result.chunk_info.answer_chunk_index == 2
    assert result.chunk_info.chunks_exhausted is False
    assert calls["n"] == 2  # Stopped after chunk 2


def test_long_note_all_chunks_exhausted():
    """If all chunks return unknown, chunks_exhausted=True and last chunk result is returned."""
    from routes.annotate import _process_single_prompt, _PROMPTS, _ensure_prompts_loaded
    _ensure_prompts_loaded()
    if not _PROMPTS:
        pytest.skip("No prompts loaded — skipping integration test")

    prompt_type = next(iter(_PROMPTS))
    long_note = " ".join([f"Sentence {i} contains clinical information." for i in range(3000)])

    # All chunks return "unknown"
    responses = [
        '{"final_output": "unknown", "evidence": "", "reasoning": "not found", "is_negated": false, "date": null}'
    ]
    mock_client, calls = _make_mock_vllm(responses)

    with patch("routes.annotate._vllm_semaphore", asyncio.Semaphore(10)):
        result = asyncio.run(
            _process_single_prompt(
                prompt_type=prompt_type,
                note_text=long_note,
                csv_date=None,
                vllm_client=mock_client,
                use_structured=False,
                request_use_fewshots=False,
                request_fewshot_k=0,
                fast_mode=True,
            )
        )

    assert result.chunk_info is not None
    assert result.chunk_info.was_chunked is True
    assert result.chunk_info.chunks_exhausted is True
    assert result.chunk_info.answer_chunk_index == result.chunk_info.total_chunks
