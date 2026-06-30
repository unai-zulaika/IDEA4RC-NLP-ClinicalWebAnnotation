"""RAG retrieval over the few-shot pool using sentence-transformers/MiniLM.

For each test note we embed both the pool notes and the test note, and pick
the top-k most similar pool entries to use as few-shot examples.
"""
from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    model = get_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def top_k(query_text: str, pool_texts: list[str], k: int) -> list[int]:
    """Return indices into pool_texts of the top-k most similar entries."""
    if not pool_texts or k <= 0:
        return []
    k = min(k, len(pool_texts))
    q = embed([query_text])[0]
    pool_emb = embed(pool_texts)
    sims = pool_emb @ q
    return list(np.argsort(-sims)[:k])
