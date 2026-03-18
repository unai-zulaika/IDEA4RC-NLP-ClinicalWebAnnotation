"""
Patient-level ICD-O-3 Diagnosis Resolver

Resolves ICD-O-3 diagnosis codes at the patient level by combining
histology (morphology) and topography codes across all notes for each patient.
"""

import re
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path


def _enrich_code_label(code: str, description: str, code_type: str) -> str:
    """
    Return an individual label from condition files, falling back to the
    annotation's own description if not found.
    """
    try:
        from lib.condition_label_loader import get_condition_labels
        loader = get_condition_labels()
        if loader is not None:
            if code_type == 'histology':
                label = loader.get_morphology_label(code)
            else:
                label = loader.get_topography_label(code)
            if label:
                return label
    except Exception:
        pass
    return description


def _classify_prompt_type(prompt_type: str) -> Optional[str]:
    """
    Classify a prompt type as histology, topography, or neither.

    Prompt keys across centers:
      - histological-tipo-int, histological-msci, histological-vgr
      - tumorsite-int, tumorsite-msci, tumorsite-vgr

    Returns:
        "histology", "topography", or None
    """
    pt = prompt_type.lower()
    if 'histolog' in pt or 'tipo' in pt:
        return 'histology'
    if 'tumorsite' in pt or 'tumor-site' in pt:
        return 'topography'
    if 'site' in pt and 'tumor' in pt:
        return 'topography'
    return None


def _extract_site_text(text: str) -> Optional[str]:
    """Extract the site description from a tumor site annotation."""
    stripped = text.strip()
    # Guard: reject raw JSON blobs (unparsed structured output)
    if stripped.startswith('{') or stripped.startswith('['):
        return None
    # "Tumor site (Category): Site." → "Site"
    m = re.search(
        r'Tumor site\s*(?:\([^)]*\))?\s*:\s*(.+?)(?:\s*\(ICD-O-3.*?\))?\s*\.?\s*$',
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return stripped.rstrip('.')


def _extract_site_category(text: str) -> Optional[str]:
    """Extract the category from a tumor site annotation.

    "Tumor site (Upper and Lower limbs): Left thigh." → "Upper and Lower limbs"
    """
    m = re.search(
        r'Tumor site\s*\(([^)]+)\)',
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


def _extract_code_from_annotation(ann: dict, classification: str) -> Optional[str]:
    """
    Extract ICD-O-3 code from annotation text (primary) with fallback to
    icdo3_code field.  This avoids the bug where CSV candidate selection
    overwrites the correct code that the LLM originally extracted.
    """
    annotation_text = ann.get('annotation_text', '') or ''

    if classification == 'histology':
        # Primary: regex extract morphology code from annotation text
        match = re.search(r'(\d{4}/\d)', annotation_text)
        if match:
            return match.group(1)
        # Fallback: icdo3_code field
        icdo3 = ann.get('icdo3_code')
        if icdo3 and isinstance(icdo3, dict):
            return (icdo3.get('morphology_code') or '').strip() or None

    elif classification == 'topography':
        # Primary: regex extract topography code from annotation text
        match = re.search(r'(C\d{2}\.\d)', annotation_text)
        if match:
            return match.group(1)
        # Secondary: resolve site text via TopographyResolver
        try:
            from lib.topography_resolver import get_topography_resolver
            resolver = get_topography_resolver()
            site_text = _extract_site_text(annotation_text)
            if site_text:
                # Try original text first
                entry = resolver.resolve_text(site_text)
                if not entry:
                    # Strip laterality (left/right/bilateral) and retry
                    clean = re.sub(
                        r'\b(left|right|bilateral|izquierd[oa]|derech[oa])\b',
                        '', site_text, flags=re.IGNORECASE,
                    ).strip()
                    if clean and clean != site_text:
                        entry = resolver.resolve_text(clean)
                if not entry:
                    # Try the category hint (e.g. "Upper and Lower limbs")
                    category = _extract_site_category(annotation_text)
                    if category:
                        # Split compound categories like "Upper and Lower limbs"
                        for part in re.split(r'\s+and\s+', category):
                            part = part.strip()
                            if part:
                                entry = resolver.resolve_text(part)
                                if entry:
                                    break
                if entry:
                    return entry['code']
        except Exception:
            pass
        # No fallback to icdo3_code for topography — it's often overridden
        # by wrong CSV candidate matches. Better to show "needs review" than
        # a wrong code. User resolves manually in Patient Diagnosis Panel.

    return None


class DiagnosisResolver:
    """Resolves patient-level ICD-O-3 codes from per-note annotations."""

    def resolve_session(
        self,
        session: Dict[str, Any],
        preserve_manual: bool = True
    ) -> Dict[str, Dict[str, Any]]:
        """
        Resolve diagnosis codes for all patients in a session.

        Groups notes by p_id, collects histology/topography ICD-O-3 codes,
        detects conflicts, and auto-combines when exactly one of each exists.

        Args:
            session: Full session dict (notes, annotations, etc.)
            preserve_manual: If True, don't overwrite manually_resolved entries

        Returns:
            Dict keyed by patient_id -> PatientDiagnosisInfo-like dict
        """
        notes = session.get('notes', [])
        annotations = session.get('annotations', {})
        existing = session.get('patient_diagnoses', {}) if preserve_manual else {}

        # Group notes by patient_id
        patient_notes: Dict[str, List[Dict]] = {}
        for note in notes:
            pid = note.get('p_id', '')
            if not pid:
                continue
            patient_notes.setdefault(pid, []).append(note)

        results: Dict[str, Dict[str, Any]] = {}
        for pid, p_notes in patient_notes.items():
            # Preserve manually resolved entries
            if preserve_manual and pid in existing:
                ex = existing[pid]
                if isinstance(ex, dict) and ex.get('status') == 'manually_resolved':
                    results[pid] = ex
                    continue

            results[pid] = self._resolve_patient(pid, p_notes, annotations)

        return results

    def _resolve_patient(
        self,
        patient_id: str,
        notes: List[Dict],
        annotations: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve diagnosis for a single patient."""
        histology_codes: Dict[str, Dict[str, Any]] = {}   # code -> {note_id, description}
        topography_codes: Dict[str, Dict[str, Any]] = {}  # code -> {note_id, description}

        for note in notes:
            note_id = note.get('note_id', '')
            if not note_id:
                continue
            note_annotations = annotations.get(note_id, {})
            if not isinstance(note_annotations, dict):
                continue

            for prompt_type, ann in note_annotations.items():
                if not isinstance(ann, dict):
                    continue
                classification = _classify_prompt_type(prompt_type)
                if classification is None:
                    continue

                # Skip annotations flagged with HIGH severity hallucination
                hallucination_flags = ann.get('hallucination_flags', [])
                if isinstance(hallucination_flags, list) and any(
                    isinstance(f, dict) and f.get('severity') == 'high'
                    for f in hallucination_flags
                ):
                    continue

                # Extract code from annotation text (primary) with fallback
                code = _extract_code_from_annotation(ann, classification)
                if not code:
                    continue

                if classification == 'histology':
                    if code not in histology_codes:
                        icdo3 = ann.get('icdo3_code') or {}
                        raw_desc = (icdo3.get('description', '') if isinstance(icdo3, dict) else '') or ''
                        histology_codes[code] = {
                            'code': code,
                            'note_id': note_id,
                            'description': _enrich_code_label(code, raw_desc, 'histology'),
                            'prompt_type': prompt_type,
                        }
                elif classification == 'topography':
                    if code not in topography_codes:
                        # Use the site text from annotation as description
                        annotation_text = ann.get('annotation_text', '') or ''
                        site_desc = _extract_site_text(annotation_text) or ''
                        if not site_desc:
                            icdo3 = ann.get('icdo3_code') or {}
                            raw = (icdo3.get('description', '') if isinstance(icdo3, dict) else '') or ''
                            # Guard: reject long/JSON descriptions (likely unparsed output)
                            site_desc = raw if raw and len(raw) < 200 and not raw.strip().startswith('{') else ''
                        topography_codes[code] = {
                            'code': code,
                            'note_id': note_id,
                            'description': site_desc or _enrich_code_label(code, '', 'topography'),
                            'prompt_type': prompt_type,
                        }

        hist_list = list(histology_codes.values())
        topo_list = list(topography_codes.values())

        has_hist = len(hist_list) > 0
        has_topo = len(topo_list) > 0

        # No diagnosis annotations at all → skip
        if not has_hist and not has_topo:
            return {
                'patient_id': patient_id,
                'status': 'skipped',
                'review_reasons': [],
                'histology_codes': [],
                'topography_codes': [],
                'resolved_code': None,
                'csv_id': None,
                'resolved_at': None,
                'resolved_by': None,
            }

        # Check for missing or conflicting codes
        review_reasons: List[str] = []

        if has_hist and not has_topo:
            review_reasons.append('Missing topography/tumor site code')
        elif has_topo and not has_hist:
            review_reasons.append('Missing histology code')

        if len(hist_list) > 1:
            codes_str = ', '.join(h['code'] for h in hist_list)
            review_reasons.append(f'Multiple conflicting histology codes: {codes_str}')
        if len(topo_list) > 1:
            codes_str = ', '.join(t['code'] for t in topo_list)
            review_reasons.append(f'Multiple conflicting topography codes: {codes_str}')

        if review_reasons:
            return {
                'patient_id': patient_id,
                'status': 'needs_review',
                'review_reasons': review_reasons,
                'histology_codes': hist_list,
                'topography_codes': topo_list,
                'resolved_code': None,
                'csv_id': None,
                'resolved_at': None,
                'resolved_by': None,
            }

        # Exactly one of each → try auto-combine via CSV
        morphology = hist_list[0]['code']
        topography = topo_list[0]['code']

        return self._auto_combine(patient_id, morphology, topography, hist_list, topo_list)

    def _auto_combine(
        self,
        patient_id: str,
        morphology: str,
        topography: str,
        hist_list: List[Dict],
        topo_list: List[Dict],
    ) -> Dict[str, Any]:
        """Attempt auto-combination by looking up morphology-topography in CSV."""
        from lib.icdo3_csv_indexer import get_csv_indexer

        indexer = get_csv_indexer()
        if indexer is None:
            return {
                'patient_id': patient_id,
                'status': 'needs_review',
                'review_reasons': ['ICD-O-3 CSV indexer not available'],
                'histology_codes': hist_list,
                'topography_codes': topo_list,
                'resolved_code': None,
                'csv_id': None,
                'resolved_at': None,
                'resolved_by': None,
            }

        validation = indexer.validate_combination(morphology, topography)

        if not validation.get('valid', False):
            return {
                'patient_id': patient_id,
                'status': 'needs_review',
                'review_reasons': [
                    f'Combination {morphology}-{topography} not found in diagnosis codes CSV'
                ],
                'histology_codes': hist_list,
                'topography_codes': topo_list,
                'resolved_code': None,
                'csv_id': None,
                'resolved_at': None,
                'resolved_by': None,
            }

        query_code = validation['query_code']
        name = validation.get('name', '')
        row_data = validation.get('row_data', {})
        csv_id = str(row_data.get('ID', '')) if row_data else None

        resolved_code = {
            'query_code': query_code,
            'morphology_code': morphology,
            'topography_code': topography,
            'name': name,
            'source': 'auto',
            'user_selected': False,
            'validation': {
                'morphology_valid': True,
                'topography_valid': True,
                'combination_valid': True,
            },
            'created_at': datetime.now(timezone.utc).isoformat(),
        }

        return {
            'patient_id': patient_id,
            'status': 'auto_resolved',
            'review_reasons': [],
            'histology_codes': hist_list,
            'topography_codes': topo_list,
            'resolved_code': resolved_code,
            'csv_id': csv_id,
            'resolved_at': datetime.now(timezone.utc).isoformat(),
            'resolved_by': 'auto',
        }

    @staticmethod
    def resolve_manual(
        query_code: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Manually resolve a patient diagnosis by selecting a query_code.
        Validates against the CSV and returns resolved_code + csv_id.

        Returns None if the code is invalid.
        """
        from lib.icdo3_csv_indexer import get_csv_indexer

        indexer = get_csv_indexer()
        if indexer is None:
            return None

        query_code = query_code.strip()
        if query_code not in indexer.query_index:
            return None

        row = indexer.query_index[query_code]
        morphology = str(row.get('Morphology', '')).strip()
        topography = str(row.get('Topography', '')).strip()
        name = str(row.get('NAME', '')).strip()
        csv_id = str(row.get('ID', '')).strip()

        resolved_code = {
            'query_code': query_code,
            'morphology_code': morphology,
            'topography_code': topography,
            'name': name,
            'source': 'user_override',
            'user_selected': True,
            'validation': {
                'morphology_valid': True,
                'topography_valid': True,
                'combination_valid': True,
            },
            'created_at': datetime.now(timezone.utc).isoformat(),
        }

        return {
            'resolved_code': resolved_code,
            'csv_id': csv_id,
        }
