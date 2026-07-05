"""
Tests for study-scoped export (routes/sessions.py _apply_study_scope).

Verifies that ?study_id= export restricts to the confirmed cohort, overlays
human-confirmed values, merges the diagnosis code, and that the full export
(study_id=None) is unaffected.

Run from the backend directory:
    cd backend && python3 test_study_export.py
"""

from fastapi import HTTPException

from routes.sessions import (
    _build_export_rows,
    _apply_study_scope,
    _merge_diagnosis_rows,
    _validate_and_deduplicate_rows,
)

STUDY_ID = "liposarcoma_retroperitoneum"


def _ann(text):
    return {"annotation_text": text}


def _session():
    notes = [
        {"note_id": "p1n1", "p_id": "P1", "report_type": "pathology", "date": "10/01/2020"},
        {"note_id": "p1n2", "p_id": "P1", "report_type": "clinical", "date": "11/01/2020"},
        {"note_id": "p2n1", "p_id": "P2", "report_type": "pathology", "date": "02/02/2020"},
    ]
    annotations = {
        "p1n1": {
            "gender-int-sarc": _ann("Patient's gender male."),
            "ageatdiagnosis-int-sarc": _ann("Age at diagnosis: 65."),
            "stage_at_diagnosis-int-sarc": _ann("Stage at diagnosis: localized."),
            "histological-tipo-int-sarc": _ann("Histological type: Liposarcoma (8850/3)."),
            "tumorsite-int-sarc": _ann("Tumor site (Retroperitoneum): Retroperitoneum (C48.0)."),
            "biopsygrading-int-sarc": _ann("Biopsy grading (FNCLCC): 2."),  # non-study var
        },
        # second P1 note disagrees on sex -> would be a conflict in the full export
        "p1n2": {"gender-int-sarc": _ann("Patient's gender female.")},
        "p2n1": {"gender-int-sarc": _ann("Patient's gender female.")},
    }
    patient_diagnoses = {
        "P1": {
            "patient_id": "P1", "status": "auto_resolved",
            "resolved_code": {"query_code": "8850/3-C48.0", "morphology_code": "8850/3",
                              "topography_code": "C48.0", "name": "Liposarcoma"},
            "csv_id": "12345",
            "histology_codes": [{"code": "8850/3", "note_id": "p1n1"}],
            "topography_codes": [{"code": "C48.0", "note_id": "p1n1"}],
        },
        "P2": {"patient_id": "P2", "status": "skipped"},
    }
    study_reviews = {
        STUDY_ID: {
            "conflict_config": {"enabled": False, "per_variable": {}},
            "patients": {
                "P1": {
                    "patient_id": "P1",
                    "eligibility": {"decision": "included", "confirmed": True},
                    "variables": {
                        "histology": {"key": "histology", "source": "diagnosis", "status": "confirmed"},
                        "topography": {"key": "topography", "source": "diagnosis", "status": "confirmed"},
                        "diagnosis_code": {"key": "diagnosis_code", "source": "diagnosis", "status": "confirmed"},
                        # human OVERRODE sex to 'female'
                        "sex": {"key": "sex", "source": "annotation", "status": "confirmed",
                                "value": "female", "source_prompt_type": "gender-int-sarc"},
                        "age": {"key": "age", "source": "annotation", "status": "confirmed",
                                "value": "65", "source_prompt_type": "ageatdiagnosis-int-sarc"},
                        "stage": {"key": "stage", "source": "annotation", "status": "auto",
                                  "proposed_value": "localized",
                                  "source_prompt_type": "stage_at_diagnosis-int-sarc"},
                    },
                    "overall_status": "completed",
                },
                "P2": {
                    "patient_id": "P2",
                    "eligibility": {"decision": "excluded", "confirmed": True},
                    "variables": {},
                    "overall_status": "excluded",
                },
            },
        }
    }
    return {
        "notes": notes, "annotations": annotations,
        "patient_diagnoses": patient_diagnoses, "study_reviews": study_reviews,
    }


def _final_rows(session, study_id):
    rows, _ = _build_export_rows(session)
    pd = session.get("patient_diagnoses", {})
    if study_id:
        rows, included = _apply_study_scope(session, rows, study_id)
        pd = {p: d for p, d in pd.items() if p in included}
    rows = _merge_diagnosis_rows(rows, pd, value_field="query_code")
    rows, conflicts, _ = _validate_and_deduplicate_rows(rows)
    return rows, conflicts


def test_full_export_unchanged_includes_all_patients():
    rows, _ = _final_rows(_session(), study_id=None)
    pids = {r["patient_id"] for r in rows}
    assert pids == {"P1", "P2"}, pids
    # non-study variable still present in the full export
    assert any(r["core_variable"] == "Diagnosis.biopsyGrading" for r in rows)


def test_study_export_filters_to_included_cohort():
    rows, conflicts = _final_rows(_session(), study_id=STUDY_ID)
    pids = {r["patient_id"] for r in rows}
    assert pids == {"P1"}, pids  # P2 excluded
    # only study variables survive (no biopsy grading)
    assert not any(r["core_variable"] == "Diagnosis.biopsyGrading" for r in rows)


def test_study_export_overlays_confirmed_value_and_no_conflict():
    rows, conflicts = _final_rows(_session(), study_id=STUDY_ID)
    sex_rows = [r for r in rows if r["core_variable"] == "Patient.sex"]
    assert len(sex_rows) == 1, sex_rows           # collapsed despite 2 disagreeing notes
    assert sex_rows[0]["value"] == "female"       # human override applied
    assert conflicts == [], conflicts             # overlay removed the cardinality conflict


def test_study_export_merges_diagnosis_code():
    rows, _ = _final_rows(_session(), study_id=STUDY_ID)
    diag = [r for r in rows if r["core_variable"] == "Diagnosis.diagnosisCode"]
    assert len(diag) == 1 and diag[0]["value"] == "8850/3-C48.0", diag
    # raw histology/subsite rows were merged away
    assert not any(r["core_variable"] in ("Diagnosis.histologySubgroup", "Diagnosis.subsite")
                   for r in rows)


def test_export_blocks_when_not_reviewed():
    s = _session()
    s.pop("study_reviews", None)   # study configured but never reviewed
    rows, _ = _build_export_rows(s)
    try:
        _apply_study_scope(s, rows, STUDY_ID)
        assert False, "expected HTTPException for un-reviewed study export"
    except HTTPException as e:
        assert e.status_code == 409, e.status_code


def test_unconfirmed_eligibility_is_excluded():
    s = _session()
    # P1 auto-included but NOT confirmed -> must not export
    s["study_reviews"][STUDY_ID]["patients"]["P1"]["eligibility"] = {
        "decision": "included", "confirmed": False,
    }
    rows, conflicts = _final_rows(s, study_id=STUDY_ID)
    assert {r["patient_id"] for r in rows} == set(), rows  # nobody confirmed-included


def test_diagnosis_rejection_drops_diagnosis_code():
    s = _session()
    # rejecting ANY diagnosis part (here the combination) drops the code
    s["study_reviews"][STUDY_ID]["patients"]["P1"]["variables"]["diagnosis_code"]["status"] = "rejected"
    rows, _ = _final_rows(s, study_id=STUDY_ID)
    assert not any(r["core_variable"] == "Diagnosis.diagnosisCode" for r in rows), rows
    # other study variables for P1 still present
    assert any(r["core_variable"] == "Patient.sex" for r in rows)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  PASS {t.__name__}")
    print(f"\n{len(tests)}/{len(tests)} study-export tests passed")


if __name__ == "__main__":
    _run_all()
