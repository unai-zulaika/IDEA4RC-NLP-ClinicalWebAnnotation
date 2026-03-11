"""
Topography Resolver

Resolves tumor site descriptions to ICD-O-3 topography codes (Cxx.x format)
using the condition_files CSVs (sarc_topography.csv, hnc_topography.csv).

Provides bidirectional lookup:
  - subsite text → topography code
  - topography code → subsite text
"""

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Module-level singleton
_resolver: Optional["TopographyResolver"] = None


class TopographyResolver:
    """Loads all topography CSVs and builds a normalised lookup index."""

    def __init__(self, condition_dir: Optional[Path] = None):
        if condition_dir is None:
            condition_dir = Path(__file__).parent.parent / "data" / "condition_files"
        self._condition_dir = condition_dir

        # text_norm → list of (original_text, code, site, group, macrogrouping, source_file)
        self._text_to_entries: Dict[str, List[dict]] = {}
        # code (e.g. "C49.2") → list of entry dicts
        self._code_to_entries: Dict[str, List[dict]] = {}
        # All unique entries for prompt enrichment
        self._all_entries: List[dict] = []

        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> bool:
        if self._loaded:
            return True

        loaded_any = False
        for csv_file in sorted(self._condition_dir.glob("*_topography.csv")):
            try:
                self._load_csv(csv_file)
                loaded_any = True
            except Exception as e:
                print(f"[WARN] Failed to load topography CSV {csv_file.name}: {e}")

        self._loaded = loaded_any
        if loaded_any:
            print(f"[INFO] TopographyResolver loaded {len(self._all_entries)} entries, "
                  f"{len(self._code_to_entries)} unique codes")
        return loaded_any

    def _load_csv(self, csv_path: Path) -> None:
        source = csv_path.stem  # e.g. "sarc_topography"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # sarc format: Subsite, ICD-O-3, Site, Group, Macrogrouping
                # hnc format:  SITE, Sub-site, icdo3_code
                subsite = (row.get("Subsite") or row.get("Sub-site") or "").strip()
                code = (row.get("ICD-O-3") or row.get("icdo3_code") or "").strip()
                site = (row.get("Site") or row.get("SITE") or "").strip()
                group = (row.get("Group") or "").strip()
                macrogrouping = (row.get("Macrogrouping") or "").strip()

                if not subsite or not code:
                    continue

                # Some codes have ranges like "C38.1-38.8" or trailing spaces
                # Extract a single Cxx.x code when possible
                single_code = self._normalise_code(code)
                if not single_code:
                    continue

                entry = {
                    "subsite": subsite,
                    "code": single_code,
                    "code_raw": code,
                    "site": site,
                    "group": group,
                    "macrogrouping": macrogrouping,
                    "source": source,
                }

                self._all_entries.append(entry)

                # Index by normalised text
                norm = self._normalise_text(subsite)
                self._text_to_entries.setdefault(norm, []).append(entry)

                # Also index by site name (broader category)
                if site:
                    site_norm = self._normalise_text(site)
                    self._text_to_entries.setdefault(site_norm, []).append(entry)

                # Index by code
                self._code_to_entries.setdefault(single_code, []).append(entry)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_text(self, text: str) -> Optional[dict]:
        """
        Resolve a tumor site description to its best topography entry.

        Returns the entry dict with keys: subsite, code, site, group, ...
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

        # Strategy 2: substring match — check if any known subsite is
        # contained in the input or vice-versa.
        best_match: Optional[dict] = None
        best_score = 0.0
        for key, entries in self._text_to_entries.items():
            score = self._fuzzy_score(norm, key)
            if score > best_score and score >= 0.6:
                best_score = score
                best_match = entries[0]

        return best_match

    def resolve_code(self, code: str) -> Optional[dict]:
        """Resolve a topography code to its entry."""
        self._ensure_loaded()
        code = code.strip().upper()
        entries = self._code_to_entries.get(code)
        return entries[0] if entries else None

    def get_all_entries(self) -> List[dict]:
        """Return all loaded topography entries (for prompt enrichment)."""
        self._ensure_loaded()
        return self._all_entries

    def get_prompt_reference_lines(self, max_lines: int = 80) -> str:
        """
        Build a compact reference string for injection into LLM prompts.

        Format: "Subsite — Cxx.x" per line, deduplicated by (subsite, code).
        """
        self._ensure_loaded()
        seen = set()
        lines = []
        for entry in self._all_entries:
            key = (self._normalise_text(entry["subsite"]), entry["code"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"{entry['subsite']} — {entry['code']}")
            if len(lines) >= max_lines:
                break
        return "\n".join(lines)

    def enrich_prompt_options(self, prompt_options_text: str) -> str:
        """
        Take the 'Possible Output Options' block from a tumorsite prompt and
        append '(ICD-O-3: Cxx.x)' to each line where the site text matches.

        E.g.: 'Tumor site (Upper and Lower limbs): Upper leg.'
           → 'Tumor site (Upper and Lower limbs): Upper leg (ICD-O-3: C49.2).'
        """
        self._ensure_loaded()
        enriched_lines = []
        for line in prompt_options_text.split("\n"):
            enriched_lines.append(self._enrich_single_line(line))
        return "\n".join(enriched_lines)

    def _enrich_single_line(self, line: str) -> str:
        """Add ICD-O-3 code to a single prompt option line if possible."""
        # Match pattern: Tumor site (Category): Site.
        m = re.match(
            r"^(Tumor site\s*\([^)]*\)\s*:\s*)(.+?)(\s*\.?\s*)$",
            line.strip(),
        )
        if not m:
            return line

        site_text = m.group(2).strip()
        # Skip if already has a code
        if "ICD-O-3:" in site_text or re.search(r"C\d{2}\.\d", site_text):
            return line

        entry = self.resolve_text(site_text)
        if entry:
            return f"{m.group(1)}{site_text} (ICD-O-3: {entry['code']}).".rstrip()

        return line

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    @staticmethod
    def _normalise_code(raw: str) -> Optional[str]:
        """Extract a single Cxx.x code from possibly messy input."""
        raw = raw.strip()
        # Direct match
        m = re.match(r"^(C\d{2}\.\d)\s*$", raw, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        # First code in a range like "C38.1-38.8" or "C53-C54-C55"
        m = re.search(r"(C\d{2}\.\d)", raw, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        # Code without dot like "C490" → "C49.0"
        m = re.match(r"^(C\d{2})(\d)\s*$", raw, re.IGNORECASE)
        if m:
            return f"{m.group(1).upper()}.{m.group(2)}"
        return None

    @staticmethod
    def _normalise_text(text: str) -> str:
        """Lowercase, strip, collapse whitespace, remove punctuation."""
        text = text.lower().strip()
        text = re.sub(r"[,;()\[\]\"']", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        # Remove trailing NOS
        text = re.sub(r"\s*nos\s*$", "", text)
        return text

    @staticmethod
    def _fuzzy_score(a: str, b: str) -> float:
        """Simple token-overlap score between two normalised strings."""
        if not a or not b:
            return 0.0
        # Exact match
        if a == b:
            return 1.0
        # One contains the other
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


def get_topography_resolver(condition_dir: Optional[Path] = None) -> TopographyResolver:
    """Get or create the global TopographyResolver singleton."""
    global _resolver
    if _resolver is None:
        _resolver = TopographyResolver(condition_dir)
        _resolver.load()
    return _resolver


def reset_resolver():
    """Reset singleton (for testing)."""
    global _resolver
    _resolver = None
