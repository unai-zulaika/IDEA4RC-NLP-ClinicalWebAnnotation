#!/usr/bin/env python3
"""
Simple script to generate and display full prompts (with few-shot examples and note text)
exactly as they are executed in evaluate_llm_int_prompts.py

This version works without heavy dependencies by manually constructing prompts.
"""

import json
import pandas as pd
from pathlib import Path
import tempfile
import os
import time
import re


def adapt_template(template: str) -> str:
    """Adapt template from prompts.json format to model_runner format."""
    # Replace {{note_original_text}} with {note}
    adapted = template.replace('{{note_original_text}}', '{note}')
    # Replace {few_shot_examples} with {fewshots}
    adapted = adapted.replace('{few_shot_examples}', '{fewshots}')
    # Remove {static_samples} placeholder
    adapted = adapted.replace('{static_samples}\n', '')
    adapted = adapted.replace('{static_samples}', '')
    # Remove {{annotation}} placeholder at the end
    adapted = adapted.replace('{{annotation}}', '')
    return adapted.strip()


def format_fewshots(fewshot_examples: list) -> str:
    """Format few-shot examples as model_runner does."""
    return "\n".join(
        f"Example:\n- Medical Note: {n}\n- Annotation: {a}\n"
        for (n, a) in fewshot_examples
    )


def build_prompt(template: str, fewshots: list, note_text: str) -> str:
    """Build the full prompt exactly as model_runner.get_prompt() does."""
    fewshots_text = format_fewshots(fewshots)
    return template.format(fewshots=fewshots_text, note=note_text)


def map_annotation_to_prompt(annotation_text: str, prompt_key: str) -> bool:
    """
    Check if an annotation matches a specific prompt type.
    Same logic as in fewshot_builder.py
    """
    annotation_lower = annotation_text.lower().strip()
    
    prompt_patterns = {
        'gender-int': [r'^patient\'?s gender', r'^gender'],
        'biopsygrading-int': [r'biopsy grading.*fnclcc', r'^biopsy grading'],
        'surgerymargins-int': [r'^margins after surgery', r'^margins'],
        'tumordepth-int': [r'^tumor depth'],
        'biopsymitoticcount-int': [r'^biopsy mitotic count', r'unknown biopsy mitotic count'],
        'reexcision-int': [r're-?excision', r'radicalization'],
        'necrosis_in_biopsy-int': [r'necrosis in biopsy'],
        'previous_cancer_treatment-int': [r'^previous cancer treatment', r'no previous cancer'],
        'chemotherapy_start-int': [r'chemotherapy.*started on', r'pre-operative chemotherapy', r'post-operative chemotherapy'],
        'surgerytype-fs30-int': [r'^primary surgery was performed', r'^surgery was performed', r'^surgery was not performed'],
        'radiotherapy_start-int': [r'radiotherapy.*started', r'pre-operative radiotherapy', r'post-operative radiotherapy'],
        'recurrencetype-int': [r'^type of recurrence', r'recurrence/progression'],
        'radiotherapy_end-int': [r'radiotherapy.*ended on', r'radiotherapy in total of'],
        'tumorbiopsytype-int': [r'baseline/primary tumor.*biopsy has been performed', r'biopsy has been performed'],
        'necrosis_in_surgical-int': [r'necrosis in surgical'],
        'tumordiameter-int': [r'^tumor longest diameter', r'tumor longest diameter unknown'],
        'patient-status-int': [r'^status of the patient', r'last follow-up'],
        'response-to-int': [r'^response to.*radiotherapy', r'^response to.*chemotherapy'],
        'stage_at_diagnosis-int': [r'^stage at diagnosis', r'unknown.*stage at diagnosis', r'unknown stage'],
        'chemotherapy_end-int': [r'chemotherapy ended on', r'pre-operative chemotherapy ended', r'post-operative chemotherapy ended'],
        'occurrence_cancer-int': [r'^occurrence of other cancer', r'^no previous or concurrent cancers', r'no information about occurrence'],
        'surgical-specimen-grading-int': [r'surgical specimen grading.*fnclcc', r'^surgical specimen grading'],
        'ageatdiagnosis-int': [r'^age at diagnosis'],
        'recur_or_prog-int': [r'^there was.*progression', r'^there was.*recurrence', r'no progression/recurrence'],
        'histological-tipo-int': [r'^histological type', r'icd-o-3'],
        'surgical-mitotic-count-int': [r'^surgical specimen mitotic count', r'unknown surgical specimen mitotic count'],
        'tumorsite-int': [r'^tumor site']
    }
    
    patterns = prompt_patterns.get(prompt_key, [])
    for pattern in patterns:
        if re.search(pattern, annotation_lower, re.IGNORECASE):
            return True
    return False


def load_fewshot_examples_from_json(json_file_path: Path, prompt_type: str, note_text: str, k: int = 5) -> list:
    """
    Load few-shot examples from JSON, using text spans from supporting_text_spans
    instead of full note text, exactly as fewshot_builder.py does.
    """
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    examples = []
    for patient in data:
        for note in patient.get('notes', []):
            note_text_full = note.get('text', '')
            annotations = note.get('annotations', [])
            annotations_with_spans = note.get('annotations_with_spans', [])
            
            # Find matching annotation for this prompt type
            for annotation in annotations:
                if map_annotation_to_prompt(annotation, prompt_type):
                    # Try to find corresponding annotation_with_spans
                    context_text = note_text_full  # Default to full note text
                    
                    if annotations_with_spans:
                        # Find the matching annotation_with_spans entry
                        for ann_with_spans in annotations_with_spans:
                            if ann_with_spans.get('template_text') == annotation:
                                # Extract all text spans and combine them
                                supporting_spans = ann_with_spans.get('supporting_text_spans', [])
                                if supporting_spans:
                                    # Extract text from each span and join with separator
                                    span_texts = [span.get('text', '').strip() 
                                                 for span in supporting_spans 
                                                 if span.get('text', '').strip()]
                                    if span_texts:
                                        # Join spans with " ... " separator for readability
                                        context_text = " ... ".join(span_texts)
                                    break  # Found matching annotation, use its spans
                    
                    examples.append((context_text, annotation))
                    if len(examples) >= k:
                        return examples
                    break  # Only take first matching annotation per note
    
    return examples


def main(
    notes_csv_path: str | Path = None,
    json_file_path: str | Path = None,
    prompts_json_path: str | Path = None,
    fewshot_k: int = 5,
    num_examples: int = 3,
    use_fewshots: bool = True
):
    """Generate and display full prompts."""
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
    
    # Step 2: Load and adapt prompts
    print("\n[STEP 2] Loading and adapting prompts...")
    with open(prompts_json_path, 'r', encoding='utf-8') as f:
        prompts_data = json.load(f)
    
    int_prompts = prompts_data.get('INT', {})
    adapted_prompts = {}
    for prompt_key, template in int_prompts.items():
        adapted_prompts[prompt_key] = adapt_template(template)
    
    prompt_types = list(adapted_prompts.keys())
    print(f"  Loaded {len(prompt_types)} prompt types")
    
    # Step 3: Load few-shot examples (if using)
    fewshot_data = None
    if use_fewshots and json_file_path.exists():
        print("\n[STEP 3] Loading few-shot examples from JSON...")
        with open(json_file_path, 'r', encoding='utf-8') as f:
            fewshot_data = json.load(f)
        print("  Few-shot data loaded")
    else:
        print("\n[STEP 3] Skipping few-shot examples (zero-shot mode)")
    
    # Step 4: Generate prompts
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
            
            # Pick a prompt type for this note
            prompt_type = prompt_types[example_count % len(prompt_types)]
            template = adapted_prompts[prompt_type]
            
            print(f"\n  Generating prompt {example_count + 1}/{num_examples}")
            print(f"    Note ID: {note_id}")
            print(f"    Report Type: {report_type}")
            print(f"    Prompt Type: {prompt_type}")
            
            # Get fewshot examples
            fewshot_examples = []
            if use_fewshots and fewshot_data:
                fewshot_examples = load_fewshot_examples_from_json(
                    json_file_path, prompt_type, note_text, k=fewshot_k
                )
                print(f"    Few-shot examples retrieved: {len(fewshot_examples)}")
            else:
                print(f"    Few-shot examples: 0 (zero-shot mode)")
            
            # Build prompt exactly as model_runner does
            prompt = build_prompt(template, fewshot_examples, note_text)
            
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
    parser.add_argument("--notes-csv", type=str, help="Path to first_patient_notes.csv")
    parser.add_argument("--json-file", type=str, help="Path to annotated JSON file")
    parser.add_argument("--prompts-json", type=str, help="Path to FBK_scripts/prompts.json")
    parser.add_argument("--fewshot-k", type=int, default=5, help="Number of fewshot examples")
    parser.add_argument("--num-examples", type=int, default=3, help="Number of prompts to generate")
    parser.add_argument("--no-fewshots", action="store_true", help="Zero-shot mode")
    
    args = parser.parse_args()
    
    main(
        notes_csv_path=args.notes_csv,
        json_file_path=args.json_file,
        prompts_json_path=args.prompts_json,
        fewshot_k=args.fewshot_k,
        num_examples=args.num_examples,
        use_fewshots=not args.no_fewshots
    )

