"""
Output Word Mapper

Applies output_word_mappings patterns from entity_mapping against the LLM
final_output at annotation time to produce derived field values.

Usage:
    derived = resolve_output_word_mappings(final_output, entity_mapping_dict)
    # derived == {"diseaseStatus": "recurrence"}
"""

import re
from typing import Any, Dict


def resolve_output_word_mappings(final_output: str, entity_mapping: Dict[str, Any]) -> Dict[str, str]:
    """
    For each field_mapping in entity_mapping that has an output_word_mappings list,
    test patterns against final_output in order. First match per field wins.

    Args:
        final_output: The LLM's final_output string (pre-normalization preferred).
        entity_mapping: The entity_mapping dict from prompts.json for the prompt type.

    Returns:
        Dict mapping field_name → matched value for every field where a pattern matched.
        Empty dict if no matches or entity_mapping has no output_word_mappings.
    """
    if not final_output or not entity_mapping:
        return {}

    derived: Dict[str, str] = {}

    for fm in entity_mapping.get("field_mappings", []):
        owm_list = fm.get("output_word_mappings")
        if not owm_list:
            continue

        field_name = fm.get("field_name", "")
        if not field_name:
            continue

        for owm in owm_list:
            pattern = owm.get("pattern", "")
            value = owm.get("value", "")
            if not pattern:
                continue

            flags_str = owm.get("flags") or ""
            re_flags = 0
            if "IGNORECASE" in flags_str:
                re_flags |= re.IGNORECASE
            if "MULTILINE" in flags_str:
                re_flags |= re.MULTILINE

            try:
                if re.search(pattern, final_output, re_flags):
                    derived[field_name] = value
                    break  # first match wins for this field
            except re.error:
                # Invalid regex — skip this mapping
                continue

    return derived
