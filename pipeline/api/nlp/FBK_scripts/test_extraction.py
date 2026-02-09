#!/usr/bin/env python3
"""Simple test to verify prompt extraction works."""

from pathlib import Path
from script_processor import extract_prompt_from_file

# Test on one file
test_file = Path("INT-Sarc-latest-scripts/llama3.1-8b-instruct-biopsygrading-int-sarc.py")
result = extract_prompt_from_file(test_file)

if result:
    print("✓ Extraction successful!")
    print(f"Prompt Type: {result['prompt_type']}")
    print(f"\nPrompt Template (first 200 chars):\n{result['prompt_template'][:200]}...")
else:
    print("✗ Extraction failed")

