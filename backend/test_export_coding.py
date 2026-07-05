"""
Regression tests for coded-export resolution of prompts audited in the
prompt-improvement rollout: the value a model emits (following the template)
must resolve to an IDEA4RC code at export, via output_word_mappings reducing a
mid-sentence value to a bare value_code_mappings key, or via numeric cleaning.

Run with:
    cd backend && python -m pytest test_export_coding.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from routes.prompts import load_prompts_json                       # noqa: E402
from routes.sessions import _clean_value_by_data_type              # noqa: E402
from lib.output_mapper import resolve_output_word_mappings         # noqa: E402

PROMPTS = load_prompts_json()


def _em(center, key):
    return PROMPTS[center][key]['entity_mapping']


def _vcm(center, key, field):
    for fm in _em(center, key)['field_mappings']:
        if fm['field_name'] == field:
            return fm.get('value_code_mappings') or {}
    raise AssertionError(f'no field {field} in {center}/{key}')


# --- recur_or_prog: no-event dropped, recurrence/progression -> bare codable key ---
def test_recur_or_prog_owm():
    em = _em('INT-SARC', 'recur_or_prog-int-sarc')
    vcm = _vcm('INT-SARC', 'recur_or_prog-int-sarc', 'diseaseStatus')
    cases = {
        'There was a recurrence on 05/06/2022.': 'recurrence',
        'There was a progression on 05/06/2022.': 'progression',
    }
    for out, exp in cases.items():
        d = resolve_output_word_mappings(out, em)
        assert d.get('diseaseStatus') == exp, (out, d)
        assert exp in vcm  # bare key is codable
    # no-event routes to the export-dropped abstention, never a real status
    d = resolve_output_word_mappings('There was no progression/recurrence.', em)
    assert d.get('diseaseStatus') == 'Not applicable'


# --- radiotherapy_start intent: mid-sentence intent -> bare curative/palliative ---
def test_radiotherapy_intent_owm():
    for center, key in [('INT-SARC', 'radiotherapy_start-int-sarc'),
                        ('INT-HNC', 'radiotherapy_start-int-hnc')]:
        em = _em(center, key)
        vcm = _vcm(center, key, 'intent')
        for out, exp in [
            ('pre-operative radiotherapy (conventional) with curative intention started at INT on 12/05/2022.', 'curative'),
            ('Postoperative radiotherapy with palliative intention was started at the hospital on 12/05/2022.', 'palliative'),
        ]:
            d = resolve_output_word_mappings(out, em)
            assert d.get('intent') == exp, (center, out, d)
            assert exp in vcm


# --- tumorbiopsytype: mid-sentence [biopsy type] -> bare codable type ---
def test_tumorbiopsytype_owm():
    for center, key in [('INT-SARC', 'tumorbiopsytype-int-sarc'),
                        ('INT-HNC', 'tumorbiopsytype-int-hnc')]:
        em = _em(center, key)
        vcm = _vcm(center, key, 'typeOfBiopsy')
        cases = {
            'Baseline/primary tumor core-trucut biopsy has been performed on 12/05/2021 in INT.': 'core-trucut',
            'Baseline/primary tumor FNA biopsy has been performed on 12/05/2021 in INT.': 'FNA',
            'Baseline/primary tumor incisional biopsy has been performed on 12/05/2021 in INT.': 'incisional',
            'Baseline/primary tumor excisional biopsy has been performed on 12/05/2021 in INT.': 'excisional',
        }
        for out, exp in cases.items():
            d = resolve_output_word_mappings(out, em)
            assert d.get('typeOfBiopsy') == exp, (center, out, d)
            assert exp in vcm


# --- multifocality: VCM keyed on the extracted bare word, not the full line ---
def test_multifocality_vcm_bare_keys():
    for center in ['INT-SARC', 'INT-HNC']:
        key = f'multifocality-{center.lower()}'
        vcm = _vcm(center, key, 'isMultifocalTumor')
        assert 'multifocal' in vcm and vcm['multifocal'] is True
        assert 'unifocal' in vcm and vcm['unifocal'] is False
        # the old full-line keys must be gone
        assert 'Multifocality: multifocal.' not in vcm


# --- numeric cleaning: a number glued to a unit is captured, not a later date ---
def test_clean_value_glued_unit():
    assert _clean_value_by_data_type('70mm (at initial imaging on 12/05/2021)', 'float') == '70'
    assert _clean_value_by_data_type('7.5mm', 'float') == '7.5'
    assert _clean_value_by_data_type('62 years', 'Integer') == '62'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
