#!/usr/bin/env python3
"""Step 1: build a draft mapping CSV from codebook node_sentences to prompt_types.

For each English-codebook entry (dict_id=199), score keyword matches against the
center's prompt names in prompts.json. Output mapping_msci.csv for manual review
before step 3 consumes it.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Allow running as a script: add this directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGLISH_DICT_ID, load_codebook, resolve_glob, stderr  # noqa: E402


# ---------- Keyword extraction ----------

# Lowercased prompt names get split on these:
_NAME_SPLIT_RE = re.compile(r"[-_ ]+")

# Very common English words that wouldn't help disambiguate prompt_types;
# stripping them keeps single-letter / generic keywords out of the match set.
_STOPWORDS = {
    "of", "the", "a", "an", "at", "in", "on", "to", "for", "and", "or",
    "is", "be", "was", "were", "patient", "patients", "select", "put",
    "pick", "provide", "type", "value", "date", "specify",
}


def _tokenize_prompt_name(name: str) -> set[str]:
    """E.g. 'patient-weightheight' -> {'patient', 'weightheight'}."""
    parts = _NAME_SPLIT_RE.split(name.lower())
    return {p for p in parts if p and p not in _STOPWORDS}


def _entity_keywords(entity_mapping: dict) -> set[str]:
    """Pull plausible keywords from entity_mapping.entity_type and field_mappings.

    e.g. 'Patient.sex' -> {'patient', 'sex'}; field_name='diameter' -> {'diameter'}.
    """
    out: set[str] = set()
    et = entity_mapping.get("entity_type") or ""
    for piece in re.split(r"[.\s_-]+", et.lower()):
        if piece and piece not in _STOPWORDS:
            out.add(piece)
    for fm in entity_mapping.get("field_mappings") or []:
        fn = (fm.get("field_name") or "").lower()
        if fn and fn not in _STOPWORDS:
            out.add(fn)
    return out


@dataclass
class PromptKeywords:
    prompt_type: str
    keywords: set[str]


def build_keyword_index(prompts_for_center: dict) -> list[PromptKeywords]:
    """For each prompt_type, derive a keyword set used to match codebook sentences."""
    out: list[PromptKeywords] = []
    for prompt_type, prompt_def in prompts_for_center.items():
        keywords = _tokenize_prompt_name(prompt_type)
        em = prompt_def.get("entity_mapping") or {}
        keywords.update(_entity_keywords(em))
        # Add manual aliases for prompt names where the tokenization misses the
        # natural English term used in the codebook. These are narrow nudges,
        # not a full ontology — extend as needed.
        aliases = _PROMPT_ALIASES.get(prompt_type, set())
        keywords.update(aliases)
        # Drop short tokens (1-2 chars) — they cause spurious matches.
        keywords = {k for k in keywords if len(k) >= 3}
        out.append(PromptKeywords(prompt_type=prompt_type, keywords=keywords))
    return out


# Narrow aliases for prompt names whose natural English term doesn't appear in
# the prompt_type itself or its entity_mapping. Keep this conservative — bad
# aliases produce false matches, which is worse than no match.
_PROMPT_ALIASES: dict[str, set[str]] = {
    "gender": {"gender", "sex"},
    "tumorsite": {"site", "tumor"},
    "tumordiameter": {"diameter"},
    "histological": {"histological", "histology"},
    "biopsygrading": {"grading", "biopsy"},
    "biopsymitoticcount": {"mitotic", "biopsy"},
    "tumorbiopsytype": {"biopsy"},
    "ageatdiagnosis": {"age", "diagnosis"},
    "stage_at_diagnosis": {"stage"},
    "patient-bmi": {"bmi"},
    "patient-weightheight": {"weight", "height"},
    "patient-status": {"status", "follow-up", "alive", "dead"},
    "chemotherapy_start": {"chemotherapy", "started"},
    "chemotherapy_end": {"chemotherapy", "ended"},
    "radiotherapy_start": {"radiotherapy", "started"},
    "radiotherapy_end": {"radiotherapy", "ended"},
    "surgerytype": {"surgery"},
    "surgerymargins": {"margins"},
    "necrosis_in_surgical": {"necrosis", "surgical"},
    "necrosis_in_biopsy": {"necrosis", "biopsy"},
    "recurrencetype": {"recurrence", "progression"},
    "recur_or_prog": {"recurrence", "progression", "event"},
    "occurrence_cancer": {"occurrence", "cancer"},
    "previous_cancer_treatment": {"previous", "treatment"},
    "last_contact_date": {"contact", "follow-up"},
}


# ---------- Scoring ----------


@dataclass
class MatchResult:
    prompt_type: str
    confidence: str  # high | medium | none
    notes: str


def score_sentence(sentence: str, index: list[PromptKeywords]) -> MatchResult:
    """Return the best-matching prompt_type for a codebook sentence."""
    s = sentence.lower()
    hits: Counter[str] = Counter()
    matched_kw: dict[str, list[str]] = {}
    for pk in index:
        local_matches = [k for k in pk.keywords if re.search(rf"\b{re.escape(k)}\b", s)]
        if local_matches:
            hits[pk.prompt_type] = len(local_matches)
            matched_kw[pk.prompt_type] = local_matches
    if not hits:
        return MatchResult(prompt_type="", confidence="none", notes="no keyword match")

    top = hits.most_common()
    best_prompt, best_count = top[0]
    runner_up_count = top[1][1] if len(top) > 1 else 0
    keywords_used = ", ".join(matched_kw[best_prompt])

    # high: unique winner with multiple hits, OR sole match
    if runner_up_count == 0 or best_count >= 2 and best_count > runner_up_count:
        confidence = "high"
    elif best_count > runner_up_count:
        confidence = "medium"
    else:
        # Tie at the top — ambiguous, demote to medium and note the tie
        confidence = "medium"
        tied = [p for p, c in top if c == best_count]
        keywords_used += f"; tied with: {', '.join(tied[1:])}"

    return MatchResult(
        prompt_type=best_prompt,
        confidence=confidence,
        notes=f"keywords: {keywords_used}",
    )


# ---------- IO ----------


def write_mapping_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["node_id", "node_sentence", "suggested_prompt_type", "confidence", "notes"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--codebook", required=True, help="Path or glob to data_items_def_*.json")
    ap.add_argument("--prompts", required=True, help="Path to backend/data/prompts/prompts.json")
    ap.add_argument("--center", required=True, help="Center key in prompts.json (e.g. MSCI)")
    ap.add_argument("--out", required=True, help="Output mapping CSV path")
    ap.add_argument("--force", action="store_true", help="Overwrite existing output (loses manual edits)")
    args = ap.parse_args(argv)

    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        stderr(
            f"ERROR: {out_path} already exists. Use --force to overwrite "
            f"(this will discard manual edits)."
        )
        return 1

    try:
        codebook_path = resolve_glob(args.codebook)
    except (FileNotFoundError, ValueError) as e:
        stderr(f"ERROR: {e}")
        return 1

    with open(args.prompts, "r", encoding="utf-8") as f:
        prompts_all = json.load(f)
    if args.center not in prompts_all:
        stderr(f"ERROR: center '{args.center}' not in prompts.json (have: {list(prompts_all.keys())})")
        return 1
    prompts_for_center = prompts_all[args.center]

    codebook = load_codebook(codebook_path)
    if not any(k[0] == ENGLISH_DICT_ID for k in codebook):
        stderr(f"ERROR: codebook has zero dict_id={ENGLISH_DICT_ID} entries — wrong file?")
        return 1

    index = build_keyword_index(prompts_for_center)

    counts = Counter()
    rows: list[dict] = []
    filtered_non_english = 0
    for (dict_id, node_id), entry in codebook.items():
        if dict_id != ENGLISH_DICT_ID:
            filtered_non_english += 1
            continue
        result = score_sentence(entry.node_sentence, index)
        counts[result.confidence] += 1
        rows.append({
            "node_id": entry.node_id,
            "node_sentence": entry.node_sentence,
            "suggested_prompt_type": result.prompt_type,
            "confidence": result.confidence,
            "notes": result.notes,
        })

    # Sort: none first (need attention), then medium, then high; secondary by sentence
    confidence_order = {"none": 0, "medium": 1, "high": 2}
    rows.sort(key=lambda r: (confidence_order.get(r["confidence"], 99), r["node_sentence"]))

    write_mapping_csv(out_path, rows)
    stderr(
        f"{filtered_non_english + len(rows)} codebook entries scanned\n"
        f"  → {filtered_non_english} filtered (non-English dicts)\n"
        f"  → {len(rows)} in dict_id={ENGLISH_DICT_ID}\n"
        f"       {counts.get('high', 0)} high confidence\n"
        f"       {counts.get('medium', 0)} medium confidence\n"
        f"       {counts.get('none', 0)} none — manual mapping required\n"
        f"Output: {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
