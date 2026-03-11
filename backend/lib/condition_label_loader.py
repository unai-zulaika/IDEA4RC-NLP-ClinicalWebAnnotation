"""
Condition-specific ICD-O-3 code label loader.

Loads individual morphology and topography labels from condition files
(sarc + hnc CSVs) for display in the Patient Diagnoses panel.
"""

import csv
import re
from pathlib import Path
from typing import Dict, Optional


class ConditionLabelLoader:
    """Loads and indexes individual ICD-O-3 code labels from condition files."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.morphology_labels: Dict[str, str] = {}
        self.topography_labels: Dict[str, str] = {}
        self._loaded = False

    def load(self) -> bool:
        if self._loaded:
            return True
        try:
            self._load_sarc_morphology()
            self._load_hnc_morphology()
            self._load_sarc_topography()
            self._load_hnc_topography()
            self._loaded = True
            print(f"[INFO] Condition labels loaded: {len(self.morphology_labels)} morphology, "
                  f"{len(self.topography_labels)} topography codes")
            return True
        except Exception as e:
            print(f"[WARN] Failed to load condition labels: {e}")
            return False

    def get_morphology_label(self, code: str) -> str:
        if not self._loaded:
            self.load()
        return self.morphology_labels.get(code.strip(), '')

    def get_topography_label(self, code: str) -> str:
        if not self._loaded:
            self.load()
        return self.topography_labels.get(code.strip(), '')

    @staticmethod
    def _clean(text: str) -> str:
        """Normalize whitespace (including non-breaking spaces) and strip."""
        return re.sub(r'\s+', ' ', text).strip()

    def _load_sarc_morphology(self):
        """sarc_morphology.csv: 'WHO 5th/ICD-O-3.2 Code' → 'WHO 5th/ICD-O-3.2 Label'"""
        path = self.data_dir / 'sarc_morphology.csv'
        if not path.exists():
            return
        with open(path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                code = self._clean(row.get('WHO 5th/ICD-O-3.2 Code', ''))
                label = self._clean(row.get('WHO 5th/ICD-O-3.2 Label', ''))
                if code and label and code not in self.morphology_labels:
                    self.morphology_labels[code] = label

    def _load_hnc_morphology(self):
        """hnc_morphology.csv: 'codes' → 'Subtype'. Codes may have extra text."""
        path = self.data_dir / 'hnc_morphology.csv'
        if not path.exists():
            return
        with open(path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                raw_code = self._clean(row.get('codes', ''))
                label = self._clean(row.get('Subtype', ''))
                if not raw_code or not label:
                    continue
                code = _extract_code(raw_code)
                if code and code not in self.morphology_labels:
                    self.morphology_labels[code] = label

    def _load_sarc_topography(self):
        """sarc_topography.csv: 'ICD-O-3' → 'Subsite'"""
        path = self.data_dir / 'sarc_topography.csv'
        if not path.exists():
            return
        with open(path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                code = self._clean(row.get('ICD-O-3', ''))
                label = self._clean(row.get('Subsite', ''))
                if code and label and code not in self.topography_labels:
                    self.topography_labels[code] = label

    def _load_hnc_topography(self):
        """hnc_topography.csv: 'icdo3_code' → 'Sub-site'"""
        path = self.data_dir / 'hnc_topography.csv'
        if not path.exists():
            return
        with open(path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                code = self._clean(row.get('icdo3_code', ''))
                label = self._clean(row.get('Sub-site', ''))
                if code and label and code not in self.topography_labels:
                    self.topography_labels[code] = label


def _extract_code(raw: str) -> str:
    """Extract the primary ICD-O-3 code from a string like '8072/3 (+ old 8121)'."""
    m = re.match(r'^(\d{4}/\d)', raw.strip())
    return m.group(1) if m else ''


# Singleton
_loader: Optional[ConditionLabelLoader] = None


def get_condition_labels(data_dir: Optional[Path] = None) -> Optional[ConditionLabelLoader]:
    """Get or create the singleton ConditionLabelLoader."""
    global _loader
    if _loader is None:
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / 'data' / 'condition_files'
        if not data_dir.exists():
            print(f"[WARN] Condition files directory not found: {data_dir}")
            return None
        _loader = ConditionLabelLoader(data_dir)
        _loader.load()
    return _loader


def reset_condition_labels():
    """Reset singleton (for testing)."""
    global _loader
    _loader = None
