"""
Session management routes
"""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from contextlib import contextmanager
import fcntl
import json
import io
import os
import re
import tempfile
from datetime import datetime

import pandas as pd
from datetime import timezone

from lib.safe_paths import safe_json_path, validate_id
from models.schemas import (
    SessionCreate, SessionInfo, SessionData, SessionUpdate,
    SessionMetadataUpdate, SessionPromptTypesUpdate, CSVRow,
    PatientDiagnosisResolveRequest, PatientDiagnosisResolveResponse,
    DiagnosisValidationReport, PatientDiagnosisInfo,
    ExportConflict, ConflictSource, ExportValidationResponse,
    ConflictResolveRequest, ConflictResolveResponse,
    ExportMetadataResponse, ExcludedRowSummary, DiagnosisWarning,
)

router = APIRouter()


def _get_sessions_dir() -> Path:
    """Get directory for storing sessions"""
    backend_dir = Path(__file__).parent.parent
    sessions_dir = backend_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def _load_session(session_id: str) -> Dict:
    """Load session from file"""
    sessions_dir = _get_sessions_dir()
    session_file = safe_json_path(sessions_dir, session_id, "session_id")
    
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
    """Save session to file.

    Writes to a temporary file in the same directory and renames it into place,
    so a crash or a concurrent reader never observes a half-written session.
    os.replace is atomic within a filesystem.
    """
    sessions_dir = _get_sessions_dir()
    session_file = safe_json_path(sessions_dir, session_id, "session_id")

    session_data['updated_at'] = datetime.now().isoformat()

    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(sessions_dir), prefix=f".{session_id}.", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False, default=_json_serial)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, session_file)
    except BaseException:
        # Never leave a stray temp file behind on failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


@contextmanager
def session_write_lock(session_id: str):
    """Serialise read-modify-write cycles on one session across processes.

    Sessions are persisted as a single whole-file JSON blob, so two overlapping
    load/mutate/save cycles used to drop whichever write landed first — losing
    unrelated edits, not just conflicting ones. Callers that read a session and
    then save it back must hold this lock across both.

    The lock is a separate .lock file (flock), so it survives the atomic rename
    of the session file itself. Advisory and per-host, which matches the current
    single-node deployment; a multi-node deployment needs shared-storage locking
    or a database.
    """
    sessions_dir = _get_sessions_dir()
    validate_id(session_id, "session_id")
    lock_path = sessions_dir / f".{session_id}.lock"
    with open(lock_path, 'a+') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def mutate_session(session_id: str):
    """Load a session, yield it for mutation, and save it — all under the lock.

    Use for short read-modify-write cycles. For long-running work that holds a
    session across `await`s, use merge_note_annotations instead: the in-memory
    copy goes stale and saving it whole would clobber concurrent edits.
    """
    with session_write_lock(session_id):
        session = _load_session(session_id)
        yield session
        _save_session(session_id, session)


def merge_note_annotations(session_id: str, note_id: str, note_annotations: Dict) -> None:
    """Merge freshly computed annotations for one note into the stored session.

    Batch and sequential runs keep a session object in memory for minutes while
    the LLM works. Writing that whole stale object back would silently discard
    anything an annotator changed meanwhile, so only the new per-note entries are
    applied, onto a freshly read copy, under the write lock.
    """
    with session_write_lock(session_id):
        session = _load_session(session_id)
        session.setdefault('annotations', {}).setdefault(note_id, {}).update(note_annotations)
        _save_session(session_id, session)


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
    
    # upload.py keeps report_type_mappings.json in this directory too. It is not
    # a session, so skip it rather than logging a spurious warning on every list.
    NON_SESSION_FILES = {"report_type_mappings.json"}

    for session_file in sessions_dir.glob("*.json"):
        if session_file.name in NON_SESSION_FILES:
            continue
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
    
    # Sort by updated_at descending. Sessions can have a mix of timezone-aware
    # and naive timestamps (imports vs. local saves), which are not directly
    # comparable — normalize aware values to naive-UTC for a robust sort key.
    def _sort_key(s):
        dt = s.updated_at
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    sessions.sort(key=_sort_key, reverse=True)

    return sessions


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    sessions_dir = _get_sessions_dir()
    session_file = safe_json_path(sessions_dir, session_id, "session_id")
    
    if not session_file.exists():
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    try:
        session_file.unlink()
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

        # INT-HNC specific (Head & Neck Cancer)
        "smoking-status": "Patient.smoking",
        "alcohol-habits": "Patient.alcohol",
        "hpv-status": "Diagnosis.hpvStatus",
        "plasmatic-ebv-dna-status": "Diagnosis.plasmaticEbvDnaAtBaseline",
        "clinical-tnmstaging": "ClinicalStage.ct",
        "pathological-tnmstaging": "PathologicalStage.pt",
        "staging-classification": "ClinicalStage.clinicalStaging",
        "disease-status": "EpisodeEvent.diseaseStatus",
        "beam-quality": "Radiotherapy.beamQuality",
        "radiotherapy_location": "Radiotherapy.treatmentSitePrimaryOnly",
        "neck-surgery-laterality": "Surgery.lateralityOfTheDissection",
        "surgery-reconstruction": "Surgery.typeOfSurgicalApproachOnTumour",
        "site-of-metastatic": "DiseaseExtent.brain",
        "before-treatment-patient-diagnosed": "Patient.comorbidity",
        "last-followup-date": "PatientFollowUp.patientFollowUpDate",
        "systemic-treatment-started": "SystemicTreatment.intent",
        "systemic-treatment-ended": "SystemicTreatment.reasonForEndOfTreatment",
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
        # "Age at diagnosis 62 years." (no colon) -> 62 (integer for the export column)
        r'^Age at diagnosis\s+(\d+)\s+years?\b',
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
        # no trailing \b: capture a number glued to a unit ("70mm" -> 70) instead
        # of skipping to a later boundary-terminated number (e.g. a date's "12").
        int_match = re.search(r'\b(\d+)', v)
        if int_match:
            return int_match.group(1)
        return v

    if data_type == 'float':
        float_match = re.search(r'\b(\d+(?:\.\d+)?)', v)
        if float_match:
            return float_match.group(1)
        return v

    if data_type == 'boolean':
        # Normalize to True/False so boolean-typed fields (e.g. Surgery.tumorRupture)
        # match the True/False that CodeableConcept booleans (ClinicalStage.*,
        # DiseaseExtent.*) resolve to — one consistent serialization in the CSV.
        return 'True' if v.strip().lower() in ('true', 'yes', '1', 'present') else 'False'

    return v


# Absence indicators that must be dropped from the normalized-table export so
# that abstentions never leak in as data. Keep these to UNAMBIGUOUS
# "not stated / not documented / not evaluable" phrasings (English + Italian).
# Do NOT add real clinical negatives that are legitimate values for some
# fields (e.g. "nessun residuo"/"R0" for margins, or "assente" for a necrosis
# field) beyond the pre-existing bare "absent"/"none" patterns below.
_ABSENCE_PATTERNS = [
    # English "not <X>" absence phrasings
    re.compile(
        r'\bnot\s+(specified|available|applicable|mentioned|present|found|'
        r'stated|provided|documented|reported|indicated|evaluable|assessable|'
        r'determinable|determined|identified|known)\b',
        re.IGNORECASE,
    ),
    re.compile(r'^unknown\b', re.IGNORECASE),
    # "<label> unknown." abstention forms (e.g. "Tumor longest diameter unknown.",
    # "Tumor category unknown.") — trailing 'unknown' only, so "carcinoma of
    # unknown primary" (a real unknown-primary finding) is preserved.
    re.compile(r'\bunknown\.?\s*$', re.IGNORECASE),
    re.compile(r'\bno\s+(information|data|result|finding|value)\b', re.IGNORECASE),
    re.compile(r'\binformation\s+not\s+available\b', re.IGNORECASE),
    # Italian "non <X>" absence phrasings (not documented / available / evaluable / known / reported)
    re.compile(
        r'\bnon\s+(specificat[oa]|disponibile|menzionat[oa]|riportat[oa]|'
        r'riferit[oa]|indicat[oa]|valutabile|not[oa]|determinat[oa]|'
        r'documentat[oa]|applicabile|definit[oa])\b',
        re.IGNORECASE,
    ),
    # n/a and the Italian "non disponibile" abbreviation n.d. (n/a, n.a., na, nd, n.d, n/d)
    re.compile(r'^n\s*[./]?\s*[ad]\.?$', re.IGNORECASE),
    # bare Italian "unknown" as the WHOLE value — anchored so a phrase like
    # "sede primitiva sconosciuta" (a real unknown-primary finding) is preserved.
    re.compile(r'^(sconosciut[oa]|ignot[oa])\.?$', re.IGNORECASE),
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


_PROMPT_EM_CACHE: Optional[Dict[str, Dict]] = None


def _prompt_entity_mappings() -> Dict[str, Dict]:
    """Lazy {suffixed_prompt_type: entity_mapping} from prompts.json (cached)."""
    global _PROMPT_EM_CACHE
    if _PROMPT_EM_CACHE is None:
        _PROMPT_EM_CACHE = {}
        try:
            from routes.prompts import load_prompts_json
            for _center, _cps in load_prompts_json().items():
                if isinstance(_cps, dict):
                    for _pt, _pd in _cps.items():
                        if isinstance(_pd, dict) and _pd.get('entity_mapping'):
                            _PROMPT_EM_CACHE[_pt] = _pd['entity_mapping']
        except Exception as e:  # pragma: no cover
            print(f"[WARN] Failed to load entity mappings: {e}")
    return _PROMPT_EM_CACHE


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
                ann_values = ann.get('values', [])
                multi_value_info = ann.get('multi_value_info')
            else:
                annotation_text = ''
                icdo3_code = ''
                extracted_date = ''
                derived_field_values = {}
                ann_values = []
                multi_value_info = None

            if not annotation_text or not annotation_text.strip():
                continue

            core_variable = prompt_mapping.get(prompt_type, prompt_type)

            # Multi-value annotations: emit one row per extracted value
            # This applies when the annotation was split from a history note
            # and has multiple distinct values in the values[] array
            _has_multi_values = (
                multi_value_info
                and isinstance(multi_value_info, dict)
                and multi_value_info.get('was_split', False)
                and len(ann_values) > 1
            )

            if _has_multi_values:
                # Process each value as a separate export row
                for _val_idx, _val in enumerate(ann_values):
                    if not isinstance(_val, dict):
                        continue
                    _val_text = _val.get('value', '').strip()
                    if not _val_text:
                        continue

                    entity = _extract_entity_from_core_variable(core_variable)
                    _val_extracted = _extract_value_from_annotation(_val_text, prompt_type)

                    # Try to extract date from this specific value
                    _val_date = extracted_date
                    # Check for date patterns in the value text itself
                    import re as _re
                    _date_match = _re.search(r'\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{1,2}-\d{1,2}', _val_text)
                    if _date_match:
                        _val_date = _date_match.group(0)

                    if _val_date:
                        date_ref = _normalize_date(_val_date)
                    else:
                        date_ref = note_date

                    absence_reason = _classify_absence(_val_extracted)
                    if absence_reason:
                        excluded_rows.append({
                            'patient_id': patient_id,
                            'core_variable': core_variable,
                            'prompt_type': prompt_type,
                            'note_id': note_id,
                            'original_value': _val_extracted or _val_text,
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
                        'value': _val_extracted,
                        'record_id': record_id,
                        'linked_to': '',
                        'quality': '',
                        'types': data_type,
                        'icdo3_code': icdo3_code,
                        'entity': entity,
                        'event_index': _val_idx,
                    })
            else:
                # --- Per-field emission: one normalized row per IDEA4RC field ---
                # A prompt's entity_mapping may declare several fields (e.g.
                # Radiotherapy intent/hospital/startDate/setting). Each coded
                # field is captured at annotation time in derived_field_values
                # (via output_word_mappings). Emit one row per such field; rows
                # of the same prompt share record_id automatically (same
                # patient/entity/date_ref). Single-field prompts keep their
                # exact prior behavior (one row, derived-or-extracted value).
                em = _prompt_entity_mappings().get(prompt_type) or {}
                fmaps = em.get('field_mappings', [])
                # Per-field emission targets fields that can produce a value:
                # coded fields (value_code_mappings) and/or owm-driven fields
                # (output_word_mappings, incl. capture-group numeric/date
                # extraction). Values come from derived_field_values (computed
                # at annotation time). Fields flagged multi_value emit one row
                # per distinct matched value (e.g. previous cancer treatments).
                _emit_fields = [
                    fm for fm in fmaps
                    if fm.get('field_name') and fm.get('entity_type')
                    and (fm.get('value_code_mappings') or fm.get('output_word_mappings'))
                ]

                pairs = []  # list of (core_variable, value)
                _seen = set()
                _mv_cvars = set()   # core_variables that are intentionally multi-valued
                for fm in _emit_fields:
                    fn = fm['field_name']
                    if fn in _seen:
                        continue
                    cv = f"{fm['entity_type']}.{fn}"
                    if fm.get('multi_value') and fm.get('output_word_mappings'):
                        _vals = []
                        for _owm in fm['output_word_mappings']:
                            _pat = _owm.get('pattern', '')
                            try:
                                if _pat and re.search(_pat, annotation_text, re.IGNORECASE):
                                    _v = _owm.get('value', '')
                                    if _v and _v not in _vals:
                                        _vals.append(_v)
                            except re.error:
                                continue
                        for _v in _vals:
                            pairs.append((cv, _v))
                        if _vals:
                            _mv_cvars.add(cv)
                        _seen.add(fn)
                    elif fn in derived_field_values:
                        pairs.append((cv, derived_field_values[fn]))
                        _seen.add(fn)
                if not pairs:
                    # single-field prompt, or no coded field derived: legacy
                    # single value for the prompt's primary variable.
                    _fn = core_variable.split('.')[-1] if '.' in core_variable else ''
                    if _fn and _fn in derived_field_values:
                        _val = derived_field_values[_fn]
                    else:
                        _val = _extract_value_from_annotation(annotation_text, prompt_type)
                    pairs = [(core_variable, _val)]

                if extracted_date:
                    date_ref = _normalize_date(extracted_date)
                else:
                    date_ref = note_date

                for cv, extracted_value in pairs:
                    entity = _extract_entity_from_core_variable(cv)

                    absence_reason = _classify_absence(extracted_value)
                    if absence_reason:
                        excluded_rows.append({
                            'patient_id': patient_id,
                            'core_variable': cv,
                            'prompt_type': prompt_type,
                            'note_id': note_id,
                            'original_value': extracted_value or annotation_text,
                            'reason': absence_reason,
                        })
                        continue

                    data_type = _get_data_type_for_variable(cv)

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
                        'core_variable': cv,
                        'date_ref': date_ref,
                        'value': extracted_value,
                        'record_id': record_id,
                        'linked_to': '',
                        'quality': '',
                        'types': data_type,
                        'icdo3_code': icdo3_code,
                        'entity': entity,
                        '_multi_value': cv in _mv_cvars,
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

    # Group source rows by the appropriate key based on cardinality.
    # Non-repeatable (1): group by (patient_id, core_variable) — date irrelevant
    # Repeatable (0):     group by (patient_id, core_variable, date_ref)
    non_rep_sources: Dict[tuple, List[ConflictSource]] = defaultdict(list)
    rep_sources: Dict[tuple, List[ConflictSource]] = defaultdict(list)

    for row in deduped:
        if row.get('_multi_value'):
            continue  # intentionally multi-valued variable (e.g. previous cancer
                      # treatments) — multiple values are expected, not a conflict
        entity = row['entity']
        card = cardinality.get(entity)  # None if entity unknown → treat as repeatable
        src = ConflictSource(
            value=row['value'],
            note_id=row.get('_note_id', ''),
            prompt_type=row.get('_prompt_type', ''),
        )
        if card == 1:
            non_rep_sources[(row['patient_id'], row['core_variable'])].append(src)
        else:
            rep_sources[(row['patient_id'], row['core_variable'], row['date_ref'])].append(src)

    def _dedup_sources(srcs: List[ConflictSource]) -> List[ConflictSource]:
        seen_triples = set()
        out: List[ConflictSource] = []
        for s in srcs:
            key = (s.value, s.note_id, s.prompt_type)
            if key in seen_triples:
                continue
            seen_triples.add(key)
            out.append(s)
        out.sort(key=lambda s: (s.note_id, s.prompt_type, s.value))
        return out

    # Non-repeatable conflicts
    for (pid, cv), srcs in non_rep_sources.items():
        unique_values = {s.value for s in srcs}
        if len(unique_values) > 1:
            conflicts.append(ExportConflict(
                patient_id=pid,
                core_variable=cv,
                date_ref=None,
                conflicting_values=sorted(unique_values),
                conflict_type="non_repeatable",
                sources=_dedup_sources(srcs),
            ))

    # Repeatable same-date conflicts
    for (pid, cv, date_ref), srcs in rep_sources.items():
        unique_values = {s.value for s in srcs}
        if len(unique_values) > 1:
            conflicts.append(ExportConflict(
                patient_id=pid,
                core_variable=cv,
                date_ref=date_ref,
                conflicting_values=sorted(unique_values),
                conflict_type="repeatable_same_date",
                sources=_dedup_sources(srcs),
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


def _apply_study_scope(
    session: Dict, rows: List[Dict], study_id: str
) -> Tuple[List[Dict], set]:
    """Restrict export rows to a study cohort and overlay human-confirmed values.

    For ``?study_id=`` exports:
      * keep only patients whose study eligibility decision == 'included'
      * keep only rows whose prompt belongs to the study's variable set
        (diagnosis prompts are kept so they can be merged downstream)
      * overlay each annotation variable's human-confirmed value (collapsing
        per-note conflicts to a single agreed value), and synthesize a row for
        confirmed variables that had no surviving annotation row

    Returns (scoped_rows, included_patient_ids).
    """
    from lib import study_config
    from services.study_resolver import _pt_matches

    study = study_config.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Study '{study_id}' not found")

    store = session.get('study_reviews', {}).get(study_id, {})
    patients = store.get('patients', {})
    # Distinguish "not reviewed yet" (no patients computed) from "reviewed, zero
    # included" — the former is a usage error, not a legitimately empty cohort.
    if not patients:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Study '{study_id}' has not been reviewed for this session yet. "
                f"Compute the review (GET .../studies/{study_id}/review) before exporting."
            ),
        )

    # Only patients a human has CONFIRMED as included form the cohort — an
    # auto-proposed 'included' is a suggestion, not a sign-off.
    def _included(p):
        e = p.get('eligibility') or {}
        return e.get('decision') == 'included' and e.get('confirmed')
    included = {pid for pid, p in patients.items() if _included(p)}

    variables = study_config.active_variables(study)
    # Only single-value 'annotation' variables overlay into the normalized export;
    # 'presence'/'event_any' (derived booleans) are review-only for now.
    ann_vars = [v for v in variables if v.get('source') == 'annotation']
    diag_vars = [v for v in variables if v.get('source') == 'diagnosis']

    def _bases(v):
        return v.get('prompt_types') or ([v['prompt_type']] if v.get('prompt_type') else [])

    diag_bases = [b for v in diag_vars for b in _bases(v)]
    ann_base_to_key = {b: v['key'] for v in ann_vars for b in _bases(v)}
    study_bases = list(ann_base_to_key) + diag_bases

    def _in_study(pt: str) -> bool:
        return any(_pt_matches(pt, b) for b in study_bases)

    def _ann_key_for(pt: str):
        for b, k in ann_base_to_key.items():
            if _pt_matches(pt, b):
                return k
        return None

    prompt_mapping = _build_prompt_to_core_variable_mapping()
    cardinality = _load_entity_cardinality()

    # Patients whose diagnosis variable the reviewer rejected — their diagnosis
    # code must not be exported (the annotation path already honors 'rejected').
    diag_keys = {v['key'] for v in diag_vars}
    diag_rejected = {
        pid for pid, p in patients.items() if pid in included
        and any(((p.get('variables') or {}).get(k) or {}).get('status') == 'rejected'
                for k in diag_keys)
    }

    # confirmed annotation values, keyed by (pid, variable key)
    confirmed: Dict[tuple, tuple] = {}
    for pid, p in patients.items():
        if pid not in included:
            continue
        for v in ann_vars:
            vr = (p.get('variables') or {}).get(v['key'], {})
            if vr.get('status') == 'rejected':
                continue
            val = vr.get('value') if vr.get('value') is not None else vr.get('proposed_value')
            if val is None or not str(val).strip():
                continue
            # Never overlay an abstention into the normalized table, even one a
            # human typed in the review — mirror the _build_export_rows guarantee.
            if _classify_absence(str(val)):
                continue
            confirmed[(pid, v['key'])] = (str(val), vr.get('source_prompt_type') or _bases(v)[0], _bases(v)[0])

    scoped: List[Dict] = []
    emitted_ann: set = set()   # (pid, variable key) collapsed rows already emitted
    for r in rows:
        pid = r.get('patient_id', '')
        pt = r.get('_prompt_type', '')
        if pid not in included or not _in_study(pt):
            continue
        vkey = _ann_key_for(pt)
        if vkey is None:
            # diagnosis prompt row — kept so _merge_diagnosis_rows can collapse it,
            # unless the reviewer rejected the diagnosis variable for this patient.
            if pid not in diag_rejected:
                scoped.append(r)
            continue
        # Repeatable variable (cardinality 0, e.g. history-split events): preserve
        # every dated record rather than collapsing to one value.
        if cardinality.get(r.get('entity', '')) != 1:
            scoped.append(r)
            continue
        # Non-repeatable: emit ONE representative row per patient with the confirmed
        # value; drop the rest (collapses per-note disagreement / multi-prompt).
        key = (pid, vkey)
        if key in emitted_ann or key not in confirmed:
            continue
        emitted_ann.add(key)
        scoped.append({**r, 'value': confirmed[key][0]})

    # synthesize rows for confirmed (non-repeatable) variables with no surviving row
    for (pid, vkey), (val, session_pt, base) in confirmed.items():
        if (pid, vkey) in emitted_ann:
            continue
        core_variable = prompt_mapping.get(session_pt) or prompt_mapping.get(base) or base
        entity = _extract_entity_from_core_variable(core_variable)
        if cardinality.get(entity) != 1:
            continue   # repeatable — don't synthesize a collapsed row
        scoped.append({
            '_note_id': '', '_prompt_type': session_pt, 'patient_id': pid,
            'original_source': 'NLP_LLM', 'core_variable': core_variable,
            'date_ref': '', 'value': val, 'record_id': 0, 'linked_to': '',
            'quality': '', 'types': _get_data_type_for_variable(core_variable),
            'icdo3_code': '', 'entity': entity,
        })

    # --- full outcome-event sequence (EpisodeEvent + linked DiseaseExtent) ---
    # The event_any outcome variables (recurrence/metastasis) are NOT collapsed:
    # emit one EpisodeEvent (+ linked DiseaseExtent sites) per curated, non-dropped
    # event, so the survival analysis gets the whole longitudinal sequence.
    status_var = next((v for v in variables if (v.get('timeline') or {}).get('category') == 'status'), None)
    met_var = next((v for v in variables if (v.get('timeline') or {}).get('category') == 'metastasis'), None)

    def _session_pt_for(base):
        if not base:
            return ''
        for anns in session.get('annotations', {}).values():
            for pt in (anns or {}):
                if _pt_matches(pt, base):
                    return pt
        return base

    recur_pt = _session_pt_for((status_var or {}).get('prompt_type'))
    met_pt = _session_pt_for((met_var or {}).get('prompt_type'))

    def _ev_row(pid, pt, cv, value, date_ref, record_id, linked_to):
        return {
            '_note_id': '', '_prompt_type': pt, 'patient_id': pid,
            'original_source': 'NLP_LLM', 'core_variable': cv,
            'date_ref': date_ref or '', 'value': value, 'record_id': record_id,
            'linked_to': linked_to, 'quality': '', 'types': _get_data_type_for_variable(cv),
            'icdo3_code': '', 'entity': _extract_entity_from_core_variable(cv),
        }

    for pid, p in patients.items():
        if pid not in included:
            continue
        for i, ev in enumerate(p.get('events') or []):
            if ev.get('status') == 'dropped':
                continue
            date = ev.get('date') or ''
            rid = f"{pid}-EE-{i + 1}"
            scoped.append(_ev_row(pid, recur_pt, 'EpisodeEvent.diseaseStatus',
                                  ev.get('disease_status', 'recurrence'), date, rid, ''))
            if date:
                scoped.append(_ev_row(pid, recur_pt, 'EpisodeEvent.dateOfEpisode', date, date, rid, ''))
            for site in ev.get('sites') or []:
                scoped.append(_ev_row(pid, met_pt, f'DiseaseExtent.{site}', 'true', date,
                                      f"{rid}-DE", rid))

    return scoped, included


@router.get("/{session_id}/export/metadata", response_model=ExportMetadataResponse)
async def get_export_metadata(session_id: str):
    """Return excluded rows and diagnosis warnings for the next export.

    These were previously sent as the `X-Excluded-Rows` and
    `X-Diagnosis-Warnings` response headers on `/export` and
    `/export/codes`. For sessions with many conflicts they grew past
    reverse-proxy header buffer limits ("upstream sent too big header"),
    so they now live in this dedicated JSON endpoint.

    Both label and code exports use the same exclusion logic, so a single
    endpoint serves both. Call it in parallel with the CSV download.
    """
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    _, excluded = _build_export_rows(session)
    patient_diagnoses = session.get('patient_diagnoses', {}) or {}

    excluded_rows = [
        ExcludedRowSummary(
            patient_id=e.get("patient_id", "") or "",
            variable=e.get("core_variable", "") or "",
            value=e.get("original_value", "") or "",
            reason=e.get("reason", "") or "",
        )
        for e in excluded
    ]

    diagnosis_warnings = [
        DiagnosisWarning(
            patient_id=pid,
            reasons=list(diag.get("review_reasons", []) or []),
        )
        for pid, diag in patient_diagnoses.items()
        if isinstance(diag, dict) and diag.get('status') == 'needs_review'
    ]

    return ExportMetadataResponse(
        excluded_rows=excluded_rows,
        diagnosis_warnings=diagnosis_warnings,
    )


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


@router.post("/{session_id}/conflicts/resolve", response_model=ConflictResolveResponse)
async def resolve_conflicts(session_id: str, request: ConflictResolveRequest):
    """Bulk-delete annotation entries that are blocking export.

    Each entry is a (note_id, prompt_type) pair; the corresponding annotation
    is removed from the session. Entries that don't exist (e.g. already deleted
    in a previous call) are silently skipped and counted as not_found.

    Returns the remaining conflicts after deletion so the frontend can refresh
    the modal in one round-trip.
    """
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    annotations = session.get('annotations', {})
    deleted = 0
    not_found = 0
    for entry in request.entries:
        note_annotations = annotations.get(entry.note_id)
        if not isinstance(note_annotations, dict) or entry.prompt_type not in note_annotations:
            not_found += 1
            continue
        del note_annotations[entry.prompt_type]
        deleted += 1

    if deleted:
        session['annotations'] = annotations
        session['updated_at'] = datetime.now().isoformat()
        _save_session(session_id, session)

    # Re-validate so the client can refresh the modal without a second call.
    rows, _excluded = _build_export_rows(session)
    patient_diagnoses = session.get('patient_diagnoses', {})
    rows = _merge_diagnosis_rows(rows, patient_diagnoses, value_field='query_code')
    clean_rows, remaining_conflicts, _ = _validate_and_deduplicate_rows(rows)

    return ConflictResolveResponse(
        deleted_count=deleted,
        not_found_count=not_found,
        remaining_conflicts=remaining_conflicts,
        valid=len(remaining_conflicts) == 0,
        row_count=len(clean_rows),
    )


@router.get("/{session_id}/export")
async def export_session_for_pipeline(
    session_id: str,
    force: bool = Query(
        False,
        description=(
            "If true, bypass the cardinality conflict gate. Conflicting rows "
            "still pass through deduplication and end up in the CSV; "
            "downstream consumers are responsible for resolving them."
        ),
    ),
    study_id: Optional[str] = Query(
        None,
        description=(
            "If set, restrict the export to the named study's confirmed cohort "
            "(included patients only), using human-confirmed variable values and "
            "the study's variable set. Omit for the full, unchanged export."
        ),
    ),
):
    """Export validated annotations in pipeline-compatible CSV format (labels).

    Format matches SARC_V2(in).csv: semicolon-delimited, 8 columns.
    Rows with absence values (Not applicable, Unknown, etc.) are excluded.
    Blocks with HTTP 409 if cardinality conflicts are detected,
    unless ?force=true is set.
    """
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    rows, excluded = _build_export_rows(session)

    # Optional study scope: restrict to confirmed cohort + overlay confirmed values
    patient_diagnoses = session.get('patient_diagnoses', {})
    if study_id:
        rows, included_pids = _apply_study_scope(session, rows, study_id)
        patient_diagnoses = {pid: d for pid, d in patient_diagnoses.items() if pid in included_pids}

    # Patient-level diagnosis merging: replace individual histology/topography rows
    # with a merged Diagnosis.diagnosisCode row using query_code format
    rows = _merge_diagnosis_rows(rows, patient_diagnoses, value_field='query_code')

    # Validate cardinality constraints and deduplicate
    rows, conflicts, _ = _validate_and_deduplicate_rows(rows)
    if conflicts and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Export blocked: cardinality conflicts detected. Resolve them before exporting.",
                "conflicts": [c.model_dump() for c in conflicts],
            },
        )
    if conflicts and force:
        print(
            f"[INFO] Forced export of {session_id} (validated): "
            f"bypassing {len(conflicts)} cardinality conflict(s)"
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

    # Excluded rows and diagnosis warnings are exposed via the dedicated
    # `/export/metadata` endpoint so they don't bloat response headers
    # past reverse-proxy buffer limits on large sessions.
    _suffix = f"_{study_id}" if study_id else "_validated"
    return StreamingResponse(
        iter([csv_buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={session_id}{_suffix}.csv",
        },
    )


@router.get("/{session_id}/export/codes")
async def export_session_coded(
    session_id: str,
    force: bool = Query(
        False,
        description=(
            "If true, bypass the cardinality conflict gate. Conflicting rows "
            "still pass through deduplication and end up in the CSV; "
            "downstream consumers are responsible for resolving them."
        ),
    ),
    study_id: Optional[str] = Query(
        None,
        description=(
            "If set, restrict the export to the named study's confirmed cohort "
            "(included patients only), using human-confirmed variable values and "
            "the study's variable set. Omit for the full, unchanged export."
        ),
    ),
):
    """Export annotations with CodeableConcept values resolved to IDEA4RC codes.

    Histology + topography rows are merged into a single Diagnosis.diagnosisCode
    row using the unified ICD-O-3 code saved during annotation.
    Non-CodeableConcept values pass through unchanged.
    Unresolved values are prefixed with 'UNRESOLVED::'.
    Blocks with HTTP 409 if cardinality conflicts are detected,
    unless ?force=true is set.
    """
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    from lib.code_resolver import CodeResolver
    resolver = CodeResolver()

    # Build value_code_mappings lookups from prompts.json.
    #   value_code_lookup:  prompt_type -> first field's vcm  (legacy fallback)
    #   value_code_by_cv:   (prompt_type, core_variable) -> that field's vcm
    # Per-field emission means each row must resolve against ITS OWN field's vcm,
    # not just the prompt's first one.
    value_code_lookup: Dict[str, Dict[str, str]] = {}
    value_code_by_cv: Dict[tuple, Dict[str, str]] = {}
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
                                cv = f"{fm.get('entity_type')}.{fm.get('field_name')}"
                                value_code_by_cv[(pt, cv)] = vcm
                                value_code_lookup.setdefault(pt, vcm)  # first = legacy
    except Exception as e:
        print(f"[WARN] Failed to load value_code_mappings from prompts.json: {e}")

    rows, excluded = _build_export_rows(session)

    # Optional study scope: restrict to confirmed cohort + overlay confirmed values
    patient_diagnoses = session.get('patient_diagnoses', {})
    if study_id:
        rows, included_pids = _apply_study_scope(session, rows, study_id)
        patient_diagnoses = {pid: d for pid, d in patient_diagnoses.items() if pid in included_pids}

    # Patient-level diagnosis merging: replace individual histology/topography rows
    # with a merged Diagnosis.diagnosisCode row using csv_id (numeric ID)
    rows = _merge_diagnosis_rows(rows, patient_diagnoses, value_field='csv_id')

    # Validate cardinality constraints and deduplicate
    rows, conflicts, _ = _validate_and_deduplicate_rows(rows)
    if conflicts and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Export blocked: cardinality conflicts detected. Resolve them before exporting.",
                "conflicts": [c.model_dump() for c in conflicts],
            },
        )
    if conflicts and force:
        print(
            f"[INFO] Forced export of {session_id} (coded): "
            f"bypassing {len(conflicts)} cardinality conflict(s)"
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
        # Resolve against THIS field's vcm (per-field emission); fall back to the
        # prompt's first-field vcm for legacy single-field rows.
        vcm = value_code_by_cv.get((pt, cv)) or value_code_lookup.get(pt, {})
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

    # Excluded rows and diagnosis warnings are exposed via the dedicated
    # `/export/metadata` endpoint so they don't bloat response headers
    # past reverse-proxy buffer limits on large sessions.
    _suffix = f"_{study_id}_coded" if study_id else "_coded"
    return StreamingResponse(
        iter([csv_buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={session_id}{_suffix}.csv",
        },
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

    raw_name = session.get("name", session_id)
    ascii_name = re.sub(r"[^\w\-]", "_", raw_name, flags=re.ASCII)
    ascii_name = re.sub(r"_+", "_", ascii_name).strip("_") or session_id
    ascii_filename = f"{ascii_name}_{session_id}.json"

    from urllib.parse import quote as _url_quote
    utf8_filename = f"{raw_name}_{session_id}.json"
    encoded_utf8 = _url_quote(utf8_filename, safe="")

    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_filename}"; '
                f"filename*=UTF-8''{encoded_utf8}"
            )
        },
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

