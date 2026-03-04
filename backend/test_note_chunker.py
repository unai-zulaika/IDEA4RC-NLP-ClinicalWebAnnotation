"""Tests for sliding-window note chunker and related schemas."""
import pytest
from models.schemas import ChunkInfo, AnnotationResult


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
