"""Shared helpers for the MSCI data-import pipeline.

Loads codebook/notes/items, computes per-data_item completeness, formats CSV rows.
Pure stdlib (no pandas) — these are offline transforms, the volume is modest.
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------- Constants ----------

ENGLISH_DICT_ID = 199
UNFILLED_PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]")

# ---------- Path helpers ----------


def resolve_glob(path_or_glob: str) -> Path:
    """Accept either a literal path or a glob; return the single matching path.

    The MSCI exports embed a timestamp in the filename (e.g.
    `data_items_def_export_15_2026-05-06T11_29_04.267Z.json`), so users typically
    pass a glob like `texts/MSCI/data_items_def_export_*.json`.
    """
    p = Path(path_or_glob)
    if p.exists() and p.is_file():
        return p
    matches = sorted(glob.glob(path_or_glob))
    if not matches:
        raise FileNotFoundError(f"No file matches: {path_or_glob}")
    if len(matches) > 1:
        raise ValueError(
            f"Glob matches {len(matches)} files; expected 1: {matches}"
        )
    return Path(matches[0])


# ---------- Data classes ----------


@dataclass(frozen=True)
class CodebookEntry:
    dict_id: int
    node_id: int
    node_sentence: str
    param_count: int  # number of placeholders in the template


@dataclass
class Note:
    internal_note_id: str
    pid: str
    note_original_text: str
    note_name: str
    note_date: str


@dataclass
class DataItem:
    internal_note_id: str
    sentence_id: int | None
    dict_id: int
    node_id: int
    text_content: str
    params: str
    # Populated during merge:
    node_sentence: str = ""
    is_complete: bool = False
    incomplete_reason: str | None = None


@dataclass
class EnrichedNote:
    """A note with its data_items embedded (the JSONL row shape)."""

    internal_note_id: str
    pid: str
    note_original_text: str
    note_name: str
    note_date: str
    data_items: list[DataItem] = field(default_factory=list)


# ---------- Loaders ----------


def load_codebook(path: Path) -> dict[tuple[int, int], CodebookEntry]:
    """Load codebook indexed by (dict_id, node_id). All entries kept; filtering
    happens at the completeness-check level so we can preserve incomplete_reason
    for visibility.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: dict[tuple[int, int], CodebookEntry] = {}
    for entry in data:
        dict_id = entry.get("dict_id")
        node_id = entry.get("node_id")
        if dict_id is None or node_id is None:
            continue
        params = entry.get("parameters") or []
        out[(int(dict_id), int(node_id))] = CodebookEntry(
            dict_id=int(dict_id),
            node_id=int(node_id),
            node_sentence=entry.get("node_sentence") or "",
            param_count=len(params) if isinstance(params, list) else 0,
        )
    return out


def load_notes(path: Path) -> dict[str, Note]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, Note] = {}
    for entry in data:
        nid = entry.get("internal_note_id")
        if nid is None:
            continue
        nid_str = str(nid)
        out[nid_str] = Note(
            internal_note_id=nid_str,
            pid=str(entry.get("pid") or ""),
            note_original_text=str(entry.get("note_original_text") or ""),
            note_name=str(entry.get("note_name") or ""),
            note_date=str(entry.get("note_date") or ""),
        )
    return out


def load_items(path: Path) -> list[DataItem]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: list[DataItem] = []
    for entry in data:
        nid = entry.get("internal_note_id")
        dict_id = entry.get("dict_id")
        node_id = entry.get("node_id")
        if nid is None or dict_id is None or node_id is None:
            continue
        out.append(
            DataItem(
                internal_note_id=str(nid),
                sentence_id=entry.get("sentence_id"),
                dict_id=int(dict_id),
                node_id=int(node_id),
                text_content=str(entry.get("text_content") or ""),
                params=str(entry.get("params") or ""),
            )
        )
    return out


def load_mapping(path: Path) -> dict[int, str]:
    """Read mapping_msci.csv → {node_id: prompt_type}. Blank prompt_types are
    excluded — the caller treats their absence as 'unmapped'.
    """
    out: dict[int, str] = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            node_id_raw = (row.get("node_id") or "").strip()
            prompt_type = (row.get("suggested_prompt_type") or "").strip()
            if not node_id_raw or not prompt_type:
                continue
            try:
                out[int(node_id_raw)] = prompt_type
            except ValueError:
                continue
    return out


# ---------- Completeness ----------


def check_completeness(
    item: DataItem, codebook: dict[tuple[int, int], CodebookEntry]
) -> tuple[bool, str | None]:
    """Return (is_complete, reason). Reason is None when complete; otherwise one of:
    polish_dict, unknown_node_id, empty_text_content, unfilled_placeholder, empty_params.
    """
    if item.dict_id != ENGLISH_DICT_ID:
        return False, "polish_dict"
    cb = codebook.get((item.dict_id, item.node_id))
    if cb is None:
        return False, "unknown_node_id"
    if not item.text_content.strip():
        return False, "empty_text_content"
    if UNFILLED_PLACEHOLDER_RE.search(item.text_content):
        return False, "unfilled_placeholder"
    # No-placeholder assertions are complete regardless of params.
    if cb.param_count > 0 and not item.params.strip():
        return False, "empty_params"
    return True, None


# ---------- CSV writing (Path A: ;-delimited, fully-quoted) ----------


def write_path_a_csv(path: Path, rows: Iterable[dict[str, str]]) -> int:
    """Write the upload-style CSV: text;date;p_id;note_id;report_type;annotations.

    Every field is double-quoted; inner " is doubled; UTF-8 no BOM. Matches the
    format consumed by /api/upload/csv and produced by the test_data example.
    Returns the row count written.
    """
    columns = ["text", "date", "p_id", "note_id", "report_type", "annotations"]
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=columns,
            delimiter=";",
            quoting=csv.QUOTE_ALL,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
            count += 1
    return count


def write_faiss_csv(path: Path, rows: Iterable[dict[str, str]]) -> int:
    """Write the FAISS-style CSV: prompt_type,note_text,annotation (standard CSV)."""
    columns = ["prompt_type", "note_text", "annotation"]
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
            count += 1
    return count


# ---------- Misc ----------


_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def format_date(note_date: str) -> str:
    """Reduce an ISO-8601 timestamp to YYYY-MM-DD. Returns '' if unparseable."""
    if not note_date:
        return ""
    m = _ISO_DATE_RE.match(note_date)
    return m.group(1) if m else ""


def render_annotations_field(
    items: list[DataItem],
    mapping: dict[int, str],
    center_lower: str,
) -> str:
    """Build the 'annotations' column for a Path A row from a note's data_items.

    Format: `<prompt>-<center>: <text_content_stripped> | ...`
    - Items without a mapping entry are skipped.
    - text_content is .strip()'d (raw values often end in '\\n').
    - Order preserved from the items list.
    """
    parts = []
    for item in items:
        prompt = mapping.get(item.node_id)
        if not prompt:
            continue
        body = item.text_content.strip()
        if not body:
            continue
        parts.append(f"{prompt}-{center_lower}: {body}")
    return " | ".join(parts)


def stderr(msg: str) -> None:
    print(msg, file=sys.stderr)
