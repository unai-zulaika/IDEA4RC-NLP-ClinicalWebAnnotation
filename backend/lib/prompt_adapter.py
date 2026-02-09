"""
Prompt Adapter for INT Prompts

Converts FBK_scripts/prompts.json INT prompts to model_runner.py compatible format.
Transforms {{note_original_text}} → {note} and {few_shot_examples} → {fewshots}.
"""

import json
from pathlib import Path
from typing import Dict


def adapt_int_prompts(prompts_json_path: str | Path) -> Dict[str, Dict[str, str]]:
    """
    Load and adapt INT prompts from FBK_scripts/prompts.json for use with model_runner.
    
    Args:
        prompts_json_path: Path to FBK_scripts/prompts.json
        
    Returns:
        Dictionary with structure: {prompt_key: {"template": adapted_template}}
        Compatible with model_runner.py's get_prompt() function
    """
    prompts_json_path = Path(prompts_json_path)
    
    with open(prompts_json_path, 'r', encoding='utf-8') as f:
        prompts_data = json.load(f)
    
    int_prompts = prompts_data.get('INT', {})
    if not int_prompts:
        raise ValueError(f"No INT prompts found in {prompts_json_path}")
    
    adapted_prompts = {}
    
    import re
    
    for prompt_key, prompt_data in int_prompts.items():
        # Handle both old format (string) and new format (dict with template and entity_mapping)
        if isinstance(prompt_data, dict):
            template = prompt_data.get('template', '')
            # entity_mapping is stored but not used in adaptation (it's for extraction later)
        elif isinstance(prompt_data, str):
            template = prompt_data
        else:
            raise ValueError(f"Unexpected prompt data type for '{prompt_key}': {type(prompt_data)}")
        
        # Replace {{note_original_text}} with {note} (for model_runner)
        adapted_template = template.replace('{{note_original_text}}', '{note}')
        
        # Replace {few_shot_examples} with {fewshots} (for model_runner)
        adapted_template = adapted_template.replace('{few_shot_examples}', '{fewshots}')
        
        # Handle {static_samples} - if present, replace with empty string for now
        # (model_runner doesn't have static_samples, but we can inject them later if needed)
        if '{static_samples}' in adapted_template:
            # For now, remove the placeholder. If static_samples are needed,
            # they should be injected before calling model_runner.get_prompt()
            adapted_template = adapted_template.replace('{static_samples}\n', '')
            adapted_template = adapted_template.replace('{static_samples}', '')
        
        # Remove the {{annotation}} placeholder at the end - model_runner handles output formatting
        # The template should end with the Response section, not with {{annotation}}
        adapted_template = adapted_template.replace('{{annotation}}', '')
        
        # Replace verbose reasoning instructions with concise ones
        verbose_reasoning_patterns = [
            r'# Reasoning Requirements \(Traceability\)\s*\nFor every entity extracted, you MUST follow this internal logic:\s*\n1\. \*\*Evidence\*\*: Locate the exact literal phrase or sentence from the note\.\s*\n2\. \*\*Clinical Validation\*\*: Determine if the finding is current, a past medical history \(PMH\), or a suspicion\.\s*\n3\. \*\*Inference\*\*: Explain the logic used to map the natural language to the standard value \(e\.g\., mapping "Ductal" to "Infiltrating duct carcinoma"\)\.\s*\nGenerate the response in a structured JSON format\. Ensure the `reasoning` and `evidence` fields are populated BEFORE the final values to ensure high-fidelity deduction\.',
            r'# Reasoning Requirements \(Traceability\)\s*\nFor every entity extracted, you MUST follow this internal logic:\s*\n1\. \*\*Evidence\*\*:.*?\n2\. \*\*Clinical Validation\*\*:.*?\n3\. \*\*Inference\*\*:.*?\nGenerate the response in a structured JSON format\.',
        ]
        
        concise_reasoning_instruction = """# Reasoning Requirements (Traceability)
For every entity extracted, you MUST follow this internal logic:
1. **Evidence**: Locate the exact literal phrase or sentence from the note.
2. **Clinical Validation**: Determine if the finding is current, a past medical history (PMH), or a suspicion.
3. **Inference**: Briefly explain the logic used to map the natural language to the standard value.

IMPORTANT: Keep the reasoning field CONCISE. Provide only essential points in 2-3 sentences maximum. Avoid verbosity or repetition.
Generate the response in a structured JSON format. Ensure the `reasoning` and `evidence` fields are populated BEFORE the final values."""
        
        for pattern in verbose_reasoning_patterns:
            adapted_template = re.sub(pattern, concise_reasoning_instruction, adapted_template, flags=re.MULTILINE | re.DOTALL)
        
        # Clean up any extra newlines or formatting issues
        adapted_template = adapted_template.strip()
        
        adapted_prompts[prompt_key] = {
            "template": adapted_template
        }
    
    return adapted_prompts


def get_adapted_prompt(prompt_key: str, prompts_json_path: str | Path) -> str:
    """
    Get a single adapted prompt template by key.
    
    Args:
        prompt_key: The prompt key (e.g., 'biopsygrading-int')
        prompts_json_path: Path to FBK_scripts/prompts.json
        
    Returns:
        Adapted template string
    """
    adapted_prompts = adapt_int_prompts(prompts_json_path)
    
    if prompt_key not in adapted_prompts:
        available = list(adapted_prompts.keys())
        raise KeyError(
            f"Prompt key '{prompt_key}' not found. Available keys: {available}")
    
    return adapted_prompts[prompt_key]["template"]


if __name__ == "__main__":
    # Test the adapter
    script_dir = Path(__file__).resolve().parent
    prompts_path = script_dir / "FBK_scripts" / "prompts.json"
    
    print(f"Loading prompts from: {prompts_path}")
    adapted = adapt_int_prompts(prompts_path)
    
    print(f"\nAdapted {len(adapted)} prompts:")
    for key in list(adapted.keys())[:3]:  # Show first 3
        template = adapted[key]["template"]
        print(f"\n{key}:")
        print(template[:200] + "..." if len(template) > 200 else template)

