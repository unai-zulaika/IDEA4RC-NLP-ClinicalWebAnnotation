"""
Session management routes
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import List, Dict
from pathlib import Path
import json
import io
import re
from datetime import datetime

import pandas as pd

from models.schemas import SessionCreate, SessionInfo, SessionData, SessionUpdate, SessionMetadataUpdate, SessionPromptTypesUpdate

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


@router.post("", response_model=SessionInfo)
async def create_session(session: SessionCreate):
    """Create new annotation session"""
    import uuid
    session_id = str(uuid.uuid4())
    
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
    
    session_data = {
        'session_id': session_id,
        'name': session.name,
        'description': session.description,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        'notes': [note.dict() for note in session.csv_data],
        'annotations': {},
        'prompt_types': session.prompt_types,
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
    annotations = {}
    for note_id, prompt_anns in session.get('annotations', {}).items():
        annotations[note_id] = {}
        for prompt_type, ann_data in prompt_anns.items():
            # Ensure all fields are preserved when loading from JSON
            if isinstance(ann_data, dict):
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
        report_type_mapping=session.get('report_type_mapping')
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
                annotations_dict[note_id][prompt_type] = ann
            else:
                annotations_dict[note_id][prompt_type] = ann.dict()
    
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

        annotations = session.get('annotations', {})
        for note_id in list(annotations.keys()):
            rt = note_report_types.get(note_id, '')
            # Prompt types now allowed for this note's report type
            allowed = set(update.report_type_mapping.get(rt, []))
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
    # Prompts are nested: { "INT": { "gender-int": {...}, ... }, "MSCI": {...}, ... }
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
        for category in ['INT', 'MSCI']:
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
        # Diagnosis entity
        "histological-tipo-int": "Diagnosis.histologySubgroup",
        "histological": "Diagnosis.histologySubgroup",
        "tumorsite-int": "Diagnosis.subsite",
        "tumorsite": "Diagnosis.subsite",
        "biopsygrading-int": "Diagnosis.grading",
        "biopsygrading": "Diagnosis.grading",
        "ageatdiagnosis-int": "Diagnosis.ageAtDiagnosis",
        "ageatdiagnosis": "Diagnosis.ageAtDiagnosis",
        "tumorbiopsytype-int": "Diagnosis.typeOfBiopsy",
        "tumorbiopsytype": "Diagnosis.typeOfBiopsy",
        "biopsymitoticcount-int": "Diagnosis.biopsyMitoticCount",
        "biopsymitoticcount": "Diagnosis.biopsyMitoticCount",
        "tumordepth-int": "Diagnosis.tumourDepth",
        "tumordiameter-int": "Diagnosis.tumourLongestDiameterClinical",
        "tumordiameter": "Diagnosis.tumourLongestDiameterClinical",
        "necrosis_in_biopsy-int": "Diagnosis.necrosisInBiopsy",
        "necrosis_in_biopsy": "Diagnosis.necrosisInBiopsy",
        "stage_at_diagnosis-int": "Diagnosis.stageAtDiagnosis",
        "stage_at_diagnosis": "Diagnosis.stageAtDiagnosis",

        # Patient entity
        "gender-int": "Patient.sex",
        "gender": "Patient.sex",
        "patient-bmi": "Patient.bmi",
        "patient-weightheight": "Patient.bmi",

        # PatientFollowUp entity
        "patient-status-int": "PatientFollowUp.statusAtLastFollowUp",
        "patient-status": "PatientFollowUp.statusAtLastFollowUp",
        "last_contact_date": "PatientFollowUp.lastContact",

        # Surgery entity
        "surgerymargins-int": "Surgery.marginsAfterSurgery",
        "surgerymargins": "Surgery.marginsAfterSurgery",
        "surgerytype-fs30-int": "Surgery.surgeryType",
        "surgerytype": "Surgery.surgeryType",
        "surgical-specimen-grading-int": "Surgery.surgicalSpecimenGrading",
        "surgical-mitotic-count-int": "Surgery.surgicalSpecimenMitoticCount",
        "necrosis_in_surgical-int": "Surgery.necrosisInSurgicalSpecimen",
        "necrosis_in_surgical": "Surgery.necrosisInSurgicalSpecimen",
        "reexcision-int": "Surgery.reExcision",

        # SystemicTreatment entity
        "chemotherapy_start-int": "SystemicTreatment.startDateSystemicTreatment",
        "chemotherapy_start": "SystemicTreatment.startDateSystemicTreatment",
        "chemotherapy_end-int": "SystemicTreatment.endDateSystemicTreatment",
        "chemotherapy_end": "SystemicTreatment.endDateSystemicTreatment",
        "response-to-int": "SystemicTreatment.treatmentResponse",

        # Radiotherapy entity
        "radiotherapy_start-int": "Radiotherapy.startDate",
        "radiotherapy_start": "Radiotherapy.startDate",
        "radiotherapy_end-int": "Radiotherapy.endDate",
        "radiotherapy_end": "Radiotherapy.endDate",

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


def _build_export_rows(session: Dict) -> List[Dict]:
    """Build export rows from session annotations.

    Shared logic used by both the label export and coded export endpoints.
    Each row includes a '_note_id' field for internal tracking (stripped before CSV output).
    """
    prompt_mapping = _build_prompt_to_core_variable_mapping()
    notes_by_id = {n.get('note_id', ''): n for n in session.get('notes', [])}

    record_id_tracker: Dict[tuple, int] = {}
    current_record_id = 0

    rows = []
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
            else:
                annotation_text = ''
                icdo3_code = ''
                extracted_date = ''

            if not annotation_text or not annotation_text.strip():
                continue

            extracted_value = _extract_value_from_annotation(annotation_text, prompt_type)
            core_variable = prompt_mapping.get(prompt_type, prompt_type)
            entity = _extract_entity_from_core_variable(core_variable)

            if extracted_date:
                date_ref = _normalize_date(extracted_date)
            else:
                date_ref = note_date

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

    return rows


@router.get("/{session_id}/export")
async def export_session_for_pipeline(session_id: str):
    """Export validated annotations in pipeline-compatible CSV format (labels)."""
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    rows = _build_export_rows(session)

    # Strip internal fields before CSV output
    for row in rows:
        row.pop('_note_id', None)
        row.pop('_prompt_type', None)

    columns = [
        'patient_id', 'original_source', 'core_variable', 'date_ref',
        'value', 'record_id', 'linked_to', 'quality', 'types',
        'icdo3_code', 'entity'
    ]

    df = pd.DataFrame(rows, columns=columns)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)

    return StreamingResponse(
        iter([csv_buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={session_id}_validated.csv"}
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

    rows = _build_export_rows(session)

    # Load unified ICD-O-3 codes from session
    unified_icdo3_codes: Dict[str, Dict] = session.get('unified_icdo3_codes', {})

    # Variables that get merged into diagnosisCode
    _DIAGNOSIS_MERGE_VARS = {'Diagnosis.histologySubgroup', 'Diagnosis.subsite'}

    # Collect note_ids that have histology/topography rows for diagnosis merging
    notes_with_diag: Dict[str, Dict] = {}  # note_id -> first matching row (for metadata)
    for row in rows:
        if row['core_variable'] in _DIAGNOSIS_MERGE_VARS:
            nid = row['_note_id']
            if nid not in notes_with_diag:
                notes_with_diag[nid] = row

    # Build coded rows
    coded_rows = []

    # Track which notes already have a diagnosisCode row added
    diag_code_added: set = set()

    for row in rows:
        cv = row['core_variable']

        if cv in _DIAGNOSIS_MERGE_VARS:
            nid = row['_note_id']
            if nid not in diag_code_added:
                diag_code_added.add(nid)
                # Create merged diagnosisCode row
                unified = unified_icdo3_codes.get(nid, {})
                query_code = unified.get('query_code', '') if isinstance(unified, dict) else ''

                if query_code:
                    value = query_code
                    confidence = 1.0
                    method = 'unified_icdo3'
                else:
                    value = 'UNRESOLVED::no_unified_icdo3_code'
                    confidence = 0.0
                    method = 'unresolved'

                coded_rows.append({
                    'patient_id': row['patient_id'],
                    'original_source': row['original_source'],
                    'core_variable': 'Diagnosis.diagnosisCode',
                    'date_ref': row['date_ref'],
                    'value': value,
                    'record_id': row['record_id'],
                    'linked_to': row['linked_to'],
                    'quality': row['quality'],
                    'types': 'CodeableConcept',
                    'icdo3_code': query_code,
                    'entity': 'Diagnosis',
                    'match_confidence': confidence,
                    'match_method': method,
                })
            # Skip individual histology/topography rows in coded output
            continue

        # Non-CodeableConcept rows pass through unchanged
        if row['types'] != 'CodeableConcept':
            coded_rows.append({
                **{k: v for k, v in row.items() if k not in ('_note_id', '_prompt_type')},
                'match_confidence': '',
                'match_method': '',
            })
            continue

        # CodeableConcept rows: check value_code_mappings first, then resolve via CodeResolver
        pt = row.get('_prompt_type', '')
        vcm = value_code_lookup.get(pt, {})
        raw_value = row['value']

        if vcm and raw_value in vcm:
            # Direct mapping from value_code_mappings
            value = vcm[raw_value]
            confidence = 1.0
            method = 'value_code_mapping'
        else:
            code_id, confidence, method = resolver.resolve(raw_value, cv)
            if code_id is not None:
                value = code_id
            else:
                value = f"UNRESOLVED::{raw_value}"

        coded_rows.append({
            **{k: v for k, v in row.items() if k not in ('_note_id', '_prompt_type')},
            'value': value,
            'match_confidence': confidence,
            'match_method': method,
        })

    columns = [
        'patient_id', 'original_source', 'core_variable', 'date_ref',
        'value', 'record_id', 'linked_to', 'quality', 'types',
        'icdo3_code', 'entity', 'match_confidence', 'match_method'
    ]

    df = pd.DataFrame(coded_rows, columns=columns)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)

    return StreamingResponse(
        iter([csv_buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={session_id}_coded.csv"}
    )


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
    if any(x in field_name for x in ['bmi', 'diameter', 'dose', 'fractions']):
        return 'float'

    # Boolean fields
    if any(x in field_name for x in ['rupture', 'hyperthermia', 'completed']):
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

