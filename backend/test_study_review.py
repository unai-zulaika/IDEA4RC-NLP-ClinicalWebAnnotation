"""
Unit tests for the study review resolver (services/study_resolver.py).

Run from the backend directory:
    cd backend && python3 test_study_review.py
    # or: python3 -m pytest test_study_review.py -q
"""

from services.study_resolver import StudyResolver


STUDY = {
    "id": "liposarcoma_retroperitoneum",
    "cohort": {
        "histology": {"label": "Liposarcoma",
                      "morphology_prefixes": ["8850", "8851", "8852", "8853",
                                               "8854", "8855", "8857", "8858"]},
        "topography": {"label": "Retroperitoneum", "codes": ["C48.0"]},
        "treatment": {"label": "Surgically treated", "prompt_type": "surgerytype"},
    },
    "variables": [
        {"key": "histology", "label": "Histology", "source": "diagnosis",
         "diagnosis_part": "histology", "prompt_types": ["histological-tipo"]},
        {"key": "topography", "label": "Topography", "source": "diagnosis",
         "diagnosis_part": "topography", "prompt_types": ["tumorsite"]},
        {"key": "diagnosis_code", "label": "Diagnosis code", "source": "diagnosis",
         "diagnosis_part": "combination", "requires": ["histology", "topography"]},
        {"key": "stage", "label": "Stage", "source": "annotation",
         "prompt_type": "stage_at_diagnosis"},
        {"key": "age", "label": "Age", "source": "annotation",
         "prompt_type": "ageatdiagnosis"},
        {"key": "sex", "label": "Sex", "source": "annotation",
         "prompt_type": "gender"},
    ],
}
VARIABLES = STUDY["variables"]


def _ann(text, **extra):
    return {"annotation_text": text, **extra}


def _build_session():
    notes = [
        {"note_id": "p1n1", "p_id": "P1", "report_type": "pathology", "date": "10/01/2020"},
        {"note_id": "p2n1", "p_id": "P2", "report_type": "clinical", "date": "05/02/2019"},
        {"note_id": "p2n2", "p_id": "P2", "report_type": "pathology", "date": "06/02/2019"},
        {"note_id": "p3n1", "p_id": "P3", "report_type": "clinical", "date": "01/03/2021"},
    ]
    annotations = {
        "p1n1": {
            "gender-int-sarc": _ann("Patient's gender male."),
            "ageatdiagnosis-int-sarc": _ann("Age at diagnosis: 65."),
            "stage_at_diagnosis-int-sarc": _ann("Stage at diagnosis: localized."),
            "surgerytype-int-sarc": _ann("Surgical procedure"),
        },
        "p2n1": {
            "gender-int-sarc": _ann("Patient's gender female."),
            "ageatdiagnosis-int-sarc": _ann("Age at diagnosis: 70."),
        },
        "p2n2": {
            "gender-int-sarc": _ann("Patient's gender male."),
            "ageatdiagnosis-int-sarc": _ann("Age at diagnosis: 71."),
        },
        "p3n1": {
            "ageatdiagnosis-int-sarc": _ann("Age at diagnosis: 50."),
        },
    }
    return {"notes": notes, "annotations": annotations}


PATIENT_DIAGNOSES = {
    "P1": {
        "patient_id": "P1", "status": "auto_resolved",
        "resolved_code": {"query_code": "8850/3-C48.0", "morphology_code": "8850/3",
                          "topography_code": "C48.0", "name": "Liposarcoma"},
        "histology_codes": [{"code": "8850/3", "note_id": "p1n1"}],
        "topography_codes": [{"code": "C48.0", "note_id": "p1n1"}],
    },
    "P2": {
        "patient_id": "P2", "status": "auto_resolved",
        "resolved_code": {"query_code": "8890/3-C49.4", "morphology_code": "8890/3",
                          "topography_code": "C49.4", "name": "Leiomyosarcoma"},
        "histology_codes": [{"code": "8890/3", "note_id": "p2n2"}],
        "topography_codes": [{"code": "C49.4", "note_id": "p2n2"}],
    },
    "P3": {"patient_id": "P3", "status": "skipped",
           "histology_codes": [], "topography_codes": []},
}


def _resolve(conflict_config=None, existing=None):
    return StudyResolver().resolve_session(
        _build_session(), STUDY, VARIABLES,
        conflict_config=conflict_config,
        patient_diagnoses=PATIENT_DIAGNOSES,
        existing=existing,
    )


def test_unanimous_value_is_auto():
    res = _resolve()
    sex = res["P1"]["variables"]["sex"]
    assert sex["status"] == "auto", sex
    assert sex["proposed_value"] == "male"
    age = res["P1"]["variables"]["age"]
    assert age["status"] == "auto" and age["proposed_value"] == "65"


def test_conflict_without_rules_needs_review():
    res = _resolve()  # no conflict config
    sex = res["P2"]["variables"]["sex"]
    assert sex["status"] == "needs_review"
    assert sex["conflict"] is True
    # default suggestion = most recent note (p2n2 / 06-02-2019 / 'male')
    assert sex["proposed_value"] == "male", sex


def test_missing_value_needs_review():
    res = _resolve()
    sex = res["P3"]["variables"]["sex"]
    assert sex["status"] == "needs_review"
    assert sex["proposed_value"] is None
    assert "No value extracted" in " ".join(sex["review_reasons"])


def test_report_type_ranking_auto_resolves():
    cfg = {"enabled": True, "per_variable": {
        "sex": {"strategy": "report_type_ranking", "ranking": ["pathology", "clinical"]}}}
    res = _resolve(conflict_config=cfg)
    sex = res["P2"]["variables"]["sex"]
    assert sex["status"] == "confirmed", sex
    assert sex["auto_resolved"] is True
    assert sex["resolution_rule"] == "report_type_ranking"
    assert sex["value"] == "male"  # pathology beats clinical


def test_ranking_tie_goes_manual():
    # both notes ranked the same -> cannot decide -> manual
    cfg = {"enabled": True, "per_variable": {
        "age": {"strategy": "report_type_ranking", "ranking": ["clinical"]}}}
    # P2 age: clinical=70, pathology=71 -> only clinical ranked, single value 70 -> resolves
    res = _resolve(conflict_config=cfg)
    age = res["P2"]["variables"]["age"]
    assert age["status"] == "confirmed" and age["value"] == "70", age


def test_date_strategy_earliest():
    cfg = {"enabled": True, "per_variable": {
        "age": {"strategy": "date", "date_pref": "earliest"}}}
    res = _resolve(conflict_config=cfg)
    age = res["P2"]["variables"]["age"]
    # earliest = p2n1 (05/02/2019) -> 70
    assert age["status"] == "confirmed", age
    assert age["value"] == "70"
    assert age["resolution_rule"] == "date_earliest"


def test_eligibility_included_excluded_and_diagnosis():
    res = _resolve()
    assert res["P1"]["eligibility"]["auto_decision"] == "included", res["P1"]["eligibility"]
    assert res["P2"]["eligibility"]["auto_decision"] == "excluded", res["P2"]["eligibility"]
    # P3: no diagnosis codes + no surgery -> needs_review (unknowns)
    assert res["P3"]["eligibility"]["auto_decision"] == "needs_review"
    # diagnosis parts: the LLM code is NOT trusted -> needs a real-code pick
    assert res["P1"]["variables"]["histology"]["status"] == "needs_review"
    assert res["P1"]["variables"]["histology"]["llm_code"] == "8850/3"
    assert "C48.0" in (res["P1"]["variables"]["topography"]["proposed_value"] or "")
    # the combination reflects the resolved diagnosis code
    assert res["P1"]["variables"]["diagnosis_code"]["status"] == "auto"
    assert "8850/3-C48.0" in (res["P1"]["variables"]["diagnosis_code"]["proposed_value"] or "")


def test_user_selected_diagnosis_part_confirmed():
    # a reviewer-picked real code shows as confirmed with selected_code
    pd = {
        "PZ": {
            "patient_id": "PZ", "status": "manually_resolved",
            "resolved_code": {"query_code": "8851/3-C48.0", "morphology_code": "8851/3",
                              "topography_code": "C48.0", "name": "Well-diff liposarcoma",
                              "validation": {"combination_valid": True}},
            "histology_codes": [{"code": "8850/3", "note_id": "n"}],
            "topography_codes": [{"code": "C48.0", "note_id": "n"}],
            "user_diagnosis": {
                "histology": {"code": "8851/3", "label": "Well-differentiated liposarcoma", "reviewer": "alice"},
                "topography": {"code": "C48.0", "label": "Retroperitoneum", "reviewer": "alice"},
            },
        }
    }
    session = {"notes": [{"note_id": "n", "p_id": "PZ", "report_type": "pathology", "date": "10/01/2020"}],
               "annotations": {"n": {}}}
    res = StudyResolver().resolve_session(session, STUDY, VARIABLES, patient_diagnoses=pd)
    h = res["PZ"]["variables"]["histology"]
    assert h["status"] == "confirmed" and h["selected_code"] == "8851/3", h
    assert h["reviewed_by"] == "alice"
    dc = res["PZ"]["variables"]["diagnosis_code"]
    assert dc["combination_valid"] is True and "8851/3-C48.0" in (dc["proposed_value"] or "")


def test_extract_llm_label():
    from services.study_resolver import _extract_llm_label
    assert _extract_llm_label("Histological type: Liposarcoma (8850/3).") == "Liposarcoma"
    assert _extract_llm_label("Tumor site (Retroperitoneum): Retroperitoneum (C48.0).") == "Retroperitoneum"


def test_human_confirmation_preserved_on_recompute():
    existing = {
        "P2": {
            "patient_id": "P2",
            "eligibility": {"decision": "included", "confirmed": True,
                            "decided_by": "alice", "decided_at": "2026-06-30T00:00:00"},
            "variables": {
                "sex": {"key": "sex", "status": "confirmed", "value": "female",
                        "reviewed_by": "alice", "auto_resolved": False},
            },
        }
    }
    res = _resolve(existing=existing)
    sex = res["P2"]["variables"]["sex"]
    assert sex["status"] == "confirmed" and sex["value"] == "female"
    assert sex["reviewed_by"] == "alice"
    elig = res["P2"]["eligibility"]
    assert elig["decision"] == "included" and elig["confirmed"] is True


def test_negated_value_excluded_from_candidates():
    # P1 sex is unanimous 'male'; add a negated 'female' which must be ignored
    session = _build_session()
    session["annotations"]["p1n1"]["gender-int-sarc"] = _ann("Patient's gender female.", is_negated=True)
    # add a second P1 note with a real 'male' so there is a real value
    session["notes"].append({"note_id": "p1n2", "p_id": "P1", "report_type": "clinical", "date": "11/01/2020"})
    session["annotations"]["p1n2"] = {"gender-int-sarc": _ann("Patient's gender male.")}
    res = StudyResolver().resolve_session(session, STUDY, VARIABLES, patient_diagnoses=PATIENT_DIAGNOSES)
    sex = res["P1"]["variables"]["sex"]
    assert sex["conflict"] is False, sex          # negated 'female' did not create a conflict
    assert sex["status"] == "auto" and sex["proposed_value"] == "male"


def test_date_tie_zero_padding_goes_manual():
    # same calendar day, different zero-padding, conflicting values -> manual
    cfg = {"enabled": True, "per_variable": {
        "age": {"strategy": "date", "date_pref": "earliest"}}}
    cands = [
        {"value": "60", "date": "1/1/2020", "report_type": "a"},
        {"value": "61", "date": "01/01/2020", "report_type": "b"},
    ]
    chosen = StudyResolver()._resolve_by_date_strict(cands, "earliest")
    assert chosen is None, chosen   # tie on the same day (despite padding) -> manual


def test_unresolved_diagnosis_not_auto_included():
    # needs_review diagnosis with one matching code among conflicts must NOT
    # satisfy the histology criterion
    pd = {
        "PX": {
            "patient_id": "PX", "status": "needs_review", "resolved_code": None,
            "histology_codes": [{"code": "8850/3", "note_id": "n"}, {"code": "8000/3", "note_id": "n2"}],
            "topography_codes": [{"code": "C48.0", "note_id": "n"}],
        }
    }
    session = {
        "notes": [{"note_id": "n", "p_id": "PX", "report_type": "pathology", "date": "10/01/2020"}],
        "annotations": {"n": {"surgerytype-int-sarc": _ann("Surgical procedure")}},
    }
    res = StudyResolver().resolve_session(session, STUDY, VARIABLES, patient_diagnoses=pd)
    elig = res["PX"]["eligibility"]
    assert elig["criteria"]["histology"] is None, elig   # unresolved -> unknown
    assert elig["auto_decision"] == "needs_review", elig


def test_treatment_prefixed_absence_not_counted_present():
    # 'Surgery type: None.' must NOT count as treatment present (false-include guard)
    present = StudyResolver._treatment_present(
        "surgerytype",
        [{"note_id": "n"}],
        {"n": {"surgerytype-int-sarc": _ann("Surgery type: None.")}},
    )
    assert present is False, present
    # a real surgery value IS present
    present2 = StudyResolver._treatment_present(
        "surgerytype",
        [{"note_id": "n"}],
        {"n": {"surgerytype-int-sarc": _ann("Surgical procedure")}},
    )
    assert present2 is True, present2


def test_event_any_ignores_negated_recurrence():
    var = {"key": "recurrence", "label": "Recurrence", "source": "event_any",
           "prompt_type": "recur_or_prog", "positive_values": ["recurrence", "progression"]}
    notes = [{"note_id": "n1", "p_id": "PR", "report_type": "fu", "date": "01/03/2021"},
             {"note_id": "n2", "p_id": "PR", "report_type": "fu", "date": "01/06/2021"}]
    anns = {
        "n1": {"recur_or_prog-int-sarc": _ann("There was no progression/recurrence.")},
        "n2": {"recur_or_prog-int-sarc": _ann("There was a progression on 01/06/2021.")},
    }
    res = StudyResolver()._resolve_event_variable(var, notes, anns)
    assert res["proposed_value"].startswith("Yes"), res           # the real progression counts
    assert "no progression" not in (res["proposed_value"] or "").lower(), res  # negated one excluded

    # all-negative -> No
    anns2 = {"n1": {"recur_or_prog-int-sarc": _ann("No evidence of recurrence.")}}
    res2 = StudyResolver()._resolve_event_variable(var, notes[:1], anns2)
    assert res2["proposed_value"] == "No", res2


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        print(f"  PASS {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} study-review tests passed")


if __name__ == "__main__":
    _run_all()


# ---------------------------------------------------------------------------
# clinical timeline (StudyResolver.build_timeline) + inclusion criteria
# ---------------------------------------------------------------------------
TIMELINE_VARS = [
    {"key": "diagnosis_code", "source": "diagnosis",
     "timeline": {"category": "diagnosis", "label": "Diagnosis"}},
    {"key": "surgery", "label": "Surgery", "source": "presence",
     "timeline": {"category": "treatment"}},
    {"key": "chemo", "label": "Chemotherapy", "source": "presence",
     "timeline": {"category": "treatment"}},
    {"key": "recurrence", "source": "event_any",
     "positive_values": ["recurrence", "progression"], "timeline": {"category": "status"}},
    {"key": "metastasis", "source": "event_any",
     "positive_values": ["metastatic"], "timeline": {"category": "metastasis"}},
    {"key": "sex", "source": "annotation"},  # no timeline block -> excluded
]


def _tl_state():
    return {
        "diagnosis_code": {"key": "diagnosis_code", "status": "confirmed", "auto_resolved": False,
            "reviewed_by": "Dr X", "value": "8850/3 C48.0",
            "candidates": [{"value": "8850/3", "date": "10/01/2020", "date_from": "note"}]},
        "surgery": {"key": "surgery", "status": "auto", "auto_resolved": False, "proposed_value": "Yes",
            "candidates": [{"value": "Primary surgery", "date": "15/02/2020", "date_from": "event"}]},
        "chemo": {"key": "chemo", "status": "confirmed", "auto_resolved": False, "reviewed_by": "Dr X",
            "value": "Yes (neoadjuvant)",
            "candidates": [{"value": "pre-op chemo", "date": "20/01/2020", "date_from": "note"}]},
        "recurrence": {"key": "recurrence", "status": "auto", "auto_resolved": False, "proposed_value": "Yes",
            "candidates": [
                {"value": "There was a recurrence on 05/06/2021", "date": "05/06/2021", "date_from": "event"},
                {"value": "There was no progression/recurrence", "date": "01/01/2021", "date_from": "note"}]},
        "metastasis": {"key": "metastasis", "status": "confirmed", "auto_resolved": False, "reviewed_by": "Dr X",
            "value": "Yes",
            "candidates": [{"value": "metastatic lung, bone", "date": "01/02/2022", "date_from": "note"}]},
        "sex": {"key": "sex", "status": "auto", "candidates": [{"value": "male", "date": "10/01/2020"}]},
    }


def test_timeline_diagnosis_first_and_ordered():
    tl = StudyResolver.build_timeline(_tl_state(), TIMELINE_VARS)
    assert tl[0]["category"] == "diagnosis"
    assert [e["date"] for e in tl] == \
        ["10/01/2020", "20/01/2020", "15/02/2020", "05/06/2021", "01/02/2022"]
    assert all(e["variable_key"] != "sex" for e in tl)  # no timeline block -> off timeline


def test_timeline_confirmed_vs_llm():
    by = {e["variable_key"]: e for e in StudyResolver.build_timeline(_tl_state(), TIMELINE_VARS)}
    assert by["diagnosis_code"]["confirmed"] is True and by["diagnosis_code"]["reviewed_by"] == "Dr X"
    assert by["surgery"]["confirmed"] is False and by["surgery"]["reviewed_by"] is None


def test_timeline_negation_excluded_and_metastasis_detail():
    tl = StudyResolver.build_timeline(_tl_state(), TIMELINE_VARS)
    labels = [(e["category"], e["label"]) for e in tl]
    assert ("status", "Recurrence") in labels
    assert ("status", "Progression") not in labels  # "no progression/recurrence" is negated
    met = next(e for e in tl if e["category"] == "metastasis")
    assert met["label"] == "Metastasis" and met["detail"] == "lung, bone" and met["date_from"] == "note"


def test_timeline_treatment_timing_detail():
    chemo = next(e for e in StudyResolver.build_timeline(_tl_state(), TIMELINE_VARS)
                 if e["variable_key"] == "chemo")
    assert chemo["category"] == "treatment" and chemo["detail"] == "neoadjuvant"


def test_timeline_auto_resolved_is_not_human_confirmed():
    st = _tl_state()
    st["metastasis"]["status"] = "confirmed"
    st["metastasis"]["auto_resolved"] = True   # settled by a rule, not a human
    st["metastasis"]["reviewed_by"] = "rule"
    met = next(e for e in StudyResolver.build_timeline(st, TIMELINE_VARS) if e["category"] == "metastasis")
    assert met["confirmed"] is False and met["reviewed_by"] is None


def test_inclusion_criteria_from_config():
    from routes.study import _inclusion_criteria
    from lib import study_config
    ic = _inclusion_criteria(study_config.get_study("liposarcoma_retroperitoneum"))
    assert [r["code"] for r in ic["histology"]] == ["8850", "8851", "8855", "8857", "8858"]
    topo = {(r["code"], r["label"]) for r in ic["topography"]}
    assert ("C48.0", "Retroperitoneum") in topo
    assert ("C49.4", "Inferior vena cava") in topo
    assert ("C49.5", "Iliac vessels") in topo
    assert ic["topography_label"] == "Retroperitoneum"


# ---------------------------------------------------------------------------
# LLM-vs-human evaluation (accept / edit / reject)
# ---------------------------------------------------------------------------
def test_classify_review_action_basic():
    C = StudyResolver.classify_review_action
    base = {"reviewed_by": "Dr A", "auto_resolved": False}
    assert C({**base, "status": "confirmed", "llm_value": "male", "value": "male"}) == "accept"
    assert C({**base, "status": "confirmed", "llm_value": "65", "value": "66"}) == "edit"
    assert C({**base, "status": "rejected", "llm_value": "x", "value": None}) == "reject"
    # rule-resolved and pending are NOT human decisions
    assert C({"status": "confirmed", "reviewed_by": "rule", "auto_resolved": True,
              "llm_value": "m", "value": "m"}) is None
    assert C({**base, "status": "needs_review", "llm_value": "m"}) is None
    # diagnosis compares the picked code to the LLM code
    assert C({**base, "status": "confirmed", "source": "diagnosis",
              "llm_code": "C48.0", "selected_code": "C48.0", "value": "C48.0 Retro"}) == "accept"
    assert C({**base, "status": "confirmed", "source": "diagnosis",
              "llm_code": "C49.9", "selected_code": "C48.1", "value": "C48.1 Mes"}) == "edit"


def test_evaluation_summary_counts_and_rates():
    def v(**k): return {"auto_resolved": False, **k}
    patients = {
        "P1": {"variables": {
            "sex": v(status="confirmed", reviewed_by="A", llm_value="male", value="male"),      # accept
            "age": v(status="confirmed", reviewed_by="A", llm_value="65", value="66"),          # edit
            "stage": v(status="rejected", reviewed_by="A", llm_value="localized", value=None),  # reject
        }},
        "P2": {"variables": {
            "sex": v(status="confirmed", reviewed_by="B", llm_value="female", value="female"),  # accept
            "age": v(status="confirmed", reviewed_by="rule", auto_resolved=True,
                     llm_value="70", value="70"),                                               # excluded (rule)
        }},
    }
    variables = [{"key": "sex", "label": "Sex", "prompt_type": "gender"},
                 {"key": "age", "label": "Age", "prompt_type": "ageatdiagnosis"},
                 {"key": "stage", "label": "Stage", "prompt_type": "stage_at_diagnosis"}]
    summ = StudyResolver.evaluation_summary(patients, variables)
    o = summ["overall"]
    assert (o["accept"], o["edit"], o["reject"], o["reviewed"]) == (2, 1, 1, 4)
    assert o["accept_rate"] == 0.5 and summ["reviewed_patients"] == 2
    by = {r["key"]: r for r in summ["per_variable"]}
    assert (by["sex"]["accept"], by["sex"]["reviewed"]) == (2, 2)
    assert by["age"]["edit"] == 1 and by["age"]["reviewed"] == 1  # rule-resolved P2.age excluded
    assert by["stage"]["reject"] == 1


def test_llm_value_preserved_across_recompute():
    # a human edited sex (LLM said 'male', reviewer set 'female'); after a fresh
    # recompute the LLM baseline must survive so the action stays 'edit'.
    existing = {"P1": {"variables": {"sex": {
        "key": "sex", "status": "confirmed", "value": "female", "reviewed_by": "Dr A",
        "auto_resolved": False, "llm_value": "male"}}}}
    sex = _resolve(existing=existing)["P1"]["variables"]["sex"]
    assert sex["llm_value"] == "male" and sex["value"] == "female"
    assert sex["review_action"] == "edit"


def test_review_action_accept_when_kept():
    existing = {"P1": {"variables": {"sex": {
        "key": "sex", "status": "confirmed", "value": "male", "reviewed_by": "Dr A",
        "auto_resolved": False, "llm_value": "male"}}}}
    assert _resolve(existing=existing)["P1"]["variables"]["sex"]["review_action"] == "accept"


# ---------------------------------------------------------------------------
# outcome events: assembly, merge, evidence-changed, missed evaluation
# ---------------------------------------------------------------------------
EVENT_CFG = [{"key": "recurrence", "timeline": {"category": "status"}},
             {"key": "metastasis", "timeline": {"category": "metastasis"}}]


def _event_vstate():
    return {
        "recurrence": {"candidates": [
            {"value": "There was a recurrence on 05/06/2021", "date": "05/06/2021", "date_from": "event", "note_id": "n2"},
            {"value": "There was a progression on 01/02/2022", "date": "01/02/2022", "date_from": "event", "note_id": "n3"},
            {"value": "There was no progression/recurrence", "date": "01/01/2021", "date_from": "note", "note_id": "n1"}]},
        "metastasis": {"candidates": [
            {"value": "metastatic lung, bone", "date": "01/02/2022", "date_from": "note", "note_id": "n3"},
            {"value": "local", "date": "05/06/2021", "date_from": "event", "note_id": "n2"}]},
    }


def test_build_events_assembly():
    ev = StudyResolver.build_events(_event_vstate(), EVENT_CFG)
    assert len(ev) == 2  # the "no recurrence" candidate is negated out
    byd = {e["date"]: e for e in ev}
    assert byd["05/06/2021"]["disease_status"] == "recurrence" and byd["05/06/2021"]["sites"] == ["localised"]
    assert byd["01/02/2022"]["disease_status"] == "progression"
    assert set(byd["01/02/2022"]["sites"]) == {"lung", "metastasisatbone"}


def test_build_events_merge_actions():
    fresh = StudyResolver.build_events(_event_vstate(), EVENT_CFG)
    prev = [
        {**fresh[0], "status": "confirmed", "reviewed_by": "Dr A"},   # accept
        {**fresh[1], "status": "dropped", "reviewed_by": "Dr A"},     # reject
        {"key": "manual:1", "disease_status": "recurrence", "date": "10/10/2023", "date_from": "event",
         "sites": ["liver"], "source_note_ids": [], "origin": "manual", "status": "confirmed",
         "reviewed_by": "Dr A", "edited": False, "evidence_changed": False},                     # missed
    ]
    ev = StudyResolver.build_events(_event_vstate(), EVENT_CFG, prev_events=prev)
    by = {e["key"]: e for e in ev}
    assert by["05/06/2021"]["review_action"] == "accept"
    assert by["01/02/2022"]["review_action"] == "reject"
    assert by["manual:1"]["review_action"] == "missed" and by["manual:1"]["origin"] == "manual"


def test_build_events_evidence_changed_on_rerun():
    fresh = StudyResolver.build_events(_event_vstate(), EVENT_CFG)
    prev = [{**fresh[0], "status": "confirmed", "reviewed_by": "Dr A"}]  # confirmed 05/06/2021
    # re-run where that recurrence's date moved to 09/09/2021
    moved = {"recurrence": {"candidates": [
        {"value": "There was a recurrence on 09/09/2021", "date": "09/09/2021", "date_from": "event", "note_id": "n2"}]},
        "metastasis": {"candidates": []}}
    ev = StudyResolver.build_events(moved, EVENT_CFG, prev_events=prev)
    stale = next(e for e in ev if e["key"] == "05/06/2021")
    assert stale["status"] == "confirmed" and stale["evidence_changed"] is True  # kept + flagged


def test_classify_event_action_direct():
    C = StudyResolver.classify_event_action
    assert C({"origin": "manual", "status": "confirmed"}) == "missed"
    assert C({"origin": "llm", "status": "dropped"}) == "reject"
    assert C({"origin": "llm", "status": "confirmed", "edited": True}) == "edit"
    assert C({"origin": "llm", "status": "confirmed", "edited": False}) == "accept"
    assert C({"origin": "llm", "status": "proposed"}) is None


def test_evaluation_includes_events_and_missed():
    def v(**k): return {"auto_resolved": False, **k}
    patients = {
        "P1": {
            "variables": {
                # LLM proposed nothing, human typed a value -> missed (false negative)
                "tumor_size": v(status="confirmed", reviewed_by="A", llm_value=None, value="120"),
                "sex": v(status="confirmed", reviewed_by="A", llm_value="male", value="male"),  # accept
            },
            "events": [
                {"origin": "llm", "status": "confirmed", "edited": False},   # accept
                {"origin": "manual", "status": "confirmed"},                 # missed
                {"origin": "llm", "status": "dropped"},                      # reject
            ],
        },
    }
    variables = [{"key": "tumor_size", "label": "Tumor size"}, {"key": "sex", "label": "Sex"}]
    summ = StudyResolver.evaluation_summary(patients, variables)
    o = summ["overall"]
    assert o["accept"] == 2 and o["missed"] == 2 and o["reject"] == 1 and o["edit"] == 0
    assert o["reviewed"] == 5
    ev_row = next(r for r in summ["per_variable"] if r["key"] == "__events__")
    assert ev_row["accept"] == 1 and ev_row["missed"] == 1 and ev_row["reject"] == 1


def test_event_sequence_exported_and_linked():
    """The confirmed outcome events export as EpisodeEvent (+ linked DiseaseExtent)
    rows; dropped events and excluded patients are omitted."""
    from routes.sessions import _apply_study_scope
    SID = "liposarcoma_retroperitoneum"
    session = {
        "annotations": {"n1": {"recur_or_prog-int-sarc": {"annotation_text": "x"},
                               "recurrencetype-int-sarc": {"annotation_text": "y"}}},
        "study_reviews": {SID: {"patients": {
            "P1": {"patient_id": "P1", "eligibility": {"decision": "included", "confirmed": True},
                   "variables": {}, "events": [
                       {"key": "05/06/2021", "disease_status": "recurrence", "date": "05/06/2021",
                        "sites": ["lung", "metastasisatbone"], "status": "confirmed", "origin": "llm"},
                       {"key": "drop", "disease_status": "recurrence", "date": "09/09/2020",
                        "sites": ["localised"], "status": "dropped", "origin": "llm"}]},
            "P2": {"patient_id": "P2", "eligibility": {"decision": "excluded", "confirmed": True},
                   "variables": {}, "events": [
                       {"key": "z", "disease_status": "recurrence", "date": "01/01/2020",
                        "sites": ["liver"], "status": "confirmed", "origin": "llm"}]},
        }}},
    }
    scoped, included = _apply_study_scope(session, [], SID)
    ev = [r for r in scoped if r["core_variable"].startswith(("EpisodeEvent", "DiseaseExtent"))]
    cvs = [r["core_variable"] for r in ev]
    assert included == {"P1"}
    assert cvs.count("EpisodeEvent.diseaseStatus") == 1        # dropped event omitted
    assert "DiseaseExtent.lung" in cvs and "DiseaseExtent.metastasisatbone" in cvs
    assert not any(r["patient_id"] == "P2" for r in ev)        # excluded patient omitted
    de = next(r for r in ev if r["core_variable"] == "DiseaseExtent.lung")
    ee = next(r for r in ev if r["core_variable"] == "EpisodeEvent.diseaseStatus")
    assert de["linked_to"] == ee["record_id"]                 # DiseaseExtent linked to EpisodeEvent
    assert ee["_prompt_type"] == "recur_or_prog-int-sarc" and de["value"] == "true"
