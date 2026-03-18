"""
Prompt wrapper to add structured JSON format instructions.

When guided decoding is active (vLLM response_format), the JSON structure
is enforced at the token level, so we can use shorter format instructions
to save tokens for the actual clinical note content.
"""
from typing import Dict, Any


# Concise format instructions for guided decoding mode (~500 fewer tokens)
_GUIDED_JSON_INSTRUCTIONS = """
# Output Format
Respond with a JSON object containing:
- "reasoning": Clinical validation and inference explaining the logic used to derive the annotation. Reference the specific phrases from the note that support the conclusion
- "final_output": Annotation following the template format exactly. If information is unavailable, use "Not applicable"
- "is_negated": true if negation/absence, false otherwise
- "date": {"date_value": "DD/MM/YYYY", "source": "extracted_from_text"} or {"date_value": "DD/MM/YYYY", "source": "derived_from_csv", "csv_date": "DD/MM/YYYY"} or null
"""


def wrap_prompt_with_json_format(
    prompt_template: str,
    csv_date: str | None = None,
    use_guided_decoding: bool = False,
) -> str:
    """
    Wrap a prompt template with JSON format instructions.
    Also replaces verbose reasoning instructions with concise ones.

    Args:
        prompt_template: Original prompt template
        csv_date: Optional CSV date to include in the prompt
        use_guided_decoding: If True, use shorter instructions (JSON structure
                             is enforced by vLLM response_format at token level)

    Returns:
        Wrapped prompt with JSON format instructions
    """
    import re

    # When guided decoding is active, use concise instructions to save tokens
    if use_guided_decoding:
        csv_date_section = f"\n- CSV Date: {csv_date}\n" if csv_date else ""

        # Still replace verbose reasoning with concise version
        for pattern in [
            r'# Reasoning Requirements \(Traceability\)\s*\nFor every entity extracted.*?ensure high-fidelity deduction\.',
            r'# Reasoning Requirements \(Traceability\)\s*\nFor every entity extracted.*?Generate the response in a structured JSON format\.(?:\s*Ensure[^\n]*)?',
        ]:
            prompt_template = re.sub(pattern, "", prompt_template, flags=re.MULTILINE | re.DOTALL)

        if "### Input:" in prompt_template:
            parts = prompt_template.split("### Input:")
            if len(parts) == 2:
                wrapped = parts[0] + _GUIDED_JSON_INSTRUCTIONS + "\n---\n\n### Input:" + csv_date_section + parts[1]
                # Strip any trailing JSON example block after ### Response
                # All standard prompts end with a literal JSON example like:
                #   ### Response (JSON only):
                #   { "evidence": "...", "final_output": "annotation in the exact format..." }
                # This must be removed because guided decoding enforces JSON structure,
                # and the LLM copies the example literally instead of extracting real data.
                wrapped = re.sub(
                    r'###\s*Response[^\n]*:\s*\n\s*\{.*?"final_output".*?\}\s*$',
                    '### Response (JSON only, no other text):',
                    wrapped,
                    flags=re.DOTALL,
                )
                # Handle templates that don't have a JSON example block
                if "### Response (JSON only, no other text):" not in wrapped:
                    wrapped = wrapped.replace("### Response:\nAnnotation: {{annotation}}", "### Response (JSON only, no other text):")
                    wrapped = wrapped.replace("### Response:", "### Response (JSON only, no other text):")
                return wrapped

        wrapped = prompt_template + "\n\n" + _GUIDED_JSON_INSTRUCTIONS
        if csv_date:
            wrapped += f"\n\nCSV Date: {csv_date}"
        wrapped += "\n\n### Response (JSON only, no other text):"
        return wrapped

    # --- Full instructions path (no guided decoding) ---
    # First, replace verbose reasoning instructions with concise ones
    
    # Pattern to match verbose reasoning requirements sections (more flexible pattern)
    # This matches the common pattern found in prompts.json
    verbose_reasoning_patterns = [
        # Pattern 1: Full verbose section with all details
        r'# Reasoning Requirements \(Traceability\)\s*\nFor every entity extracted, you MUST follow this internal logic:\s*\n1\. \*\*Evidence\*\*: Locate the exact literal phrase or sentence from the note\.\s*\n2\. \*\*Clinical Validation\*\*: Determine if the finding is current, a past medical history \(PMH\), or a suspicion\.\s*\n3\. \*\*Inference\*\*: Explain the logic used to map the natural language to the standard value \(e\.g\., mapping "Ductal" to "Infiltrating duct carcinoma"\)\.\s*\nGenerate the response in a structured JSON format\. Ensure the `reasoning` and `evidence` fields are populated BEFORE the final values to ensure high-fidelity deduction\.',
        # Pattern 2: Shorter version (also consume trailing Ensure line if present)
        r'# Reasoning Requirements \(Traceability\)\s*\nFor every entity extracted, you MUST follow this internal logic:\s*\n1\. \*\*Evidence\*\*:.*?\n2\. \*\*Clinical Validation\*\*:.*?\n3\. \*\*Inference\*\*:.*?\nGenerate the response in a structured JSON format\.(?:\s*Ensure[^\n]*)?',
    ]
    
    concise_reasoning_instruction = """# Reasoning Requirements (Traceability)
For every entity extracted, you MUST follow this internal logic:
1. **Evidence**: Reference the exact literal phrase or sentence from the note that supports the annotation.
2. **Clinical Validation**: Determine if the finding is current, a past medical history (PMH), or a suspicion.
3. **Inference**: Explain the logic used to map the natural language to the standard value.

Generate the response in a structured JSON format. Ensure the `reasoning` field is populated BEFORE the final values."""
    
    # Replace verbose reasoning instructions with concise ones
    for pattern in verbose_reasoning_patterns:
        prompt_template = re.sub(pattern, concise_reasoning_instruction, prompt_template, flags=re.MULTILINE | re.DOTALL)
    # JSON format instructions
    json_instructions = """
# Output Format (JSON)
You MUST output a JSON object with the following structure:
{
  "reasoning": "Clinical reasoning explaining the logic used to derive the annotation. Reference the specific phrases from the note that support the conclusion. Include: 1) Clinical Validation (current vs PMH vs suspicion), 2) Inference steps.",
  "final_output": "The final annotation text following the exact template format specified in the prompt above.",
  "is_negated": false,
  "date": null
}

# Field Guidelines:
- **reasoning**: Explain your clinical validation and inference logic. Reference the exact phrases from the note that support the annotation. Include: (1) whether finding is current/PMH/suspicion, (2) inference steps used to map natural language to the standard value.
- **final_output**: Must match the template format exactly as specified in the prompt.

  **CRITICAL - Handling Missing Information**: If the required information is NOT available in the note (e.g., surgery hasn't occurred yet, information is not mentioned, or cannot be determined), you MUST follow this standardized format:

  * For structured annotations with a label (e.g., "Tumor depth: [value]"), output: "[Label]: Not applicable"
  * For annotations without a label, output: "Not applicable"
  * Alternative standardized phrases (use consistently): "Not applicable", "Not available", "Not specified", "Unknown", or "Information not available"

  **IMPORTANT**: Always use the SAME standardized phrase throughout. Do NOT mix different absence indicators. Do NOT fill in placeholder values like "[select result]", "[put date]", etc. when information is truly unavailable - instead use "Not applicable".
- **is_negated**: Set to true if the annotation indicates absence, negation, or negative finding (e.g., 'no evidence', 'absence of', 'ruled out', 'no', 'not', 'negative', 'none', 'without', 'excluded').
- **date**: ALWAYS provide date information. First, try to extract the date from the note text. If found, use {"date_value": "DD/MM/YYYY", "source": "extracted_from_text"}. If no date is found in the note text, you MUST use the CSV date provided: {"date_value": "DD/MM/YYYY", "source": "derived_from_csv", "csv_date": "DD/MM/YYYY"}. Never set date to null - always use either the extracted date or the CSV date.

IMPORTANT:
- Output ONLY valid JSON. Do not include any explanatory text before or after the JSON object.
- CRITICAL: If the required information is NOT available in the note (e.g., surgery hasn't occurred, information is not mentioned, or cannot be determined), you MUST:
  * Set `final_output` to a STANDARDIZED absence format:
    - For annotations with labels (e.g., "Tumor depth: [value]"), use: "[Label]: Not applicable"
    - For annotations without labels, use: "Not applicable"
    - ALWAYS use "Not applicable" consistently (do NOT mix with "Not specified", "Unknown", etc.)
  * In `reasoning`, clearly state that the information is not available (e.g., "The note does not state...", "Information is not available...", "Cannot be determined from the note...")
  * Do NOT guess or fill in placeholder values like "[select result]", "[put date]" when information is truly unavailable - use "Not applicable" instead.
"""
    
    # Add CSV date to prompt if provided
    csv_date_section = ""
    if csv_date:
        csv_date_section = f"\n- CSV Date: {csv_date}\n"
    
    # Find where to insert JSON instructions (before the final "Now process" section)
    if "Now process the following note" in prompt_template or "### Input:" in prompt_template:
        # Insert before the input section
        parts = prompt_template.split("### Input:")
        if len(parts) == 2:
            # Add JSON instructions before input section
            wrapped = parts[0] + json_instructions + "\n---\n\n### Input:" + csv_date_section + parts[1]
            # Strip any trailing JSON example block (same as guided path)
            wrapped = re.sub(
                r'###\s*Response[^\n]*:\s*\n\s*\{.*?"final_output".*?\}\s*$',
                '### Response (JSON only, no other text):',
                wrapped,
                flags=re.DOTALL,
            )
            if "### Response (JSON only, no other text):" not in wrapped:
                wrapped = wrapped.replace("### Response:\nAnnotation: {{annotation}}", "### Response (JSON only, no other text):")
                wrapped = wrapped.replace("### Response:", "### Response (JSON only, no other text):")
            return wrapped
        else:
            # Try alternative pattern
            parts = prompt_template.split("Now process the following note")
            if len(parts) == 2:
                wrapped = parts[0] + json_instructions + "\n---\n\nNow process the following note" + csv_date_section + parts[1]
                wrapped = wrapped.replace("Annotation: {{annotation}}", "")
                return wrapped
    
    # If no clear insertion point, append at the end
    wrapped = prompt_template + "\n\n" + json_instructions
    if csv_date:
        wrapped += f"\n\nCSV Date: {csv_date}"
    wrapped += "\n\n### Response (JSON only, no other text):"
    
    return wrapped


def update_prompt_placeholders(prompt: str, note_text: str, csv_date: str | None = None) -> str:
    """
    Update prompt placeholders with actual values.
    
    Args:
        prompt: Prompt template with placeholders
        note_text: Note text to insert
        csv_date: Optional CSV date
    
    Returns:
        Prompt with placeholders replaced
    """
    # Replace note placeholders
    prompt = prompt.replace("{{note_original_text}}", note_text)
    prompt = prompt.replace("{note}", note_text)
    prompt = prompt.replace("{{note}}", note_text)
    
    # Replace CSV date placeholder
    if csv_date:
        prompt = prompt.replace("{{csv_date}}", csv_date)
    else:
        prompt = prompt.replace("{{csv_date}}", "Not provided")
    
    return prompt

