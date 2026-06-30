"""FBK-style EM + PM evaluation via cosine similarity."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rag_retriever import embed


@dataclass
class EvalResult:
    n: int
    exact_match: int
    partial_match: int
    mismatch: int
    accuracy: float  # (EM + PM) / N
    em_rate: float
    pm_rate: float
    avg_similarity: float


def _norm(s: str) -> str:
    return " ".join(s.strip().split())


def evaluate(pairs: list[tuple[str, str]], pm_threshold: float = 0.6) -> EvalResult:
    """pairs: list of (gold, predicted) annotation strings."""
    if not pairs:
        return EvalResult(0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0)

    golds = [_norm(g) for g, _ in pairs]
    preds = [_norm(p) for _, p in pairs]

    em = sum(1 for g, p in zip(golds, preds) if g == p)

    g_emb = embed(golds)
    p_emb = embed(preds)
    sims = (g_emb * p_emb).sum(axis=1)

    pm = 0
    mismatch = 0
    for g, p, s in zip(golds, preds, sims):
        if g == p:
            continue
        if s >= pm_threshold:
            pm += 1
        else:
            mismatch += 1

    n = len(pairs)
    return EvalResult(
        n=n,
        exact_match=em,
        partial_match=pm,
        mismatch=mismatch,
        accuracy=(em + pm) / n,
        em_rate=em / n,
        pm_rate=pm / n,
        avg_similarity=float(np.mean(sims)),
    )
