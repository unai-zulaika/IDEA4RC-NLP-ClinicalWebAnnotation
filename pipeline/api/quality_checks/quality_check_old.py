from collections import Counter
import collections
import os
import great_expectations as gx
import json
import argparse

import pandas as pd
from quality_checks.custom_expectations.plugins.expectations.expect_colum_pair_to_be_null_if import ExpectColumnPairToBeNullIf
from great_expectations_experimental.expectations.expect_column_values_not_to_be_future_date import ExpectColumnValuesNotToBeFutureDate

from quality_checks.fill_metadata import fill_for_center

import sys
import io
from pathlib import Path
import pandas as pd
import csv

# ── Force UTF-8 stdio on Windows so Electron / PyInstaller consoles don’t choke ──

# At the top of quality_check.py
BASE_DIR = "/data/results/"

if os.name == "nt":                      # only needed on Windows
    def utf8_wrapper(stream): return io.TextIOWrapper(
        stream.buffer, encoding="utf-8", errors="replace"
    )
    sys.stdout = utf8_wrapper(sys.stdout)
    sys.stderr = utf8_wrapper(sys.stderr)
    os.environ["PYTHONUTF8"] = "1"       # downstream libs respect this too
# ────────────────────────────────────────────────────────────────────────────────

QCNAME2EASYLABEL = {
    "expect_column_values_to_not_be_null": "Is data present?",
    "expect_column_values_to_be_in_set": "Is code in allowed set?",
    "expect_column_values_to_be_of_type": "Is data of correct type?",
    "expect_column_values_to_be_between": "Is data within allowed range?",
    "expect_column_values_not_to_be_future_date": "Is date not in the future?",
}
NLP_TAG = "NLP_LLM"
PATIENT_PASS_THRESHOLD = 0.8      # 80% of checks must pass to consider patient OK
CROSSTAB_ENTITY_REPORT_ORDER = [
    "Patient",
    "CancerEpisode",
    "Diagnosis",
    "ClinicalStage",
    "PathologicalStage",
    "EpisodeEvent",
    "DiseaseExtent",
    "Surgery",
    "Radiotherapy",
    "SystemicTreatment",
    "OverallTreatmentResponse",
    "PatientFollowUp"]

dataset_filter_path = "/app/quality_checks/dataset_variable_filter.json"

with open(dataset_filter_path,
          encoding="utf8") as fh:
    # e.g.  "Patient_sex": "both"  :contentReference[oaicite:0]{index=0}
    VAR_GROUP = json.load(fh)

VAR_GROUP = {
    k.replace("_", "."): v
    for k, v in VAR_GROUP.items()
}


def keep(var: str, ALLOWED) -> bool:
    """
    Return True if *var* is tagged for the user-selected tumour type.
    Tries 'Entity.variable' first, then the short variable name.
    Defaults to 'both' when the tag is missing.
    """
    tag = (VAR_GROUP.get(var) or
           VAR_GROUP.get(var.split(".", 1)[-1], "both"))
    return tag in ALLOWED


def read_table(path: str, **pd_kwargs) -> pd.DataFrame:
    """
    Load a CSV or Excel file into a DataFrame.
    • .csv  →  try pandas' default reader; on ParserError sniff the delimiter
               (comma / semicolon / tab / pipe) and retry.
    • .xls/.xlsx  →  pd.read_excel
    """
    ext = Path(path).suffix.lower()

    # ---------- CSV -------------------------------------------------------
    if ext == ".csv":
        try:
            return pd.read_csv(path, **pd_kwargs)          # fast path
        except pd.errors.ParserError:
            # ── auto-detect separator and fall back to the python engine ──
            with open(path, "r", newline="", encoding=pd_kwargs.get("encoding", "utf-8")) as fh:
                sample = fh.read(4096)                     # first ~4 KB
                delim = csv.Sniffer().sniff(sample, delimiters=[
                    ",", ";", "\t", "|"]).delimiter
            return pd.read_csv(path,
                               delimiter=delim,
                               engine="python",            # more forgiving
                               **pd_kwargs)

    # ---------- Excel -----------------------------------------------------
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path, **pd_kwargs)

    # ---------- unsupported ----------------------------------------------
    raise ValueError(f"Unsupported file type for input data: {ext}")


def crosstab_external_user(df_matrix, output_csv_path):
    """
    Writes a semicolon-delimited CSV with only:
    Variable;Importance;First phase;MissingPercent
    """
    dfm = df_matrix.copy()
    cols_to_keep = [c for c in ["Variable", "Importance",
                                "First phase", "MissingPercent"] if c in dfm.columns]
    reduced = dfm[cols_to_keep].copy()
    if "MissingPercent" in reduced.columns:
        reduced["MissingPercent"] = pd.to_numeric(
            reduced["MissingPercent"], errors="coerce")

    os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)
    with open(output_csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(cols_to_keep)
        for _, r in reduced.iterrows():
            row_vals = [("" if pd.isna(r[col]) else str(r[col]))
                        for col in cols_to_keep]
            w.writerow(row_vals)
    print(f"Wrote external crosstab to: {output_csv_path}")


def prepare_repeatable_entity_data(entity_name, original_data_filepath, repeatable_entities_config, app_path):
    """
    Reads the original long-format data, filters for variables of a specific repeatable entity,
    and pivots it to a wide format where each row is a unique instance of that entity.
    Saves the result to a CSV file.

    Parameters:
        entity_name (str): The name of the repeatable entity (e.g., "PatientFollowUp", "Diagnosis").
        original_data_filepath (str): Path to the original long-format data file (e.g., 'synthetic_idea4rc.xlsx').
        repeatable_entities_config (dict): The dictionary under the "repeteables" key from rep_entities.json.
        app_path (str): Path to the application directory for saving the output CSV.

    Returns:
        pd.DataFrame: A wide-format DataFrame with one row per entity instance, or an empty DataFrame on error.
    """
    try:
        # df_source = pd.read_excel(original_data_filepath, dtype=str)
        df_source = read_table(original_data_filepath, dtype=str)
    except FileNotFoundError:
        print(
            f"Error: Original data file not found at {original_data_filepath}")
        return pd.DataFrame()
    except Exception as e:
        print(
            f"Error reading original data file {original_data_filepath}: {e}")
        return pd.DataFrame()

    # If the entity is not in rep_entities.json, derive its variables from the data as a fallback.
    if entity_name not in repeatable_entities_config:
        print(
            f"Info: Entity '{entity_name}' not in rep_entities.json. Deriving variables from data.")
        try:
            derived_shorts = sorted({
                str(cv).split(".", 1)[1]
                for cv in df_source.get("core_variable", pd.Series([], dtype=str)).astype(str)
                if cv.startswith(f"{entity_name}.")
            })
        except Exception:
            derived_shorts = []
        if not derived_shorts:
            print(
                f"Warning: Could not derive variables for '{entity_name}' from data. Skipping.")
            return pd.DataFrame()
        variable_short_names = derived_shorts
    else:
        variable_short_names = repeatable_entities_config[entity_name]

    # Construct the full core_variable names (e.g., "PatientFollowUp.statusOfPatientAtLastFollowUp")
    entity_core_variables = [
        f"{entity_name}.{v}" for v in variable_short_names
    ]
    entity_core_variables = [
        v for v in entity_core_variables if keep(v)]   # NEW

    # Filter for rows that contain the core variables for the specified entity
    df_entity_long = df_source[df_source['core_variable'].isin(
        entity_core_variables)]

    if df_entity_long.empty:
        print(
            f"No data found for entity '{entity_name}' with core variables: {entity_core_variables}")
        return pd.DataFrame()

    # Pivot the table to have one row per patient_id + record_id,
    # and the entity's variables as columns.
    try:
        df_entity_wide = df_entity_long.pivot_table(
            # Ensures each entity instance is a row
            index=['patient_id', 'record_id'],
            columns='core_variable',          # Turns variables into columns
            values='value',                   # Takes the 'value' for each variable
            aggfunc='first'  # Assumes one value per variable within a patient_id/record_id combo
        ).reset_index()
    except KeyError as e:
        print(
            f"Error pivoting data for entity '{entity_name}'. A key column (patient_id, record_id, core_variable, value) might be missing or misnamed: {e}")
        return pd.DataFrame()
    except Exception as e:
        print(f"Error pivoting data for entity '{entity_name}': {e}")
        return pd.DataFrame()
    missing_cols = set(entity_core_variables) - set(df_entity_wide.columns)
    for col in missing_cols:
        df_entity_wide[col] = pd.NA
    # Save the prepared DataFrame to a CSV file
    output_filename = f"{entity_name}_prepared_data.csv"
    output_filepath = os.path.join(app_path, output_filename)
    try:
        df_entity_wide.to_csv(output_filepath, index=False)
        print(
            f"Successfully prepared and saved data for entity '{entity_name}' to: {output_filepath}")
    except Exception as e:
        print(
            f"Error saving prepared data for entity '{entity_name}' to CSV: {e}")
        return pd.DataFrame()  # Or return df_entity_wide if saving is optional

    return df_entity_wide


def format_normalized_table(filename, formated_filepath, non_repeatable_vars_set):

    # load filename
    # Force the datetime column to be read as a string to avoid conversion issues with great_expectations. GE needs to have the datetime column in str.
    # input_df = pd.read_excel(filename, dtype=str)
    input_df = read_table(filename, dtype=str)

    output_data = []
    patients_data = {}
    # datatype

    # convert rows into columns by patient
    for _, row in input_df.iterrows():
        p_id = row["patient_id"]
        source = row["original_source"]

        if p_id not in patients_data:
            patients_data[p_id] = {"original_source": source}
        core_variable = row["core_variable"]

        # MODIFICATION: Only process if core_variable is in the non_repeatable_vars_set
        if core_variable in non_repeatable_vars_set:
            patients_data[p_id].update({core_variable: row["value"]})
        # else:
        # Optional: print(f"Skipping repeatable/unknown core_variable: {core_variable} for patient {p_id}")

    # now that we have all data for each patient prepare for doing our dataframe
    for key, value in patients_data.items():
        output_row = {"patient_id": key, **value}
        output_data.append(output_row)

    # save as parquet format for keeping datatypes
    output_df = pd.DataFrame(output_data)

    # ---------- NEW: add tumour-allowed columns that never appeared -----------
    missing_cols = non_repeatable_vars_set - set(output_df.columns)
    for col in missing_cols:
        output_df[col] = pd.NA        # entire column is <NA>

    # (optional but nice) keep a stable column order
    col_order = ["patient_id", "original_source",
                 *sorted(non_repeatable_vars_set)]
    output_df = output_df.reindex(columns=col_order)
    # -------------------------------------------------------------------------

    output_df.to_excel(formated_filepath)


def quality_check(data, disease_type="sarcoma"):
    ALLOWED = {disease_type, "both"}
    data_file = data
    repeated_entities_file = "/app/quality_checks/repeteable_entities.json"
    suites_file = "/app/quality_checks/expectations_data.json"
    app_path = BASE_DIR
    print(f"App path set to: {app_path}")
    if isinstance(data_file, pd.DataFrame):
        try:
            tmp_csv = os.path.join(app_path, "api_input.csv")
            data_file.to_csv(tmp_csv, index=False)
            data_file = tmp_csv
            print(f"Detected DataFrame input → persisted to {tmp_csv}")
        except Exception as e:
            print(f"ERROR persisting DataFrame input: {e}")
            raise
    try:
        candidate = json.loads(data_file)
        if not isinstance(candidate, list):
            raise ValueError            # it was a plain path string
        data_files = candidate          # ✔ we really have a list
    except (json.JSONDecodeError, ValueError):
        data_files = [data_file]   # fall back → single file

    if len(data_files) > 1:
        print(f"🛈  Combining {len(data_files)} patient files …")
        dfs = []
        for p in data_files:
            try:
                dfs.append(read_table(p, dtype=str))
            except Exception as e:
                print(f"    ⚠︎  Skipping {p}: {e}")
        if not dfs:
            sys.exit("ERROR: none of the provided data files could be read.")

        combined_df = pd.concat(dfs, ignore_index=True)
        combined_path = os.path.join(app_path, "combined_input.xlsx")
        combined_df.to_excel(combined_path, index=False)
        data_file = combined_path      # 👈 every downstream call sees ONE file
        print(f"    → wrote combined cohort to {combined_path}")
    else:
        # single-file workflow – nothing changes
        data_file = data_files[0]

    # Get the absolute path to the current file
    current_file_path = os.path.abspath(__file__)
    plugins_directory = os.path.dirname(
        current_file_path) + "\custom_expectations\plugins"

    data_context_config = gx.data_context.types.base.DataContextConfig(
        store_backend_defaults=gx.data_context.types.base.InMemoryStoreBackendDefaults(),
        plugins_directory=plugins_directory
    )
    context = gx.get_context(project_config=data_context_config)

    # --- Load Entity Definitions (rep_entities.json) ---
    with open(repeated_entities_file, encoding="utf8") as f:
        repeated_entities_data = json.load(f)

    all_non_repeatable_core_variables = set()
    non_repeatable_entity_names = set(
        repeated_entities_data.get("non_repeteables", {}).keys())
    repeatable_entity_names = set(
        repeated_entities_data.get("repeteables", {}).keys())

    if "non_repeteables" in repeated_entities_data:
        for entity_name, variables_list in repeated_entities_data["non_repeteables"].items():
            for var_name in variables_list:
                all_non_repeatable_core_variables.add(
                    f"{entity_name}.{var_name}")

    # keep only the variables that are allowed by the tumor type filter
    all_non_repeatable_core_variables = {
        v for v in all_non_repeatable_core_variables if keep(v, ALLOWED)
    }

    # ── COMPLETE VARIABLE LIST (non-rep + rep) ──────────────────────────────
    all_core_variables_filtered = set(all_non_repeatable_core_variables)

    for ent, short_vars in repeated_entities_data.get("repeteables", {}).items():
        for v in short_vars:
            full = f"{ent}.{v}"
            if keep(full, ALLOWED):                          # tumour-type filter
                all_core_variables_filtered.add(full)

    # --- Load minimum-cardinality per entity -----------------------------------
    card_file = os.path.join(os.path.dirname(repeated_entities_file),
                             "entities_cardinality.json")
    try:
        with open(card_file, encoding="utf-8") as fh:
            # e.g.  {"Patient":1, "Surgery":0, ...}
            entity_min_card = json.load(fh)
    except Exception as e:
        print(f"ERROR loading entities_cardinality.json: {e}")
        entity_min_card = {}          # default → treat as 1 (mandatory)

    # ── Re-classify repeatable vs non-repeatable from entities_cardinality.json ──
    non_repeatable_entity_names = {
        e for e, card in entity_min_card.items() if card == 1}
    repeatable_entity_names = {
        e for e in entity_min_card if e not in non_repeatable_entity_names}

    # rebuild the list of non-repeatable *variables* based on the new rule
    all_non_repeatable_core_variables = {
        v for v in all_core_variables_filtered
        if v.split(".", 1)[0] in non_repeatable_entity_names
    }

    # --- Prepare and Validate Non-Repeatable Data ---
    print("\n--- Processing Non-Repeatable Data ---")
    FORMATED_FILEPATH_NON_REP = os.path.join(
        app_path, "idea4rc_data_non_repeatable.xlsx")
    format_normalized_table(
        data_file, FORMATED_FILEPATH_NON_REP, all_non_repeatable_core_variables)
    non_repeatable_validator = context.sources.pandas_default.read_excel(
        FORMATED_FILEPATH_NON_REP, asset_name="non_repeatable_data_asset")
    df_non_repeatable = pd.read_excel(FORMATED_FILEPATH_NON_REP)  # Load the DF
    print(f"Validator 'non_repeatable_validator' created for non-repeatable data.")

    # --- Initialize dictionary to hold validators for repeatable entities ---
    repeatable_entity_validators = {}
    repeatable_entity_checkpoint_results = {}

    # --- Load ALL Expectations (from suites_file, which is expectations_data.json) ---
    print(f"\n--- Loading expectations from {suites_file} ---")
    with open(suites_file, encoding="utf8") as f:
        # This is your expectations_data.json
        all_expectations_data = json.load(f)

    # NEW: build a map of expected datatype per column (Entity.Variable)

    def _norm_colname(name: str) -> str:
        if not isinstance(name, str):
            return name
        if "." in name:
            return name
        if "_" in name:
            a, b = name.split("_", 1)
            return f"{a}.{b}"
        return name

    def _is_int_type(t) -> bool:
        # Accept common integer type spellings: Integer, int, int64, Int64, etc.
        return isinstance(t, str) and ("int" in t.lower())

    def _parse_int_if_possible(v):
        if isinstance(v, int):
            return v
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, str):
            s = v.strip()
            if s.startswith(("+", "-")):
                sign, rest = s[0], s[1:]
            else:
                sign, rest = "", s
            if rest.isdigit():
                try:
                    return int(s)
                except Exception:
                    return v
        return v

    def _coerce_int_kwargs_for_column(kwargs: dict, expected_type_map: dict, col: str):
        # Mutates kwargs in place when the column's expected type is integer
        if not isinstance(col, str):
            return
        t = expected_type_map.get(col)
        if not _is_int_type(t):
            return

        # Keys commonly holding literal comparison values
        for k in ("min_value", "max_value", "value"):
            if k in kwargs:
                kwargs[k] = _parse_int_if_possible(kwargs[k])

        if "value_set" in kwargs and isinstance(kwargs["value_set"], (list, tuple, set)):
            kwargs["value_set"] = [_parse_int_if_possible(
                x) for x in kwargs["value_set"]]

    # Pre-scan expectations to collect expected types
    expected_type_by_col = {}
    for item in all_expectations_data:
        for exp in item.get("expectations", []) or []:
            meta = exp.get("metadata", {})
            if meta.get("ge_name") == "expect_column_values_to_be_of_type":
                # Merge args to dict
                args_list = meta.get("args", []) or []
                merged = {k: v for d in args_list for k, v in d.items()}
                col = _norm_colname(merged.get("column"))
                typ = merged.get("type_") or merged.get("type")
                if isinstance(col, str) and typ:
                    expected_type_by_col[col] = typ

    # --- NEW: capture coercions that turned non-empty strings into NA ----------
    coercion_coerced_to_na_nonrep = collections.defaultdict(
        set)  # col -> {pid}
    coercion_coerced_to_na_rep = collections.defaultdict(
        lambda: collections.defaultdict(set))  # ent -> col -> {pid}

    def _coerce_df_numeric_types(df: pd.DataFrame, type_map: dict, context: str | None = None) -> pd.DataFrame:
        """
        Coerce dataframe columns to expected numeric types, and record rows where
        non-empty strings were coerced to NA (per patient_id) so we can flag datatype errors.
        context: "nonrep" or entity name for repeatables.
        """
        if df is None or df.empty:
            return df
        out = df.copy()
        has_pid = "patient_id" in out.columns

        for col, t in type_map.items():
            if col not in out.columns or not isinstance(t, str):
                continue
            tl = t.lower()
            try:
                # only track coercion for numeric targets
                if "int" in tl or "float" in tl:
                    ser = out[col]
                    # raw string emptiness check
                    ser_str = ser.astype(str)
                    non_empty = ser.notna() & ser_str.str.strip().ne("")
                    # attempt numeric conversion (don't mutate yet)
                    numeric = pd.to_numeric(ser, errors="coerce")
                    # bad when original was non-empty but numeric is NA
                    bad_mask = non_empty & numeric.isna()
                    if has_pid and bad_mask.any():
                        bad_pids = set(
                            out.loc[bad_mask, "patient_id"].astype(str))
                        if context == "nonrep":
                            coercion_coerced_to_na_nonrep[col].update(bad_pids)
                        elif isinstance(context, str):
                            coercion_coerced_to_na_rep[context][col].update(
                                bad_pids)

                    # now assign coerced column
                    if "int" in tl:
                        out[col] = numeric.astype("Int64")
                    else:  # float
                        out[col] = numeric

                # leave bool/str as-is (already handled reasonably)
            except Exception:
                # leave column untouched if coercion fails
                pass
        return out

    # NEW: rebuild non_repeatable validator using coerced dataframe so GE sees integers (not floats)
    try:
        # coerce types on the already loaded df_non_repeatable
        df_non_repeatable = _coerce_df_numeric_types(
            df_non_repeatable, expected_type_by_col, context="nonrep")
        # swap the validator to use the coerced dataframe
        non_repeatable_validator = context.sources.pandas_default.read_dataframe(
            df_non_repeatable, asset_name="non_repeatable_data_asset"
        )
        print("Recreated non_repeatable_validator with coerced dtypes.")
    except Exception as e:
        print(f"WARNING: could not coerce dtypes for non-repeatable data: {e}")

    # Stores DataFrames for repeatable entities for the Quality Summarization
    repeatable_entity_dataframes = {}

    # --- Process and Route Expectations ---
    for item_definition in all_expectations_data:
        if "expectations" not in item_definition or not item_definition["expectations"]:
            continue

        # Get the primary entity context from the item definition itself (e.g., "Patient_sex" from item_definition["col1"])
        # This will be used as a fallback for table-level expectations.
        context_entity_variable_from_col1 = item_definition.get("col1", "")

        for expectation_details in item_definition["expectations"]:
            ge_name = expectation_details["metadata"]["ge_name"]
            args_list_original = expectation_details["metadata"]["args"]
            dimensions = expectation_details["metadata"]["dimensions"]

            current_validator = non_repeatable_validator  # Default validator
            entity_name_for_routing = None

            # Make a deep copy of args_list to modify it for processing
            # without affecting the original expectations_data if it's used elsewhere.
            args_list = json.loads(json.dumps(args_list_original))

            # Standardize column names in args to Entity.Variable format and attempt type conversion
            # This part is from your existing script, with slight modifications for clarity
            # and to ensure 'column' key is handled if it's Entity_Variable format.
            # Will store the 'Entity.Variable' formatted column name
            target_column_for_expectation = None

            for arg_dict in args_list:
                for key, value in arg_dict.items():
                    new_value = value
                    if isinstance(value, str):
                        # If the key is 'column' and value has '_', convert it to Entity.Variable
                        if key == "column" and '_' in value and '.' not in value:  # e.g. "Patient_sex" -> "Patient.sex"
                            parts = value.split('_', 1)
                            if len(parts) == 2:
                                new_value = f"{parts[0]}.{parts[1]}"
                        # Your original replacement for other string values
                        elif key != "column" and isinstance(value, str):
                            new_value = value.replace('_', '.')

                        # Attempt int conversion for values that are all digits or negative digits
                        # Be cautious with this if some string values are meant to be codes that look like numbers
                        if isinstance(new_value, str) and (new_value.isdigit() or (new_value.startswith('-') and new_value[1:].isdigit())):
                            try:
                                new_value = int(new_value)
                            except ValueError:
                                pass  # Keep as string
                    arg_dict[key] = new_value  # Update the copied arg_dict

                    if key == "column":
                        # Store the (potentially converted) column name
                        target_column_for_expectation = arg_dict[key]

            # ── tumour-type filter: skip whole expectation if any target column is out of scope
            # Collect every column referenced in this expectation
            cols_in_expectation = [
                v for d in args_list for v in d.values()
                # Entity.Variable form
                if isinstance(v, str) and "." in v
            ]
            if cols_in_expectation and not all(keep(c, ALLOWED) for c in cols_in_expectation):
                print(f"    Skipping {ge_name} – tumour_type '{disease_type}' "
                      f"excludes columns {cols_in_expectation}")
                continue

            # Determine entity for routing
            if target_column_for_expectation and '.' in target_column_for_expectation:
                entity_name_for_routing = target_column_for_expectation.split('.')[
                    0]
            elif not target_column_for_expectation and context_entity_variable_from_col1:
                # Fallback for table-level expectations: parse col1
                if '_' in context_entity_variable_from_col1 and '.' not in context_entity_variable_from_col1:
                    entity_name_for_routing = context_entity_variable_from_col1.split('_', 1)[
                        0]
                elif '.' in context_entity_variable_from_col1:  # If col1 was already Entity.Variable
                    entity_name_for_routing = context_entity_variable_from_col1.split('.')[
                        0]
                else:  # col1 does not provide clear entity prefix
                    print(
                        f"  Info: Table-level expectation '{ge_name}' from item '{context_entity_variable_from_col1}' does not have a clear entity prefix in col1. Defaulting to non_repeatable_validator.")
            # else: entity_name_for_routing remains None, will default to non_repeatable_validator
            if entity_name_for_routing and not keep(f"{entity_name_for_routing}.dummy", ALLOWED):
                print(f"    Skipping table-level expectation {ge_name} – "
                      f"entity '{entity_name_for_routing}' not in tumour_type '{disease_type}'")
                continue

            # Select the validator
            if entity_name_for_routing:
                if entity_name_for_routing in non_repeatable_entity_names:
                    current_validator = non_repeatable_validator
                elif entity_name_for_routing in repeatable_entity_names:
                    if entity_name_for_routing not in repeatable_entity_validators:
                        print(
                            f"  Preparing data and validator for new repeatable entity: {entity_name_for_routing}")
                        df_entity = prepare_repeatable_entity_data(
                            entity_name_for_routing,
                            data_file,
                            repeated_entities_data["repeteables"],
                            app_path
                        )
                        if not df_entity.empty:
                            # NEW: coerce repeatable DF types before building validator
                            df_entity = _coerce_df_numeric_types(
                                df_entity, expected_type_by_col, context=entity_name_for_routing)
                            asset_name_for_entity = f"{entity_name_for_routing}_data_asset"
                            repeatable_entity_dataframes[entity_name_for_routing] = df_entity
                            validator_instance = context.sources.pandas_default.read_dataframe(
                                df_entity, asset_name=asset_name_for_entity)
                            repeatable_entity_validators[entity_name_for_routing] = validator_instance
                            current_validator = validator_instance
                        else:
                            print(
                                f"  Warning: Could not prepare data for repeatable entity {entity_name_for_routing}. Skipping expectation '{ge_name}'.")
                            continue
                    else:
                        current_validator = repeatable_entity_validators[entity_name_for_routing]
                else:
                    # Dynamic fallback: if this looks like a repeatable entity in data, prepare it on the fly
                    looks_repeatable_in_data = False
                    try:
                        if 'df_long_all' in globals() and not df_long_all.empty:
                            looks_repeatable_in_data = any(
                                str(cv).startswith(
                                    f"{entity_name_for_routing}.")
                                for cv in df_long_all["core_variable"].astype(str)
                            )
                    except Exception:
                        looks_repeatable_in_data = False

                    if looks_repeatable_in_data:
                        print(
                            f"  Detected entity '{entity_name_for_routing}' in data but not in config. Preparing dynamically.")
                        df_entity = prepare_repeatable_entity_data(
                            entity_name_for_routing,
                            data_file,
                            repeated_entities_data.get("repeteables", {}),
                            app_path
                        )
                        if not df_entity.empty:
                            df_entity = _coerce_df_numeric_types(
                                df_entity, expected_type_by_col, context=entity_name_for_routing)
                            asset_name_for_entity = f"{entity_name_for_routing}_data_asset"
                            repeatable_entity_dataframes[entity_name_for_routing] = df_entity
                            validator_instance = context.sources.pandas_default.read_dataframe(
                                df_entity, asset_name=asset_name_for_entity)
                            repeatable_entity_validators[entity_name_for_routing] = validator_instance
                            current_validator = validator_instance
                        else:
                            print(
                                f"  Warning: Dynamic preparation failed for '{entity_name_for_routing}'. Defaulting to non_repeatable_validator for '{ge_name}'.")
                            # current_validator remains non_repeatable_validator
                    else:
                        print(f"  Warning: Entity '{entity_name_for_routing}' (derived from '{target_column_for_expectation or context_entity_variable_from_col1}') is not defined in non_repeteables or repeteables and not found in data. Defaulting to non_repeatable_validator for expectation '{ge_name}'.")
            # else: current_validator remains non_repeatable_validator

            # Apply the expectation
            # NEW: make sure validator_name_for_log is defined even if method is missing
            validator_name_for_log = "non_repeatable_validator"
            if current_validator != non_repeatable_validator:
                for name, val_instance in repeatable_entity_validators.items():
                    if val_instance == current_validator:
                        validator_name_for_log = f"validator_for_{name}"
                        break

            method = getattr(current_validator, ge_name, None)
            if method:
                combined_kwargs = {
                    k: v for d in args_list for k, v in d.items()}
                combined_kwargs["meta"] = {"dimensions": dimensions}

                # NEW: never skip rows with missing values for type/not-null checks
                if ge_name in ("expect_column_values_to_be_of_type", "expect_column_values_to_not_be_null"):
                    combined_kwargs.setdefault("ignore_row_if", "never")

                # NEW: Coerce expectation argument values to integers if the column is expected to be Integer
                col_for_type = target_column_for_expectation or None
                if not col_for_type and context_entity_variable_from_col1:
                    col_for_type = _norm_colname(
                        context_entity_variable_from_col1)
                if isinstance(col_for_type, str):
                    col_for_type = _norm_colname(col_for_type)
                    _coerce_int_kwargs_for_column(
                        combined_kwargs, expected_type_by_col, col_for_type)

                validator_name_for_log = "non_repeatable_validator"
                if current_validator != non_repeatable_validator:
                    for name, val_instance in repeatable_entity_validators.items():
                        if val_instance == current_validator:
                            validator_name_for_log = f"validator_for_{name}"
                            break

                # ------------------------------------------------------------------

                #  ⛔ Skip NOT-NULL checks for optional (min-card 0) non-repeatable
                # ------------------------------------------------------------------
                if (ge_name == "expect_column_values_to_not_be_null"
                        and current_validator is non_repeatable_validator):
                    ent = entity_name_for_routing or "UNKNOWN"
                    if entity_min_card.get(ent, 1) == 0:
                        print(
                            f"    Skipping {ge_name} on optional entity '{ent}'")
                        continue
                # ------------------------------------------------------------------

                try:
                    method(**combined_kwargs)
                except Exception as e:
                    print(
                        f"    ERROR applying expectation {ge_name} to {validator_name_for_log} with args {combined_kwargs}: {e}")
            else:
                print(
                    f"  Warning: Method {ge_name} not found in the selected validator ({validator_name_for_log}).")

    # --- Save Suites and Run Checkpoints ---

    # --- Save Suite and Run Checkpoint for Non-Repeatable Data ---
    non_repeatable_suite_name = "non_repeatable_default_suite"  # Define your suite name

    # Set the name on the ExpectationSuite object held by the validator
    if non_repeatable_validator.expectation_suite:
        non_repeatable_validator.expectation_suite.expectation_suite_name = non_repeatable_suite_name
    else:
        # This should ideally not happen if expectations were added.
        # If it's possible to have no expectations, you might need to create an empty named suite.
        # For now, assuming expectations were added, so validator.expectation_suite exists.
        print(
            f"Warning: non_repeatable_validator does not have an active suite. Creating one named '{non_repeatable_suite_name}'.")
        from great_expectations.core import ExpectationSuite
        new_suite = ExpectationSuite(
            expectation_suite_name=non_repeatable_suite_name)
        # If you created a new suite, you'd typically add it to the context first,
        # then get a validator for it. The current flow adds expectations to the validator's default suite.
        # So, the if block above should normally be sufficient.
        # Assigning a new one if it was None
        non_repeatable_validator.expectation_suite = new_suite

    # Save the suite using the validator. It will use the name set on validator.expectation_suite.
    non_repeatable_validator.save_expectation_suite(
        discard_failed_expectations=False)  # Removed expectation_suite_name kwarg
    print(
        f"Expectation suite '{non_repeatable_suite_name}' saved for non-repeatable data.")

    dataframe_asset = context.sources.add_pandas(
        "non_repeatable_validator_checkpoint"
    ).add_dataframe_asset(
        name="non_repeatable_data_asset",
        dataframe=df_non_repeatable,
    )
    batch_request = dataframe_asset.build_batch_request()

    # Checkpoint configuration still uses expectation_suite_name to load the correct suite
    checkpoint_main = context.add_or_update_checkpoint(
        name="non_repeatable_checkpoint",
        batch_request=batch_request,
        # This tells the checkpoint which suite to use
        expectation_suite_name=non_repeatable_suite_name,
        runtime_configuration={
            "result_format": {"result_format": "COMPLETE", "unexpected_index_column_names": ["patient_id", "original_source"], "return_unexpected_index_query": True}
        }
    )

    print(f"--- Debugging non_repeatable_validator before checkpoint run ---")
    if non_repeatable_validator.active_batch:
        print(
            f"Validator has an active batch with ID: {non_repeatable_validator.active_batch.id}")
        if hasattr(non_repeatable_validator.active_batch.data, "dataframe"):
            print(
                f"Number of rows in validator's active batch: {len(non_repeatable_validator.active_batch.data.dataframe)}")
            print(
                f"Sample of data in validator's active batch:\n{non_repeatable_validator.active_batch.data.dataframe.head()}")
        else:
            print("Validator's active batch data is not a direct Pandas DataFrame.")
    else:
        print("ERROR: non_repeatable_validator has NO active batch before checkpoint run!")

    print(
        f"Expectation suite name in validator: {non_repeatable_validator.expectation_suite.expectation_suite_name}")
    print(
        f"Number of expectations to run: {len(non_repeatable_validator.expectation_suite.expectations)}")

    # Now run the checkpoint
    checkpoint_result_main = checkpoint_main.run()
    results_dict = checkpoint_result_main.to_json_dict()
    with open(os.path.join(app_path, 'results_non_repeatable.json'), 'w') as f:
        json.dump(results_dict, f, indent=4)
    print("\nNon-repeatable data validation complete. Results saved.")

    # For Repeatable Entities
    for entity_name, entity_validator_for_suite_authoring in repeatable_entity_validators.items():  # Renamed for clarity
        print(
            f"\n--- Finalizing validation for repeatable entity: {entity_name} ---")

        if not entity_validator_for_suite_authoring.expectation_suite:
            print(
                f"Warning: Validator for entity {entity_name} does not have an active suite. Skipping checkpoint.")
            continue

        entity_suite_to_run = entity_validator_for_suite_authoring.expectation_suite.expectation_suite_name
        # Ensure the suite name is set on the suite object if not already done during creation
        entity_validator_for_suite_authoring.expectation_suite.expectation_suite_name = entity_suite_to_run
        entity_validator_for_suite_authoring.save_expectation_suite(
            discard_failed_expectations=False)
        print(
            f"Expectation suite '{entity_suite_to_run}' saved for {entity_name}.")

        # === MODIFICATION START: Use the stored DataFrame to create a fresh validator for the checkpoint ===
        df_current_entity = repeatable_entity_dataframes.get(
            entity_name)  # Retrieve the stored DataFrame

        if df_current_entity is None or df_current_entity.empty:
            print(
                f"Warning: DataFrame for entity '{entity_name}' not found or is empty in repeatable_entity_dataframes. Skipping checkpoint.")
            continue

        dataframe_asset = context.sources.add_pandas(
            f"{entity_name}_validator_checkpoint"
        ).add_dataframe_asset(
            name="f{entity_name}_data_asset",
            dataframe=df_current_entity,
        )
        batch_request = dataframe_asset.build_batch_request()

        checkpoint_entity = context.add_or_update_checkpoint(
            name=f"{entity_name}_checkpoint",
            expectation_suite_name=entity_suite_to_run,
            runtime_configuration={
                "result_format": {"result_format": "COMPLETE", "unexpected_index_column_names": ["patient_id", "record_id"], "return_unexpected_index_query": True}
            },
            batch_request=batch_request
        )

        entity_checkpoint_result = checkpoint_entity.run()
        repeatable_entity_checkpoint_results[entity_name] = entity_checkpoint_result.to_json_dict(
        )

        entity_results_filename = f"results_{entity_name}.json"
        with open(os.path.join(app_path, entity_results_filename), 'w') as f:
            json.dump(entity_checkpoint_result.to_json_dict(), f, indent=4)
        print(f"{entity_name} validation results saved to {entity_results_filename}")

    # Add main non-repeatable results
    if 'checkpoint_result_main' in locals() and checkpoint_result_main:
        # Keep this for specific use if needed
        results_dict_main = checkpoint_result_main.to_json_dict()
    else:
        results_dict_main = None  # Ensure it's defined for patient summary fallback

    # Will store tuples: (source_description, result_dict)
    all_checkpoint_results_with_source = []

    # Add main non-repeatable results
    if 'checkpoint_result_main' in locals() and checkpoint_result_main:
        results_dict_main = checkpoint_result_main.to_json_dict()
        all_checkpoint_results_with_source.append(
            ("Non-Repeatable Patient Data", results_dict_main))
    else:
        # Still needed for subsequent summaries if they depend on it by this name
        results_dict_main = None

    # Add results from repeatable entities
    if 'repeatable_entity_checkpoint_results' in locals():
        for entity_name, entity_result_dict in repeatable_entity_checkpoint_results.items():
            if entity_result_dict:  # Ensure it's not None
                all_checkpoint_results_with_source.append(
                    (f"Repeatable Entity: {entity_name}", entity_result_dict))

    if not all_checkpoint_results_with_source:
        print(
            "No checkpoint results found to generate detailed error reports or summaries.")
        # Potentially exit or skip further processing

    # In main.py, after populating all_checkpoint_results_with_source

    print("\n" + "="*30 + " DETAILED EXPECTATION FAILURE REPORT " + "="*30)
    if not all_checkpoint_results_with_source:
        print("No validation results to report on.")
    else:
        any_failure_found_overall = False
        for source_description, results_dict in all_checkpoint_results_with_source:
            if not results_dict:
                print(
                    f"\n--- Validation Results for: {source_description} ---")
                print("  No results dictionary found for this source.")
                continue

            print(f"\n--- Validation Results for: {source_description} ---")
            run_id_info = results_dict.get('run_id', {})
            print(
                f"  Run Name: {run_id_info.get('run_name', 'N/A')}, Run Time: {run_id_info.get('run_time', 'N/A')}")

            # Assume success if key missing (should not happen)
            overall_success_for_this_run = results_dict.get("success", True)

            found_failures_in_this_run = False
            for run_name_key, run_result_data in results_dict.get("run_results", {}).items():
                validation_result = run_result_data.get(
                    "validation_result", {})
                if not validation_result:
                    continue

                individual_expectation_results = validation_result.get(
                    "results", [])
                for expectation_outcome in individual_expectation_results:
                    # If this specific expectation failed
                    if not expectation_outcome.get("success", True):
                        found_failures_in_this_run = True
                        # Mark that at least one failure was found globally
                        any_failure_found_overall = True

                        config = expectation_outcome.get(
                            "expectation_config", {})
                        ge_name = config.get(
                            "expectation_type", "N/A_EXPECTATION_TYPE")
                        kwargs = config.get("kwargs", {})
                        column_name = kwargs.get(
                            "column", "N/A (Table-Level or Column not in kwargs)")

                        print(f"\n  [FAILED] Expectation: {ge_name}")
                        print(f"    Target Column: {column_name}")
                        if "meta" in config and "dimensions" in config["meta"]:
                            print(
                                f"    Dimensions: {config['meta']['dimensions']}")

                        result_details = expectation_outcome.get("result", {})
                        partial_unexpected_list = result_details.get(
                            "partial_unexpected_list", [])
                        partial_unexpected_index_list = result_details.get(
                            "partial_unexpected_index_list", [])

                        if partial_unexpected_index_list:
                            print(
                                f"    Problematic Entries (up to {len(partial_unexpected_index_list)} shown):")
                            for idx, failing_row_indices_dict in enumerate(partial_unexpected_index_list):
                                # failing_row_indices_dict already contains column names as keys from unexpected_index_column_names
                                # e.g., {"patient_id": "PID1", "original_source": "sourceA", "ActualColumnNameInError": "bad_value"}
                                # Or for repeatable: {"patient_id": "PID1", "record_id": "REC1", "ActualColumnNameInError": "bad_value"}

                                patient_id = failing_row_indices_dict.get(
                                    "patient_id", "PID_Not_Found")
                                record_id = failing_row_indices_dict.get(
                                    "record_id")  # Will be None if not present
                                original_source = failing_row_indices_dict.get(
                                    "original_source")  # Will be None if not present

                                identifier_str = f"Patient ID: {patient_id}"
                                if record_id:
                                    identifier_str += f", Record ID: {record_id}"
                                elif original_source:  # For non-repeatable, you used 'original_source'
                                    identifier_str += f", Source: {original_source}"

                                problem_value_str = "N/A"
                                if idx < len(partial_unexpected_list):
                                    problem_value_str = str(
                                        partial_unexpected_list[idx])

                                # Construct a more detailed reason string
                                reason = ""
                                if ge_name == "expect_column_values_to_not_be_null":
                                    reason = f"Value is NULL in column '{column_name}'"
                                elif ge_name == "expect_column_values_to_be_in_set":
                                    value_set_str = str(
                                        kwargs.get("value_set", "N/A"))
                                    reason = f"Value '{problem_value_str}' from column '{column_name}' not in expected set: {value_set_str}"
                                elif ge_name == "expect_column_values_to_be_between":
                                    min_val, max_val = kwargs.get(
                                        "min_value"), kwargs.get("max_value")
                                    reason = f"Value '{problem_value_str}' from column '{column_name}' not between {min_val} and {max_val}"
                                elif ge_name == "expect_column_values_not_to_be_future_date":
                                    reason = f"Date value '{problem_value_str}' from column '{column_name}' is a future date"
                                # Add more elif for other specific standard or custom expectations
                                elif "expect_radiotherapy_session_completeness" in ge_name or "expect_episode_event_completeness" in ge_name:
                                    # Custom expectations might have their specific structure in partial_unexpected_list
                                    # problem_value_str would be a dict here
                                    reason = f"Completeness check failed. Details: {problem_value_str}"
                                else:  # Generic fallback
                                    reason = f"Unexpected value: '{problem_value_str}' in column '{column_name}'"
                                    if not partial_unexpected_list and "observed_value" in result_details:
                                        reason = f"Observed value '{result_details['observed_value']}' was unexpected for table/column level check on '{column_name}'."

                                print(f"      - {identifier_str} -> {reason}")

                        # No index list, but have values (less common for row-level issues)
                        elif partial_unexpected_list:
                            print(
                                f"    Problematic Values (no specific row indices provided, up to {len(partial_unexpected_list)} shown): {partial_unexpected_list}")

                        elif "observed_value" in result_details:  # For table-level expectations or others without lists
                            print(
                                f"    Observed Value that failed expectation: {result_details['observed_value']}")
                        else:
                            print(
                                f"    No detailed unexpected list or observed value provided for this failure. Check full JSON results for expectation: {ge_name} on column/context: {column_name}.")
                        # Separator for details of next failed expectation
                        print("    " + "-"*20)

            if not found_failures_in_this_run and overall_success_for_this_run:
                print("  All expectations passed for this validation run.")
            elif not found_failures_in_this_run and not overall_success_for_this_run:
                print("  Overall validation for this run is False, but no individual expectation failures were detailed in results (check suite-level issues or evaluation parameters).")

        if not any_failure_found_overall:
            print(
                "\nCongratulations! All expectations passed across all validation runs.")
    print("="*30 + " END OF DETAILED REPORT " + "="*30 + "\n")

    all_checkpoint_result_dicts = [
        rd                                   # the dict itself
        for _src, rd in all_checkpoint_results_with_source
        if rd                                # skip None entries
    ]

    # --- Helpers for per‑patient totals/failures attribution --------------------

    def _entity_df_for_column(col: str):
        """Return the wide dataframe for the entity owning `col`."""
        try:
            ent = col.split(".", 1)[0]
            if ent in non_repeatable_entity_names:
                return df_non_repeatable if 'df_non_repeatable' in globals() else None
            return repeatable_entity_dataframes.get(ent)
        except Exception:
            return None

    def _per_patient_totals_for_col(col: str) -> dict:
        """
        Return {pid -> total_rows_evaluated_for_col} using the entity dataframe:
        - non-repeatable: 1 per patient
        - repeatable: number of instances (record_id) per patient
        """
        df = _entity_df_for_column(col)
        if df is None or col not in getattr(df, "columns", []):
            return {}
        if "patient_id" not in df.columns:
            return {}
        if "record_id" in df.columns:
            return (
                df.groupby("patient_id")["record_id"]
                .nunique(dropna=False)
                .astype(int)
                .to_dict()
            )
        return {str(pid): 1 for pid in df["patient_id"].astype(str).unique()}

    # ------------------------------------------------------------------
    # Figure out which columns actually had a NOT-NULL check
    # ------------------------------------------------------------------
    NULL_EXP = "expect_column_values_to_not_be_null"
    notnull_vars = set()

    for chk in all_checkpoint_result_dicts:
        if not chk:
            continue
        for run in chk.get("run_results", {}).values():
            for out in run.get("validation_result", {}).get("results", []):
                cfg = out.get("expectation_config", {})
                if cfg.get("expectation_type") != NULL_EXP:
                    continue
                col = cfg.get("kwargs", {}).get("column")
                if col:
                    notnull_vars.add(col)

    if not notnull_vars:
        print("WARNING: no NOT-NULL expectations found – phase summary will be empty")

    # # ── universal set for QC variable-percentages ───────────────────────────
    # non_optional_vars_set = {
    #     v for v in all_core_variables_filtered
    #     if entity_min_card.get(v.split(".", 1)[0], 1) == 1     # entity mandatory
    # }
    # num_non_optional_vars = len(non_optional_vars_set)

    non_optional_vars_set = notnull_vars
    num_non_optional_vars = len(notnull_vars)

    # ---------------------------------------------------------------------------
    # --- Generate Missing-value & Consistency summary per original_source -------
    print("\n--- Generating datasource summary from NOT-NULL QC results ----------")

    try:
        # df_long_all = pd.read_excel(data_file, dtype=str)
        df_long_all = read_table(data_file, dtype=str)

    except Exception as e:
        print(f"ERROR reading long-format file: {e}")
        df_long_all = pd.DataFrame()

    # ── 1.  First-seen rule for canonical source + detect mismatches ────────────
    canonical_src = {}          # core_variable → first source encountered
    var_has_mismatch = set()

    if not df_long_all.empty and {"core_variable", "original_source"}.issubset(df_long_all.columns):
        for _, row in df_long_all.iterrows():
            var = row["core_variable"]
            src = str(row["original_source"]).strip() if pd.notna(
                row["original_source"]) else "NULL"

            # first time we see this variable ⇒ lock the source
            if var not in canonical_src:
                canonical_src[var] = src
            elif src != canonical_src[var]:
                var_has_mismatch.add(var)
    else:
        print("Required columns (core_variable, original_source) missing.")

    # ── 2.  Collect NOT-NULL QC metrics from GE checkpoint results ─────────────
    NULL_EXP = "expect_column_values_to_not_be_null"
    # var → [element_count, unexpected_count]
    var_counts = collections.defaultdict(lambda: [0, 0])

    for chk in all_checkpoint_result_dicts:
        if not chk:
            continue
        for _, run in chk.get("run_results", {}).items():
            for out in run.get("validation_result", {}).get("results", []):
                cfg = out.get("expectation_config", {})
                if cfg.get("expectation_type") != NULL_EXP:
                    continue
                var = cfg.get("kwargs", {}).get("column")
                if not var:
                    continue
                ec = out.get("result", {}).get("element_count", 0)
                uc = out.get("result", {}).get("unexpected_count", 0)
                var_counts[var][0] += ec
                var_counts[var][1] += uc

    # ── 3a.  Variable-level tallies  ───────────────────────────────────────────
    # 1️⃣  Map every non-optional variable → its canonical source
    # NEW: compute dataset-level default source to use when canonical is missing/NULL
    unique_sources = set()
    try:
        if not df_long_all.empty and "original_source" in df_long_all.columns:
            unique_sources = {
                str(s).strip()
                for s in df_long_all["original_source"].dropna().unique()
                if str(s).strip()
            }
    except Exception:
        unique_sources = set()

    default_source = None
    if len(unique_sources) == 1:
        default_source = next(iter(unique_sources))
    elif len(unique_sources) == 2 and NLP_TAG in unique_sources:
        default_source = next(iter(unique_sources - {NLP_TAG}), None)

    def _fallback_source_for(var: str) -> str:
        src = canonical_src.get(var)
        if src is None or src in {"", "NULL"}:
            return default_source or "UNKNOWN_SOURCE"
        return src

    # Map ALL variables (for dimension aggregation), plus the NOT-NULL subset used below
    var2src_all = {v: _fallback_source_for(
        v) for v in all_core_variables_filtered}
    var2src = {v: _fallback_source_for(v) for v in non_optional_vars_set}

    # print vars with UNKNOWN_SOURCE
    if "UNKNOWN_SOURCE" in var2src.values():
        print("WARNING: Some variables have UNKNOWN_SOURCE:")
        for var, src in var2src.items():
            if src == "UNKNOWN_SOURCE":
                print(f"  {var} → {src}")

    datasources = sorted(set(var2src.values()) | set(
        df_long_all.original_source.dropna().unique()))

    # 2️⃣  Variable-level failure map generated from NOT-NULL expectation results
    var_missing = {v for v, (_, uc) in var_counts.items() if uc}

    # ── NEW: Per-datasource Dimension (Completeness/Conformance/Plausibility/Total) tallies ──
    dims_known = ["Plausibility", "Conformance", "Completeness"]
    ds_dim_counts = collections.defaultdict(lambda: {
        "Plausibility": {"Passed": 0, "Failed": 0, "Total": 0},
        "Conformance": {"Passed": 0, "Failed": 0, "Total": 0},
        "Completeness": {"Passed": 0, "Failed": 0, "Total": 0},
        "Total": {"Passed": 0, "Failed": 0, "Total": 0},
    })

    for chk in all_checkpoint_result_dicts:
        if not chk:
            continue
        for _, run in chk.get("run_results", {}).items():
            for out in run.get("validation_result", {}).get("results", []):
                cfg = out.get("expectation_config", {}) or {}
                kwargs = cfg.get("kwargs", {}) or {}
                col = kwargs.get("column")
                if not col:
                    # Skip table-level expectations without a target column; cannot attribute to a datasource reliably
                    continue
                # find datasource for this column using our fallback rules
                src = var2src_all.get(col, default_source or "UNKNOWN_SOURCE")

                res = out.get("result", {}) or {}
                elem = int(res.get("element_count", 0) or 0)
                unexp = int(res.get("unexpected_count", 0) or 0)
                success = bool(out.get("success", True))

                # Mirror dimension_summary_results logic for zero-element failures
                if elem == 0 and not success:
                    tot = 1
                    fail = 1
                else:
                    tot = elem
                    fail = unexp
                pass_ = max(0, tot - fail)

                dims = (cfg.get("meta", {}) or {}).get("dimensions", []) or []
                # Update per-dimension buckets
                for d in dims:
                    if d in ds_dim_counts[src]:
                        ds_dim_counts[src][d]["Total"] += tot
                        ds_dim_counts[src][d]["Failed"] += fail
                        ds_dim_counts[src][d]["Passed"] += pass_
                # Always update 'Total' category
                ds_dim_counts[src]["Total"]["Total"] += tot
                ds_dim_counts[src]["Total"]["Failed"] += fail
                ds_dim_counts[src]["Total"]["Passed"] += pass_

    # Finalise per-datasource percentages

    def _finalise_dim_block(block: dict) -> dict:
        out = {}
        for name, stats in block.items():
            t = stats.get("Total", 0)
            f = stats.get("Failed", 0)
            p = max(0, t - f) if "Passed" not in stats else stats["Passed"]
            pct = f"{(p / t * 100):.1f}%" if t else "100.0%"
            out[name] = {"Passed": p, "Failed": f,
                         "Total": t, "PercentagePass": pct}
        return out

    # 3️⃣  Patient-level tallies per datasource (threshold-based using NOT-NULL results)
    ds_pat_counts = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {"tot": 0, "fail": 0})
    )
    for chk in all_checkpoint_result_dicts:
        if not chk:
            continue
        for _, run in chk.get("run_results", {}).items():
            for out in run.get("validation_result", {}).get("results", []):
                cfg = out.get("expectation_config", {})
                if cfg.get("expectation_type") != "expect_column_values_to_not_be_null":
                    continue
                col = (cfg.get("kwargs", {}) or {}).get("column")
                if not col:
                    continue
                src = var2src_all.get(col, default_source or "UNKNOWN_SOURCE")
                totals = _per_patient_totals_for_col(col)
                # add totals
                for pid, t in totals.items():
                    ds_pat_counts[src][str(pid)]["tot"] += int(t)
                # add failures
                res = out.get("result", {}) or {}
                idx_list = res.get("unexpected_index_list") or res.get(
                    "partial_unexpected_index_list") or []
                if idx_list:
                    for idx in idx_list:
                        if isinstance(idx, dict) and "patient_id" in idx and idx["patient_id"] is not None:
                            pid = str(idx["patient_id"])
                            ds_pat_counts[src][pid]["fail"] += 1
                elif int(res.get("unexpected_count", 0) or 0):
                    # conservative fallback: 1 failure for every patient that had at least one evaluated row
                    for pid in totals.keys():
                        ds_pat_counts[src][str(pid)]["fail"] += 1

    # 4️⃣  Build two rows per datasource
    rows_ds = []
    for src in datasources:
        # ----- Variable-unit row -------------------------------------------
        vars_in_src = {v for v in non_optional_vars_set if var2src[v] == src}
        var_total_src = len(vars_in_src)

        fail_vars = vars_in_src & var_missing
        miss_v = len(fail_vars)
        pass_v = var_total_src - miss_v

        # NEW: patient pass/fail via threshold
        pat_counts = ds_pat_counts.get(src, {})
        p_tot = len(pat_counts)
        p_pass = sum(
            1
            for pid, c in pat_counts.items()
            if c["tot"] > 0 and ((c["tot"] - c["fail"]) / c["tot"]) >= PATIENT_PASS_THRESHOLD
        )
        p_fail = max(0, p_tot - p_pass)

        total_qcs_ds = 0
        total_failed_qcs_ds = 0
        for v in var_counts:
            if var2src[v] == src:
                total_qcs_ds += var_counts[v][0]
                total_failed_qcs_ds += var_counts[v][1]
        total_passed_qcs_ds = total_qcs_ds - total_failed_qcs_ds

        row_dimensions = _finalise_dim_block(ds_dim_counts.get(src, {
            "Plausibility": {"Passed": 0, "Failed": 0, "Total": 0},
            "Conformance": {"Passed": 0, "Failed": 0, "Total": 0},
            "Completeness": {"Passed": 0, "Failed": 0, "Total": 0},
            "Total": {"Passed": 0, "Failed": 0, "Total": 0},
        }))

        rows_ds.append({
            "Datasource":  src,
            "total_variables":       var_total_src,
            "failed_variables":      miss_v,
            "passed_variables":      pass_v,
            "complete_variables_percentage": round((pass_v / var_total_src) * 100, 2) if var_total_src else "not computed",
            "missing_variables_percentage": round((miss_v / var_total_src) * 100, 2) if var_total_src else "not computed",
            # NEW: threshold-based patient counts
            "total_patients":        p_tot,
            "failed_patients":       p_fail,
            "passed_patients":       p_pass,
            "complete_patients_percentage": round((p_pass / p_tot) * 100, 2) if p_tot else "not computed",
            "missing_patients_percentage": round((p_fail / p_tot) * 100, 2) if p_tot else "not computed",
            "total_quality_checks": total_qcs_ds,
            "failed_quality_checks": total_failed_qcs_ds,
            "passed_quality_checks": total_passed_qcs_ds,
            "quality_checks_percentage_passed": round(total_passed_qcs_ds / (total_qcs_ds * 100), 2) if total_qcs_ds else 0,
            "quality_checks_percentage_fail": round(total_failed_qcs_ds / (total_passed_qcs_ds * 100), 2) if total_passed_qcs_ds else 0,
            "dimensions": row_dimensions,
        })

    # 5️⃣  Persist to JSON
    ds_json = os.path.join(
        app_path, "datasource_missingness_results.json")
    with open(ds_json, "w", encoding="utf-8") as fh:
        json.dump(rows_ds, fh, indent=4)

    print(f"Datasource QC summary saved to: {ds_json}")

    # ---------------------------------------------------------------------------

    DESC_MAP = {row["col1"]: row.get("col2", "")
                for row in all_expectations_data}

    # --- Generate Variable‐level QC Summary ---
    print("\n--- Generating Aggregated Variable‐level QC Summary ---")
    variable_qc = {}

    # all_checkpoint_results_with_source is a list of tuples: (source_desc, result_dict)
    for source_desc, results_dict in all_checkpoint_results_with_source:
        for run_name, run_data in results_dict.get("run_results", {}).items():
            validation = run_data.get("validation_result", {})
            for outcome in validation.get("results", []):
                cfg = outcome.get("expectation_config", {})
                col = cfg.get("kwargs", {}).get("column")
                if not col:
                    # skip table‐level or column‐independent checks
                    continue

                res = outcome.get("result", {})
                # element_count may be 0 or missing for table‐level checks; default to 1
                total = res.get("element_count", 1) or 1
                failed = res.get("unexpected_count", 0)

                if col not in variable_qc:
                    variable_qc[col] = {
                        "Variable":     col,
                        # NEW
                        "Description":  DESC_MAP.get(col.replace(".", "_"))
                        or DESC_MAP.get(col.split(".")[-1], ""),
                        "Total":        0,
                        "Failed":       0
                    }

                variable_qc[col]["Total"] += total
                variable_qc[col]["Failed"] += failed

    # Calculate Passed and PercentagePass
    for stats in variable_qc.values():
        stats["Passed"] = stats["Total"] - stats["Failed"]
        stats["PercentagePass"] = (
            round((stats["Passed"] / stats["Total"]) * 100, 2)
            if stats["Total"] else 100.0
        )

    # Write out to JSON
    variable_summary_path = os.path.join(
        app_path, "variable_summary_results.json")
    with open(variable_summary_path, "w") as f:
        json.dump(list(variable_qc.values()), f, indent=4)

    print(f"Variable‐level QC summary saved to: {variable_summary_path}")

    # ── Generate Datatype Expectation Summary ( expect_column_values_to_be_of_type ) ──
    print("\n--- Generating Datatype Expectation Summary ------------------------")

    # 1) Collect missingness per column from NOT-NULL results (and fallback to DF scan)
    NULL_EXP = "expect_column_values_to_not_be_null"
    missing_unexp_by_col: dict[str, int] = {}

    for _src, results_dict in all_checkpoint_results_with_source:
        if not results_dict:
            continue
        for _run_name, run_data in results_dict.get("run_results", {}).items():
            validation = run_data.get("validation_result", {}) or {}
            for out in validation.get("results", []) or []:
                cfg = out.get("expectation_config", {}) or {}
                if cfg.get("expectation_type") != NULL_EXP:
                    continue
                col = (cfg.get("kwargs", {}) or {}).get("column")
                if not col:
                    continue
                unexp = int((out.get("result", {}) or {}).get(
                    "unexpected_count", 0) or 0)
                missing_unexp_by_col[col] = missing_unexp_by_col.get(
                    col, 0) + unexp

    def _blank_count_from_df(col: str) -> int:
        try:
            ent = col.split(".", 1)[0]
            # Non-repeatable
            if ent in non_repeatable_entity_names and 'df_non_repeatable' in globals():
                if col in getattr(df_non_repeatable, "columns", []):
                    ser = df_non_repeatable[col]
                    return int(ser.isna().sum() + (ser.astype(str).str.strip() == "").sum())
            # Repeatable
            if ent in repeatable_entity_dataframes:
                df_ent = repeatable_entity_dataframes.get(ent)
                if df_ent is not None and col in getattr(df_ent, "columns", []):
                    ser = df_ent[col]
                    return int(ser.isna().sum() + (ser.astype(str).str.strip() == "").sum())
        except Exception:
            pass
        return 0

    def _patients_for_col(col: str) -> set[str]:
        """All patient_ids present for the entity of this column (best-effort fallback)."""
        out = set()
        try:
            ent = col.split(".", 1)[0]
            if ent in non_repeatable_entity_names and 'df_non_repeatable' in globals():
                if "patient_id" in getattr(df_non_repeatable, "columns", []):
                    out |= set(
                        df_non_repeatable["patient_id"].astype(str).unique())
            elif ent in repeatable_entity_dataframes:
                df_ent = repeatable_entity_dataframes.get(ent)
                if df_ent is not None and "patient_id" in df_ent.columns:
                    out |= set(df_ent["patient_id"].astype(str).unique())
            elif 'df_long_all' in globals() and not df_long_all.empty:
                tmp = df_long_all[df_long_all["core_variable"] == col]
                if not tmp.empty and "patient_id" in tmp.columns:
                    out |= set(tmp["patient_id"].astype(str).unique())
        except Exception:
            pass
        return out

    def _patients_with_blank_in_col(col: str) -> set[str]:
        """Patients where this column has blank/NA (best-effort, per entity DF first, fallback long table)."""
        out = set()
        try:
            ent = col.split(".", 1)[0]
            if ent in non_repeatable_entity_names and 'df_non_repeatable' in globals() and col in getattr(df_non_repeatable, "columns", []):
                ser = df_non_repeatable[col]
                mask = ser.isna() | (ser.astype(str).str.strip() == "")
                if "patient_id" in df_non_repeatable.columns:
                    out |= set(
                        df_non_repeatable.loc[mask, "patient_id"].astype(str))
            elif ent in repeatable_entity_dataframes:
                df_ent = repeatable_entity_dataframes.get(ent)
                if df_ent is not None and col in df_ent.columns and "patient_id" in df_ent.columns:
                    ser = df_ent[col]
                    mask = ser.isna() | (ser.astype(str).str.strip() == "")
                    out |= set(df_ent.loc[mask, "patient_id"].astype(str))
            elif 'df_long_all' in globals() and not df_long_all.empty:
                tmp = df_long_all[df_long_all["core_variable"] == col]
                if not tmp.empty:
                    vals = tmp["value"].astype(str)
                    mask = tmp["value"].isna() | (vals.str.strip() == "")
                    out |= set(tmp.loc[mask, "patient_id"].astype(str))
        except Exception:
            pass
        return out

    datatype_exp_name = "expect_column_values_to_be_of_type"
    datatype_results_accumulator = {}

    for source_desc, results_dict in all_checkpoint_results_with_source:
        if not results_dict:
            continue
        for _run_name, run_data in results_dict.get("run_results", {}).items():
            validation = run_data.get("validation_result", {})
            for outcome in validation.get("results", []):
                cfg = outcome.get("expectation_config", {})
                if cfg.get("expectation_type") != datatype_exp_name:
                    continue
                kwargs_cfg = cfg.get("kwargs", {})
                col = kwargs_cfg.get("column")
                expected_type = kwargs_cfg.get("type_")
                if not col:
                    continue  # skip malformed entries
                success = outcome.get("success", False)
                res = outcome.get("result", {})
                # sometimes 0 for table-level
                element_count = res.get("element_count", 0) or 0
                unexpected_count = res.get("unexpected_count", 0) or 0
                # Current datatype info
                observed_value = res.get("observed_value")

                entry = datatype_results_accumulator.setdefault(col, {
                    "Variable": col,
                    "ExpectedType": expected_type,
                    "CurrentDatatype": observed_value,
                    "TotalElements": 0,
                    "UnexpectedCount": 0,
                    "AllSucceeded": True,
                    "Sources": set(),
                    "PatientsFailed": set(),  # ← collect failing patient_ids
                })

                # If differing expected types appear, keep the first but note mismatch
                if entry["ExpectedType"] != expected_type and expected_type is not None:
                    entry.setdefault("TypeMismatchWith", set()
                                     ).add(str(expected_type))

                # Update current datatype if we have new information (unless already marked as Missing later)
                if observed_value is not None and entry.get("CurrentDatatype") != "Missing":
                    entry["CurrentDatatype"] = observed_value

                entry["TotalElements"] += element_count
                entry["UnexpectedCount"] += unexpected_count
                entry["AllSucceeded"] = entry["AllSucceeded"] and bool(success)
                entry["Sources"].add(source_desc)

                # Collect failing patient IDs from GE-provided indices
                idx_list = (
                    res.get("unexpected_index_list")
                    or res.get("partial_unexpected_index_list")
                    or []
                )
                for idx in idx_list:
                    if isinstance(idx, dict) and "patient_id" in idx and idx["patient_id"] is not None:
                        entry["PatientsFailed"].add(str(idx["patient_id"]))

    # 2) Treat missing values as pass for datatype summary (do not mark failure)
    for col, entry in datatype_results_accumulator.items():
        miss_ct = missing_unexp_by_col.get(col, 0)
        if miss_ct == 0:
            # fallback if NOT-NULL wasn’t executed for this column
            miss_ct = _blank_count_from_df(col)
        if miss_ct > 0:
            # Annotate CurrentDatatype for visibility if nothing observed, but do not mark as failure
            if entry.get("CurrentDatatype") is None:
                entry["CurrentDatatype"] = "Missing"
            # Do NOT flip AllSucceeded to False and do NOT add patients to PatientsFailed for missing-only
            pass

    # --- NEW: inject coercion-to-NA events into datatype summary ---------------
    # Merge logs nonrep + repeat into {col -> set(patient_id)}
    _coercion_by_col: dict[str, set[str]] = collections.defaultdict(set)
    for c, pids in coercion_coerced_to_na_nonrep.items():
        _coercion_by_col[c].update({str(p) for p in pids})
    for ent, cmap in coercion_coerced_to_na_rep.items():
        for c, pids in cmap.items():
            _coercion_by_col[c].update({str(p) for p in pids})

    for col, pids in _coercion_by_col.items():
        if not pids:
            continue
        # ensure an entry exists
        entry = datatype_results_accumulator.setdefault(col, {
            "Variable": col,
            "ExpectedType": expected_type_by_col.get(col),
            "CurrentDatatype": None,
            "TotalElements": 0,
            "UnexpectedCount": 0,
            "AllSucceeded": True,
            "Sources": set(),
            "PatientsFailed": set(),
        })
        # Mark as failed due to string→NA coercion
        entry["AllSucceeded"] = False
        entry["PatientsFailed"].update(pids)
        # reflect observed type as string
        entry["CurrentDatatype"] = "string"

    # 2) Treat missing values as pass for datatype summary (do not mark failure)
    for col, entry in datatype_results_accumulator.items():
        miss_ct = missing_unexp_by_col.get(col, 0)
        if miss_ct == 0:
            # fallback if NOT-NULL wasn’t executed for this column
            miss_ct = _blank_count_from_df(col)
        if miss_ct > 0:
            # Annotate CurrentDatatype for visibility if nothing observed, but do not mark as failure
            if entry.get("CurrentDatatype") is None:
                entry["CurrentDatatype"] = "Missing"
            # Do NOT flip AllSucceeded to False and do NOT add patients to PatientsFailed for missing-only
            pass

    # Transform to list + compute percentages / flags
    datatype_summary_rows = []
    for col, data in datatype_results_accumulator.items():
        total = data["TotalElements"] or 0
        unexpected = data["UnexpectedCount"] or 0
        passed = total - \
            unexpected if total else (1 if data["AllSucceeded"] else 0)
        percentage_pass = (round((passed / total) * 100, 2)
                           if total else (100.0 if data["AllSucceeded"] else 0.0))
        row = {
            "Variable": data["Variable"],
            "ExpectedType": data["ExpectedType"],
            "CurrentDatatype": data["CurrentDatatype"],
            "DatatypeCorrect": data["AllSucceeded"] and unexpected == 0,
            "TotalElements": total,
            "UnexpectedCount": unexpected,
            "PercentagePass": percentage_pass,
            "Sources": sorted(data["Sources"]),
            "PatientsFailed": sorted(data["PatientsFailed"]),
        }
        if "TypeMismatchWith" in data:
            row["TypeMismatchWith"] = sorted(data["TypeMismatchWith"])
        datatype_summary_rows.append(row)

    # --- Save Summary Results to JSON ---
    summary_results_path = os.path.join(
        app_path, "datatype_expectation_results.json")
    with open(summary_results_path, "w", encoding="utf-8") as fh:
        json.dump(datatype_summary_rows, fh, indent=4)
    print(f"Summary results saved to: {summary_results_path}")

    # ── Generate "in set" Expectation Summary ( expect_column_values_to_be_in_set ) ──
    print("\n--- Generating In-Set Expectation Summary --------------------------")
    inset_exp_name = "expect_column_values_to_be_in_set"

    # Accumulators (per variable)
    inset_results_acc = {}   # col -> dict

    # Helper to get observed values for a column from our cached dataframes

    def _observed_values_for(col: str) -> set:
        ent = col.split(".", 1)[0]
        vals = set()
        try:
            if ent in non_repeatable_entity_names and 'df_non_repeatable' in globals() and not df_non_repeatable.empty:
                if col in df_non_repeatable.columns:
                    vals.update(str(v).strip()
                                for v in df_non_repeatable[col].dropna().unique())
            elif ent in repeatable_entity_dataframes:
                df_ent = repeatable_entity_dataframes[ent]
                if col in df_ent.columns:
                    vals.update(str(v).strip()
                                for v in df_ent[col].dropna().unique())
            else:
                # fallback to long table if needed
                if not df_long_all.empty:
                    vals.update(
                        str(v).strip()
                        for v in df_long_all.loc[df_long_all["core_variable"] == col, "value"].dropna().unique()
                    )
        except Exception:
            pass
        # Normalise empties
        vals = {v for v in vals if v not in {"", "nan", "None", "NaT"}}
        return vals

    def _str_set(iterable) -> set:
        try:
            return {str(v).strip() for v in iterable if v is not None}
        except Exception:
            return set()

    def _patients_not_in_set(col: str, expected_set) -> set[str]:
        """Best-effort derive failing patient_ids when GE doesn't return row indices."""
        ent = col.split(".", 1)[0]
        exp = _str_set(expected_set)
        out = set()
        try:
            if ent in non_repeatable_entity_names and 'df_non_repeatable' in globals() and not df_non_repeatable.empty and col in df_non_repeatable.columns:
                ser = df_non_repeatable[col]
                vals = ser.astype(str).str.strip()
                mask = ser.notna() & vals.ne("") & (~vals.isin(
                    exp)) if exp else pd.Series(False, index=ser.index)
                if "patient_id" in df_non_repeatable.columns:
                    out |= set(
                        df_non_repeatable.loc[mask, "patient_id"].astype(str))
            elif ent in repeatable_entity_dataframes:
                df_ent = repeatable_entity_dataframes.get(ent)
                if df_ent is not None and not df_ent.empty and col in df_ent.columns and "patient_id" in df_ent.columns:
                    ser = df_ent[col]
                    vals = ser.astype(str).str.strip()
                    mask = ser.notna() & vals.ne("") & (~vals.isin(
                        exp)) if exp else pd.Series(False, index=ser.index)
                    out |= set(df_ent.loc[mask, "patient_id"].astype(str))
            elif not df_long_all.empty:
                tmp = df_long_all[df_long_all["core_variable"] == col].copy()
                if not tmp.empty and "patient_id" in tmp.columns and "value" in tmp.columns:
                    vals = tmp["value"].astype(str).str.strip()
                    mask = tmp["value"].notna() & vals.ne("") & (
                        ~vals.isin(exp)) if exp else pd.Series(False, index=tmp.index)
                    out |= set(tmp.loc[mask, "patient_id"].astype(str))
        except Exception:
            pass
        return out

    def _patients_not_in_set_per_record(col: str, expected_set) -> dict:
        """Return {record_id_or_None -> set(patient_id)} for rows failing in-set."""
        ent = col.split(".", 1)[0]
        exp = _str_set(expected_set)
        out = {}
        try:
            if ent in repeatable_entity_dataframes:
                df_ent = repeatable_entity_dataframes.get(ent)
                if df_ent is not None and not df_ent.empty and col in df_ent.columns:
                    if "patient_id" not in df_ent.columns:
                        return out
                    # Wide DF has one row per (patient_id, record_id)
                    ser = df_ent[col]
                    vals = ser.astype(str).str.strip()
                    mask = ser.notna() & vals.ne("") & (~vals.isin(
                        exp)) if exp else pd.Series(False, index=ser.index)
                    if "record_id" in df_ent.columns:
                        bad = df_ent.loc[mask, [
                            "patient_id", "record_id"]].copy()
                        bad["record_id"] = bad["record_id"].astype(str)
                        for rid, grp in bad.groupby("record_id", dropna=False):
                            rid_key = None if rid.lower() in {
                                "nan", "none"} else rid
                            out.setdefault(rid_key, set()).update(
                                grp["patient_id"].astype(str))
                    else:
                        # If record_id missing, collapse under None
                        out[None] = set(
                            df_ent.loc[mask, "patient_id"].astype(str))
            elif ent in non_repeatable_entity_names and 'df_non_repeatable' in globals() and not df_non_repeatable.empty and col in df_non_repeatable.columns:
                ser = df_non_repeatable[col]
                vals = ser.astype(str).str.strip()
                mask = ser.notna() & vals.ne("") & (~vals.isin(
                    exp)) if exp else pd.Series(False, index=ser.index)
                out[None] = set(df_non_repeatable.loc[mask,
                                "patient_id"].astype(str))
            elif not df_long_all.empty:
                tmp = df_long_all[df_long_all["core_variable"] == col].copy()
                if not tmp.empty:
                    vals = tmp["value"].astype(str).str.strip()
                    mask = tmp["value"].notna() & vals.ne("") & (
                        ~vals.isin(exp)) if exp else pd.Series(False, index=tmp.index)
                    if "record_id" in tmp.columns:
                        bad = tmp.loc[mask, ["patient_id", "record_id"]].copy()
                        bad["record_id"] = bad["record_id"].astype(str)
                        for rid, grp in bad.groupby("record_id", dropna=False):
                            rid_key = None if rid.lower() in {
                                "nan", "none"} else rid
                            out.setdefault(rid_key, set()).update(
                                grp["patient_id"].astype(str))
                    else:
                        out[None] = set(
                            tmp.loc[mask, "patient_id"].astype(str))

        except Exception:
            pass
        return out

    # First pass: sweep GE outputs and collect failures, expected sets and indices
    for _src, results_dict in all_checkpoint_results_with_source:
        if not results_dict:
            continue
        for _run_name, run_data in results_dict.get("run_results", {}).items():
            validation = run_data.get("validation_result", {})
            for outcome in validation.get("results", []):
                cfg = outcome.get("expectation_config", {})
                if cfg.get("expectation_type") != inset_exp_name:
                    continue

                kwargs_cfg = cfg.get("kwargs", {}) or {}
                col = kwargs_cfg.get("column")
                expected_set = kwargs_cfg.get("value_set", [])
                if not col:
                    continue

                ent = col.split(".", 1)[0]
                success = bool(outcome.get("success", False))
                res = outcome.get("result", {}) or {}

                # Index lists (GE may return full or partial)
                idx_list = (
                    res.get("unexpected_index_list")
                    or res.get("partial_unexpected_index_list")
                    or []
                )
                # Unexpected raw values
                unexpected_vals = res.get("unexpected_list") or res.get(
                    "partial_unexpected_list") or []
                unexpected_count = int(res.get("unexpected_count", 0) or 0)

                rec = inset_results_acc.setdefault(col, {
                    "Variable": col,
                    "Entity": ent,
                    "ExpectedSet": list(expected_set) if isinstance(expected_set, (list, tuple, set)) else [expected_set],
                    "AllSucceeded": True,              # will AND across outcomes
                    "UnexpectedValues": set(),         # union across runs
                    "PatientsAffected": set(),
                    "RecordsAffected": set(),          # (patient_id, record_id|None)
                    # Per-entity-instance breakdown for repeatables
                    "PerRecord": collections.defaultdict(lambda: {
                        "EntityInstance": None,       # record_id or None
                        "Patients": set(),
                        "UnexpectedValues": set(),
                    }),
                })

                rec["AllSucceeded"] = rec["AllSucceeded"] and success
                # Track unexpected values
                for v in unexpected_vals:
                    if v is not None:
                        rec["UnexpectedValues"].add(str(v))

                # Track who/where failed (from GE indices if available)
                for idx in idx_list:
                    if isinstance(idx, dict):
                        pid = str(idx.get("patient_id")) if idx.get(
                            "patient_id") is not None else None
                        rid = idx.get("record_id", None)
                        if pid:
                            rec["PatientsAffected"].add(pid)
                        rec["RecordsAffected"].add(
                            (pid, None if rid is None else str(rid)))
                        # Per-record breakdown (only meaningful for repeatables)
                        key_r = None if rid is None else str(rid)
                        pr = rec["PerRecord"][key_r]
                        pr["EntityInstance"] = key_r
                        if pid:
                            pr["Patients"].add(pid)

                # Fallback: if GE did not return indices but reported failures,
                # mark *all* patients that own the entity as missing
                if unexpected_count > 0 and not idx_list:
                    try:
                        pats = _patients_not_in_set(col, expected_set)
                        if pats:
                            rec["PatientsAffected"].update(pats)
                            # Per-record distribution
                            per_rec = _patients_not_in_set_per_record(
                                col, expected_set)
                            for rid_key, pset in per_rec.items():
                                rec["RecordsAffected"].update(
                                    {(pid, None if rid_key is None else str(rid_key))
                                     for pid in pset}
                                )
                                pr = rec["PerRecord"][rid_key]
                                pr["EntityInstance"] = None if rid_key is None else str(
                                    rid_key)
                                pr["Patients"].update(pset)
                    except Exception:
                        pass

    # Second pass: attach "ObservedValues" (global for each variable) and flatten sets
    inset_rows_global = []
    for col, data in inset_results_acc.items():
        observed = _observed_values_for(col)
        row = {
            "Variable": data["Variable"],
            "Entity": data["Entity"],
            "ExpectedSet": sorted(map(str, data["ExpectedSet"])),
            # what is actually present in the data
            "ObservedValues": sorted(observed),
            "AllSucceeded": data["AllSucceeded"] and len(data["UnexpectedValues"]) == 0,
            # values *outside* the set
            "UnexpectedValues": sorted(data["UnexpectedValues"]),
            # ⬇︎ include patient ids where QC failed (union across runs)
            "PatientsAffected": sorted(data["PatientsAffected"]),
            "RecordsAffected": sorted(
                {f"{pid or ''}:{rid or ''}" for (
                    pid, rid) in data["RecordsAffected"]}
            ),
        }
        inset_rows_global.append(row)

    # Third pass: build per-instance rows (repeatables carry record_id; non-repeatables will have EntityInstance=None)
    inset_rows_per_instance = []
    for col, data in inset_results_acc.items():
        ent = data["Entity"]
        # Choose a source df to enumerate instances/values
        df_src = None
        if ent in repeatable_entity_dataframes:
            df_src = repeatable_entity_dataframes[ent]
        else:
            # non-repeatables: synthesise a single "instance"
            df_src = df_non_repeatable if 'df_non_repeatable' in globals() else None

        # If we have no df (corner case), fall back to the indices we saw
        if df_src is None or df_src.empty or col not in df_src.columns:
            # Emit whatever we can from the GE results
            for rid_key, pr in data["PerRecord"].items():
                inset_rows_per_instance.append({
                    "Variable": col,
                    "Entity": ent,
                    "EntityInstance": rid_key,                           # None or record_id
                    "ExpectedSet": sorted(map(str, data["ExpectedSet"])),
                    "ObservedValues": [],                                # unknown
                    # we only create this row if we saw failures
                    "Failed": True,
                    "UnexpectedValues": sorted(pr["UnexpectedValues"]) if pr["UnexpectedValues"] else sorted(data["UnexpectedValues"]),
                    # ⬇︎ include patient ids where QC failed (per record)
                    "PatientsAffected": sorted(pr["Patients"]) if pr["Patients"] else sorted(data["PatientsAffected"]),
                })
            # For non-repeatables with no explicit PerRecord, still emit one row
            if ent in non_repeatable_entity_names and not data["PerRecord"]:
                inset_rows_per_instance.append({
                    "Variable": col,
                    "Entity": ent,
                    "EntityInstance": None,
                    "ExpectedSet": sorted(map(str, data["ExpectedSet"])),
                    "ObservedValues": sorted(_observed_values_for(col)),
                    "Failed": not data["AllSucceeded"] or bool(data["UnexpectedValues"]),
                    "UnexpectedValues": sorted(data["UnexpectedValues"]),
                    # ⬇︎ include patient ids where QC failed (global for non-repeatable)
                    "PatientsAffected": sorted(data["PatientsAffected"]),
                })
            continue

        # We *do* have a dataframe for this entity/column
        if ent in repeatable_entity_names:
            # One row per record_id instance
            # Ensure record_id exists (prepare_repeatable_entity_data created it)
            if "record_id" not in df_src.columns:
                # Create a synthetic instance if missing
                tmp = df_src[[col]].copy()
                tmp["record_id"] = None
                tmp["patient_id"] = df_src.get(
                    "patient_id", pd.Series(dtype=str))
            else:
                tmp = df_src[["patient_id", "record_id", col]].copy()

            for rid_val, sub in tmp.groupby("record_id", dropna=False):
                # observed codes *in that instance* (across all rows with that record_id)
                obs_vals = set(str(v).strip()
                               for v in sub[col].dropna().unique())
                obs_vals = {v for v in obs_vals if v not in {
                    "", "nan", "None", "NaT"}}

                # which patients failed for this instance?
                rid_key = None if pd.isna(rid_val) else str(rid_val)
                pr = data["PerRecord"].get(
                    rid_key, {"Patients": set(), "UnexpectedValues": set()})

                # Also derive failing patients for this record_id directly from DF (ensures presence even if GE omitted indices)
                expected_str = set(map(str, data["ExpectedSet"]))
                vals = sub[col].astype(str).str.strip()
                mask_bad = sub[col].notna() & vals.ne("") & (~vals.isin(
                    expected_str)) if expected_str else pd.Series(False, index=sub.index)
                derived_bad_pids = set(
                    sub.loc[mask_bad, "patient_id"].astype(str))
                patients_failed = set(pr["Patients"]) | derived_bad_pids

                # A “failure” if ANY observed value is outside the expected set
                outside = sorted({v for v in obs_vals if (
                    expected_str and v not in expected_str)})
                failed = bool(outside) or bool(patients_failed) or (
                    len(data["UnexpectedValues"]) > 0)

                inset_rows_per_instance.append({
                    "Variable": col,
                    "Entity": ent,
                    "EntityInstance": rid_key,
                    "ExpectedSet": sorted(map(str, data["ExpectedSet"])),
                    "ObservedValues": sorted(obs_vals),
                    "Failed": failed,
                    "UnexpectedValues": outside if outside else sorted(data["UnexpectedValues"]),
                    # ⬇︎ include patient ids where QC failed (per record)
                    "PatientsAffected": sorted(patients_failed) if patients_failed else sorted(data["PatientsAffected"]),
                })
        else:
            # Non-repeatable → single instance (EntityInstance=None)
            obs_vals = _observed_values_for(col)
            expected_set_str = set(map(str, data["ExpectedSet"]))
            outside = sorted({v for v in obs_vals if (
                expected_set_str and v not in expected_set_str)})
            # derive failing patients for non-repeatables
            pats_failed = _patients_not_in_set(col, expected_set_str)
            failed = bool(outside) or (
                len(data["UnexpectedValues"]) > 0) or bool(pats_failed)
            inset_rows_per_instance.append({
                "Variable": col,
                "Entity": ent,
                "EntityInstance": None,
                "ExpectedSet": sorted(map(str, data["ExpectedSet"])),
                "ObservedValues": sorted(obs_vals),
                "Failed": failed,
                "UnexpectedValues": outside if outside else sorted(data["UnexpectedValues"]),
                # ⬇︎ include patient ids where QC failed (global for non-repeatable)
                "PatientsAffected": sorted(pats_failed) if pats_failed else sorted(data["PatientsAffected"]),
            })

    # Persist
    inset_summary_path = os.path.join(
        app_path, "in_set_expectation_results.json")
    with open(inset_summary_path, "w", encoding="utf-8") as fh:
        json.dump(inset_rows_global, fh, indent=4)
    print(
        f"In-set expectation (per variable) summary saved to: {inset_summary_path}")

    inset_per_instance_path = os.path.join(
        app_path, "in_set_expectation_per_instance.json")
    with open(inset_per_instance_path, "w", encoding="utf-8") as fh:
        json.dump(inset_rows_per_instance, fh, indent=4)
    print(
        f"In-set expectation (per variable × entity instance) summary saved to: {inset_per_instance_path}")

    # ── Generate Importance-group Summary ( M / O / R ) ────────────────────────
    print("\n--- Generating Importance-group (M/O/R) summary ---------------")

    all_patients: set[str] = (
        set(df_long_all["patient_id"].astype(
            str))
        if not df_long_all.empty
        else set()
    )

    # 0️⃣ helper to normalise keys once

    def _norm(txt: str) -> str:
        return "".join(ch.lower() for ch in txt if ch.isalnum())

    # 1️⃣ load variable-importance map (same as before)
    importance_file = os.path.join(os.path.dirname(suites_file),
                                   "variable_importance.json")
    importance_map = {}
    try:
        with open(importance_file, encoding="utf-8") as fh:
            raw_map = json.load(fh)
        importance_map = {_norm(k.replace(".", "_"))
                                : v for k, v in raw_map.items()}
    except Exception as e:
        print(f"WARNING loading variable_importance.json: {e}")

    def importance_of(col: str) -> str:
        full = _norm(col.replace(".", "_"))
        if full in importance_map:
            return importance_map[full]
        short = col.split(".", 1)[-1]
        return importance_map.get(_norm(short), "Unknown")

    # 2️⃣ fixed denominators per group (non-optional vars only)
    group_vars = {"M": set(), "R": set(), "O": set(), "Unknown": set()}
    for v in non_optional_vars_set:
        group_vars[importance_of(v)].add(v)

    group_var_tot = {g: len(s) for g, s in group_vars.items()}

    full_dm_group_vars = {g: set() for g in group_vars}
    for v in all_core_variables_filtered:
        grp = importance_of(v)
        if grp in full_dm_group_vars:
            full_dm_group_vars[grp].add(v)

    # 3️⃣ which of those variables actually failed NOT-NULL
    group_var_fail = {g: set() for g in group_vars}
    for v in non_optional_vars_set:
        if v in var_missing:                         # from earlier NOT-NULL calc
            group_var_fail[importance_of(v)].add(v)

    full_dm_group_var_fail = {g: set() for g in group_vars}
    for v in all_core_variables_filtered:
        grp = importance_of(v)
        if v in var_missing:
            full_dm_group_var_fail[grp].add(v)

    # 4️⃣ patient-level failures per group (threshold-based on NOT-NULL)
    group_pat_counts = {g: collections.defaultdict(
        lambda: {"tot": 0, "fail": 0}) for g in group_vars}
    for chk in all_checkpoint_result_dicts:
        if not chk:
            continue
        for _, run in chk.get("run_results", {}).items():
            for out in run.get("validation_result", {}).get("results", []):
                cfg = out.get("expectation_config", {})
                if cfg.get("expectation_type") != "expect_column_values_to_not_be_null":
                    continue
                col = (cfg.get("kwargs", {}) or {}).get("column")
                if not col:
                    continue
                src = var2src_all.get(col, default_source or "UNKNOWN_SOURCE")
                totals = _per_patient_totals_for_col(col)
                # add totals
                for pid, t in totals.items():
                    group_pat_counts[importance_of(
                        col)][str(pid)]["tot"] += int(t)
                # add failures
                res = out.get("result", {}) or {}
                idx_list = res.get("unexpected_index_list") or res.get(
                    "partial_unexpected_index_list") or []
                if idx_list:
                    for idx in idx_list:
                        if isinstance(idx, dict) and "patient_id" in idx and idx["patient_id"] is not None:
                            group_pat_counts[importance_of(col)][str(
                                idx["patient_id"])]["fail"] += 1
                elif int(res.get("unexpected_count", 0) or 0):
                    for pid in totals.keys():
                        group_pat_counts[importance_of(
                            col)][str(pid)]["fail"] += 1

    # Build patient fail sets from threshold
    group_pat_fail = {g: set() for g in group_vars}
    for grp, pats in group_pat_counts.items():
        for pid, c in pats.items():
            if c["tot"] == 0:
                continue
            passed_ratio = (c["tot"] - c["fail"]) / c["tot"]
            if passed_ratio < PATIENT_PASS_THRESHOLD:
                group_pat_fail[grp].add(pid)

    # NEW: Full-DM patient-level fail sets use the same thresholded sets
    full_dm_group_pat_fail = group_pat_fail

    # NEW: Aggregate total and failed QC counts per importance group from NOT-NULL tallies
    group_var_total_qcs = {g: 0 for g in group_vars}
    group_var_total_failed_qcs = {g: 0 for g in group_vars}
    for v, (tot, fail) in var_counts.items():
        grp = importance_of(v)
        group_var_total_qcs[grp] += int(tot or 0)
        group_var_total_failed_qcs[grp] += int(fail or 0)

    # 5️⃣ build two-row summary per group
    rows_imp = []
    grp_map = {"M": "High",
               "R": "Medium", "O": "Low", "Unknown": "Unknown"}
    for grp in ["M", "O", "R", "Unknown"]:
        v_tot = group_var_tot[grp]
        v_fail = len(group_var_fail[grp])
        v_pass = v_tot - v_fail

        p_tot = len(all_patients)
        p_fail = len(group_pat_fail[grp])
        p_pass = p_tot - p_fail

        # NEW: compute full-DM fail/pass counts used below
        full_dm_v_fail = len(full_dm_group_var_fail[grp])
        full_dm_v_pass = len(full_dm_group_vars[grp]) - full_dm_v_fail

        total_qcs_grp = group_var_total_qcs[grp]
        total_failed_qcs_grp = group_var_total_failed_qcs[grp]
        total_passed_qcs_grp = total_qcs_grp - total_failed_qcs_grp
        if total_qcs_grp == 0:
            total_qcs_grp = 1  # avoid division by zero

        # ── Variable row
        rows_imp.append({
            "Group":      grp_map[grp],
            "Unit":       "Variable",

            # raw counts
            "total_variables":  v_tot,
            "failed_variables": v_fail,
            "passed_variables": v_pass,
            "total_patients":   p_tot,
            "failed_patients":  p_fail,
            "passed_patients":  p_pass,

            # full
            "full_dm_total_variables":               len(full_dm_group_vars[grp]),
            "full_dm_failed_variables":              full_dm_v_fail,
            "full_dm_passed_variables":              full_dm_v_pass,
            "full_dm_complete_variables_percentage": round(full_dm_v_pass / len(full_dm_group_vars[grp]) * 100, 2)
            if len(full_dm_group_vars[grp]) > 0 else "not computed",
            "full_dm_missing_variables_percentage":  round(full_dm_v_fail / len(full_dm_group_vars[grp]) * 100, 2)
            if len(full_dm_group_vars[grp]) > 0 else "not computed",

            # NEW: threshold-based patient counts
            "total_patients":        p_tot,
            "failed_patients":       p_fail,
            "passed_patients":       p_pass,
            "complete_patients_percentage": round((p_pass / p_tot) * 100, 2) if p_tot else "not computed",
            "missing_patients_percentage": round((p_fail / p_tot) * 100, 2) if p_tot else "not computed",

            "total_quality_checks": total_qcs_grp,
            "failed_quality_checks": total_failed_qcs_grp,
            "passed_quality_checks": total_passed_qcs_grp,
            "quality_checks_percentage_passed": round(total_passed_qcs_grp / (total_qcs_grp) * 100, 2),
            "quality_checks_percentage_fail": round(total_failed_qcs_grp / (total_qcs_grp) * 100, 2)
        })

    # (optional) sort by group name
    rows_imp = sorted(rows_imp, key=lambda r: r["Group"])

    # 6️⃣ write JSON
    imp_json = os.path.join(app_path,
                            "importance_group_summary_results.json")
    with open(imp_json, "w", encoding="utf-8") as fh:
        json.dump(rows_imp, fh, indent=4)

    print(f"Importance-group summary saved to: {imp_json}")

    # --- Generate QC (Expectation Name) Summary (Aggregated) -------------------
    print("\n--- Generating Aggregated QC (Expectation Name) Summary ---")

    qc_summary_data: dict[str, dict] = {}
    qc_var_tot = collections.defaultdict(set)
    qc_var_fail = collections.defaultdict(set)
    qc_pat_counts = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {"tot": 0, "fail": 0}))
    qc_pat_tot = collections.defaultdict(set)
    qc_pat_fail = collections.defaultdict(set)

    # ── POPULATE qc_summary_data and helper sets (now with per-patient totals/fails) ──
    for chk in all_checkpoint_result_dicts:
        if not chk:
            continue
        for run in chk.get("run_results", {}).values():
            validation = run.get("validation_result", {}) or {}
            for outcome in validation.get("results", []) or []:
                cfg = outcome.get("expectation_config", {}) or {}
                ge_name = cfg.get("expectation_type")
                if not ge_name:
                    continue

                res = outcome.get("result", {}) or {}
                elem_cnt = int(res.get("element_count", 0) or 0)
                unexp_cnt = int(res.get("unexpected_count", 0) or 0)

                rec = qc_summary_data.setdefault(
                    ge_name,
                    {
                        "ge_name": ge_name,
                        "total_checks": 0,
                        "failed_checks": 0,
                        "passed_checks": 0,
                        "percentage_pass": 0.0,
                        "variable_missing_percent": None,
                        "patient_missing_percent": None,
                    },
                )
                rec["total_checks"] += elem_cnt
                rec["failed_checks"] += unexp_cnt
                rec["passed_checks"] += max(0, elem_cnt - unexp_cnt)
                rec["percentage_pass"] = (
                    rec["passed_checks"] / rec["total_checks"] * 100) if rec["total_checks"] else 0.0

                col = (cfg.get("kwargs", {}) or {}).get("column")
                if col:
                    qc_var_tot[ge_name].add(col)
                    if unexp_cnt:
                        qc_var_fail[ge_name].add(col)

                    # NEW: attribute totals and failures per patient for this expectation
                    totals = _per_patient_totals_for_col(col)
                    for pid, t in totals.items():
                        qc_pat_counts[ge_name][str(pid)]["tot"] += int(t)

                    idx_list = res.get("unexpected_index_list") or res.get(
                        "partial_unexpected_index_list") or []
                    if idx_list:
                        for idx in idx_list:
                            if isinstance(idx, dict) and "patient_id" in idx and idx["patient_id"] is not None:
                                pid = str(idx["patient_id"])
                                qc_pat_counts[ge_name][pid]["fail"] += 1
                            else:
                                print(f"  ⚠︎  Unexpected index format: {idx}")
                    elif unexp_cnt:
                        for pid in totals.keys():
                            qc_pat_counts[ge_name][str(pid)]["fail"] += 1
                            qc_pat_fail[ge_name].add(str(pid))

                # patients covered by this run (legacy)
                qc_pat_tot[ge_name].update(all_patients)

    # --- Generate QC summary rows for JSON output -------------------------------
    datamodel_vars_set = all_core_variables_filtered
    num_datamodel_vars = len(datamodel_vars_set)

    # NEW: variables that were extracted by NLP (seen with original_source == NLP_TAG)
    nlp_vars_all = set()
    try:
        if not df_long_all.empty and {"original_source", "core_variable"}.issubset(df_long_all.columns):
            nlp_vars_all = set(
                df_long_all.loc[df_long_all["original_source"]
                                == NLP_TAG, "core_variable"]
                .astype(str)
                .unique()
            )
    except Exception:
        nlp_vars_all = set()

    # NEW: identify variables that are truly "Missing" for datatype expectation, so we can exclude them
    missing_type_vars = set()
    try:
        missing_type_vars = {
            col for col, data in (datatype_results_accumulator or {}).items()
            if data.get("CurrentDatatype") == "Missing"
        }
    except Exception:
        missing_type_vars = set()

    rows_for_json = []
    for ge_name in sorted(qc_summary_data):
        # Default computation for most QCs
        v_tot = len(qc_var_tot[ge_name])
        v_fail = len(qc_var_fail[ge_name])
        v_pass = v_tot - v_fail

        # SPECIAL CASE: datatype QC — exclude variables that are fully Missing
        if ge_name == "expect_column_values_to_be_of_type":
            considered_tot_set = qc_var_tot[ge_name] - missing_type_vars
            considered_fail_set = qc_var_fail[ge_name] - missing_type_vars
            v_tot = len(considered_tot_set)
            v_fail = len(considered_fail_set)
            v_pass = v_tot - v_fail

        # NEW: threshold-based patient pass/fail for this expectation
        pat_counts = qc_pat_counts.get(ge_name, {})
        p_tot = len(pat_counts)
        p_pass = sum(
            1
            for pid, c in pat_counts.items()
            if c["tot"] > 0 and ((c["tot"] - c["fail"]) / c["tot"]) >= PATIENT_PASS_THRESHOLD
        )
        p_fail = max(0, p_tot - p_pass)

        # Full-DM totals; for datatype QC, exclude Missing variables from denominator
        if ge_name == "expect_column_values_to_be_of_type":
            filtered_dm_set = datamodel_vars_set - missing_type_vars
            num_dm_considered = len(filtered_dm_set)
            fail_vars_full = {
                v for v in filtered_dm_set
                if ((v in qc_var_fail[ge_name]) or (v not in qc_var_tot[ge_name]))
            }
            v_fail_full = len(fail_vars_full)
            v_pass_full = num_dm_considered - v_fail_full
            denom_full_dm = num_dm_considered
        else:
            fail_vars_full = {
                v for v in datamodel_vars_set
                if ((v in qc_var_fail[ge_name]) or (v not in qc_var_tot[ge_name]))
            }
            v_fail_full = len(fail_vars_full)
            v_pass_full = num_datamodel_vars - v_fail_full
            denom_full_dm = num_datamodel_vars

        # NEW: NLP-only group (denominator = variables seen from NLP source)
        if ge_name == "expect_column_values_to_be_of_type":
            nlp_dm_vars_set_considered = (
                datamodel_vars_set & nlp_vars_all) - missing_type_vars
            nlp_fail_vars_full = {
                v for v in nlp_dm_vars_set_considered
                if ((v in qc_var_fail[ge_name]) or (v not in qc_var_tot[ge_name]))
            }
            nlp_v_tot = len(nlp_dm_vars_set_considered)
            nlp_v_fail = len(nlp_fail_vars_full)
            nlp_v_pass = nlp_v_tot - nlp_v_fail
        else:
            nlp_dm_vars_set = datamodel_vars_set & nlp_vars_all
            nlp_fail_vars_full = {
                v for v in nlp_dm_vars_set
                if ((v in qc_var_fail[ge_name]) or (v not in qc_var_tot[ge_name]))
            }
            nlp_v_tot = len(nlp_dm_vars_set)
            nlp_v_fail = len(nlp_fail_vars_full)
            nlp_v_pass = nlp_v_tot - nlp_v_fail

        rows_for_json.append({
            "QC": QCNAME2EASYLABEL.get(ge_name, ge_name),
            "full_name": ge_name,
            "total_variables": v_tot,
            "failed_variables": v_fail,
            "passed_variables": v_pass,
            "complete_variables_percentage": round((v_pass / v_tot) * 100, 2) if v_tot else "not computed",
            "missing_variables_percentage": round((v_fail / v_tot) * 100, 2) if v_tot else "not computed",
            "total_patients": p_tot,
            "failed_patients": p_fail,
            "passed_patients": p_pass,
            "complete_patients_percentage": round((p_pass / p_tot) * 100, 2) if p_tot else "not computed",
            "missing_patients_percentage": round((p_fail / p_tot) * 100, 2) if p_tot else "not computed",
            "total_quality_checks": qc_summary_data[ge_name]["total_checks"],
            "failed_quality_checks": qc_summary_data[ge_name]["failed_checks"],
            "passed_quality_checks": qc_summary_data[ge_name]["passed_checks"],
            "quality_checks_percentage_pass": round(
                (qc_summary_data[ge_name]["passed_checks"] /
                 qc_summary_data[ge_name]["total_checks"]) * 100, 2
            ) if qc_summary_data[ge_name]["total_checks"] else "not computed",
            "quality_checks_percentage_fail": round(
                (qc_summary_data[ge_name]["failed_checks"] /
                 qc_summary_data[ge_name]["total_checks"]) * 100, 2
            ) if qc_summary_data[ge_name]["total_checks"] else "not computed",

            # NEW: Full‑DM fields used by the UI
            "full_dm_total_variables": denom_full_dm,
            "full_dm_failed_variables": v_fail_full,
            "full_dm_passed_variables": v_pass_full,
            "full_dm_complete_variables_percentage": round((v_pass_full / denom_full_dm) * 100, 2) if denom_full_dm else "not computed",
            "full_dm_missing_variables_percentage": round((v_fail_full / denom_full_dm) * 100, 2) if denom_full_dm else "not computed",
        })

    with open(os.path.join(app_path,
                           "qc_summary_results.json"), "w", encoding="utf-8") as fh:
        json.dump(rows_for_json, fh, indent=4)

    
    # --- Phase report: nearest Dx / Progression / Recurrence in time -----------

    # NEW: Safety initializations for removed summaries
    if 'patient_summary_data_aggregated' not in locals():
        try:
            pat_ids = sorted(set(df_long_all["patient_id"].astype(
                str))) if not df_long_all.empty else []
        except Exception:
            pat_ids = []
        patient_summary_data_aggregated = {
            pid: {"PatientID": pid} for pid in pat_ids}

    # ────────────────────────────────────────────────────────────────
    #  Patient  ×  Importance-group summary (High / Medium / Low)
    # ────────────────────────────────────────────────────────────────
    per_patient_imp = {}        # (pid, grp) → counters

    for var, stats in variable_qc.items():
        grp = importance_of(var)       # High / Medium / Low / Unknown
        for pid, pstats in patient_summary_data_aggregated.items():
            # every variable is ‘tested’ for every patient once
            key = (pid, grp)
            rec = per_patient_imp.setdefault(key,
                                            {"PatientID": pid, "Group": grp,
                                            "Passed": 0, "Failed": 0, "Total": 0})
            rec["Total"] += stats["Total"]
            rec["Failed"] += stats["Failed"]

    for rec in per_patient_imp.values():
        rec["Passed"] = rec["Total"] - rec["Failed"]
        rec["PassPercent"] = (
            round(rec["Passed"]/rec["Total"]*100, 2) if rec["Total"] else 100.0)

    out = list(per_patient_imp.values())
    with open(os.path.join(app_path,
            "patient_importance_summary_results.json"), "w") as fh:
        json.dump(out, fh, indent=4)
    print("Patient-importance summary written.")

    # NEW: Ensure df_with_phase exists (phase defaults to 'Diagnosis') before summaries that need it
    if 'df_with_phase' not in locals():
        df_with_phase = df_long_all.copy()
        if not df_with_phase.empty:
            df_with_phase["phase"] = "Diagnosis"

    # ────────────────────────────────────────────────────────────────
    #  Patient  ×  Phase missingness summary
    # ────────────────────────────────────────────────────────────────
    per_patient_phase = {}      # (pid, phase) → counters

    for _, r in df_with_phase.iterrows():
        if r.core_variable not in notnull_vars:
            continue
        key = (r.patient_id, r.phase)
        rec = per_patient_phase.setdefault(key,
                                        {"PatientID": r.patient_id, "Phase": r.phase,
                                            "Present": 0, "Missing": 0, "Total": 0})
        rec["Total"] += 1
        if pd.isna(r.value) or str(r.value).strip() == "":
            rec["Missing"] += 1
        else:
            rec["Present"] += 1

    for rec in per_patient_phase.values():
        rec["MissingPercent"] = (
            round(rec["Missing"]/rec["Total"]*100, 2) if rec["Total"] else 0.0)

    out = list(per_patient_phase.values())
    with open(os.path.join(app_path,
            "patient_phase_summary_results.json"), "w") as fh:
        json.dump(out, fh, indent=4)
    print("Patient-phase summary written.")


    # ─────────────────────────────────────────────────────────────────────────────
    #  Variable × Patient missing‑matrix report
    #      NEW: rely on GE NOT‑NULL results instead of ad‑hoc Pandas tallies
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n--- Building Variable × Patient missingness matrix ---------------")

    # Build matrix only for variables that are in the data and/or have a NOT-NULL QC
    vars_in_data = set()
    if not df_long_all.empty and "core_variable" in df_long_all.columns:
        vars_in_data = set(df_long_all["core_variable"].astype(str).unique())
    candidate_vars = ((all_core_variables_filtered & vars_in_data) | notnull_vars)

    # --- NEW: custom ordering (entity order, then variable order from config) ---
    _BIG = 10_000_000
    entity_rank = {e: i for i, e in enumerate(CROSSTAB_ENTITY_REPORT_ORDER)}
    var_rank = {}
    # pick variable order from rep_entities.json (non_repeteables + repeteables)
    try:
        # non-repeatables
        for ent, short_list in (repeated_entities_data.get("non_repeteables") or {}).items():
            for j, short in enumerate(short_list):
                var_rank[f"{ent}.{short}"] = j
        # repeatables
        for ent, short_list in (repeated_entities_data.get("repeteables") or {}).items():
            for j, short in enumerate(short_list):
                var_rank[f"{ent}.{short}"] = j
    except Exception:
        pass


    def _var_sort_key(v: str):
        ent = v.split(".", 1)[0]
        return (
            entity_rank.get(ent, _BIG),      # entity block order
            var_rank.get(v, _BIG),           # in-entity field order from config
            v                                 # stable fallback
        )


    variables = sorted(candidate_vars, key=_var_sort_key)

    patient_ids = sorted(df_long_all["patient_id"].astype(str).unique())

    if not variables or not patient_ids:
        print("  Nothing to report – no variables or patients detected.")
    else:
        # ---------- 0⃣  look‑ups already available elsewhere -------------------
        # (pid, entity) → how many instances of that entity does that patient have?
        ent_total_inst = (
            df_long_all
            .assign(entity=lambda d: d["core_variable"].str.split(".", n=1).str[0])
            .groupby(["patient_id", "entity"])["record_id"]
            .nunique(dropna=False)
            .to_dict()
        )

        # Helper: normalize importance to user-facing label
        def _importance_label_for(var: str) -> str:
            iv = importance_of(var)
            return {"M": "High", "R": "Medium", "O": "Low"}.get(
                iv, iv if iv in ("High", "Medium", "Low") else "Unknown"
            )

        # NEW: compute first encountered phase per entity using df_with_phase (phase_df-backed)
        first_phase_per_entity = {}
        try:
            if 'df_with_phase' in locals() and not df_with_phase.empty:
                tmp = (
                    df_with_phase
                    .assign(entity=lambda d: d["core_variable"].str.split(".", n=1).str[0])
                    .drop_duplicates(subset=["patient_id", "record_id", "entity"])
                    [["patient_id", "record_id", "entity", "phase"]]
                )
                # attach record date if available (may be NaT)
                if 'record_dates' in locals():
                    tmp = tmp.merge(
                        record_dates[["patient_id", "record_id", "date"]],
                        on=["patient_id", "record_id"], how="left"
                    )
                else:
                    tmp["date"] = pd.NaT

                # pick, per entity: earliest dated record; if no dates → earliest phase by fixed order
                ORDER = {"Diagnosis": 0, "Progression": 1, "Recurrence": 2}

                def _pick_first(grp: pd.DataFrame) -> str:
                    dated = grp.dropna(subset=["date"])
                    if not dated.empty:
                        return dated.sort_values("date").iloc[0]["phase"]
                    ranked = grp.assign(_ord=grp["phase"].map(ORDER).fillna(999))
                    return ranked.sort_values("_ord").iloc[0]["phase"] if not ranked.empty else ""

                firsts = tmp.groupby("entity", as_index=False).apply(
                    lambda g: pd.Series({"phase": _pick_first(g)})
                )
                first_phase_per_entity = dict(
                    zip(firsts["entity"].astype(str), firsts["phase"].astype(str))
                )
        except Exception as e:
            print(f"  ⚠︎  Could not compute first phase per entity: {e}")
            first_phase_per_entity = {}

        # ---------- 1⃣  derive *missing* instances straight from GE -----------

        # (var, pid) → how many entity instances failed NOT‑NULL
        var_missing_inst = collections.defaultdict(int)

        for chk in all_checkpoint_result_dicts:
            if not chk:
                continue
            for run in chk.get("run_results", {}).values():
                for out in run.get("validation_result", {}).get("results", []):
                    cfg = out.get("expectation_config", {})
                    if cfg.get("expectation_type") != "expect_column_values_to_not_be_null":
                        continue
                    var = cfg.get("kwargs", {}).get("column")
                    if not var:
                        continue

                    idx_list = (
                        out.get("result", {}).get("unexpected_index_list")
                        or out.get("result", {}).get("partial_unexpected_index_list")
                        or []
                    )

                    # each failing row carries patient_id (and record_id for repeatables)
                    for idx in idx_list:
                        if isinstance(idx, dict) and "patient_id" in idx:
                            pid = str(idx["patient_id"])
                            var_missing_inst[(var, pid)] += 1

                    # safeguard – if GE returned no indexes but reported failures,
                    # mark *all* patients that own the entity as missing
                    if out.get("result", {}).get("unexpected_count", 0) and not idx_list:
                        entity = var.split(".", 1)[0]
                        for pid in patient_ids:
                            if ent_total_inst.get((pid, entity), 0):
                                var_missing_inst[(var, pid)
                                                ] = ent_total_inst[(pid, entity)]

        # ---------- 2⃣  build the matrix row‑by‑row ----------------------------
        rows = []
        for var in variables:
            entity = var.split(".", 1)[0]
            importance = _importance_label_for(var)
            first_phase = first_phase_per_entity.get(entity, "")

            row, miss_cnt = {"Variable": var,
                            "Importance": importance, "First phase": first_phase}, 0

            for pid in patient_ids:
                total_inst = ent_total_inst.get(
                    (pid, entity), 0)                # all entity rows
                missing_inst = var_missing_inst.get(
                    (var, pid), 0)                 # GE failures
                filled_inst = max(0, total_inst - missing_inst)

                # decide cell label exactly like before, but using GE data
                if total_inst == 0 and entity_min_card.get(entity, 1) == 0:
                    cell = "Not present"
                elif filled_inst == 0:
                    cell = "Missing"
                    miss_cnt += 1
                elif (
                    total_inst > 1 and entity in repeatable_entity_names
                    and filled_inst < total_inst
                ):
                    cell = "Sometimes"
                else:
                    cell = ""

                row[pid] = cell

            row["MissingPercent"] = round(miss_cnt / len(patient_ids) * 100, 2)
            rows.append(row)

        df_matrix = pd.DataFrame(
            rows, columns=["Variable", "Importance", "First phase",
                        *patient_ids, "MissingPercent"]
        )

        # ---------- 3  per-patient % row ------------------------------------
        pat_row = {"Variable": "MissingPercentPerPatient",
                "Importance": "", "First phase": ""}

        for pid in patient_ids:
            pct = sum(df_matrix[pid] == "Missing") / len(variables) * 100
            pct = round(pct, 2)
            pat_row[pid] = pct

        df_matrix = pd.concat([df_matrix, pd.DataFrame([pat_row])],
                            ignore_index=True)

        # ---------- 4  append Total [Importance] at [Phase] rows -------------
        combined_rows = []
        if 'df_with_phase' in locals() and not df_with_phase.empty:
            for importance in ["High", "Medium", "Low"]:
                for phase in ["Diagnosis", "Progression", "Recurrence"]:
                    # Find which patients have data in this phase
                    patients_with_phase = set(
                        str(pid) for pid in df_with_phase[df_with_phase.phase == phase]["patient_id"].unique()
                    )

                    # FIX: Select variables of this importance level using normalized label
                    phase_variables = [v for v in variables
                                    if _importance_label_for(v) == importance]

                    # Build summary row using exact same logic as main matrix
                    summary = {
                        "Variable": f"Total {importance} at {phase.lower()}",
                        "Importance": importance,
                        "First phase": ""
                    }

                    # Always compute; default to 0.0 when no data
                    for pid in patient_ids:
                        if pid in patients_with_phase:
                            missing_count = 0
                            total_count = 0

                            for var in phase_variables:
                                # We rely on the already computed cell values in df_matrix
                                cell_status_series = df_matrix.loc[
                                    df_matrix["Variable"] == var, pid
                                ]
                                cell_status = cell_status_series.iloc[0] if len(
                                    cell_status_series) > 0 else ""

                                # Count "Missing" and "Sometimes" as missing, but NOT blank cells
                                if cell_status in ["Missing", "Sometimes"]:
                                    missing_count += 1
                                total_count += 1

                            pct = round(missing_count / total_count *
                                        100, 2) if total_count > 0 else 0.0
                        else:
                            pct = 0.0

                        summary[pid] = str(pct)

                    # Calculate overall average across patients (even if many are 0.0)
                    summary["MissingPercent"] = str(round(
                        sum(float(summary[pid])
                            for pid in patient_ids) / len(patient_ids), 2
                    ))
                    combined_rows.append(summary)
        else:
            print(
                "  ⚠︎  df_with_phase not available – skipping combined importance-phase rows.")

        if combined_rows:
            df_matrix = pd.concat([df_matrix, pd.DataFrame(combined_rows)],
                                ignore_index=True)

        # Ensure column order with First phase before MissingPercent
        if {"Variable", "Importance", "MissingPercent"}.issubset(df_matrix.columns):
            other_cols = [c for c in df_matrix.columns
                        if c not in ("Variable", "Importance", "First phase", "MissingPercent")]
            df_matrix = df_matrix[["Variable", "Importance",
                                "First phase", "MissingPercent", *other_cols]]

        # NEW: reorder rows so summary rows are at the top
        summary_order = [
            "MissingPercentPerPatient",
            "Total High at diagnosis",
            "Total High at progression",
            "Total High at recurrence",
            "Total Medium at diagnosis",
            "Total Medium at progression",
            "Total Medium at recurrence",
            "Total Low at diagnosis",
            "Total Low at progression",
            "Total Low at recurrence",
        ]
        order_map = {name: i for i, name in enumerate(summary_order)}
        df_matrix["__orig_idx"] = range(len(df_matrix))
        df_matrix["__order"] = df_matrix["Variable"].map(
            order_map).fillna(len(summary_order)).astype(int)
        df_matrix = (
            df_matrix
            .sort_values(["__order", "__orig_idx"])
            .drop(columns=["__order", "__orig_idx"])
            .reset_index(drop=True)
        )

        # ---------- 5 persist -------------------------------------------------
        out_csv = os.path.join(
            app_path, "variable_patient_missing_matrix.csv")
        out_xlsx = os.path.join(
            app_path, "variable_patient_missing_matrix.xlsx")
        df_matrix.to_csv(out_csv, index=False)
        df_matrix.to_excel(out_xlsx, index=False)
        print(f"  Matrix saved to:\n    {out_csv}\n    {out_xlsx}")

    # now fill metadata

    center = os.getenv("CENTER_NAME", "INT")

    datasource_name = os.getenv(
        "METADATA_DATASOURCE_NAME", "Default")
    datasource_info = os.getenv(
        "METADATA_DATASOURCE_INFORMATION", "No description provided.")
    # Paths
    here = Path(__file__).parent
    metadata_path = os.getenv(
        "EMPTY_METADATA_PATH",
        str(here / "empty_metadata.json"),
    )

    # Load metadata skeleton
    with open(metadata_path, encoding="utf-8") as fh:
        metadata = json.load(fh)

    # show first 10 rows of df_long_all
    print("\nFirst 10 rows of the long-format data:")
    print(df_long_all.head(10).to_string(index=False))

    filled = fill_for_center(
        metadata_items=metadata,
        df_long=df_long_all,
        center_code=center,
        datasource_name=datasource_name,
        datasource_info=datasource_info,
    )

    with open("/data/results/filled_metadata.json", "w", encoding="utf-8") as fh:
        json.dump(filled, fh, ensure_ascii=False, indent=2)
    print("Saved: /data/results/filled_metadata.json")

    crosstab_external_user(df_matrix, os.path.join(
        app_path, "/data/results/user_crosstab_external.csv"))
    return data, []
