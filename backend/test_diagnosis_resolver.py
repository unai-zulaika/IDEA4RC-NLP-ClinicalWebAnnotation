"""Tests for patient-level diagnosis resolver."""

import pytest
from unittest.mock import patch, MagicMock
from services.diagnosis_resolver import DiagnosisResolver, _classify_prompt_type


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(notes, annotations, patient_diagnoses=None):
    """Build a minimal session dict."""
    s = {'notes': notes, 'annotations': annotations}
    if patient_diagnoses is not None:
        s['patient_diagnoses'] = patient_diagnoses
    return s


def _make_note(p_id, note_id):
    return {'p_id': p_id, 'note_id': note_id, 'text': '...'}


def _make_annotation(morphology_code=None, topography_code=None, description=''):
    """Build a SessionAnnotation-like dict with icdo3_code."""
    icdo3 = None
    if morphology_code or topography_code:
        icdo3 = {
            'morphology_code': morphology_code or '',
            'topography_code': topography_code or '',
            'description': description,
        }
    return {
        'annotation_text': 'test',
        'values': [],
        'status': 'success',
        'icdo3_code': icdo3,
    }


def _mock_indexer(valid_combos=None):
    """Create a mock CSV indexer with given valid combinations.

    valid_combos: dict mapping query_code -> {Morphology, Topography, NAME, ID}
    """
    indexer = MagicMock()
    if valid_combos is None:
        valid_combos = {}

    indexer.query_index = valid_combos

    def validate_combination(morphology, topography):
        key = f"{morphology}-{topography}"
        if key in valid_combos:
            row = valid_combos[key]
            return {
                'valid': True,
                'query_code': key,
                'name': row.get('NAME', ''),
                'morphology_valid': True,
                'topography_valid': True,
                'row_data': row,
            }
        return {
            'valid': False,
            'query_code': None,
            'name': None,
            'morphology_valid': morphology in {r.get('Morphology') for r in valid_combos.values()},
            'topography_valid': topography in {r.get('Topography') for r in valid_combos.values()},
        }

    indexer.validate_combination = validate_combination
    return indexer


# ---------------------------------------------------------------------------
# _classify_prompt_type
# ---------------------------------------------------------------------------

class TestClassifyPromptType:
    def test_histology_int(self):
        assert _classify_prompt_type('histological-tipo-int') == 'histology'

    def test_histology_msci(self):
        assert _classify_prompt_type('histological-msci') == 'histology'

    def test_histology_vgr(self):
        assert _classify_prompt_type('histological-vgr') == 'histology'

    def test_topography_int(self):
        assert _classify_prompt_type('tumorsite-int') == 'topography'

    def test_topography_msci(self):
        assert _classify_prompt_type('tumorsite-msci') == 'topography'

    def test_topography_alt(self):
        assert _classify_prompt_type('tumor-site-int') == 'topography'

    def test_unrelated(self):
        assert _classify_prompt_type('age-at-diagnosis') is None

    def test_case_insensitive(self):
        assert _classify_prompt_type('Histological-TIPO-INT') == 'histology'


# ---------------------------------------------------------------------------
# DiagnosisResolver.resolve_session
# ---------------------------------------------------------------------------

class TestResolveSession:
    """Integration-style tests for the full resolver."""

    def test_patient_with_no_annotations(self):
        """Patient with notes but no annotations → skipped."""
        session = _make_session(
            notes=[_make_note('P1', 'N1')],
            annotations={},
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'skipped'

    def test_patient_with_no_diagnosis_prompts(self):
        """Patient has annotations but none are histology/topography → skipped."""
        session = _make_session(
            notes=[_make_note('P1', 'N1')],
            annotations={
                'N1': {
                    'age-at-diagnosis': {'annotation_text': '45', 'values': [], 'status': 'success', 'icdo3_code': None},
                }
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'skipped'

    def test_patient_missing_topography(self):
        """Patient has histology but no topography → needs_review."""
        session = _make_session(
            notes=[_make_note('P1', 'N1')],
            annotations={
                'N1': {
                    'histological-tipo-int': _make_annotation(morphology_code='8805/3'),
                }
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'needs_review'
        assert any('Missing topography' in r for r in result['P1']['review_reasons'])

    def test_patient_missing_histology(self):
        """Patient has topography but no histology → needs_review."""
        session = _make_session(
            notes=[_make_note('P1', 'N1')],
            annotations={
                'N1': {
                    'tumorsite-int': _make_annotation(topography_code='C49.5'),
                }
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'needs_review'
        assert any('Missing histology' in r for r in result['P1']['review_reasons'])

    def test_patient_conflicting_histology(self):
        """Two notes with different morphology codes → needs_review."""
        session = _make_session(
            notes=[_make_note('P1', 'N1'), _make_note('P1', 'N2')],
            annotations={
                'N1': {
                    'histological-tipo-int': _make_annotation(morphology_code='8805/3'),
                    'tumorsite-int': _make_annotation(topography_code='C49.5'),
                },
                'N2': {
                    'histological-tipo-int': _make_annotation(morphology_code='8810/3'),
                },
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'needs_review'
        assert any('conflicting histology' in r for r in result['P1']['review_reasons'])

    def test_patient_conflicting_topography(self):
        """Two notes with different topography codes → needs_review."""
        session = _make_session(
            notes=[_make_note('P1', 'N1'), _make_note('P1', 'N2')],
            annotations={
                'N1': {
                    'histological-tipo-int': _make_annotation(morphology_code='8805/3'),
                    'tumorsite-int': _make_annotation(topography_code='C49.5'),
                },
                'N2': {
                    'tumorsite-int': _make_annotation(topography_code='C71.7'),
                },
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'needs_review'
        assert any('conflicting topography' in r for r in result['P1']['review_reasons'])

    def test_same_code_from_multiple_notes_no_conflict(self):
        """Same morphology code from 2 notes is NOT a conflict."""
        combo = {
            '8805/3-C49.5': {
                'Morphology': '8805/3', 'Topography': 'C49.5',
                'NAME': 'Undifferentiated sarcoma', 'ID': '12345',
                'Query': '8805/3-C49.5',
            }
        }
        with patch('lib.icdo3_csv_indexer.get_csv_indexer', return_value=_mock_indexer(combo)):
            session = _make_session(
                notes=[_make_note('P1', 'N1'), _make_note('P1', 'N2')],
                annotations={
                    'N1': {
                        'histological-tipo-int': _make_annotation(morphology_code='8805/3'),
                        'tumorsite-int': _make_annotation(topography_code='C49.5'),
                    },
                    'N2': {
                        'histological-tipo-int': _make_annotation(morphology_code='8805/3'),
                    },
                },
            )
            resolver = DiagnosisResolver()
            result = resolver.resolve_session(session)
            assert result['P1']['status'] == 'auto_resolved'

    @patch('lib.icdo3_csv_indexer.get_csv_indexer')
    def test_auto_resolve_success(self, mock_get_indexer):
        """Exactly one histology + one topography, CSV match → auto_resolved."""
        combo = {
            '8805/3-C49.5': {
                'Morphology': '8805/3', 'Topography': 'C49.5',
                'NAME': 'Undifferentiated sarcoma of connective tissue',
                'ID': '44512345', 'Query': '8805/3-C49.5',
            }
        }
        mock_get_indexer.return_value = _mock_indexer(combo)

        session = _make_session(
            notes=[_make_note('P1', 'N1'), _make_note('P1', 'N2')],
            annotations={
                'N1': {
                    'histological-tipo-int': _make_annotation(morphology_code='8805/3'),
                },
                'N2': {
                    'tumorsite-int': _make_annotation(topography_code='C49.5'),
                },
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)

        p = result['P1']
        assert p['status'] == 'auto_resolved'
        assert p['resolved_code']['query_code'] == '8805/3-C49.5'
        assert p['csv_id'] == '44512345'
        assert p['resolved_by'] == 'auto'

    @patch('lib.icdo3_csv_indexer.get_csv_indexer')
    def test_no_csv_match(self, mock_get_indexer):
        """Combination doesn't exist in CSV → needs_review."""
        mock_get_indexer.return_value = _mock_indexer({})  # empty CSV

        session = _make_session(
            notes=[_make_note('P1', 'N1')],
            annotations={
                'N1': {
                    'histological-tipo-int': _make_annotation(morphology_code='9999/9'),
                    'tumorsite-int': _make_annotation(topography_code='C99.9'),
                },
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'needs_review'
        assert any('not found in diagnosis codes CSV' in r for r in result['P1']['review_reasons'])

    def test_preserve_manually_resolved(self):
        """Manually resolved entries are preserved on re-run."""
        manual_entry = {
            'patient_id': 'P1',
            'status': 'manually_resolved',
            'review_reasons': [],
            'histology_codes': [],
            'topography_codes': [],
            'resolved_code': {'query_code': '8805/3-C49.5'},
            'csv_id': '12345',
            'resolved_at': '2026-03-01T00:00:00',
            'resolved_by': 'user',
        }
        session = _make_session(
            notes=[_make_note('P1', 'N1')],
            annotations={
                'N1': {
                    'histological-tipo-int': _make_annotation(morphology_code='8805/3'),
                    'tumorsite-int': _make_annotation(topography_code='C49.5'),
                },
            },
            patient_diagnoses={'P1': manual_entry},
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'manually_resolved'
        assert result['P1']['csv_id'] == '12345'

    def test_multiple_patients(self):
        """Multiple patients resolved independently."""
        session = _make_session(
            notes=[
                _make_note('P1', 'N1'),
                _make_note('P2', 'N2'),
                _make_note('P3', 'N3'),
            ],
            annotations={
                'N1': {},  # P1: no diagnosis annotations → skipped
                'N2': {
                    'histological-msci': _make_annotation(morphology_code='8805/3'),
                    # P2: missing topography → needs_review
                },
                'N3': {},  # P3: no annotations → skipped
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'skipped'
        assert result['P2']['status'] == 'needs_review'
        assert result['P3']['status'] == 'skipped'

    def test_annotation_without_icdo3_code_ignored(self):
        """Annotations with no icdo3_code are gracefully skipped."""
        session = _make_session(
            notes=[_make_note('P1', 'N1')],
            annotations={
                'N1': {
                    'histological-tipo-int': {
                        'annotation_text': 'failed',
                        'values': [],
                        'status': 'error',
                        'icdo3_code': None,
                    },
                }
            },
        )
        resolver = DiagnosisResolver()
        result = resolver.resolve_session(session)
        assert result['P1']['status'] == 'skipped'


# ---------------------------------------------------------------------------
# resolve_manual
# ---------------------------------------------------------------------------

class TestResolveManual:
    @patch('lib.icdo3_csv_indexer.get_csv_indexer')
    def test_valid_code(self, mock_get_indexer):
        combo = {
            '8805/3-C49.5': {
                'Morphology': '8805/3', 'Topography': 'C49.5',
                'NAME': 'Undifferentiated sarcoma', 'ID': '44512345',
                'Query': '8805/3-C49.5',
            }
        }
        mock_get_indexer.return_value = _mock_indexer(combo)

        result = DiagnosisResolver.resolve_manual('8805/3-C49.5')
        assert result is not None
        assert result['csv_id'] == '44512345'
        assert result['resolved_code']['query_code'] == '8805/3-C49.5'

    @patch('lib.icdo3_csv_indexer.get_csv_indexer')
    def test_invalid_code(self, mock_get_indexer):
        mock_get_indexer.return_value = _mock_indexer({})
        result = DiagnosisResolver.resolve_manual('INVALID')
        assert result is None

    @patch('lib.icdo3_csv_indexer.get_csv_indexer')
    def test_indexer_unavailable(self, mock_get_indexer):
        mock_get_indexer.return_value = None
        result = DiagnosisResolver.resolve_manual('8805/3-C49.5')
        assert result is None
