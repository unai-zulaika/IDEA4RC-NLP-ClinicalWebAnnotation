"""
Prompt Adapter

Converts prompts.json prompts to model_runner.py compatible format.
Transforms {{note_original_text}} → {note} and {few_shot_examples} → {fewshots}.
Supports loading prompts from all centers (INT, MSCI, VGR, etc.).
"""

import json
import re
from pathlib import Path
from typing import Dict


def _adapt_prompts_for_center(center_prompts: Dict, adapted_prompts: Dict[str, Dict[str, str]]) -> None:
    """
    Adapt prompts from a single center and merge them into adapted_prompts dict.

    Args:
        center_prompts: Dict of {prompt_key: prompt_data} for one center
        adapted_prompts: Output dict to merge results into (mutated in place)
    """
    for prompt_key, prompt_data in center_prompts.items():
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


def adapt_all_prompts_from_dir(prompts_dir: str | Path) -> Dict[str, Dict[str, str]]:
    """
    Load and adapt prompts from a directory-based structure where each center
    has its own subdirectory with a prompts.json file.

    Structure: prompts_dir/{CENTER}/prompts.json
    Keys in each file are unsuffixed (e.g. 'biopsygrading').
    On load, keys are suffixed with '-{center_lower}' to avoid collisions
    (e.g. 'biopsygrading-int').

    Args:
        prompts_dir: Path to directory containing center subdirectories

    Returns:
        Dictionary with structure: {suffixed_key: {"template": adapted_template}}
        Compatible with model_runner.py's get_prompt() function
    """
    prompts_dir = Path(prompts_dir)

    if not prompts_dir.is_dir():
        raise ValueError(f"Prompts directory not found: {prompts_dir}")

    adapted_prompts: Dict[str, Dict[str, str]] = {}

    center_dirs = sorted(
        [d for d in prompts_dir.iterdir() if d.is_dir() and (d / "prompts.json").exists()]
    )

    if not center_dirs:
        raise ValueError(f"No center subdirectories with prompts.json found in {prompts_dir}")

    for center_dir in center_dirs:
        center_name = center_dir.name  # e.g. "INT", "VGR", "MSCI"
        center_lower = center_name.lower()
        prompts_file = center_dir / "prompts.json"

        with open(prompts_file, 'r', encoding='utf-8') as f:
            center_prompts = json.load(f)

        if not isinstance(center_prompts, dict):
            continue

        # Suffix keys with -center_lower before adapting
        suffixed_prompts: Dict = {}
        for key, value in center_prompts.items():
            suffixed_key = f"{key}-{center_lower}"
            suffixed_prompts[suffixed_key] = value

        _adapt_prompts_for_center(suffixed_prompts, adapted_prompts)

    if not adapted_prompts:
        raise ValueError(f"No prompts found in {prompts_dir}")

    return adapted_prompts


def adapt_all_prompts(prompts_path: str | Path) -> Dict[str, Dict[str, str]]:
    """
    Load and adapt prompts for use with model_runner.

    Accepts either:
    - A directory path containing {CENTER}/prompts.json subdirectories (new format)
    - A single prompts.json file path (legacy format)

    Args:
        prompts_path: Path to prompts directory or prompts.json file

    Returns:
        Dictionary with structure: {prompt_key: {"template": adapted_template}}
        Compatible with model_runner.py's get_prompt() function
    """
    prompts_path = Path(prompts_path)

    # Directory-based structure: delegate to adapt_all_prompts_from_dir
    if prompts_path.is_dir():
        return adapt_all_prompts_from_dir(prompts_path)

    # Legacy single-file format
    with open(prompts_path, 'r', encoding='utf-8') as f:
        prompts_data = json.load(f)

    adapted_prompts: Dict[str, Dict[str, str]] = {}

    for center_key, center_prompts in prompts_data.items():
        if not isinstance(center_prompts, dict):
            continue
        _adapt_prompts_for_center(center_prompts, adapted_prompts)

    if not adapted_prompts:
        raise ValueError(f"No prompts found in {prompts_path}")

    return adapted_prompts


# Backward-compatible alias
def adapt_int_prompts(prompts_json_path: str | Path) -> Dict[str, Dict[str, str]]:
    """Backward-compatible alias for adapt_all_prompts."""
    return adapt_all_prompts(prompts_json_path)


def get_adapted_prompt(prompt_key: str, prompts_json_path: str | Path) -> str:
    """
    Get a single adapted prompt template by key.

    Args:
        prompt_key: The prompt key (e.g., 'biopsygrading-int')
        prompts_json_path: Path to prompts.json

    Returns:
        Adapted template string
    """
    adapted_prompts = adapt_all_prompts(prompts_json_path)

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
    adapted = adapt_all_prompts(prompts_path)

    print(f"\nAdapted {len(adapted)} prompts:")
    for key in list(adapted.keys())[:3]:  # Show first 3
        template = adapted[key]["template"]
        print(f"\n{key}:")
        print(template[:200] + "..." if len(template) > 200 else template)

