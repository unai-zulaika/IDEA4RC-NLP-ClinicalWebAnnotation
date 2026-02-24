"""
CSV upload and processing routes
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from typing import List, Dict, Tuple, Optional
import pandas as pd
import csv
import io
import json
from pathlib import Path

from models.schemas import CSVUploadResponse, CSVRow

router = APIRouter()


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


def _parse_csv_with_reconstruction(contents_str: str, required_columns: List[str]) -> Optional[pd.DataFrame]:
    """
    Parse CSV by splitting on ; and reconstructing fields when text contains the delimiter.
    Handles the ""value"" quoting convention by stripping quotes after splitting.
    """
    lines = contents_str.strip().split('\n')
    if len(lines) < 2:
        return None

    # Parse header
    header = [h.strip().strip('"').strip() for h in lines[0].split(';')]

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
    Raises HTTPException(400) if no strategy works.
    """
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

    for strategy in strategies[:4]:
        try:
            df = pd.read_csv(io.StringIO(contents_str), **strategy)
            df.columns = [col.strip().strip('"').strip() for col in df.columns]
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
            df.columns = [col.strip().strip('"').strip() for col in df.columns]
            missing = [c for c in required_columns if c not in df.columns]
            if missing:
                continue
            if strategy.get('quoting') == csv.QUOTE_NONE:
                for col in df.columns:
                    df[col] = df[col].astype(str).str.strip().str.strip('"').str.strip()
            return df
        except Exception:
            continue

    raise HTTPException(
        status_code=400,
        detail=f"Failed to parse CSV. No delimiter/quoting strategy produced the required columns: {required_columns}"
    )


@router.post("/csv", response_model=CSVUploadResponse)
async def upload_csv(file: UploadFile = File(...)):
    """Upload and parse CSV file"""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    # Read CSV content
    contents = await file.read()
    
    contents_str = contents.decode('utf-8')
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
    return CSVUploadResponse(
        success=True,
        message=f"CSV uploaded successfully. {len(rows)} rows parsed.",
        row_count=len(rows),
        columns=list(df.columns),
        preview=preview,  # First 10 rows for display
        all_rows=all_rows_dicts,  # All rows for session creation
        session_id=None,  # No session created yet
        has_annotations=has_annotations,  # Indicates if evaluation mode should be used
        report_types=unique_report_types  # Unique report types found in CSV
    )


@router.post("/fewshots")
async def upload_fewshots(file: UploadFile = File(...)):
    """
    Upload few-shot examples CSV.
    Expected format: prompt_type, note_text, annotation
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    contents = await file.read()
    
    contents_str = contents.decode('utf-8')
    required_columns = ['prompt_type', 'note_text', 'annotation']
    df = _parse_csv_flexible(contents_str, required_columns)
    
    # Import the few-shot storage from annotate module (lazy import to avoid circular dependency)
    import importlib
    annotate_module = importlib.import_module('routes.annotate')
    _simple_fewshots = getattr(annotate_module, '_simple_fewshots', {})
    
    # Load existing fewshots from disk if memory is empty
    if not _simple_fewshots:
        _simple_fewshots.update(_load_fewshots_from_disk())
    
    # Group by prompt_type and store
    fewshot_count = 0
    for _, row in df.iterrows():
        prompt_type = str(row['prompt_type']).strip()
        note_text = str(row['note_text']).strip()
        annotation = str(row['annotation']).strip()
        
        if prompt_type and note_text and annotation:
            if prompt_type not in _simple_fewshots:
                _simple_fewshots[prompt_type] = []
            _simple_fewshots[prompt_type].append((note_text, annotation))
            fewshot_count += 1
    
    # Save to disk for persistence
    _save_fewshots_to_disk(_simple_fewshots)
    
    return {
        "success": True,
        "message": f"Uploaded {fewshot_count} few-shot examples",
        "prompt_types": list(_simple_fewshots.keys()),
        "counts_by_prompt": {pt: len(examples) for pt, examples in _simple_fewshots.items()}
    }


@router.get("/report-type-mappings")
async def get_report_type_mappings(center: Optional[str] = Query(None)):
    """Get saved report type to prompt type mappings, scoped by center.

    The file stores mappings nested by center:
      { "INT": { "Pathology": ["biopsygrading-int", ...] }, "MSCI": { ... } }

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


@router.get("/fewshots/status")
async def get_fewshots_status():
    """Get status of uploaded few-shot examples"""
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
    
    return {
        "faiss_available": faiss_available,
        "simple_fewshots_available": len(_simple_fewshots) > 0,
        "prompt_types_with_fewshots": list(_simple_fewshots.keys()),
        "counts_by_prompt": {pt: len(examples) for pt, examples in _simple_fewshots.items()},
        "total_examples": sum(len(examples) for examples in _simple_fewshots.values())
    }


@router.delete("/fewshots")
async def delete_fewshots():
    """
    Delete all few-shot examples.
    Clears both in-memory storage and disk storage of few-shot examples.
    """
    import importlib
    annotate_module = importlib.import_module('routes.annotate')
    _simple_fewshots = getattr(annotate_module, '_simple_fewshots', {})
    
    # Load from disk if memory is empty
    if not _simple_fewshots:
        _simple_fewshots.update(_load_fewshots_from_disk())
    
    # Count examples before deletion
    total_examples = sum(len(examples) for examples in _simple_fewshots.values())
    prompt_types_count = len(_simple_fewshots)
    
    # Clear the dictionary
    _simple_fewshots.clear()
    setattr(annotate_module, '_simple_fewshots', _simple_fewshots)
    
    # Also delete from disk
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

