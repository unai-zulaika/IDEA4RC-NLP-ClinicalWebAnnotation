import pandas as pd
import json
import os
from pathlib import Path


def _parse_date_flexible(date_str):
    """
    Parse date string flexibly, handling multiple formats:
    - DD/MM/YYYY
    - YYYY-MM-DD
    - YYYY-MM-DD HH:MM:SS
    - etc.
    """
    if pd.isna(date_str) or date_str == '':
        return pd.NaT

    date_str = str(date_str).strip()

    # Try DD/MM/YYYY format first (European format)
    try:
        return pd.to_datetime(date_str, format='%d/%m/%Y')
    except (ValueError, TypeError):
        pass

    # Try ISO format YYYY-MM-DD
    try:
        return pd.to_datetime(date_str, format='%Y-%m-%d')
    except (ValueError, TypeError):
        pass

    # Try with time component
    try:
        return pd.to_datetime(date_str, format='%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        pass

    # Try pandas auto-detection as last resort
    try:
        return pd.to_datetime(date_str, errors='coerce', dayfirst=True)
    except Exception:
        return pd.NaT


def link_rows(data: pd.DataFrame) -> pd.DataFrame:
    """
    Links rows in the DataFrame by populating the 'linked_to' column,
    based on entity_mappings.json and date logic.

    Args:
        data (pd.DataFrame): Must contain 'record_id', 'patient_id',
                             'core_variable', 'date_ref' (and optionally 'date_ref.1'), 'value'.

    Returns:
        pd.DataFrame: Copy of data with 'linked_to' filled where possible.
    """
    # 1) Load mappings
    # --- locate the JSON file relative to this script file ---
    script_dir   = Path(__file__).resolve().parent
    mapping_path = script_dir / "entity_mappings.json"
    if not mapping_path.exists():
        raise FileNotFoundError(f"Could not find mappings at {mapping_path}")
    with open(mapping_path, "r") as f:
        entity_mappings = json.load(f)

    # 2) Check required columns
    for col in ("record_id", "patient_id", "core_variable", "value"):
        if col not in data.columns:
            raise ValueError(f"Data must contain '{col}' column.")

    # 3) Work on a copy of the original data
    df_result = data.copy()

    # Ensure linked_to column exists
    if 'linked_to' not in df_result.columns:
        df_result['linked_to'] = ''

    # 4) Create working copy, drop rows with no 'value' for linking logic
    df = df_result.dropna(subset=["value"]).copy()

    # 5) Extract entity name and parse dates flexibly
    df['entity'] = df['core_variable'].str.split('.').str[0]
    df['date_ref_parsed'] = df['date_ref'].apply(_parse_date_flexible)

    # 6) Loop each row and find links
    for i, row in df.iterrows():
        entity = row['entity']
        if entity not in entity_mappings:
            # print(f"Entity '{entity}' not found in mappings. Skipping row {i}.")
            continue

        if pd.isna(row['date_ref_parsed']):
            print(f"Invalid date_ref for row {i} (entity={entity}). Skipping.")
            continue

        # identify target entities
        targets = entity_mappings[entity]
        if not targets:
            # print(f"No target entities found for '{entity}'. Skipping row {i}.")
            continue

        # look for the target entities with the latest date_ref and same patient_id
        mask = (
            (df['patient_id'].astype(str) == str(row['patient_id'])) &
            (df['entity'].isin(targets)) &
            (df['date_ref_parsed'].notna()) &
            (df['date_ref_parsed'] <= row['date_ref_parsed'])
        )
        cands = df.loc[mask]
        if cands.empty:
            # print(f"No candidates found for row {i}. Skipping.")
            continue

        # pick the record with the max date_ref
        latest_idx = cands['date_ref_parsed'].idxmax()
        linked_record_id = df.at[latest_idx, 'record_id']

        # Update both the working df and the result df
        df.at[i, 'linked_to'] = linked_record_id
        df_result.at[i, 'linked_to'] = linked_record_id
        # print(f"Row {i} ({entity}) linked to record {linked_record_id}.")

    # 7) Return the complete DataFrame with the 'linked_to' column updated
    return df_result

if __name__ == "__main__":
    # quick smoke‐test
    sample_data = pd.DataFrame({
        "record_id": [1,2,3,4],
        "patient_id": ["A","A","B","B"],
        "core_variable": ["X","Y","X","Z"],
        "date_ref": ["2025-01-01","2025-01-02","2025-01-01","2025-01-03"],
        "value":       [10,      20,      30,       40]
    })
    # linked = link_rows(sample_data, linking_criteria={"by_date": True})

    # load dataframe from file
    data = pd.read_excel(
        "/home/zulaika/IDEA4RC-NLP-Ingestion/test_data/MSCI_DEMO_NT_V2_CLEAN.xlsx",
    )
    # 9) Run the function
    linked = link_rows(data)
    print("###" * 10)
    print(linked)
    # print linked to column
    print(linked["linked_to"])
    # save the file to downloads
    linked.to_excel(
        "/home/zulaika/IDEA4RC-NLP-Ingestion/test_data/MSCI_DEMO_NT_V2_CLEAN_LINKED_TEST.xlsx",
        index=False,
    )
