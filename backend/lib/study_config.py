"""
Study definition loader.

A "study" defines a small, fixed set of patient-level variables to validate
(e.g. site/topography, stage, age, sex) plus a cohort inclusion rule. Studies
live as JSON files in ``backend/data/studies/`` so the variable list can be
edited (add/remove) without code changes.

The loader is intentionally tiny and side-effect free; callers get plain dicts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Any


def _studies_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "studies"


_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _load_all(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Load and cache every study config keyed by its ``id``."""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE

    studies: Dict[str, Dict[str, Any]] = {}
    sdir = _studies_dir()
    if sdir.exists():
        for path in sorted(sdir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                sid = cfg.get("id") or path.stem
                cfg["id"] = sid
                studies[sid] = cfg
            except Exception as e:  # pragma: no cover - defensive
                print(f"[WARN] Failed to load study config {path}: {e}")
    _CACHE = studies
    return studies


def list_studies() -> List[Dict[str, Any]]:
    """Return a lightweight list of available studies (id, name, description)."""
    out = []
    for cfg in _load_all().values():
        out.append({
            "id": cfg.get("id"),
            "name": cfg.get("name", cfg.get("id")),
            "description": cfg.get("description", ""),
            "center": cfg.get("center"),
            "variable_count": len(active_variables(cfg)),
        })
    out.sort(key=lambda c: (c.get("name") or "").lower())
    return out


def get_study(study_id: str) -> Optional[Dict[str, Any]]:
    """Return the full config dict for a study, or None if unknown."""
    return _load_all().get(study_id)


def active_variables(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the enabled variables for a study.

    The ``variables`` list is always active. ``optional_variables`` are included
    only when their ``enabled`` flag is truthy, which lets the survival endpoint
    (vital status, treatment dates) be switched on by editing one flag.
    """
    variables = list(cfg.get("variables", []))
    for v in cfg.get("optional_variables", []):
        if v.get("enabled"):
            variables.append(v)
    return variables


def reload() -> None:
    """Drop the cache (used by tests and after editing study JSON on disk)."""
    _load_all(force=True)
