"""
Session management routes
"""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json
import io
import re
from datetime import datetime

import pandas as pd

from models.schemas import (
    SessionCreate, SessionInfo, SessionData, SessionUpdate,
    SessionMetadataUpdate, SessionPromptTypesUpdate, CSVRow,
    PatientDiagnosisResolveRequest, PatientDiagnosisResolveResponse,
    DiagnosisValidationReport, PatientDiagnosisInfo,
    ExportConflict, ExportValidationResponse,
)

router = APIRouter()

# In-memory session storage (could be replaced with database)
_sessions: Dict[str, Dict] = {}


def _get_sessions_dir() -> Path:
    """Get directory for storing sessions"""
    backend_dir = Path(__file__).parent.parent
    sessions_dir = backend_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def _load_session(session_id: str) -> Dict:
    """Load session from file"""
    sessions_dir = _get_sessions_dir()
    session_file = sessions_dir / f"{session_id}.json"
    
    if not session_file.exists():
        raise FileNotFoundError(f"Session {session_id} not found")
    
    with open(session_file, 'r', encoding='utf-8') as f:
        session_data = json.load(f)
    
    # Ensure evaluation_mode is set (for backward compatibility with old sessions)
    if 'evaluation_mode' not in session_data:
        # Auto-detect: if any note has annotations, use evaluation mode
        has_annotations = any(
            note.get('annotations') and str(note.get('annotations', '')).strip()
            for note in session_data.get('notes', [])
        )
        session_data['evaluation_mode'] = 'evaluation' if has_annotations else 'validation'
        # Save the updated session
        _save_session(session_id, session_data)
    
    return session_data


def _json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _save_session(session_id: str, session_data: Dict):
    """Save session to file"""
    sessions_dir = _get_sessions_dir()
    session_file = sessions_dir / f"{session_id}.json"

    session_data['updated_at'] = datetime.now().isoformat()

    with open(session_file, 'w', encoding='utf-8') as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False, default=_json_serial)
    
    # Also update in-memory cache
    _sessions[session_id] = session_data


@router.post("/import", response_model=SessionInfo)
async def import_session(file: UploadFile = File(...)):
    """Import a session from a previously exported JSON file."""
    import uuid

    if not (file.filename or "").endswith(".json"):
        raise HTTPException(status_code=400, detail="File must be a .json file")

    content = await file.read()
    try:
        session_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON content")

    required_fields = ["name", "notes", "annotations", "prompt_types"]
    missing = [f for f in required_fields if f not in session_data]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required fields: {missing}")

    new_session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    imported = {
        **session_data,
        "session_id": new_session_id,
        "created_at": session_data.get("created_at", now),
        "updated_at": now,
    }
    imported.pop("exported_at", None)
    imported.pop("export_version", None)

    _save_session(new_session_id, imported)

    return SessionInfo(
        session_id=new_session_id,
        name=imported["name"],
        description=imported.get("description"),
        created_at=imported["created_at"],
        updated_at=imported["updated_at"],
        note_count=len(imported.get("notes", [])),
        prompt_types=imported.get("prompt_types", []),
        center=imported.get("center"),
        evaluation_mode=imported.get("evaluation_mode", "validation"),
    )


@router.post("", response_model=SessionInfo)
async def create_session(session: SessionCreate):
    """Create new annotation session"""
    import uuid
    session_id = str(uuid.uuid4())

    # Ensure note_ids are unique — deduplicate by appending row index when needed
    seen_ids: set = set()
    duplicate_ids: set = set()
    for note in session.csv_data:
        if note.note_id in seen_ids:
            duplicate_ids.add(note.note_id)
        seen_ids.add(note.note_id)

    if duplicate_ids:
        print(f"[WARN] create_session: duplicate note_ids detected: {duplicate_ids}. Deduplicating.")
        deduped = []
        for idx, note in enumerate(session.csv_data):
            if note.note_id in duplicate_ids:
                deduped.append(CSVRow(
                    text=note.text,
                    date=note.date,
                    p_id=note.p_id,
                    note_id=f"{note.note_id}_{idx}",
                    report_type=note.report_type,
                    annotations=note.annotations,
                ))
            else:
                deduped.append(note)
        session = SessionCreate(
            name=session.name,
            description=session.description,
            csv_data=deduped,
            prompt_types=session.prompt_types,
            evaluation_mode=session.evaluation_mode,
            center=session.center,
            report_type_mapping=session.report_type_mapping,
        )

    # Determine evaluation mode: check if any note has annotations
    evaluation_mode = session.evaluation_mode or "validation"
    if evaluation_mode == "validation":
        # Auto-detect: if any note has annotations, switch to evaluation mode
        has_annotations = any(
            note.annotations and str(note.annotations).strip()
            for note in session.csv_data
        )
        if has_annotations:
            evaluation_mode = "evaluation"
    
    # Infer center from prompt_types if not explicitly provided
    center = session.center
    if not center and session.prompt_types:
        # Extract center suffix from prompt_types by matching against known centers
        # e.g. "alcohol-habits-int-hnc" with known center "INT-HNC" → match suffix "-int-hnc"
        from routes.prompts import get_latest_prompts_dir
        prompts_dir = get_latest_prompts_dir()
        known_centers = sorted(
            (d.name for d in prompts_dir.iterdir()
             if d.is_dir() and (d / "prompts.json").exists()),
            key=len, reverse=True  # longest first to match "INT-SARC" before "INT"
        ) if prompts_dir.is_dir() else []
        center_votes: Dict[str, int] = {}
        for pt in session.prompt_types:
            for kc in known_centers:
                suffix = f"-{kc.lower()}"
                if pt.endswith(suffix):
                    center_votes[kc] = center_votes.get(kc, 0) + 1
                    break
        if center_votes:
            center = max(center_votes, key=center_votes.get)
            print(f"[INFO] Inferred center '{center}' from prompt_types")

    session_data = {
        'session_id': session_id,
        'name': session.name,
        'description': session.description,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        'notes': [note.dict() for note in session.csv_data],
        'annotations': {},
        'prompt_types': session.prompt_types,
        'center': center,
        'evaluation_mode': evaluation_mode,
        'report_type_mapping': session.report_type_mapping
    }

    _save_session(session_id, session_data)

    return SessionInfo(
        session_id=session_id,
        name=session.name,
        description=session.description,
        created_at=datetime.fromisoformat(session_data['created_at']),
        updated_at=datetime.fromisoformat(session_data['updated_at']),
        note_count=len(session.csv_data),
        prompt_types=session.prompt_types,
        center=center,
        evaluation_mode=evaluation_mode
    )


@router.get("/{session_id}", response_model=SessionData)
async def get_session(session_id: str):
    """Get session data"""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    # Convert annotations to proper format
    from services.structured_generator import detect_repetition_hallucination
    import re as _re_sess
    annotations = {}
    for note_id, prompt_anns in session.get('annotations', {}).items():
        annotations[note_id] = {}
        for prompt_type, ann_data in prompt_anns.items():
            # Ensure all fields are preserved when loading from JSON
            if isinstance(ann_data, dict):
                # Retroactive hallucination detection for annotations saved before this feature
                if ann_data.get('raw_response') and ann_data.get('hallucination_flags') is None:
                    _rr = ann_data['raw_response']
                    _reasoning = ann_data.get('reasoning', '')
                    _raw_for_scan = ""
                    try:
                        import json as _json_sess
                        _parsed = _json_sess.loads(_rr)
                        if isinstance(_parsed, dict):
                            _reasoning = _parsed.get('reasoning', _reasoning)
                    except (ValueError, TypeError):
                        _m = _re_sess.search(r'"reasoning"\s*:\s*"(.*?)(?:"\s*,|\Z)', _rr, _re_sess.DOTALL)
                        if _m and len(_m.group(1)) > len(_reasoning):
                            _reasoning = _m.group(1)
                        _raw_for_scan = _rr
                    flags = detect_repetition_hallucination(
                        reasoning=_reasoning,
                        raw_output=_raw_for_scan,
                    )
                    if flags:
                        ann_data['hallucination_flags'] = [f.model_dump() for f in flags]
                annotations[note_id][prompt_type] = ann_data
            else:
                # If it's already a SessionAnnotation, convert to dict
                annotations[note_id][prompt_type] = ann_data.dict() if hasattr(ann_data, 'dict') else ann_data
    
    return SessionData(
        session_id=session['session_id'],
        name=session['name'],
        description=session.get('description'),
        created_at=datetime.fromisoformat(session['created_at']),
        updated_at=datetime.fromisoformat(session['updated_at']),
        notes=session['notes'],
        annotations=annotations,
        prompt_types=session['prompt_types'],
        evaluation_mode=session.get('evaluation_mode', 'validation'),
        report_type_mapping=session.get('report_type_mapping'),
        note_prompt_overrides=session.get('note_prompt_overrides'),
        note_prompt_exclusions=session.get('note_prompt_exclusions')
    )


@router.put("/{session_id}", response_model=SessionData)
async def update_session(session_id: str, update: SessionUpdate):
    """Update session annotations"""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    # Update annotations
    session['annotations'] = update.annotations
    
    # Convert annotation objects to dicts for storage
    annotations_dict = {}
    for note_id, prompt_anns in update.annotations.items():
        annotations_dict[note_id] = {}
        for prompt_type, ann in prompt_anns.items():
            if isinstance(ann, dict):
                ann_dict = ann
            else:
                ann_dict = ann.dict()
            # Clear derived_field_values when user manually edits an annotation
            # so stale pattern-matched values are not used at export time
            if ann_dict.get('edited'):
                ann_dict.pop('derived_field_values', None)
            annotations_dict[note_id][prompt_type] = ann_dict
    
    session['annotations'] = annotations_dict
    _save_session(session_id, session)
    
    return await get_session(session_id)


@router.patch("/{session_id}", response_model=SessionData)
async def update_session_metadata(session_id: str, update: SessionMetadataUpdate):
    """Update session name and/or report_type_mapping"""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if update.name is not None:
        session['name'] = update.name
    if update.note_prompt_overrides is not None:
        session['note_prompt_overrides'] = update.note_prompt_overrides
    if update.note_prompt_exclusions is not None:
        session['note_prompt_exclusions'] = update.note_prompt_exclusions
    if update.report_type_mapping is not None:
        session['report_type_mapping'] = update.report_type_mapping
        # Set prompt_types to exactly the union of all mapped prompt types
        new_prompt_types = set()
        for prompt_types_list in update.report_type_mapping.values():
            new_prompt_types.update(prompt_types_list)

        # Remove annotations per-note based on each note's report type
        # Build a lookup from note_id to report_type
        note_report_types = {}
        for note in session.get('notes', []):
            nid = note.get('note_id', '')
            rt = note.get('report_type', '')
            if nid:
                note_report_types[nid] = rt

        note_prompt_overrides = session.get('note_prompt_overrides', {})
        annotations = session.get('annotations', {})
        for note_id in list(annotations.keys()):
            rt = note_report_types.get(note_id, '')
            # Prompt types now allowed for this note's report type + per-note overrides
            allowed = set(update.report_type_mapping.get(rt, []))
            allowed.update(note_prompt_overrides.get(note_id, []))
            for pt in list(annotations[note_id].keys()):
                if pt not in allowed:
                    del annotations[note_id][pt]
        session['annotations'] = annotations
        session['prompt_types'] = list(new_prompt_types)

    _save_session(session_id, session)

    return await get_session(session_id)


@router.get("", response_model=List[SessionInfo])
async def list_sessions():
    """List all sessions"""
    sessions_dir = _get_sessions_dir()
    sessions = []
    
    for session_file in sessions_dir.glob("*.json"):
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
                sessions.append(SessionInfo(
                    session_id=session_data['session_id'],
                    name=session_data['name'],
                    description=session_data.get('description'),
                    created_at=datetime.fromisoformat(session_data['created_at']),
                    updated_at=datetime.fromisoformat(session_data['updated_at']),
                    note_count=len(session_data.get('notes', [])),
                    prompt_types=session_data.get('prompt_types', []),
                    evaluation_mode=session_data.get('evaluation_mode', 'validation')
                ))
        except Exception as e:
            print(f"[WARN] Failed to load session {session_file}: {e}")
    
    # Sort by updated_at descending
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    
    return sessions


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    sessions_dir = _get_sessions_dir()
    session_file = sessions_dir / f"{session_id}.json"
    
    if not session_file.exists():
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    try:
        session_file.unlink()
        # Also remove from in-memory cache if present
        if session_id in _sessions:
            del _sessions[session_id]
        return {"success": True, "message": f"Session {session_id} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


@router.post("/{session_id}/prompt_types", response_model=SessionData)
async def add_prompt_types(session_id: str, update: SessionPromptTypesUpdate):
    """Add prompt types to a session"""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    # Validate that prompt types exist
    from routes.prompts import load_prompts_json
    prompts = load_prompts_json()
    # Prompts are nested: { "INT-SARC": { "gender-int-sarc": {...}, ... }, "MSCI": {...}, ... }
    # Flatten to get all available prompt types
    available_prompt_types = []
    for category, category_prompts in prompts.items():
        if isinstance(category_prompts, dict):
            available_prompt_types.extend(category_prompts.keys())
    
    # Check which prompt types are new
    current_prompt_types = set(session.get('prompt_types', []))
    new_prompt_types = [pt for pt in update.prompt_types if pt not in current_prompt_types]
    
    # Validate new prompt types exist
    invalid_types = [pt for pt in new_prompt_types if pt not in available_prompt_types]
    if invalid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prompt types: {invalid_types}. Available types: {available_prompt_types}"
        )
    
    # Add new prompt types
    updated_prompt_types = list(current_prompt_types) + new_prompt_types
    session['prompt_types'] = updated_prompt_types
    
    _save_session(session_id, session)
    
    return await get_session(session_id)


@router.delete("/{session_id}/prompt_types", response_model=SessionData)
async def remove_prompt_types(session_id: str, prompt_types: List[str] = Query(...)):
    """Remove prompt types from a session"""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    current_prompt_types = session.get('prompt_types', [])
    prompt_types_to_remove = prompt_types

    # Remove prompt types
    updated_prompt_types = [pt for pt in current_prompt_types if pt not in prompt_types_to_remove]

    # Ensure at least one prompt type remains
    if len(updated_prompt_types) == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove all prompt types. A session must have at least one prompt type."
        )

    # Remove annotations for removed prompt types
    annotations = session.get('annotations', {})
    for note_id in annotations:
        for removed_pt in prompt_types_to_remove:
            if removed_pt in annotations[note_id]:
                del annotations[note_id][removed_pt]

    session['prompt_types'] = updated_prompt_types
    session['annotations'] = annotations

    _save_session(session_id, session)

    return await get_session(session_id)


def _build_prompt_to_core_variable_mapping() -> Dict[str, str]:
    """
    Build mapping from prompt_type to core_variable (Entity.fieldName).

    Uses entity_mapping.field_mappings from prompts.json when available,
    falls back to a predefined mapping for common prompt types.
    """
    from routes.prompts import load_prompts_json

    mapping = {}

    # Try to load mappings from prompts.json entity_mapping
    try:
        prompts = load_prompts_json()
        for category in prompts:
            if category not in prompts:
                continue
            for prompt_key, prompt_data in prompts[category].items():
                if isinstance(prompt_data, dict):
                    em = prompt_data.get('entity_mapping', {})
                    if em:
                        fm = em.get('field_mappings', [])
                        for m in fm:
                            et = m.get('entity_type', '')
                            fn = m.get('field_name', '')
                            if et and fn:
                                mapping[prompt_key] = f'{et}.{fn}'
                                break
    except Exception as e:
        print(f"[WARN] Failed to load entity mappings from prompts.json: {e}")

    # Predefined mapping for common prompt types that may not have entity_mapping yet
    # Based on IDEA4RC data model and sarcoma_dictionary.json
    predefined_mapping = {
        # Diagnosis entity (names match SARC_V2(in).csv)
        "histological-tipo-int": "Diagnosis.histologySubgroup",
        "histological": "Diagnosis.histologySubgroup",
        "tumorsite-int": "Diagnosis.subsite",
        "tumorsite": "Diagnosis.subsite",
        "biopsygrading-int": "Diagnosis.biopsyGrading",
        "biopsygrading": "Diagnosis.biopsyGrading",
        "ageatdiagnosis-int": "Diagnosis.ageAtDiagnosis",
        "ageatdiagnosis": "Diagnosis.ageAtDiagnosis",
        "tumorbiopsytype-int": "Diagnosis.typeOfBiopsy",
        "tumorbiopsytype": "Diagnosis.typeOfBiopsy",
        "biopsymitoticcount-int": "Diagnosis.biopsyMitoticCount",
        "biopsymitoticcount": "Diagnosis.biopsyMitoticCount",
        "tumordepth-int": "Diagnosis.tumourDepth",
        "tumordiameter-int": "Diagnosis.tumorSize",
        "tumordiameter": "Diagnosis.tumorSize",
        "necrosis_in_biopsy-int": "Diagnosis.necrosisInBiopsy",
        "necrosis_in_biopsy": "Diagnosis.necrosisInBiopsy",
        "stage_at_diagnosis-int": "Diagnosis.stageAtDiagnosis",
        "stage_at_diagnosis": "Diagnosis.stageAtDiagnosis",

        # Patient entity
        "gender-int": "Patient.sex",
        "gender": "Patient.sex",
        "patient-bmi": "Patient.bmi",
        "patient-weightheight": "Patient.bmi",

        # PatientFollowUp entity (SARC_V2 uses statusOfPatientAtLastFollowUp)
        "patient-status-int": "PatientFollowUp.statusOfPatientAtLastFollowUp",
        "patient-status": "PatientFollowUp.statusOfPatientAtLastFollowUp",
        "last_contact_date": "PatientFollowUp.lastContact",

        # Surgery entity (SARC_V2 uses surgicalSpecimenGradingOnlyInUntreatedTumours)
        "surgerymargins-int": "Surgery.marginsAfterSurgery",
        "surgerymargins": "Surgery.marginsAfterSurgery",
        "surgerytype-fs30-int": "Surgery.surgeryType",
        "surgerytype": "Surgery.surgeryType",
        "surgical-specimen-grading-int": "Surgery.surgicalSpecimenGradingOnlyInUntreatedTumours",
        "surgical-mitotic-count-int": "Surgery.surgicalSpecimenMitoticCount",
        "necrosis_in_surgical-int": "Surgery.necrosisInSurgicalSpecimen",
        "necrosis_in_surgical": "Surgery.necrosisInSurgicalSpecimen",
        "reexcision-int": "Surgery.reExcision",

        # SystemicTreatment entity
        "chemotherapy_start-int": "SystemicTreatment.intent",
        "chemotherapy_start": "SystemicTreatment.intent",
        "chemotherapy_end-int": "SystemicTreatment.reasonForEndOfTreatment",
        "chemotherapy_end": "SystemicTreatment.reasonForEndOfTreatment",
        "response-to-int": "SystemicTreatment.treatmentResponse",
        "response-to": "SystemicTreatment.treatmentResponse",
        "other-systemic-therapy-int": "SystemicTreatment.typeOfSystemicTreatment",
        "other-systemic-therapy": "SystemicTreatment.typeOfSystemicTreatment",

        # Radiotherapy entity (SARC_V2 uses rtTreatmentCompletedAsPlanned)
        "radiotherapy_start-int": "Radiotherapy.intent",
        "radiotherapy_start": "Radiotherapy.intent",
        "radiotherapy_end-int": "Radiotherapy.rtTreatmentCompletedAsPlanned",
        "radiotherapy_end": "Radiotherapy.rtTreatmentCompletedAsPlanned",

        # EpisodeEvent entity
        "recur_or_prog-int": "EpisodeEvent.diseaseStatus",
        "recur_or_prog": "EpisodeEvent.diseaseStatus",
        "recurrencetype-int": "EpisodeEvent.recurrenceType",
        "recurrencetype": "EpisodeEvent.recurrenceType",

        # CancerEpisode entity
        "previous_cancer_treatment-int": "CancerEpisode.previousCancerTreatment",
        "previous_cancer_treatment": "CancerEpisode.previousCancerTreatment",
        "occurrence_cancer-int": "CancerEpisode.occurrenceOfOtherCancer",
        "occurrence_cancer": "CancerEpisode.occurrenceOfOtherCancer",
    }

    # Merge: prompts.json mappings take precedence over predefined
    for k, v in predefined_mapping.items():
        if k not in mapping:
            mapping[k] = v

    return mapping


def _extract_entity_from_core_variable(core_variable: str) -> str:
    """Extract entity name from core_variable (e.g., 'Diagnosis.histologySubgroup' -> 'Diagnosis')"""
    if '.' in core_variable:
        return core_variable.split('.')[0]
    return core_variable


def _extract_value_from_annotation(annotation_text: str, prompt_type: str) -> str:
    """
    Extract the actual value from a template-formatted annotation.

    For example:
    - "Biopsy grading (FNCLCC): 3." -> "3"
    - "Patient's gender male." -> "male"
    - "Histological type: Undifferentiated sarcoma (8805/3)." -> "Undifferentiated sarcoma (8805/3)"
    - "Tumor site (Trunk wall): Flank." -> "Flank"
    """
    if not annotation_text:
        return ''

    text = annotation_text.strip()

    # Common extraction patterns based on template formats
    patterns = [
        # "Biopsy grading (FNCLCC): [value]." or "Biopsy grading: [value]"
        r'^Biopsy grading.*?:\s*(.+?)\.?$',
        # "Patient's gender [value]."
        r"^Patient's gender\s+(.+?)\.?$",
        # "Histological type: [value]."
        r'^Histological type:\s*(.+?)\.?$',
        # "Tumor site ([location]): [value]." or "Tumor site: [value]"
        r'^Tumor site.*?:\s*(.+?)\.?$',
        # "Age at diagnosis: [value]" or similar
        r'^Age at diagnosis:\s*(.+?)\.?$',
        # "Margins after surgery: [value]"
        r'^Margins after surgery:\s*(.+?)\.?$',
        # "[Something]: [value]." - generic colon-separated
        r'^[^:]+:\s*(.+?)\.?$',
        # "Annotation: [value]" format
        r'^Annotation:\s*(.+?)\.?$',
    ]

    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            extracted = match.group(1).strip()
            # Remove trailing period if present
            if extracted.endswith('.'):
                extracted = extracted[:-1].strip()
            return extracted

    # If no pattern matches, return original text (cleaned)
    return text.rstrip('.')


def _normalize_date(date_str: str) -> str:
    """
    Normalize date string to DD/MM/YYYY format for consistency.
    Handles: DD/MM/YYYY, YYYY-MM-DD, and other common formats.
    """
    if not date_str:
        return ''

    date_str = str(date_str).strip()

    # Already in DD/MM/YYYY format
    if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', date_str):
        return date_str

    # ISO format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS
    iso_match = re.match(r'^(\d{4})-(\d{2})-(\d{2})', date_str)
    if iso_match:
        year, month, day = iso_match.groups()
        return f"{day}/{month}/{year}"

    # Try to parse with datetime
    try:
        from datetime import datetime as dt
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f']:
            try:
                parsed = dt.strptime(date_str.split()[0] if ' ' in date_str else date_str, fmt.split()[0])
                return parsed.strftime('%d/%m/%Y')
            except ValueError:
                continue
    except Exception:
        pass

    return date_str


def _clean_value_by_data_type(value: str, data_type: str) -> str:
    """Extract the actual typed value from template-formatted annotation text.

    For date types, extracts the date pattern (DD/MM/YYYY or YYYY-MM-DD).
    For Integer types, extracts the first standalone integer.
    For float types, extracts the first standalone number (int or decimal).
    Other types pass through unchanged.
    """
    if not value or not value.strip():
        return value

    v = value.strip()

    if 'date' in data_type.lower() or 'iso' in data_type.lower():
        # Try DD/MM/YYYY or DD-MM-YYYY first
        date_match = re.search(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b', v)
        if date_match:
            return _normalize_date(date_match.group(1))
        # Try YYYY-MM-DD
        date_match = re.search(r'\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})\b', v)
        if date_match:
            return _normalize_date(date_match.group(1))
        return v

    if data_type == 'Integer':
        int_match = re.search(r'\b(\d+)\b', v)
        if int_match:
            return int_match.group(1)
        return v

    if data_type == 'float':
        float_match = re.search(r'\b(\d+(?:\.\d+)?)\b', v)
        if float_match:
            return float_match.group(1)
        return v

    return v


_ABSENCE_PATTERNS = [
    re.compile(r'\bnot\s+(specified|available|applicable|mentioned|present|found)\b', re.IGNORECASE),
    re.compile(r'^unknown\b', re.IGNORECASE),
    re.compile(r'\bno\s+(information|data|result|finding|value)\b', re.IGNORECASE),
    re.compile(r'\binformation\s+not\s+available\b', re.IGNORECASE),
    re.compile(r'^\[.*\]$'),
    re.compile(r'^absent\.?$', re.IGNORECASE),
    re.compile(r'^none\.?$', re.IGNORECASE),
]


def _classify_absence(value: str) -> str:
    """Return the reason a value is an absence indicator, or empty string if it's not."""
    if not value or not value.strip():
        return "Empty value"
    v = value.strip()
    for pat in _ABSENCE_PATTERNS:
        m = pat.search(v)
        if m:
            matched = m.group(0).strip()
            return f"Absence indicator detected: \"{matched}\""
    return ""


def _build_export_rows(session: Dict) -> Tuple[List[Dict], List[Dict]]:
    """Build export rows from session annotations.

    Shared logic used by both the label export and coded export endpoints.
    Each row includes a '_note_id' field for internal tracking (stripped before CSV output).

    Returns:
        Tuple of (rows, excluded_rows) where excluded_rows contains rows that were
        filtered out due to absence values (Not applicable, Unknown, etc.)
    """
    prompt_mapping = _build_prompt_to_core_variable_mapping()
    notes_by_id = {n.get('note_id', ''): n for n in session.get('notes', [])}

    record_id_tracker: Dict[tuple, int] = {}
    current_record_id = 0

    rows = []
    excluded_rows = []
    for note_id, prompt_annotations in session.get('annotations', {}).items():
        note = notes_by_id.get(note_id)

        if note is None:
            for nid, n in notes_by_id.items():
                if note_id in nid or nid in note_id:
                    note = n
                    break

        patient_id = note.get('p_id', '') if note else ''
        note_date = note.get('date', '') if note else ''
        note_date = _normalize_date(note_date)

        for prompt_type, ann in prompt_annotations.items():
            if isinstance(ann, dict):
                annotation_text = ann.get('annotation_text', '')
                icdo3_data = ann.get('icdo3_code', {})
                icdo3_code = icdo3_data.get('code', '') if isinstance(icdo3_data, dict) else ''
                extracted_date = ann.get('extracted_date', '')
                if not extracted_date:
                    date_info = ann.get('date', {})
                    if isinstance(date_info, dict):
                        extracted_date = date_info.get('date_value', '')
                    elif isinstance(date_info, str):
                        extracted_date = date_info
                derived_field_values = ann.get('derived_field_values') or {}
            else:
                annotation_text = ''
                icdo3_code = ''
                extracted_date = ''
                derived_field_values = {}

            if not annotation_text or not annotation_text.strip():
                continue

            core_variable = prompt_mapping.get(prompt_type, prompt_type)
            # Use derived_field_values if available for this field (set by output_word_mappings at annotation time)
            _field_name = core_variable.split('.')[-1] if '.' in core_variable else ''
            if _field_name and _field_name in derived_field_values:
                extracted_value = derived_field_values[_field_name]
            else:
                extracted_value = _extract_value_from_annotation(annotation_text, prompt_type)
            entity = _extract_entity_from_core_variable(core_variable)

            if extracted_date:
                date_ref = _normalize_date(extracted_date)
            else:
                date_ref = note_date

            # Filter out absence/not-applicable values
            absence_reason = _classify_absence(extracted_value)
            if absence_reason:
                excluded_rows.append({
                    'patient_id': patient_id,
                    'core_variable': core_variable,
                    'prompt_type': prompt_type,
                    'note_id': note_id,
                    'original_value': extracted_value or annotation_text,
                    'reason': absence_reason,
                })
                continue

            data_type = _get_data_type_for_variable(core_variable)

            record_key = (patient_id, entity, date_ref)
            if record_key not in record_id_tracker:
                current_record_id += 1
                record_id_tracker[record_key] = current_record_id

            record_id = record_id_tracker[record_key]

            rows.append({
                '_note_id': note_id,
                '_prompt_type': prompt_type,
                'patient_id': patient_id,
                'original_source': 'NLP_LLM',
                'core_variable': core_variable,
                'date_ref': date_ref,
                'value': extracted_value,
                'record_id': record_id,
                'linked_to': '',
                'quality': '',
                'types': data_type,
                'icdo3_code': icdo3_code,
                'entity': entity
            })

    return rows, excluded_rows


# ---------------------------------------------------------------------------
# Cardinality-based validation & deduplication
# ---------------------------------------------------------------------------

_CARDINALITY_CACHE: Optional[Dict[str, int]] = None


def _load_entity_cardinality() -> Dict[str, int]:
    """Load entity cardinality config (1 = non-repeatable, 0 = repeatable)."""
    global _CARDINALITY_CACHE
    if _CARDINALITY_CACHE is None:
        path = Path(__file__).resolve().parent.parent / "data" / "entities_cardinality.json"
        with open(path) as f:
            _CARDINALITY_CACHE = json.load(f)
    return _CARDINALITY_CACHE


def _validate_and_deduplicate_rows(
    rows: List[Dict],
) -> Tuple[List[Dict], List[ExportConflict], int]:
    """Validate cardinality constraints and deduplicate exact rows.

    Returns:
        Tuple of (clean_rows, conflicts, deduplicated_count)
    """
    cardinality = _load_entity_cardinality()

    # --- 1. Deduplicate exact rows ---
    seen = set()
    deduped: List[Dict] = []
    dedup_count = 0
    for row in rows:
        key = (row['patient_id'], row['entity'], row['date_ref'],
               row['core_variable'], row['value'])
        if key in seen:
            dedup_count += 1
            continue
        seen.add(key)
        deduped.append(row)

    # --- 2. Detect conflicts ---
    from collections import defaultdict
    conflicts: List[ExportConflict] = []

    # Group values by the appropriate key based on cardinality
    # Non-repeatable (1): group by (patient_id, core_variable) — date irrelevant
    # Repeatable (0):     group by (patient_id, core_variable, date_ref)
    non_rep_values: Dict[tuple, set] = defaultdict(set)
    rep_values: Dict[tuple, set] = defaultdict(set)

    for row in deduped:
        entity = row['entity']
        card = cardinality.get(entity)  # None if entity unknown → treat as repeatable

        if card == 1:
            group_key = (row['patient_id'], row['core_variable'])
            non_rep_values[group_key].add(row['value'])
        else:
            group_key = (row['patient_id'], row['core_variable'], row['date_ref'])
            rep_values[group_key].add(row['value'])

    # Non-repeatable conflicts
    for (pid, cv), values in non_rep_values.items():
        if len(values) > 1:
            conflicts.append(ExportConflict(
                patient_id=pid,
                core_variable=cv,
                date_ref=None,
                conflicting_values=sorted(values),
                conflict_type="non_repeatable",
            ))

    # Repeatable same-date conflicts
    for (pid, cv, date_ref), values in rep_values.items():
        if len(values) > 1:
            conflicts.append(ExportConflict(
                patient_id=pid,
                core_variable=cv,
                date_ref=date_ref,
                conflicting_values=sorted(values),
                conflict_type="repeatable_same_date",
            ))

    # --- 3. Reassign record_id based on cardinality ---
    record_id_tracker: Dict[tuple, int] = {}
    current_record_id = 0
    for row in deduped:
        entity = row['entity']
        card = cardinality.get(entity)
        if card == 1:
            record_key = (row['patient_id'], entity)
        else:
            record_key = (row['patient_id'], entity, row['date_ref'])

        if record_key not in record_id_tracker:
            current_record_id += 1
            record_id_tracker[record_key] = current_record_id
        row['record_id'] = record_id_tracker[record_key]

    return deduped, conflicts, dedup_count


_SARC_COLUMNS = [
    'patient_id', 'original_source', 'core_variable', 'date_ref',
    'value', 'record_id', 'linked_to', 'quality'
]


def _build_excluded_summary(excluded_rows: List[Dict]) -> str:
    """Build a JSON summary of excluded rows for the response header."""
    return json.dumps([
        {
            "patient_id": e.get("patient_id", ""),
            "variable": e.get("core_variable", ""),
            "value": e.get("original_value", ""),
            "reason": e.get("reason", ""),
        }
        for e in excluded_rows
    ], ensure_ascii=False)


_DIAGNOSIS_MERGE_VARS = {'Diagnosis.histologySubgroup', 'Diagnosis.subsite'}


def _merge_diagnosis_rows(
    rows: List[Dict],
    patient_diagnoses: Dict[str, Dict],
    value_field: str = 'query_code',
) -> List[Dict]:
    """Replace individual histology/topography rows with merged Diagnosis.diagnosisCode rows.

    Args:
        rows: Export rows from _build_export_rows()
        patient_diagnoses: session['patient_diagnoses'] dict keyed by patient_id
        value_field: 'query_code' for labels export, 'csv_id' for codes export

    Returns:
        New list of rows with diagnosis rows merged at the patient level.
    """
    if not patient_diagnoses:
        # No patient_diagnoses computed yet — pass through unchanged for backward compat
        return rows

    diag_added: set = set()   # patient_ids that already have a diagnosisCode row
    merged: List[Dict] = []

    for row in rows:
        if row['core_variable'] not in _DIAGNOSIS_MERGE_VARS:
            merged.append(row)
            continue

        pid = row['patient_id']
        if pid in diag_added:
            # Already emitted a diagnosisCode row for this patient — skip
            continue

        diag_added.add(pid)
        diag = patient_diagnoses.get(pid, {})
        status = diag.get('status', '')

        if status in ('auto_resolved', 'manually_resolved'):
            resolved = diag.get('resolved_code') or {}
            if value_field == 'csv_id':
                value = diag.get('csv_id', '') or ''
                if not value:
                    value = 'UNRESOLVED::no_csv_id'
            else:
                value = resolved.get('query_code', '') or ''
                if not value:
                    value = 'UNRESOLVED::no_query_code'
        else:
            value = 'UNRESOLVED::needs_review'

        merged.append({
            **row,
            'core_variable': 'Diagnosis.diagnosisCode',
            'value': value,
        })

    return merged


def _build_diagnosis_warnings(patient_diagnoses: Dict[str, Dict]) -> str:
    """Build JSON warning list for patients that still need review."""
    warnings = []
    for pid, diag in patient_diagnoses.items():
        if not isinstance(diag, dict):
            continue
        if diag.get('status') == 'needs_review':
            warnings.append({
                'patient_id': pid,
                'reasons': diag.get('review_reasons', []),
            })
    if not warnings:
        return ''
    return json.dumps(warnings, ensure_ascii=False)


@router.get("/{session_id}/export/validate", response_model=ExportValidationResponse)
async def validate_export(session_id: str):
    """Pre-validate export data for cardinality conflicts.

    Returns conflict details without generating CSV so the frontend can
    warn the user before attempting to export.
    """
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    rows, _excluded = _build_export_rows(session)
    patient_diagnoses = session.get('patient_diagnoses', {})
    rows = _merge_diagnosis_rows(rows, patient_diagnoses, value_field='query_code')
    clean_rows, conflicts, dedup_count = _validate_and_deduplicate_rows(rows)

    return ExportValidationResponse(
        valid=len(conflicts) == 0,
        conflicts=conflicts,
        row_count=len(clean_rows),
        deduplicated_count=dedup_count,
    )


@router.get("/{session_id}/export")
async def export_session_for_pipeline(session_id: str):
    """Export validated annotations in pipeline-compatible CSV format (labels).

    Format matches SARC_V2(in).csv: semicolon-delimited, 8 columns.
    Rows with absence values (Not applicable, Unknown, etc.) are excluded.
    Blocks with HTTP 409 if cardinality conflicts are detected.
    """
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    rows, excluded = _build_export_rows(session)

    # Patient-level diagnosis merging: replace individual histology/topography rows
    # with a merged Diagnosis.diagnosisCode row using query_code format
    patient_diagnoses = session.get('patient_diagnoses', {})
    rows = _merge_diagnosis_rows(rows, patient_diagnoses, value_field='query_code')

    # Validate cardinality constraints and deduplicate
    rows, conflicts, _ = _validate_and_deduplicate_rows(rows)
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Export blocked: cardinality conflicts detected. Resolve them before exporting.",
                "conflicts": [c.model_dump() for c in conflicts],
            },
        )

    # Strip internal fields before CSV output
    for row in rows:
        row.pop('_note_id', None)
        row.pop('_prompt_type', None)
        row.pop('types', None)
        row.pop('icdo3_code', None)
        row.pop('entity', None)

    df = pd.DataFrame(rows, columns=_SARC_COLUMNS)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, sep=';')

    headers = {
        "Content-Disposition": f"attachment; filename={session_id}_validated.csv",
        "Access-Control-Expose-Headers": "X-Excluded-Rows, X-Diagnosis-Warnings",
    }
    if excluded:
        headers["X-Excluded-Rows"] = _build_excluded_summary(excluded)

    diag_warnings = _build_diagnosis_warnings(patient_diagnoses)
    if diag_warnings:
        headers["X-Diagnosis-Warnings"] = diag_warnings

    return StreamingResponse(
        iter([csv_buffer.getvalue()]),
        media_type="text/csv",
        headers=headers,
    )


@router.get("/{session_id}/export/codes")
async def export_session_coded(session_id: str):
    """Export annotations with CodeableConcept values resolved to IDEA4RC codes.

    Histology + topography rows are merged into a single Diagnosis.diagnosisCode
    row using the unified ICD-O-3 code saved during annotation.
    Non-CodeableConcept values pass through unchanged.
    Unresolved values are prefixed with 'UNRESOLVED::'.
    """
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    from lib.code_resolver import CodeResolver
    resolver = CodeResolver()

    # Build prompt_type -> value_code_mappings lookup from prompts.json
    value_code_lookup: Dict[str, Dict[str, str]] = {}
    try:
        from routes.prompts import load_prompts_json
        prompts_data = load_prompts_json()
        for center_key, center_prompts in prompts_data.items():
            if not isinstance(center_prompts, dict):
                continue
            for pt, prompt_data in center_prompts.items():
                if isinstance(prompt_data, dict):
                    em = prompt_data.get('entity_mapping', {})
                    if em:
                        for fm in em.get('field_mappings', []):
                            vcm = fm.get('value_code_mappings')
                            if vcm and isinstance(vcm, dict):
                                value_code_lookup[pt] = vcm
                                break  # use first field mapping with value_code_mappings
    except Exception as e:
        print(f"[WARN] Failed to load value_code_mappings from prompts.json: {e}")

    rows, excluded = _build_export_rows(session)

    # Patient-level diagnosis merging: replace individual histology/topography rows
    # with a merged Diagnosis.diagnosisCode row using csv_id (numeric ID)
    patient_diagnoses = session.get('patient_diagnoses', {})
    rows = _merge_diagnosis_rows(rows, patient_diagnoses, value_field='csv_id')

    # Validate cardinality constraints and deduplicate
    rows, conflicts, _ = _validate_and_deduplicate_rows(rows)
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Export blocked: cardinality conflicts detected. Resolve them before exporting.",
                "conflicts": [c.model_dump() for c in conflicts],
            },
        )

    # Build coded rows (resolve CodeableConcept values to IDEA4RC codes)
    coded_rows = []

    for row in rows:
        cv = row['core_variable']

        # Diagnosis.diagnosisCode rows already have their value set by _merge_diagnosis_rows
        if cv == 'Diagnosis.diagnosisCode':
            coded_rows.append({
                k: v for k, v in row.items()
                if k not in ('_note_id', '_prompt_type', 'types', 'icdo3_code', 'entity')
            })
            continue

        # Non-CodeableConcept rows: clean value by data type before passing through
        if row['types'] != 'CodeableConcept':
            cleaned_value = _clean_value_by_data_type(row['value'], row['types'])
            coded_rows.append({
                **{k: v for k, v in row.items()
                   if k not in ('_note_id', '_prompt_type', 'types', 'icdo3_code', 'entity')},
                'value': cleaned_value,
            })
            continue

        # CodeableConcept rows: check value_code_mappings first, then resolve via CodeResolver
        pt = row.get('_prompt_type', '')
        vcm = value_code_lookup.get(pt, {})
        raw_value = row['value']

        if vcm and raw_value in vcm:
            # Direct mapping from value_code_mappings
            value = vcm[raw_value]
        else:
            code_id, _confidence, _method = resolver.resolve(raw_value, cv)
            if code_id is not None:
                value = code_id
            else:
                value = f"UNRESOLVED::{raw_value}"

        coded_rows.append({
            **{k: v for k, v in row.items()
               if k not in ('_note_id', '_prompt_type', 'types', 'icdo3_code', 'entity')},
            'value': value,
        })

    df = pd.DataFrame(coded_rows, columns=_SARC_COLUMNS)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, sep=';')

    headers = {
        "Content-Disposition": f"attachment; filename={session_id}_coded.csv",
        "Access-Control-Expose-Headers": "X-Excluded-Rows, X-Diagnosis-Warnings",
    }
    if excluded:
        headers["X-Excluded-Rows"] = _build_excluded_summary(excluded)

    diag_warnings = _build_diagnosis_warnings(patient_diagnoses)
    if diag_warnings:
        headers["X-Diagnosis-Warnings"] = diag_warnings

    return StreamingResponse(
        iter([csv_buffer.getvalue()]),
        media_type="text/csv",
        headers=headers,
    )


@router.get("/{session_id}/export/session")
async def export_session_json(session_id: str):
    """Export full session as a JSON file for backup/transfer."""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    export_data = {
        **session,
        "exported_at": datetime.now().isoformat(),
        "export_version": "1.0",
    }

    json_bytes = json.dumps(export_data, indent=2, ensure_ascii=False, default=_json_serial).encode("utf-8")
    safe_name = re.sub(r"[^\w\-]", "_", session.get("name", session_id))
    filename = f"{safe_name}_{session_id}.json"

    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Patient Diagnosis endpoints
# ---------------------------------------------------------------------------

@router.get("/{session_id}/diagnoses")
async def get_patient_diagnoses(session_id: str):
    """Compute and return patient-level diagnosis status for all patients."""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    from services.diagnosis_resolver import DiagnosisResolver
    resolver = DiagnosisResolver()
    patient_diagnoses = resolver.resolve_session(session)

    # Persist computed results to session
    session['patient_diagnoses'] = patient_diagnoses
    _save_session(session_id, session)

    patients_list = list(patient_diagnoses.values())
    summary = _diagnosis_summary(patients_list)
    return {**summary, 'patients': patients_list}


@router.post("/{session_id}/diagnoses/{patient_id}/resolve")
async def resolve_patient_diagnosis(
    session_id: str,
    patient_id: str,
    request: PatientDiagnosisResolveRequest,
):
    """Manually resolve a patient's diagnosis by selecting a query_code."""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    from services.diagnosis_resolver import DiagnosisResolver

    resolved = DiagnosisResolver.resolve_manual(request.query_code)
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or unrecognised query code: {request.query_code}",
        )

    # Get or create patient_diagnoses
    patient_diagnoses = session.setdefault('patient_diagnoses', {})
    existing = patient_diagnoses.get(patient_id, {})

    patient_diagnoses[patient_id] = {
        **existing,
        'patient_id': patient_id,
        'status': 'manually_resolved',
        'review_reasons': [],
        'resolved_code': resolved['resolved_code'],
        'csv_id': resolved['csv_id'],
        'resolved_at': datetime.now().isoformat(),
        'resolved_by': 'user',
    }

    _save_session(session_id, session)

    return PatientDiagnosisResolveResponse(
        success=True,
        diagnosis=PatientDiagnosisInfo(**patient_diagnoses[patient_id]),
        message=f"Saved diagnosis: {request.query_code}",
    )


@router.post("/{session_id}/diagnoses/resolve-all")
async def resolve_all_diagnoses(session_id: str):
    """Run the resolver and auto-save all auto-resolvable diagnoses.

    Manually-resolved entries are preserved.
    """
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    from services.diagnosis_resolver import DiagnosisResolver
    resolver = DiagnosisResolver()
    patient_diagnoses = resolver.resolve_session(session, preserve_manual=True)

    session['patient_diagnoses'] = patient_diagnoses
    _save_session(session_id, session)

    patients_list = list(patient_diagnoses.values())
    summary = _diagnosis_summary(patients_list)
    return {**summary, 'patients': patients_list}


def _diagnosis_summary(patients: list) -> dict:
    """Build summary counts from a list of PatientDiagnosisInfo dicts."""
    counts = {'auto_resolved': 0, 'needs_review': 0, 'manually_resolved': 0, 'skipped': 0}
    for p in patients:
        status = p.get('status', 'skipped') if isinstance(p, dict) else 'skipped'
        if status in counts:
            counts[status] += 1
    return {'total_patients': len(patients), **counts}


def _get_data_type_for_variable(core_variable: str) -> str:
    """
    Determine the data type for a core_variable based on field naming conventions.
    """
    field_name = core_variable.split('.')[-1].lower() if '.' in core_variable else core_variable.lower()

    # Date fields
    if any(x in field_name for x in ['date', 'lastcontact', 'startdate', 'enddate']):
        return 'date in the ISO format ISO8601  https://en.wikipedia.org/wiki/ISO_8601'

    # Integer fields
    if any(x in field_name for x in ['age', 'count', 'number', 'cycles']):
        return 'Integer'

    # Float fields
    if any(x in field_name for x in ['bmi', 'diameter', 'dose', 'fractions', 'tumorsize', 'size']):
        return 'float'

    # Boolean fields (exclude rtTreatmentCompletedAsPlanned which is a CodeableConcept)
    if any(x in field_name for x in ['rupture', 'hyperthermia']) or (
        'completed' in field_name and 'asplanned' not in field_name
    ):
        return 'boolean'

    # Reference fields
    if any(x in field_name for x in ['patient', 'episode', 'treatment', 'cancerepisode']):
        if field_name in ['patient', 'cancerepisode', 'episodeevent', 'systemictreatment']:
            return 'reference'

    # String fields
    if any(x in field_name for x in ['hospital', 'location', 'doneby', 'definedat']):
        return 'String'

    # Default to CodeableConcept for coded values
    return 'CodeableConcept'

