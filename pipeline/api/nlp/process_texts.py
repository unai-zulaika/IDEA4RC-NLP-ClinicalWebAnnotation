"""
NLP Text Processing Module

This module provides functions for processing medical texts using LLMs and regex-based extraction.

MAIN WORKFLOW (process_texts):
================================
Input: Clinical notes DataFrame (text, date, p_id, note_id, report_type)
  ↓
Step 1: LLM Annotation (process_texts_with_llm)
  - Run LLM with multiple prompts on each text
  - Generate structured annotations
  - Parse multiple values from single annotation
  ↓
Step 2: Regex Pattern Matching
  - Apply regex patterns to LLM annotations
  - Extract structured values using sarcoma_dictionary patterns
  ↓
Step 3: Data Integration
  - Map to core_variables
  - Handle patient_id propagation
  - Use extracted dates or fall back to note dates
  - Manage record_ids for entity grouping
  ↓
Output: Structured excel_data DataFrame with extracted entities

Key Features:
- process_texts: Main pipeline function (LLM → Regex → Structured Data)
- process_texts_with_llm: LLM annotation with multiple value extraction
- llm_annotations_to_excel_format: Direct LLM-to-Excel conversion (alternative path)
- parse_annotation_values: Smart parsing of multiple values from annotations

The LLM processor can parse multiple values from annotations in various formats:
- JSON arrays: ["value1", "value2", "value3"]
- Comma-separated: value1, value2, value3
- Semicolon-separated: value1; value2; value3
- Newline-separated lists (with or without bullets/numbers)

Date Handling:
- Primary: Dates extracted by LLM from annotation text
- Fallback: Original note date if extraction fails

Patient ID: Carried through entire pipeline from input to output

See PROCESSING_WORKFLOW.md for detailed documentation.
"""

from transformers import pipeline  # type: ignore  # Example NLP library
import pandas
import re
from pathlib import Path
import json
from typing import Dict, List

from nlp.model_runner import get_prompt, init_model, load_prompts_from_json, run_model_with_prompt
import nlp.model_runner as model_runner_module
from nlp.processing_utils import (
    first_group as _first_group,
    is_duplicate_row as _is_duplicate_row,
    is_invalid_value as _is_invalid_value,
    to_str as _to_str,
    parse_date_any as _parse_date_any,  # <-- added
)
from nlp.special_handlers import SPECIAL_HANDLERS, SPECIAL_HANDLERS_AFTER


types_map = {
    "ENUM": "CodeableConcept",
    "NUMBER": "float",
    "DATE": "date in the ISO format ISO8601  https://en.wikipedia.org/wiki/ISO_8601 ",
    "TEXT": "string",
    "DEFAULT": "CodeableConcept",
}


def process_texts_with_llm(
    texts: pandas.DataFrame,
    model_path: str = None,
    prompts_json_path: str = None,
    fewshots_dict: Dict[str, List[tuple]] = None,
    parse_multiple_values: bool = True,
    task_id: str = None,
    is_cancelled_callback=None,
    report_type_mapping: Dict[str, List[str]] | None = None
) -> pandas.DataFrame:
    """
    Process texts row by row using the LLM for each prompt type.

    Args:
        texts (pandas.DataFrame): DataFrame with columns: text, date, p_id, note_id, report_type
        excel_data (pandas.DataFrame): Existing Excel data (not used but kept for compatibility)
        model_path (str): Path to the LLM model file. If None, uses default path.
        prompts_json_path (str): Path to prompts.json. If None, uses default path.
        fewshots_dict (Dict[str, List[tuple]]): Dictionary mapping prompt_type to list of (text, annotation) tuples.
                                                 If None, uses empty fewshots.
        parse_multiple_values (bool): If True, attempts to parse multiple values from a single annotation.
                                      Supports JSON arrays, comma-separated, semicolon-separated, and newline-separated values.
                                      Each value will create a separate row in the output.
        task_id (str): Optional task ID for cancellation checking
        is_cancelled_callback (callable): Optional callback function to check if task is cancelled
        report_type_mapping (Dict[str, List[str]]): Optional mapping of report_type -> list of prompt types.
                                                     If provided, only runs prompts relevant to each note's report_type.
                                                     If None or empty, runs all prompts for all notes.

    Returns:
        pandas.DataFrame: DataFrame with columns: prompt_type, annotation, p_id, date, note_id, report_type, raw_output

    Raises:
        RuntimeError: If task is cancelled during processing
    """

    # Set default paths
    script_dir = Path(__file__).resolve().parent

    if prompts_json_path is None:
        prompts_json_path = script_dir / "prompts.json"

    if model_path is None:
        model_path = script_dir / "meta-llama-3.1-8b-instruct-q4_k_m.gguf"

    # Initialize model and load prompts
    print("[INFO] Loading prompts...")
    # Check if this is FBK_scripts/prompts.json (INT format) and adapt if needed
    import json
    try:
        with open(prompts_json_path, "r", encoding="utf-8") as f:
            prompts_data = json.load(f)
        if 'INT' in prompts_data:
            # This is an INT prompts file, need to adapt it
            print("[INFO] Detected INT prompts format, adapting for model_runner...")
            from nlp.prompt_adapter import adapt_int_prompts
            adapted_prompts = adapt_int_prompts(prompts_json_path)
            # Set the global _PROMPTS variable in model_runner module
            # Use the module-level import to ensure we're modifying the same module instance
            model_runner_module._PROMPTS = adapted_prompts
            print(f"[INFO] Loaded {len(adapted_prompts)} adapted INT prompts")
            # Verify it worked by checking the module's _PROMPTS
            if len(model_runner_module._PROMPTS) == 0:
                print(f"[ERROR] Failed to load prompts into model_runner._PROMPTS")
            else:
                print(f"[INFO] Verified {len(model_runner_module._PROMPTS)} prompts loaded successfully")
        else:
            # Regular format, use normal loader
            load_prompts_from_json(prompts_json_path)
    except Exception as e:
        print(f"[WARN] Error checking prompts format: {e}, using default loader")
        load_prompts_from_json(prompts_json_path)

    print("[INFO] Initializing model...")
    init_model(str(model_path))

    # Get all available prompt types
    import json
    
    # Check if we loaded adapted INT prompts by checking model_runner's _PROMPTS
    # After loading, _PROMPTS should contain the prompts
    if len(model_runner_module._PROMPTS) > 0:
        # Use adapted prompts from model_runner
        prompt_types = list(model_runner_module._PROMPTS.keys())
    else:
        # Use prompts from JSON file (fallback)
        with open(prompts_json_path, "r", encoding="utf-8") as f:
            prompts_config = json.load(f)
        # Handle both regular format and INT format
        if 'INT' in prompts_config:
            # INT format - we should have already adapted it above
            # But if we get here, something went wrong, so use INT prompts directly
            prompt_types = list(prompts_config['INT'].keys())
        else:
            prompt_types = list(prompts_config.keys())
    print(f"[INFO] Found {len(prompt_types)} prompt types: {prompt_types}")
    
    # Check if report type filtering is enabled
    use_report_type_filtering = report_type_mapping is not None and len(report_type_mapping) > 0
    if use_report_type_filtering:
        print(f"[INFO] Report type filtering: ENABLED ({len(report_type_mapping)} report types mapped)")
        # Validate that mapped prompts exist in prompts.json
        all_mapped_prompts = set()
        for report_type, prompts in report_type_mapping.items():
            all_mapped_prompts.update(prompts)
        missing_prompts = all_mapped_prompts - set(prompt_types)
        if missing_prompts:
            print(f"[WARN] {len(missing_prompts)} prompt(s) in mapping don't exist in prompts.json: {sorted(missing_prompts)}")
            print(f"[WARN] These prompts will be skipped during processing")
    else:
        print("[INFO] Report type filtering: DISABLED (running all prompts for all notes)")

    # Initialize fewshots if not provided
    if fewshots_dict is None:
        fewshots_dict = {pt: [] for pt in prompt_types}

    # Prepare results list
    results = []

    # Process each row in texts
    total_rows = len(texts)
    for idx, row in texts.iterrows():
        # Check for cancellation at the start of each text processing
        if is_cancelled_callback and task_id and is_cancelled_callback(task_id):
            print(
                f"[WARN] Task {task_id} cancelled during text processing at row {idx + 1}/{total_rows}")
            raise RuntimeError(f"Task {task_id} was cancelled by user")

        text = row.get("text", "")
        date = row.get("date", "")
        p_id = row.get("p_id", "")
        note_id = row.get("note_id", "")
        report_type = row.get("report_type", "")

        print(
            f"[INFO] Processing row {idx + 1}/{total_rows} - Patient: {p_id}, Note: {note_id}, Report Type: {report_type}")

        # Determine which prompts to run for this note
        if use_report_type_filtering:
            allowed_prompts = report_type_mapping.get(report_type, prompt_types)
            # Filter out prompts that don't exist in the actual prompts.json
            allowed_prompts = [pt for pt in allowed_prompts if pt in prompt_types]
            if len(allowed_prompts) < len(report_type_mapping.get(report_type, [])):
                skipped = len(report_type_mapping.get(report_type, [])) - len(allowed_prompts)
                print(f"  [WARN] Skipped {skipped} prompt(s) from mapping that don't exist in prompts.json")
            if len(allowed_prompts) < len(prompt_types):
                print(f"  [INFO] Filtered prompts: {len(allowed_prompts)}/{len(prompt_types)} prompts relevant to {report_type}")
            if len(allowed_prompts) == 0:
                print(f"  [WARN] No valid prompts found for report_type '{report_type}' - skipping this note")
                continue
        else:
            allowed_prompts = prompt_types

        # Run model for each allowed prompt type
        for prompt_type in allowed_prompts:
            print(f"  - Running prompt type: {prompt_type}")

            # Get fewshots for this prompt type
            fewshots = fewshots_dict.get(prompt_type, [])

            # Build the prompt
            prompt = get_prompt(
                task_key=prompt_type,
                fewshots=fewshots,
                note_text=text
            )

            print(f"    [DEBUG] Prompt:\n{prompt}\n")

            print("***" * 20)

            # Run the model
            try:
                output = run_model_with_prompt(
                    prompt=prompt,
                    max_new_tokens=256,
                    temperature=0.1
                )

                annotation = output["normalized"]
                raw_output = output["raw"]

                print(f"    [DEBUG] Raw Output:\n{raw_output}\n")
                print("####" * 20)

                # Clean annotation: remove "Annotation: " prefix if present
                if annotation and isinstance(annotation, str):
                    # Remove case-insensitive "Annotation:" or "Annotation :" prefix
                    annotation = re.sub(
                        r'^\s*annotation\s*:\s*', '', annotation, flags=re.IGNORECASE).strip()

                # Parse annotation to extract multiple values if enabled
                if parse_multiple_values:
                    annotation_values = parse_annotation_values(annotation)
                else:
                    annotation_values = [annotation]

                # Create a row for each extracted value
                for annotation_value in annotation_values:
                    # Extract dates from annotation if present (optional enhancement)
                    extracted_dates = extract_dates_from_annotation(
                        annotation_value)

                    # Append result
                    results.append({
                        "prompt_type": prompt_type,
                        "annotation": annotation_value,
                        "p_id": p_id,
                        "date": date,
                        "note_id": note_id,
                        "report_type": report_type,
                        "raw_output": raw_output,
                        "extracted_dates": extracted_dates
                    })

            except Exception as e:
                print(
                    f"    [ERROR] Failed to process prompt type {prompt_type}: {e}")
                results.append({
                    "prompt_type": prompt_type,
                    "annotation": f"ERROR: {str(e)}",
                    "p_id": p_id,
                    "date": date,
                    "note_id": note_id,
                    "report_type": report_type,
                    "raw_output": "",
                    "extracted_dates": []
                })

    # Create DataFrame from results
    results_df = pandas.DataFrame(results)

    print(
        f"[INFO] Processing complete. Generated {len(results_df)} annotations.")
    return results_df


def parse_annotation_values(annotation: str) -> List[str]:
    """
    Parse annotation to extract multiple values if present.
    Supports multiple formats:
    - JSON arrays: ["value1", "value2"]
    - Comma-separated: value1, value2, value3
    - Semicolon-separated: value1; value2; value3
    - Newline-separated: value1\nvalue2\nvalue3
    - Bullet points: - value1\n- value2
    - Numbered lists: 1. value1\n2. value2

    Args:
        annotation (str): The annotation text to parse

    Returns:
        List[str]: List of extracted values (single value if no multiple values detected)
    """
    if not annotation or annotation.startswith("ERROR:"):
        return [annotation]

    # Remove leading/trailing whitespace
    annotation = annotation.strip()

    # Try to parse as JSON array
    if annotation.startswith("[") and annotation.endswith("]"):
        try:
            import json
            values = json.loads(annotation)
            if isinstance(values, list):
                # Filter out empty values and convert to strings
                return [str(v).strip() for v in values if v and str(v).strip()]
        except (json.JSONDecodeError, ValueError):
            pass

    # Try to detect and parse delimited values
    # Check for semicolon-separated (higher priority than comma for medical text)
    if ";" in annotation and annotation.count(";") >= 1:
        values = [v.strip() for v in annotation.split(";") if v.strip()]
        if len(values) > 1:
            return values

    # Check for comma-separated (but avoid single sentences with commas)
    if "," in annotation:
        values = [v.strip() for v in annotation.split(",") if v.strip()]
        # Only treat as list if we have 2+ values and none are too long (likely sentences)
        if len(values) > 1 and all(len(v) < 100 for v in values):
            return values

    # Check for newline-separated with bullet points or numbers
    lines = annotation.split("\n")
    if len(lines) > 1:
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Remove bullet points and numbering
            line = re.sub(r"^[-*•]\s+", "", line)  # Bullets
            line = re.sub(r"^\d+[\.)]\s+", "", line)  # Numbers
            if line:
                cleaned_lines.append(line)

        if len(cleaned_lines) > 1:
            return cleaned_lines

    # Check for pipe-separated
    if "|" in annotation:
        values = [v.strip() for v in annotation.split("|") if v.strip()]
        if len(values) > 1:
            return values

    # No multiple values detected, return as single value
    return [annotation]


def extract_dates_from_annotation(annotation: str) -> List[str]:
    """
    Extract dates from annotation text.
    Supports formats: DD/MM/YYYY, YYYY-MM-DD, and other common date patterns.

    Args:
        annotation (str): The annotation text to extract dates from

    Returns:
        List[str]: List of extracted date strings
    """
    date_patterns = [
        r'\d{2}/\d{2}/\d{4}',  # DD/MM/YYYY
        r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
        r'\d{1,2}/\d{1,2}/\d{4}',  # D/M/YYYY or DD/M/YYYY
    ]

    dates = []
    for pattern in date_patterns:
        matches = re.findall(pattern, annotation)
        dates.extend(matches)

    return dates


def process_llm_annotations_with_regex(
    llm_annotations: pandas.DataFrame,
    excel_data: pandas.DataFrame,
    sarcoma_dictionary_path: str = None,
    sarcoma_dictionary_regexp_path: str = None
) -> pandas.DataFrame:
    """
    Process LLM annotations using regex patterns to extract structured data.

    This function takes pre-generated LLM annotations and applies regex patterns
    to extract structured values, which are then added to the excel_data DataFrame.

    Args:
        llm_annotations (pandas.DataFrame): DataFrame with columns: prompt_type, annotation, p_id, date, note_id, report_type, extracted_dates
        excel_data (pandas.DataFrame): Existing Excel data to append to
        sarcoma_dictionary_path (str): Path to sarcoma_dictionary.json. If None, uses default path.
        sarcoma_dictionary_regexp_path (str): Path to sarcoma_dictionary_regexp.json. If None, uses default path.

    Returns:
        pandas.DataFrame: Excel data with new structured data appended
    """

    print("[DEBUG] ========================================")
    print("[DEBUG] Starting process_llm_annotations_with_regex")
    print("[DEBUG] ========================================")

    # Set default paths
    script_dir = Path(__file__).resolve().parent
    if sarcoma_dictionary_path is None:
        sarcoma_dictionary_path = script_dir / "sarcoma_dictionary_updated.json"
    if sarcoma_dictionary_regexp_path is None:
        sarcoma_dictionary_regexp_path = script_dir / "sarcoma_dictionary_regexp.json"

    print(f"[DEBUG] Using sarcoma_dictionary: {sarcoma_dictionary_path}")
    print(
        f"[DEBUG] Using sarcoma_dictionary_regexp: {sarcoma_dictionary_regexp_path}")

    # Validate input DataFrames
    print(f"[DEBUG] Input llm_annotations shape: {llm_annotations.shape}")
    print(
        f"[DEBUG] Input llm_annotations columns: {list(llm_annotations.columns)}")
    print(f"[DEBUG] Input excel_data shape: {excel_data.shape}")
    print(
        f"[DEBUG] Input excel_data columns: {list(excel_data.columns) if not excel_data.empty else 'EMPTY'}")

    # Ensure excel_data has required columns
    if excel_data is None or excel_data.empty:
        print("[DEBUG] excel_data is empty, initializing new DataFrame")
        excel_data = pandas.DataFrame(columns=[
            "patient_id", "original_source", "core_variable",
            "date_ref", "value", "record_id", "note_id", "prompt_type", "types"
        ])

    # Normalize column names for compatibility
    # Common alternate column names -> normalize to patient_id
    if "patient_id" not in excel_data.columns:
        for alt in ("p_id", "excel_data_dfpatient_id", "patient", "patientId"):
            if alt in excel_data.columns:
                print(
                    f"[DEBUG] Renaming '{alt}' to 'patient_id' in excel_data")
                excel_data["patient_id"] = excel_data[alt]
                break

    # Load regex dictionaries
    print("[DEBUG] Loading regex dictionaries...")
    try:
        with sarcoma_dictionary_path.open("r", encoding="utf-8") as file:
            summary_dict: dict[str, str] = json.load(file)
        print(
            f"[DEBUG] Loaded {len(summary_dict)} entries from sarcoma_dictionary.json")

        with sarcoma_dictionary_regexp_path.open("r", encoding="utf-8") as file:
            regexp_dict: dict[str, str] = json.load(file)
        print(
            f"[DEBUG] Loaded {len(regexp_dict)} regex patterns from sarcoma_dictionary_regexp.json")
        missing = [
            aid for aid, data in summary_dict.items()
            if data.get("parameters") and not str(regexp_dict.get(aid, "")).strip()
        ]
        if missing:
            print(
                f"[WARN] {len(missing)} annotations have missing/empty regex patterns. Sample: {missing[:10]}")
    except Exception as e:
        print(f"[ERROR] Failed to load dictionaries: {e}")
        raise

    # Get the biggest record_id from excel_data
    if not excel_data.empty and "record_id" in excel_data.columns:
        try:
            max_record_id = int(excel_data["record_id"].max()) if not pandas.isna(
                excel_data["record_id"].max()) else 0
        except Exception:
            max_record_id = 0
    else:
        max_record_id = 0

    print(f"[DEBUG] Starting record_id: {max_record_id}")

    # Process each LLM annotation
    new_rows = []
    annotation_count = 0
    skipped_count = 0
    error_count = 0

    def _find_nearby_group_record_id(patient_id: str, entity_prefix: str, note_date_str: str) -> int | None:
        """
        Find an existing record_id for the same entity (by core_variable prefix) within ±14 days.
        Searches both existing excel_data and staged new_rows.
        """
        annotation_dt = _parse_date_any(_to_str(note_date_str))
        if not annotation_dt:
            return None
        candidates: list[tuple[int, int]] = []

        def consider_row(row: dict | pandas.Series) -> None:
            try:
                if _to_str(row.get("patient_id")) != _to_str(patient_id):
                    return
                cv = _to_str(row.get("core_variable"))
                if not cv.startswith(entity_prefix):
                    return
                dt = _parse_date_any(_to_str(row.get("date_ref")))
                if not dt:
                    return
                delta = abs((annotation_dt - dt).days)
                if delta <= 14:
                    rid = int(row.get("record_id"))
                    candidates.append((delta, rid))
            except Exception:
                return

        if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
            for _, er in excel_data.iterrows():
                consider_row(er)
        for sr in new_rows:
            consider_row(sr)

        if not candidates:
            return None
        candidates.sort(key=lambda t: (t[0], t[1]))
        return candidates[0][1]

    print(f"[DEBUG] Processing {len(llm_annotations)} LLM annotations...")
    print("[DEBUG] ========================================")

    for index, llm_row in llm_annotations.iterrows():
        print(
            f"\n[DEBUG] --- Processing annotation {index + 1}/{len(llm_annotations)} ---")

        # Extract data from LLM results
        annotation_text = llm_row.get("annotation", "")
        prompt_type = llm_row.get("prompt_type", "")
        patient_id = llm_row.get("p_id", "")
        note_date = llm_row.get("date", "")
        note_id = llm_row.get("note_id", "")

        print(f"[DEBUG] Patient ID: {patient_id}")
        print(f"[DEBUG] Note ID: {note_id}")
        print(f"[DEBUG] Prompt Type: {prompt_type}")
        print(f"[DEBUG] Note Date: {note_date}")
        print(f"[DEBUG] Annotation Text (raw): {annotation_text[:100]}..." if len(str(
            annotation_text)) > 100 else f"[DEBUG] Annotation Text (raw): {annotation_text}")

        # Clean annotation text - remove "Annotation:" prefix if present
        if annotation_text and isinstance(annotation_text, str):
            original_annotation = annotation_text
            annotation_text = annotation_text.replace(
                "Annotation:", "").strip()
            # strip surrounding double quotes if present
            annotation_text = re.sub(r'^"+|"+$', '', annotation_text)
            if original_annotation != annotation_text:
                print(f"[DEBUG] Annotation normalized: {annotation_text}")

        # Try to use extracted dates from annotation, fall back to note date
        extracted_dates = llm_row.get("extracted_dates", [])

        # Handle string representation of lists
        if isinstance(extracted_dates, str):
            import ast
            try:
                extracted_dates = ast.literal_eval(
                    extracted_dates) if extracted_dates else []
            except Exception:
                extracted_dates = []
        if extracted_dates:
            print(
                f"[DEBUG] Ignoring extracted date(s) from annotation: {extracted_dates}")
        date = note_date
        print(f"[DEBUG] Using note date: {date}")

        # Skip error annotations
        if str(annotation_text).startswith("ERROR:"):
            print(f"[WARN] Skipping error annotation: {annotation_text}")
            error_count += 1
            continue

        # Track if any pattern matched for this annotation
        annotation_matched = False

        # Helper function to check if annotation_id is relevant to prompt_type
        def is_annotation_relevant_to_prompt(annotation_id: str, annotation_data: Dict, prompt_type: str) -> bool:
            """
            Check if an annotation is relevant to the current prompt_type.
            This prevents cross-prompt-type false matches.
            """
            # Patient status annotations (225, 226, 227, 228, 229) should only match patient-status-int
            patient_status_ids = {"225", "226", "227", "228", "229", "230", "231"}
            if annotation_id in patient_status_ids:
                return prompt_type == "patient-status-int"
            
            # Add more specific mappings as needed
            # For now, be more permissive for other annotations but stricter for patient status
            return True

        # Apply regex patterns to the annotation text
        print(
            f"[DEBUG] Checking against {len(summary_dict)} annotation patterns for prompt_type: {prompt_type}...")

        for annotation_id, annotation_data in summary_dict.items():
            # Filter by prompt_type relevance
            if not is_annotation_relevant_to_prompt(annotation_id, annotation_data, prompt_type):
                continue
            
            # Check if there are parameters defined
            if "parameters" not in annotation_data or not annotation_data["parameters"]:
                # print(
                #     f"[DEBUG]     No parameters defined, checking for content match...")

                # No parameters - check for exact/partial match with stricter criteria
                sentence_content = annotation_data.get("sentence_content", "")
                norm_content = sentence_content.lower().strip()
                norm_annotation = annotation_text.lower().strip()

                print(f"[DEBUG]     Expected content: '{sentence_content}'")

                # Stricter matching: require the full sentence content to be present in annotation
                # This prevents partial substring matches that cause false positives
                # For patient status annotations, require exact or near-exact match
                if annotation_id in {"225", "226", "227", "228", "229", "230", "231"}:
                    # For patient status, require the key phrase to be present
                    # Check for the distinctive part (e.g., "Dead of Disease", "Alive, No Evidence")
                    key_phrases = {
                        "225": ["dead of disease", "dod"],
                        "226": ["dead of other cause", "doc"],
                        "227": ["dead of unknown cause", "duc"],
                        "228": ["alive, no evidence of disease", "ned"],
                        "229": ["alive with disease", "awd", "localised"],
                        "230": ["alive with disease", "awd", "nodes"],
                        "231": ["alive with disease", "awd", "metastatic"]
                    }
                    phrases = key_phrases.get(annotation_id, [])
                    if not phrases or not any(phrase in norm_annotation for phrase in phrases):
                        continue
                    # Also require "status" or "follow-up" to be present
                    if "status" not in norm_annotation and "follow-up" not in norm_annotation and "followup" not in norm_annotation:
                        continue
                else:
                    # For other parameterless annotations, use stricter matching
                    # Require the sentence content to be a substantial part of the annotation
                    # or the annotation to be contained in the sentence content
                    if norm_content not in norm_annotation:
                        # If sentence content not in annotation, check if it's a reasonable match
                        # Require at least 50% of key words to match
                        content_words = set(norm_content.split())
                        annotation_words = set(norm_annotation.split())
                        if len(content_words) > 0:
                            overlap = len(content_words & annotation_words) / len(content_words)
                            if overlap < 0.5:
                                continue
                
                # Final check: original bidirectional match (but only if passed above filters)
                if norm_content in norm_annotation or norm_annotation in norm_content:
                    print(
                        f"[INFO] ✓ Matched parameterless sentence {annotation_id}: {sentence_content}")
                    annotation_matched = True

                    # NEW: run special handlers for parameterless annotations (e.g., 225)
                    handler = SPECIAL_HANDLERS.get(str(annotation_id))
                    if handler:
                        ctx = {
                            "annotation_id": str(annotation_id),
                            "annotation_data": annotation_data,
                            "match": None,
                            "patient_id": patient_id,
                            "date": date,
                            "note_id": note_id,
                            "prompt_type": prompt_type,
                            "excel_data": excel_data,
                            "staged_rows": new_rows,
                        }
                        special_rows = handler(ctx)
                        for sr in special_rows:
                            cv = _to_str(sr.get("core_variable", ""))
                            val = sr.get("value")
                            if not cv or _is_invalid_value("TEXT", val):
                                print(
                                    f"[DEBUG]     Skipping special row with empty/invalid fields: {sr}")
                                continue
                            if _is_duplicate_row(excel_data, new_rows, sr.get("patient_id"), cv, val, sr.get("date_ref")):
                                continue
                            # Respect provided record_id; otherwise reuse nearby group or allocate new
                            if "record_id" in sr and _to_str(sr["record_id"]):
                                try:
                                    max_record_id = max(
                                        max_record_id, int(sr["record_id"]))
                                except (TypeError, ValueError):
                                    pass
                            else:
                                date_ref_sr = _to_str(
                                    sr.get("date_ref") or date)
                                entity_prefix = cv.split(".", 1)[0] + "."
                                reuse_id = _find_nearby_group_record_id(
                                    patient_id, entity_prefix, date_ref_sr)
                                if reuse_id is not None:
                                    sr["record_id"] = reuse_id
                                    max_record_id = max(
                                        max_record_id, reuse_id)
                                else:
                                    max_record_id += 1
                                    sr["record_id"] = max_record_id
                            sr.setdefault("types", "string")
                            new_rows.append(sr)

                    # ...existing code for optional associated_variable in first parameter...
                    params = annotation_data.get("parameters", [])
                    if params and len(params) > 0 and "associated_variable" in params[0]:
                        # ...existing code...
                        pass
                continue

            # Get the regex pattern for the current annotation
            # Filter by prompt_type relevance for regex patterns too
            if not is_annotation_relevant_to_prompt(annotation_id, summary_dict.get(annotation_id, {}), prompt_type):
                continue
            
            pattern = regexp_dict.get(annotation_id)
            # Skip if pattern is missing or blank (avoid empty-regex matching everywhere)
            if not pattern or not str(pattern).strip():
                # print(
                #     f"[DEBUG]     No regex pattern found for annotation_id {annotation_id}, skipping")
                continue
            # Validate and compile the regex
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                print(
                    f"[WARN]     Invalid regex for annotation_id {annotation_id}: {e}, skipping")
                skipped_count += 1
                continue

            print(f"[DEBUG]     Regex pattern: {pattern}")

            # Find all matches in the annotation text
            matches: list = regex.findall(annotation_text)

            if matches:
                annotation_matched = True
                annotation_count += 1
                print(f"[INFO] ✓ Matched annotation {annotation_id}")
                print(
                    f"[DEBUG]     Extracted {len(matches)} match(es): {matches}")

                # Handle different match structures
                if not isinstance(matches[0], tuple):
                    # Single group match
                    matches = [(m,) for m in matches]
                    print(f"[DEBUG]     Converted to tuple format")

                # Process each match
                for match_index, match in enumerate(matches):
                    # --- existing pre-default special handler hook ---
                    handler = SPECIAL_HANDLERS.get(str(annotation_id))
                    if handler:
                        ctx = {
                            "annotation_id": str(annotation_id),
                            "annotation_data": annotation_data,
                            "match": match,
                            "patient_id": patient_id,
                            "date": date,
                            "note_id": note_id,
                            "prompt_type": prompt_type,
                            "excel_data": excel_data,
                            "staged_rows": new_rows
                        }
                        special_rows = handler(ctx)
                        appended = 0
                        for sr in special_rows:
                            cv = _to_str(sr.get("core_variable", ""))
                            val = sr.get("value")
                            if not cv or _is_invalid_value("TEXT", val):
                                print(
                                    f"[DEBUG]       Skipping special row with empty/invalid fields: {sr}")
                                continue
                            if _is_duplicate_row(excel_data, new_rows, sr.get("patient_id"), cv, val, sr.get("date_ref")):
                                continue
                            # Respect provided record_id; otherwise reuse nearby group or allocate new
                            if "record_id" in sr and _to_str(sr["record_id"]):
                                try:
                                    max_record_id = max(
                                        max_record_id, int(sr["record_id"]))
                                except (TypeError, ValueError):
                                    pass
                            else:
                                date_ref_sr = _to_str(
                                    sr.get("date_ref") or date)
                                entity_prefix = cv.split(".", 1)[0] + "."
                                reuse_id = _find_nearby_group_record_id(
                                    patient_id, entity_prefix, date_ref_sr)
                                if reuse_id is not None:
                                    sr["record_id"] = reuse_id
                                    max_record_id = max(
                                        max_record_id, reuse_id)
                                else:
                                    max_record_id += 1
                                    sr["record_id"] = max_record_id
                            sr.setdefault("types", "string")
                            new_rows.append(sr)
                            appended += 1
                        # Do NOT skip default logic
                    # --- END pre-default special handler hook ---

                    # Default logic (unchanged) with capture for base_record_id (211)
                    param_index = match_index if match_index < len(
                        annotation_data["parameters"]) else 0
                    parameter_data = annotation_data["parameters"][param_index]

                    assoc_var = parameter_data["associated_variable"]
                    param_type = parameter_data.get(
                        "parameter_type", "DEFAULT")
                    # <-- precompute for special cases
                    assoc_var_str = _to_str(assoc_var)

                    # Determine the value based on parameter_type
                    if param_type == "ENUM":
                        # Map captured value to concept_id
                        possible_values = parameter_data.get(
                            "possible_values", [])
                        captured_value = _first_group(match)

                        value = None
                        for pv_dict in possible_values:
                            for key, concept_id in pv_dict.items():
                                if key.lower() in _to_str(captured_value).lower():
                                    value = concept_id
                                    print(
                                        f"[DEBUG]       ✓ Mapped '{key}' → '{concept_id}'")
                                    break
                            if value:
                                break

                        if not value:
                            print(
                                f"[WARN]       ✗ No concept_id mapping found for '{captured_value}'. Skipping row.")
                            continue
                    elif param_type in ["DATE", "NUMBER", "TEXT"]:
                        value = _first_group(match)
                        print(
                            f"[DEBUG]       Extracted {param_type} value: {value}")
                        # --- special case: annotation 74 provides age; compute birth year from note date ---
                        if str(annotation_id) == "74" and assoc_var_str == "Patient.birthYear":
                            dt = _parse_date_any(_to_str(date))
                            try:
                                age_years = float(_to_str(value))
                            except Exception:
                                print(
                                    f"[WARN]       ✗ Invalid age '{value}' for birth year computation. Skipping row.")
                                skipped_count += 1
                                continue
                            if not dt:
                                print(
                                    f"[WARN]       ✗ Invalid/missing note date '{date}' for birth year computation. Skipping row.")
                                skipped_count += 1
                                continue
                            birth_year = int(dt.year - int(age_years))
                            value = birth_year
                            print(
                                f"[DEBUG]       Computed Patient.birthYear = {birth_year} from age {age_years} and note year {dt.year}")
                    elif param_type == "DEFAULT":
                        value = parameter_data.get("value", match)
                        print(f"[DEBUG]       Using DEFAULT value: {value}")
                    else:
                        value = _first_group(match)
                        print(f"[DEBUG]       Using raw match value: {value}")

                    # Validate assoc_var
                    if not assoc_var_str:
                        print(
                            f"[WARN]       ✗ Empty associated_variable. Skipping row.")
                        skipped_count += 1
                        continue

                    # Validate value
                    if _is_invalid_value(param_type, value):
                        print(
                            f"[WARN]       ✗ Invalid/empty value for type '{param_type}': '{value}'. Skipping row.")
                        skipped_count += 1
                        continue

                    # NEW: unified duplicate check (existing excel + staged rows)
                    if _is_duplicate_row(excel_data, new_rows, patient_id, assoc_var_str, value, date):
                        print(
                            f"[DEBUG]       ✗ Duplicate detected (existing or staged), skipping")
                        skipped_count += 1
                        # --- Capture base_record_id if we skipped adding due to duplicate ---
                        base_record_id = None
                        if str(annotation_id) in SPECIAL_HANDLERS_AFTER and (
                            assoc_var_str == "IsolatedLimbPerfusion.startDate"
                            or (str(annotation_id) == "240" and assoc_var_str == "CancerEpisode.cancerStartDate")
                            # NEW: support 241 duplicates as well
                            or (str(annotation_id) == "241" and assoc_var_str in {"EpisodeEvent.diseaseStatus", "EpisodeEvent.dateOfEpisode"})
                            # NEW: support 219 anchored on RegionalDeepHyperthemia.startDate
                            or (str(annotation_id) == "219" and assoc_var_str == "RegionalDeepHyperthemia.startDate")
                        ):
                            # try find existing record_id in excel_data or staged rows
                            if not excel_data.empty:
                                exist = excel_data[
                                    (excel_data["patient_id"] == patient_id) &
                                    (excel_data["core_variable"] == assoc_var_str) &
                                    (excel_data["date_ref"].astype(
                                        str) == _to_str(date))
                                ]
                                if not exist.empty and "record_id" in exist.columns:
                                    try:
                                        base_record_id = int(
                                            exist.iloc[0]["record_id"])
                                    except Exception:
                                        base_record_id = None
                            if base_record_id is None:
                                # search staged rows
                                for r in reversed(new_rows):
                                    if r.get("patient_id") == patient_id and r.get("core_variable") == assoc_var_str and _to_str(r.get("date_ref")) == _to_str(date):
                                        base_record_id = r.get("record_id")
                                        break
                        # If post-handler present and we have base_record_id, run it now
                        post_handler = SPECIAL_HANDLERS_AFTER.get(
                            str(annotation_id))
                        if post_handler and base_record_id:
                            ctx_after = {
                                "annotation_id": str(annotation_id),
                                "annotation_data": annotation_data,
                                "match": match,
                                "patient_id": patient_id,
                                "date": date,
                                "note_id": note_id,
                                "prompt_type": prompt_type,
                                "excel_data": excel_data,
                                "staged_rows": new_rows,
                                "base_record_id": base_record_id
                            }
                            post_rows = post_handler(ctx_after)
                            for sr in post_rows:
                                cv = _to_str(sr.get("core_variable", ""))
                                val = sr.get("value")
                                if not cv or _is_invalid_value("TEXT", val):
                                    continue
                                if _is_duplicate_row(excel_data, new_rows, sr.get("patient_id"), cv, val, sr.get("date_ref")):
                                    continue
                                # keep provided record_id
                                if "record_id" in sr and _to_str(sr["record_id"]):
                                    try:
                                        max_record_id = max(
                                            max_record_id, int(sr["record_id"]))
                                    except (TypeError, ValueError):
                                        pass
                                else:
                                    max_record_id += 1
                                    sr["record_id"] = max_record_id
                                sr.setdefault("types", "string")
                                new_rows.append(sr)
                        continue

                    # Only now assign record_id (reuse nearby group or allocate) and append
                    entity_prefix = assoc_var_str.split(".", 1)[0] + "."
                    reuse_id = _find_nearby_group_record_id(
                        patient_id, entity_prefix, date)
                    if reuse_id is not None:
                        assigned_rid = reuse_id
                        max_record_id = max(max_record_id, reuse_id)
                    else:
                        max_record_id += 1
                        assigned_rid = max_record_id
                    new_row = {
                        "patient_id": patient_id,
                        "original_source": "NLP_LLM",
                        "core_variable": assoc_var_str,
                        "date_ref": date,
                        "value": value,
                        "record_id": assigned_rid,
                        "note_id": note_id,
                        "prompt_type": prompt_type,
                        "types": types_map.get(param_type, "NOT SPECIFIED"),
                    }
                    new_rows.append(new_row)

                    # --- NEW: After-default special handler hook (211, 240, 241) ---
                    post_handler = SPECIAL_HANDLERS_AFTER.get(
                        str(annotation_id))
                    if post_handler and (
                        # Keep existing cases
                        assoc_var_str == "IsolatedLimbPerfusion.startDate"
                        or (str(annotation_id) == "240" and assoc_var_str == "CancerEpisode.cancerStartDate")
                        # NEW: trigger for 241 after either diseaseStatus or date row
                        or (str(annotation_id) == "241" and assoc_var_str in {"EpisodeEvent.diseaseStatus", "EpisodeEvent.dateOfEpisode"})
                        # NEW: trigger for 219 anchored on RegionalDeepHyperthemia.startDate
                        or (str(annotation_id) == "219" and assoc_var_str == "RegionalDeepHyperthemia.startDate")
                    ):
                        # record_id assigned to this row (reused or new)
                        base_record_id = assigned_rid
                        ctx_after = {
                            "annotation_id": str(annotation_id),
                            "annotation_data": annotation_data,
                            "match": match,
                            "patient_id": patient_id,
                            "date": date,
                            "note_id": note_id,
                            "prompt_type": prompt_type,
                            "excel_data": excel_data,
                            "staged_rows": new_rows,
                            "base_record_id": base_record_id
                        }
                        post_rows = post_handler(ctx_after)
                        for sr in post_rows:
                            cv = _to_str(sr.get("core_variable", ""))
                            val = sr.get("value")
                            if not cv or _is_invalid_value("TEXT", val):
                                print(
                                    f"[DEBUG]       Skipping post-special row with empty/invalid fields: {sr}")
                                continue
                            if _is_duplicate_row(excel_data, new_rows, sr.get("patient_id"), cv, val, sr.get("date_ref")):
                                continue
                            # Respect provided record_id (base_record_id)
                            if "record_id" in sr and _to_str(sr["record_id"]):
                                try:
                                    max_record_id = max(
                                        max_record_id, int(sr["record_id"]))
                                except (TypeError, ValueError):
                                    pass
                            else:
                                max_record_id += 1
                                sr["record_id"] = max_record_id
                            sr.setdefault("types", "string")
                            new_rows.append(sr)
    print("\n[DEBUG] ========================================")
    print("[DEBUG] Processing Summary:")
    print(f"[DEBUG]   Total annotations processed: {len(llm_annotations)}")
    print(f"[DEBUG]   Successful regex matches: {annotation_count}")
    print(f"[DEBUG]   New rows created: {len(new_rows)}")
    print(f"[DEBUG]   Duplicates skipped: {skipped_count}")
    print(f"[DEBUG]   Errors skipped: {error_count}")
    print(f"[DEBUG]   Final record_id: {max_record_id}")
    print("[DEBUG] ========================================")

    # Append new rows to excel_data
    if new_rows:
        print(f"[DEBUG] Appending {len(new_rows)} new rows to excel_data")
        new_df = pandas.DataFrame(new_rows)
        excel_data = pandas.concat(
            [excel_data, new_df], ignore_index=True) if not excel_data.empty else new_df
        print(f"[DEBUG] Final excel_data shape: {excel_data.shape}")
    else:
        print("[DEBUG] No new rows to append")

    return excel_data


def process_texts(
    texts: pandas.DataFrame,
    excel_data: pandas.DataFrame,
    model_path: str = None,
    prompts_json_path: str = None,
    fewshots_dict: Dict[str, List[tuple]] = None,
    task_id: str = None,
    is_cancelled_callback=None,
    report_type_mapping: Dict[str, List[str]] | None = None
) -> tuple[pandas.DataFrame, pandas.DataFrame]:
    """
    Main function to process texts using LLM and extract structured data.

    Workflow:
    1. Call process_texts_with_llm to get LLM annotations for each text
    2. Use regex patterns to parse the structured annotations
    3. Extract values and insert into excel_data DataFrame

    Args:
        texts (pandas.DataFrame): DataFrame with columns: text, date, p_id, note_id, report_type
        excel_data (pandas.DataFrame): Existing Excel data to append to
        model_path (str): Path to the LLM model file. If None, uses default path.
        prompts_json_path (str): Path to prompts.json. If None, uses default path.
        fewshots_dict (Dict[str, List[tuple]]): Dictionary mapping prompt_type to list of (text, annotation) tuples.
        task_id (str): Optional task ID for cancellation checking
        is_cancelled_callback (callable): Optional callback function to check if task is cancelled

    Returns:
        tuple[pandas.DataFrame, pandas.DataFrame]: (excel_data, llm_results)
            - excel_data: Excel data with structured data integrated
            - llm_results: Raw LLM annotations from process_texts_with_llm

    Raises:
        RuntimeError: If task is cancelled during processing
    """

    print("[INFO] Starting text processing pipeline...")

    # Step 1: Get LLM annotations for all texts
    print("[INFO] Step 1: Running LLM to annotate texts...")
    llm_results = process_texts_with_llm(
        texts=texts,
        model_path=model_path,
        prompts_json_path=prompts_json_path,
        fewshots_dict=fewshots_dict,
        parse_multiple_values=True,
        task_id=task_id,
        is_cancelled_callback=is_cancelled_callback,
        report_type_mapping=report_type_mapping
    )

    print(f"[INFO] LLM generated {len(llm_results)} annotations")

    # Step 2: Process LLM annotations with regex
    print("[INFO] Step 2: Processing LLM annotations with regex patterns...")
    excel_data = process_llm_annotations_with_regex(
        llm_annotations=llm_results,
        excel_data=excel_data
    )

    print(
        f"[INFO] Processing complete! Final excel_data has {len(excel_data)} records")

    return excel_data, llm_results


if __name__ == "__main__":
    import sys

    print("=" * 80)
    print("DEBUG: Testing process_texts with provided CSV data")
    print("=" * 80)

    # Load the LLM annotations CSV (notes input)
    llm_annotations_path = "nlp/test_data/sarcoma_regex_synthetic_2.csv"
    processed_texts_path = "nlp/test_data/processed_texts.csv"

    # Load texts to run LLM (kept for reference; currently not used below)
    try:
        with open(llm_annotations_path, "r", encoding="utf-8") as f:
            first_line = f.readline()
            delimiter = "," if first_line.count(
                ",") > first_line.count(";") else ";"
        print(
            f"[INFO] Detected delimiter '{delimiter}' for llm_annotations CSV")
        texts_df = pandas.read_csv(
            llm_annotations_path, delimiter=delimiter, header=0)
    except Exception as e:
        print(f"[ERROR] Failed to load texts CSV: {e}")
        sys.exit(1)
    print(f"[INFO] Loaded {len(texts_df)} texts from {llm_annotations_path}")
    print(texts_df.iloc[0])
    print(texts_df.columns)

    prompts_json_path = "nlp/prompts.json"

    with open(prompts_json_path, "r", encoding="utf-8") as f:
        prompts_config = json.load(f)

    prompt_types = list(prompts_config.keys())
    print(f"[INFO] Found {len(prompt_types)} prompt types: {prompt_types}")

    fewshots_dict = {pt: [] for pt in prompt_types}

    llm_results = process_texts_with_llm(
        texts=texts_df,
        model_path="nlp/meta-llama-3.1-8b-instruct-q4_k_m.gguf",
        prompts_json_path=prompts_json_path,
        fewshots_dict=fewshots_dict,
        parse_multiple_values=True,
        task_id="task_id",
        is_cancelled_callback=None
    )
    # write to processed texts path for inspection
    llm_results.to_csv(processed_texts_path, index=False)
    print(f"[INFO] LLM results saved to {processed_texts_path}")
    exit(0)  # Prevent running the full processing below for now

    # Load structured data CSV
    try:
        with open(processed_texts_path, "r", encoding="utf-8") as f:
            first_line = f.readline()
            delimiter = "," if first_line.count(
                ",") > first_line.count(";") else ";"
        print(
            f"[INFO] Detected delimiter '{delimiter}' for processed_texts CSV")
        excel_data_df = pandas.read_csv(
            processed_texts_path, delimiter=delimiter, header=0)
    except Exception as e:
        print(f"[ERROR] Failed to load processed_texts CSV: {e}")
        sys.exit(1)
    print(
        f"[INFO] Loaded {len(excel_data_df)} existing records from {processed_texts_path}")

    # Regex-only processing with pre-generated LLM annotations
    llm_results_path = "nlp/test_data/llm_results_output.csv"
    try:
        llm_results_df = pandas.read_csv(llm_results_path)
        print(
            f"[INFO] Loaded {len(llm_results_df)} LLM annotations from {llm_results_path}")
    except Exception as e:
        print(f"[ERROR] Failed to load LLM results CSV: {e}")
        sys.exit(1)

    try:
        updated_excel_data = process_llm_annotations_with_regex(
            llm_annotations=llm_results_df,
            excel_data=excel_data_df
        )
    except Exception as e:
        print(f"[ERROR] Regex processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(
        f"[INFO] Final structured data has {len(updated_excel_data)} records")
    updated_excel_data.to_csv(
        "nlp/test_data/updated_structured_data.csv", index=False)
    print("Finished processing. Updated data saved to updated_structured_data.csv")
