# Sliding-Window Note Chunker Design

**Date:** 2026-03-04
**Status:** Approved

## Problem

MedGemma 1.5 4B-IT has an 8192-token context window. The annotation pipeline passes the full clinical note + prompt template + few-shot examples to the model with no token counting or truncation. When the combined input exceeds the context window, vLLM silently fails or raises an error, producing no annotation.

Italian pathology reports and multi-visit clinical notes can easily exceed the available note budget (~5000–6000 tokens after prompt overhead).

## Approach: Sliding Window with First Confident Answer

Split long notes into overlapping sentence-boundary-respecting chunks. Process chunks sequentially, returning on the first chunk that yields a confident (non-null) answer. Record which chunk produced the answer in metadata.

**Why not alternatives:**
- Simple truncation: silently drops clinical content that may contain the target field.
- Extractive summarization: adds latency and a second model/NLP dependency.
- Sliding window with first confident answer: balanced — full coverage, minimal overhead for notes that fit, stops early once found.

## Architecture

```
_process_single_prompt()
  │
  ├─ Build prompt-without-note (template + fewshots, empty note placeholder)
  ├─ overhead = count_tokens(prompt_without_note)
  ├─ available = context_window − overhead − output_buffer
  │
  ├─ count_tokens(note_text) ≤ available?  →  normal path (unchanged)
  │
  └─ note too long  →  chunking path
        chunks = chunk_note(note_text, available, overlap_sentences=2)
        for i, chunk in enumerate(chunks):
            prompt = _get_prompt(task_key, fewshots, chunk, ...)
            result = await _run_inference(prompt)
            if is_confident(result) OR last chunk:
                result.chunk_info = ChunkInfo(
                    was_chunked=True,
                    total_chunks=len(chunks),
                    answer_chunk_index=i+1,
                    chunks_exhausted=(not confident and last)
                )
                return result
```

## Components

### New: `backend/lib/note_chunker.py`

Class `NoteChunker` (singleton, lazy init):

- **`count_tokens(text: str) -> int`**
  Uses `AutoTokenizer.from_pretrained(model_path)` loaded from `vllm_config.json`.
  Falls back to `len(text) // 4` (char approximation) if tokenizer unavailable; logs WARNING.

- **`calculate_available_tokens(prompt_without_note: str, output_buffer: int) -> int`**
  Returns `context_window - count_tokens(prompt_without_note) - output_buffer`.

- **`chunk_note(note_text: str, available_tokens: int, overlap_sentences: int = 2) -> List[str]`**
  1. Split on sentence boundaries: `. `, `?\n`, `!\n`, `\n\n` — works for Italian text.
  2. Greedy packing: add sentences until token budget reached.
  3. Keep last `overlap_sentences` from previous chunk as overlap.
  4. Fallback: if a single sentence exceeds budget, split at word boundaries.

- **`is_confident_result(annotation_text: str) -> bool`**
  Returns `False` if `annotation_text.strip().lower()` matches null-like patterns:
  `{"", "unknown", "n/a", "not mentioned", "not found", "not available", "nessuno", "non specificato"}`.
  Otherwise `True`.

### Modified: `backend/models/schemas.py`

New model (add before `AnnotationResult`):
```python
class ChunkInfo(BaseModel):
    was_chunked: bool = False
    total_chunks: Optional[int] = None
    answer_chunk_index: Optional[int] = None  # 1-indexed
    chunks_exhausted: bool = False
```

Add to `AnnotationResult`:
```python
chunk_info: Optional[ChunkInfo] = None
```

Add to `SessionAnnotation`:
```python
chunk_info: Optional[ChunkInfo] = None
```

### Modified: `backend/routes/annotate.py`

In `_process_single_prompt()` (around line 506), after fewshot retrieval:

1. Build `prompt_without_note` by calling `_get_prompt()` with `note_text=""`.
2. Compute `available_tokens` via `NoteChunker`.
3. If `count_tokens(note_text) <= available_tokens`: proceed normally (no change to hot path).
4. Else: chunk, iterate with early stop, attach `chunk_info` to result.

Fewshot retrieval continues to use the **full note** (not per-chunk) for FAISS similarity — acceptable.

### Modified: `backend/config/vllm_config.json`

Add:
```json
"context_window": 8192
```

MedGemma 1.5 4B-IT supports 8192 tokens per Google's published specs.

## Token Budget Calculation

| Component | Tokens (estimate) |
|-----------|-------------------|
| System message | ~40 |
| Prompt template (fast) | ~200–400 |
| 1 few-shot example | ~150–300 |
| Output buffer (fast mode) | 1024 |
| Output buffer (standard) | 4096 |
| **Available for note (fast, 1 fewshot)** | **~6500** |
| **Available for note (standard, 5 fewshots)** | **~2500–3500** |

Standard mode with 5 few-shots is the most constrained path.

## Error Handling

- Tokenizer load failure → WARNING + char-based fallback (`len(text) // 4`).
- All chunks fail vLLM inference → propagate last error unchanged (no regression).
- `context_window` missing from config → default `8192`.
- Note splits into only 1 chunk (edge case: note just over budget after approximation) → treated as normal, no `chunk_info` attached.

## Testing

### Unit tests (`backend/test_note_chunker.py`)
- `count_tokens`: verify fallback mode returns `len(text) // 4`.
- `chunk_note`: short note → 1 chunk; long note → multiple chunks; verify overlap; verify word-level fallback for giant sentences.
- `is_confident_result`: test null patterns in English and Italian.

### Integration test
- Mock vLLM client to return predictable responses.
- Send a note > 8192 chars, assert `chunk_info.was_chunked == True`.
- Assert early stop: if chunk 2 returns a confident answer, chunk 3 is never called.

### Manual verification
- Use an existing long Italian note from `backend/sessions/`.
- Confirm annotation succeeds and `chunk_info` appears in the saved session JSON.

## Files Changed

| File | Change |
|------|--------|
| `backend/lib/note_chunker.py` | **NEW** |
| `backend/models/schemas.py` | Add `ChunkInfo`, extend `AnnotationResult` + `SessionAnnotation` |
| `backend/routes/annotate.py` | Integrate chunking in `_process_single_prompt()` |
| `backend/config/vllm_config.json` | Add `context_window: 8192` |
| `backend/test_note_chunker.py` | **NEW** (unit tests) |
