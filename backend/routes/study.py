"""
Study review routes.

Patient-level human validation of a fixed study variable set, plus cohort
eligibility, layered on top of the existing per-note annotations and the
per-patient diagnosis resolution. Endpoints:

  GET  /api/studies
  GET  /api/sessions/{session_id}/studies/{study_id}/review
  POST /api/sessions/{session_id}/studies/{study_id}/patients/{pid}/variables/{var_key}/confirm
  POST /api/sessions/{session_id}/studies/{study_id}/patients/{pid}/eligibility
  PUT  /api/sessions/{session_id}/studies/{study_id}/conflict-config
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from lib import study_config
from models.schemas import (
    StudyReviewReport,
    StudyPatientReview,
    StudyEvaluationReport,
    StudyVariableConfirmRequest,
    StudyEligibilityRequest,
    StudyEventActionRequest,
    StudyConflictConfigRequest,
    CodeSearchResponse,
    SetDiagnosisPartRequest,
)
from routes.sessions import _load_session, _save_session

router = APIRouter()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _require_study(study_id: str) -> Dict[str, Any]:
    cfg = study_config.get_study(study_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Study '{study_id}' not found")
    return cfg


def _session_report_types(session: Dict[str, Any]) -> List[str]:
    seen = []
    for n in session.get("notes", []):
        rt = (n.get("report_type") or "").strip()
        if rt and rt not in seen:
            seen.append(rt)
    return sorted(seen)


def _ensure_diagnoses(session: Dict[str, Any], conflict_config: Dict[str, Any], study: Dict[str, Any]) -> Dict[str, Any]:
    """Compute (and persist) patient_diagnoses, applying the optional date
    strategy to the diagnosis variable when enabled."""
    from services.diagnosis_resolver import DiagnosisResolver
    from services.study_resolver import StudyResolver

    resolver = DiagnosisResolver()
    patient_diagnoses = resolver.resolve_session(session, preserve_manual=True)

    # If any diagnosis part has a 'date' conflict strategy enabled, settle
    # conflicting diagnosis codes by date (one operation for the whole diagnosis).
    if conflict_config.get("enabled"):
        per_var = conflict_config.get("per_variable") or {}
        for v in study.get("variables", []):
            if v.get("source") != "diagnosis":
                continue
            vc = per_var.get(v["key"], {})
            if vc.get("strategy") == "date":
                notes_by_id = {n.get("note_id", ""): n for n in session.get("notes", [])}
                StudyResolver().apply_diagnosis_date_strategy(
                    patient_diagnoses, notes_by_id, vc.get("date_pref", "earliest")
                )
                break

    session["patient_diagnoses"] = patient_diagnoses
    return patient_diagnoses


def _review_signature(session: Dict[str, Any], conflict_config: Dict[str, Any], study: Dict[str, Any]) -> str:
    """Stable hash of the inputs that determine the review result.

    Auto-resolution is deterministic from the annotations + conflict_config, so
    only the annotations, the note fields the resolver reads, the conflict config,
    and any MANUAL diagnosis resolutions (the one input not derivable from
    annotations) are included. Volatile fields (timestamps) are excluded so the
    signature is stable across recomputes.
    """
    payload = {
        "annotations": session.get("annotations", {}),
        "notes": [
            {k: n.get(k) for k in ("note_id", "p_id", "date", "report_type")}
            for n in session.get("notes", [])
        ],
        "conflict_config": conflict_config,
        "diagnoses": {
            pid: {
                "status": d.get("status"),
                "query_code": (d.get("resolved_code") or {}).get("query_code"),
                "user_diagnosis": d.get("user_diagnosis"),
            }
            for pid, d in (session.get("patient_diagnoses") or {}).items()
            if isinstance(d, dict)
        },
        # invalidate the cache when the study's variable set changes
        "variables": [
            {"key": v.get("key"), "source": v.get("source"), "part": v.get("diagnosis_part"),
             "prompt_type": v.get("prompt_type"), "prompt_types": v.get("prompt_types"),
             "requires": v.get("requires")}
            for v in study_config.active_variables(study)
        ],
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _compute_review(session: Dict[str, Any], study: Dict[str, Any]) -> bool:
    """Recompute the study review for every patient, preserving human decisions,
    and write it back into the session dict. Returns True if it (re)computed
    (caller should persist), or False if the cached result is still valid."""
    from services.study_resolver import StudyResolver

    study_id = study["id"]
    store = session.setdefault("study_reviews", {}).setdefault(study_id, {})
    conflict_config = store.get("conflict_config") or {"enabled": False, "per_variable": {}}

    sig = _review_signature(session, conflict_config, study)
    if store.get("_sig") == sig and store.get("patients"):
        return False  # inputs unchanged — skip the full resolve + disk write

    existing = store.get("patients", {})
    patient_diagnoses = _ensure_diagnoses(session, conflict_config, study)
    variables = study_config.active_variables(study)

    patients = StudyResolver().resolve_session(
        session,
        study,
        variables,
        conflict_config=conflict_config,
        patient_diagnoses=patient_diagnoses,
        existing=existing,
    )
    store["patients"] = patients
    store["conflict_config"] = conflict_config
    store["_sig"] = sig
    return True


def _build_report(session: Dict[str, Any], study: Dict[str, Any]) -> StudyReviewReport:
    study_id = study["id"]
    store = session.get("study_reviews", {}).get(study_id, {})
    patients_dict = store.get("patients", {})
    variables = study_config.active_variables(study)

    patient_models = [StudyPatientReview(**p) for p in patients_dict.values()]
    included = sum(1 for p in patient_models if p.eligibility.decision == "included")
    excluded = sum(1 for p in patient_models if p.eligibility.decision == "excluded")
    needs = sum(1 for p in patient_models if p.eligibility.decision == "needs_review")

    return StudyReviewReport(
        study_id=study_id,
        study_name=study.get("name", study_id),
        condition_family=study.get("condition_family"),
        inclusion_criteria=_inclusion_criteria(study),
        variables=[
            {"key": v["key"], "label": v.get("label", v["key"]),
             "source": v.get("source", "annotation"), "type": v.get("type"),
             "part": v.get("diagnosis_part"), "requires": v.get("requires", []),
             "group": v.get("group", "Other")}
            for v in variables
        ],
        report_types=_session_report_types(session),
        conflict_config=store.get("conflict_config") or {"enabled": False, "per_variable": {}},
        patients=patient_models,
        total_patients=len(patient_models),
        included=included,
        excluded=excluded,
        needs_review=needs,
    )


def _recompute_overall(patient: Dict[str, Any], variables: List[Dict[str, Any]]) -> None:
    from services.study_resolver import StudyResolver
    # Refresh each variable's derived accept/edit/reject label after a mutation.
    for v in patient.get("variables", {}).values():
        StudyResolver.annotate_review_action(v)
    patient["overall_status"] = StudyResolver._overall_status(
        patient.get("eligibility", {}), patient.get("variables", {}), variables
    )
    # The timeline's per-event confirmed flags are derived from variable state, so
    # rebuild it whenever a variable/eligibility mutation lands in-place.
    patient["timeline"] = StudyResolver.build_timeline(patient.get("variables", {}), variables)


def _inclusion_criteria(study: Dict[str, Any]) -> Dict[str, Any]:
    """The cohort inclusion ICD-O codes (with friendly labels) surfaced to the
    reviewer. Prefers an explicit ``reference`` list per part; otherwise falls
    back to the bare cohort-rule codes."""
    cohort = study.get("cohort", {}) or {}
    h = cohort.get("histology", {}) or {}
    t = cohort.get("topography", {}) or {}

    def _refs(part: Dict[str, Any], code_key: str) -> List[Dict[str, str]]:
        ref = part.get("reference")
        if ref:
            return [{"code": str(r.get("code", "")), "label": str(r.get("label", ""))} for r in ref]
        return [{"code": str(c), "label": part.get("label", "")} for c in (part.get(code_key) or [])]

    return {
        "histology_label": h.get("label", ""),
        "histology": _refs(h, "morphology_prefixes"),
        "topography_label": t.get("label", ""),
        "topography": _refs(t, "codes"),
    }


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------

@router.get("/studies")
async def list_studies():
    """List the available study definitions."""
    return {"studies": study_config.list_studies()}


@router.get("/sessions/{session_id}/studies/{study_id}/review", response_model=StudyReviewReport)
async def get_study_review(session_id: str, study_id: str):
    """Compute, persist, and return the study review for all patients."""
    study = _require_study(study_id)
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if _compute_review(session, study):
        _save_session(session_id, session)
    return _build_report(session, study)


@router.get(
    "/sessions/{session_id}/studies/{study_id}/evaluation",
    response_model=StudyEvaluationReport,
)
async def get_study_evaluation(session_id: str, study_id: str):
    """LLM-vs-human evaluation: how often reviewers accept / edit / reject the
    model's proposed values, overall and per variable."""
    from services.study_resolver import StudyResolver

    study = _require_study(study_id)
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if _compute_review(session, study):
        _save_session(session_id, session)

    patients = session.get("study_reviews", {}).get(study_id, {}).get("patients", {})
    summary = StudyResolver.evaluation_summary(patients, study_config.active_variables(study))
    return StudyEvaluationReport(
        study_id=study_id,
        study_name=study.get("name", study_id),
        overall=summary["overall"],
        per_variable=summary["per_variable"],
        reviewed_patients=summary["reviewed_patients"],
        total_patients=len(patients),
    )


@router.post(
    "/sessions/{session_id}/studies/{study_id}/patients/{patient_id}/variables/{var_key}/confirm",
    response_model=StudyPatientReview,
)
async def confirm_variable(
    session_id: str, study_id: str, patient_id: str, var_key: str,
    request: StudyVariableConfirmRequest,
):
    """Confirm / edit / reject a single study variable for a patient."""
    study = _require_study(study_id)
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    store = session.get("study_reviews", {}).get(study_id, {})
    if not store.get("patients"):
        _compute_review(session, study)
        store = session["study_reviews"][study_id]

    patient = store["patients"].get(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not in study review")
    var = patient.get("variables", {}).get(var_key)
    if var is None:
        raise HTTPException(status_code=404, detail=f"Variable {var_key} not found for patient")

    # Capture the LLM's proposed value as the stable evaluation baseline BEFORE the
    # confirm below overwrites proposed_value — this is what accept-vs-edit compares against.
    if var.get("llm_value") is None:
        var["llm_value"] = var.get("proposed_value")

    now = datetime.now().isoformat()
    if request.action == "reject":
        var.update({
            "status": "rejected", "value": None,
            "auto_resolved": False, "resolution_rule": None,
            "reviewed_by": request.reviewer or "user", "reviewed_at": now,
            "note": request.note,
        })
    else:  # confirm / edit
        # A blank value is treated the same as "no explicit value" -> fall back to
        # the proposed value, so we never persist a confirmed-but-empty variable
        # that the UI shows as Validated yet silently drops from the export.
        explicit = request.value
        if explicit is not None and not explicit.strip():
            explicit = None
        value = explicit if explicit is not None else var.get("proposed_value")
        var.update({
            "status": "confirmed",
            "value": value,
            "proposed_value": value if value is not None else var.get("proposed_value"),
            "auto_resolved": False, "resolution_rule": None,
            "reviewed_by": request.reviewer or "user", "reviewed_at": now,
            "note": request.note,
        })

    _recompute_overall(patient, study_config.active_variables(study))
    _save_session(session_id, session)
    return StudyPatientReview(**patient)


@router.post(
    "/sessions/{session_id}/studies/{study_id}/patients/{patient_id}/eligibility",
    response_model=StudyPatientReview,
)
async def set_eligibility(
    session_id: str, study_id: str, patient_id: str, request: StudyEligibilityRequest,
):
    """Confirm cohort eligibility (include/exclude) for a patient."""
    if request.decision not in ("included", "excluded"):
        raise HTTPException(status_code=400, detail="decision must be 'included' or 'excluded'")

    study = _require_study(study_id)
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    store = session.get("study_reviews", {}).get(study_id, {})
    if not store.get("patients"):
        _compute_review(session, study)
        store = session["study_reviews"][study_id]

    patient = store["patients"].get(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not in study review")

    elig = patient.setdefault("eligibility", {})
    elig.update({
        "decision": request.decision,
        "confirmed": True,
        "decided_by": request.reviewer or "user",
        "decided_at": datetime.now().isoformat(),
    })

    _recompute_overall(patient, study_config.active_variables(study))
    _save_session(session_id, session)
    return StudyPatientReview(**patient)


@router.post(
    "/sessions/{session_id}/studies/{study_id}/patients/{patient_id}/events",
    response_model=StudyPatientReview,
)
async def edit_events(
    session_id: str, study_id: str, patient_id: str, request: StudyEventActionRequest,
):
    """Curate a patient's outcome-event list (the interactive timeline): confirm the
    whole list, or confirm / drop / restore / edit one event, or add an event the
    LLM missed. Assembled events survive re-annotation with their human decisions."""
    from services.study_resolver import StudyResolver

    study = _require_study(study_id)
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    store = session.get("study_reviews", {}).get(study_id, {})
    if not store.get("patients"):
        _compute_review(session, study)
        store = session["study_reviews"][study_id]
    patient = store["patients"].get(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not in study review")

    events = patient.setdefault("events", [])
    by_key = {e.get("key"): e for e in events}
    now = datetime.now().isoformat()
    rv = request.reviewer or "user"
    action = request.action

    def _find():
        ev = by_key.get(request.key)
        if ev is None:
            raise HTTPException(status_code=404, detail=f"Event {request.key} not found")
        return ev

    if action == "confirm_all":
        for e in events:
            if e.get("status") == "proposed":
                e.update(status="confirmed", reviewed_by=rv, reviewed_at=now, evidence_changed=False)
    elif action == "confirm":
        _find().update(status="confirmed", reviewed_by=rv, reviewed_at=now, evidence_changed=False)
    elif action == "drop":
        _find().update(status="dropped", reviewed_by=rv, reviewed_at=now)
    elif action == "restore":
        _find().update(status="proposed", reviewed_by=None, reviewed_at=None)
    elif action == "edit":
        e = _find()
        if request.date is not None:
            e["date"] = request.date or None
            e["date_from"] = "event" if request.date else "none"
        if request.disease_status:
            e["disease_status"] = request.disease_status
        if request.sites is not None:
            e["sites"] = request.sites
        e.update(status="confirmed", edited=True, reviewed_by=rv, reviewed_at=now, evidence_changed=False)
    elif action == "add":
        n = sum(1 for x in events if x.get("origin") == "manual") + 1
        events.append({
            "key": f"manual:{patient_id}:{n}", "disease_status": request.disease_status or "recurrence",
            "date": request.date or None, "date_from": "event" if request.date else "none",
            "sites": request.sites or [], "source_note_ids": [], "origin": "manual",
            "status": "confirmed", "edited": False, "evidence_changed": False,
            "reviewed_by": rv, "reviewed_at": now,
        })
    else:
        raise HTTPException(status_code=400, detail=f"Unknown event action '{action}'")

    StudyResolver.finalize_events(events)
    _recompute_overall(patient, study_config.active_variables(study))
    _save_session(session_id, session)
    return StudyPatientReview(**patient)


@router.get("/icdo3/morphology/search", response_model=CodeSearchResponse)
async def search_morphology(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    family: Optional[str] = Query(None, description="Condition-file family filter, e.g. 'sarc' or 'hnc'"),
):
    """Ranked morphology code candidates from the condition file matching a label."""
    from lib import condition_search
    return CodeSearchResponse(results=condition_search.search_morphology(q, limit, family), query=q)


@router.get("/icdo3/topography/search", response_model=CodeSearchResponse)
async def search_topography(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    family: Optional[str] = Query(None, description="Condition-file family filter, e.g. 'sarc' or 'hnc'"),
):
    """Ranked topography code candidates from the condition file matching a label."""
    from lib import condition_search
    return CodeSearchResponse(results=condition_search.search_topography(q, limit, family), query=q)


@router.post(
    "/sessions/{session_id}/studies/{study_id}/patients/{patient_id}/diagnosis-part",
    response_model=StudyPatientReview,
)
async def set_diagnosis_part(
    session_id: str, study_id: str, patient_id: str, request: SetDiagnosisPartRequest,
):
    """Set (or reject) the reviewer-chosen real code for a diagnosis part.

    When both histology and topography codes are chosen, the combination is
    validated against the diagnosis-codes CSV and written to patient_diagnoses so
    the export emits the corrected diagnosis code.
    """
    if request.part not in ("histology", "topography"):
        raise HTTPException(status_code=400, detail="part must be 'histology' or 'topography'")
    if request.action == "select" and not request.code:
        raise HTTPException(status_code=400, detail="code is required to select a diagnosis part")

    study = _require_study(study_id)
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Make sure a diagnosis entry exists for this patient.
    from services.diagnosis_resolver import DiagnosisResolver
    pd = session.get("patient_diagnoses") or {}
    if patient_id not in pd:
        pd = DiagnosisResolver().resolve_session(session, preserve_manual=True)
    session["patient_diagnoses"] = pd
    entry = pd.setdefault(patient_id, {"patient_id": patient_id, "status": "needs_review"})
    ud = entry.setdefault("user_diagnosis", {})
    now = datetime.now().isoformat()

    if request.action == "reject":
        ud[request.part] = {"rejected": True, "reviewer": request.reviewer or "user", "at": now}
    else:
        ud[request.part] = {
            "code": request.code, "label": request.label or "",
            "reviewer": request.reviewer or "user", "at": now,
        }

    # If both parts are chosen (not rejected), assemble + validate the combination.
    morph = ud.get("histology") or {}
    topo = ud.get("topography") or {}
    if morph.get("code") and topo.get("code"):
        from lib.icdo3_csv_indexer import get_csv_indexer
        indexer = get_csv_indexer()
        validation = indexer.validate_combination(morph["code"], topo["code"]) if indexer else {"valid": False}
        valid = bool(validation.get("valid"))
        query_code = validation.get("query_code") if valid else f"{morph['code']}-{topo['code']}"
        row = validation.get("row_data") or {}
        entry["resolved_code"] = {
            "query_code": query_code,
            "morphology_code": morph["code"],
            "topography_code": topo["code"],
            "name": validation.get("name") or " / ".join(x for x in (morph.get("label"), topo.get("label")) if x),
            "source": "user_override",
            "user_selected": True,
            "validation": {"morphology_valid": True, "topography_valid": True, "combination_valid": valid},
            "created_at": now,
        }
        entry["csv_id"] = str(row.get("ID", "")) if row else None
        entry["status"] = "manually_resolved"
        entry["resolved_at"] = now
        entry["resolved_by"] = "user"
    else:
        entry.setdefault("status", "needs_review")

    _compute_review(session, study)
    _save_session(session_id, session)

    patient = session["study_reviews"][study_id]["patients"].get(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not in study review")
    return StudyPatientReview(**patient)


@router.put("/sessions/{session_id}/studies/{study_id}/conflict-config", response_model=StudyReviewReport)
async def set_conflict_config(
    session_id: str, study_id: str, request: StudyConflictConfigRequest,
):
    """Update the session-scoped automatic conflict-resolution config and
    recompute the review (auto-resolutions are re-applied)."""
    study = _require_study(study_id)
    try:
        session = _load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    store = session.setdefault("study_reviews", {}).setdefault(study_id, {})
    store["conflict_config"] = request.config.model_dump()

    if _compute_review(session, study):
        _save_session(session_id, session)
    return _build_report(session, study)
