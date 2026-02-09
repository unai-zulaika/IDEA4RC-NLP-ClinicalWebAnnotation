"""Special-case handler functions for specific sarcoma annotations."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence
import re
import pandas
from .processing_utils import parse_date_any, to_str

Handler = Callable[[Dict[str, Any]], List[Dict[str, Any]]]


def _match_value(match: Any, index: int) -> str:
    """Safely extract a capture group from regex results."""
    if match is None:
        return ""
    if isinstance(match, Sequence) and not isinstance(match, (str, bytes)):
        try:
            return to_str(match[index])
        except (IndexError, TypeError):
            return ""
    group_fn = getattr(match, "group", None)
    if callable(group_fn):
        try:
            return to_str(group_fn(index))
        except Exception:
            return ""
    return to_str(match) if index == 0 else ""


def _extract_float(text: str) -> float | None:
    if not text:
        return None
    normalized = to_str(text).replace(",", ".")
    match = re.search(r"[-+]?\d*\.?\d+", normalized)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def handle_radiotherapy_site(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Expand metastatic radiotherapy sites into individual boolean flags."""
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    match = ctx.get("match")

    site_category = _match_value(match, 0).lower()
    details = _match_value(match, 1)

    if "metastatic" not in site_category:
        return []

    tokens = [t.strip().lower() for t in details.split(",") if t and t.strip()]
    normalized = {token.replace("-", " ").replace("_", " ").strip()
                  for token in tokens}

    site_var_map = {
        "lung": "Radiotherapy.metastaticTreatmentSiteLung",
        "mediastinum": "Radiotherapy.metastaticTreatmentSiteMediastinum",
        "bone": "Radiotherapy.metastaticTreatmentSiteBone",
        "soft tissue": "Radiotherapy.metastaticTreatmentSiteSoftTissue",
        "liver": "Radiotherapy.metastaticTreatmentSiteLiver",
    }

    def matches_soft_tissue(token: str) -> bool:
        return token.startswith("soft") or "soft tissue" in token

    rows: List[Dict[str, Any]] = []
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
            continue

        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": var,
                "date_ref": date_ref,
                "value": True,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "boolean",
            }
        )

    return rows


def _next_record_id(excel_data: pandas.DataFrame | None, staged_rows: List[Dict[str, Any]]) -> int:
    """Compute the next record_id based on existing excel/staged rows."""
    max_id = 0
    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty and "record_id" in excel_data.columns:
        for value in excel_data["record_id"].tolist():
            try:
                max_id = max(max_id, int(value))
            except (TypeError, ValueError):
                continue

    for row in staged_rows:
        try:
            max_id = max(max_id, int(row.get("record_id")))
        except (TypeError, ValueError):
            continue

    return max_id + 1


def _find_recent_episode_event_id(
    patient_id: Any,
    annotation_dt: Any,
    excel_data: pandas.DataFrame | None,
    staged_rows: List[Dict[str, Any]],
) -> int | None:
    """Locate the most recent EpisodeEvent within 14 days of the annotation."""

    candidates: List[tuple[Any, int]] = []

    def add_candidate(date_str: Any, record_id: Any) -> None:
        if record_id in (None, ""):
            return
        episode_dt = parse_date_any(to_str(date_str))
        if not episode_dt:
            return
        if annotation_dt:
            delta = (annotation_dt - episode_dt).days
            if delta < 0 or delta > 14:
                return
        try:
            candidates.append((episode_dt, int(record_id)))
        except (TypeError, ValueError):
            return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        if "core_variable" in excel_data.columns:
            subset = excel_data[excel_data["core_variable"]
                                == "EpisodeEvent.dateOfEpisode"]
        else:
            subset = pandas.DataFrame()
        for _, row in subset.iterrows():
            if to_str(row.get("patient_id")) != to_str(patient_id):
                continue
            add_candidate(row.get("value") or row.get(
                "date_ref"), row.get("record_id"))

    for row in staged_rows:
        if to_str(row.get("patient_id")) != to_str(patient_id):
            continue
        if row.get("core_variable") != "EpisodeEvent.dateOfEpisode":
            continue
        add_candidate(row.get("value") or row.get(
            "date_ref"), row.get("record_id"))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][1]


def handle_disease_extent_progression(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create DiseaseExtent rows linked to recent EpisodeEvents for annotation 242."""

    match = ctx.get("match")
    patient_id = ctx["patient_id"]
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    date_ref = ctx.get("date")
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    recurrence_type = _match_value(match, 0).strip().lower()
    site_text = _match_value(match, 1).strip().lower()

    if not recurrence_type:
        return []

    annotation_dt = parse_date_any(to_str(date_ref))
    episode_event_id = _find_recent_episode_event_id(
        patient_id, annotation_dt, excel_data, staged_rows)

    if not episode_event_id:
        return []

    is_local = "local" in recurrence_type
    is_metastatic = "metast" in recurrence_type

    if not (is_local or is_metastatic):
        return []

    site_value_map = {
        "lung": ("DiseaseExtent.lung", "36770283"),
        "liver": ("DiseaseExtent.liver", "36770544"),
        "brain": ("DiseaseExtent.brain", "36768862"),
        "bone": ("DiseaseExtent.metastasisatbone", "36769301"),
        "soft tissue": ("DiseaseExtent.softTissue", "35225724"),
        "other": ("DiseaseExtent.otherViscera", "4077953"),
        "unknown": ("DiseaseExtent.otherViscera", "4129922"),
    }

    sites: List[str] = []
    if is_metastatic and site_text:
        cleaned = site_text.replace("[select site if metastatic]", "")
        for token in re.split(r",|;|/| and ", cleaned):
            normalized = token.strip().lower().strip(". ")
            if not normalized:
                continue
            if "select site" in normalized:
                continue
            normalized = re.sub(r"^(in|to|at|on|the)\s+", "", normalized)
            normalized = re.sub(r"metastases?", "", normalized).strip()
            if normalized.endswith("s") and normalized[:-1] in {"lung", "bone", "liver", "brain"}:
                normalized = normalized[:-1]
            if "soft tissue" in normalized:
                normalized = "soft tissue"
            elif "other" in normalized and "unknown" not in normalized:
                normalized = "other"
            elif "unknown" in normalized:
                normalized = "unknown"
            sites.append(normalized)

    unique_sites: List[str] = []
    for site in sites:
        if site not in unique_sites:
            unique_sites.append(site)

    next_record_id = _next_record_id(excel_data, staged_rows)

    rows: List[Dict[str, Any]] = [
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "DiseaseExtent.episodeEvent",
            "date_ref": date_ref,
            "value": episode_event_id,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "reference",
            "record_id": next_record_id,
        }
    ]

    if is_local:
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "DiseaseExtent.localised",
                "date_ref": date_ref,
                "value": "32942",
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "concept",
                "record_id": next_record_id,
            }
        )

    if is_metastatic:
        target_sites = unique_sites if unique_sites else (
            ["other"] if site_text else [])
        for site in target_sites:
            mapping = site_value_map.get(site)
            if not mapping:
                continue
            variable, concept_id = mapping
            rows.append(
                {
                    "patient_id": patient_id,
                    "original_source": "NLP_LLM",
                    "core_variable": variable,
                    "date_ref": date_ref,
                    "value": concept_id,
                    "note_id": note_id,
                    "prompt_type": prompt_type,
                    "types": "concept",
                    "record_id": next_record_id,
                }
            )

    return rows


def handle_ilp_drugs(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Emit linked ILP drug rows for annotation 211."""
    match = ctx.get("match")
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    base_record_id = ctx.get("base_record_id")

    if base_record_id is None:
        return []

    details = _match_value(match, 1)
    if not details:
        return []

    tokens = [t.strip() for t in details.split(",") if t and t.strip()]
    if not tokens:
        return []

    rows: List[Dict[str, Any]] = []
    for drug in tokens:
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "DrugsForTreatments.isolatedLimbPerfusion",
                "date_ref": date_ref,
                "value": True,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "boolean",
                "record_id": base_record_id,
            }
        )
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "DrugsForTreatments.drug",
                "date_ref": date_ref,
                "value": drug,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "string",
                "record_id": base_record_id,
            }
        )

    return rows


def handle_episode_event_link(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Link EpisodeEvent rows to the latest CancerEpisode for the same patient."""
    patient_id = ctx["patient_id"]
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])
    base_record_id = ctx.get("base_record_id")

    if not base_record_id:
        return []

    episode_date_str = ""
    for row in reversed(staged_rows):
        if (
            row.get("record_id") == base_record_id
            and to_str(row.get("patient_id")) == to_str(patient_id)
            and row.get("core_variable") == "EpisodeEvent.dateOfEpisode"
            and to_str(row.get("value"))
        ):
            episode_date_str = to_str(row.get("value"))
            break
    if not episode_date_str:
        episode_date_str = to_str(ctx.get("date"))

    episode_dt = parse_date_any(episode_date_str)
    if not episode_dt:
        return []

    # Skip if a link already exists for this record in staged rows.
    for row in staged_rows:
        if (
            row.get("record_id") == base_record_id
            and row.get("core_variable") == "EpisodeEvent.cancerEpisode"
        ):
            return []

    candidates: List[tuple[Any, int]] = []

    def add_candidate(date_str: str, record_id: Any) -> None:
        date_obj = parse_date_any(date_str)
        if date_obj and record_id not in (None, ""):
            try:
                candidates.append((date_obj, int(record_id)))
            except (TypeError, ValueError):
                pass

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, row in excel_data.iterrows():
            if to_str(row.get("patient_id")) != to_str(patient_id):
                continue
            if row.get("core_variable") != "CancerEpisode.cancerStartDate":
                continue
            candidate_date = to_str(
                row.get("value")) or to_str(row.get("date_ref"))
            add_candidate(candidate_date, row.get("record_id"))

    for row in staged_rows:
        if to_str(row.get("patient_id")) != to_str(patient_id):
            continue
        if row.get("core_variable") != "CancerEpisode.cancerStartDate":
            continue
        candidate_date = to_str(
            row.get("value")) or to_str(row.get("date_ref"))
        add_candidate(candidate_date, row.get("record_id"))

    if not candidates:
        return []

    prior_candidates = [item for item in candidates if item[0] <= episode_dt]
    if not prior_candidates:
        return []

    _, linked_episode_id = max(prior_candidates, key=lambda item: item[0])

    return [
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "EpisodeEvent.cancerEpisode",
            "date_ref": episode_date_str,
            "value": linked_episode_id,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "reference",
            "record_id": base_record_id,
        }
    ]


def handle_weight_height_bmi(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    match = ctx.get("match")
    patient_id = ctx["patient_id"]
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    date_ref = ctx.get("date")

    weight = _extract_float(_match_value(match, 0))
    height = _extract_float(_match_value(match, 1))

    if not weight or not height:
        return []
    height_m = height / 100 if height > 3 else height
    if height_m <= 0:
        return []

    bmi = round(weight / (height_m**2), 2)

    return [
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "Patient.heightWeight",
            "date_ref": date_ref,
            "value": bmi,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "float",
        }
    ]


def handle_genetic_syndromes(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    match = ctx.get("match")
    patient_id = ctx["patient_id"]
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    date_ref = ctx.get("date")

    selection = _match_value(match, 0)
    if not selection:
        return []

    mapping = {
        "olliers disease": ("Patient.olliersDisease", "4145177"),
        "maffucci syndrome": ("Patient.maffuciSyndrome", "4187683"),
        "li fraumeni syndrome": ("Patient.liFraumeniSyndrome", "4323645"),
        "mccune albright syndrome": ("Patient.mccuneAlBrightSyndrome", "37117262"),
        "multiple osteochondromas": ("Patient.multipleOsteochondromas", "37396802"),
        "neurofibromatosis type 1": ("Patient.neurofibromatosisType1", "377252"),
        "rothmund thomson syndrome": ("Patient.rothmundThomsonSyndrome", "4286355"),
        "werner syndrome": ("Patient.wernerSyndrome", "4197821"),
        "retinoblastoma": ("Patient.retinoblastoma", "4158977"),
        "paget disease": ("Patient.pagetDisease", "75910"),
    }

    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for token in re.split(r",|;|/| and ", to_str(selection)):
        normalized = to_str(token).lower().replace("–", "-")
        normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        mapping_entry = mapping.get(normalized)
        if not mapping_entry:
            continue
        core_variable, concept_id = mapping_entry
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": core_variable,
                "date_ref": date_ref,
                "value": concept_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "concept",
            }
        )
    return rows


def handle_no_genetic_syndrome(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "patient_id": ctx["patient_id"],
            "original_source": "NLP_LLM",
            "core_variable": "Patient.noGeneticSyndrome",
            "date_ref": ctx.get("date"),
            "value": True,
            "note_id": ctx.get("note_id"),
            "prompt_type": ctx.get("prompt_type"),
            "types": "boolean",
        }
    ]


def handle_radiotherapy_induced_sarcoma(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Annotation 76: Radiotherapy induced sarcoma → boolean flag."""
    return [
        {
            "patient_id": ctx["patient_id"],
            "original_source": "NLP_LLM",
            "core_variable": "Diagnosis.radiotherapyInducedSarcoma",
            "date_ref": ctx.get("date"),
            "value": True,
            "note_id": ctx.get("note_id"),
            "prompt_type": ctx.get("prompt_type"),
            "types": "boolean",
        }
    ]


def _find_nearby_disease_extent_group(
    patient_id: Any,
    annotation_dt: Any,
    excel_data: pandas.DataFrame | None,
    staged_rows: List[Dict[str, Any]],
) -> int | None:
    """Find a DiseaseExtent group (record_id) within ±14 days of annotation date."""
    if not annotation_dt:
        return None

    def is_dx(cv: Any) -> bool:
        return to_str(cv).startswith("DiseaseExtent.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        if "patient_id" in excel_data.columns:
            subset = excel_data[excel_data["patient_id"] == patient_id]
        else:
            subset = pandas.DataFrame()
        for _, row in subset.iterrows():
            if not is_dx(row.get("core_variable")):
                continue
            dt = parse_date_any(to_str(row.get("date_ref")))
            if not dt:
                continue
            delta = abs((annotation_dt - dt).days)
            if delta <= 14:
                try:
                    candidates.append((delta, int(row.get("record_id"))))
                except (TypeError, ValueError):
                    continue

    for row in staged_rows:
        if to_str(row.get("patient_id")) != to_str(patient_id):
            continue
        if not is_dx(row.get("core_variable")):
            continue
        dt = parse_date_any(to_str(row.get("date_ref")))
        if not dt:
            continue
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                candidates.append((delta, int(row.get("record_id"))))
            except (TypeError, ValueError):
                continue

    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][1]


def _find_latest_episode_event_id(
    patient_id: Any,
    annotation_dt: Any,
    excel_data: pandas.DataFrame | None,
    staged_rows: List[Dict[str, Any]],
) -> int | None:
    """Find the latest EpisodeEvent (by date) for patient; prefer <= annotation date."""
    candidates: List[tuple[Any, int]] = []

    def add_candidate(date_str: Any, record_id: Any) -> None:
        if record_id in (None, ""):
            return
        dt = parse_date_any(to_str(date_str))
        if not dt:
            return
        try:
            candidates.append((dt, int(record_id)))
        except (TypeError, ValueError):
            return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        if "core_variable" in excel_data.columns:
            subset = excel_data[excel_data["core_variable"]
                                == "EpisodeEvent.dateOfEpisode"]
        else:
            subset = pandas.DataFrame()
        for _, row in subset.iterrows():
            if to_str(row.get("patient_id")) != to_str(patient_id):
                continue
            add_candidate(row.get("value") or row.get(
                "date_ref"), row.get("record_id"))

    for row in staged_rows:
        if to_str(row.get("patient_id")) != to_str(patient_id):
            continue
        if row.get("core_variable") != "EpisodeEvent.dateOfEpisode":
            continue
        add_candidate(row.get("value") or row.get(
            "date_ref"), row.get("record_id"))

    if not candidates:
        return None

    if annotation_dt:
        prior = [c for c in candidates if c[0] <= annotation_dt]
        if prior:
            return max(prior, key=lambda t: t[0])[1]
    # Fallback: absolute latest if none prior
    return max(candidates, key=lambda t: t[0])[1]


def handle_localized_stage(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Annotation 91: Stage at diagnosis: localized → DiseaseExtent.localised True and optional episode link."""
    patient_id = ctx["patient_id"]
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    date_ref = ctx.get("date")
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))
    group_record_id = _find_nearby_disease_extent_group(
        patient_id, annotation_dt, excel_data, staged_rows)

    rows: List[Dict[str, Any]] = []

    if group_record_id is None:
        group_record_id = _next_record_id(excel_data, staged_rows)
        # Try link to the latest EpisodeEvent
        episode_event_id = _find_latest_episode_event_id(
            patient_id, annotation_dt, excel_data, staged_rows)
        if episode_event_id:
            rows.append(
                {
                    "patient_id": patient_id,
                    "original_source": "NLP_LLM",
                    "core_variable": "DiseaseExtent.episodeEvent",
                    "date_ref": date_ref,
                    "value": episode_event_id,
                    "note_id": note_id,
                    "prompt_type": prompt_type,
                    "types": "reference",
                    "record_id": group_record_id,
                }
            )

    # Always add the localized flag in the group (boolean True as requested)
    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "DiseaseExtent.localised",
            "date_ref": date_ref,
            "value": True,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "boolean",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_loco_regional(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Annotation 92: Stage at diagnosis: loco-regional → boolean flags."""
    patient_id = ctx["patient_id"]
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    date_ref = ctx.get("date")
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])
    match = ctx.get("match")

    selection = _match_value(match, 0).lower()
    annotation_dt = parse_date_any(to_str(date_ref))
    group_record_id = _find_nearby_disease_extent_group(
        patient_id, annotation_dt, excel_data, staged_rows)
    if group_record_id is None:
        group_record_id = _next_record_id(excel_data, staged_rows)

    rows: List[Dict[str, Any]] = [
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "DiseaseExtent.locoRegional",
            "date_ref": date_ref,
            "value": True,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "boolean",
            "record_id": group_record_id,
        }
    ]

    if "transit" in selection:
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "DiseaseExtent.isTransitMetastasisWithClinicalConfirmation",
                "date_ref": date_ref,
                "value": True,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "boolean",
                "record_id": group_record_id,
            }
        )
    elif "multifocal" in selection:
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "DiseaseExtent.isMultifocalTumor",
                "date_ref": date_ref,
                "value": True,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "boolean",
                "record_id": group_record_id,
            }
        )

    return rows


def handle_regional_deep_hyperthermia_link(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 219: If 'select combination' is 'in combination with radiotherapy',
    create a Radiotherapy.regionalDeepHyperthemia row whose value is the record_id
    of the RegionalDeepHyperthemia group (anchored on RegionalDeepHyperthemia.startDate).
    """
    match = ctx.get("match")
    patient_id = ctx["patient_id"]
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    date_ref = ctx.get("date")
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])
    base_record_id = ctx.get("base_record_id")

    # Extract 'select combination' (first group)
    selection = _match_value(match, 0).lower()
    if "radiotherapy" not in selection:
        return []

    # Fallback: try to resolve base_record_id if missing by locating a RegionalDeepHyperthemia.startDate row
    if not base_record_id:
        # Prefer a staged row for current patient
        for row in reversed(staged_rows):
            if (
                to_str(row.get("patient_id")) == to_str(patient_id)
                and row.get("core_variable") == "RegionalDeepHyperthemia.startDate"
                and to_str(row.get("record_id"))
            ):
                try:
                    base_record_id = int(row.get("record_id"))
                    break
                except (TypeError, ValueError):
                    continue

        # Look into excel_data if still not found
        if not base_record_id and isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
            if "patient_id" in excel_data.columns and "core_variable" in excel_data.columns:
                subset = excel_data[
                    (excel_data["patient_id"] == patient_id)
                    & (excel_data["core_variable"] == "RegionalDeepHyperthemia.startDate")
                ]
            else:
                subset = pandas.DataFrame()
            if not subset.empty:
                try:
                    base_record_id = int(subset.iloc[-1]["record_id"])
                except (TypeError, ValueError, KeyError):
                    base_record_id = None

    if not base_record_id:
        return []

    return [
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "Radiotherapy.regionalDeepHyperthemia",
            "date_ref": date_ref,
            "value": base_record_id,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "reference",
            "record_id": base_record_id,
        }
    ]


def handle_patient_followup_dod(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 225 (parameterless): Dead of Disease (DOD)
    - If a PatientFollowUp group exists within ±14 days of note date, reuse its record_id.
    - Else create a new group (record_id) and add PatientFollowUp.patient reference.
    - Always add PatientFollowUp.statusAtLastFollowUp = 2000100072 in the chosen group.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx.get("date")
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_pfu(cv: Any) -> bool:
        return to_str(cv).startswith("PatientFollowUp.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series):
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_pfu(row.get("core_variable")):
            return
        # prefer date_ref; fallback to value for known date fields
        date_str = to_str(row.get("date_ref"))
        if not date_str and row.get("core_variable") in {"PatientFollowUp.patientFollowUpDate", "PatientFollowUp.lastContact"}:
            date_str = to_str(row.get("value"))
        dt = parse_date_any(date_str)
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                rid = int(row.get("record_id"))
                candidates.append((delta, rid))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        # pick nearest by days; if tie, smaller record_id
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    if group_record_id is None:
        # allocate a new group id
        group_record_id = _next_record_id(excel_data, staged_rows)  # noqa: F821 (defined elsewhere in file)
        create_patient_row = True
    else:
        create_patient_row = False

    rows: List[Dict[str, Any]] = []

    if create_patient_row:
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "PatientFollowUp.patient",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    # Always add the DOD status row
    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "PatientFollowUp.statusAtLastFollowUp",
            "date_ref": date_ref,
            "value": "2000100072",
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "concept",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_patient_followup_doc(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 226 (parameterless): Dead of Other Cause (DOC)
    - If a PatientFollowUp group exists within ±14 days of note date, reuse its record_id.
    - Else create a new group (record_id) and add PatientFollowUp.patient reference.
    - Always add PatientFollowUp.statusAtLastFollowUp = 2000100073 in the chosen group.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_pfu(cv: Any) -> bool:
        return to_str(cv).startswith("PatientFollowUp.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series):
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_pfu(row.get("core_variable")):
            return
        date_str = to_str(row.get("date_ref"))
        if not date_str and row.get("core_variable") in {"PatientFollowUp.patientFollowUpDate", "PatientFollowUp.lastContact"}:
            date_str = to_str(row.get("value"))
        dt = parse_date_any(date_str)
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                rid = int(row.get("record_id"))
                candidates.append((delta, rid))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    rows: List[Dict[str, Any]] = []

    if group_record_id is None:
        # allocate a new group id
        # _next_record_id is defined elsewhere in this module
        group_record_id = _next_record_id(excel_data, staged_rows)
        # create PatientFollowUp.patient reference in the new group
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "PatientFollowUp.patient",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    # Always add the DOC status row
    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "PatientFollowUp.statusAtLastFollowUp",
            "date_ref": date_ref,
            "value": "2000100073",
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "concept",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_patient_followup_duc(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 227 (parameterless): Dead of Unknown Cause (DUC)
    - If a PatientFollowUp group exists within ±14 days of note date, reuse its record_id.
    - Else create a new group (record_id) and add PatientFollowUp.patient reference.
    - Always add PatientFollowUp.statusAtLastFollowUp = 2000100074 in the chosen group.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_pfu(cv: Any) -> bool:
        return to_str(cv).startswith("PatientFollowUp.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series):
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_pfu(row.get("core_variable")):
            return
        date_str = to_str(row.get("date_ref"))
        if not date_str and row.get("core_variable") in {"PatientFollowUp.patientFollowUpDate", "PatientFollowUp.lastContact"}:
            date_str = to_str(row.get("value"))
        dt = parse_date_any(date_str)
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                rid = int(row.get("record_id"))
                candidates.append((delta, rid))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    rows: List[Dict[str, Any]] = []

    if group_record_id is None:
        # allocate a new group id
        group_record_id = _next_record_id(excel_data, staged_rows)
        # create PatientFollowUp.patient reference in the new group
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "PatientFollowUp.patient",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    # Always add the DUC status row
    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "PatientFollowUp.statusAtLastFollowUp",
            "date_ref": date_ref,
            "value": "2000100074",
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "concept",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_patient_followup_ned(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 228 (parameterless): Alive, No Evidence of Disease (NED)
    - If a PatientFollowUp group exists within ±14 days of note date, reuse its record_id.
    - Else create a new group (record_id) and add PatientFollowUp.patient reference.
    - Always add PatientFollowUp.statusAtLastFollowUp = 2000100071 in the chosen group.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_pfu(cv: Any) -> bool:
        return to_str(cv).startswith("PatientFollowUp.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series):
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_pfu(row.get("core_variable")):
            return
        # prefer date_ref; fallback to value for known date fields
        date_str = to_str(row.get("date_ref"))
        if not date_str and row.get("core_variable") in {"PatientFollowUp.patientFollowUpDate", "PatientFollowUp.lastContact"}:
            date_str = to_str(row.get("value"))
        dt = parse_date_any(date_str)
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                rid = int(row.get("record_id"))
                candidates.append((delta, rid))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    rows: List[Dict[str, Any]] = []

    if group_record_id is None:
        # allocate a new group id
        group_record_id = _next_record_id(excel_data, staged_rows)
        # create PatientFollowUp.patient reference in the new group
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "PatientFollowUp.patient",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    # Always add the NED status row
    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "PatientFollowUp.statusAtLastFollowUp",
            "date_ref": date_ref,
            "value": "2000100071",
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "concept",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_patient_followup_awd_local(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 229 (parameterless): Alive With Disease (AWD) - local
    - Reuse an existing PatientFollowUp group within ±14 days of the note date.
    - Otherwise create a new group (record_id) and add PatientFollowUp.patient reference.
    - Always add PatientFollowUp.statusAtLastFollowUp = 2000100075 in that group.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx.get("date")
    note_id = ctx["note_id"]
    prompt_type = ctx.get("prompt_type")
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_pfu(cv: Any) -> bool:
        return to_str(cv).startswith("PatientFollowUp.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series):
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_pfu(row.get("core_variable")):
            return
        date_str = to_str(row.get("date_ref"))
        if not date_str and row.get("core_variable") in {"PatientFollowUp.patientFollowUpDate", "PatientFollowUp.lastContact"}:
            date_str = to_str(row.get("value"))
        dt = parse_date_any(date_str)
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                rid = int(row.get("record_id"))
                candidates.append((delta, rid))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    rows: List[Dict[str, Any]] = []

    if group_record_id is None:
        # _next_record_id is available in this module
        group_record_id = _next_record_id(excel_data, staged_rows)
        # create PatientFollowUp.patient reference in the new group
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "PatientFollowUp.patient",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    # Always add the AWD-local status row
    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "PatientFollowUp.statusAtLastFollowUp",
            "date_ref": date_ref,
            "value": "2000100075",
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "concept",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_patient_followup_awd_nodes(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 230 (parameterless): Alive With Disease (AWD) - lymph nodes
    - Reuse an existing PatientFollowUp group within ±14 days of the note date.
    - Otherwise create a new group (record_id) and add PatientFollowUp.patient reference.
    - Always add PatientFollowUp.statusAtLastFollowUp = 2000100075 in that group.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_pfu(cv: Any) -> bool:
        return to_str(cv).startswith("PatientFollowUp.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series):
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_pfu(row.get("core_variable")):
            return
        date_str = to_str(row.get("date_ref"))
        if not date_str and row.get("core_variable") in {"PatientFollowUp.patientFollowUpDate", "PatientFollowUp.lastContact"}:
            date_str = to_str(row.get("value"))
        dt = parse_date_any(date_str)
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                rid = int(row.get("record_id"))
                candidates.append((delta, rid))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    rows: List[Dict[str, Any]] = []

    if group_record_id is None:
        # allocate a new group id and create PatientFollowUp.patient
        group_record_id = _next_record_id(excel_data, staged_rows)
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "PatientFollowUp.patient",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    # Always add the AWD status row (concept 2000100075)
    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "PatientFollowUp.statusAtLastFollowUp",
            "date_ref": date_ref,
            "value": "2000100075",
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "concept",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_patient_followup_awd_metastatic(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 231: Alive With Disease (AWD) - metastatic
    - If a PatientFollowUp group exists within ±14 days of the note date, reuse its record_id.
    - Else create a new group (record_id) and add PatientFollowUp.patient reference.
    - Always add PatientFollowUp.statusAtLastFollowUp = 2000100075 in the chosen group.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_pfu(cv: Any) -> bool:
        return to_str(cv).startswith("PatientFollowUp.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series):
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_pfu(row.get("core_variable")):
            return
        # prefer date_ref; fallback to value for known date fields
        date_str = to_str(row.get("date_ref"))
        if not date_str and row.get("core_variable") in {"PatientFollowUp.patientFollowUpDate", "PatientFollowUp.lastContact"}:
            date_str = to_str(row.get("value"))
        dt = parse_date_any(date_str)
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                rid = int(row.get("record_id"))
                candidates.append((delta, rid))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    rows: List[Dict[str, Any]] = []

    if group_record_id is None:
        # allocate a new group id
        group_record_id = _next_record_id(excel_data, staged_rows)
        # create PatientFollowUp.patient reference in the new group
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "PatientFollowUp.patient",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    # Always add the AWD (metastatic) status row (concept 2000100075)
    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "PatientFollowUp.statusAtLastFollowUp",
            "date_ref": date_ref,
            "value": "2000100075",
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "concept",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_clinical_stage_regional_nodes(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 93 (parameterless): Regional node metastases
    - Reuse an existing ClinicalStage group within ±14 days of the note date.
    - Otherwise create a new group (record_id) and add ClinicalStage.diagnosisReference with the patient id.
    - Always add ClinicalStage.regionalNodalMetastases = True in that group.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx.get("date")
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_cs(cv: Any) -> bool:
        return to_str(cv).startswith("ClinicalStage.")

    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series) -> None:
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_cs(row.get("core_variable")):
            return
        dt = parse_date_any(to_str(row.get("date_ref")))
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                rid = int(row.get("record_id"))
                candidates.append((delta, rid))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    rows: List[Dict[str, Any]] = []

    if group_record_id is None:
        group_record_id = _next_record_id(excel_data, staged_rows)
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "ClinicalStage.diagnosisReference",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    rows.append(
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "ClinicalStage.regionalNodalMetastases",
            "date_ref": date_ref,
            "value": True,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "boolean",
            "record_id": group_record_id,
        }
    )

    return rows


def handle_clinical_stage_distant_metastases(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 94: Distant metastases (with organ selection)
    - Reuse ClinicalStage group within ±14 days, else create a new one and add ClinicalStage.diagnosisReference.
    - For each selected organ, add the corresponding ClinicalStage.* boolean = True.
    """
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]
    excel_data: pandas.DataFrame | None = ctx.get("excel_data")
    staged_rows: List[Dict[str, Any]] = ctx.get("staged_rows", [])
    match = ctx.get("match")

    annotation_dt = parse_date_any(to_str(date_ref))

    def is_cs(cv: Any) -> bool:
        return to_str(cv).startswith("ClinicalStage.")

    # Find existing ClinicalStage group within ±14 days
    candidates: List[tuple[int, int]] = []  # (abs_days, record_id)

    def consider_row(row: Dict[str, Any] | pandas.Series) -> None:
        if to_str(row.get("patient_id")) != to_str(patient_id):
            return
        if not is_cs(row.get("core_variable")):
            return
        dt = parse_date_any(to_str(row.get("date_ref")))
        if not dt or not annotation_dt:
            return
        delta = abs((annotation_dt - dt).days)
        if delta <= 14:
            try:
                candidates.append((delta, int(row.get("record_id"))))
            except (TypeError, ValueError):
                return

    if isinstance(excel_data, pandas.DataFrame) and not excel_data.empty:
        for _, r in excel_data.iterrows():
            consider_row(r)
    for r in staged_rows:
        consider_row(r)

    group_record_id: int | None = None
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1]))
        group_record_id = candidates[0][1]

    rows: List[Dict[str, Any]] = []

    # If no nearby group, create a new one and add ClinicalStage.diagnosisReference
    if group_record_id is None:
        group_record_id = _next_record_id(excel_data, staged_rows)
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": "ClinicalStage.diagnosisReference",
                "date_ref": date_ref,
                "value": patient_id,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "reference",
                "record_id": group_record_id,
            }
        )

    # Map selected organs to ClinicalStage variables
    site_var_map = {
        "lung": "ClinicalStage.lung",
        "liver": "ClinicalStage.liver",
        "brain": "ClinicalStage.brain",
        "bone": "ClinicalStage.metastasisatbone",
        "soft tissue": "ClinicalStage.softTissue",
        "other": "ClinicalStage.otherViscera",
        "unknown": "ClinicalStage.unknown",
    }

    selection_raw = _match_value(match, 0)
    tokens = []
    if selection_raw:
        for token in re.split(r",|;|/| and ", to_str(selection_raw)):
            t = to_str(token).strip().lower().strip(". ")
            if not t:
                continue
            t = re.sub(r"^(in|to|at|on|the)\s+", "", t)
            if "soft tissue" in t:
                t = "soft tissue"
            elif t.endswith("s") and t[:-1] in {"lung", "bone", "liver", "brain"}:
                t = t[:-1]
            elif "other" in t and "unknown" not in t:
                t = "other"
            elif "unknown" in t:
                t = "unknown"
            tokens.append(t)

    # Deduplicate while preserving order
    seen: set[str] = set()
    normalized_sites: List[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            normalized_sites.append(t)

    # If nothing parsed, nothing to add
    for site in normalized_sites:
        var = site_var_map.get(site)
        if not var:
            continue
        rows.append(
            {
                "patient_id": patient_id,
                "original_source": "NLP_LLM",
                "core_variable": var,
                "date_ref": date_ref,
                "value": True,
                "note_id": note_id,
                "prompt_type": prompt_type,
                "types": "boolean",
                "record_id": group_record_id,
            }
        )

    return rows


def handle_biopsy_mitotic_count_hpf(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 187: Biopsy mitotic count: [mitoses count]/[number of HPFs]HPF
    Emit a single Diagnosis.biopsyMitoticCount row combining both parameters as '<count>/<HPF>HPF'.
    """
    match = ctx.get("match")
    patient_id = ctx["patient_id"]
    date_ref = ctx.get("date")
    note_id = ctx.get("note_id")
    prompt_type = ctx.get("prompt_type")

    mitoses = _match_value(match, 0)
    hpf = _match_value(match, 1)
    if not mitoses or not hpf:
        return []

    # Normalize numbers
    mitoses_num = re.findall(r"\d+\.?\d*", to_str(mitoses))
    hpf_num = re.findall(r"\d+\.?\d*", to_str(hpf))
    if not mitoses_num or not hpf_num:
        return []

    value = f"{mitoses_num[0]}/{hpf_num[0]}HPF"

    return [
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "Diagnosis.biopsyMitoticCount",
            "date_ref": date_ref,
            "value": value,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "string",
        }
    ]


def handle_biopsy_mitotic_count_mm2(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Annotation 188: Biopsy mitotic count: [mitoses count]/[area]mm2
    Normalize to Number per 10 HPF (equivalent to per 1 mm2).
    Emits Diagnosis.biopsyMitoticCount as '<normalized>/10HPF'.
    """
    match = ctx.get("match")
    patient_id = ctx["patient_id"]
    date_ref = ctx["date"]
    note_id = ctx["note_id"]
    prompt_type = ctx["prompt_type"]

    mitoses_raw = _match_value(match, 0)
    area_raw = _match_value(match, 1)
    if not mitoses_raw or not area_raw:
        return []

    m_nums = re.findall(r"\d+\.?\d*", to_str(mitoses_raw))
    a_nums = re.findall(r"\d+\.?\d*", to_str(area_raw))
    if not m_nums or not a_nums:
        return []

    try:
        mitoses = float(m_nums[0])
        area_mm2 = float(a_nums[0])
        if area_mm2 <= 0:
            return []
        per_mm2 = mitoses / area_mm2  # per 1 mm2 == per 10 HPF
    except Exception:
        return []

    # Format nicely: integer if whole, else up to 2 decimals without trailing zeros
    if per_mm2.is_integer():
        value_num = str(int(per_mm2))
    else:
        value_num = f"{per_mm2:.2f}".rstrip("0").rstrip(".")

    value = f"{value_num}/10HPF"

    return [
        {
            "patient_id": patient_id,
            "original_source": "NLP_LLM",
            "core_variable": "Diagnosis.biopsyMitoticCount",
            "date_ref": date_ref,
            "value": value,
            "note_id": note_id,
            "prompt_type": prompt_type,
            "types": "string",
        }
    ]


SPECIAL_HANDLERS: Dict[str, Handler] = {
    "61": handle_weight_height_bmi,
    "63": handle_genetic_syndromes,
    "64": handle_no_genetic_syndrome,
    "76": handle_radiotherapy_induced_sarcoma,
    "91": handle_localized_stage,
    "92": handle_loco_regional,
    "217": handle_radiotherapy_site,
    "261": handle_radiotherapy_site,
    "242": handle_disease_extent_progression,
    "225": handle_patient_followup_dod,
    "227": handle_patient_followup_duc,
    "230": handle_patient_followup_awd_nodes,
    "231": handle_patient_followup_awd_metastatic,
    "93": handle_clinical_stage_regional_nodes,
    "94": handle_clinical_stage_distant_metastases,
    "187": handle_biopsy_mitotic_count_hpf,
    "188": handle_biopsy_mitotic_count_mm2,  # new
}

SPECIAL_HANDLERS_AFTER: Dict[str, Handler] = {
    "211": handle_ilp_drugs,
    "241": handle_episode_event_link,
    "219": handle_regional_deep_hyperthermia_link,
    "226": handle_patient_followup_doc,
    "228": handle_patient_followup_ned,
    "229": handle_patient_followup_awd_local,
}
