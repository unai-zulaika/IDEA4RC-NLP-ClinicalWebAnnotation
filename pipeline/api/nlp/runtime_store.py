# runtime_store.py
import faiss
import pandas as pd
import json
from pathlib import Path
from sentence_transformers import SentenceTransformer


class FewShotStore:
    def __init__(self, root="faiss_store"):
        self.root = Path(root)
        self.embedder = SentenceTransformer(
            "sentence-transformers/all-mpnet-base-v2")
        self.idxs, self.tables = {}, {}

    def load_task(self, task_key: str):
        if task_key in self.idxs:
            return
        self.idxs[task_key] = faiss.read_index(
            str(self.root / f"{task_key}.index"))
        self.tables[task_key] = pd.read_parquet(
            self.root / f"{task_key}.parquet")

    def topk(self, task_key: str, note_text: str, k: int = 12):
        self.load_task(task_key)
        x = self.embedder.encode(
            [note_text], convert_to_numpy=True, normalize_embeddings=True).astype("float32")
        # cosine scores (since normalized)
        D, I = self.idxs[task_key].search(x, k)
        tbl = self.tables[task_key].iloc[I[0]]
        # Return as list[(note, annotation)]
        return list(zip(tbl["note_original_text"].tolist(), tbl["annotation"].tolist()))
