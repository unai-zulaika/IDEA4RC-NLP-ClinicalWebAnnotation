#!/usr/bin/env python3
"""
Evaluate the same INT notes + gold annotations against the FastAPI backend
(http://localhost:8001) rather than calling vLLM directly. This exercises the
backend features that the standalone pipeline eval skips:

  * history-note splitting (note_splitter)
  * structured/guided decoding (services/structured_generator)
  * ICD-O-3 lookup (lib/icdo3_extractor + csv_indexer)
  * confidence scoring + hallucination flags
  * note-context classification

Outputs:
  pipeline/api/nlp/llm_evaluation_detailed_backend.csv  — same schema as the
    pipeline run's detailed CSV, so judge_verdicts.py can be re-pointed at it.
  pipeline/api/nlp/backend_predictions.json             — raw responses.

Prereqs:
  * 27B vLLM server on :8000
  * Backend on :8001  (cd backend && uvicorn main:app --port 8001)
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

NLP_DIR = Path(__file__).resolve().parent
REPO_ROOT = NLP_DIR.parents[2]

BACKEND = "http://localhost:8001"
NOTES_CSV = NLP_DIR / "first_patient_notes.csv"
GOLD_JSON = NLP_DIR / "annotated_patient_notes_with_spans_full_verified.json"
RTYPE_JSON = NLP_DIR / "report_type_prompt_mapping_int.json"
DETAILED_OUT = NLP_DIR / "llm_evaluation_detailed_backend_filtered.csv"
RAW_OUT = NLP_DIR / "backend_predictions_filtered.json"

REQUEST_TIMEOUT = 600  # per /annotate/process call


PROMPT_TYPES = [
    "biopsygrading-int-sarc", "surgerymargins-int-sarc", "tumordepth-int-sarc",
    "biopsymitoticcount-int-sarc", "gender-int-sarc", "reexcision-int-sarc",
    "necrosis_in_biopsy-int-sarc", "previous_cancer_treatment-int-sarc",
    "chemotherapy_start-int-sarc", "surgerytype-int-sarc", "radiotherapy_start-int-sarc",
    "recurrencetype-int-sarc", "radiotherapy_end-int-sarc", "tumorbiopsytype-int-sarc",
    "necrosis_in_surgical-int-sarc", "tumordiameter-int-sarc", "patient-status-int-sarc",
    "response-to-int-sarc", "stage_at_diagnosis-int-sarc", "chemotherapy_end-int-sarc",
    "occurrence_cancer-int-sarc", "surgical-specimen-grading-int-sarc",
    "ageatdiagnosis-int-sarc", "recur_or_prog-int-sarc", "histological-tipo-int-sarc",
    "surgical-mitotic-count-int-sarc", "tumorsite-int-sarc",
]

# Map backend prompt keys back to the pipeline's keys so gold lookup still works
# (gold annotations are mapped by pipeline's `-int` names via regex matching).
BACKEND_TO_PIPELINE: dict[str, str] = {
    "surgerytype-int-sarc": "surgerytype-fs30-int",  # historical name difference
}
for p in PROMPT_TYPES:
    BACKEND_TO_PIPELINE.setdefault(p, p.replace("-int-sarc", "-int"))


def load_notes() -> list[dict]:
    rows = []
    with NOTES_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";", quotechar='"')
        for r in reader:
            rows.append({k: (v or "") for k, v in r.items()})
    return rows


def load_gold_by_note() -> dict[str, list[str]]:
    """Map note_id -> list of gold annotations."""
    data = json.loads(GOLD_JSON.read_text())
    out: dict[str, list[str]] = {}
    for patient in data:
        for note in patient["notes"]:
            out[note["note_id"]] = note.get("annotations", [])
    return out


def load_report_type_mapping() -> dict[str, list[str]]:
    return json.loads(RTYPE_JSON.read_text())


def preflight() -> None:
    try:
        r = requests.get(f"{BACKEND}/api/server/status", timeout=5)
        r.raise_for_status()
    except Exception as e:
        sys.exit(
            f"[FATAL] Cannot reach backend at {BACKEND}. "
            "Start it with: cd backend && uvicorn main:app --port 8001\n"
            f"Underlying error: {e}"
        )


def create_session(notes: list[dict], rtype_mapping: dict[str, list[str]]) -> str:
    csv_data = []
    for n in notes:
        # Backend expects CSVRow with: text, date, p_id, note_id, report_type, annotations(optional)
        csv_data.append({
            "text":        n["text"],
            "date":        n["date"],
            "p_id":        n["p_id"],
            "note_id":     n["note_id"],
            "report_type": n["report_type"],
            # Don't send annotations — we'll score against gold ourselves.
        })

    payload = {
        "name":               "27B backend eval (INT)",
        "description":        "Replicating PDF analysis via /api/annotate/process to exercise history splitting, structured output, ICDO3 lookup",
        "csv_data":           csv_data,
        "prompt_types":       PROMPT_TYPES,
        "center":             "INT-SARC",
        "evaluation_mode":    "validation",
        "report_type_mapping": rtype_mapping,
    }
    r = requests.post(f"{BACKEND}/api/sessions", json=payload, timeout=60)
    r.raise_for_status()
    session_id = r.json()["session_id"]
    print(f"[session] created {session_id}")
    return session_id


def process_note(session_id: str, note: dict,
                 fewshot_k: int = 5, fast_mode: bool = False) -> dict[str, Any]:
    """Hit /api/annotate/process for one note, returning the raw response dict."""
    body = {
        "note_id":      note["note_id"],
        "prompt_types": PROMPT_TYPES,
        "fewshot_k":    fewshot_k,
        "use_fewshots": fewshot_k > 0,
        "fast_mode":    fast_mode,
    }
    params = {
        "session_id": session_id,
        "note_text":  note["text"],
    }
    r = requests.post(
        f"{BACKEND}/api/annotate/process",
        params=params, json=body, timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def annotation_for_prompt(annotations: list[str], prompt_type: str) -> str:
    """Return the gold annotation string for a given prompt_type (regex-mapped)."""
    # Use the same regex map as fewshot_builder.map_annotation_to_prompt.
    sys.path.insert(0, str(NLP_DIR))
    from fewshot_builder import map_annotation_to_prompt  # type: ignore
    for a in annotations:
        if map_annotation_to_prompt(a, prompt_type):
            return a
    return ""


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--center", default="INT-SARC")
    ap.add_argument("--model", default="")          # label only; server is authoritative
    ap.add_argument("--fewshot-k", type=int, default=5)
    ap.add_argument("--fast-mode", dest="fast_mode", action="store_true")
    ap.add_argument("--no-fast-mode", dest="fast_mode", action="store_false")
    ap.add_argument("--filter", dest="use_filter", action="store_true")
    ap.add_argument("--no-filter", dest="use_filter", action="store_false")
    ap.add_argument("--out", default=str(DETAILED_OUT))
    ap.set_defaults(fast_mode=False, use_filter=True)
    args = ap.parse_args()

    out_csv = Path(args.out)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    preflight()
    notes = load_notes()
    print(f"[load] {len(notes)} notes  (k={args.fewshot_k}, fast_mode={args.fast_mode}, filter={args.use_filter})")
    gold_by_note = load_gold_by_note()
    rtype_mapping = load_report_type_mapping() if args.use_filter else None

    session_id = create_session(notes, rtype_mapping)
    print(f"[run] processing {len(notes)} notes × {len(PROMPT_TYPES)} prompts via backend")

    all_results: list[dict] = []
    detailed_rows: list[dict] = []
    t0 = time.time()

    for i, note in enumerate(notes, 1):
        nt0 = time.time()
        try:
            resp = process_note(session_id, note,
                                fewshot_k=args.fewshot_k, fast_mode=args.fast_mode)
        except Exception as e:
            print(f"[{i}/{len(notes)}] {note['note_id']} ERROR: {e}")
            continue

        anns = resp.get("annotations", [])
        elapsed = time.time() - nt0
        print(f"[{i}/{len(notes)}] {note['note_id']}  {len(anns)} prompts answered in {elapsed:.1f}s"
              + (f"  [history split]" if (resp.get("history_detection") or {}).get("is_history") else ""))

        all_results.append({"note_id": note["note_id"], "p_id": note["p_id"], "response": resp})

        gold_anns = gold_by_note.get(note["note_id"], [])
        for ann in anns:
            backend_ptype = ann.get("prompt_type", "")
            pipeline_ptype = BACKEND_TO_PIPELINE.get(backend_ptype, backend_ptype)
            pred  = ann.get("annotation_text", "") or ""
            gold  = annotation_for_prompt(gold_anns, pipeline_ptype)
            detailed_rows.append({
                "note_id":         note["note_id"],
                "p_id":            note["p_id"],
                "note_date":       note["date"],
                "report_type":     note["report_type"],
                # Store pipeline-style key so downstream judge/comparison scripts
                # join cleanly with the pipeline run.
                "prompt_type":     pipeline_ptype,
                "backend_prompt_type": backend_ptype,
                "expected_annotation": gold,
                "predicted_annotation": pred,
                "llm_output":      pred,
                "raw_response":    (ann.get("raw_response") or "")[:1000],
                "reasoning":       (ann.get("reasoning") or "")[:1000],
                "confidence_score": ann.get("confidence_score"),
                "is_negated":      ann.get("is_negated"),
                "icdo3_code":      (ann.get("icdo3_code") or {}).get("code") if ann.get("icdo3_code") else "",
                "icdo3_low_conf":  (ann.get("icdo3_code") or {}).get("low_confidence") if ann.get("icdo3_code") else "",
                "hallucination":   bool(ann.get("hallucination_flags")),
                "multi_value":     bool(ann.get("multi_value_info")),
                "status":          ann.get("status", ""),
                "processing_time": ann.get("timing_breakdown", {}).get("total") if ann.get("timing_breakdown") else None,
                "history_note":    bool((resp.get("history_detection") or {}).get("is_history")),
            })

    print(f"[done] wall-clock {time.time()-t0:.1f}s")

    # Rich detailed CSV (semicolon-delim) next to the standardized predictions.
    detailed_out = out_csv.with_name(out_csv.stem + "_detailed.csv")
    if detailed_rows:
        fieldnames = list(detailed_rows[0].keys())
        with detailed_out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";",
                               quotechar='"', quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(detailed_rows)
        print(f"[wrote] {detailed_out}  ({len(detailed_rows)} rows)")

        # Standardized predictions.csv (note_id, p_id, report_type, prompt_type, gold, pred)
        import pandas as pd
        std = pd.DataFrame(detailed_rows)[
            ["note_id", "p_id", "report_type", "prompt_type",
             "expected_annotation", "predicted_annotation"]
        ].rename(columns={"expected_annotation": "gold", "predicted_annotation": "pred"})
        std.to_csv(out_csv, index=False)
        print(f"[wrote] {out_csv}  ({len(std)} rows)")

    raw_out = out_csv.with_name(out_csv.stem + "_raw.json")
    raw_out.write_text(json.dumps(all_results, ensure_ascii=False, indent=1))
    print(f"[wrote] {raw_out}")


if __name__ == "__main__":
    main()
