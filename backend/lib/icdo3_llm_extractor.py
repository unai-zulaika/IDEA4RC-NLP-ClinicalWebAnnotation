"""
ICD-O-3 LLM-Based Extractor

This module uses LLM to extract histology and topography information from clinical notes.
"""

import json
import re
from typing import Optional, Dict, Any, Tuple
from pathlib import Path


def extract_histology_topography_with_llm(
    note_text: str,
    annotation_text: str,
    prompt_type: str,
    vllm_client: Any
) -> Optional[Dict[str, Any]]:
    """
    Extract histology and topography information using LLM.
    
    Args:
        note_text: Original clinical note text
        annotation_text: Extracted annotation text
        prompt_type: Type of prompt (histology or site)
        vllm_client: vLLM client instance
    
    Returns:
        Dictionary with extracted information:
        {
            "histology_text": "...",
            "morphology_code": "...",
            "topography_text": "...",
            "topography_code": "...",
            "query_code": "..."
        }
        or None if extraction fails
    """
    if not vllm_client:
        print("[WARN] vLLM client not available for ICD-O-3 extraction")
        return None
    
    # Build extraction prompt
    prompt = _build_extraction_prompt(note_text, annotation_text, prompt_type)
    
    try:
        # Generate with LLM
        output = vllm_client.generate(
            prompt=prompt,
            max_new_tokens=512,
            temperature=0.0,  # Deterministic output
            return_logprobs=False
        )
        
        raw_output = output.get("raw", output.get("normalized", ""))
        
        # Parse LLM response
        extracted_info = _parse_llm_response(raw_output, prompt_type)
        
        return extracted_info
    except Exception as e:
        print(f"[WARN] LLM extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def _build_extraction_prompt(
    note_text: str,
    annotation_text: str,
    prompt_type: str
) -> str:
    """
    Build prompt for LLM to extract histology/topography information.
    
    Args:
        note_text: Original clinical note
        annotation_text: Extracted annotation
        prompt_type: Type of prompt
    
    Returns:
        Formatted prompt string
    """
    is_histology = 'histolog' in prompt_type.lower()
    is_site = 'site' in prompt_type.lower() and 'tumor' in prompt_type.lower()
    
    # Determine what to extract
    if is_histology and is_site:
        extraction_type = "both histology and topography"
    elif is_histology:
        extraction_type = "histology (morphology)"
    elif is_site:
        extraction_type = "topography (tumor site)"
    else:
        extraction_type = "histology and topography"
    
    # Check if annotation has placeholder - if so, emphasize using note text
    has_placeholder = any(placeholder in annotation_text.lower() for placeholder in [
        '[select icd-o-3 code]',
        '[select icdo code]',
        '[select code]',
        'select icd-o-3',
        'select icdo'
    ])
    
    placeholder_note = ""
    if has_placeholder:
        placeholder_note = "\n\nIMPORTANT: The annotation contains a placeholder '[select ICD-O-3 code]', which means the code was not extracted. You MUST extract the ICD-O-3 code from the Clinical Note below. Look carefully for histology descriptions and match them to appropriate ICD-O-3 codes."
    
    prompt = f"""You are a medical coding expert. Extract ICD-O-3 coding information from the following clinical note and annotation.

Clinical Note:
{note_text[:2000]}

Annotation:
{annotation_text}
{placeholder_note}

Task: Extract {extraction_type} information and provide ICD-O-3 codes.

CRITICAL INSTRUCTIONS:
1. If the annotation contains "[select ICD-O-3 code]" or similar placeholders, you MUST extract the code from the Clinical Note
2. Look for histology descriptions in the Clinical Note (e.g., "Sarcoma, undifferentiated", "Undifferentiated sarcoma", "Pleomorphic sarcoma")
3. Match these descriptions to appropriate ICD-O-3 morphology codes
4. For histology prompts, focus on morphology codes (e.g., 8805/3 for undifferentiated sarcoma)
5. For site prompts, focus on topography codes (e.g., C71.7 for brain stem)

Output format (JSON only):
{{
  "histology_text": "Description of histology type from the note (e.g., 'Sarcoma, undifferentiated, pleomorphic')",
  "morphology_code": "ICD-O-3 morphology code (e.g., '8805/3' for undifferentiated sarcoma) or null if not found",
  "topography_text": "Description of tumor site/location (e.g., 'External lip, NOS')",
  "topography_code": "ICD-O-3 topography code (e.g., 'C00.2') or null if not found",
  "query_code": "Full ICD-O-3 code if both morphology and topography are found (e.g., '8805/3-C00.2') or null"
}}

Code Format:
- Morphology: "XXXX/X" (4 digits, slash, 1 digit) - e.g., "8805/3" for undifferentiated sarcoma
- Topography: "CXX.X" (C, 2 digits, dot, 1 digit) - e.g., "C71.7" for brain stem
- Query code: "morphology_code-topography_code" - e.g., "8805/3-C71.7"

Common ICD-O-3 Codes Reference:
- Undifferentiated sarcoma: 8805/3
- Pleomorphic sarcoma: 8802/3
- Spindle cell sarcoma: 8801/3
- Myxoid sarcoma: 8840/3

Output ONLY valid JSON, no other text."""

    return prompt


def _parse_llm_response(response_text: str, prompt_type: str) -> Optional[Dict[str, Any]]:
    """
    Parse LLM response into structured format.
    
    Args:
        response_text: Raw LLM response
        prompt_type: Type of prompt
    
    Returns:
        Dictionary with extracted information or None if parsing fails
    """
    if not response_text:
        return None
    
    # Try to extract JSON from response
    json_match = re.search(r'\{[^{}]*"histology_text"[^{}]*\}', response_text, re.DOTALL)
    if not json_match:
        # Try broader JSON pattern
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    
    if json_match:
        try:
            json_str = json_match.group(0)
            # Clean up common JSON issues
            json_str = json_str.replace('\n', ' ').replace('\r', ' ')
            parsed = json.loads(json_str)
            
            # Validate and normalize
            result = {
                "histology_text": parsed.get("histology_text", "").strip() or None,
                "morphology_code": _normalize_code(parsed.get("morphology_code")) or None,
                "topography_text": parsed.get("topography_text", "").strip() or None,
                "topography_code": _normalize_code(parsed.get("topography_code")) or None,
                "query_code": _normalize_code(parsed.get("query_code")) or None
            }
            
            # If query_code not provided but both codes are available, construct it
            if not result["query_code"] and result["morphology_code"] and result["topography_code"]:
                result["query_code"] = f"{result['morphology_code']}-{result['topography_code']}"
            
            return result
        except json.JSONDecodeError as e:
            print(f"[WARN] Failed to parse JSON from LLM response: {e}")
            print(f"[DEBUG] Response text: {response_text[:500]}")
    
    # Fallback: Try to extract codes directly from text using regex
    return _extract_codes_from_text(response_text)


def _normalize_code(code: Any) -> Optional[str]:
    """Normalize ICD-O-3 code format"""
    if not code or code == "null" or code == "None":
        return None
    
    code_str = str(code).strip()
    if not code_str:
        return None
    
    return code_str


def _extract_codes_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Fallback: Extract codes directly from text using regex patterns.
    
    Args:
        text: Text to search
    
    Returns:
        Dictionary with extracted codes or None
    """
    # Pattern for morphology code: XXXX/X
    morph_pattern = r'(\d{4}/\d)'
    # Pattern for topography code: CXX.X
    topo_pattern = r'([C]\d{2}\.\d)'
    # Pattern for combined: XXXX/X-CXX.X
    combined_pattern = r'(\d{4}/\d)\s*-\s*([C]\d{2}\.\d)'
    
    morphology_code = None
    topography_code = None
    query_code = None
    
    # Try combined pattern first
    combined_match = re.search(combined_pattern, text)
    if combined_match:
        morphology_code = combined_match.group(1)
        topography_code = combined_match.group(2)
        query_code = f"{morphology_code}-{topography_code}"
    else:
        # Try separate patterns
        morph_match = re.search(morph_pattern, text)
        if morph_match:
            morphology_code = morph_match.group(1)
        
        topo_match = re.search(topo_pattern, text)
        if topo_match:
            topography_code = topo_match.group(1)
        
        if morphology_code and topography_code:
            query_code = f"{morphology_code}-{topography_code}"
    
    if morphology_code or topography_code:
        return {
            "histology_text": None,
            "morphology_code": morphology_code,
            "topography_text": None,
            "topography_code": topography_code,
            "query_code": query_code
        }
    
    return None
