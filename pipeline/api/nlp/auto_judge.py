#!/usr/bin/env python3
"""
Rule-based auto-judge for IDEA4RC NLP extractions.

Returns C / W / NA / D per sub-field for any (gold, predicted) pair.

  C  = clinically correct (after applying the equivalence rules)
  W  = clinically wrong
  NA = sub-field not applicable for this row (gold has a placeholder)
  D  = gold is itself malformed (handled per-row by caller)

Validated against the manual verdicts in
  docs/reports/INT-SARC/artifacts/judge_verdicts*.csv

Run as a script to compute agreement on every existing INT-SARC run.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Optional

NLP_DIR = Path(__file__).resolve().parent
from _report_paths import ARTIFACTS_DIR  # noqa: E402


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace, drop punctuation noise."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[“”‘’\"']", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _strip_label_prefix(text: str) -> str:
    """Strip the leading 'Label: ' prefix from a template-style annotation."""
    if not text:
        return text
    # e.g. 'Patient's gender female' -> 'female';  'Biopsy grading (FNCLCC): 3' -> '3'
    m = re.match(r"^[^:]+:\s*(.+)$", text.strip())
    return m.group(1).strip() if m else text.strip()


PLACEHOLDER_RE = re.compile(
    r"\[(select|put|provide|pick|choose)[^\]]*\]|\[(value|date|select)\]",
    re.IGNORECASE,
)


def _is_placeholder(text: str) -> bool:
    return bool(text) and bool(PLACEHOLDER_RE.search(text))


def _strip_placeholders(text: str) -> str:
    return PLACEHOLDER_RE.sub("", text or "").strip().rstrip(".,:; ").strip()


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

# Match dates in many common formats. Returns (day, month, year) tuples,
# any of which may be None for partial dates.
_DATE_PATTERNS = [
    # 27/09/2019, 27-09-2019, 27.09.2019
    re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b"),
    # 27/9/19, 27-9-19, 27.9.19 (2-digit year — assume 20xx)
    re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2})\b"),
    # 2019-10-11 (ISO)
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
    # 06/2019, 06-2019, 06.2019
    re.compile(r"\b(\d{1,2})[/.\-](\d{4})\b"),
    # 01/15/2018 (US-format gold typos)
    # handled by the first pattern too — interpretation done in extract
]


def _try_int(s: str | None) -> int | None:
    try:
        return int(s) if s is not None else None
    except (ValueError, TypeError):
        return None


def extract_dates(text: str) -> list[tuple[int | None, int | None, int | None]]:
    """Return list of (day, month, year) tuples found in text.
    Partial dates use None for missing components.
    Year < 100 is treated as 20YY (clinical notes are post-2000).
    """
    if not text:
        return []
    found: list[tuple[int | None, int | None, int | None]] = []

    # ISO format yyyy-mm-dd
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            found.append((d, mo, y))

    # dd/mm/yyyy (also dd-mm-yyyy, dd.mm.yyyy)
    for m in re.finditer(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b", text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Heuristic: if first component > 12, it's definitely a day
        # If second > 12, it's a US-style mm/dd swap
        if mo > 12 and d <= 12:
            d, mo = mo, d  # try swap (handles US mm/dd/yyyy)
        # Gold sometimes has typos like "21/06/1029" — accept any 4-digit year
        found.append((d, mo, y))

    # dd/mm/yy (2-digit year)
    for m in re.finditer(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2})(?!\d)", text):
        d, mo, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = 2000 + y2 if y2 < 70 else 1900 + y2
        if mo > 12 and d <= 12:
            d, mo = mo, d
        found.append((d, mo, y))

    # mm/yyyy partial date
    for m in re.finditer(r"\b(\d{1,2})[/.\-](\d{4})\b", text):
        mo, y = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and (None, mo, y) not in [(p[0], p[1], p[2]) for p in found]:
            found.append((None, mo, y))

    return found


def dates_match(gold: str, pred: str) -> bool:
    """True if any pred date is consistent with any gold date.
    Partial dates match more specific ones (06/2019 ≡ 21/06/2019).
    """
    g_dates = extract_dates(gold)
    p_dates = extract_dates(pred)
    if not g_dates or not p_dates:
        return False
    for gd, gm, gy in g_dates:
        for pd, pm, py in p_dates:
            # Year must match (allow gold typos like 1029 → assume meant 2019)
            gy_norm = 2000 + gy % 100 if gy and gy < 1900 else gy
            py_norm = 2000 + py % 100 if py and py < 1900 else py
            if gy and py and gy_norm != py_norm:
                continue
            # Month must match (allow None on one side)
            if gm and pm and gm != pm:
                continue
            # Day: allow None on either side; if both present they must match
            if gd and pd and gd != pd:
                continue
            return True
    return False


# ---------------------------------------------------------------------------
# Enum / vocabulary judges
# ---------------------------------------------------------------------------

GENDER_SYNS = {
    "male":   ["male", "maschio", "il paziente", "il pz"],
    "female": ["female", "femmina", "donna", "la paziente", "la pz"],
}


def _gender_of(text: str) -> Optional[str]:
    """Return 'male' / 'female' / None using word-boundary match."""
    t = _norm(text)
    for label, syns in GENDER_SYNS.items():
        for s in syns:
            if re.search(rf"\b{re.escape(s)}\b", t):
                return label
    return None


def judge_gender(gold: str, pred: str) -> str:
    if _is_placeholder(pred) or not pred:
        return "W"
    g = _gender_of(gold)
    p = _gender_of(pred)
    if g is None or p is None:
        return "W"
    return "C" if g == p else "W"


def judge_age(gold: str, pred: str) -> str:
    g_age = re.search(r"\b(\d{1,3})\s*(years|year|anni)\b", gold or "", re.I)
    p_age = re.search(r"\b(\d{1,3})\s*(years|year|anni)\b", pred or "", re.I)
    if not g_age or not p_age:
        # fallback: any 1-3 digit number
        g_nums = re.findall(r"\b(\d{1,3})\b", gold or "")
        p_nums = re.findall(r"\b(\d{1,3})\b", pred or "")
        return "C" if g_nums and p_nums and g_nums[0] == p_nums[0] else "W"
    return "C" if g_age.group(1) == p_age.group(1) else "W"


FNCLCC_GRADE_RE = re.compile(r"\b([123])\b")


def judge_fnclcc(gold: str, pred: str) -> str:
    g = FNCLCC_GRADE_RE.search(_strip_label_prefix(gold))
    p = FNCLCC_GRADE_RE.search(_strip_label_prefix(pred))
    if not p:
        return "W"
    if g and p and g.group(1) == p.group(1):
        return "C"
    return "W"


def judge_margins(gold: str, pred: str) -> str:
    g = re.search(r"\bR([012])\b", gold or "", re.I)
    p = re.search(r"\bR([012])\b", pred or "", re.I)
    if not g or not p:
        # bare value 0/1/2 sometimes (backend final_output)
        gn = re.search(r"\b([012])\b", _strip_label_prefix(gold))
        pn = re.search(r"\b([012])\b", _strip_label_prefix(pred))
        return "C" if gn and pn and gn.group(1) == pn.group(1) else "W"
    return "C" if g.group(1).upper() == p.group(1).upper() else "W"


def judge_tumordiameter(gold: str, pred: str) -> str:
    # Match number+unit; gold sometimes has "110 mm" or "150mm"; allow both
    g_val = re.search(r"(\d{1,4})\s*mm", gold or "", re.I)
    p_val = re.search(r"(\d{1,4})\s*mm", pred or "", re.I)
    if not g_val or not p_val:
        return "W"
    return "C" if g_val.group(1) == p_val.group(1) else "W"


# ---------------------------------------------------------------------------
# Histology and tumour site
# ---------------------------------------------------------------------------

HISTOLOGY_EQUIV = {
    # Map of Italian/English/abbreviation forms to canonical concept
    "leiomyosarcoma":        {"leiomyosarcoma", "leiomiosarcoma", "lms"},
    "myxoid_liposarcoma":    {"myxoid liposarcoma", "mixoid liposarcoma", "liposarcoma mixoide", "liposarcoma mixoid"},
    "undifferentiated":      {"undifferentiated sarcoma", "sarcoma indifferenziato", "undifferentiated", "indifferenziato"},
    "pecoma":                {"pecoma", "pecomas", "perivascular epithelioid cell tumor", "perivascular epithelioid cell tumour"},
    "spindle_cell":          {"spindle cell sarcoma", "sarcoma a cellule fusate"},
    "sarcoma_nos":           {"sarcoma nos", "sarcoma not otherwise specified", "soft tissue sarcoma nos"},
}


def _canonical_histology(text: str) -> Optional[str]:
    t = _norm(_strip_label_prefix(text))
    for canonical, forms in HISTOLOGY_EQUIV.items():
        if any(f in t for f in forms):
            return canonical
    return None


def judge_histology(gold: str, pred: str) -> str:
    g_canon = _canonical_histology(gold)
    p_canon = _canonical_histology(pred)
    # If gold and pred map to the same canonical histology, correct.
    if g_canon and p_canon and g_canon == p_canon:
        return "C"
    # ICD-O-3 morphology code as a fallback (PDF says don't trust LLM ICDs)
    g_icd = re.search(r"\b(\d{4})/\d\b", gold or "")
    p_icd = re.search(r"\b(\d{4})/\d\b", pred or "")
    if g_icd and p_icd and g_icd.group(1) == p_icd.group(1):
        return "C"
    return "W"


# Tumour-site equivalence: per PDF, name match is what matters
SITE_EQUIV = {
    "thigh":      {"thigh", "coscia", "upper leg"},
    "leg":        {"leg", "gamba"},
    "buttock":    {"buttock", "gluteus", "gluteo", "natica"},
    "bladder":    {"bladder", "vescica"},
    "uterus":     {"uterus", "utero"},
    "thoracic_wall": {"thoracic wall", "parete toracica"},
    "wall_generic":  {"wall"},  # vaguer; only matches if specific site missing
}


# Rows where the gold annotation is itself malformed (mislabelled, missing
# crucial fields). These are excluded from accuracy calculations across all
# runs and are flagged separately. Keyed by (note_id_suffix, prompt_type).
KNOWN_GOLD_ISSUES = {
    # Anamnesis chemo start prompt with end-of-chemo text
    ("ds_ana_remota|163235|423557", "chemotherapy_start-int"),
    # patient-status rows where gold has only the date, no status
    # (multiple notes — handled by the lambda returning "D" in JUDGES)
    # radiotherapy_start prompt with a response annotation as gold
    ("MULTI_SAR_Visita|ds_ana_remota|60|538752", "radiotherapy_start-int"),
}


def _is_known_gold_issue(note_id: str, prompt_type: str) -> bool:
    for suffix, pt in KNOWN_GOLD_ISSUES:
        if pt == prompt_type and suffix in (note_id or ""):
            return True
    return False


# INT-SARC: rows where the gold annotation is malformed. Identified by row
# index in /tmp/judge_pairs_*.json (which is stable across runs because the
# extraction loop is deterministic). These row idx values map to:
#   10 → chemotherapy_start with end-of-chemo gold text (patient 999676)
#   29 → patient-status with only a date in gold (no status)
#   55 → patient-status with only a date in gold
#   64 → radiotherapy_start with a response annotation as gold (patient 1008936)
INT_SARC_GOLD_ISSUE_IDX = {10, 29, 55, 64}


def _site_canon(text: str) -> Optional[str]:
    t = _norm(_strip_label_prefix(text))
    # Strip ICD codes
    t = re.sub(r"\(icd-o-?3:[^)]+\)", "", t).strip().rstrip(".")
    for canon, forms in SITE_EQUIV.items():
        if any(re.search(rf"\b{re.escape(f)}\b", t) for f in forms):
            return canon
    return None


SITE_CATEGORIES = (
    "trunk wall", "upper and lower limbs", "genito urinary",
    "head and neck", "intra abdominal", "breast", "other",
)


def _site_category(text: str) -> Optional[str]:
    t = _norm(text)
    for cat in SITE_CATEGORIES:
        if cat in t:
            return cat
    return None


def judge_tumorsite(gold: str, pred: str) -> str:
    g_site = _site_canon(gold)
    p_site = _site_canon(pred)
    # Site detail must match (e.g. Buttock ≡ Gluteus). If gold has a specific
    # site, pred must match it.
    if g_site and p_site and g_site == p_site:
        # Check category too — Buttock-in-trunk-wall is wrong if gold says
        # Buttock-in-limbs. PDF was lenient on category mistakes, so we accept
        # category mismatch as long as the specific site name matches.
        return "C"
    if g_site and not p_site:
        return "W"
    if not g_site:
        # No canonical site in gold; fall back to substring on cleaned text
        g_clean = re.sub(r"\(icd-o-?3:[^)]+\)", "", _norm(_strip_label_prefix(gold))).strip().rstrip(".")
        p_clean = re.sub(r"\(icd-o-?3:[^)]+\)", "", _norm(_strip_label_prefix(pred))).strip().rstrip(".")
        if g_clean and p_clean and (g_clean == p_clean or g_clean in p_clean or p_clean in g_clean):
            return "C"
    return "W"


# ---------------------------------------------------------------------------
# Mitotic count
# ---------------------------------------------------------------------------

def judge_mitotic_count(gold: str, pred: str) -> str:
    g_val = re.search(r"(\d{1,3})\s*/\s*\d+\s*(hpf|mm2|mm\^2)", (gold or "").lower())
    p_val = re.search(r"(\d{1,3})\s*/\s*\d+\s*(hpf|mm2|mm\^2)", (pred or "").lower())
    if g_val and p_val and g_val.group(1) == p_val.group(1):
        return "C"
    # Fallback: any number before /
    g_n = re.search(r"(\d{1,3})\s*/", gold or "")
    p_n = re.search(r"(\d{1,3})\s*/", pred or "")
    if g_n and p_n and g_n.group(1) == p_n.group(1):
        return "C"
    return "W"


# ---------------------------------------------------------------------------
# Stage, response, recurrence-type single-value
# ---------------------------------------------------------------------------

STAGE_SYNS = {
    "localized":         {"localized", "localised", "localizzato"},
    "loco_regional":     {"loco-regional", "locoregional"},
    "distant_lung":      {"distant metastases (lung)", "metastatic (lung)"},
    "distant_other":     {"distant metastases (other)", "distant metastases"},
    "distant_nodal":     {"distant metastases (regional nodal", "metastatic (regional nodal"},
    "unknown":           {"unknown stage at diagnosis", "unknown"},
}


def judge_stage(gold: str, pred: str) -> str:
    g = _norm(_strip_label_prefix(gold))
    p = _norm(_strip_label_prefix(pred))
    for forms in STAGE_SYNS.values():
        if any(f in g for f in forms) and any(f in p for f in forms):
            return "C"
    return "W"


RESPONSE_VALUES = {"complete response", "partial response", "stable disease", "progression"}


def judge_response_to(gold: str, pred: str) -> str:
    g = _norm(gold)
    p = _norm(pred)
    g_val = next((v for v in RESPONSE_VALUES if v in g), None)
    p_val = next((v for v in RESPONSE_VALUES if v in p), None)
    if not p_val:
        return "W"
    return "C" if g_val == p_val else "W"


def judge_recurrencetype(gold: str, pred: str) -> str:
    """Multi-field: type (local/metastatic) + site_detail."""
    g = _norm(_strip_label_prefix(gold))
    p = _norm(_strip_label_prefix(pred))
    if not p or p in {"none", ""}:
        return "W"
    g_local = "local" in g and "metastatic" not in g
    g_meta = "metastatic" in g
    p_local = "local" in p and "metastatic" not in p
    p_meta = "metastatic" in p
    if g_local != p_local or g_meta != p_meta:
        return "W"
    # Type matches; check site detail if gold has one
    SITES = {"soft tissue", "bone", "lung", "liver", "pelvic"}
    g_sites = {s for s in SITES if s in g}
    p_sites = {s for s in SITES if s in p}
    if g_sites and not p_sites:
        return "W"  # site detail missing
    return "C"


def judge_recur_or_prog(gold: str, pred: str) -> str:
    """Type (recurrence/progression/no-event) + date."""
    g = _norm(gold)
    p = _norm(pred)
    g_recur = "recurrence" in g and "no progression" not in g and "no recurrence" not in g
    g_prog = "progression" in g and "no progression" not in g
    g_none = "no progression/recurrence" in g or "no progression / recurrence" in g
    p_recur = "recurrence" in p and "no progression" not in p and "no recurrence" not in p
    p_prog = "progression" in p and "no progression" not in p
    p_none = "no progression/recurrence" in p or "no progression / recurrence" in p
    if (g_recur, g_prog, g_none) != (p_recur, p_prog, p_none):
        return "W"
    # Type matches; check date
    if not dates_match(gold, pred):
        return "W"
    return "C"


# ---------------------------------------------------------------------------
# Multi-field templates: surgery, chemo, radiotherapy
# ---------------------------------------------------------------------------

def _has_setting(text: str, settings: tuple[str, ...]) -> Optional[str]:
    t = _norm(text)
    for s in settings:
        if s in t:
            return s
    return None


CHEMO_SETTINGS = ("pre-operative", "post-operative", "therapeutic (without surgery)")
RT_SETTINGS = ("pre-operative", "post-operative", "therapeutic (radiotherapy without surgery)")


def judge_setting(gold: str, pred: str, settings=CHEMO_SETTINGS) -> str:
    g = _has_setting(gold, settings)
    p = _has_setting(pred, settings)
    if not p or _is_placeholder(pred):
        return "W"
    return "C" if g == p else "W"


def judge_completeness(gold: str, pred: str) -> str:
    g = _norm(gold)
    p = _norm(pred)
    g_val = "complete" if "macroscopically complete" in g else (
        "incomplete" if "macroscopically incomplete" in g else None
    )
    p_val = "complete" if "macroscopically complete" in p else (
        "incomplete" if "macroscopically incomplete" in p else None
    )
    if g_val is None or "[select result]" in g:
        return "NA"  # gold itself abstains
    if p_val is None:
        return "W"  # pred has placeholder or missing
    return "C" if g_val == p_val else "W"


def judge_date_in(gold: str, pred: str) -> str:
    """Date sub-field judge for multi-field templates."""
    # Only NA when there's no extractable date in gold (other placeholders
    # like [select place] don't invalidate the date check).
    if not extract_dates(gold) or "[put date]" in (gold or "").lower() or "[provide date]" in (gold or "").lower():
        return "NA"
    if not extract_dates(pred):
        return "W"
    return "C" if dates_match(gold, pred) else "W"


# Drug equivalences (Italian → English, common combos)
DRUG_EQUIV = {
    "doxorubicin":   {"doxorubicin", "adriamicina", "adriamycin"},
    "dacarbazine":   {"dacarbazine", "dacarbazina"},
    "ifosfamide":    {"ifosfamide", "ifosfamide"},
    "epirubicin":    {"epirubicin", "epirubicina"},
    "gemcitabine":   {"gemcitabine", "gemcitabina"},
    "trabectedin":   {"trabectedin", "trabectedina"},
    "sirolimus":     {"sirolimus", "rapamicina"},
}


def _drugs_in(text: str) -> set[str]:
    t = _norm(text)
    found = set()
    for canon, syns in DRUG_EQUIV.items():
        if any(s in t for s in syns):
            found.add(canon)
    return found


def judge_regimen(gold: str, pred: str) -> str:
    g_drugs = _drugs_in(gold)
    p_drugs = _drugs_in(pred)
    if not g_drugs:
        return "NA"
    if not p_drugs:
        return "W"
    # Same set of drugs (order-agnostic, separator-agnostic)
    return "C" if g_drugs == p_drugs else "W"


def judge_intent(gold: str, pred: str) -> str:
    INTENT_VALUES = {"curative", "palliative", "life expectancy prolongation",
                     "adjuvant", "neoadjuvant", "prolongation of life"}
    g = _norm(gold)
    p = _norm(pred)
    g_val = next((v for v in INTENT_VALUES if v in g), None)
    if g_val is None:
        return "NA"
    p_val = next((v for v in INTENT_VALUES if v in p), None)
    if p_val is None:
        return "W"
    # Treat 'life expectancy prolongation' ≡ 'prolongation of life'
    norm_map = {"prolongation of life": "life expectancy prolongation"}
    return "C" if norm_map.get(g_val, g_val) == norm_map.get(p_val, p_val) else "W"


REASON_VALUES = {"completion", "progression", "toxicity", "unknown",
                 "treatment completion", "disease progression", "tumor progression"}


def judge_reason(gold: str, pred: str) -> str:
    g = _norm(gold)
    p = _norm(pred)
    g_val = next((v for v in REASON_VALUES if v in g), None)
    if g_val is None:
        return "NA"
    p_val = next((v for v in REASON_VALUES if v in p), None)
    if p_val is None:
        return "W"
    norm = lambda v: {"treatment completion": "completion",
                      "disease progression": "progression",
                      "tumor progression": "progression"}.get(v, v)
    return "C" if norm(g_val) == norm(p_val) else "W"


def judge_cycles(gold: str, pred: str) -> str:
    g_m = re.search(r"(\d{1,2})\s*(?:of\s*)?cycles", (gold or "").lower())
    p_m = re.search(r"(\d{1,2})\s*(?:of\s*)?cycles", (pred or "").lower())
    if "[provide number]" in (gold or "").lower() or not g_m:
        return "NA"
    if not p_m:
        return "W"
    return "C" if g_m.group(1) == p_m.group(1) else "W"


def judge_dose(gold: str, pred: str) -> str:
    g_m = re.search(r"(\d{1,3}(?:\.\d)?)\s*gy", (gold or "").lower())
    p_m = re.search(r"(\d{1,3}(?:\.\d)?)\s*gy", (pred or "").lower())
    if not g_m:
        return "NA"
    if not p_m:
        return "W"
    return "C" if g_m.group(1) == p_m.group(1) else "W"


def judge_fractions(gold: str, pred: str) -> str:
    g_m = re.search(r"in\s+(\d{1,3})\s+fractions", (gold or "").lower())
    p_m = re.search(r"in\s+(\d{1,3})\s+fractions", (pred or "").lower())
    if "[put number of]" in (gold or "").lower() or not g_m:
        return "NA"
    if not p_m:
        return "W"
    return "C" if g_m.group(1) == p_m.group(1) else "W"


def judge_hospital(gold: str, pred: str) -> str:
    HOSPITAL_VALUES = {"at the hospital", "at the hosptial", "outside of the hospital", "in int", "in the hospital"}
    g = _norm(gold)
    p = _norm(pred)
    g_val = next((v for v in HOSPITAL_VALUES if v in g), None)
    if g_val is None or "[please select where]" in g:
        return "NA"
    p_val = next((v for v in HOSPITAL_VALUES if v in p), None)
    if p_val is None:
        return "W"
    return "C" if g_val == p_val else "W"


# ---------------------------------------------------------------------------
# Surgery type label (Primary surgery vs Surgery vs Surgical procedure vs ...)
# ---------------------------------------------------------------------------

def judge_surgery_type(gold: str, pred: str) -> str:
    g = _norm(gold)
    p = _norm(pred)
    # Accept any of these as a valid type label
    VALID_TYPES = {"primary surgery", "surgery", "surgical procedure",
                   "local excision", "limb operation", "amputation",
                   "re-excision"}
    g_val = next((v for v in VALID_TYPES if v in g), None)
    p_val = next((v for v in VALID_TYPES if v in p), None)
    if g_val is None:
        return "NA"
    if p_val is None:
        return "W"
    # Treat all "surgery-flavoured" labels as equivalent — PDF used "Type" loosely
    return "C"


# ---------------------------------------------------------------------------
# Biopsy type / institution
# ---------------------------------------------------------------------------

BIOPSY_TYPES = {"core-trucut", "core trucut", "core needle", "incisional",
                "excisional", "fine needle aspiration", "fna"}


def judge_biopsy_type(gold: str, pred: str) -> str:
    g = _norm(gold)
    p = _norm(pred)
    if "[pick biopsy type]" in g or "[biopsy type]" in g:
        return "NA"
    g_val = next((v for v in BIOPSY_TYPES if v in g), None)
    if g_val is None:
        return "NA"
    p_val = next((v for v in BIOPSY_TYPES if v in p), None)
    if p_val is None:
        return "W"
    return "C"


def judge_institution(gold: str, pred: str) -> str:
    if "[select place]" in (gold or "").lower():
        return "NA"
    # Check whether the gold lists a specific institution (uncommon in our set)
    g = _norm(gold)
    p = _norm(pred)
    if not g:
        return "NA"
    return "C" if g in p or p in g else "W"


# ---------------------------------------------------------------------------
# Per-prompt dispatch
# ---------------------------------------------------------------------------

# Each prompt maps to a dict of {sub_field_name: judging_function}.
# For single-value prompts the sub-field is called 'value'.
JudgeFn = Callable[[str, str], str]

JUDGES: dict[str, dict[str, JudgeFn]] = {
    "gender-int":                    {"value": judge_gender},
    "ageatdiagnosis-int":            {"value": judge_age},
    "biopsygrading-int":             {"value": judge_fnclcc},
    "surgerymargins-int":            {"value": judge_margins},
    "surgical-mitotic-count-int":    {"value": judge_mitotic_count},
    "tumordiameter-int":             {"value": judge_tumordiameter},
    "tumorsite-int":                 {"value": judge_tumorsite},
    "histological-tipo-int":         {"value": judge_histology},
    "stage_at_diagnosis-int":        {"value": judge_stage},
    "response-to-int":               {"value": judge_response_to},
    "patient-status-int":            {"value": lambda g, p: "D"},  # gold often incomplete
    "previous_cancer_treatment-int": {"value": lambda g, p: "C" if "surgery" in _norm(g) and "surgery" in _norm(p) else "W"},
    "recurrencetype-int":            {"type": lambda g, p: judge_recurrencetype(g, p)},
    "recur_or_prog-int":             {"event_type": lambda g, p: judge_recur_or_prog(g, p)},
    "tumorbiopsytype-int": {
        "biopsy_type": judge_biopsy_type,
        "date":        judge_date_in,
        "institution": judge_institution,
    },
    "reexcision-int": {
        "date":         judge_date_in,
        "completeness": judge_completeness,
    },
    "surgerytype-fs30-int": {
        "type":         judge_surgery_type,
        "date":         judge_date_in,
        "completeness": judge_completeness,
    },
    "chemotherapy_start-int": {
        "setting": lambda g, p: judge_setting(g, p, CHEMO_SETTINGS),
        "date":    judge_date_in,
        "regimen": judge_regimen,
        "intent":  judge_intent,
    },
    "chemotherapy_end-int": {
        "setting": lambda g, p: judge_setting(g, p, CHEMO_SETTINGS),
        "date":    judge_date_in,
        "cycles":  judge_cycles,
        "reason":  judge_reason,
    },
    "radiotherapy_start-int": {
        "setting":  lambda g, p: judge_setting(g, p, RT_SETTINGS),
        "intent":   judge_intent,
        "hospital": judge_hospital,
        "date":     judge_date_in,
    },
    "radiotherapy_end-int": {
        "setting":   lambda g, p: judge_setting(g, p, RT_SETTINGS),
        "dose":      judge_dose,
        "fractions": judge_fractions,
        "date":      judge_date_in,
        "reason":    judge_reason,
    },
}


def judge_pair(gold: str, pred: str, prompt_type: str,
               note_id: str = "", idx: int | None = None) -> dict[str, str]:
    """Return {sub_field: 'C'|'W'|'NA'|'D'} for one (gold, pred) pair."""
    if _is_known_gold_issue(note_id, prompt_type):
        return {sf: "D" for sf in (JUDGES.get(prompt_type) or {"value": None})}
    if idx is not None and idx in INT_SARC_GOLD_ISSUE_IDX:
        return {sf: "D" for sf in (JUDGES.get(prompt_type) or {"value": None})}
    judges = JUDGES.get(prompt_type)
    if judges is None:
        return {"value": "?"}
    return {sf: fn(gold or "", pred or "") for sf, fn in judges.items()}


def row_verdict(sub_verdicts: dict[str, str]) -> str:
    """Collapse a sub-field verdict dict into a single row verdict (matches the
    methodology used in our manual judging)."""
    if any(v == "D" for v in sub_verdicts.values()):
        return "D"
    judged = [v for v in sub_verdicts.values() if v in {"C", "W"}]
    if not judged:
        return "D"  # everything was NA — caller decides
    return "C" if all(v == "C" for v in judged) else "W"


# ---------------------------------------------------------------------------
# Validation harness — compare auto-judge against my manual verdicts
# ---------------------------------------------------------------------------

def _load_manual_verdicts(csv_name: str):
    import pandas as pd
    df = pd.read_csv(ARTIFACTS_DIR / csv_name)
    return df


def validate_against_manual(csv_name: str) -> dict:
    """Returns dict of {prompt_type: (matched, total)} agreement counts."""
    df = _load_manual_verdicts(csv_name)
    import pandas as pd
    rows = []
    for _, r in df.iterrows():
        prompt_type = r["prompt_type"]
        gold = str(r["gold"]) if pd.notna(r["gold"]) else ""
        pred = str(r["pred"]) if pd.notna(r["pred"]) else ""
        manual = str(r["verdict"])
        # If the manual verdict has a 'note_id' column, pass it (not always present)
        note_id = str(r.get("note_id", "")) if "note_id" in r else ""
        idx = int(r["idx"]) if "idx" in r else None
        sub = judge_pair(gold, pred, prompt_type, note_id=note_id, idx=idx)
        auto = row_verdict(sub)
        rows.append({
            "idx":         r["idx"],
            "prompt_type": prompt_type,
            "manual":      manual,
            "auto":        auto,
            "match":       manual == auto,
        })

    agree = sum(1 for r in rows if r["match"])
    total = len(rows)
    print(f"=== {csv_name}: {agree}/{total} = {agree/total*100:.1f}% agreement ===")
    # Per-prompt breakdown of disagreements
    from collections import defaultdict
    disagreements = defaultdict(list)
    for r in rows:
        if not r["match"]:
            disagreements[r["prompt_type"]].append((r["idx"], r["manual"], r["auto"]))
    if disagreements:
        print(f"Disagreements ({total-agree}):")
        for pt, items in sorted(disagreements.items()):
            for idx, m, a in items:
                print(f"  idx={idx:>3}  {pt:34s}  manual={m}  auto={a}")
    return {"agree": agree, "total": total, "rows": rows}


def main() -> None:
    runs = [
        "judge_verdicts_pdf_session.csv",
        "judge_verdicts.csv",
        "judge_verdicts_backend.csv",
        "judge_verdicts_backend_v2.csv",
        "judge_verdicts_4B_pipeline.csv",
        "judge_verdicts_4B_backend.csv",
    ]
    overall_agree = 0
    overall_total = 0
    for run in runs:
        try:
            res = validate_against_manual(run)
            overall_agree += res["agree"]
            overall_total += res["total"]
            print()
        except FileNotFoundError:
            print(f"[skip] {run} not found")
    print(f"\n=== OVERALL: {overall_agree}/{overall_total} = "
          f"{overall_agree/overall_total*100:.1f}% agreement ===")


if __name__ == "__main__":
    main()
