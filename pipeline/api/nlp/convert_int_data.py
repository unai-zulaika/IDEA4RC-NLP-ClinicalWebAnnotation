#!/usr/bin/env python3
"""
Convert INT-format data files into the layout expected by
evaluate_llm_int_prompts.py:

  Input:
    extra_data/patients_notes_with_annotations_INT.csv  (gold: notes + annotations)
    extra_data/fewshots_int-sarc.csv                    (few-shot pool)

  Output:
    pipeline/api/nlp/first_patient_notes.csv
    pipeline/api/nlp/annotated_patient_notes_with_spans_full_verified.json
    pipeline/api/nlp/faiss_store/<prompt_key>-int.{index,parquet,json}
"""
from __future__ import annotations

import csv
import json
import re
from collections import OrderedDict, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
NLP_DIR = Path(__file__).resolve().parent

GOLD_CSV = REPO_ROOT / "extra_data" / "patients_notes_with_annotations_INT.csv"
FEWSHOTS_CSV = REPO_ROOT / "extra_data" / "fewshots_int-sarc.csv"

NOTES_OUT = NLP_DIR / "first_patient_notes.csv"
GOLD_OUT = NLP_DIR / "annotated_patient_notes_with_spans_full_verified.json"
FAISS_DIR = NLP_DIR / "faiss_store"


ANNOTATION_PREFIX_RE = re.compile(r"^[a-z0-9_\-]+-int\s*:\s*", re.IGNORECASE)


def clean_annotation(raw: str) -> str:
    """Strip the '<prompt-key>-int:' prefix and trailing period/whitespace."""
    s = ANNOTATION_PREFIX_RE.sub("", raw.strip())
    return s.rstrip(". ").strip()


def split_annotations(cell: str) -> list[str]:
    if not cell or cell.strip() == "":
        return []
    parts = [p.strip() for p in cell.split("|")]
    return [clean_annotation(p) for p in parts if p.strip()]


def convert_gold() -> None:
    rows: list[dict] = []
    with GOLD_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";", quotechar='"')
        for row in reader:
            if not row.get("p_id"):
                continue
            rows.append(row)

    print(f"[gold] read {len(rows)} note rows")

    # Notes CSV — same columns minus the annotations column
    notes_cols = ["text", "date", "p_id", "note_id", "report_type"]
    with NOTES_OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=notes_cols, delimiter=";", quotechar='"',
                                quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in notes_cols})
    print(f"[gold] wrote notes -> {NOTES_OUT}")

    # Group by patient
    patients: OrderedDict[str, list[dict]] = OrderedDict()
    for row in rows:
        pid = row["p_id"]
        patients.setdefault(pid, []).append({
            "text": row.get("text", ""),
            "date": row.get("date", ""),
            "p_id": pid,
            "note_id": row.get("note_id", ""),
            "report_type": row.get("report_type", ""),
            "annotations": split_annotations(row.get("annotations", "")),
        })

    gold = [
        {"patient_id": pid, "notes": notes}
        for pid, notes in patients.items()
    ]
    with GOLD_OUT.open("w", encoding="utf-8") as f:
        json.dump(gold, f, ensure_ascii=False, indent=2)
    n_anns = sum(len(n["annotations"]) for p in gold for n in p["notes"])
    print(f"[gold] wrote {len(gold)} patients, {sum(len(p['notes']) for p in gold)} notes, "
          f"{n_anns} annotations -> {GOLD_OUT}")


def build_faiss() -> None:
    # Imported lazily so the script's gold-conversion half stays cheap.
    import faiss
    from sentence_transformers import SentenceTransformer

    FAISS_DIR.mkdir(exist_ok=True)
    print(f"[faiss] writing to {FAISS_DIR}")

    df = pd.read_csv(FEWSHOTS_CSV)
    df = df.dropna(subset=["prompt_type", "note_text", "annotation"])
    print(f"[faiss] loaded {len(df)} fewshot rows")

    embedder = SentenceTransformer("sentence-transformers/all-mpnet-base-v2",
                                   device="cuda" if _cuda_available() else "cpu")

    by_type: dict[str, pd.DataFrame] = {
        k: g.reset_index(drop=True) for k, g in df.groupby("prompt_type")
    }
    for prompt_type, group in by_type.items():
        key = f"{prompt_type}-int"
        sub = group[["note_text", "annotation"]].rename(
            columns={"note_text": "note_original_text"}
        ).reset_index(drop=True)

        embeddings = embedder.encode(
            sub["note_original_text"].tolist(),
            convert_to_numpy=True,
            normalize_embeddings=True,
            batch_size=64,
            show_progress_bar=False,
        ).astype(np.float32)

        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)

        faiss.write_index(index, str(FAISS_DIR / f"{key}.index"))
        sub.to_parquet(FAISS_DIR / f"{key}.parquet", index=False)
        meta = {"task": key, "dim": int(embeddings.shape[1]), "size": int(len(sub))}
        (FAISS_DIR / f"{key}.json").write_text(json.dumps(meta, indent=2))
        print(f"[faiss]   {key:35s}  {len(sub):4d} examples")


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


if __name__ == "__main__":
    convert_gold()
    build_faiss()
    print("[done]")
