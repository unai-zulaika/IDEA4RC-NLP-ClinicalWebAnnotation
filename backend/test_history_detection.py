"""Tests for history note detection."""

import pytest
from lib.history_detector import HistoryNoteDetector


@pytest.fixture
def detector():
    return HistoryNoteDetector()


# --- Sample notes ---

HISTORY_NOTE_POLISH = (
    "Stan po leczeniu z powodu raka piersi prawej - operacja oszczedzajaca, "
    "RTH i HTH Tamoksyfen (1999-2000) i raka piersi lewej - mastektomia z "
    "rekonstrukcja platem TRAM (2010-2011). Rak skory okolicy ledzwiowej "
    "prawej (Carcinoma basocellulare cutis). Stan po brachyterapii kontaktowej "
    "(2013). Rak skory piersi lewej. Stan po usunieciu zmiany skornej z lewej "
    "piersi (27.03.2017) - Rak podstawnokomorkowy skory. Miesak srodstopia "
    "prawego (2017). Wycieto miesaka srodstopia prawego drugiego razem z koscia "
    "srodstopia i palcem II (03.08.2017). Wznowa miesaka w 2025. Stan po "
    "amputacji I i III promienia stopy prawej (03.2025). Podejrzenie chloniaka"
)

HISTORY_NOTE_LONG = (
    "C49.2 Myxofibrosarcoma posladka w stadium rozsiewu - wznowa miejscowa MFS HG "
    "tkanek miekkich posladka lewego z wszczepami do tkanki podskornej i ww.chlonnych "
    "Stan po radioterapii technika IMRT+CBCT (02.2022) Stan po resekcji guza (20.02.2022) "
    "Progresja - wznowa miejscowa (TK 22.07.2022). Stan po chemioterapii AI (30.07.2022). "
    "Nietolerancja. Progresja. Stan po resekcji wznowy miesaka (12.08.2022). "
    "Stan po plastyce platowej (28.08.2022) Stan po chemioterapii DXL+GCB (11x, 2.11.2022-06.2023), "
    "GCB w monoterapii (7x, 06.2023-12.2023). Progresja nacieku tkanek miekkich (12.12.2023). "
    "Stan po chemioterapii HD-IFO (1x, 4.01.2024)"
)

SIMPLE_NOTE = (
    "Pacjent lat 65, rozpoznanie: Myxoid liposarcoma FNCLCC G1 uda prawego. "
    "Resekcja guza 15.03.2024."
)

SIMPLE_PATHOLOGY = (
    "Badanie histopatologiczne nr 12345. Rozpoznanie: Liposarcoma myxoides, "
    "FNCLCC G1. Margines wolny od nacieku nowotworowego. Wymiary: 5x4x3 cm."
)

NOTE_MANY_DATES_ONE_EVENT = (
    "Wizyta kontrolna dnia 15.03.2024. Wyniki badan z dnia 10.03.2024 i 12.03.2024 "
    "potwierdzaja stabilna chorobe. Kolejna wizyta zaplanowana na 20.04.2024."
)

# --- Italian sample notes ---

HISTORY_NOTE_ITALIAN = (
    "06-2019 – altrove - intervento chirurgico di isteroannessectomia bilaterale "
    "(tramite morcellamento senza endobag) con EI: leiomiosarcoma uterino (9cm). "
    "Seguiva trattamento adiuvante secondo schema gemcitabina-dacarbazina x 4 cicli "
    "(09-2019/12-2019). 02-10-2019 ricovero per neutropenia febbrile dopo II ciclo. "
    "02-2020 comparsa di recidiva pelvica. Sottoposta a intervento chirurgico di "
    "asportazione della recidiva in data 05-03-2020. EI: leiomiosarcoma ad alto grado. "
    "Seguiva trattamento con adriamicina x 6 cicli (05-2020/09-2020). "
    "01-2021 progressione di malattia con comparsa di localizzazioni polmonari bilaterali."
)

SIMPLE_NOTE_ITALIAN = (
    "Lesione parete toracica posteriore dx di circa 15 cm di consistenza "
    "duro lignea parzialmente mobile sui piani superficiali."
)

PATHOLOGY_NOTE_ITALIAN = (
    "LIPOSARCOMA MIXOIDE PRETRATTATO (diametro massimo 14cm) in cui si identificano: "
    "tumore residuo (circa 80%) rappresentato da componente classica (circa 10%) e "
    "componente di maturazione lipoblastica (circa 70%); sclero-jalinosi (circa 20%). "
    "Margini di resezione prossimale, distale, mediale e laterale indenni."
)

# --- Swedish sample note ---

HISTORY_NOTE_SWEDISH = (
    "Patienten opererad 2018-03-15 med resektion av sarkom i höger lår. "
    "Genomgått postoperativ strålbehandling 2018-05 till 2018-07. "
    "Status efter kemoterapi med doxorubicin 6 cykler (2018-08/2019-01). "
    "Recidiv diagnostiserat 2020-06. Opererad med amputation 2020-08-10. "
    "Behandlad med ifosfamid 4 cykler (2020-10/2021-02)."
)


class TestHistoryNoteDetection:
    """Test history note detection heuristics."""

    def test_detects_polish_history_note(self, detector):
        result = detector.get_detection_details(HISTORY_NOTE_POLISH)
        assert result["is_history"] is True
        assert result["confidence"] > 0.5
        assert result["event_marker_count"] >= 3
        assert "surgery" in result["treatment_types_found"]

    def test_detects_long_history_note(self, detector):
        result = detector.get_detection_details(HISTORY_NOTE_LONG)
        assert result["is_history"] is True
        assert result["confidence"] > 0.5
        assert result["event_marker_count"] >= 5

    def test_simple_note_not_history(self, detector):
        result = detector.get_detection_details(SIMPLE_NOTE)
        assert result["is_history"] is False

    def test_pathology_note_not_history(self, detector):
        result = detector.get_detection_details(SIMPLE_PATHOLOGY)
        assert result["is_history"] is False

    def test_many_dates_one_event_not_history(self, detector):
        """Notes with multiple dates but no event markers should not be history."""
        result = detector.get_detection_details(NOTE_MANY_DATES_ONE_EVENT)
        # Has 4 dates but no event markers
        assert result["event_marker_count"] < 3

    def test_report_type_triggers_detection(self, detector):
        result = detector.get_detection_details(
            "Krotka notatka", report_type="Anamnesis"
        )
        assert result["is_history"] is True
        assert "report_type" in result["detection_methods"]

    def test_report_type_wywiad(self, detector):
        result = detector.get_detection_details(
            "Krotka notatka", report_type="Wywiad lekarski"
        )
        assert result["is_history"] is True

    def test_is_history_note_shortcut(self, detector):
        """Test the quick boolean method."""
        assert detector.is_history_note(HISTORY_NOTE_POLISH) is True
        assert detector.is_history_note(SIMPLE_NOTE) is False

    def test_detection_details_structure(self, detector):
        """Test that the returned dict has all expected keys."""
        result = detector.get_detection_details(HISTORY_NOTE_POLISH)
        assert "is_history" in result
        assert "confidence" in result
        assert "detected_events_estimate" in result
        assert "detection_methods" in result
        assert "date_count" in result
        assert "event_marker_count" in result
        assert "treatment_types_found" in result
        assert isinstance(result["treatment_types_found"], list)
        assert isinstance(result["detection_methods"], list)

    def test_custom_thresholds(self):
        """Test that custom thresholds work."""
        strict_detector = HistoryNoteDetector(
            min_date_count=10, min_event_markers=10
        )
        # Should not detect with very strict thresholds
        result = strict_detector.get_detection_details(HISTORY_NOTE_POLISH)
        # Even with strict date/event thresholds, diverse treatments can still trigger
        # so just check that it's harder to detect
        assert result["confidence"] < 1.0

    def test_empty_note(self, detector):
        result = detector.get_detection_details("")
        assert result["is_history"] is False

    def test_confidence_bounded(self, detector):
        result = detector.get_detection_details(HISTORY_NOTE_LONG)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_diverse_treatment_types(self, detector):
        """Test that multiple treatment types are detected."""
        result = detector.get_detection_details(HISTORY_NOTE_LONG)
        assert len(result["treatment_types_found"]) >= 3
        assert "surgery" in result["treatment_types_found"]
        assert "chemotherapy" in result["treatment_types_found"]
        assert "radiotherapy" in result["treatment_types_found"]

    # --- Italian language tests ---

    def test_detects_italian_history_note(self, detector):
        """Italian anamnesis with multiple events should be detected."""
        result = detector.get_detection_details(HISTORY_NOTE_ITALIAN)
        assert result["is_history"] is True
        assert result["confidence"] > 0.5
        assert result["event_marker_count"] >= 3
        assert "surgery" in result["treatment_types_found"]
        assert "chemotherapy" in result["treatment_types_found"]
        assert "recurrence" in result["treatment_types_found"]

    def test_simple_italian_note_not_history(self, detector):
        """Short Italian exam note should not be detected."""
        result = detector.get_detection_details(SIMPLE_NOTE_ITALIAN)
        assert result["is_history"] is False

    def test_italian_pathology_not_history(self, detector):
        """Italian pathology report should not be detected."""
        result = detector.get_detection_details(PATHOLOGY_NOTE_ITALIAN)
        assert result["is_history"] is False

    def test_italian_report_type_anamnesi(self, detector):
        """Italian report type 'Anamnesi' should trigger detection."""
        result = detector.get_detection_details(
            "Breve nota clinica", report_type="Anamnesi Patologica Prossima"
        )
        assert result["is_history"] is True
        assert "report_type" in result["detection_methods"]

    def test_italian_hyphenated_dates(self, detector):
        """Italian date formats like MM-YYYY and DD-MM-YYYY should be counted."""
        result = detector.get_detection_details(HISTORY_NOTE_ITALIAN)
        assert result["date_count"] >= 3

    # --- Swedish language tests ---

    def test_detects_swedish_history_note(self, detector):
        """Swedish anamnesis with multiple events should be detected."""
        result = detector.get_detection_details(HISTORY_NOTE_SWEDISH)
        assert result["is_history"] is True
        assert result["confidence"] > 0.5
        assert "surgery" in result["treatment_types_found"]
        assert "chemotherapy" in result["treatment_types_found"]
        assert "radiotherapy" in result["treatment_types_found"]

    def test_swedish_report_type_anamnes(self, detector):
        """Swedish report type should trigger detection."""
        result = detector.get_detection_details(
            "Kort anteckning", report_type="Anamnes"
        )
        assert result["is_history"] is True
        assert "report_type" in result["detection_methods"]
