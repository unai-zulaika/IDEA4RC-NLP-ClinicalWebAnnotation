"""
History note detector for clinical anamnesis/history notes.

Identifies notes that contain multiple clinical events across different dates,
which require splitting before annotation to extract all events properly.
"""

import re
from typing import Optional


# Report type keywords that indicate a history/anamnesis note
_REPORT_TYPE_KEYWORDS = {
    # English
    "anamnesis", "history", "epicrisis",
    # Polish
    "wywiad", "historia", "przebieg", "epikryza",
    # Italian
    "anamnesi", "storia clinica", "sintesi clinica",
    "evoluzione", "decorso",
    # Swedish
    "anamnes", "sjukhistoria",
    # Generic prefix match
    "anamnes",
}

# Event markers: phrases that indicate a past clinical event
# Organized by language for maintainability
_EVENT_MARKERS = [
    # English
    r"status\s+post",
    r"s/p\b",
    r"condition\s+after",
    # Polish
    r"stan\s+po",                    # "condition after"
    r"po\s+leczeniu",                # "after treatment"
    r"po\s+operacji",                # "after surgery"
    r"po\s+chemioterapii",           # "after chemotherapy"
    r"po\s+radioterapii",            # "after radiotherapy"
    r"po\s+amputacji",               # "after amputation"
    r"po\s+resekcji",               # "after resection"
    r"po\s+usuni[eę]ciu",           # "after removal"
    r"po\s+brachyterapii",          # "after brachytherapy"
    r"po\s+mastektomii",            # "after mastectomy"
    r"po\s+plastyce",               # "after plastic surgery"
    r"po\s+wyci[eę]ciu",            # "after excision"
    # Italian
    r"intervento\s+chirurgico",      # "surgical intervention"
    r"trattamento\s+(?:adiuvante|neoadiuvante|chemioterapico|radioterapico)",  # "adjuvant/neoadjuvant/chemo/radio treatment"
    r"sottoposta?\s+a",              # "underwent" (submitted to)
    r"(?:si\s+)?ricovera",           # "hospitalized"
    r"eseguita?\s+(?:il|in\s+data)", # "performed on"
    r"(?:esame\s+)?istologic[oa]",   # "histological (examination)"
    r"E\.?\s*I\.?\s*:",              # "EI:" (Esame Istologico - histological exam)
    r"seguiva\s+",                   # "followed by" (treatment sequence)
    r"avviava\s+",                   # "started" (treatment)
    r"operata?\s+in\s+data",         # "operated on date"
    # Swedish
    r"opererad",                     # "operated"
    r"behandlad\s+med",             # "treated with"
    r"status\s+efter",               # "status after"
    r"genomg[åa]tt",                # "underwent"
]

_EVENT_MARKER_PATTERN = re.compile(
    "|".join(f"(?:{p})" for p in _EVENT_MARKERS),
    re.IGNORECASE,
)

# Date patterns to detect in note text
_DATE_PATTERNS = [
    r"\b\d{1,2}[./]\d{1,2}[./]\d{4}\b",     # DD.MM.YYYY or DD/MM/YYYY
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2}\b",      # DD.MM.YY
    r"\b\d{1,2}[./]\d{4}\b",                  # MM.YYYY or MM/YYYY
    r"\b\d{1,2}[-]\d{4}\b",                   # MM-YYYY (Italian style)
    r"\b\d{1,2}[-]\d{1,2}[-]\d{4}\b",         # DD-MM-YYYY (hyphenated)
    r"\(\d{4}\)",                              # (YYYY)
    r"\b\d{4}-\d{2}-\d{2}\b",                 # YYYY-MM-DD (ISO)
    r"\b\d{1,2}\.\d{2}\.\d{4}\s*r?\.",        # DD.MM.YYYY r. (Polish date)
    r"\b\d{2}-\d{4}\b",                       # MM-YYYY (Italian: 06-2019)
]

_DATE_PATTERN = re.compile("|".join(f"(?:{p})" for p in _DATE_PATTERNS))

# Year-only pattern for counting distinct years
_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

# Treatment keywords for detecting diverse event types
_TREATMENT_KEYWORDS = {
    "surgery": re.compile(
        # Polish
        r"operacj[aie]|resekcj[aie]|amputacj[aie]|mastektomi[aie]|wyci[eę]ci[eao]"
        # English
        r"|surgery|resection|excision"
        # Italian
        r"|intervento\s+chirurgico|resezione|asportazione|isteroannessectomia"
        r"|amputazione|mastectomia|exeresi|escissione|enucleazione"
        # Swedish
        r"|operation|resektion|amputation",
        re.IGNORECASE,
    ),
    "chemotherapy": re.compile(
        # Polish
        r"chemioterapi[aie]|systemow[eay]|paklitaksel|gemcytabin|docetaksel|ifosfamid"
        # English
        r"|chemotherapy|chth|cht\b"
        # Italian
        r"|chemioterapia|trattamento\s+(?:adiuvante|neoadiuvante|chemioterapico)"
        r"|gemcitabina|dacarbazina|adriamicina|doxorubicina|ifosfamide|paclitaxel"
        r"|cicl[oi]\b"  # "cycle(s)"
        # Swedish
        r"|kemoterapi|cytostatika",
        re.IGNORECASE,
    ),
    "radiotherapy": re.compile(
        # Polish
        r"radioterapii|brachyterapi[aie]|napromienianie"
        # English
        r"|radiotherapy|rth\b|brachytherapy|imrt"
        # Italian
        r"|radioterapia|brachiterapia|irradiazione"
        # Swedish
        r"|str[åa]lbehandling|str[åa]lterapi",
        re.IGNORECASE,
    ),
    "recurrence": re.compile(
        # Polish
        r"wznow[aey]|nawrot|progresj[aie]"
        # English
        r"|recurrence|progression|relapse"
        # Italian
        r"|recidiva|progressione|ripresa\s+di\s+malattia"
        # Swedish
        r"|recidiv|[åa]terfall|progress",
        re.IGNORECASE,
    ),
}


class HistoryNoteDetector:
    """Detects whether a clinical note is a history/anamnesis note
    containing multiple clinical events that need splitting."""

    def __init__(
        self,
        min_date_count: int = 3,
        min_event_markers: int = 3,
        min_distinct_treatment_types: int = 2,
    ):
        self.min_date_count = min_date_count
        self.min_event_markers = min_event_markers
        self.min_distinct_treatment_types = min_distinct_treatment_types

    def is_history_note(
        self, note_text: str, report_type: str = ""
    ) -> bool:
        """Quick check: is this note a history/anamnesis note?"""
        details = self.get_detection_details(note_text, report_type)
        return details["is_history"]

    def get_detection_details(
        self, note_text: str, report_type: str = ""
    ) -> dict:
        """Analyze a note and return detection details.

        Returns dict with:
            is_history: bool
            confidence: float (0.0-1.0)
            detected_events_estimate: int
            detection_methods: list of str (which criteria matched)
            date_count: int
            event_marker_count: int
            treatment_types_found: list of str
        """
        methods: list[str] = []
        confidence = 0.0

        # 1. Report type keyword match
        report_type_match = False
        if report_type:
            rt_lower = report_type.lower().strip()
            for kw in _REPORT_TYPE_KEYWORDS:
                if kw in rt_lower:
                    report_type_match = True
                    methods.append("report_type")
                    confidence += 0.4
                    break

        # 2. Count distinct date patterns
        date_matches = _DATE_PATTERN.findall(note_text)
        date_count = len(set(date_matches))

        # Also count distinct years for a broader signal
        year_matches = _YEAR_PATTERN.findall(note_text)
        distinct_years = len(set(year_matches))

        if date_count >= self.min_date_count:
            methods.append("date_count")
            confidence += min(0.3, 0.1 * date_count)

        # 3. Count event markers
        event_markers = _EVENT_MARKER_PATTERN.findall(note_text)
        event_marker_count = len(event_markers)
        if event_marker_count >= self.min_event_markers:
            methods.append("event_markers")
            confidence += min(0.4, 0.1 * event_marker_count)

        # 4. Diverse treatment types
        treatment_types_found: list[str] = []
        for ttype, pattern in _TREATMENT_KEYWORDS.items():
            if pattern.search(note_text):
                treatment_types_found.append(ttype)

        if len(treatment_types_found) >= self.min_distinct_treatment_types:
            methods.append("diverse_treatments")
            confidence += 0.2

        # Determine is_history: need at least one strong signal
        is_history = (
            report_type_match
            or (date_count >= self.min_date_count and event_marker_count >= self.min_event_markers)
            or (event_marker_count >= self.min_event_markers and len(treatment_types_found) >= self.min_distinct_treatment_types)
            or (date_count >= 5 and len(treatment_types_found) >= self.min_distinct_treatment_types)
        )

        # Estimate number of events from event markers and distinct dates
        detected_events_estimate = max(
            event_marker_count,
            date_count,
            len(treatment_types_found),
        )

        return {
            "is_history": is_history,
            "confidence": min(1.0, confidence),
            "detected_events_estimate": detected_events_estimate,
            "detection_methods": methods,
            "date_count": date_count,
            "distinct_years": distinct_years,
            "event_marker_count": event_marker_count,
            "treatment_types_found": treatment_types_found,
        }


# Module-level singleton
_detector: Optional[HistoryNoteDetector] = None


def get_history_detector(
    min_date_count: int = 3,
    min_event_markers: int = 3,
    min_distinct_treatment_types: int = 2,
) -> HistoryNoteDetector:
    """Get or create the singleton HistoryNoteDetector."""
    global _detector
    if _detector is None:
        _detector = HistoryNoteDetector(
            min_date_count=min_date_count,
            min_event_markers=min_event_markers,
            min_distinct_treatment_types=min_distinct_treatment_types,
        )
    return _detector
