"""
Tests for MorphologyResolver and the histology-prompt fix in icdo3_extractor.
"""

import pytest
from pathlib import Path

from lib.morphology_resolver import MorphologyResolver, get_morphology_resolver, reset_resolver


CONDITION_DIR = Path(__file__).parent / "data" / "condition_files"


@pytest.fixture(autouse=True)
def _reset():
    """Reset singleton between tests."""
    reset_resolver()
    yield
    reset_resolver()


class TestMorphologyResolverLoading:
    """Test CSV loading from both sarc and hnc formats."""

    def test_load_succeeds(self):
        resolver = MorphologyResolver(CONDITION_DIR)
        assert resolver.load() is True

    def test_loads_entries(self):
        resolver = MorphologyResolver(CONDITION_DIR)
        resolver.load()
        entries = resolver.get_all_entries()
        assert len(entries) > 0, "Should load at least some morphology entries"

    def test_loads_sarc_entries(self):
        resolver = MorphologyResolver(CONDITION_DIR)
        resolver.load()
        sarc = [e for e in resolver.get_all_entries() if e["source"] == "sarc_morphology"]
        assert len(sarc) > 0, "Should load sarc_morphology entries"

    def test_loads_hnc_entries(self):
        resolver = MorphologyResolver(CONDITION_DIR)
        resolver.load()
        hnc = [e for e in resolver.get_all_entries() if e["source"] == "hnc_morphology"]
        assert len(hnc) > 0, "Should load hnc_morphology entries"

    def test_si_no_filtering(self):
        """Only rows with Si/No='Si' or 'si' should be loaded from sarc CSV."""
        resolver = MorphologyResolver(CONDITION_DIR)
        resolver.load()
        sarc = [e for e in resolver.get_all_entries() if e["source"] == "sarc_morphology"]
        # Row 1 in sarc_morphology.csv has Si/No="No" (Steroid cell tumour NOS) — should be excluded
        labels = [e["label"].lower() for e in sarc]
        assert "steroid cell tumour nos" not in labels, "Entries with Si/No='No' should be excluded"

    def test_entries_have_valid_codes(self):
        """All entries should have a morphology code in xxxx/x format."""
        resolver = MorphologyResolver(CONDITION_DIR)
        resolver.load()
        import re
        pattern = re.compile(r'^\d{4}/\d$')
        for entry in resolver.get_all_entries():
            assert pattern.match(entry["code"]), f"Invalid code format: {entry['code']} for {entry['label']}"


class TestMorphologyResolverResolveText:
    """Test text-to-code resolution."""

    def test_resolve_exact_sarc_label(self):
        """Known label from sarc_morphology.csv should resolve."""
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_text("Undifferentiated sarcoma")
        assert entry is not None
        assert entry["code"] == "8805/3"

    def test_resolve_exact_hnc_label(self):
        """Known label from hnc_morphology.csv should resolve."""
        resolver = get_morphology_resolver(CONDITION_DIR)
        # Full label: "Keratinizing squamous cell carcinoma; epidermoid carcinoma"
        entry = resolver.resolve_text("Keratinizing squamous cell carcinoma; epidermoid carcinoma")
        assert entry is not None
        assert entry["code"] == "8071/3"

    def test_resolve_hnc_partial_label(self):
        """Partial HNC label should fuzzy-match to a valid morphology code."""
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_text("Adenoid cystic carcinoma")
        assert entry is not None
        assert entry["code"] == "8200/3"

    def test_resolve_nos_variant(self):
        """Labels ending in NOS should fuzzy-match without NOS."""
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_text("Leiomyosarcoma NOS")
        assert entry is not None
        assert entry["code"] == "8890/3"

    def test_resolve_fuzzy_match(self):
        """Fuzzy matching should find close labels."""
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_text("Epithelioid leiomyosarcoma")
        assert entry is not None
        assert entry["code"] == "8891/3"

    def test_resolve_returns_none_for_unknown(self):
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_text("Completely unknown tumor type xyz123")
        assert entry is None

    def test_resolve_myxoid_liposarcoma(self):
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_text("Myxoid liposarcoma")
        assert entry is not None
        assert entry["code"] == "8852/3"


class TestMorphologyResolverResolveCode:
    """Test code-to-entry resolution."""

    def test_resolve_known_code(self):
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_code("8805/3")
        assert entry is not None
        assert "sarcoma" in entry["label"].lower()

    def test_resolve_unknown_code(self):
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_code("0000/0")
        assert entry is None

    def test_resolve_hnc_code(self):
        resolver = get_morphology_resolver(CONDITION_DIR)
        entry = resolver.resolve_code("8071/3")
        assert entry is not None


class TestExtractorHistologyFix:
    """Test that the icdo3_extractor correctly handles histology prompts."""

    def test_topography_only_discarded_for_histology_prompt(self):
        """Histology prompt with only a topography code should not use it."""
        from lib.icdo3_extractor import extract_icdo3_from_text

        result = extract_icdo3_from_text(
            "Histological type: Undifferentiated sarcoma (C64.0).",
            "histological-tipo-int"
        )
        # Should resolve to a morphology code, not C64.0
        assert result is not None
        assert result.get("morphology_code") is not None
        assert result["morphology_code"] != "C64.0"
        # Morphology codes are in xxxx/x format
        import re
        assert re.match(r'\d{4}/\d', result["morphology_code"]), \
            f"Expected morphology code format, got: {result['morphology_code']}"

    def test_histology_prompt_gets_morphology_code(self):
        """Histology annotation should resolve to correct morphology code."""
        from lib.icdo3_extractor import extract_icdo3_from_text

        result = extract_icdo3_from_text(
            "Histological type: Leiomyosarcoma NOS.",
            "histological-tipo-int"
        )
        assert result is not None
        assert result.get("morphology_code") == "8890/3"

    def test_site_prompt_still_gets_topography(self):
        """Site prompts should still use TopographyResolver — no regression."""
        from lib.icdo3_extractor import extract_icdo3_from_text

        result = extract_icdo3_from_text(
            "Tumor site (Upper and Lower limbs): Upper leg.",
            "tumorsite-int"
        )
        # Should resolve to a topography code
        if result:
            assert result.get("topography_code") is not None or result.get("code", "").startswith("C")

    def test_histology_with_existing_morphology_code_preserved(self):
        """If annotation already contains a morphology code, it should be kept."""
        from lib.icdo3_extractor import extract_icdo3_from_text

        result = extract_icdo3_from_text(
            "Histological type: Undifferentiated sarcoma (ICD-O-3: 8805/3).",
            "histological-tipo-int"
        )
        assert result is not None
        assert result.get("morphology_code") == "8805/3"

    def test_histology_prompt_alternative_naming(self):
        """Test with alternative prompt name 'histological-type-int'."""
        from lib.icdo3_extractor import extract_icdo3_from_text

        result = extract_icdo3_from_text(
            "Histological type: Epithelioid sarcoma.",
            "histological-type-int"
        )
        assert result is not None
        assert result.get("morphology_code") is not None
        import re
        assert re.match(r'\d{4}/\d', result["morphology_code"])


class TestSingleton:
    """Test singleton pattern."""

    def test_singleton_returns_same_instance(self):
        r1 = get_morphology_resolver(CONDITION_DIR)
        r2 = get_morphology_resolver(CONDITION_DIR)
        assert r1 is r2

    def test_reset_clears_singleton(self):
        r1 = get_morphology_resolver(CONDITION_DIR)
        reset_resolver()
        r2 = get_morphology_resolver(CONDITION_DIR)
        assert r1 is not r2
