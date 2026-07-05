"""
Ranked label search over the ICD-O-3 condition files (morphology & topography).

The LLM's *codes* are frequently hallucinated, but its *labels* (tumour-type
text, site text) are usually right. This module searches a free-text label
against the curated per-centre condition files (the authoritative label↔code
tables) and returns ranked real code candidates, so a reviewer can pick the
correct code independently for morphology and topography.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[,;()\[\]\"'†/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\bnos\b", "", s).strip()
    return s


def _score(query: str, label: str) -> float:
    """Cheap, deterministic label similarity in [0,1]."""
    q, l = _norm(query), _norm(label)
    if not q or not l:
        return 0.0
    if q == l:
        return 1.0
    if l.startswith(q) or q.startswith(l):
        return 0.92
    if q in l or l in q:
        return 0.85
    qt, lt = set(q.split()), set(l.split())
    if not qt or not lt:
        return 0.0
    inter, union = len(qt & lt), len(qt | lt)
    return round(0.7 * inter / union, 3) if union else 0.0


def _search(entries: List[Dict[str, Any]], label_key: str, code_key: str,
            query: str, limit: int, family: Optional[str]) -> List[Dict[str, Any]]:
    scored: Dict[str, Dict[str, Any]] = {}  # code -> best result (dedupe by code)
    for e in entries:
        if family and family.lower() not in (e.get("source", "") or "").lower():
            continue
        code = (e.get(code_key) or "").strip()
        label = (e.get(label_key) or "").strip()
        if not code or not label:
            continue
        s = _score(query, label)
        if s <= 0:
            continue
        prev = scored.get(code)
        if prev is None or s > prev["score"]:
            scored[code] = {"code": code, "label": label, "score": s, "source": e.get("source", "")}
    return sorted(scored.values(), key=lambda r: (-r["score"], r["code"]))[:limit]


def search_morphology(query: str, limit: int = 10, family: Optional[str] = None) -> List[Dict[str, Any]]:
    from lib.morphology_resolver import get_morphology_resolver
    resolver = get_morphology_resolver()
    if resolver is None:
        return []
    return _search(resolver.get_all_entries(), "label", "code", query, limit, family)


def search_topography(query: str, limit: int = 10, family: Optional[str] = None) -> List[Dict[str, Any]]:
    from lib.topography_resolver import get_topography_resolver
    resolver = get_topography_resolver()
    if resolver is None:
        return []
    return _search(resolver.get_all_entries(), "subsite", "code", query, limit, family)
