"""Tests for condition_label_loader module."""
import pytest
from pathlib import Path
from lib.condition_label_loader import (
    ConditionLabelLoader,
    get_condition_labels,
    reset_condition_labels,
    _extract_code,
)


DATA_DIR = Path(__file__).parent / 'data' / 'condition_files'


class TestExtractCode:
    def test_clean_code(self):
        assert _extract_code('8670/0') == '8670/0'

    def test_code_with_old_ref(self):
        assert _extract_code('8072/3 (+ old 8121)') == '8072/3'

    def test_code_with_complex_suffix(self):
        assert _extract_code('8140/3 (+ ex 8440/3; 8480/3) + 8420') == '8140/3'

    def test_empty(self):
        assert _extract_code('') == ''

    def test_no_match(self):
        assert _extract_code('some text') == ''

    def test_whitespace(self):
        assert _extract_code('  8071/3  ') == '8071/3'


class TestConditionLabelLoader:
    @pytest.fixture(autouse=True)
    def setup(self):
        reset_condition_labels()
        yield
        reset_condition_labels()

    def test_load_succeeds(self):
        loader = ConditionLabelLoader(DATA_DIR)
        assert loader.load() is True
        assert loader._loaded is True
        assert len(loader.morphology_labels) > 0
        assert len(loader.topography_labels) > 0

    def test_load_missing_dir(self, tmp_path):
        loader = ConditionLabelLoader(tmp_path / 'nonexistent')
        # Should not crash, just return True with empty dicts
        assert loader.load() is True
        assert len(loader.morphology_labels) == 0

    def test_sarc_morphology_label(self):
        loader = ConditionLabelLoader(DATA_DIR)
        loader.load()
        label = loader.get_morphology_label('8670/0')
        assert label == 'Steroid cell tumour NOS'

    def test_hnc_morphology_label(self):
        loader = ConditionLabelLoader(DATA_DIR)
        loader.load()
        # 8071/3 is in hnc_morphology.csv
        label = loader.get_morphology_label('8071/3')
        assert 'squamous' in label.lower() or 'keratinizing' in label.lower()

    def test_sarc_topography_label(self):
        loader = ConditionLabelLoader(DATA_DIR)
        loader.load()
        label = loader.get_topography_label('C10.0')
        assert label == 'Vallecula'

    def test_hnc_topography_label(self):
        loader = ConditionLabelLoader(DATA_DIR)
        loader.load()
        label = loader.get_topography_label('C00.0')
        assert label != ''

    def test_unknown_code_returns_empty(self):
        loader = ConditionLabelLoader(DATA_DIR)
        loader.load()
        assert loader.get_morphology_label('9999/9') == ''
        assert loader.get_topography_label('C99.9') == ''

    def test_code_stripping(self):
        loader = ConditionLabelLoader(DATA_DIR)
        loader.load()
        assert loader.get_topography_label('  C10.0  ') == 'Vallecula'


class TestSingleton:
    @pytest.fixture(autouse=True)
    def setup(self):
        reset_condition_labels()
        yield
        reset_condition_labels()

    def test_get_condition_labels_returns_loader(self):
        loader = get_condition_labels(DATA_DIR)
        assert loader is not None
        assert loader._loaded is True

    def test_singleton_reuse(self):
        loader1 = get_condition_labels(DATA_DIR)
        loader2 = get_condition_labels(DATA_DIR)
        assert loader1 is loader2

    def test_reset(self):
        loader1 = get_condition_labels(DATA_DIR)
        reset_condition_labels()
        loader2 = get_condition_labels(DATA_DIR)
        assert loader1 is not loader2


class TestEnrichCodeLabelIntegration:
    """Test that _enrich_code_label uses condition files, not diagnosis-codes-list.csv."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_condition_labels()
        yield
        reset_condition_labels()

    def test_returns_condition_label_not_combination_name(self):
        from services.diagnosis_resolver import _enrich_code_label
        # Even if description contains a combination name, should return condition file label
        label = _enrich_code_label('8670/0', 'Steroid cell tumour NOS of parotid gland', 'histology')
        assert label == 'Steroid cell tumour NOS'

    def test_unknown_code_returns_empty(self):
        from services.diagnosis_resolver import _enrich_code_label
        label = _enrich_code_label('9999/9', 'Some combination name', 'histology')
        assert label == ''

    def test_topography_returns_condition_label(self):
        from services.diagnosis_resolver import _enrich_code_label
        label = _enrich_code_label('C10.0', '', 'topography')
        assert label == 'Vallecula'
