"""
Morphology Resolver

Resolves histological type descriptions to ICD-O-3 morphology codes (xxxx/x format)
using the condition_files CSVs (sarc_morphology.csv, hnc_morphology.csv).

Provides bidirectional lookup:
  - histology text → morphology code
  - morphology code → histology text
"""

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional

# Module-level singleton
_resolver: Optional["MorphologyResolver"] = None


class MorphologyResolver:
    """Loads all morphology CSVs and builds a normalised lookup index."""

    def __init__(self, condition_dir: Optional[Path] = None):
        if condition_dir is None:
            condition_dir = Path(__file__).parent.parent / "data" / "condition_files"
        self._condition_dir = condition_dir

        # text_norm → list of entry dicts
        self._text_to_entries: Dict[str, List[dict]] = {}
        # code (e.g. "8800/3") → list of entry dicts
        self._code_to_entries: Dict[str, List[dict]] = {}
        # All entries for prompt enrichment
        self._all_entries: List[dict] = []

        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> bool:
        if self._loaded:
            return True

        loaded_any = False

        # Load SARC morphology
        sarc_path = self._condition_dir / "sarc_morphology.csv"
        if sarc_path.exists():
            try:
                self._load_sarc_morphology(sarc_path)
                loaded_any = True
            except Exception as e:
                print(f"[WARN] Failed to load sarc_morphology.csv: {e}")

        # Load HNC morphology
        hnc_path = self._condition_dir / "hnc_morphology.csv"
        if hnc_path.exists():
            try:
                self._load_hnc_morphology(hnc_path)
                loaded_any = True
            except Exception as e:
                print(f"[WARN] Failed to load hnc_morphology.csv: {e}")

        self._loaded = loaded_any
        if loaded_any:
            print(f"[INFO] MorphologyResolver loaded {len(self._all_entries)} entries, "
                  f"{len(self._code_to_entries)} unique codes")
        return loaded_any

    def _load_sarc_morphology(self, csv_path: Path) -> None:
        """Load sarc_morphology.csv. Only include rows where Si/No is 'Si' (case-insensitive)."""
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Filter: only rows marked as included
                si_no = (row.get("Si/No") or "").strip().lower()
                if si_no not in ("si", "sì"):
                    continue

                raw_code = (row.get("WHO 5th/ICD-O-3.2 Code") or "").strip()
                label = self._clean(row.get("WHO 5th/ICD-O-3.2 Label") or "")
                group = self._clean(row.get("Group") or "")
                behaviour = (row.get("behaviour") or row.get("Behaviour") or "").strip()

                if not label:
                    continue

                code = self._normalise_code(raw_code)
                # Some entries have no code but a valid label — still index by text
                entry = {
                    "label": label,
                    "code": code or raw_code,
                    "code_raw": raw_code,
                    "group": group,
                    "behaviour": behaviour,
                    "source": "sarc_morphology",
                }

                if code:
                    self._all_entries.append(entry)
                    self._code_to_entries.setdefault(code, []).append(entry)

                # Index by normalised label text
                norm = self._normalise_text(label)
                if norm:
                    self._text_to_entries.setdefault(norm, []).append(entry)

                # Also index by group name for broader matching
                if group:
                    group_norm = self._normalise_text(group)
                    if group_norm:
                        self._text_to_entries.setdefault(group_norm, []).append(entry)

    def _load_hnc_morphology(self, csv_path: Path) -> None:
        """Load hnc_morphology.csv. Only include rows with non-empty codes."""
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_code = self._clean(row.get("codes") or "")
                label = self._clean(row.get("Subtype") or "")
                type_group = self._clean(row.get("Type") or "")

                if not raw_code or not label:
                    continue

                # Extract primary code (e.g. "8072/3" from "8072/3 (+ old 8121)")
                code = self._normalise_code(raw_code)
                if not code:
                    continue

                entry = {
                    "label": label,
                    "code": code,
                    "code_raw": raw_code,
                    "group": type_group,
                    "behaviour": "",
                    "source": "hnc_morphology",
                }

                self._all_entries.append(entry)
                self._code_to_entries.setdefault(code, []).append(entry)

                # Index by normalised label text
                norm = self._normalise_text(label)
                if norm:
                    self._text_to_entries.setdefault(norm, []).append(entry)

                # Also index by type/group
                if type_group:
                    type_norm = self._normalise_text(type_group)
                    if type_norm:
                        self._text_to_entries.setdefault(type_norm, []).append(entry)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_text(self, text: str) -> Optional[dict]:
        """
        Resolve a histology description to its best morphology entry.

        Returns the entry dict with keys: label, code, group, ...
        or None if no match.
        """
        self._ensure_loaded()
        if not text:
            return None

        # Strategy 1: exact normalised match
        norm = self._normalise_text(text)
        entries = self._text_to_entries.get(norm)
        if entries:
            return entries[0]

        # Strategy 2: fuzzy token-overlap match
        best_match: Optional[dict] = None
        best_score = 0.0
        for key, entries in self._text_to_entries.items():
            score = self._fuzzy_score(norm, key)
            if score > best_score and score >= 0.6:
                best_score = score
                best_match = entries[0]

        return best_match

    def resolve_code(self, code: str) -> Optional[dict]:
        """Resolve a morphology code to its entry."""
        self._ensure_loaded()
        code = code.strip()
        entries = self._code_to_entries.get(code)
        return entries[0] if entries else None

    def get_all_entries(self) -> List[dict]:
        """Return all loaded morphology entries."""
        self._ensure_loaded()
        return self._all_entries

    def get_prompt_reference_lines(self, max_lines: int = 80) -> str:
        """
        Build a compact reference string for injection into LLM prompts.

        Format: "Label — xxxx/x" per line, deduplicated by (label, code).
        """
        self._ensure_loaded()
        seen = set()
        lines = []
        for entry in self._all_entries:
            key = (self._normalise_text(entry["label"]), entry["code"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"{entry['label']} — {entry['code']}")
            if len(lines) >= max_lines:
                break
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    @staticmethod
    def _normalise_code(raw: str) -> Optional[str]:
        """Extract a single morphology code (xxxx/x) from possibly messy input."""
        raw = raw.strip()
        m = re.match(r"^(\d{4}/\d)", raw)
        return m.group(1) if m else None

    @staticmethod
    def _clean(text: str) -> str:
        """Normalize whitespace (including non-breaking spaces) and strip."""
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _normalise_text(text: str) -> str:
        """Lowercase, strip, collapse whitespace, remove punctuation."""
        text = text.lower().strip()
        text = re.sub(r"[,;()\[\]\"'†]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        # Remove trailing NOS
        text = re.sub(r"\s*nos\s*$", "", text)
        return text

    @staticmethod
    def _fuzzy_score(a: str, b: str) -> float:
        """Simple token-overlap score between two normalised strings."""
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if a in b or b in a:
            shorter = min(len(a), len(b))
            longer = max(len(a), len(b))
            return 0.7 + 0.3 * (shorter / longer)

        tokens_a = set(a.split())
        tokens_b = set(b.split())
        if not tokens_a or not tokens_b:
            return 0.0
        overlap = tokens_a & tokens_b
        if not overlap:
            return 0.0
        return len(overlap) / max(len(tokens_a), len(tokens_b))


def get_morphology_resolver(condition_dir: Optional[Path] = None) -> MorphologyResolver:
    """Get or create the global MorphologyResolver singleton."""
    global _resolver
    if _resolver is None:
        _resolver = MorphologyResolver(condition_dir)
        _resolver.load()
    return _resolver


def reset_resolver():
    """Reset singleton (for testing)."""
    global _resolver
    _resolver = None
