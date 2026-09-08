"""
Path-safety helpers for user-supplied identifiers.

Session IDs, preset IDs and center names arrive from request paths, query strings
and JSON bodies, and are used to build filesystem paths. Interpolating them
directly lets `../` escape the intended directory, so every such identifier is
validated here before it reaches a Path.
"""

import re
from pathlib import Path

from fastapi import HTTPException

# Identifiers are UUID4 strings in practice. The pattern is a little wider than
# that so hand-made IDs keep working, but it admits no separator, no dot, and no
# leading punctuation — which is what makes traversal impossible.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

# Center names are directory names (INT-SARC, MSCI, VGR, INT-HNC).
_SAFE_CENTER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def validate_id(value: str, kind: str = "id") -> str:
    """Return `value` if it is safe to use as a single path segment, else 400.

    Rejects empty strings, separators, dots, and anything over 128 characters.
    """
    if not isinstance(value, str) or not _SAFE_ID_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid {kind}: must be 1-128 characters of letters, digits, "
                f"'-' or '_', starting with a letter or digit."
            ),
        )
    return value


def validate_center(value: str) -> str:
    """Return `value` if it is safe to use as a center directory name, else 400."""
    if not isinstance(value, str) or not _SAFE_CENTER_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid center name: must be 1-64 characters of letters, digits, "
                "'-', '_' or '.', starting with a letter or digit."
            ),
        )
    return value


def safe_json_path(base: Path, identifier: str, kind: str = "id") -> Path:
    """Return `base/<identifier>.json` for a validated identifier.

    The regex alone is sufficient, but the resolved-prefix check is kept as a
    second barrier so a future change to the pattern cannot silently reopen
    traversal. Symlinks inside `base` are resolved before comparison.
    """
    validate_id(identifier, kind)
    base_resolved = base.resolve()
    candidate = (base_resolved / f"{identifier}.json").resolve()
    if candidate.parent != base_resolved:
        raise HTTPException(status_code=400, detail=f"Invalid {kind}: path escapes storage directory.")
    return candidate


def safe_center_dir(base: Path, center: str) -> Path:
    """Return `base/<center>` for a validated center name."""
    validate_center(center)
    base_resolved = base.resolve()
    candidate = (base_resolved / center).resolve()
    if candidate.parent != base_resolved:
        raise HTTPException(status_code=400, detail="Invalid center name: path escapes prompts directory.")
    return candidate
