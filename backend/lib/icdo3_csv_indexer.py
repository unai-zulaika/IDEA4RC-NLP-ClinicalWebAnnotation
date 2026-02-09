"""
ICD-O-3 CSV Indexer

This module loads and indexes the diagnosis codes CSV file for fast lookup.
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import re
import json
from collections import defaultdict


class ICDO3CSVIndexer:
    """Indexer for ICD-O-3 diagnosis codes CSV"""
    
    def __init__(self, csv_path: Path):
        """Initialize indexer with CSV path"""
        self.csv_path = csv_path
        self.df: Optional[pd.DataFrame] = None
        self.query_index: Dict[str, Dict[str, Any]] = {}
        self.morphology_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.topography_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.name_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._loaded = False
    
    def load(self) -> bool:
        """Load CSV file and build indexes"""
        if self._loaded:
            return True
        
        if not self.csv_path.exists():
            print(f"[WARN] CSV file not found: {self.csv_path}")
            return False
        
        try:
            print(f"[INFO] Loading ICD-O-3 diagnosis codes CSV from {self.csv_path}...")
            # Read CSV with semicolon delimiter (as seen in the file)
            self.df = pd.read_csv(
                self.csv_path,
                delimiter=',',
                dtype=str,
                keep_default_na=False
            )
            print(f"[INFO] Loaded {len(self.df)} rows from CSV")
            
            # Build indexes
            self._build_indexes()
            self._loaded = True
            print(f"[INFO] Built indexes: {len(self.query_index)} query codes, "
                  f"{len(self.morphology_index)} morphology codes, "
                  f"{len(self.topography_index)} topography codes")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load CSV: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _build_indexes(self):
        """Build lookup indexes from DataFrame"""
        if self.df is None:
            return
        
        for _, row in self.df.iterrows():
            query_code = str(row.get('Query', '')).strip()
            morphology = str(row.get('Morphology', '')).strip()
            topography = str(row.get('Topography', '')).strip()
            name = str(row.get('NAME', '')).strip()
            
            # Convert row to dict for easy access
            row_dict = row.to_dict()
            
            # Query index (exact match)
            if query_code:
                self.query_index[query_code] = row_dict
            
            # Morphology index
            if morphology:
                self.morphology_index[morphology].append(row_dict)
            
            # Topography index
            if topography:
                self.topography_index[topography].append(row_dict)
            
            # Name index (normalized for text matching)
            if name:
                normalized_name = self._normalize_text(name)
                if normalized_name:
                    self.name_index[normalized_name].append(row_dict)
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching: lowercase, remove punctuation"""
        if not text:
            return ""
        # Convert to lowercase
        text = text.lower()
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def find_matching_code(
        self,
        histology_text: Optional[str] = None,
        topography_text: Optional[str] = None,
        morphology_code: Optional[str] = None,
        topography_code: Optional[str] = None,
        query_code: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], float, str]:
        """
        Find matching code in CSV indexes.
        
        Args:
            histology_text: Histology description text
            topography_text: Topography/site description text
            morphology_code: Morphology code (e.g., "8940/0")
            topography_code: Topography code (e.g., "C00.2")
            query_code: Full query code (e.g., "8940/0-C00.2")
        
        Returns:
            Tuple of (matched_row_dict, match_score, match_method)
            - matched_row_dict: Dictionary with row data or None
            - match_score: Confidence score (0.0-1.0)
            - match_method: How the match was found ("exact", "combined", "morphology_text", "text", "partial")
        """
        if not self._loaded:
            if not self.load():
                return None, 0.0, "error"
        
        # Strategy 1: Exact query code match
        if query_code:
            if query_code in self.query_index:
                return self.query_index[query_code], 1.0, "exact"
        
        # Strategy 2: Combined morphology + topography code match
        if morphology_code and topography_code:
            # Find rows that match both
            morph_matches = self.morphology_index.get(morphology_code, [])
            topo_matches = self.topography_index.get(topography_code, [])
            
            # Find intersection
            morph_set = {id(row) for row in morph_matches}
            topo_set = {id(row) for row in topo_matches}
            combined_matches = [row for row in morph_matches if id(row) in topo_set]
            
            if combined_matches:
                # Return first match (could be enhanced with scoring)
                return combined_matches[0], 0.9, "combined"
        
        # Strategy 3: Morphology code + topography text match
        if morphology_code and topography_text:
            morph_matches = self.morphology_index.get(morphology_code, [])
            if morph_matches:
                # Try to find best match by text similarity
                normalized_topo = self._normalize_text(topography_text)
                best_match = self._find_best_text_match(morph_matches, normalized_topo, "topography")
                if best_match:
                    return best_match, 0.7, "morphology_text"
        
        # Strategy 4: Text-only matching on NAME column
        if histology_text or topography_text:
            # Search in name index
            search_terms = []
            if histology_text:
                search_terms.append(self._normalize_text(histology_text))
            if topography_text:
                search_terms.append(self._normalize_text(topography_text))
            
            if search_terms:
                # Find rows where NAME contains search terms
                matches = []
                for term in search_terms:
                    if term:
                        # Search in name index (simple substring match)
                        for normalized_name, rows in self.name_index.items():
                            if term in normalized_name or normalized_name in term:
                                matches.extend(rows)
                
                if matches:
                    # Return first match (could be enhanced with scoring)
                    return matches[0], 0.5, "text"
        
        # Strategy 5: Partial match (morphology only or topography only)
        if morphology_code:
            morph_matches = self.morphology_index.get(morphology_code, [])
            if morph_matches:
                return morph_matches[0], 0.3, "partial_morphology"
        
        if topography_code:
            topo_matches = self.topography_index.get(topography_code, [])
            if topo_matches:
                return topo_matches[0], 0.3, "partial_topography"
        
        return None, 0.0, "no_match"
    
    def _find_best_text_match(
        self,
        candidates: List[Dict[str, Any]],
        search_text: str,
        field: str = "NAME"
    ) -> Optional[Dict[str, Any]]:
        """Find best text match from candidates"""
        if not candidates or not search_text:
            return None

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            candidate_text = str(candidate.get(field, "")).lower()
            # Simple substring matching score
            if search_text in candidate_text:
                score = len(search_text) / len(candidate_text) if candidate_text else 0.0
                if score > best_score:
                    best_score = score
                    best_match = candidate

        return best_match if best_score > 0.0 else None

    def _score_text_similarity(self, search_text: str, candidate_text: str) -> float:
        """Calculate fuzzy text match score between search text and candidate text"""
        from difflib import SequenceMatcher

        if not search_text or not candidate_text:
            return 0.0

        search_norm = self._normalize_text(search_text)
        text_norm = self._normalize_text(candidate_text)

        if not search_norm or not text_norm:
            return 0.0

        # Exact substring match gets high score
        if search_norm in text_norm:
            return 0.85 + (0.1 * len(search_norm) / len(text_norm))

        if text_norm in search_norm:
            return 0.75 + (0.1 * len(text_norm) / len(search_norm))

        # Fuzzy match using SequenceMatcher
        ratio = SequenceMatcher(None, search_norm, text_norm).ratio()
        return ratio * 0.7

    def search_by_text(
        self,
        query: str,
        morphology_filter: Optional[str] = None,
        topography_filter: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search ICD-O-3 codes by text (name or code substring).

        Args:
            query: Search query (searches NAME column and codes)
            morphology_filter: Optional morphology code prefix to filter results
            topography_filter: Optional topography code prefix to filter results
            limit: Maximum number of results to return

        Returns:
            List of dicts with query_code, morphology_code, topography_code, name, match_score
        """
        if not self._loaded:
            if not self.load():
                return []

        if not query or not query.strip():
            return []

        query = query.strip()
        query_lower = query.lower()
        query_norm = self._normalize_text(query)

        results = []
        seen_codes = set()

        if self.df is None:
            return []

        for _, row in self.df.iterrows():
            query_code = str(row.get('Query', '')).strip()
            morphology = str(row.get('Morphology', '')).strip()
            topography = str(row.get('Topography', '')).strip()
            name = str(row.get('NAME', '')).strip()

            if not query_code:
                continue

            # Skip if already seen
            if query_code in seen_codes:
                continue

            # Apply filters
            if morphology_filter and not morphology.startswith(morphology_filter):
                continue
            if topography_filter and not topography.startswith(topography_filter):
                continue

            # Calculate match score
            score = 0.0

            # Exact code match (highest priority)
            if query_code.lower() == query_lower:
                score = 1.0
            elif morphology.lower() == query_lower or topography.lower() == query_lower:
                score = 0.95
            # Code contains query
            elif query_lower in query_code.lower():
                score = 0.85
            elif query_lower in morphology.lower() or query_lower in topography.lower():
                score = 0.8
            # Name matching
            else:
                name_lower = name.lower()
                name_norm = self._normalize_text(name)

                # Exact name match
                if query_lower == name_lower:
                    score = 0.9
                # Name starts with query
                elif name_lower.startswith(query_lower):
                    score = 0.75
                # Query in name (substring)
                elif query_lower in name_lower:
                    # Score based on how much of the name the query covers
                    score = 0.5 + (0.2 * len(query) / len(name))
                # Normalized text match
                elif query_norm and query_norm in name_norm:
                    score = 0.45 + (0.15 * len(query_norm) / len(name_norm))
                # Word-level matching
                else:
                    query_words = set(query_lower.split())
                    name_words = set(name_lower.split())
                    if query_words:
                        common_words = query_words.intersection(name_words)
                        if common_words:
                            score = 0.3 * (len(common_words) / len(query_words))

            if score > 0:
                seen_codes.add(query_code)
                results.append({
                    'query_code': query_code,
                    'morphology_code': morphology,
                    'topography_code': topography,
                    'name': name,
                    'match_score': score
                })

        # Sort by score descending
        results.sort(key=lambda x: x['match_score'], reverse=True)

        return results[:limit]

    def validate_combination(
        self,
        morphology: str,
        topography: str
    ) -> Dict[str, Any]:
        """
        Validate if a morphology + topography combination exists in the CSV.

        Args:
            morphology: Morphology code (e.g., "8031/3")
            topography: Topography code (e.g., "C00.2")

        Returns:
            Dict with validation status and matched row data
        """
        if not self._loaded:
            if not self.load():
                return {
                    'valid': False,
                    'query_code': None,
                    'name': None,
                    'morphology_valid': False,
                    'topography_valid': False,
                    'error': 'CSV not loaded'
                }

        morphology = morphology.strip() if morphology else ''
        topography = topography.strip() if topography else ''

        # Check if individual codes exist
        morphology_valid = morphology in self.morphology_index if morphology else False
        topography_valid = topography in self.topography_index if topography else False

        # Try to find the combination
        combined_key = f"{morphology}-{topography}" if morphology and topography else None

        if combined_key and combined_key in self.query_index:
            row = self.query_index[combined_key]
            return {
                'valid': True,
                'query_code': combined_key,
                'name': row.get('NAME', ''),
                'morphology_valid': True,
                'topography_valid': True,
                'row_data': row
            }

        # Combination doesn't exist as-is, try to find matching row
        if morphology and topography:
            morph_matches = self.morphology_index.get(morphology, [])
            for row in morph_matches:
                if str(row.get('Topography', '')).strip() == topography:
                    return {
                        'valid': True,
                        'query_code': str(row.get('Query', '')).strip(),
                        'name': str(row.get('NAME', '')).strip(),
                        'morphology_valid': True,
                        'topography_valid': True,
                        'row_data': row
                    }

        return {
            'valid': False,
            'query_code': None,
            'name': None,
            'morphology_valid': morphology_valid,
            'topography_valid': topography_valid
        }

    def get_valid_topographies_for_morphology(
        self,
        morphology: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get all valid topography codes for a given morphology code.

        Args:
            morphology: Morphology code (e.g., "8031/3")
            limit: Maximum number of results

        Returns:
            List of dicts with topography_code, query_code, and name
        """
        if not self._loaded:
            if not self.load():
                return []

        morphology = morphology.strip() if morphology else ''
        if not morphology:
            return []

        results = []
        seen_topographies = set()

        morph_matches = self.morphology_index.get(morphology, [])
        for row in morph_matches:
            topography = str(row.get('Topography', '')).strip()
            if topography and topography not in seen_topographies:
                seen_topographies.add(topography)
                results.append({
                    'topography_code': topography,
                    'query_code': str(row.get('Query', '')).strip(),
                    'name': str(row.get('NAME', '')).strip()
                })

        # Sort alphabetically by topography code
        results.sort(key=lambda x: x['topography_code'])

        return results[:limit]

    def get_valid_morphologies_for_topography(
        self,
        topography: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get all valid morphology codes for a given topography code.

        Args:
            topography: Topography code (e.g., "C00.2")
            limit: Maximum number of results

        Returns:
            List of dicts with morphology_code, query_code, and name
        """
        if not self._loaded:
            if not self.load():
                return []

        topography = topography.strip() if topography else ''
        if not topography:
            return []

        results = []
        seen_morphologies = set()

        topo_matches = self.topography_index.get(topography, [])
        for row in topo_matches:
            morphology = str(row.get('Morphology', '')).strip()
            if morphology and morphology not in seen_morphologies:
                seen_morphologies.add(morphology)
                results.append({
                    'morphology_code': morphology,
                    'query_code': str(row.get('Query', '')).strip(),
                    'name': str(row.get('NAME', '')).strip()
                })

        # Sort alphabetically by morphology code
        results.sort(key=lambda x: x['morphology_code'])

        return results[:limit]

    def find_top_candidates(
        self,
        histology_text: Optional[str] = None,
        topography_text: Optional[str] = None,
        morphology_code: Optional[str] = None,
        topography_code: Optional[str] = None,
        query_code: Optional[str] = None,
        n: int = 5
    ) -> List[Tuple[Dict[str, Any], float, str]]:
        """
        Find top N matching codes from CSV indexes, ranked by score.

        Args:
            histology_text: Histology description text (from LLM extraction)
            topography_text: Topography/site description text (from LLM extraction)
            morphology_code: Morphology code (e.g., "8940/0")
            topography_code: Topography code (e.g., "C00.2")
            query_code: Full query code (e.g., "8940/0-C00.2")
            n: Number of candidates to return (default 5)

        Returns:
            List of tuples (matched_row_dict, match_score, match_method)
            sorted by match_score descending, limited to n results
        """
        if not self._loaded:
            if not self.load():
                return []

        # Collect all potential matches with scores
        candidates_dict: Dict[str, Tuple[Dict[str, Any], float, str]] = {}

        # Strategy 1: Exact query code match (score: 1.0)
        if query_code and query_code in self.query_index:
            row = self.query_index[query_code]
            candidates_dict[query_code] = (row, 1.0, "exact")

        # Strategy 2: Combined morphology + topography code match (score: 0.9)
        if morphology_code and topography_code:
            morph_matches = self.morphology_index.get(morphology_code, [])
            for row in morph_matches:
                if str(row.get('Topography', '')).strip() == topography_code:
                    key = str(row.get('Query', ''))
                    if key and key not in candidates_dict:
                        candidates_dict[key] = (row, 0.9, "combined")

        # Strategy 3: Morphology code only match (score: 0.6-0.75)
        if morphology_code:
            morph_matches = self.morphology_index.get(morphology_code, [])
            for row in morph_matches:
                key = str(row.get('Query', ''))
                if key and key not in candidates_dict:
                    # Score higher if topography text matches
                    base_score = 0.6
                    if topography_text:
                        name = str(row.get('NAME', ''))
                        text_score = self._score_text_similarity(topography_text, name)
                        base_score = max(base_score, 0.6 + text_score * 0.15)
                    candidates_dict[key] = (row, min(base_score, 0.75), "morphology")

        # Strategy 4: Topography code only match (score: 0.5-0.65)
        if topography_code:
            topo_matches = self.topography_index.get(topography_code, [])
            for row in topo_matches:
                key = str(row.get('Query', ''))
                if key and key not in candidates_dict:
                    # Score higher if histology text matches
                    base_score = 0.5
                    if histology_text:
                        name = str(row.get('NAME', ''))
                        text_score = self._score_text_similarity(histology_text, name)
                        base_score = max(base_score, 0.5 + text_score * 0.15)
                    candidates_dict[key] = (row, min(base_score, 0.65), "topography")

        # Strategy 5: Text-only matching on NAME column (score: 0.3-0.6)
        search_terms = []
        if histology_text:
            search_terms.append(histology_text)
        if topography_text:
            search_terms.append(topography_text)

        if search_terms and self.df is not None:
            for search_text in search_terms:
                search_norm = self._normalize_text(search_text)
                if not search_norm:
                    continue

                # Search through all rows for text matches
                for _, row in self.df.iterrows():
                    name = str(row.get('NAME', ''))
                    key = str(row.get('Query', ''))
                    if not key or key in candidates_dict:
                        continue

                    text_score = self._score_text_similarity(search_text, name)
                    if text_score >= 0.3:  # Minimum threshold
                        final_score = 0.3 + text_score * 0.3  # Scale to 0.3-0.6 range
                        row_dict = row.to_dict()
                        # Only add if better than existing or not present
                        if key not in candidates_dict or candidates_dict[key][1] < final_score:
                            candidates_dict[key] = (row_dict, min(final_score, 0.6), "text")

        # Sort by score descending and return top n
        sorted_candidates = sorted(
            candidates_dict.values(),
            key=lambda x: x[1],
            reverse=True
        )

        return sorted_candidates[:n]


# Global indexer instance (singleton pattern)
_indexer: Optional[ICDO3CSVIndexer] = None


def get_csv_indexer(csv_path: Optional[Path] = None) -> Optional[ICDO3CSVIndexer]:
    """
    Get or create global CSV indexer instance.
    
    Args:
        csv_path: Optional path to CSV file. If None, uses default from config.
    
    Returns:
        ICDO3CSVIndexer instance or None if CSV not found
    """
    global _indexer
    
    if _indexer is None:
        if csv_path is None:
            # Try to load from config
            backend_dir = Path(__file__).parent.parent
            try:
                config_path = backend_dir / "config" / "icdo3_config.json"
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                        csv_path_str = config.get('csv_path', '')
                        if csv_path_str:
                            # Handle relative paths
                            if csv_path_str.startswith('/'):
                                csv_path = Path(csv_path_str)
                            else:
                                csv_path = backend_dir / csv_path_str
                else:
                    # Default path: try backend/data first, then shared data directory
                    csv_path = backend_dir / "data" / "diagnosis_codes" / "diagnosis-codes-list.csv"
                    if not csv_path.exists():
                        csv_path = Path(__file__).parent.parent.parent / "data" / "diagnosis_codes" / "diagnosis-codes-list.csv"
            except Exception as e:
                print(f"[WARN] Failed to load config, using default path: {e}")
                csv_path = backend_dir / "data" / "diagnosis_codes" / "diagnosis-codes-list.csv"
                if not csv_path.exists():
                    csv_path = Path(__file__).parent.parent.parent / "data" / "diagnosis_codes" / "diagnosis-codes-list.csv"
        
        if csv_path and csv_path.exists():
            _indexer = ICDO3CSVIndexer(csv_path)
            _indexer.load()
        else:
            print(f"[WARN] CSV file not found at {csv_path}")
            return None
    
    return _indexer


def reset_indexer():
    """Reset global indexer (useful for testing or reloading)"""
    global _indexer
    _indexer = None
