import os
import json
import argparse
from pathlib import Path
import pandas as pd
import csv

# --------------------- IO helpers ---------------------


def read_table(path: str, **pd_kwargs) -> pd.DataFrame:
    """
    Load a CSV or Excel file into a DataFrame.
    • .csv  →  try pandas' default reader; on ParserError sniff the delimiter
    • .xls/.xlsx  →  pd.read_excel
    """
    ext = Path(path).suffix.lower()
    if ext == ".csv":
        try:
            return pd.read_csv(path, **pd_kwargs)
        except pd.errors.ParserError:
            with open(path, "r", newline="", encoding=pd_kwargs.get("encoding", "utf-8")) as fh:
                sample = fh.read(4096)
                delim = csv.Sniffer().sniff(sample, delimiters=[
                    ",", ";", "\t", "|"]).delimiter
            return pd.read_csv(path, delimiter=delim, engine="python", **pd_kwargs)
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path, **pd_kwargs)
    raise ValueError(f"Unsupported file type for input data: {ext}")

# --------------------- CLI ---------------------


parser = argparse.ArgumentParser()
parser.add_argument(
    'data_file', help='filename to load (CSV/XLSX or JSON array of paths)')
parser.add_argument('repeated_entities_file',
                    help='path used to locate dataset_variable_filter.json')
parser.add_argument(
    'suites_file', help='path used to locate variable_importance.json')
parser.add_argument('app_path', help='output directory')
parser.add_argument(
    "tumor_type",
    choices=["sarcoma", "head_and_neck"],
    help="Filter variables by tumour group (variables tagged 'both' are included)"
)
args = parser.parse_args()

# Allow JSON list of files; otherwise a single file
try:
    candidate = json.loads(args.data_file)
    data_files = candidate if isinstance(candidate, list) else [args.data_file]
except (json.JSONDecodeError, TypeError):
    data_files = [args.data_file]

# --------------------- Tumour filter ---------------------

dataset_filter_path = os.path.join(os.path.dirname(
    args.repeated_entities_file), "dataset_variable_filter.json")
with open(dataset_filter_path, encoding="utf8") as fh:
    VAR_GROUP = json.load(fh)  # e.g. "Patient_sex": "both"

# Normalize to Entity.variable
VAR_GROUP = {k.replace("_", "."): v for k, v in VAR_GROUP.items()}
ALLOWED = {args.tumor_type, "both"}


def keep(var: str) -> bool:
    """
    Return True if var is tagged for the selected tumour type.
    Tries full 'Entity.variable' first, then the short variable name.
    Defaults to 'both' when missing.
    """
    tag = (VAR_GROUP.get(var) or VAR_GROUP.get(var.split(".", 1)[-1], "both"))
    return tag in ALLOWED

# --------------------- Importance map ---------------------


def _norm(txt: str) -> str:
    return "".join(ch.lower() for ch in str(txt) if ch.isalnum())


importance_file = os.path.join(os.path.dirname(
    args.suites_file), "variable_importance.json")
importance_map = {}
try:
    with open(importance_file, encoding="utf-8") as fh:
        raw_map = json.load(fh)
    importance_map = {_norm(k.replace(".", "_"))                      : v for k, v in raw_map.items()}
except Exception:
    importance_map = {}


def importance_of(col: str) -> str:
    # Map to High/Medium/Low/Unknown
    code = importance_map.get(_norm(col.replace(".", "_"))) or importance_map.get(
        _norm(col.split(".", 1)[-1]), "")
    return {"M": "High", "R": "Medium", "O": "Low",
            "High": "High", "Medium": "Medium", "Low": "Low"}.get(code, "Unknown")

# --------------------- Load and combine data ---------------------


dfs = []
for p in data_files:
    try:
        dfs.append(read_table(p, dtype=str))
    except Exception as e:
        print(f"Warning: skipping '{p}': {e}")
if not dfs:
    raise SystemExit("ERROR: no readable input files.")

df_long_all = pd.concat(dfs, ignore_index=True)
expected_cols = {"patient_id", "core_variable", "value"}
if not expected_cols.issubset(df_long_all.columns):
    missing = expected_cols - set(df_long_all.columns)
    raise SystemExit(f"ERROR: input data missing required columns: {missing}")

# Normalize strings
df_long_all["patient_id"] = df_long_all["patient_id"].astype(str)
df_long_all["core_variable"] = df_long_all["core_variable"].astype(str)
df_long_all["value"] = df_long_all["value"].astype(str)

# --------------------- Build reduced matrix ---------------------

# Patients to consider
patient_ids = sorted(df_long_all["patient_id"].dropna().astype(str).unique())
num_patients = len(patient_ids)

# Variables filtered by tumour type (seen in data)
vars_in_data = sorted(
    v for v in df_long_all["core_variable"].dropna().astype(str).unique()
    if keep(v)
)

rows = []
for var in vars_in_data:
    # Missing if patient has no non-empty value for this variable
    miss = 0
    if num_patients == 0:
        missing_percent = 0.0
    else:
        for pid in patient_ids:
            sub = df_long_all[(df_long_all["patient_id"] == pid) & (
                df_long_all["core_variable"] == var)]
            has_value = False
            if not sub.empty:
                vals = sub["value"].astype(str).str.strip()
                has_value = any((~vals.isna()) & (vals != "")
                                & (vals.str.lower() != "nan"))
            if not has_value:
                miss += 1
        missing_percent = round((miss / num_patients) * 100, 2)

    rows.append({
        "Variable": var,
        "Importance": importance_of(var),
        "First phase": "Diagnosis",  # default; no phase derivation required for this output
        "MissingPercent": missing_percent
    })

df_matrix = pd.DataFrame(
    rows, columns=["Variable", "Importance", "First phase", "MissingPercent"])

# --------------------- Crosstab export only ---------------------


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

# Write only the final user crosstab
# crosstab_external_user(df_matrix, os.path.join(args.app_path, "user_crosstab_external.csv"))
