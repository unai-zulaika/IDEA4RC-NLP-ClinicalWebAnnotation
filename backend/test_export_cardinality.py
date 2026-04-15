"""
Unit tests for cardinality-based export validation.

Tests the _validate_and_deduplicate_rows function and the /export/validate endpoint.

Run with:
    cd backend && .venv/bin/python -m pytest test_export_cardinality.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from main import app  # noqa: E402
from routes.sessions import _validate_and_deduplicate_rows  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helper to build a row dict matching _build_export_rows output format
# ---------------------------------------------------------------------------
def _row(patient_id, entity, core_variable, date_ref, value, record_id=1,
         note_id='N001', prompt_type='test-prompt'):
    return {
        '_note_id': note_id,
        '_prompt_type': prompt_type,
        'patient_id': patient_id,
        'original_source': 'NLP_LLM',
        'core_variable': core_variable,
        'date_ref': date_ref,
        'value': value,
        'record_id': record_id,
        'linked_to': '',
        'quality': '',
        'types': 'CodeableConcept',
        'icdo3_code': '',
        'entity': entity,
    }


# ---------------------------------------------------------------------------
# _validate_and_deduplicate_rows unit tests
# ---------------------------------------------------------------------------

class TestDeduplication:
    """Exact duplicate rows should be silently removed."""

    def test_exact_duplicates_removed(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),  # duplicate
        ]
        clean, conflicts, dedup_count = _validate_and_deduplicate_rows(rows)
        assert len(clean) == 1
        assert dedup_count == 1
        assert len(conflicts) == 0

    def test_no_duplicates_unchanged(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),
            _row('P1', 'Patient', 'Patient.age', '01/01/2024', '65'),
        ]
        clean, conflicts, dedup_count = _validate_and_deduplicate_rows(rows)
        assert len(clean) == 2
        assert dedup_count == 0


class TestNonRepeatableConflicts:
    """Non-repeatable entities (cardinality=1) allow only one value per (patient, variable)."""

    def test_single_value_passes(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),
        ]
        clean, conflicts, dedup_count = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 0
        assert len(clean) == 1

    def test_conflicting_values_detected(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),
            _row('P1', 'Patient', 'Patient.gender', '05/03/2024', 'Female'),  # conflict!
        ]
        clean, conflicts, dedup_count = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == 'non_repeatable'
        assert conflicts[0].patient_id == 'P1'
        assert conflicts[0].core_variable == 'Patient.gender'
        assert set(conflicts[0].conflicting_values) == {'Male', 'Female'}
        assert conflicts[0].date_ref is None  # non-repeatable ignores date

    def test_same_value_different_dates_ok(self):
        """Same value across different dates for non-repeatable = deduplicated, no conflict."""
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),
            _row('P1', 'Patient', 'Patient.gender', '05/03/2024', 'Male'),
        ]
        clean, conflicts, dedup_count = _validate_and_deduplicate_rows(rows)
        # These are NOT exact duplicates (different dates), but for non-repeatable
        # the values are the same, so no conflict
        assert len(conflicts) == 0

    def test_diagnosis_non_repeatable(self):
        rows = [
            _row('P1', 'Diagnosis', 'Diagnosis.diagnosisCode', '01/01/2024', '8031/3-C00.2'),
            _row('P1', 'Diagnosis', 'Diagnosis.diagnosisCode', '01/01/2024', '9999/3-C10.0'),
        ]
        clean, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == 'non_repeatable'


class TestRepeatableConflicts:
    """Repeatable entities (cardinality=0) allow different dates but not same-date conflicts."""

    def test_different_dates_ok(self):
        rows = [
            _row('P1', 'Surgery', 'Surgery.surgeryType', '01/01/2024', 'Wide excision'),
            _row('P1', 'Surgery', 'Surgery.surgeryType', '15/03/2024', 'Amputation'),
        ]
        clean, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 0
        assert len(clean) == 2

    def test_same_date_same_value_deduplicated(self):
        rows = [
            _row('P1', 'Surgery', 'Surgery.surgeryType', '01/01/2024', 'Wide excision'),
            _row('P1', 'Surgery', 'Surgery.surgeryType', '01/01/2024', 'Wide excision'),
        ]
        clean, conflicts, dedup_count = _validate_and_deduplicate_rows(rows)
        assert len(clean) == 1
        assert dedup_count == 1
        assert len(conflicts) == 0

    def test_same_date_different_values_conflict(self):
        rows = [
            _row('P1', 'Surgery', 'Surgery.surgeryType', '01/01/2024', 'Wide excision'),
            _row('P1', 'Surgery', 'Surgery.surgeryType', '01/01/2024', 'Amputation'),
        ]
        clean, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == 'repeatable_same_date'
        assert conflicts[0].date_ref == '01/01/2024'
        assert set(conflicts[0].conflicting_values) == {'Wide excision', 'Amputation'}

    def test_episode_event_different_dates(self):
        rows = [
            _row('P1', 'EpisodeEvent', 'EpisodeEvent.eventType', '01/01/2024', 'Progression'),
            _row('P1', 'EpisodeEvent', 'EpisodeEvent.eventType', '15/06/2024', 'Recurrence'),
        ]
        clean, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 0
        assert len(clean) == 2


class TestRecordIdReassignment:
    """Record IDs should reflect cardinality grouping."""

    def test_non_repeatable_shares_record_id(self):
        """All fields of a non-repeatable entity for one patient share the same record_id."""
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),
            _row('P1', 'Patient', 'Patient.age', '05/03/2024', '65'),
        ]
        clean, _, _ = _validate_and_deduplicate_rows(rows)
        assert clean[0]['record_id'] == clean[1]['record_id']

    def test_repeatable_different_dates_different_record_ids(self):
        rows = [
            _row('P1', 'Surgery', 'Surgery.surgeryType', '01/01/2024', 'Wide excision'),
            _row('P1', 'Surgery', 'Surgery.surgeryType', '15/03/2024', 'Amputation'),
        ]
        clean, _, _ = _validate_and_deduplicate_rows(rows)
        assert clean[0]['record_id'] != clean[1]['record_id']

    def test_repeatable_same_date_shares_record_id(self):
        rows = [
            _row('P1', 'Surgery', 'Surgery.surgeryType', '01/01/2024', 'Wide excision'),
            _row('P1', 'Surgery', 'Surgery.margin', '01/01/2024', 'R0'),
        ]
        clean, _, _ = _validate_and_deduplicate_rows(rows)
        assert clean[0]['record_id'] == clean[1]['record_id']


class TestMixedScenarios:
    """Complex scenarios mixing repeatable and non-repeatable entities."""

    def test_mixed_entities_no_conflicts(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),
            _row('P1', 'Diagnosis', 'Diagnosis.diagnosisCode', '01/01/2024', '8031/3'),
            _row('P1', 'Surgery', 'Surgery.surgeryType', '01/01/2024', 'Wide excision'),
            _row('P1', 'Surgery', 'Surgery.surgeryType', '15/03/2024', 'Amputation'),
        ]
        clean, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 0
        assert len(clean) == 4

    def test_multiple_patients(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male'),
            _row('P2', 'Patient', 'Patient.gender', '01/01/2024', 'Female'),
        ]
        clean, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 0
        assert len(clean) == 2

    def test_empty_rows(self):
        clean, conflicts, dedup_count = _validate_and_deduplicate_rows([])
        assert len(clean) == 0
        assert len(conflicts) == 0
        assert dedup_count == 0


class TestConflictSources:
    """Conflicts must carry the source notes that produced each value."""

    def test_non_repeatable_sources_populated(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male',
                 note_id='NOTE_A', prompt_type='gender-int'),
            _row('P1', 'Patient', 'Patient.gender', '05/03/2024', 'Female',
                 note_id='NOTE_B', prompt_type='gender-int'),
        ]
        _, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 1
        sources = conflicts[0].sources
        assert len(sources) == 2
        triples = {(s.value, s.note_id, s.prompt_type) for s in sources}
        assert triples == {
            ('Male', 'NOTE_A', 'gender-int'),
            ('Female', 'NOTE_B', 'gender-int'),
        }

    def test_repeatable_same_date_sources_populated(self):
        rows = [
            _row('P1', 'Surgery', 'Surgery.type', '01/01/2024', 'Wide excision',
                 note_id='NOTE_A', prompt_type='surgery-type'),
            _row('P1', 'Surgery', 'Surgery.type', '01/01/2024', 'Amputation',
                 note_id='NOTE_B', prompt_type='surgery-type'),
        ]
        _, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == 'repeatable_same_date'
        triples = {(s.value, s.note_id, s.prompt_type) for s in conflicts[0].sources}
        assert triples == {
            ('Wide excision', 'NOTE_A', 'surgery-type'),
            ('Amputation', 'NOTE_B', 'surgery-type'),
        }

    def test_sources_deduplicated(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male',
                 note_id='NOTE_A', prompt_type='gender-int'),
            _row('P1', 'Patient', 'Patient.gender', '02/01/2024', 'Male',
                 note_id='NOTE_A', prompt_type='gender-int'),
            _row('P1', 'Patient', 'Patient.gender', '05/03/2024', 'Female',
                 note_id='NOTE_B', prompt_type='gender-int'),
        ]
        _, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 1
        triples = {(s.value, s.note_id, s.prompt_type) for s in conflicts[0].sources}
        assert triples == {
            ('Male', 'NOTE_A', 'gender-int'),
            ('Female', 'NOTE_B', 'gender-int'),
        }

    def test_no_conflict_no_sources_needed(self):
        rows = [
            _row('P1', 'Patient', 'Patient.gender', '01/01/2024', 'Male',
                 note_id='NOTE_A', prompt_type='gender-int'),
        ]
        _, conflicts, _ = _validate_and_deduplicate_rows(rows)
        assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------

# Minimal session with annotations that produce exportable rows
def _make_session(annotations_by_note):
    """Build a session dict with the given annotations.

    annotations_by_note: dict of { note_id: { prompt_type: annotation_text } }
    """
    notes = []
    annotations = {}
    for i, (note_id, prompts) in enumerate(annotations_by_note.items()):
        notes.append({
            'text': f'Clinical note {i}',
            'date': '01/01/2024',
            'p_id': 'P001',
            'note_id': note_id,
            'report_type': 'CCE',
            'annotations': '',
        })
        annotations[note_id] = {}
        for pt, ann_text in prompts.items():
            annotations[note_id][pt] = {
                'note_id': note_id,
                'prompt_type': pt,
                'annotation_text': ann_text,
                'values': [{'value': ann_text, 'evidence_spans': [], 'reasoning': None}],
                'edited': False,
                'status': 'success',
                'evidence_spans': [],
            }

    return {
        'session_id': 'test-session-001',
        'name': 'Test Session',
        'description': '',
        'created_at': '2024-01-01T00:00:00',
        'updated_at': '2024-01-01T00:00:00',
        'notes': notes,
        'annotations': annotations,
        'prompt_types': list(set(
            pt for prompts in annotations_by_note.values() for pt in prompts
        )),
        'center': 'INT',
        'evaluation_mode': 'validation',
        'report_type_mapping': {},
        'patient_diagnoses': {},
    }


class TestValidateEndpoint:
    """Test the /export/validate endpoint."""

    def test_validate_no_conflicts(self, tmp_path):
        session = _make_session({
            'N001': {'gender-int': "Patient's gender male."},
        })
        session_file = tmp_path / 'test-session-001.json'
        session_file.write_text(json.dumps(session))

        with patch('routes.sessions._get_sessions_dir', return_value=tmp_path):
            resp = client.get('/api/sessions/test-session-001/export/validate')

        assert resp.status_code == 200
        data = resp.json()
        assert data['valid'] is True
        assert data['conflicts'] == []

    def test_validate_with_conflicts(self, tmp_path):
        # Two notes with same patient, same prompt type, but different values
        # for a non-repeatable entity (Patient)
        session = _make_session({
            'N001': {'gender-int': "Patient's gender male."},
            'N002': {'gender-int': "Patient's gender female."},
        })
        # Second note same patient
        session['notes'][1]['p_id'] = 'P001'
        session_file = tmp_path / 'test-session-001.json'
        session_file.write_text(json.dumps(session))

        with patch('routes.sessions._get_sessions_dir', return_value=tmp_path):
            resp = client.get('/api/sessions/test-session-001/export/validate')

        assert resp.status_code == 200
        data = resp.json()
        assert data['valid'] is False
        assert len(data['conflicts']) >= 1

    def test_export_labels_blocked_on_conflict(self, tmp_path):
        session = _make_session({
            'N001': {'gender-int': "Patient's gender male."},
            'N002': {'gender-int': "Patient's gender female."},
        })
        session['notes'][1]['p_id'] = 'P001'
        session_file = tmp_path / 'test-session-001.json'
        session_file.write_text(json.dumps(session))

        with patch('routes.sessions._get_sessions_dir', return_value=tmp_path):
            resp = client.get('/api/sessions/test-session-001/export')

        assert resp.status_code == 409
        detail = resp.json()['detail']
        assert 'conflicts' in detail
        assert len(detail['conflicts']) >= 1

    def test_export_codes_blocked_on_conflict(self, tmp_path):
        session = _make_session({
            'N001': {'gender-int': "Patient's gender male."},
            'N002': {'gender-int': "Patient's gender female."},
        })
        session['notes'][1]['p_id'] = 'P001'
        session_file = tmp_path / 'test-session-001.json'
        session_file.write_text(json.dumps(session))

        with patch('routes.sessions._get_sessions_dir', return_value=tmp_path):
            resp = client.get('/api/sessions/test-session-001/export/codes')

        assert resp.status_code == 409

    def test_export_succeeds_without_conflicts(self, tmp_path):
        session = _make_session({
            'N001': {'gender-int': "Patient's gender male."},
        })
        session_file = tmp_path / 'test-session-001.json'
        session_file.write_text(json.dumps(session))

        with patch('routes.sessions._get_sessions_dir', return_value=tmp_path):
            resp = client.get('/api/sessions/test-session-001/export')

        assert resp.status_code == 200
        assert 'text/csv' in resp.headers.get('content-type', '')
