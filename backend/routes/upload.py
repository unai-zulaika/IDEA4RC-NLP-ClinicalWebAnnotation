"""
CSV upload and processing routes
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import List, Dict, Tuple, Optional
import pandas as pd
import csv
import io
import json
import re
from pathlib import Path

from models.schemas import CSVUploadResponse, CSVRow

router = APIRouter()


def _normalize_text(text: str) -> str:
    """Normalize text for duplicate comparison (does not mutate stored text)."""
    return re.sub(r'\s+', ' ', text.strip()).lower()


def _get_sessions_dir() -> Path:
    """Get directory for storing sessions"""
    backend_dir = Path(__file__).parent.parent
    sessions_dir = backend_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def _get_fewshots_file() -> Path:
    """Get path to few-shot examples storage file"""
    # Import from annotate module to avoid duplication
    from routes.annotate import _get_fewshots_file
    return _get_fewshots_file()


def _load_fewshots_from_disk() -> Dict[str, List[Tuple[str, str]]]:
    """Load few-shot examples from disk"""
    # Import from annotate module to avoid duplication
    from routes.annotate import _load_fewshots_from_disk
    return _load_fewshots_from_disk()


def _save_fewshots_to_disk(fewshots: Dict[str, List[Tuple[str, str]]]):
    """Save few-shot examples to disk"""
    from routes.annotate import _get_fewshots_file
    fewshots_file = _get_fewshots_file()
    try:
        # Convert from list of tuples to JSON-serializable format (list of lists)
        data = {}
        for prompt_type, examples in fewshots.items():
            data[prompt_type] = [[note, annotation] for note, annotation in examples]
        
        with open(fewshots_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Failed to save fewshots to disk: {e}")
        raise


def _normalize_column_name(name: str) -> str:
    """Normalize a column header: strip whitespace, wrapping quotes, and UTF-8 BOM.

    Excel on Windows saves UTF-8 files with a BOM (\ufeff) which shows up as the
    first character of the first column name. Without stripping it, a header like
    "\ufeffprompt_type" fails the `col in header` check and every parse strategy
    rejects the file.
    """
    return name.strip().lstrip('\ufeff').strip('"').strip()


def _decode_csv_bytes(raw: bytes) -> str:
    """Decode uploaded CSV bytes, trying common encodings.

    Order:
      1. UTF-8 with BOM (utf-8-sig) — transparently strips a BOM if present.
      2. UTF-8 strict.
      3. UTF-16 — only when a UTF-16 BOM is detected, because any even-length
         byte sequence is a valid UTF-16 decode and would silently produce
         garbled output for Latin-1 files otherwise.
      4. Latin-1 — never raises on valid bytes; serves as the safe final
         fallback for legacy Excel exports on Windows.
    """
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except (UnicodeDecodeError, UnicodeError):
            pass
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("latin-1", errors="replace")


def _parse_csv_with_reconstruction(contents_str: str, required_columns: List[str]) -> Optional[pd.DataFrame]:
    """
    Parse CSV by splitting on ; and reconstructing fields when text contains the delimiter.
    Handles the ""value"" quoting convention by stripping quotes after splitting.
    """
    lines = contents_str.strip().split('\n')
    if len(lines) < 2:
        return None

    # Parse header
    header = [_normalize_column_name(h) for h in lines[0].split(';')]

    # Check required columns
    if not all(col in header for col in required_columns):
        return None

    expected_cols = len(header)

    rows = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(';')

        if len(parts) == expected_cols:
            rows.append([p.strip().strip('"').strip() for p in parts])
        elif len(parts) > expected_cols:
            # Text field (first column) was split by internal ;
            # Take the last (expected_cols - 1) parts as the non-text columns
            # Everything else is the text field
            excess = len(parts) - expected_cols
            text_parts = parts[:excess + 1]
            rest_parts = parts[excess + 1:]

            text_value = ';'.join(text_parts)
            all_parts = [text_value] + list(rest_parts)
            rows.append([p.strip().strip('"').strip() for p in all_parts])
        else:
            # Fewer fields than expected — pad with empty strings
            padded = parts + [''] * (expected_cols - len(parts))
            rows.append([p.strip().strip('"').strip() for p in padded])

    if not rows:
        return None

    return pd.DataFrame(rows, columns=header)


def _parse_csv_flexible(contents_str: str, required_columns: List[str]) -> pd.DataFrame:
    """
    Try multiple CSV parsing strategies to handle different delimiter/quoting formats.
    Returns the first successfully parsed DataFrame that contains all required columns.
    Raises HTTPException(400) with the columns actually found if no strategy works.
    """
    # Strip leading BOM if present (normally _decode_csv_bytes has already handled
    # this via utf-8-sig, but callers that build a string directly can still hit it).
    if contents_str.startswith("\ufeff"):
        contents_str = contents_str.lstrip("\ufeff")

    common_kwargs = dict(dtype=str, keep_default_na=False)

    strategies = [
        # 1. Semicolon, standard quoting (current happy path)
        dict(sep=';', **common_kwargs),
        # 2. Comma, standard quoting
        dict(sep=',', **common_kwargs),
        # 3. Tab, standard quoting
        dict(sep='\t', **common_kwargs),
        # 4. Auto-detect delimiter
        dict(sep=None, engine='python', **common_kwargs),
        # 5. Semicolon with QUOTE_NONE (fixes broken-quoting format)
        dict(sep=';', quoting=csv.QUOTE_NONE, **common_kwargs),
        # 6. Comma with QUOTE_NONE
        dict(sep=',', quoting=csv.QUOTE_NONE, **common_kwargs),
    ]

    # Track the longest column list we saw across all strategies — the best proxy for
    # "what columns did the user actually have?" when every strategy fails.
    best_found_columns: List[str] = []

    def _maybe_update_best(columns: List[str]) -> None:
        nonlocal best_found_columns
        if len(columns) > len(best_found_columns):
            best_found_columns = columns

    for strategy in strategies[:4]:
        try:
            df = pd.read_csv(io.StringIO(contents_str), **strategy)
            df.columns = [_normalize_column_name(col) for col in df.columns]
            _maybe_update_best(list(df.columns))
            missing = [c for c in required_columns if c not in df.columns]
            if missing:
                continue
            return df
        except Exception:
            continue

    # Try column-reconstruction strategy for files with ; in text fields
    try:
        df = _parse_csv_with_reconstruction(contents_str, required_columns)
        if df is not None:
            return df
    except Exception:
        pass

    # Fallback: QUOTE_NONE strategies
    for strategy in strategies[4:]:
        try:
            df = pd.read_csv(io.StringIO(contents_str), **strategy)
            df.columns = [_normalize_column_name(col) for col in df.columns]
            _maybe_update_best(list(df.columns))
            missing = [c for c in required_columns if c not in df.columns]
            if missing:
                continue
            if strategy.get('quoting') == csv.QUOTE_NONE:
                for col in df.columns:
                    df[col] = df[col].astype(str).str.strip().str.strip('"').str.strip()
            return df
        except Exception:
            continue

    found_msg = (
        f"Columns found in file: {best_found_columns}."
        if best_found_columns
        else "No columns could be parsed from the file."
    )
    raise HTTPException(
        status_code=400,
        detail=(
            f"Failed to parse CSV. Required columns: {required_columns}. "
            f"{found_msg} "
            "Tip: save as UTF-8 CSV from Excel and ensure the header row uses the exact names above."
        ),
    )


@router.post("/csv", response_model=CSVUploadResponse)
async def upload_csv(file: UploadFile = File(...)):
    """Upload and parse CSV file"""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    # Read CSV content
    contents = await file.read()

    contents_str = _decode_csv_bytes(contents)
    required_columns = ['text', 'date', 'p_id', 'note_id', 'report_type']
    df = _parse_csv_flexible(contents_str, required_columns)
    
    # Convert to list of CSVRow objects
    # Use .fillna('') to handle any NaN values and ensure we get full strings
    rows = []
    for idx, row in df.iterrows():
        # Get text value - ensure we preserve full length
        text_value = row['text'] if pd.notna(row['text']) else ''
        # Convert to string explicitly, handling any pandas object types
        if isinstance(text_value, str):
            text_str = text_value
        else:
            text_str = str(text_value)
        
        # Debug: log first row's text length to verify no truncation
        if idx == 0:
            print(f"[DEBUG] First row text length: {len(text_str)} characters")
        
        rows.append(CSVRow(
            text=text_str,
            date=str(row['date']) if pd.notna(row['date']) else '',
            p_id=str(row['p_id']) if pd.notna(row['p_id']) else '',
            note_id=str(row['note_id']) if pd.notna(row['note_id']) else '',
            report_type=str(row['report_type']) if pd.notna(row['report_type']) else '',
            annotations=str(row.get('annotations', '')) if 'annotations' in df.columns and pd.notna(row.get('annotations')) else None
        ))
    
    # Deduplicate note_ids: if duplicates exist, append the row index as suffix
    seen_ids: set = set()
    duplicate_ids: set = set()
    for row in rows:
        nid = row.note_id
        if nid in seen_ids:
            duplicate_ids.add(nid)
        seen_ids.add(nid)

    had_duplicates = bool(duplicate_ids)
    if had_duplicates:
        print(f"[WARN] Duplicate note_ids detected in CSV: {duplicate_ids}. Deduplicating by appending row indices.")
        deduped = []
        for idx, row in enumerate(rows):
            if row.note_id in duplicate_ids:
                deduped.append(CSVRow(
                    text=row.text,
                    date=row.date,
                    p_id=row.p_id,
                    note_id=f"{row.note_id}_{idx}",
                    report_type=row.report_type,
                    annotations=row.annotations,
                ))
            else:
                deduped.append(row)
        rows = deduped

    # Deduplicate rows by text content: keep first occurrence, remove subsequent
    seen_texts: set = set()
    text_deduped: list = []
    removed_note_ids: list = []
    for row in rows:
        fingerprint = _normalize_text(row.text)
        if fingerprint in seen_texts:
            removed_note_ids.append(row.note_id)
        else:
            seen_texts.add(fingerprint)
            text_deduped.append(row)
    had_text_duplicates = bool(removed_note_ids)
    if had_text_duplicates:
        print(f"[WARN] Duplicate text content in CSV. Removing {len(removed_note_ids)} rows: {removed_note_ids}")
        rows = text_deduped

    # Convert all rows to dicts
    all_rows_dicts = [row.dict() for row in rows]

    # Check if annotations column exists and has values (determines evaluation mode)
    has_annotations = 'annotations' in df.columns and any(
        str(row.get('annotations', '')).strip()
        for row in all_rows_dicts
        if row.get('annotations')
    )
    
    # Return preview (first 10 rows) for display
    preview = all_rows_dicts[:10]
    
    # Extract unique report types
    unique_report_types = sorted(list(set(row.report_type for row in rows if row.report_type)))
    
    # Note: Session is NOT created here - it will be created when user clicks "Create Session"
    # This prevents duplicate session creation
    message = f"CSV uploaded successfully. {len(rows)} rows parsed."
    if had_duplicates:
        message += " Duplicate Note IDs were detected and made unique by appending row indices."
    if had_text_duplicates:
        message += f" {len(removed_note_ids)} row(s) with duplicate text content were removed (first occurrence kept)."
    return CSVUploadResponse(
        success=True,
        message=message,
        row_count=len(rows),
        columns=list(df.columns),
        preview=preview,  # First 10 rows for display
        all_rows=all_rows_dicts,  # All rows for session creation
        session_id=None,  # No session created yet
        has_annotations=has_annotations,  # Indicates if evaluation mode should be used
        report_types=unique_report_types,  # Unique report types found in CSV
        duplicate_note_ids_detected=had_duplicates,
        duplicate_text_detected=had_text_duplicates,
        duplicate_text_removed_count=len(removed_note_ids),
        duplicate_text_note_ids=removed_note_ids,
    )


@router.post("/fewshots")
async def upload_fewshots(file: UploadFile = File(...), center: str = Query(..., description="Center to associate few-shots with (e.g., INT-SARC, MSCI, VGR, INT-HNC)")):
    """
    Upload few-shot examples CSV for a specific center.
    Expected format: prompt_type, note_text, annotation
    The prompt_type values are automatically suffixed with the center name
    to match the prompt key format (e.g., 'gender' → 'gender-int-sarc').
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    center_lower = center.lower()

    contents = await file.read()

    contents_str = _decode_csv_bytes(contents)
    required_columns = ['prompt_type', 'note_text', 'annotation']
    df = _parse_csv_flexible(contents_str, required_columns)

    # Import the few-shot storage from annotate module (lazy import to avoid circular dependency)
    import importlib
    annotate_module = importlib.import_module('routes.annotate')
    _simple_fewshots = getattr(annotate_module, '_simple_fewshots', {})

    # Load existing fewshots from disk if memory is empty
    if not _simple_fewshots:
        _simple_fewshots.update(_load_fewshots_from_disk())

    # Group by prompt_type and store, suffixing with center
    fewshot_count = 0
    for _, row in df.iterrows():
        prompt_type = str(row['prompt_type']).strip()
        note_text = str(row['note_text']).strip()
        annotation = str(row['annotation']).strip()

        if prompt_type and note_text and annotation:
            # Suffix with center to match prompt keys (e.g., "gender" → "gender-int-sarc")
            full_key = f"{prompt_type}-{center_lower}"
            if full_key not in _simple_fewshots:
                _simple_fewshots[full_key] = []
            _simple_fewshots[full_key].append((note_text, annotation))
            fewshot_count += 1

    # Save to disk for persistence
    _save_fewshots_to_disk(_simple_fewshots)

    return {
        "success": True,
        "message": f"Uploaded {fewshot_count} few-shot examples for center '{center}'",
        "center": center,
        "prompt_types": list(_simple_fewshots.keys()),
        "counts_by_prompt": {pt: len(examples) for pt, examples in _simple_fewshots.items()}
    }


@router.get("/report-type-mappings")
async def get_report_type_mappings(center: Optional[str] = Query(None)):
    """Get saved report type to prompt type mappings, scoped by center.

    The file stores mappings nested by center:
      { "INT-SARC": { "Pathology": ["biopsygrading-int-sarc", ...] }, "MSCI": { ... } }

    If center is provided, returns only that center's mappings (flat dict).
    If center is omitted, returns the entire nested structure.
    """
    mappings_file = _get_sessions_dir() / "report_type_mappings.json"
    if not mappings_file.exists():
        return {}
    try:
        with open(mappings_file, 'r', encoding='utf-8') as f:
            all_mappings = json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to load report type mappings: {e}")
        return {}

    # Migrate old flat format: if top-level values are lists, it's the old format — discard it
    if all_mappings and any(isinstance(v, list) for v in all_mappings.values()):
        print("[INFO] Discarding old flat report_type_mappings.json (not center-scoped)")
        all_mappings = {}
        try:
            with open(mappings_file, 'w', encoding='utf-8') as f:
                json.dump(all_mappings, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    if center:
        return all_mappings.get(center, {})
    return all_mappings


@router.post("/report-type-mappings")
async def save_report_type_mappings(
    mapping: Dict[str, List[str]],
    center: Optional[str] = Query(None),
):
    """Save report type to prompt type mapping, scoped by center.

    If center is provided, saves under that center key.
    If center is omitted, treats mapping as a flat update (legacy behavior).
    """
    mappings_file = _get_sessions_dir() / "report_type_mappings.json"
    try:
        all_mappings: Dict = {}
        if mappings_file.exists():
            with open(mappings_file, 'r', encoding='utf-8') as f:
                all_mappings = json.load(f)

        # Migrate old flat format
        if all_mappings and any(isinstance(v, list) for v in all_mappings.values()):
            print("[INFO] Discarding old flat report_type_mappings.json during save")
            all_mappings = {}

        if center:
            if center not in all_mappings:
                all_mappings[center] = {}
            all_mappings[center].update(mapping)
        else:
            all_mappings.update(mapping)

        with open(mappings_file, 'w', encoding='utf-8') as f:
            json.dump(all_mappings, f, indent=2, ensure_ascii=False)

        return {"success": True, "message": "Report type mapping saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save mapping: {str(e)}")


def _strip_center_suffix(key: str, center_suffix: str, legacy_suffix: str, match_legacy: bool) -> str:
    """Strip the center suffix from a prompt key to get the base prompt type."""
    if key.endswith(center_suffix):
        return key[: -len(center_suffix)]
    elif match_legacy and key.endswith(legacy_suffix):
        return key[: -len(legacy_suffix)]
    return key


def _load_faiss_fewshots(center: str) -> Dict[str, List[Tuple[str, str]]]:
    """Load fewshot examples from FAISS parquet files, filtered by center."""
    faiss_dir = _get_faiss_store_dir()
    if not faiss_dir.exists():
        return {}

    center_lower = center.lower()
    center_suffix = f"-{center_lower}"
    legacy_suffix = "-int"
    match_legacy = center_lower == "int-sarc"

    result: Dict[str, List[Tuple[str, str]]] = {}
    for parquet_file in sorted(faiss_dir.glob("*.parquet")):
        prompt_key = parquet_file.stem
        if not (prompt_key.endswith(center_suffix)
                or (match_legacy and prompt_key.endswith(legacy_suffix))):
            continue
        try:
            import pandas as _pd
            df = _pd.read_parquet(parquet_file)
            examples = [
                (str(row.get("note_original_text", "")), str(row.get("annotation", "")))
                for _, row in df.iterrows()
            ]
            if examples:
                result[prompt_key] = examples
        except Exception:
            pass
    return result


@router.get("/fewshots/download")
async def download_fewshots(center: str = Query(..., description="Center to download few-shots for (e.g., INT-SARC, MSCI, VGR)")):
    """
    Download few-shot examples for a specific center as a CSV file.
    Returns the same format used for upload: prompt_type, note_text, annotation.
    The center suffix is stripped from prompt_type so the file can be re-uploaded directly.
    Checks simple fewshots first, then falls back to FAISS parquet data.
    """
    center_lower = center.lower()
    center_suffix = f"-{center_lower}"
    legacy_suffix = "-int"
    match_legacy = center_lower == "int-sarc"

    # Try simple fewshots first
    all_fewshots = _load_fewshots_from_disk()
    filtered: Dict[str, List[Tuple[str, str]]] = {}
    for k, v in all_fewshots.items():
        if k.endswith(center_suffix):
            filtered[k] = v
        elif match_legacy and k.endswith(legacy_suffix):
            filtered[k] = v

    # Fall back to FAISS parquet data
    if not filtered:
        filtered = _load_faiss_fewshots(center)

    if not filtered:
        raise HTTPException(status_code=404, detail=f"No few-shot examples found for center '{center}'")

    # Build CSV: strip center suffix from prompt_type to match upload format
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["prompt_type", "note_text", "annotation"])
    for full_key, examples in sorted(filtered.items()):
        base_type = _strip_center_suffix(full_key, center_suffix, legacy_suffix, match_legacy)
        for note_text, annotation in examples:
            writer.writerow([base_type, note_text, annotation])

    csv_buffer.seek(0)
    filename = f"fewshots_{center_lower}.csv"
    return StreamingResponse(
        iter([csv_buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _get_faiss_store_dir() -> Path:
    """Get path to the FAISS store directory."""
    return Path(__file__).parent.parent / "data" / "faiss_store"


def _scan_faiss_counts(center: Optional[str] = None) -> Dict[str, int]:
    """Scan FAISS store metadata files and return {prompt_key: example_count}.

    Optionally filters by center suffix.
    """
    faiss_dir = _get_faiss_store_dir()
    if not faiss_dir.exists():
        return {}

    center_lower = center.lower() if center else None
    center_suffix = f"-{center_lower}" if center_lower else None
    legacy_suffix = "-int"
    match_legacy = center_lower == "int-sarc" if center_lower else False

    counts: Dict[str, int] = {}
    for meta_file in faiss_dir.glob("*.json"):
        prompt_key = meta_file.stem  # e.g. "gender-int"
        if center_lower:
            if not (prompt_key.endswith(center_suffix)
                    or (match_legacy and prompt_key.endswith(legacy_suffix))):
                continue
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            counts[prompt_key] = meta.get("size", 0)
        except Exception:
            pass
    return counts


@router.get("/fewshots/status")
async def get_fewshots_status(center: Optional[str] = Query(None, description="Filter by center (e.g., INT-SARC, MSCI)")):
    """Get status of uploaded few-shot examples, optionally filtered by center"""
    import importlib
    annotate_module = importlib.import_module('routes.annotate')
    _simple_fewshots = getattr(annotate_module, '_simple_fewshots', {})

    # Load from disk if memory is empty
    if not _simple_fewshots:
        _simple_fewshots.update(_load_fewshots_from_disk())
        # Also update the annotate module's storage
        setattr(annotate_module, '_simple_fewshots', _simple_fewshots)

    # Also check if FAISS builder is available
    try:
        from routes.annotate import _get_fewshot_builder
        builder = _get_fewshot_builder()
        faiss_available = builder is not None
    except:
        faiss_available = False

    # Filter simple fewshots by center if specified
    if center:
        center_lower = center.lower()
        center_suffix = f"-{center_lower}"
        # Match exact center suffix, e.g. center="INT-SARC" matches "gender-int-sarc"
        # Legacy "-int" keys only match INT-SARC (the original center)
        legacy_suffix = "-int"
        match_legacy = center_lower == "int-sarc"
        filtered = {}
        for k, v in _simple_fewshots.items():
            if k.endswith(center_suffix):
                filtered[k] = v
            elif match_legacy and k.endswith(legacy_suffix):
                filtered[k] = v
    else:
        filtered = _simple_fewshots

    # Merge FAISS counts (FAISS keys not already in simple fewshots)
    faiss_counts = _scan_faiss_counts(center)
    merged_counts: Dict[str, int] = {pt: len(examples) for pt, examples in filtered.items()}
    for pt, count in faiss_counts.items():
        if pt not in merged_counts:
            merged_counts[pt] = count

    total_examples = sum(merged_counts.values())
    has_fewshots = total_examples > 0

    return {
        "faiss_available": faiss_available,
        "simple_fewshots_available": has_fewshots,
        "prompt_types_with_fewshots": list(merged_counts.keys()),
        "counts_by_prompt": merged_counts,
        "total_examples": total_examples,
    }


@router.delete("/fewshots")
async def delete_fewshots(center: Optional[str] = Query(None, description="Delete only few-shots for this center. If omitted, deletes all.")):
    """
    Delete few-shot examples, optionally filtered by center.
    If center is provided, only deletes few-shots for that center.
    If omitted, deletes all few-shot examples.
    """
    import importlib
    annotate_module = importlib.import_module('routes.annotate')
    _simple_fewshots = getattr(annotate_module, '_simple_fewshots', {})

    # Load from disk if memory is empty
    if not _simple_fewshots:
        _simple_fewshots.update(_load_fewshots_from_disk())

    if center:
        # Delete only keys for the specified center
        center_suffix = f"-{center.lower()}"
        keys_to_delete = [k for k in _simple_fewshots if k.endswith(center_suffix)]
        total_examples = sum(len(_simple_fewshots[k]) for k in keys_to_delete)
        for k in keys_to_delete:
            del _simple_fewshots[k]
        prompt_types_count = len(keys_to_delete)
        # Save remaining to disk
        _save_fewshots_to_disk(_simple_fewshots)
    else:
        # Delete all
        total_examples = sum(len(examples) for examples in _simple_fewshots.values())
        prompt_types_count = len(_simple_fewshots)
        _simple_fewshots.clear()
        setattr(annotate_module, '_simple_fewshots', _simple_fewshots)
        # Delete disk file
        fewshots_file = _get_fewshots_file()
        if fewshots_file.exists():
            try:
                fewshots_file.unlink()
            except Exception as e:
                print(f"[WARN] Failed to delete fewshots file from disk: {e}")
    
    return {
        "success": True,
        "message": f"Deleted {total_examples} few-shot examples from {prompt_types_count} prompt types",
        "deleted_examples": total_examples,
        "deleted_prompt_types": prompt_types_count
    }

