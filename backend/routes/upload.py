"""
CSV upload and processing routes
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import List, Dict, Tuple
import pandas as pd
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


@router.post("/csv", response_model=CSVUploadResponse)
async def upload_csv(file: UploadFile = File(...)):
    """Upload and parse CSV file"""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    # Read CSV content
    contents = await file.read()
    
    try:
        # Parse CSV (handle semicolon delimiter as in first_patient_notes.csv)
        # Use dtype=str to prevent any truncation and preserve full text
        df = pd.read_csv(
            io.StringIO(contents.decode('utf-8')), 
            delimiter=';', 
            encoding='utf-8',
            dtype=str,  # Read all columns as strings to preserve full content
            keep_default_na=False  # Don't convert empty strings to NaN
        )
    except Exception as e:
        # Try comma delimiter as fallback
        try:
            df = pd.read_csv(
                io.StringIO(contents.decode('utf-8')), 
                delimiter=',', 
                encoding='utf-8',
                dtype=str,  # Read all columns as strings to preserve full content
                keep_default_na=False  # Don't convert empty strings to NaN
            )
        except Exception as e2:
            raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e2)}")
    
    # Validate required columns
    required_columns = ['text', 'date', 'p_id', 'note_id', 'report_type']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {missing_columns}"
        )
    
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
    
    try:
        # Use dtype=str to prevent any truncation and preserve full text
        df = pd.read_csv(
            io.StringIO(contents.decode('utf-8')), 
            delimiter=';', 
            encoding='utf-8',
            dtype=str,  # Read all columns as strings to preserve full content
            keep_default_na=False  # Don't convert empty strings to NaN
        )
    except Exception as e:
        try:
            df = pd.read_csv(
                io.StringIO(contents.decode('utf-8')), 
                delimiter=',', 
                encoding='utf-8',
                dtype=str,  # Read all columns as strings to preserve full content
                keep_default_na=False  # Don't convert empty strings to NaN
            )
        except Exception as e2:
            raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e2)}")
    
    # Validate required columns
    required_columns = ['prompt_type', 'note_text', 'annotation']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {missing_columns}. Expected: {required_columns}"
        )
    
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
async def get_report_type_mappings():
    """Get saved report type to prompt type mappings"""
    mappings_file = _get_sessions_dir() / "report_type_mappings.json"
    if mappings_file.exists():
        try:
            with open(mappings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to load report type mappings: {e}")
            return {}
    return {}


@router.post("/report-type-mappings")
async def save_report_type_mappings(mapping: Dict[str, List[str]]):
    """Save report type to prompt type mapping"""
    mappings_file = _get_sessions_dir() / "report_type_mappings.json"
    try:
        # Load existing mappings
        existing_mappings = {}
        if mappings_file.exists():
            with open(mappings_file, 'r', encoding='utf-8') as f:
                existing_mappings = json.load(f)
        
        # Update with new mapping
        existing_mappings.update(mapping)
        
        # Save back
        with open(mappings_file, 'w', encoding='utf-8') as f:
            json.dump(existing_mappings, f, indent=2, ensure_ascii=False)
        
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

