# build_faiss.py
import faiss
import numpy as np
import pandas as pd
import json
from sentence_transformers import SentenceTransformer
from pathlib import Path

EMB = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")
OUT_DIR = Path("faiss_store")
OUT_DIR.mkdir(exist_ok=True)


def build_task_index(task_key: str, df: pd.DataFrame, text_col="note_original_text"):
    # df: labeled pool for the task (already filtered like in your scripts)
    # columns we keep to reconstruct few-shots later:
    kept = df[[text_col, "annotation"]].copy().reset_index(drop=True)
    X = EMB.encode(kept[text_col].tolist(),
                   convert_to_numpy=True, normalize_embeddings=True)
    idx = faiss.IndexFlatIP(X.shape[1])      # cosine (since we normalized)
    idx.add(X.astype(np.float32))

    faiss.write_index(idx, str(OUT_DIR / f"{task_key}.index"))
    kept.to_parquet(OUT_DIR / f"{task_key}.parquet", index=False)
    meta = {"task": task_key, "dim": int(X.shape[1]), "size": int(X.shape[0])}
    (OUT_DIR / f"{task_key}.json").write_text(json.dumps(meta, indent=2))

    print(
        f"[INFO] FAISS index and metadata for task '{task_key}' built successfully.")

# Example: build from your existing filtered DataFrames HISTOLOGY EXAMPLE


# Read DataFrames from CSV files
df1 = pd.read_csv('Swedish_data.csv')
merged_df = df1.dropna(
    subset=['annotation', 'note_original_text', 'processed_highlight'])

# Print sizes of the original DataFrames
print(f"\n\nSize of Phase 1 Data: {merged_df.shape}")


def filter_annotations(example):
    annotation = example["annotation"]
    if annotation is None:
        return False  # Skip rows with missing annotations
    # CHANGE THIS FOR DIFFERENT FILTERS
    return example["annotation"].startswith("Histolog")


df_filtered = merged_df[merged_df.apply(filter_annotations, axis=1)]
build_task_index("histology", df_filtered)
