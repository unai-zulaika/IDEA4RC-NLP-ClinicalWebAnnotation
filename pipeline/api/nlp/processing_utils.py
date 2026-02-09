"""Utility helpers shared across NLP processing modules."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List

import pandas


def to_str(val: Any) -> str:
    """Return a trimmed string representation for any value."""
    try:
        return str(val).strip()
    except Exception:
        return ""


def is_placeholder(text: str) -> bool:
    """Check if the provided text should be treated as a placeholder/empty value."""
    s = to_str(text).lower()
    if not s:
        return True
    if s in {"n/a", "na", "none", "null", "unknown", "unk", "-", "--"}:
        return True
    # Match patterns like [provide date], [select regimen], etc.
    if re.fullmatch(r"\[[^\]]+\]", s or ""):
        return True
    return False


def is_invalid_value(param_type: str, value: Any) -> bool:
    """Return True if the value is considered invalid for the given parameter type."""
    if value is None:
        return True
    try:
        if pandas.isna(value):
            return True
    except Exception:
        pass
    s = to_str(value)
    if not s:
        return True
    if is_placeholder(s):
        return True
    if param_type == "DATE":
        if not re.search(r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}", s):
            return True
    return False


def is_duplicate_row(
    existing_rows: pandas.DataFrame | None,
    staged_rows: List[dict[str, Any]],
    patient_id: Any,
    core_variable: str,
    value: Any,
    date_ref: Any,
) -> bool:
    """Check if a row with the same patient_id, core_variable, value, and date_ref
    already exists in either existing_rows (DataFrame) or staged_rows (list of dicts).

    Args:
        existing_rows: Existing DataFrame (e.g., excel_data)
        staged_rows: List of staged row dictionaries
        patient_id: Patient identifier
        core_variable: Core variable name
        value: Value to check
        date_ref: Reference date

    Returns:
        True if duplicate exists, False otherwise
    """
    # Normalize inputs
    patient_id_str = to_str(patient_id)
    core_variable_str = to_str(core_variable)
    value_str = to_str(value)
    date_ref_str = to_str(date_ref)

    # Check existing DataFrame
    if isinstance(existing_rows, pandas.DataFrame) and not existing_rows.empty:
        # Check for required columns before filtering
        required_cols = {"patient_id", "core_variable", "value", "date_ref"}
        if not required_cols.issubset(existing_rows.columns):
            # Skip DataFrame check if columns missing
            pass
        else:
            matches = existing_rows[
                (existing_rows["patient_id"] == patient_id_str)
                & (existing_rows["core_variable"] == core_variable_str)
                & (existing_rows["value"].astype(str) == value_str)
                & (existing_rows["date_ref"].astype(str) == date_ref_str)
            ]
            if not matches.empty:
                return True

    # Check staged rows
    for row in staged_rows:
        if (
            row.get("patient_id") == patient_id
            and row.get("core_variable") == core_variable
            and to_str(row.get("value")) == to_str(value)
            and to_str(row.get("date_ref")) == to_str(date_ref)
        ):
            return True
    return False


def parse_date_any(s: str) -> datetime | None:
    """Parse DD/MM/YYYY or YYYY-MM-DD formats; return None if not parseable."""
    if not s:
        return None
    s = to_str(s)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def first_group(match: Any) -> Any:
    """Return the first element of a regex match tuple or the raw match."""
    if isinstance(match, tuple) and len(match) > 0:
        return match[0]
    return match
