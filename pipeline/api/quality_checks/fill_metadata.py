import os
import json
import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from functools import lru_cache

VAR_SUMMARY_ENV = "VAR_SUMMARY_PATH"
# For Helm/container deployments, entities_cardinality.json lives under /app/quality_checks
# but this can be overridden with ENTITY_CARD_PATH.
ENTITY_CARD_PATH = os.getenv(
    "ENTITY_CARD_PATH",
    "/app/quality_checks/entities_cardinality.json",
)
RESULTS_DIR_ENV = "RESULTS_DIR"
DEFAULT_RESULTS_DIR = "/data/results"


@lru_cache(maxsize=1)
def _variable_summary_map() -> dict:
    """Load variable_summary_results.json → {var: {'Total': int, 'Failed': int}}."""
    path = os.getenv(VAR_SUMMARY_ENV) or os.path.join(
        "/data/results", "variable_summary_results.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or []
        return {
            str(r.get("Variable")): {
                "Total": int(r.get("Total") or 0),
                "Failed": int(r.get("Failed") or 0),
            }
            for r in data if isinstance(r, dict) and "Variable" in r
        }
    except Exception:
        return {}


def _qc_counts_for(var_core: str) -> tuple[int | None, int | None]:
    rec = _variable_summary_map().get(var_core)
    if rec:
        return rec["Total"], rec["Failed"]
    return None, None


@lru_cache(maxsize=1)
def _entity_cardinality() -> dict:
    """Load entities_cardinality.json → {Entity: min_cardinality}."""
    try:
        with open(ENTITY_CARD_PATH, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def _is_non_repeatable_entity(entity: str) -> bool:
    card = _entity_cardinality().get(entity)
    # default to repeatable if unknown; only 1 means non-repeatable
    return card == 1


def _compute_counts_from_df(df: pd.DataFrame, var_core: str) -> tuple[int, int]:
    """
    Fallback: compute (Total, Failed) from the long DF for var_core (Entity.field).
    - Non-repeatable: Total = #patients in DF; Failed = patients with empty/missing value for var_core.
    - Repeatable: Total = #entity instances (pid, rid) where Entity.* appears;
                  Failed = instances where var_core is missing/empty.
    """
    if df is None or df.empty or "core_variable" not in df.columns:
        return 0, 0

    dfa = df.copy()
    for c in ("patient_id", "record_id", "core_variable", "value"):
        if c not in dfa.columns:
            dfa[c] = pd.NA
    dfa["patient_id"] = dfa["patient_id"].astype(str)
    dfa["record_id"] = dfa["record_id"].astype(str)
    dfa["core_variable"] = dfa["core_variable"].astype(str)

    try:
        ent, short = var_core.split(".", 1)
    except ValueError:
        # malformed; treat as non-repeatable by patients
        patients = set(dfa["patient_id"].astype(str).unique())
        vals = dfa.loc[dfa["core_variable"] ==
                       var_core, ["patient_id", "value"]].copy()
        vals["v"] = vals["value"].astype(str).str.strip()
        present = set(vals.loc[vals["value"].notna() &
                      vals["v"].ne(""), "patient_id"].astype(str))
        total = len(patients)
        failed = max(0, total - len(present))
        return total, failed

    if _is_non_repeatable_entity(ent):
        # Non-repeatable: 1 row per patient expected
        patients = set(dfa["patient_id"].astype(str).unique())
        sub = dfa[dfa["core_variable"] == var_core].copy()
        if sub.empty:
            return len(patients), len(patients)
        sub["v"] = sub["value"].astype(str).str.strip()
        present = set(sub.loc[sub["value"].notna() &
                      sub["v"].ne(""), "patient_id"].astype(str))
        total = len(patients)
        failed = max(0, total - len(present))
        return total, failed

    # Repeatable: count by (pid, rid) instances for this entity
    ent_rows = dfa[dfa["core_variable"].str.startswith(f"{ent}.")].copy()
    if ent_rows.empty:
        return 0, 0
    inst = set(zip(ent_rows["patient_id"].astype(
        str), ent_rows["record_id"].astype(str)))
    var_rows = dfa[dfa["core_variable"] == var_core].copy()
    var_rows["v"] = var_rows["value"].astype(
        str).str.strip() if not var_rows.empty else ""
    present = set(
        zip(
            var_rows.loc[var_rows["value"].notna() & var_rows["v"].ne(
                ""), "patient_id"].astype(str),
            var_rows.loc[var_rows["value"].notna() & var_rows["v"].ne(
                ""), "record_id"].astype(str),
        )
    ) if not var_rows.empty else set()
    total = len(inst)
    failed = max(0, total - len(present))
    return total, failed


def read_table(path: str, **pd_kwargs) -> pd.DataFrame:
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, **pd_kwargs)
    if ext == ".csv":
        return pd.read_csv(path, **pd_kwargs)
    raise ValueError(f"Unsupported file type: {ext}")


def varid_to_core(var_id: str) -> str:
    # Turn "Entity_variableName" → "Entity.variableName"
    if "_" in var_id:
        ent, rest = var_id.split("_", 1)
        return f"{ent}.{rest}"
    return var_id.replace("_", ".", 1)


def non_empty(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return False
    return True


def compute_years(df_center: pd.DataFrame) -> str:
    mask = df_center["core_variable"] == "Diagnosis.dateOfDiagnosis"
    if not mask.any():
        return "Unknown"
    yrs = (
        pd.to_datetime(df_center.loc[mask, "value"], errors="coerce")
        .dropna()
        .dt.year
        .astype("Int64")
        .dropna()
    )
    if yrs.empty:
        return "Unknown"
    return f"{int(yrs.min())}-{int(yrs.max())}"


def compute_center_availability(df_center: pd.DataFrame, var_core: str) -> Dict[str, bool]:
    if df_center is None or df_center.empty:
        return {"availability_d": False, "availability_p": False, "availability_r": False}

    # Ensure expected columns
    for c in ("patient_id", "record_id", "core_variable", "value"):
        if c not in df_center.columns:
            df_center[c] = pd.NA
    dfa = df_center.copy()
    dfa["patient_id"] = dfa["patient_id"].astype(str)
    dfa["record_id"] = dfa["record_id"].astype(str)

    def to_ts(val):
        try:
            return pd.to_datetime(val, errors="coerce")
        except Exception:
            return pd.NaT

    # Phase-defining events (keep ALL diagnosis-like EE status events)
    epi_date_lookup = (
        dfa[dfa.core_variable == "EpisodeEvent.dateOfEpisode"]
        .set_index(["patient_id", "record_id"])["value"]
        .to_dict()
    )
    diag_lookup = (
        dfa[dfa.core_variable == "Diagnosis.dateOfDiagnosis"]
        .sort_values("value")
        .drop_duplicates("patient_id")
        .set_index("patient_id")["value"]
        .to_dict()
    )

    events = []
    for _, r in dfa.iterrows():
        cv = str(r.core_variable)
        if cv == "EpisodeEvent.diseaseStatus":
            code = str(r.value).strip()
            if code == "32949":
                phase = "Progression"
            elif code == "2000100002":
                phase = "Recurrence"
            else:
                phase = "Diagnosis"  # treat any other EE status as diagnosis-like
            dt_raw = epi_date_lookup.get(
                (r.patient_id, r.record_id)) or diag_lookup.get(r.patient_id)
            events.append((r.patient_id, phase, to_ts(dt_raw)))
        elif cv == "Diagnosis.dateOfDiagnosis":
            events.append((r.patient_id, "Diagnosis", to_ts(r.value)))

    phase_df = pd.DataFrame(
        events, columns=["pid", "phase", "date"]).dropna().sort_values("date")

    # 1) Compute general record date (min of any '...date...' variables in that record)
    record_min_dates = (
        dfa.assign(
            date=dfa.apply(
                lambda r: to_ts(r.value) if "date" in str(
                    r.core_variable).lower() else pd.NaT,
                axis=1,
            )
        )
        .groupby(["patient_id", "record_id"])["date"]
        .min()
        .reset_index()
    )

    # 2) Prefer the target variable’s own date for mapping, if it is a date variable
    target_dates = (
        dfa[dfa.core_variable == var_core]
        .assign(date=lambda x: x["value"].apply(to_ts))
        .groupby(["patient_id", "record_id"])["date"]
        .min()  # in case multiple rows exist
        .reset_index()
    )

    record_dates = record_min_dates.merge(
        target_dates, on=["patient_id", "record_id"], how="left", suffixes=("_min", "_target")
    )
    # choose target-specific date if available; else fall back to record min
    record_dates["date"] = record_dates["date_target"].combine_first(
        record_dates["date_min"])

    def closest_phase(row):
        pid, dt = row.patient_id, row.date
        # Default to Diagnosis if no usable date or no phase events
        if pd.isna(dt) or phase_df.empty:
            return "Diagnosis"
        cand = phase_df[(phase_df.pid == pid) & (phase_df.date <= dt)]
        if cand.empty:
            return "Diagnosis"
        idx = (dt - cand.date).idxmin()
        return cand.loc[idx, "phase"]

    record_dates["phase"] = record_dates.apply(closest_phase, axis=1)

    # Attach phase/date to each row
    df_with_phase = dfa.merge(
        record_dates[["patient_id", "record_id", "phase", "date"]],
        on=["patient_id", "record_id"],
        how="left",
    )

    # Target variable instances with non-empty values
    sub = df_with_phase[df_with_phase["core_variable"] == var_core].copy()
    if sub.empty:
        return {"availability_d": False, "availability_p": False, "availability_r": False}

    # Only require non-empty value; phase is guaranteed (defaults to Diagnosis)
    val_str = sub["value"].astype(str)
    sub = sub[sub["value"].notna() & val_str.str.strip().ne("")
              & sub["phase"].notna()]

    avail_d = bool((sub["phase"] == "Diagnosis").any())
    avail_p = bool((sub["phase"] == "Progression").any())
    avail_r = bool((sub["phase"] == "Recurrence").any())

    return {"availability_d": avail_d, "availability_p": avail_p, "availability_r": avail_r}


def fill_for_center(
    metadata_items: List[Dict[str, Any]],
    df_long: pd.DataFrame,
    center_code: str,
    datasource_name: str,
    datasource_info: str,
) -> List[Dict[str, Any]]:
    # Use all rows for statistics; center_code only selects which center to fill
    df_center = df_long.copy()

    # Ensure required columns exist
    for c in ("patient_id", "core_variable", "value"):
        if c not in df_center.columns:
            df_center[c] = ""

    df_center["patient_id"] = df_center["patient_id"].astype(str)
    df_center["core_variable"] = df_center["core_variable"].astype(str)

    n_cases = int(df_center["patient_id"].nunique()
                  ) if not df_center.empty else 0
    print(
        f"Filling metadata for center '{center_code}' with {n_cases} patients.")
    years_str = compute_years(df_center)

    def build_center_block(var_core: str) -> Dict[str, Any]:
        # Try QC-derived counts first; if missing, compute from DF
        qc_total, qc_failed = _qc_counts_for(var_core)
        if qc_total is None or qc_failed is None:
            n_cases, m_cases = _compute_counts_from_df(df_center, var_core)
        else:
            n_cases, m_cases = int(qc_total), int(qc_failed)

        overall_score = int(
            round(((n_cases - m_cases) / n_cases) * 100)) if n_cases > 0 else 0

        print(
            f"  Variable '{var_core}': n_cases={n_cases}, m_cases={m_cases}, overall_score={overall_score}%")
        availability = compute_center_availability(df_center, var_core)

        return {
            # ensure plain JSON-native types
            "availability_d": bool(availability["availability_d"]),
            "availability_p": bool(availability["availability_p"]),
            "availability_r": bool(availability["availability_r"]),
            "years": str(years_str),
            "datasource_name": str(datasource_name),
            "datasource_information": str(datasource_info),
            "n_cases": int(n_cases),
            "m_cases": int(m_cases),
            "plausability_score": "Does not apply",
            "overall_score": int(overall_score),
        }

    # Update centers array for each variable (only the entry keyed by center_code)
    for item in metadata_items:
        var_id = item.get("variable_id", "")
        core_name = varid_to_core(var_id)
        center_block = build_center_block(core_name)

        centers = item.get("centers", [])
        updated = False
        for idx, c in enumerate(centers):
            if isinstance(c, dict) and center_code in c:
                centers[idx][center_code] = center_block
                updated = True
                break
        if not updated:
            centers.append({center_code: center_block})
        item["centers"] = centers

    return metadata_items


def detect_delimiter(file_path: str) -> str:
    with open(file_path, 'r', encoding='utf-8') as f:
        first_line = f.readline()
        if first_line.count(';') > first_line.count(','):
            return ';'
        else:
            return ','


def _default(value, fallback):
    return value if value is not None and str(value).strip() != "" else fallback


def _make_out_path(center_code: str | None, out_path: str | None) -> str:
    if out_path and isinstance(out_path, str):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        return out_path
    base = os.getenv(RESULTS_DIR_ENV, DEFAULT_RESULTS_DIR)
    os.makedirs(base, exist_ok=True)
    cc = (center_code or "ALL").replace("/", "_")
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Output path not provided; using default results dir: {base}")
    return os.path.join(base, f"filled_metadata_{cc}_{stamp}.json")


def run_fill_metadata(
    df: pd.DataFrame,
    center_code: str | None = None,
    datasource_name: str | None = None,
    datasource_info: str | None = None,
    out_path: str | None = None,
) -> str:
    """
    Build filled metadata JSON and write it to disk, returning the file path.
    """
    # Defaults
    center_code = _default(center_code, os.getenv("CENTER_CODE", "FPNS"))
    datasource_name = _default(datasource_name, os.getenv(
        "METADATA_DATASOURCE_NAME", "DEFAULT"))
    datasource_info = _default(datasource_info, os.getenv(
        "METADATA_DATASOURCE_INFORMATION", "No data provided"))
    out_path_resolved = _make_out_path(center_code, out_path)

    here = Path(__file__).parent
    template_path = here / "empty_metadata.json"
    try:
        with open(template_path, "r", encoding="utf-8") as fh:
            metadata_items = json.load(fh)
    except Exception:
        metadata_items = []

    # Fill centers
    filled = fill_for_center(
        metadata_items=metadata_items,
        df_long=df,
        center_code=center_code,
        datasource_name=str(datasource_name),
        datasource_info=str(datasource_info),
    )

    # Persist
    with open(out_path_resolved, "w", encoding="utf-8") as fh:
        json.dump(filled, fh, ensure_ascii=False, indent=2)

    return out_path_resolved


def main():
    # Inputs
    center = os.getenv("CENTER_NAME", "FPNS2")
    datasource_name = os.getenv(
        "METADATA_DATASOURCE_NAME", "No datasource name provided")
    datasource_info = os.getenv(
        "METADATA_DATASOURCE_INFORMATION", "No datasource information provided")

    # Paths
    here = Path(__file__).parent
    metadata_path = os.getenv(
        "EMPTY_METADATA_PATH",
        str(here / "empty_metadata.json"),
    )
    # required
    data_file = os.getenv("LONG_DATA_PATH", "D:\\Book 1(Hoja1).xlsx")
    data_file = "/data/fpns.xlsx"

    if not data_file or not Path(data_file).exists():
        raise SystemExit(
            "Set LONG_DATA_PATH to the long-format data file (csv/xlsx).")

    # Load data
    # check if csv or xlsx and load accordingly, also check for delimeter
    if data_file.endswith(".xlsx"):
        df = pd.read_excel(data_file, dtype=str)
    else:
        # delimeter
        delimiter = detect_delimiter(data_file)
        df = read_table(data_file, dtype=str, delimiter=delimiter)
    print(f"Loaded data: {data_file} with {len(df)} rows.")
    # Load metadata skeleton
    with open(metadata_path, encoding="utf-8") as fh:
        metadata = json.load(fh)

    # Compute and fill
    filled = fill_for_center(
        metadata_items=metadata,
        df_long=df,
        center_code=center,
        datasource_name=datasource_name,
        datasource_info=datasource_info,
    )

    # Output
    out_path = os.getenv(
        "FILLED_METADATA_PATH",
        str(Path(metadata_path).with_name(f"filled_metadata_{center}.json")),
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(filled, fh, ensure_ascii=False, indent=2)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
