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
    
    for prompt_key, template in int_prompts.items():
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

