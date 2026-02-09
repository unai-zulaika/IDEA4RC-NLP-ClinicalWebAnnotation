#!/usr/bin/env python3
"""
Script processor to extract prompts from Python files.
Extracts the generate_prompt_template function from each script and organizes
prompts by center (INT, MSCI, VGR) and prompt type.
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List


def extract_prompt_from_function(func_node: ast.FunctionDef, source_lines: List[str]) -> Optional[str]:
    """
    Extract the prompt template string from a function node.
    Uses source lines to extract the raw f-string template.
    """
    # Find the return statement in the AST
    return_node = None
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return) and node.value:
            return_node = node
            break

    if not return_node:
        return None

    # Get the line numbers for the return statement
    return_start_line = return_node.lineno - 1  # Convert to 0-based index
    return_end_line = return_node.end_lineno if hasattr(
        return_node, 'end_lineno') else return_start_line + 50

    # Extract the return statement source code
    return_source = '\n'.join(source_lines[return_start_line:return_end_line])

    # Find the f-string pattern: return f"""...""" or return f'''...'''
    # Handle both triple-quoted and single-quoted f-strings
    patterns = [
        (r'return\s+f"""', '"""'),  # Triple double quotes
        (r"return\s+f'''", "'''"),  # Triple single quotes
        (r'return\s+f"', '"'),       # Single double quote (single line)
        (r"return\s+f'", "'"),       # Single single quote (single line)
    ]

    for pattern_start, quote_end in patterns:
        match = re.search(pattern_start, return_source)
        if match:
            # Find the start position after "return f"""
            start_pos = match.end()
            # Find the closing quotes
            remaining = return_source[start_pos:]
            end_pos = remaining.find(quote_end)
            if end_pos != -1:
                prompt = remaining[:end_pos]
                # Preserve the template variables (they're already in the string)
                return prompt

    # Fallback: try AST parsing for non-f-strings
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return) and node.value:
            # Handle f-strings
            if isinstance(node.value, ast.JoinedStr):
                # Reconstruct the f-string template
                parts = []
                for part in node.value.values:
                    if isinstance(part, ast.Constant):
                        parts.append(part.value)
                    elif isinstance(part, ast.FormattedValue):
                        # Extract the variable name or expression
                        if isinstance(part.value, ast.Name):
                            parts.append(f"{{{part.value.id}}}")
                        else:
                            # For complex expressions, try to unparse
                            try:
                                expr_str = ast.unparse(part.value)
                                parts.append(f"{{{expr_str}}}")
                            except (AttributeError, ValueError):
                                # Fallback: use a placeholder
                                parts.append("{...}")
                return "".join(parts)
            # Handle regular strings
            elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value

    return None


def extract_prompt_from_file(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Extract the prompt template from a Python file.
    Returns a dictionary with prompt_type and prompt_template.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            source_lines = content.splitlines()

        # Parse the AST
        tree = ast.parse(content, filename=str(file_path))

        # Find the generate_prompt_template function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'generate_prompt_template':
                prompt_template = extract_prompt_from_function(
                    node, source_lines)
                if prompt_template:
                    # Extract prompt type from filename
                    # Format: llama3.1-8b-instruct-{prompt_type}-{center}.py
                    filename = file_path.stem
                    # Remove the prefix and suffix
                    parts = filename.split('-')
                    # Find the center indicator (last part before .py)
                    # Extract prompt type (everything between 'instruct' and center)
                    try:
                        instruct_idx = parts.index('instruct')
                        # Get everything after 'instruct' until the center part
                        prompt_parts = parts[instruct_idx + 1:]
                        # Remove center identifier (last part: vgr, msci, int-sarc)
                        prompt_type = '-'.join(prompt_parts[:-1])

                        return {
                            'prompt_type': prompt_type,
                            'prompt_template': prompt_template,
                            'filename': file_path.name
                        }
                    except (ValueError, IndexError):
                        # Fallback: try to extract from filename pattern
                        match = re.search(
                            r'instruct-(.+?)-(vgr|msci|int-sarc)', filename)
                        if match:
                            prompt_type = match.group(1)
                            return {
                                'prompt_type': prompt_type,
                                'prompt_template': prompt_template,
                                'filename': file_path.name
                            }
                        return {
                            'prompt_type': 'unknown',
                            'prompt_template': prompt_template,
                            'filename': file_path.name
                        }

        return None
    except (SyntaxError, ValueError, UnicodeDecodeError) as e:
        print(f"Error processing {file_path}: {e}")
        return None


def normalize_center_name(folder_name: str) -> str:
    """
    Normalize folder names to center codes.
    INT-Sarc-latest-scripts -> INT
    MSCI-latest-scripts -> MSCI
    VGR_latest_scripts -> VGR
    """
    if 'INT' in folder_name.upper() or 'int-sarc' in folder_name.lower():
        return 'INT'
    elif 'MSCI' in folder_name.upper():
        return 'MSCI'
    elif 'VGR' in folder_name.upper():
        return 'VGR'
    return folder_name


def process_all_scripts(base_dir: Path) -> Dict[str, Dict[str, str]]:
    """
    Process all Python scripts in subdirectories and organize prompts by center and type.
    Returns a nested dictionary: {center: {prompt_type: prompt_template}}
    """
    prompts: Dict[str, Dict[str, str]] = {}

    # Define the subdirectories to process
    subdirs = ['INT-Sarc-latest-scripts',
               'MSCI-latest-scripts', 'VGR_latest_scripts']

    for subdir_name in subdirs:
        subdir_path = base_dir / subdir_name
        if not subdir_path.exists():
            print(f"Warning: Directory {subdir_path} does not exist")
            continue

        center = normalize_center_name(subdir_name)
        prompts[center] = {}

        # Find all Python files
        python_files = list(subdir_path.glob('*.py'))
        # Filter out Zone.Identifier files and script_processor.py
        python_files = [
            f for f in python_files if 'Zone.Identifier' not in f.name and f.name != 'script_processor.py']

        print(f"\nProcessing {center} ({len(python_files)} files)...")

        for py_file in python_files:
            result = extract_prompt_from_file(py_file)
            if result:
                prompt_type = result['prompt_type']
                prompt_template = result['prompt_template']

                # Handle duplicate prompt types (add filename suffix if needed)
                if prompt_type in prompts[center]:
                    print(f"  Warning: Duplicate prompt type '{prompt_type}' in {center}. "
                          f"Using filename: {result['filename']}")
                    # Use filename as key if duplicate
                    prompts[center][prompt_type] = prompt_template
                else:
                    prompts[center][prompt_type] = prompt_template

                print(f"  ✓ Extracted: {prompt_type}")
            else:
                print(f"  ✗ Failed to extract from: {py_file.name}")

    return prompts


def save_prompts(prompts: Dict[str, Dict[str, str]], output_file: Path):
    """
    Save prompts to a JSON file.
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(prompts, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Prompts saved to {output_file}")


def main():
    """
    Main function to process all scripts and generate the prompts file.
    """
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    base_dir = script_dir

    print("=" * 60)
    print("Prompt Extraction Script")
    print("=" * 60)

    # Process all scripts
    prompts = process_all_scripts(base_dir)

    # Save to JSON file
    output_file = base_dir / 'prompts.json'
    save_prompts(prompts, output_file)

    # Print summary
    print("\n" + "=" * 60)
    print("Summary:")
    print("=" * 60)
    for center, center_prompts in prompts.items():
        print(f"{center}: {len(center_prompts)} prompt types")
        for prompt_type in sorted(center_prompts.keys()):
            print(f"  - {prompt_type}")

    print(
        f"\nTotal prompts extracted: {sum(len(p) for p in prompts.values())}")
    print(
        f"\nAccess prompts using: prompts['{list(prompts.keys())[0]}']['{list(list(prompts.values())[0].keys())[0] if prompts else 'prompt_type'}']")


if __name__ == '__main__':
    main()
