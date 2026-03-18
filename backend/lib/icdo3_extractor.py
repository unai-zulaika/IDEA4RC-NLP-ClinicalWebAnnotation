"""
ICD-O-3 Code Extraction Service

This module provides functionality to extract ICD-O-3 codes from histology and site annotations.
Uses LLM-based extraction with CSV matching, pattern matching, and exact code extraction.
For tumor site prompts, also uses the TopographyResolver for condition-file-based lookup.
"""

import asyncio
import re
from typing import Optional, Dict, Any, List
from pathlib import Path
import json


# Module-level caches
_LOOKUP_TABLE_CACHE: Optional[Dict] = None

# Prompts that require ICD-O-3 code extraction
HISTOLOGY_SITE_PROMPTS = {
    'histological-tipo-int',
    'tumorsite-int',
    'histological-type-int',  # Alternative naming
    'tumor-site-int',  # Alternative naming
}

# No external dependencies - all extraction is done via LLM+CSV or pattern matching


def _is_site_prompt(prompt_type: str) -> bool:
    """Check if a prompt type is a tumor site prompt."""
    pt = prompt_type.lower()
    return 'tumorsite' in pt or ('site' in pt and 'tumor' in pt)


def _is_histology_prompt(prompt_type: str) -> bool:
    """Check if a prompt type is a histological type prompt."""
    pt = prompt_type.lower()
    return 'histolog' in pt


def is_histology_or_site_prompt(prompt_type: str) -> bool:
    """Check if a prompt type requires ICD-O-3 code extraction"""
    return prompt_type.lower() in HISTOLOGY_SITE_PROMPTS or \
           'histolog' in prompt_type.lower() or \
           'site' in prompt_type.lower() and 'tumor' in prompt_type.lower()


def extract_icdo3_from_text(
    text: str,
    prompt_type: str,
    note_text: Optional[str] = None,
    vllm_client: Optional[Any] = None,
    n_candidates: int = 5
) -> Optional[Dict[str, Any]]:
    """
    Extract ICD-O-3 code from annotation text with multiple candidates from CSV.

    CSV is always the source of truth. This function uses LLM to extract search
    terms, then queries CSV to get ranked candidates for user selection.

    Args:
        text: Annotation text containing histology/site information
        prompt_type: Type of prompt (to determine extraction strategy)
        note_text: Optional original note text (used for extraction if annotation doesn't contain enough info)
        vllm_client: Optional vLLM client for LLM-based extraction
        n_candidates: Number of candidates to return (default 5)

    Returns:
        Dictionary with ICD-O-3 code information including candidates array, or None if not found
    """
    if not text or not is_histology_or_site_prompt(prompt_type):
        return None

    # Check if annotation text contains placeholders indicating codes are missing
    has_placeholder = any(placeholder in text.lower() for placeholder in [
        '[select icd-o-3 code]',
        '[select icdo code]',
        '[select code]',
        'select icd-o-3',
        'select icdo',
        'icd-o-3 code',
        'icdo code'
    ])

    # If annotation has placeholder and we have note_text, prioritize note_text for extraction
    primary_extraction_text = note_text if (has_placeholder and note_text) else text

    # Strategy 1: Check for existing ICD-O-3 codes in text as search hint
    # Even if found, we still query CSV to get candidates
    existing_code = _extract_existing_code(text)
    if not existing_code and note_text:
        existing_code = _extract_existing_code(note_text)

    # For histology prompts, discard topography-only codes — they are irrelevant
    # and would cause Strategy 3 to return location-based instead of morphology-based results.
    if existing_code and _is_histology_prompt(prompt_type):
        if existing_code.get('topography_code') and not existing_code.get('morphology_code'):
            print(f"[INFO] Discarding topography-only code {existing_code['topography_code']} for histology prompt")
            existing_code = None

    # Strategy 1.5a: For site prompts, use TopographyResolver to resolve
    # the site text to a topography code from condition_files.
    # This is fast and deterministic — no LLM call needed.
    if _is_site_prompt(prompt_type) and not existing_code:
        topo_result = _resolve_topography_from_annotation(text)
        if topo_result:
            existing_code = topo_result
            print(f"[INFO] TopographyResolver matched site text → {topo_result['topography_code']}")

    # Strategy 1.5b: For histology prompts, use MorphologyResolver to resolve
    # the histology text to a morphology code from condition_files.
    if _is_histology_prompt(prompt_type) and not existing_code:
        morph_result = _resolve_morphology_from_annotation(text)
        if morph_result:
            existing_code = morph_result
            print(f"[INFO] MorphologyResolver matched histology text → {morph_result['morphology_code']}")

    # Strategy 2: Use LLM to extract search terms and get candidates from CSV
    # This is the primary strategy - CSV is the source of truth
    if vllm_client:
        try:
            extraction_note_text = primary_extraction_text if has_placeholder else note_text
            llm_csv_match = _extract_with_llm_and_csv_match(
                text,
                prompt_type,
                extraction_note_text,
                vllm_client,
                n_candidates=n_candidates
            )
            if llm_csv_match:
                llm_csv_match = _reconcile_with_existing_code(llm_csv_match, existing_code)
                print(f"[INFO] Extracted ICD-O-3 candidates from CSV: {len(llm_csv_match.get('candidates', []))} candidates, best: {llm_csv_match.get('query_code') or llm_csv_match.get('code')}")
                return llm_csv_match
        except Exception as e:
            print(f"[WARN] LLM+CSV extraction failed: {e}")
            import traceback
            traceback.print_exc()

    # Strategy 3: If LLM extraction failed but we found existing code, use it to search CSV
    if existing_code:
        try:
            from lib.icdo3_csv_indexer import get_csv_indexer
            csv_indexer = get_csv_indexer()
            if csv_indexer:
                # Use existing code to search for candidates
                candidates = csv_indexer.find_top_candidates(
                    morphology_code=existing_code.get('morphology_code'),
                    topography_code=existing_code.get('topography_code'),
                    query_code=existing_code.get('code') if '-' in (existing_code.get('code') or '') else None,
                    n=n_candidates
                )
                if candidates:
                    # Build response with candidates
                    candidate_list = []
                    for rank, (row, score, method) in enumerate(candidates, 1):
                        candidate_list.append({
                            'rank': rank,
                            'query_code': str(row.get('Query', '')),
                            'morphology_code': str(row.get('Morphology', '')),
                            'topography_code': str(row.get('Topography', '')),
                            'name': str(row.get('NAME', '')),
                            'match_score': score,
                            'match_method': method
                        })

                    best_row = candidates[0][0]
                    return {
                        'code': str(best_row.get('Query', '')) or existing_code.get('code'),
                        'query_code': str(best_row.get('Query', '')),
                        'morphology_code': str(best_row.get('Morphology', '')) or existing_code.get('morphology_code'),
                        'topography_code': str(best_row.get('Topography', '')) or existing_code.get('topography_code'),
                        'histology_code': existing_code.get('histology_code'),
                        'behavior_code': existing_code.get('behavior_code'),
                        'description': str(best_row.get('NAME', '')),
                        'confidence': candidates[0][1],
                        'match_method': f'code_csv_{candidates[0][2]}',
                        'match_score': candidates[0][1],
                        'candidates': candidate_list,
                        'selected_candidate_index': 0,
                        'user_selected': False
                    }
        except Exception as e:
            print(f"[WARN] CSV lookup with existing code failed: {e}")

        # Fallback: return existing code without candidates
        print(f"[INFO] Found existing ICD-O-3 code (no CSV candidates): {existing_code['code']}")
        existing_code['match_method'] = 'exact_no_csv'
        existing_code['match_score'] = 1.0
        existing_code['candidates'] = []
        existing_code['selected_candidate_index'] = 0
        existing_code['user_selected'] = False
        if 'query_code' not in existing_code:
            if existing_code.get('morphology_code') and existing_code.get('topography_code'):
                existing_code['query_code'] = f"{existing_code['morphology_code']}-{existing_code['topography_code']}"
        return existing_code

    # Strategy 4: Pattern-based extraction as last resort
    pattern_code = _extract_with_patterns(text, prompt_type)
    if pattern_code:
        print(f"[INFO] Extracted ICD-O-3 code from lookup table: {pattern_code['code']}")
        pattern_code['match_method'] = 'pattern'
        pattern_code['match_score'] = 0.5
        pattern_code['candidates'] = []
        pattern_code['selected_candidate_index'] = 0
        pattern_code['user_selected'] = False
        if 'query_code' not in pattern_code:
            if pattern_code.get('morphology_code') and pattern_code.get('topography_code'):
                pattern_code['query_code'] = f"{pattern_code['morphology_code']}-{pattern_code['topography_code']}"
        return pattern_code

    return None


async def extract_icdo3_from_text_async(
    text: str,
    prompt_type: str,
    note_text: Optional[str] = None,
    vllm_client: Optional[Any] = None,
    n_candidates: int = 5,
    icdo3_llm_cache: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Async version of extract_icdo3_from_text. Uses non-blocking LLM calls.

    Args:
        text: Annotation text containing histology/site information
        prompt_type: Type of prompt (to determine extraction strategy)
        note_text: Optional original note text
        vllm_client: Optional vLLM client for LLM-based extraction
        n_candidates: Number of candidates to return (default 5)
        icdo3_llm_cache: Optional shared cache dict keyed by note_text hash
            to avoid duplicate LLM calls for the same note across prompt types.

    Returns:
        Dictionary with ICD-O-3 code information including candidates array, or None
    """
    if not text or not is_histology_or_site_prompt(prompt_type):
        return None

    has_placeholder = any(placeholder in text.lower() for placeholder in [
        '[select icd-o-3 code]', '[select icdo code]', '[select code]',
        'select icd-o-3', 'select icdo', 'icd-o-3 code', 'icdo code'
    ])

    primary_extraction_text = note_text if (has_placeholder and note_text) else text

    existing_code = _extract_existing_code(text)
    if not existing_code and note_text:
        existing_code = _extract_existing_code(note_text)

    # For histology prompts, discard topography-only codes
    if existing_code and _is_histology_prompt(prompt_type):
        if existing_code.get('topography_code') and not existing_code.get('morphology_code'):
            print(f"[INFO] Discarding topography-only code {existing_code['topography_code']} for histology prompt")
            existing_code = None

    # Strategy 1.5a: For site prompts, use TopographyResolver
    if _is_site_prompt(prompt_type) and not existing_code:
        topo_result = _resolve_topography_from_annotation(text)
        if topo_result:
            existing_code = topo_result
            print(f"[INFO] TopographyResolver matched site text → {topo_result['topography_code']}")

    # Strategy 1.5b: For histology prompts, use MorphologyResolver
    if _is_histology_prompt(prompt_type) and not existing_code:
        morph_result = _resolve_morphology_from_annotation(text)
        if morph_result:
            existing_code = morph_result
            print(f"[INFO] MorphologyResolver matched histology text → {morph_result['morphology_code']}")

    # Strategy 2: Use async LLM to extract search terms and get candidates from CSV
    if vllm_client:
        try:
            extraction_note_text = primary_extraction_text if has_placeholder else note_text
            llm_csv_match = await _extract_with_llm_and_csv_match_async(
                text, prompt_type, extraction_note_text, vllm_client,
                n_candidates=n_candidates,
                icdo3_llm_cache=icdo3_llm_cache,
            )
            if llm_csv_match:
                llm_csv_match = _reconcile_with_existing_code(llm_csv_match, existing_code)
                print(f"[INFO] Extracted ICD-O-3 candidates from CSV: {len(llm_csv_match.get('candidates', []))} candidates, best: {llm_csv_match.get('query_code') or llm_csv_match.get('code')}")
                return llm_csv_match
        except Exception as e:
            print(f"[WARN] Async LLM+CSV extraction failed: {e}")
            import traceback
            traceback.print_exc()

    # Strategy 3: existing code → CSV lookup (same as sync, CPU-only)
    if existing_code:
        try:
            from lib.icdo3_csv_indexer import get_csv_indexer
            csv_indexer = get_csv_indexer()
            if csv_indexer:
                candidates = csv_indexer.find_top_candidates(
                    morphology_code=existing_code.get('morphology_code'),
                    topography_code=existing_code.get('topography_code'),
                    query_code=existing_code.get('code') if '-' in (existing_code.get('code') or '') else None,
                    n=n_candidates
                )
                if candidates:
                    candidate_list = []
                    for rank, (row, score, method) in enumerate(candidates, 1):
                        candidate_list.append({
                            'rank': rank,
                            'query_code': str(row.get('Query', '')),
                            'morphology_code': str(row.get('Morphology', '')),
                            'topography_code': str(row.get('Topography', '')),
                            'name': str(row.get('NAME', '')),
                            'match_score': score,
                            'match_method': method
                        })
                    best_row = candidates[0][0]
                    return {
                        'code': str(best_row.get('Query', '')) or existing_code.get('code'),
                        'query_code': str(best_row.get('Query', '')),
                        'morphology_code': str(best_row.get('Morphology', '')) or existing_code.get('morphology_code'),
                        'topography_code': str(best_row.get('Topography', '')) or existing_code.get('topography_code'),
                        'histology_code': existing_code.get('histology_code'),
                        'behavior_code': existing_code.get('behavior_code'),
                        'description': str(best_row.get('NAME', '')),
                        'confidence': candidates[0][1],
                        'match_method': f'code_csv_{candidates[0][2]}',
                        'match_score': candidates[0][1],
                        'candidates': candidate_list,
                        'selected_candidate_index': 0,
                        'user_selected': False
                    }
        except Exception as e:
            print(f"[WARN] CSV lookup with existing code failed: {e}")

        print(f"[INFO] Found existing ICD-O-3 code (no CSV candidates): {existing_code['code']}")
        existing_code['match_method'] = 'exact_no_csv'
        existing_code['match_score'] = 1.0
        existing_code['candidates'] = []
        existing_code['selected_candidate_index'] = 0
        existing_code['user_selected'] = False
        if 'query_code' not in existing_code:
            if existing_code.get('morphology_code') and existing_code.get('topography_code'):
                existing_code['query_code'] = f"{existing_code['morphology_code']}-{existing_code['topography_code']}"
        return existing_code

    # Strategy 4: Pattern-based extraction
    pattern_code = _extract_with_patterns(text, prompt_type)
    if pattern_code:
        print(f"[INFO] Extracted ICD-O-3 code from lookup table: {pattern_code['code']}")
        pattern_code['match_method'] = 'pattern'
        pattern_code['match_score'] = 0.5
        pattern_code['candidates'] = []
        pattern_code['selected_candidate_index'] = 0
        pattern_code['user_selected'] = False
        if 'query_code' not in pattern_code:
            if pattern_code.get('morphology_code') and pattern_code.get('topography_code'):
                pattern_code['query_code'] = f"{pattern_code['morphology_code']}-{pattern_code['topography_code']}"
        return pattern_code

    return None


async def _extract_with_llm_and_csv_match_async(
    text: str,
    prompt_type: str,
    note_text: Optional[str],
    vllm_client: Any,
    n_candidates: int = 5,
    icdo3_llm_cache: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Async version of _extract_with_llm_and_csv_match.
    Uses cache to avoid duplicate LLM calls for the same note text.
    """
    try:
        from lib.icdo3_llm_extractor import extract_histology_topography_with_llm_async
        from lib.icdo3_csv_indexer import get_csv_indexer

        # Check cache first to avoid redundant LLM calls.
        # Use asyncio.Lock to prevent duplicate calls under asyncio.gather.
        if icdo3_llm_cache is not None and note_text:
            cache_key = note_text[:200]  # use text prefix as stable key
            lock_key = f"_lock_{cache_key}"
            if lock_key not in icdo3_llm_cache:
                icdo3_llm_cache[lock_key] = asyncio.Lock()
            async with icdo3_llm_cache[lock_key]:
                if cache_key in icdo3_llm_cache:
                    extracted_info = icdo3_llm_cache[cache_key]
                    print(f"[INFO] ICD-O-3 LLM extraction cache hit for note (prompt_type={prompt_type})")
                else:
                    extracted_info = await extract_histology_topography_with_llm_async(
                        note_text=note_text or text,
                        annotation_text=text,
                        prompt_type=prompt_type,
                        vllm_client=vllm_client
                    )
                    icdo3_llm_cache[cache_key] = extracted_info
        else:
            extracted_info = await extract_histology_topography_with_llm_async(
                note_text=note_text or text,
                annotation_text=text,
                prompt_type=prompt_type,
                vllm_client=vllm_client
            )

        csv_indexer = get_csv_indexer()
        if not csv_indexer:
            print("[WARN] CSV indexer not available, cannot extract ICD-O-3 codes")
            return None

        candidates = csv_indexer.find_top_candidates(
            histology_text=extracted_info.get('histology_text') if extracted_info else None,
            topography_text=extracted_info.get('topography_text') if extracted_info else None,
            morphology_code=extracted_info.get('morphology_code') if extracted_info else None,
            topography_code=extracted_info.get('topography_code') if extracted_info else None,
            query_code=extracted_info.get('query_code') if extracted_info else None,
            n=n_candidates
        )

        if not candidates:
            print(f"[INFO] No CSV candidates found for extracted search terms")
            return None

        candidate_list = []
        for rank, (row, score, method) in enumerate(candidates, 1):
            candidate_list.append({
                'rank': rank,
                'query_code': str(row.get('Query', '')),
                'morphology_code': str(row.get('Morphology', '')),
                'topography_code': str(row.get('Topography', '')),
                'name': str(row.get('NAME', '')),
                'match_score': score,
                'match_method': method
            })

        best_row, best_score, best_method = candidates[0]
        query_code = str(best_row.get('Query', ''))
        morphology_code = str(best_row.get('Morphology', ''))
        topography_code = str(best_row.get('Topography', ''))
        description = str(best_row.get('NAME', ''))

        histology_code = None
        behavior_code = None
        if morphology_code and '/' in morphology_code:
            parts = morphology_code.split('/')
            histology_code = parts[0]
            behavior_code = parts[1] if len(parts) > 1 else None

        if query_code:
            primary_code = query_code
        elif morphology_code and topography_code:
            primary_code = f"{morphology_code}-{topography_code}"
        elif morphology_code:
            primary_code = morphology_code
        elif topography_code:
            primary_code = topography_code
        else:
            primary_code = candidate_list[0]['query_code'] if candidate_list else None

        return {
            'code': primary_code,
            'query_code': query_code if query_code else None,
            'morphology_code': morphology_code if morphology_code else None,
            'topography_code': topography_code if topography_code else None,
            'histology_code': histology_code,
            'behavior_code': behavior_code,
            'description': description if description else None,
            'confidence': best_score,
            'match_method': f'llm_csv_{best_method}',
            'match_score': best_score,
            'candidates': candidate_list,
            'selected_candidate_index': 0,
            'user_selected': False
        }
    except Exception as e:
        print(f"[WARN] Async LLM+CSV extraction error: {e}")
        import traceback
        traceback.print_exc()
        return None


def _reconcile_with_existing_code(
    result: Dict[str, Any],
    existing_code: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Ensure the primary morphology/topography codes match what was extracted
    from the annotation text, not overridden by CSV candidate selection.

    The CSV candidates are kept for user selection, but the "active" code
    should reflect what the annotation actually says.
    """
    if not existing_code:
        return result

    # Reconcile morphology_code
    extracted_morph = existing_code.get('morphology_code')
    if extracted_morph and extracted_morph != result.get('morphology_code'):
        print(f"[INFO] Reconciling morphology: CSV had {result.get('morphology_code')}, annotation text has {extracted_morph}")
        result['morphology_code'] = extracted_morph
        # Update derived fields
        if '/' in extracted_morph:
            parts = extracted_morph.split('/')
            result['histology_code'] = parts[0]
            result['behavior_code'] = parts[1] if len(parts) > 1 else None
        # Try to find a matching candidate
        matched = False
        for idx, cand in enumerate(result.get('candidates', [])):
            if cand.get('morphology_code') == extracted_morph:
                result['selected_candidate_index'] = idx
                result['code'] = cand['query_code']
                result['query_code'] = cand['query_code']
                result['topography_code'] = cand['topography_code']
                result['description'] = cand['name']
                matched = True
                break
        if not matched:
            # No matching candidate — recompute code from extracted values
            topo = result.get('topography_code')
            if extracted_morph and topo:
                result['code'] = f"{extracted_morph}-{topo}"
                result['query_code'] = f"{extracted_morph}-{topo}"
            else:
                result['code'] = extracted_morph
                result['query_code'] = None

    # Reconcile topography_code
    extracted_topo = existing_code.get('topography_code')
    if extracted_topo and extracted_topo != result.get('topography_code'):
        print(f"[INFO] Reconciling topography: CSV had {result.get('topography_code')}, annotation text has {extracted_topo}")
        result['topography_code'] = extracted_topo
        # Try to find a matching candidate
        matched = False
        for idx, cand in enumerate(result.get('candidates', [])):
            if cand.get('topography_code') == extracted_topo:
                result['selected_candidate_index'] = idx
                result['code'] = cand['query_code']
                result['query_code'] = cand['query_code']
                result['morphology_code'] = cand.get('morphology_code') or result.get('morphology_code')
                result['description'] = cand['name']
                matched = True
                break
        if not matched:
            morph = result.get('morphology_code')
            if morph and extracted_topo:
                result['code'] = f"{morph}-{extracted_topo}"
                result['query_code'] = f"{morph}-{extracted_topo}"
            else:
                result['code'] = extracted_topo

    return result


def _extract_existing_code(text: str) -> Optional[Dict[str, Any]]:
    """Extract ICD-O-3 code if it already exists in the text"""
    # Pattern 1: Full ICD-O-3 code with morphology and topography: "8852/3-C50.1"
    pattern1 = r'(\d{4}/\d)\s*-\s*([C]\d{2}\.\d)'
    match1 = re.search(pattern1, text)
    if match1:
        morphology = match1.group(1)
        topography = match1.group(2)
        histology, behavior = morphology.split('/')
        return {
            'code': f"{morphology}-{topography}",
            'morphology_code': morphology,
            'topography_code': topography,
            'histology_code': histology,
            'behavior_code': behavior,
            'description': None,
            'confidence': 1.0  # High confidence since it's explicitly stated
        }
    
    # Pattern 2: Morphology code only: "8805/3"
    pattern2 = r'(\d{4}/\d)'
    match2 = re.search(pattern2, text)
    if match2:
        morphology = match2.group(1)
        histology, behavior = morphology.split('/')
        return {
            'code': morphology,
            'morphology_code': morphology,
            'topography_code': None,
            'histology_code': histology,
            'behavior_code': behavior,
            'description': None,
            'confidence': 1.0
        }
    
    # Pattern 3: Topography code only: "C71.7"
    pattern3 = r'([C]\d{2}\.\d)'
    match3 = re.search(pattern3, text)
    if match3:
        topography = match3.group(1)
        return {
            'code': topography,
            'morphology_code': None,
            'topography_code': topography,
            'histology_code': None,
            'behavior_code': None,
            'description': None,
            'confidence': 0.8
        }
    
    return None


def _extract_with_llm_and_csv_match(
    text: str,
    prompt_type: str,
    note_text: Optional[str],
    vllm_client: Any,
    n_candidates: int = 5
) -> Optional[Dict[str, Any]]:
    """
    Extract ICD-O-3 code using LLM to extract search terms and match against CSV.
    Returns multiple candidates from CSV for user selection.

    Args:
        text: Annotation text
        prompt_type: Type of prompt
        note_text: Original note text
        vllm_client: vLLM client instance
        n_candidates: Number of candidates to return (default 5)

    Returns:
        Dictionary with ICD-O-3 code information including candidates array, or None
    """
    try:
        # Import LLM extractor and CSV indexer
        from lib.icdo3_llm_extractor import extract_histology_topography_with_llm
        from lib.icdo3_csv_indexer import get_csv_indexer

        # Extract histology/topography information using LLM (as search terms)
        extracted_info = extract_histology_topography_with_llm(
            note_text=note_text or text,
            annotation_text=text,
            prompt_type=prompt_type,
            vllm_client=vllm_client
        )

        # Get CSV indexer - this is required as CSV is the source of truth
        csv_indexer = get_csv_indexer()
        if not csv_indexer:
            print("[WARN] CSV indexer not available, cannot extract ICD-O-3 codes")
            return None

        # Get top N candidates from CSV using LLM-extracted search terms
        candidates = csv_indexer.find_top_candidates(
            histology_text=extracted_info.get('histology_text') if extracted_info else None,
            topography_text=extracted_info.get('topography_text') if extracted_info else None,
            morphology_code=extracted_info.get('morphology_code') if extracted_info else None,
            topography_code=extracted_info.get('topography_code') if extracted_info else None,
            query_code=extracted_info.get('query_code') if extracted_info else None,
            n=n_candidates
        )

        if not candidates:
            print(f"[INFO] No CSV candidates found for extracted search terms")
            return None

        # Build candidate list for frontend
        candidate_list = []
        for rank, (row, score, method) in enumerate(candidates, 1):
            candidate_list.append({
                'rank': rank,
                'query_code': str(row.get('Query', '')),
                'morphology_code': str(row.get('Morphology', '')),
                'topography_code': str(row.get('Topography', '')),
                'name': str(row.get('NAME', '')),
                'match_score': score,
                'match_method': method
            })

        # Use first candidate (best match) as the default selection
        best_row, best_score, best_method = candidates[0]
        query_code = str(best_row.get('Query', ''))
        morphology_code = str(best_row.get('Morphology', ''))
        topography_code = str(best_row.get('Topography', ''))
        description = str(best_row.get('NAME', ''))

        # Parse morphology code
        histology_code = None
        behavior_code = None
        if morphology_code and '/' in morphology_code:
            parts = morphology_code.split('/')
            histology_code = parts[0]
            behavior_code = parts[1] if len(parts) > 1 else None

        # Determine primary code
        if query_code:
            primary_code = query_code
        elif morphology_code and topography_code:
            primary_code = f"{morphology_code}-{topography_code}"
        elif morphology_code:
            primary_code = morphology_code
        elif topography_code:
            primary_code = topography_code
        else:
            primary_code = candidate_list[0]['query_code'] if candidate_list else None

        return {
            'code': primary_code,
            'query_code': query_code if query_code else None,
            'morphology_code': morphology_code if morphology_code else None,
            'topography_code': topography_code if topography_code else None,
            'histology_code': histology_code,
            'behavior_code': behavior_code,
            'description': description if description else None,
            'confidence': best_score,
            'match_method': f'llm_csv_{best_method}',
            'match_score': best_score,
            # Multi-candidate support
            'candidates': candidate_list,
            'selected_candidate_index': 0,
            'user_selected': False
        }
    except Exception as e:
        print(f"[WARN] LLM+CSV extraction error: {e}")
        import traceback
        traceback.print_exc()
        return None


def _resolve_topography_from_annotation(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract the site text from a tumor site annotation and resolve it to a
    topography code using the TopographyResolver (condition_files CSVs).

    Handles annotation formats like:
      - "Tumor site (Upper and Lower limbs): Upper leg."
      - "Tumor site (Intra abdominal): perirenal (ICD-O-3: C49.4)."
      - "Upper leg"

    Returns dict compatible with existing_code format, or None.
    """
    try:
        from lib.topography_resolver import get_topography_resolver
        resolver = get_topography_resolver()
    except Exception as e:
        print(f"[WARN] TopographyResolver not available: {e}")
        return None

    # Extract site text from annotation format
    site_text = None

    # Pattern 1: "Tumor site (Category): Site (ICD-O-3: Cxx.x)."
    m = re.search(r'Tumor site\s*\([^)]*\)\s*:\s*(.+?)(?:\s*\(ICD-O-3:.*?\))?\s*\.?\s*$', text, re.IGNORECASE)
    if m:
        site_text = m.group(1).strip()
    else:
        # Pattern 2: "Tumor site: site."
        m = re.search(r'Tumor site\s*:\s*(.+?)(?:\s*\(ICD-O-3:.*?\))?\s*\.?\s*$', text, re.IGNORECASE)
        if m:
            site_text = m.group(1).strip()
        else:
            # Pattern 3: use full text as site description
            site_text = text.strip().rstrip('.')

    if not site_text:
        return None

    # Remove any trailing parenthetical like "(hip)"
    clean_site = re.sub(r'\s*\([^)]*\)\s*$', '', site_text).strip()

    # Try the cleaned text first, then original
    entry = resolver.resolve_text(clean_site) or resolver.resolve_text(site_text)
    if not entry:
        return None

    return {
        'code': entry['code'],
        'morphology_code': None,
        'topography_code': entry['code'],
        'histology_code': None,
        'behavior_code': None,
        'description': f"{entry['subsite']} ({entry.get('site', '')})" if entry.get('site') else entry['subsite'],
        'confidence': 0.85
    }


def _resolve_morphology_from_annotation(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract the histology text from a histological type annotation and resolve
    it to a morphology code using the MorphologyResolver (condition_files CSVs).

    Handles annotation formats like:
      - "Histological type (SARC): Undifferentiated sarcoma (ICD-O-3: 8800/3)."
      - "Histological type: Sarcoma NOS."
      - "Undifferentiated sarcoma"

    Returns dict compatible with existing_code format, or None.
    """
    try:
        from lib.morphology_resolver import get_morphology_resolver
        resolver = get_morphology_resolver()
    except Exception as e:
        print(f"[WARN] MorphologyResolver not available: {e}")
        return None

    # Extract histology text from annotation format
    histology_text = None

    # Pattern 1: "Histological type (Category): Type (ICD-O-3: xxxx/x)."
    m = re.search(
        r'Histolog\w+\s+type?\s*\([^)]*\)\s*:\s*(.+?)(?:\s*\(ICD-O-3:.*?\))?\s*\.?\s*$',
        text, re.IGNORECASE
    )
    if m:
        histology_text = m.group(1).strip()
    else:
        # Pattern 2: "Histological type: Type."
        m = re.search(
            r'Histolog\w+\s+type?\s*:\s*(.+?)(?:\s*\(ICD-O-3:.*?\))?\s*\.?\s*$',
            text, re.IGNORECASE
        )
        if m:
            histology_text = m.group(1).strip()
        else:
            # Pattern 3: use full text as histology description
            histology_text = text.strip().rstrip('.')

    if not histology_text:
        return None

    # Remove any trailing parenthetical like "(C64.0)" or "(ICD-O-3: ...)"
    clean_text = re.sub(r'\s*\([^)]*\)\s*$', '', histology_text).strip()

    # Try the cleaned text first, then original
    entry = resolver.resolve_text(clean_text) or resolver.resolve_text(histology_text)
    if not entry:
        return None

    code = entry['code']
    histology_code = None
    behavior_code = None
    if '/' in code:
        parts = code.split('/')
        histology_code = parts[0]
        behavior_code = parts[1] if len(parts) > 1 else None

    return {
        'code': code,
        'morphology_code': code,
        'topography_code': None,
        'histology_code': histology_code,
        'behavior_code': behavior_code,
        'description': f"{entry['label']} ({entry.get('group', '')})" if entry.get('group') else entry['label'],
        'confidence': 0.85
    }


def _extract_with_patterns(text: str, prompt_type: str) -> Optional[Dict[str, Any]]:
    """
    Fallback pattern-based extraction for common histology/site terms.
    This uses a simple lookup table for common terms.
    """
    global _LOOKUP_TABLE_CACHE

    # Load lookup table once and cache at module level
    if _LOOKUP_TABLE_CACHE is None:
        lookup_file = Path(__file__).parent.parent / "data" / "icdo3_lookup.json"
        if lookup_file.exists():
            try:
                with open(lookup_file, 'r', encoding='utf-8') as f:
                    _LOOKUP_TABLE_CACHE = json.load(f)
            except Exception as e:
                print(f"[WARN] Failed to load ICD-O-3 lookup table: {e}")
                _LOOKUP_TABLE_CACHE = {}
        else:
            _LOOKUP_TABLE_CACHE = {}

    # Normalize text for matching
    text_lower = text.lower()

    # Try to match against lookup table
    for term, code_info in _LOOKUP_TABLE_CACHE.items():
        if term.lower() in text_lower:
            return code_info

    return None

