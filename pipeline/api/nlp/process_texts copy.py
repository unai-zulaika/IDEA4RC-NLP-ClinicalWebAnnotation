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
from typing import List, Dict
from datetime import datetime  # NEW
from nlp.model_runner import load_prompts_from_json, get_prompt, run_model_with_prompt, init_model


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
    is_cancelled_callback=None
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
    load_prompts_from_json(prompts_json_path)

    print("[INFO] Initializing model...")
    init_model(str(model_path))

    # Get all available prompt types
    import json
    with open(prompts_json_path, "r", encoding="utf-8") as f:
        prompts_config = json.load(f)

    prompt_types = list(prompts_config.keys())
    print(f"[INFO] Found {len(prompt_types)} prompt types: {prompt_types}")

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
            f"[INFO] Processing row {idx + 1}/{total_rows} - Patient: {p_id}, Note: {note_id}")

        # Run model for each prompt type
        for prompt_type in prompt_types:
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


# --- Special handlers registry (annotation_id -> callable) ---
SPECIAL_HANDLERS: Dict[str, callable] = {}


def register_special_handler(annotation_id: str, handler: callable):
    SPECIAL_HANDLERS[str(annotation_id)] = handler


# --- NEW: Post-default special handlers (run after default logic to reuse record_id) ---
SPECIAL_HANDLERS_AFTER: Dict[str, callable] = {}


def register_special_handler_after(annotation_id: str, handler: callable):
    SPECIAL_HANDLERS_AFTER[str(annotation_id)] = handler

# --- Helpers shared by handlers and regex processing ---


def _to_str(val) -> str:
    try:
        return str(val).strip()
    except Exception:
        return ""


def _is_placeholder(text: str) -> bool:
    s = _to_str(text).lower()
    if not s:
        return True
    if s in {"n/a", "na", "none", "null", "unknown", "unk", "-", "--"}:
        return True
    # [provide date], [select regimen], [something]
    if re.fullmatch(r"\[[^\]]+\]", s or ""):
        return True
    return False


def _is_invalid_value(param_type: str, value) -> bool:
    # Treat NaN/None/empty and placeholders as invalid
    if value is None:
        return True
    try:
        if pandas.isna(value):
            return True
    except Exception:
        pass
    s = _to_str(value)
    if not s:
        return True
    if _is_placeholder(s):
        return True
    # Optional: for DATE, enforce basic date pattern
    if param_type == "DATE":
        if not re.search(r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}", s):
            return True
    return False


def _is_duplicate_row(excel_data: pandas.DataFrame, staged_rows: List[dict],
                      patient_id: str, core_variable: str, value, date_ref: str) -> bool:
    # Check duplicates in existing excel_data
    if "patient_id" in excel_data.columns and not excel_data.empty:
        existing_rows = excel_data[excel_data["patient_id"] == patient_id]
        if not existing_rows.empty:
            dup = existing_rows[
                (existing_rows["core_variable"] == core_variable) &
                (existing_rows["value"].astype(str) == _to_str(value)) &
                (existing_rows["date_ref"].astype(str) == _to_str(date_ref))
            ]
            if not dup.empty:
                return True
    # Check duplicates in rows staged during current run
    for r in staged_rows:
        if (r.get("patient_id") == patient_id and
            r.get("core_variable") == core_variable and
            _to_str(r.get("value")) == _to_str(value) and
                _to_str(r.get("date_ref")) == _to_str(date_ref)):
            return True
    return False

# --- NEW: small helpers ---
def _parse_date_any(s: str):
    if not s:
        return None
    s = _to_str(s)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(s, fmt)
        except Exception:
            pass
    return None

def _first_group(match):
    return match[0] if isinstance(match, tuple) and len(match) > 0 else match

# --- Example special handler: Radiotherapy site (217/261) ---


def _handle_radiotherapy_site(ctx: dict) -> List[dict]:
    """
    Special handling for 'Radiotherapy site':
    - Let default regex flow handle the first parameter (select site).
    - If the first parameter indicates 'metastatic site', parse the second parameter (comma-separated list)
      and emit boolean flags for the following variables:
        - Radiotherapy.metastaticTreatmentSiteLung
        - Radiotherapy.metastaticTreatmentSiteMediastinum
        - Radiotherapy.metastaticTreatmentSiteBone
        - Radiotherapy.metastaticTreatmentSiteSoftTissue
        - Radiotherapy.metastaticTreatmentSiteLiver
    """
    match = ctx["match"]
    patient_id = ctx["patient_id"]
    date = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]

    # Regex 261 captures: (site_category) (details)
    site_category = _to_str(match[0]) if len(match) > 0 else ""
    details = _to_str(match[1]) if len(match) > 1 else ""

    rows: List[dict] = []

    # Only handle the second parameter when metastatic site is selected.
    if "metastatic" in site_category.lower():
        # Expected comma-separated list
        tokens = [t.strip().lower()
                  for t in details.split(",") if t and t.strip()]
        # Normalize some common variants
        normalized = set()
        for t in tokens:
            t_norm = t.replace("-", " ").replace("_", " ").strip()
            normalized.add(t_norm)

        # Map normalized tokens to boolean variables
        site_var_map = {
            "lung": "Radiotherapy.metastaticTreatmentSiteLung",
            "mediastinum": "Radiotherapy.metastaticTreatmentSiteMediastinum",
            "bone": "Radiotherapy.metastaticTreatmentSiteBone",
            "soft tissue": "Radiotherapy.metastaticTreatmentSiteSoftTissue",
            "liver": "Radiotherapy.metastaticTreatmentSiteLiver",
        }

        # Soft tissue: allow prefixes like "soft" and phrases like "soft tissue", "soft-tissue"
        def matches_soft_tissue(token: str) -> bool:
            return token.startswith("soft") or "soft tissue" in token

        for token in normalized:
            if token == "lung":
                var = site_var_map["lung"]
            elif token == "mediastinum":
                var = site_var_map["mediastinum"]
            elif token == "bone":
                var = site_var_map["bone"]
            elif token == "liver":
                var = site_var_map["liver"]
            elif matches_soft_tissue(token):
                var = site_var_map["soft tissue"]
            else:
                continue  # ignore tokens not in the requested set

            rows.append({
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": var,
                "date_ref": date,
                "value": True,       # boolean TRUE
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "boolean"
            })

    return rows


# Register handlers for both dictionary id 217 and regexp id 261
register_special_handler("217", _handle_radiotherapy_site)
register_special_handler("261", _handle_radiotherapy_site)

# --- NEW: Post-default handler for Isolated limb perfusion drugs (211) ---


def _handle_ilp_drugs(ctx: dict) -> List[dict]:
    """
    For annotation 211:
      - Default logic handles the first parameter (DATE) and creates IsolatedLimbPerfusion.startDate with a record_id.
      - This handler parses the second parameter (list drugs, comma-separated) and emits, for each drug:
          1) DrugsForTreatments.isolatedLimbPerfusion = True (boolean), with record_id = base_record_id
          2) DrugsForTreatments.drug = <drug name> (string), with record_id = base_record_id
    ctx keys expected:
      - match: tuple(str date, str list_drugs)
      - patient_id, date, note_id, prompt_type
      - base_record_id: int (record_id assigned to the DATE row)
    """
    match = ctx["match"]
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    base_record_id = ctx.get("base_record_id")

    rows: List[dict] = []
    if base_record_id is None:
        # Without the base record id we cannot link rows; skip safely
        return rows

    # Extract comma-separated drugs from match[1]
    details = _to_str(match[1]) if len(match) > 1 else ""
    if not details:
        return rows

    # split by comma; trim tokens; ignore empties
    tokens = [t.strip() for t in details.split(",") if t and t.strip()]
    if not tokens:
        return rows

    for drug in tokens:
        # Boolean flag for ILP present in treatment (linked to same record_id)
        rows.append({
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "DrugsForTreatments.isolatedLimbPerfusion",
            "date_ref": date_ref,
            "value": True,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "boolean",
            "record_id": base_record_id  # preserve linkage
        })
        # Drug name row (linked to same record_id)
        rows.append({
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "DrugsForTreatments.drug",
            "date_ref": date_ref,
            "value": drug,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "string",
            "record_id": base_record_id  # preserve linkage
        })

    return rows


# Register post-default handler for 211
register_special_handler_after("211", _handle_ilp_drugs)

# --- NEW: Post-default handler to link EpisodeEvent -> CancerEpisode (241) ---
def _handle_episode_event_link(ctx: dict) -> List[dict]:
    patient_id = ctx["patient_id"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    excel_data: pandas.DataFrame = ctx.get("excel_data")
    staged_rows: List[dict] = ctx.get("staged_rows", [])
    base_record_id = ctx.get("base_record_id")

    # Find EpisodeEvent.dateOfEpisode value for this record group
    episode_date_str = None
    for r in reversed(staged_rows):
        if (
            r.get("record_id") == base_record_id
            and r.get("patient_id") == patient_id
            and r.get("core_variable") == "EpisodeEvent.dateOfEpisode"
            and _to_str(r.get("value"))
        ):
            episode_date_str = _to_str(r.get("value"))
            break
    if not episode_date_str:
        episode_date_str = _to_str(ctx.get("date"))
    episode_dt = _parse_date_any(episode_date_str)
    if not base_record_id or not episode_dt:
        return []

    # Collect candidate CancerEpisode.cancerStartDate rows
    candidates = []
    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty and "core_variable" in excel_data.columns:
        for _, r in excel_data.iterrows():
            if _to_str(r.get("patient_id")) != _to_str(patient_id):
                continue
            if r.get("core_variable") != "CancerEpisode.cancerStartDate":
                continue
            rid = r.get("record_id")
            start_date_str = _to_str(r.get("value")) or _to_str(r.get("date_ref"))
            sd = _parse_date_any(start_date_str)
            if sd and rid is not None:
                try:
                    candidates.append((sd, int(rid)))
                except Exception:
                    pass
    for r in staged_rows:
        if (
            _to_str(r.get("patient_id")) == _to_str(patient_id)
            and r.get("core_variable") == "CancerEpisode.cancerStartDate"
            and _to_str(r.get("record_id"))
        ):
            start_date_str = _to_str(r.get("value")) or _to_str(r.get("date_ref"))
            sd = _parse_date_any(start_date_str)
            if sd:
                try:
                    candidates.append((sd, int(r.get("record_id"))))
                except Exception:
                    pass

    if not candidates:
        return []
    before = [(d, rid) for d, rid in candidates if d <= episode_dt]
    if not before:
        return []

    _, linked_episode_id = max(before, key=lambda x: x[0])
    return [{
        "patient_id": patient_id,
        "original_source": "NLP_LLM",
        "core_variable": "EpisodeEvent.cancerEpisode",
        "date_ref": episode_date_str,
        "value": linked_episode_id,
        "note_id": note_id,
        "prompt_type": prompt_type,
        "types": "reference",
        "record_id": base_record_id
    }]

# Register post-default handler for 241
register_special_handler_after("241", _handle_episode_event_link)

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
    if "patient_id" not in excel_data.columns and "p_id" in excel_data.columns:
        print("[DEBUG] Renaming 'p_id' to 'patient_id' in excel_data")
        excel_data["patient_id"] = excel_data["p_id"]

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

        if extracted_dates and len(extracted_dates) > 0:
            date = extracted_dates[0]
            print(f"[DEBUG] Using extracted date: {date}")
        else:
            date = note_date
            print(f"[DEBUG] No extracted date, using note date: {date}")

        # Skip error annotations
        if str(annotation_text).startswith("ERROR:"):
            print(f"[WARN] Skipping error annotation: {annotation_text}")
            error_count += 1
            continue

        # Track if any pattern matched for this annotation
        annotation_matched = False

        # Apply regex patterns to the annotation text
        print(
            f"[DEBUG] Checking against {len(summary_dict)} annotation patterns...")

        for annotation_id, annotation_data in summary_dict.items():
            # Check if there are parameters defined
            if "parameters" not in annotation_data or not annotation_data["parameters"]:
                # print(
                #     f"[DEBUG]     No parameters defined, checking for content match...")

                # No parameters - check for exact/partial match
                sentence_content = annotation_data.get("sentence_content", "")
                norm_content = sentence_content.lower().strip()
                norm_annotation = annotation_text.lower().strip()

                print(f"[DEBUG]     Expected content: '{sentence_content}'")

                # Check for match
                if norm_content in norm_annotation or norm_annotation in norm_content:
                    print(
                        f"[INFO] ✓ Matched parameterless sentence {annotation_id}: {sentence_content}")
                    annotation_matched = True

                    # Look for associated_variable in first parameter if exists
                    params = annotation_data.get("parameters", [])
                    if params and len(params) > 0 and "associated_variable" in params[0]:
                        assoc_var = params[0]["associated_variable"]
                        value = params[0].get("value", "")

                        print(f"[DEBUG]     Associated variable: {assoc_var}")
                        print(f"[DEBUG]     Value: {value}")

                        if assoc_var and value:
                            max_record_id += 1
                            new_row = {
                                "patient_id": patient_id,
                                "original_source": "NLP_LLM",
                                "core_variable": assoc_var,
                                "date_ref": date,
                                "value": value,
                                "record_id": max_record_id,
                                "note_id": note_id,
                                "prompt_type": prompt_type
                            }
                            new_rows.append(new_row)

                            # --- NEW: validate and deduplicate parameterless rows ---
                            assoc_var_str = _to_str(assoc_var)
                            if not assoc_var_str or _is_invalid_value("TEXT", value):
                                print(
                                    f"[WARN]     ✗ Invalid parameterless row (var/value). Skipping.")
                                continue
                            if _is_duplicate_row(excel_data, new_rows, patient_id, assoc_var_str, value, date):
                                print(
                                    f"[DEBUG]     ✗ Duplicate parameterless row detected. Skipping.")
                                continue
                            # Only now assign record_id and append
                            max_record_id += 1
                            new_row = {
                                "patient_id": patient_id,
                                "original_source": "NLP_LLM",
                                "core_variable": assoc_var_str,
                                "date_ref": date,
                                "value": value,
                                "record_id": max_record_id,
                                "note_id": note_id,
                                "prompt_type": prompt_type
                            }
                            new_rows.append(new_row)
                            # -------------------------------------------------------
                continue

            # Get the regex pattern for the current annotation
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
                            "excel_data": excel_data
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
                            # Respect provided record_id if present; otherwise allocate a new one
                            if "record_id" in sr and _to_str(sr["record_id"]):
                                pass  # keep provided record_id; do not change max_record_id
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

                    # Determine the value based on parameter_type
                    if param_type == "ENUM":
                        # Map captured value to concept_id
                        possible_values = parameter_data.get("possible_values", [])
                        captured_value = _first_group(match)

                        value = None
                        for pv_dict in possible_values:
                            for key, concept_id in pv_dict.items():
                                if key.lower() in _to_str(captured_value).lower():
                                    value = concept_id
                                    print(f"[DEBUG]       ✓ Mapped '{key}' → '{concept_id}'")
                                    break
                            if value:
                                break

                        if not value:
                            print(f"[WARN]       ✗ No concept_id mapping found for '{captured_value}'. Skipping row.")
                            continue
                    elif param_type in ["DATE", "NUMBER", "TEXT"]:
                        value = _first_group(match)
                        print(f"[DEBUG]       Extracted {param_type} value: {value}")
                    elif param_type == "DEFAULT":
                        value = parameter_data.get("value", match)
                        print(f"[DEBUG]       Using DEFAULT value: {value}")
                    else:
                        value = _first_group(match)
                        print(f"[DEBUG]       Using raw match value: {value}")

                    # Validate assoc_var
                    assoc_var_str = _to_str(assoc_var)
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
                        ):
                            # try find existing record_id in excel_data or staged rows
                            if not excel_data.empty:
                                exist = excel_data[
                                    (excel_data["patient_id"] == patient_id) &
                                    (excel_data["core_variable"] == assoc_var_str) &
                                    (excel_data["date_ref"].astype(str) == _to_str(date))
                                ]
                                if not exist.empty and "record_id" in exist.columns:
                                    try:
                                        base_record_id = int(exist.iloc[0]["record_id"])
                                    except Exception:
                                        base_record_id = None
                            if base_record_id is None:
                                # search staged rows
                                for r in reversed(new_rows):
                                    if r.get("patient_id") == patient_id and r.get("core_variable") == assoc_var_str and _to_str(r.get("date_ref")) == _to_str(date):
                                        base_record_id = r.get("record_id")
                                        break
                        # If post-handler present and we have base_record_id, run it now
                        post_handler = SPECIAL_HANDLERS_AFTER.get(str(annotation_id))
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
                                sr.setdefault("types", "string")
                                new_rows.append(sr)
                        continue

                    # Only now assign record_id and append
                    max_record_id += 1
                    new_row = {
                        "patient_id": patient_id,
                        "original_source": "NLP_LLM",
                        "core_variable": assoc_var_str,
                        "date_ref": date,
                        "value": value,
                        "record_id": max_record_id,
                        "note_id": note_id,
                        "prompt_type": prompt_type,
                        "types": types_map.get(param_type, "NOT SPECIFIED")
                    }
                    new_rows.append(new_row)

                    # --- NEW: After-default special handler hook (211, 240, 241) ---
                    post_handler = SPECIAL_HANDLERS_AFTER.get(str(annotation_id))
                    if post_handler and (
                        # Keep existing cases
                        assoc_var_str == "IsolatedLimbPerfusion.startDate"
                        or (str(annotation_id) == "240" and assoc_var_str == "CancerEpisode.cancerStartDate")
                        # NEW: trigger for 241 after either diseaseStatus or date row
                        or (str(annotation_id) == "241" and assoc_var_str in {"EpisodeEvent.diseaseStatus", "EpisodeEvent.dateOfEpisode"})
                    ):
                        base_record_id = max_record_id  # record_id just assigned to this EpisodeEvent row
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
                                print(f"[DEBUG]       Skipping post-special row with empty/invalid fields: {sr}")
                                continue
                            if _is_duplicate_row(excel_data, new_rows, sr.get("patient_id"), cv, val, sr.get("date_ref")):
                                continue
                            # Respect provided record_id (base_record_id)
                            if "record_id" in sr and _to_str(sr["record_id"]):
                                pass
                            else:
                                max_record_id += 1
                                sr["record_id"] = max_record_id
                            sr.setdefault("types", "string")
                            new_rows.append(sr)
            # --- NEW: Post-default handler to link EpisodeEvent -> CancerEpisode (241) ---
            def _handle_episode_event_link(ctx: dict) -> List[dict]:
                """
                For annotation 241:
                  - After default creates EpisodeEvent.diseaseStatus/dateOfEpisode, add:
                    EpisodeEvent.cancerEpisode = <record_id of last CancerEpisode BEFORE the event date>.
                  - If no CancerEpisode exists before the event date, do not emit a link.
                """
                patient_id = ctx["patient_id"]
                note_id = ctx["note_id"]
                prompt_type = ctx["prompt_type"]
                excel_data: pandas.DataFrame = ctx.get("excel_data")
                staged_rows: List[dict] = ctx.get("staged_rows", [])
                base_record_id = ctx.get("base_record_id")
                # Prefer the EpisodeEvent.dateOfEpisode value recorded for this record group
                episode_date_str = None
                for r in reversed(staged_rows):
                    if (
                        r.get("record_id") == base_record_id
                        and r.get("patient_id") == patient_id
                        and r.get("core_variable") == "EpisodeEvent.dateOfEpisode"
                        and _to_str(r.get("value"))
                    ):
                        episode_date_str = _to_str(r.get("value"))
                        break
                # Fallback to ctx["date"] (date_ref) if no explicit dateOfEpisode row found
                if not episode_date_str:
                    episode_date_str = _to_str(ctx.get("date"))
                episode_dt = _parse_date_any(episode_date_str)

                if not base_record_id or not episode_dt:
                    # Without a base record_id or a valid event date, we cannot link properly
                    return []

                # Gather candidate CancerEpisode.cancerStartDate rows for this patient
                candidates: List[tuple[datetime, int]] = []

                # From existing excel_data
                if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty and "core_variable" in excel_data.columns:
                    for _, r in excel_data.iterrows():
                        if _to_str(r.get("patient_id")) != _to_str(patient_id):
                            continue
                        if r.get("core_variable") != "CancerEpisode.cancerStartDate":
                            continue
                        rid = r.get("record_id")
                        # Use value (start date) primarily; fall back to date_ref if needed
                        start_date_str = _to_str(r.get("value")) or _to_str(r.get("date_ref"))
                        sd = _parse_date_any(start_date_str)
                        if sd and rid is not None:
                            try:
                                candidates.append((sd, int(rid)))
                            except Exception:
                                pass

                # From staged rows in the current run
                for r in staged_rows:
                    if (
                        _to_str(r.get("patient_id")) == _to_str(patient_id)
                        and r.get("core_variable") == "CancerEpisode.cancerStartDate"
                        and _to_str(r.get("record_id"))
                    ):
                        start_date_str = _to_str(r.get("value")) or _to_str(r.get("date_ref"))
                        sd = _parse_date_any(start_date_str)
                        if sd:
                            try:
                                candidates.append((sd, int(r.get("record_id"))))
                            except Exception:
                                pass

                if not candidates:
                    return []

                # Pick the latest CancerEpisode that is <= EpisodeEvent date
                candidates_before = [(d, rid) for d, rid in candidates if d <= episode_dt]
                if candidates_before:
                    linked_d, linked_episode_id = max(candidates_before, key=lambda x: x[0])
                else:
                    # If none before, do not link (strict requirement)
                    return []

                return [{
                    "patient_id": patient_id,
                    "original_source": "NLP_LLM",
                    "core_variable": "EpisodeEvent.cancerEpisode",
                    "date_ref": episode_date_str,  # keep event date
                    "value": linked_episode_id    # reference to CancerEpisode record_id
                }]

            # Register post-default handler for 241 (register at module import time)
            # register_special_handler_after("241", _handle_episode_event_link)

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
    is_cancelled_callback=None
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
        is_cancelled_callback=is_cancelled_callback
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

    # prompts_json_path = "nlp/prompts.json"

    # with open(prompts_json_path, "r", encoding="utf-8") as f:
    #     prompts_config = json.load(f)


    # prompt_types = list(prompts_config.keys())
    # print(f"[INFO] Found {len(prompt_types)} prompt types: {prompt_types}")

    # fewshots_dict = {pt: [] for pt in prompt_types}

    # llm_results = process_texts_with_llm(
    #     texts=texts_df,
    #     model_path="nlp/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    #     prompts_json_path=prompts_json_path,
    #     fewshots_dict=fewshots_dict,
    #     parse_multiple_values=True,
    #     task_id="task_id",
    #     is_cancelled_callback=None
    # )
    # # write to processed texts path for inspection
    # llm_results.to_csv(processed_texts_path, index=False)
    # print(f"[INFO] LLM results saved to {processed_texts_path}")
    # exit(0)  # Prevent running the full processing below for now

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
