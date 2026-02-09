#!/usr/bin/env python3
"""
Script to generate and display full prompts (with few-shot examples and note text)
exactly as they are executed in evaluate_llm_int_prompts.py

Usage:
    python show_prompts.py [--notes-csv PATH] [--json-file PATH] [--prompts-json PATH] 
                           [--faiss-dir PATH] [--fewshot-k K] [--num-examples N]
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import sys
import tempfile
import os
import time

# Import our modules
from prompt_adapter import adapt_int_prompts
from model_runner import get_prompt

# Import model_runner module to access _PROMPTS
import model_runner as mr

# Conditionally import FewshotBuilder (may fail if faiss/numpy not available)
try:
    from fewshot_builder import FewshotBuilder
    FEWSHOT_BUILDER_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] FewshotBuilder not available: {e}")
    print(f"[WARN] Will run in zero-shot mode only")
    FewshotBuilder = None
    FEWSHOT_BUILDER_AVAILABLE = False


def load_adapted_prompts(prompts_json_path: str | Path):
    """Adapt INT prompts and load them into model_runner's global _PROMPTS."""
    print("[INFO] Adapting INT prompts for model_runner...")
    adapted_prompts = adapt_int_prompts(prompts_json_path)
    mr._PROMPTS = adapted_prompts
    print(f"[INFO] Loaded {len(adapted_prompts)} adapted prompts into model_runner")


def main(
    notes_csv_path: str | Path = None,
    json_file_path: str | Path = None,
    prompts_json_path: str | Path = None,
    faiss_store_dir: str | Path = "faiss_store",
    fewshot_k: int = 5,
    num_examples: int = 3,  # Number of note-prompt combinations to show
    use_fewshots: bool = True
):
    """
    Generate and display full prompts exactly as executed in evaluation script.
    
    Args:
        notes_csv_path: Path to first_patient_notes.csv
        json_file_path: Path to annotated_patient_notes_with_spans_full_verified.json
        prompts_json_path: Path to FBK_scripts/prompts.json
        faiss_store_dir: Directory for FAISS indexes
        fewshot_k: Number of fewshot examples to retrieve
        num_examples: Number of note-prompt combinations to generate
        use_fewshots: Whether to include few-shot examples
    """
    script_dir = Path(__file__).resolve().parent
    
    # Set default paths
    if notes_csv_path is None:
        notes_csv_path = script_dir / "first_patient_notes.csv"
    if json_file_path is None:
        json_file_path = script_dir / "annotated_patient_notes_with_spans_full_verified.json"
        if not Path(json_file_path).exists():
            json_file_path = script_dir / "annotated_patient_notes.json"
    if prompts_json_path is None:
        prompts_json_path = script_dir / "FBK_scripts" / "prompts.json"
    
    notes_csv_path = Path(notes_csv_path)
    json_file_path = Path(json_file_path)
    prompts_json_path = Path(prompts_json_path)
    
    print("=" * 80)
    print("PROMPT GENERATOR - Full Prompts with Few-shot Examples")
    print("=" * 80)
    print(f"Mode: {'Few-shot' if use_fewshots else 'Zero-shot'} (k={fewshot_k if use_fewshots else 0})")
    print(f"Number of examples to generate: {num_examples}")
    print("=" * 80)
    
    # Step 1: Load data
    print("\n[STEP 1] Loading data...")
    print(f"  Loading notes from: {notes_csv_path}")
    notes_df = pd.read_csv(notes_csv_path, delimiter=';', encoding='utf-8')
    print(f"  Loaded {len(notes_df)} notes")
    
    # Step 2: Adapt and load prompts
    print("\n[STEP 2] Adapting prompts...")
    load_adapted_prompts(prompts_json_path)
    prompt_types = list(mr._PROMPTS.keys())
    print(f"  Available prompt types: {len(prompt_types)}")
    
    # Step 3: Initialize FAISS builder (if using fewshots)
    builder = None
    if use_fewshots:
        if not FEWSHOT_BUILDER_AVAILABLE:
            print("\n[STEP 3] FewshotBuilder not available, switching to zero-shot mode...")
            use_fewshots = False
        else:
            print("\n[STEP 3] Setting up FAISS indexes for few-shot examples...")
            builder = FewshotBuilder(store_dir=faiss_store_dir, use_gpu=True)
        
        # Check if indexes exist
        if not (Path(faiss_store_dir) / "gender-int.index").exists():
            print(f"  [WARN] FAISS indexes not found in {faiss_store_dir}")
            print(f"  [WARN] Run evaluate_llm_int_prompts.py first to build indexes")
            print(f"  [INFO] Continuing without few-shot examples...")
            use_fewshots = False
            builder = None
        else:
            print("  Preloading FAISS indexes into memory...")
            builder.preload_all_indexes(prompt_types)
            print("  FAISS indexes ready")
    else:
        print("\n[STEP 3] Skipping FAISS setup (zero-shot mode)")
    
    # Step 4: Generate prompts for example note-prompt combinations
    print(f"\n[STEP 4] Generating {num_examples} example prompts...")
    
    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
    temp_path = temp_file.name
    
    try:
        temp_file.write("=" * 80 + "\n")
        temp_file.write("FULL PROMPTS (as executed in evaluate_llm_int_prompts.py)\n")
        temp_file.write("=" * 80 + "\n\n")
        
        example_count = 0
        for idx, (_, note_row) in enumerate(notes_df.iterrows()):
            if example_count >= num_examples:
                break
            
            note_id = note_row['note_id']
            note_text = note_row['text']
            report_type = note_row['report_type']
            
            # Pick a prompt type for this note (cycle through available prompts)
            prompt_type = prompt_types[example_count % len(prompt_types)]
            
            print(f"\n  Generating prompt {example_count + 1}/{num_examples}")
            print(f"    Note ID: {note_id}")
            print(f"    Report Type: {report_type}")
            print(f"    Prompt Type: {prompt_type}")
            
            # Get fewshot examples (or use empty list if disabled)
            if use_fewshots and builder is not None:
                fewshot_examples = builder.get_fewshot_examples(
                    prompt_type,
                    note_text,
                    k=fewshot_k
                )
                print(f"    Few-shot examples retrieved: {len(fewshot_examples)}")
            else:
                fewshot_examples = []
                print(f"    Few-shot examples: 0 (zero-shot mode)")
            
            # Build prompt using model_runner's get_prompt (exactly as evaluation script does)
            prompt = get_prompt(
                task_key=prompt_type,
                fewshots=fewshot_examples,
                note_text=note_text
            )
            
            # Write to file
            temp_file.write(f"\n{'=' * 80}\n")
            temp_file.write(f"EXAMPLE {example_count + 1}/{num_examples}\n")
            temp_file.write(f"{'=' * 80}\n\n")
            temp_file.write(f"Note ID: {note_id}\n")
            temp_file.write(f"Report Type: {report_type}\n")
            temp_file.write(f"Prompt Type: {prompt_type}\n")
            temp_file.write(f"Few-shot Examples: {len(fewshot_examples)}\n")
            temp_file.write(f"Prompt Length: {len(prompt)} characters\n")
            temp_file.write(f"\n{'-' * 80}\n")
            temp_file.write("FULL PROMPT:\n")
            temp_file.write(f"{'-' * 80}\n\n")
            temp_file.write(prompt)
            temp_file.write("\n\n")
            
            example_count += 1
        
        temp_file.close()
        
        # Read and print the file contents
        print("\n" + "=" * 80)
        print("FULL PROMPTS (copy these):")
        print("=" * 80 + "\n")
        with open(temp_path, 'r', encoding='utf-8') as f:
            content = f.read()
            print(content)
        print("=" * 80)
        print(f"\nFile location: {temp_path}")
        print("File will be deleted in 5 seconds...")
        time.sleep(5)
        
    finally:
        # Delete the file
        if os.path.exists(temp_path):
            os.unlink(temp_path)
            print(f"\nFile {temp_path} has been deleted.")
        else:
            print(f"\nFile {temp_path} was already removed.")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate and display full prompts with few-shot examples"
    )
    parser.add_argument(
        "--notes-csv",
        type=str,
        help="Path to first_patient_notes.csv"
    )
    parser.add_argument(
        "--json-file",
        type=str,
        help="Path to annotated_patient_notes_with_spans_full_verified.json"
    )
    parser.add_argument(
        "--prompts-json",
        type=str,
        help="Path to FBK_scripts/prompts.json"
    )
    parser.add_argument(
        "--faiss-dir",
        type=str,
        default="faiss_store",
        help="Directory for FAISS indexes"
    )
    parser.add_argument(
        "--fewshot-k",
        type=int,
        default=5,
        help="Number of fewshot examples to retrieve"
    )
    parser.add_argument(
        "--num-examples",
        type=int,
        default=3,
        help="Number of note-prompt combinations to generate"
    )
    parser.add_argument(
        "--no-fewshots",
        action="store_true",
        help="Run in zero-shot mode without few-shot examples"
    )
    
    args = parser.parse_args()
    
    main(
        notes_csv_path=args.notes_csv,
        json_file_path=args.json_file,
        prompts_json_path=args.prompts_json,
        faiss_store_dir=args.faiss_dir,
        fewshot_k=args.fewshot_k,
        num_examples=args.num_examples,
        use_fewshots=not args.no_fewshots
    )

