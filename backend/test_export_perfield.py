"""
Regression tests for per-field export decomposition (_build_export_rows).

A multi-field prompt (e.g. chemotherapy_start = intent + regimen + ...) must emit
ONE normalized row per coded IDEA4RC field, all sharing one record_id, with each
field's value taken from derived_field_values (output_word_mappings). Single-field
prompts must keep emitting exactly one row (no regression). Non-coded fields (dates,
numbers, broken capture-group owm) must NOT surface as their own rows.

Run with:
    cd backend && python -m pytest test_export_perfield.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from routes.sessions import _build_export_rows, _prompt_entity_mappings          # noqa: E402
from lib.output_mapper import resolve_output_word_mappings                        # noqa: E402


def _rows(pt, final_output):
    em = _prompt_entity_mappings()[pt]
    dfv = resolve_output_word_mappings(final_output, em)
    session = {
        'notes': [{'note_id': 'n1', 'p_id': 'P1', 'date': '12/05/2021'}],
        'annotations': {'n1': {pt: {'annotation_text': final_output, 'derived_field_values': dfv}}},
    }
    rows, _ = _build_export_rows(session)
    return rows


def test_multifield_emits_one_row_per_coded_field_linked():
    rows = _rows('chemotherapy_start-int-sarc',
                 'pre-operative chemotherapy, curative, Doxorubicin + Ifosfamide regimen.')
    cvars = {r['core_variable']: r for r in rows}
    assert 'SystemicTreatment.intent' in cvars
    assert 'SystemicTreatment.regimen' in cvars
    assert cvars['SystemicTreatment.intent']['value'] == 'curative'
    assert cvars['SystemicTreatment.regimen']['value'] == 'Doxorubicin + Ifosfamide'
    # all rows of one prompt share a record_id (linked as one entity instance)
    assert len({r['record_id'] for r in rows}) == 1


def test_single_coded_field_still_emits():
    rows = _rows('radiotherapy_end-int-sarc', 'RT completed for toxicity.')
    cv = {r['core_variable'] for r in rows}
    assert 'Radiotherapy.rtTreatmentCompletedAsPlanned' in cv
    assert next(r for r in rows if r['core_variable'].endswith('rtTreatmentCompletedAsPlanned'))['value'] == 'toxicity'


def test_capture_group_owm_extracts_date_no_dollar_leak():
    # 2B: the dateOfNeckSurgery owm uses a capture group ($1) — it must now
    # extract the real date, and no row may leak a literal '$1'.
    rows = _rows('neck-surgery-laterality-int-hnc', 'Neck dissection Ipsilateral on 03/03/2022.')
    got = {r['core_variable'].split('.')[-1]: r['value'] for r in rows}
    assert got.get('lateralityOfTheDissection') == 'Ipsilateral'
    assert got.get('dateOfNeckSurgery') == '03/03/2022'
    assert all('$1' != r['value'] for r in rows)


def test_single_field_prompt_unregressed():
    for pt, out, field, val in [
        ('gender-int-sarc', "Patient's gender male.", 'Patient.sex', 'male'),
        ('biopsygrading-int-sarc', 'Biopsy grading (FNCLCC): 3.', 'Diagnosis.biopsyGrading', '3'),
    ]:
        rows = _rows(pt, out)
        assert len(rows) == 1, (pt, [r['core_variable'] for r in rows])
        assert rows[0]['core_variable'] == field
        assert rows[0]['value'] == val


def test_recurrencetype_string_to_per_site_booleans():
    # one controlled string -> one boolean row per metastatic site (DiseaseExtent)
    rows = _rows('recurrencetype-int-sarc',
                 'Type of recurrence/progression: metastatic lung, bone, soft tissue.')
    sites = {r['core_variable'].split('.')[-1] for r in rows}
    assert sites == {'lung', 'metastasisatbone', 'softTissue'}
    assert all(r['value'] == 'true' for r in rows)
    assert len({r['record_id'] for r in rows}) == 1
    # 'local' -> localised only
    assert {r['core_variable'].split('.')[-1]
            for r in _rows('recurrencetype-int-sarc',
                           'Type of recurrence/progression: local.')} == {'localised'}


def test_config_fixed_fields_resolve_to_dm_codes():
    """chemo setting->chemotherapyInfo, surgery boolean, previous cancer treatment, systemic type."""
    from routes.prompts import load_prompts_json
    by_cv = {}
    # build (pt, core_variable) -> vcm from prompts.json
    for _c, cps in load_prompts_json().items():
        for pt, pd in cps.items():
            for fm in pd.get('entity_mapping', {}).get('field_mappings', []):
                if fm.get('value_code_mappings'):
                    by_cv[(pt, f"{fm['entity_type']}.{fm['field_name']}")] = fm['value_code_mappings']

    def code(pt, out):
        rows = _rows(pt, out)
        got = {}
        for r in rows:
            vcm = by_cv.get((pt, r['core_variable']), {})
            got[r['core_variable'].split('.')[-1]] = vcm.get(r['value'])
        return got

    c = code('chemotherapy_start-int-sarc',
             'pre-operative chemotherapy, curative, Doxorubicin + Ifosfamide regimen.')
    assert c.get('intent') == '4162591' and c.get('chemotherapyInfo') == '4119031' and c.get('regimen') == '35806965'
    s = code('surgery-reconstruction-int-hnc',
             'Surgical approach Transoral with reconstruction; surgery intention curative.')
    assert s.get('reconstruction') == '4188539' and s.get('typeOfSurgicalApproachOnTumour') == '4038679'
    assert code('previous_cancer_treatment-int-sarc',
                'Previous cancer treatment: chemotherapy.').get('previousCancerTreatment') == '4273629'
    assert code('systemic-treatment-started-int-hnc',
                'Immunotherapy with curative intention at the hospital.').get('typeOfSystemicTreatment') == '40310107'


def test_2B_capture_group_numbers_and_dates():
    rows = _rows('radiotherapy_end-int-sarc',
                 'RT total dose 45 Gy in 25 fractions, ended for toxicity on 27/05/2022.')
    got = {r['core_variable'].split('.')[-1]: r['value'] for r in rows}
    assert got['totalDoseGy'] == '45'
    assert got['numberOfFractions'] == '25'
    assert got['endDate'] == '27/05/2022'
    assert got['rtTreatmentCompletedAsPlanned'] == 'toxicity'


def test_4A_previous_cancer_treatment_multivalue_no_conflict():
    from routes.sessions import _validate_and_deduplicate_rows
    rows = _rows('previous_cancer_treatment-int-sarc',
                 'Previous cancer treatment: surgery, chemotherapy.')
    vals = sorted(r['value'] for r in rows)
    assert vals == ['chemotherapy', 'surgery']
    assert len({r['record_id'] for r in rows}) == 1  # one Patient record
    _, conflicts, _ = _validate_and_deduplicate_rows(rows)
    assert conflicts == []  # multi-value must not trip the cardinality gate


def test_3B_neck_surgery_codes_from_real_output_format():
    # the LLM emits the CONTROLLED output "<LATERALITY> neck surgery was
    # performed on <DATE>." — neckSurgery=true only when laterality is FILLED.
    rows = _rows('neck-surgery-laterality-int-hnc',
                 'Bilateral neck surgery was performed on 12/03/2020.')
    got = {r['core_variable'].split('.')[-1]: r['value'] for r in rows}
    assert got.get('neckSurgery') == 'true'
    assert got.get('lateralityOfTheDissection') == 'Bilateral'
    # the no-surgery placeholder output must NOT set neckSurgery=true
    none_rows = _rows('neck-surgery-laterality-int-hnc',
                      '[select laterality] neck surgery was performed on [provide date].')
    assert 'Surgery.neckSurgery' not in {r['core_variable'] for r in none_rows}


def test_1C_split_prompts_reuse_response_to_fewshot_store():
    from routes.annotate import _strip_center_suffix
    assert _strip_center_suffix('response-to-chemo-int-sarc') == 'response-to'
    assert _strip_center_suffix('response-to-rt-int-sarc') == 'response-to'
    assert _strip_center_suffix('response-to-int-sarc') == 'response-to'  # unchanged


def test_1C_response_split_single_entity_each():
    ems = _prompt_entity_mappings()
    assert 'response-to-int-sarc' not in ems           # old dual-entity prompt retired
    # chemo prompt -> SystemicTreatment only
    chemo = _rows('response-to-chemo-int-sarc', 'Response to pre-operative chemotherapy was: partial response')
    assert {r['core_variable'] for r in chemo} == {'SystemicTreatment.chemotherapyInfo',
                                                   'SystemicTreatment.treatmentResponse'}
    # rt prompt -> Radiotherapy only
    rt = _rows('response-to-rt-int-sarc', 'Response to definitive radiotherapy was: stable disease')
    assert {r['core_variable'] for r in rt} == {'Radiotherapy.setting', 'Radiotherapy.treatmentResponse'}


def test_stage_at_diagnosis_multiboolean_all_centers():
    for c in ['int-sarc', 'msci', 'vgr']:
        pt = f'stage_at_diagnosis-{c}'
        def sites(out):
            return {r['core_variable'].split('.')[-1] for r in _rows(pt, out)}
        assert sites('Stage at diagnosis: localized.') == {'localised'}
        assert sites('Stage at diagnosis: loco-regional (In transit metastasis).') == \
            {'locoRegional', 'isTransitMetastasisWithClinicalConfirmation'}
        assert sites('Stage at diagnosis: distant metastases (lung).') == {'lung'}
        assert sites('Stage at diagnosis: metastatic (regional nodal metastases).') == {'regionalNodalMetastases'}
        # Unknown stage is an abstention -> nothing emitted
        assert sites('Unknown stage at diagnosis.') == set()
        # all emitted values are the boolean True (FormalConceptualDomain)
        rows = _rows(pt, 'Stage at diagnosis: distant metastases (lung).')
        assert all(r['value'] == 'true' for r in rows)


def test_surgerytype_type_and_date_margins_suppressed():
    rows = _rows('surgerytype-vgr',
                 'Local excision was performed on 12/05/2021 and was macroscopically complete.')
    got = {r['core_variable'].split('.')[-1]: r['value'] for r in rows}
    assert got.get('surgeryType') == 'Local excision'
    assert got.get('dateOfSurgery') == '12/05/2021'
    # margins are surgerymargins' job — surgerytype must NOT emit marginsAfterSurgery
    assert 'Surgery.marginsAfterSurgery' not in {r['core_variable'] for r in rows}
    # and surgerymargins itself still codes R0/R1/R2
    from routes.sessions import _extract_value_from_annotation, _classify_absence
    v = _extract_value_from_annotation('Margins after surgery: R1', 'surgerymargins-vgr')
    assert v == 'R1' and _classify_absence(v) == ''


def test_tumorrupture_boolean():
    assert _rows('tumorrupture-vgr', 'Tumor ruptured.')[0]['value'] == 'true'
    assert _rows('tumorrupture-vgr', 'Tumor did not rupture.')[0]['value'] == 'false'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
