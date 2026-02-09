"""
Code resolver for converting text labels to IDEA4RC CodeableConcept codes.

Loads id2codes_dict.json and provides label-to-code resolution with
exact, substring, and fuzzy matching strategies.
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Optional, Tuple


# Mapping from core_variable strings to id2codes_dict categories
CORE_VARIABLE_TO_CATEGORY: Dict[str, str] = {
    "Patient.sex": "Sex",
    "Patient.race": "Race",
    "Patient.smoking": "Smoking",
    "Patient.alcohol": "Alcohol",
    "Patient.ecogPs": "ECOG PS label",
    "Patient.karnofsyIndex": "Karnofsy index label",
    "Patient.otherGeneticSyndrome": "Other Genetic syndrome",
    "Diagnosis.histology": "Histology",
    "Diagnosis.histologyGroup": "Histology group",
    "Diagnosis.histologySubgroup": "Histology subgroup",
    "Diagnosis.subsite": "Subsite",
    "Diagnosis.site": "Site",
    "Diagnosis.tumourDepth": "Deep depth ",
    "Diagnosis.typeOfBiopsy": "Type of biopsy",
    "Diagnosis.grading": "Grading",
    "Diagnosis.stageAtDiagnosis": "Clinical Staging",
    "Diagnosis.cT": "cT",
    "Diagnosis.cN": "cN",
    "Diagnosis.cM": "cM",
    "Diagnosis.pT": "pT",
    "Diagnosis.pN": "pN",
    "Diagnosis.pM": "pM",
    "Diagnosis.pathologicalStaging": "Pathological staging",
    "Diagnosis.extraNodalExtension": "Extra-nodal extension (rEne)",
    "Diagnosis.crpTested": "CRP \u2013 C reactive protein tested ",
    "Diagnosis.otherImagingForMetastasis": "Other imaging for metastasis",
    "Surgery.surgeryType": "Surgery type",
    "Surgery.intent": "Intent",
    "Surgery.typeOfSurgicalApproach": "Type of surgical approach on Tumour",
    "Surgery.marginsAfterSurgery": "Margins after surgery",
    "Surgery.lateralityOfDissection": "Laterality of the dissection",
    "Surgery.surgicalComplications": "Surgical complications (Clavien-Dindo Classification)",
    "Surgery.surgicalSpecimenGrading": "Grading",
    "Surgery.necrosisInSurgicalSpecimen": "Necrosis",
    "Surgery.reExcision": "Re-excision",
    "SystemicTreatment.typeOfSystemicTreatment": "type of systemic treatment",
    "SystemicTreatment.setting": "Setting",
    "SystemicTreatment.chemotherapyInfo": "Chemotherapy info",
    "SystemicTreatment.regimen": "Regimen",
    "SystemicTreatment.treatmentResponse": "Overall Treatment response (based on imaging alone; no recist or other criteria)",
    "SystemicTreatment.reasonForEndOfTreatment": "Reason for end of treatment",
    "Radiotherapy.setting": "Setting",
    "Radiotherapy.beamQuality": "Beam quality",
    "Radiotherapy.treatmentTechnique": "Treatment technique",
    "Radiotherapy.treatmentCompleted": "RT Treatment Completed as Planned?",
    "EpisodeEvent.diseaseStatus": "Disease status",
    "EpisodeEvent.recurrenceType": "Recurrence type",
    "PatientFollowUp.statusAtLastFollowUp": "Status of patient at last follow-up",
    "CancerEpisode.previousCancerTreatment": "Previous cancer treatment",
    "CancerEpisode.adverseEventDuration": "Adverse event duration",
}


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip, remove trailing
    punctuation, remove embedded ICD-O-3 code patterns, collapse whitespace."""
    if not text:
        return ""
    t = text.lower().strip()
    # Remove embedded ICD-O-3 code patterns like (8805/3) or [8805/3]
    t = re.sub(r'[\(\[]\d{4}/\d[\)\]]', '', t)
    # Remove trailing punctuation (period, semicolon, comma)
    t = t.rstrip('.;,')
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t


class CodeResolver:
    """Resolves text labels to IDEA4RC CodeableConcept code IDs."""

    def __init__(self, dict_path: Optional[str] = None):
        if dict_path is None:
            # Try shared data directory first, then fallback to project root
            shared_path = Path(__file__).parent.parent.parent / "data" / "dictionaries" / "id2codes_dict.json"
            if shared_path.exists():
                dict_path = str(shared_path)
            else:
                dict_path = str(Path(__file__).parent.parent.parent / "id2codes_dict.json")
        self._dict_path = dict_path
        # Reverse index: {category_normalized: {label_normalized: code_id}}
        self._index: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self):
        with open(self._dict_path, 'r', encoding='utf-8') as f:
            raw: Dict[str, str] = json.load(f)

        for code_id, description in raw.items():
            # Split "Category - Label" on first " - "
            parts = description.split(" - ", 1)
            if len(parts) != 2:
                continue
            category = parts[0].strip()
            label = parts[1].strip()

            cat_norm = _normalize(category)
            label_norm = _normalize(label)

            if cat_norm not in self._index:
                self._index[cat_norm] = {}
            self._index[cat_norm][label_norm] = code_id

    def resolve(self, value: str, core_variable: str) -> Tuple[Optional[str], float, str]:
        """Resolve a text label to a code ID.

        Returns:
            (code_id or None, confidence 0.0-1.0, method string)
            method is one of: "exact", "contains", "fuzzy", "unresolved"
        """
        category = CORE_VARIABLE_TO_CATEGORY.get(core_variable)
        if not category:
            return None, 0.0, "unresolved"

        cat_norm = _normalize(category)
        cat_entries = self._index.get(cat_norm)
        if not cat_entries:
            return None, 0.0, "unresolved"

        val_norm = _normalize(value)
        if not val_norm:
            return None, 0.0, "unresolved"

        # 1. Exact match
        if val_norm in cat_entries:
            return cat_entries[val_norm], 1.0, "exact"

        # 2. Substring / containment match
        best_contains: Optional[Tuple[str, str]] = None
        best_contains_len = 0
        for label, code_id in cat_entries.items():
            if label in val_norm or val_norm in label:
                # Prefer the longest matching label to be most specific
                if len(label) > best_contains_len:
                    best_contains = (code_id, label)
                    best_contains_len = len(label)
        if best_contains is not None:
            return best_contains[0], 0.9, "contains"

        # 3. Fuzzy match via SequenceMatcher
        best_ratio = 0.0
        best_fuzzy_code: Optional[str] = None
        for label, code_id in cat_entries.items():
            ratio = SequenceMatcher(None, val_norm, label).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_fuzzy_code = code_id

        if best_ratio >= 0.75 and best_fuzzy_code is not None:
            return best_fuzzy_code, round(best_ratio, 3), "fuzzy"

        # 4. No match
        return None, 0.0, "unresolved"
