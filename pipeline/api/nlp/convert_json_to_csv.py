#!/usr/bin/env python3
"""
Script to convert annotated_patient_notes.json to CSV format.
Only processes the first patient.
Also creates a mapping of notes to annotations per INT prompt type.
"""

import json
import csv
from pathlib import Path
import re
import unicodedata

def clean_text(text):
    """
    Clean text by removing newlines and rare/control characters.
    
    Args:
        text: Input text string
    
    Returns:
        Cleaned text string
    """
    if not text:
        return ''
    
    # Replace newlines and carriage returns with spaces
    text = text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    
    # Replace multiple consecutive spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    
    # Remove control characters (except common whitespace)
    # Keep printable characters and common whitespace
    cleaned = []
    for char in text:
        # Keep printable characters, spaces, tabs
        if unicodedata.category(char)[0] != 'C' or char in [' ', '\t']:
            cleaned.append(char)
        # Replace other control characters with space
        elif unicodedata.category(char) == 'Cc':
            cleaned.append(' ')
    
    text = ''.join(cleaned)
    
    # Normalize unicode (e.g., convert composed characters to decomposed or vice versa)
    # This helps fix encoding issues like M-CM- sequences
    text = unicodedata.normalize('NFKC', text)
    
    # Final cleanup: remove any remaining control characters and normalize whitespace
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)  # Remove remaining control chars
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
    text = text.strip()  # Remove leading/trailing whitespace
    
    return text


def convert_json_to_csv(json_file_path, output_csv_path):
    """
    Convert JSON patient notes to CSV format.
    
    Args:
        json_file_path: Path to the input JSON file
        output_csv_path: Path to the output CSV file
    """
    # Read the JSON file
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Get the first patient
    if not data or len(data) == 0:
        print("Error: JSON file is empty or has no patients.")
        return
    
    first_patient = data[0]
    
    if 'notes' not in first_patient:
        print("Error: First patient has no 'notes' field.")
        return
    
    notes = first_patient['notes']
    
    if not notes:
        print("Warning: First patient has no notes.")
        return
    
    # Write to CSV with semicolon delimiter
    with open(output_csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        
        # Write header
        writer.writerow(['text', 'date', 'p_id', 'note_id', 'report_type'])
        
        # Write each note as a row
        for note in notes:
            text = clean_text(note.get('text', ''))
            date = clean_text(note.get('date', ''))
            p_id = clean_text(str(note.get('p_id', '')))
            note_id = clean_text(str(note.get('note_id', '')))
            report_type = clean_text(note.get('report_type', ''))
            
            writer.writerow([text, date, p_id, note_id, report_type])
    
    print(f"Successfully converted {len(notes)} notes from first patient to {output_csv_path}")


def map_annotation_to_prompt(annotation_text, prompt_key):
    """
    Check if an annotation matches a specific prompt type.
    
    Args:
        annotation_text: The annotation string from the JSON
        prompt_key: The prompt key (e.g., 'gender-int', 'biopsygrading-int')
    
    Returns:
        bool: True if the annotation matches the prompt type
    """
    annotation_lower = annotation_text.lower().strip()
    
    # Mapping of prompt keys to annotation patterns (must match at the start or be a key phrase)
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


def map_notes_to_prompts(json_file_path, prompts_file_path, output_csv_path):
    """
    Map notes and their annotations to INT prompt types.
    
    Args:
        json_file_path: Path to the annotated_patient_notes.json file
        prompts_file_path: Path to the prompts.json file
        output_csv_path: Path to the output CSV file
    """
    # Read the JSON file
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Read the prompts file
    with open(prompts_file_path, 'r', encoding='utf-8') as f:
        prompts_data = json.load(f)
    
    # Get INT prompts
    int_prompts = prompts_data.get('INT', {})
    prompt_keys = list(int_prompts.keys())
    
    # Get the first patient
    if not data or len(data) == 0:
        print("Error: JSON file is empty or has no patients.")
        return
    
    first_patient = data[0]
    
    if 'notes' not in first_patient:
        print("Error: First patient has no 'notes' field.")
        return
    
    notes = first_patient['notes']
    
    if not notes:
        print("Warning: First patient has no notes.")
        return
    
    # Prepare data for CSV
    rows = []
    
    # For each note, check each prompt type
    for note in notes:
        note_id = clean_text(str(note.get('note_id', '')))
        note_text = note.get('text', '')
        date = clean_text(note.get('date', ''))
        p_id = clean_text(str(note.get('p_id', '')))
        report_type = clean_text(note.get('report_type', ''))
        annotations = note.get('annotations', [])
        
        # For each prompt type, find matching annotations
        for prompt_key in prompt_keys:
            matching_annotations = []
            
            for annotation in annotations:
                if map_annotation_to_prompt(annotation, prompt_key):
                    matching_annotations.append(clean_text(annotation))
            
            # Create a row for this note-prompt combination
            # If no matching annotation found, still create a row with empty annotation
            matching_annotation_text = ' | '.join(matching_annotations) if matching_annotations else ''
            all_annotations_text = ' | '.join([clean_text(ann) for ann in annotations])
            
            # Clean and truncate note text preview
            note_text_cleaned = clean_text(note_text)
            note_text_preview = note_text_cleaned[:200] + '...' if len(note_text_cleaned) > 200 else note_text_cleaned
            
            rows.append({
                'note_id': note_id,
                'date': date,
                'p_id': p_id,
                'report_type': report_type,
                'prompt_type': prompt_key,
                'matching_annotation': matching_annotation_text,
                'all_annotations': all_annotations_text,
                'note_text_preview': note_text_preview
            })
    
    # Write to CSV
    with open(output_csv_path, 'w', encoding='utf-8', newline='') as f:
        if rows:
            fieldnames = ['note_id', 'date', 'p_id', 'report_type', 'prompt_type', 
                         'matching_annotation', 'all_annotations', 'note_text_preview']
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
    
    print(f"Successfully created annotation mapping for {len(notes)} notes and {len(prompt_keys)} prompt types")
    print(f"Total rows: {len(rows)}")
    print(f"Output saved to: {output_csv_path}")


if __name__ == '__main__':
    # Set file paths
    json_file = Path(__file__).parent / 'annotated_patient_notes.json'
    output_file = Path(__file__).parent / 'first_patient_notes.csv'
    prompts_file = Path(__file__).parent / 'FBK_scripts' / 'prompts.json'
    mapping_output_file = Path(__file__).parent / 'first_patient_notes_annotation_mapping.csv'
    
    # Convert to CSV
    convert_json_to_csv(json_file, output_file)
    
    # Map annotations to prompts
    map_notes_to_prompts(json_file, prompts_file, mapping_output_file)

