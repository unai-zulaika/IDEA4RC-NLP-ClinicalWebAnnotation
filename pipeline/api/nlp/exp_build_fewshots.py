#!/usr/bin/env python3
"""
Build per-mode FAISS indexes for the few-shot quality dimension (Q3/Q9).

Modes:
  all        — every few-shot example (the existing pool)
  complete   — only examples whose annotation has NO [placeholder] left
  incomplete — only examples whose annotation still contains a [placeholder]
  note-only  — same examples as `all`, but the annotation is blanked so the
               rendered few-shot shows the note without the answer (Q9).
               (Index content is identical to `all`; the *rendering* differs,
               handled by exp_run.py via the --note-only-fewshots flag.)

Outputs one FAISS index per prompt key per mode, under
  pipeline/api/nlp/experiments/faiss/<CENTER>/<mode>/<prompt_key>.{index,parquet,json}

Usage:
  python exp_build_fewshots.py --center INT-SARC
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from exp_registry import CENTERS

PLACEHOLDER_RE = re.compile(r"\[(select|put|provide|pick|choose)[^\]]*\]|\[(value|date|select)\]", re.I)


def _has_placeholder(annotation: str) -> bool:
    return bool(PLACEHOLDER_RE.search(annotation or ""))


def _faiss_key(center: str, prompt_type: str) -> str:
    """Map a source few-shot prompt_type to the backend FAISS key for `center`.

    INT-SARC source keys end with '-int' and map to '-int-sarc' (plus the
    surgerytype-fs30 -> surgerytype special case). Other centers (MSCI, VGR,
    INT-HNC) use bare source keys and map to '-<center_lower>'.
    """
    cl = center.lower()
    base = prompt_type
    for suf in (f"-{cl}", "-int"):
        if base.endswith(suf):
            base = base[: -len(suf)]
            break
    if center == "INT-SARC" and base == "surgerytype-fs30":
        base = "surgerytype"
    return f"{base}-{cl}"


def expected_keys(center: str) -> set[str]:
    """The FAISS keys the backend will request for `center`, from its prompts.json.

    prompts.json keys may already carry a center suffix (INT block keys end in
    '-int'), so route each through _faiss_key to get the canonical backend key.
    """
    cd = CENTERS[center]
    pj = json.loads(Path(cd.prompts_json).read_text(encoding="utf-8"))
    block = pj.get(cd.prompts_center_key, {})
    return {_faiss_key(center, k) for k in block.keys()}


def check_coverage(center: str) -> list[str]:
    """Compare the built `all` pool against expected_keys; return missing keys.

    A missing index is the silent-zero-shot hazard: the backend would retrieve
    nothing and fall back to zero-shot with no error.
    """
    cd = CENTERS[center]
    all_dir = cd.faiss_root / "all"
    built = {p.stem for p in all_dir.glob("*.index")} if all_dir.exists() else set()
    expected = expected_keys(center)
    print(f"[{center}] FAISS coverage: {len(built & expected)}/{len(expected)} "
          f"expected keys present")
    missing = sorted(expected - built)
    extra = sorted(built - expected)
    if missing:
        print(f"[{center}] MISSING indexes (would silently zero-shot): {missing}")
    if extra:
        print(f"[{center}] extra indexes (not in prompts.json): {extra}")
    return missing


def build_indexes(center: str) -> None:
    cd = CENTERS[center]
    import faiss
    from sentence_transformers import SentenceTransformer

    df = pd.read_csv(cd.fewshots_csv).dropna(subset=["prompt_type", "note_text", "annotation"])
    print(f"[{center}] loaded {len(df)} few-shot rows")

    embedder = SentenceTransformer(
        "sentence-transformers/all-mpnet-base-v2",
        device="cuda" if _cuda() else "cpu",
    )

    modes = {
        "all":        df,
        "complete":   df[~df["annotation"].apply(_has_placeholder)],
        "incomplete": df[df["annotation"].apply(_has_placeholder)],
        # note-only shares the `all` content; rendering blanks the annotation.
    }

    for mode, mdf in modes.items():
        out_dir = cd.faiss_root / mode
        # Clean the dir first so a rebuild can't leave stale indexes from an
        # earlier naming scheme behind (we hit exactly that bug with -int /
        # -int-int / -int-sarc variants piling up).
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n[{center}/{mode}] {len(mdf)} examples")
        for prompt_type, group in mdf.groupby("prompt_type"):
            # Map source few-shot key -> backend FAISS key for this center.
            key = _faiss_key(center, prompt_type)
            sub = (group[["note_text", "annotation"]]
                   .rename(columns={"note_text": "note_original_text"})
                   .reset_index(drop=True))
            if len(sub) == 0:
                continue
            emb = embedder.encode(
                sub["note_original_text"].tolist(),
                convert_to_numpy=True, normalize_embeddings=True,
                batch_size=64, show_progress_bar=False,
            ).astype(np.float32)
            index = faiss.IndexFlatIP(emb.shape[1])
            index.add(emb)
            faiss.write_index(index, str(out_dir / f"{key}.index"))
            sub.to_parquet(out_dir / f"{key}.parquet", index=False)
            (out_dir / f"{key}.json").write_text(
                json.dumps({"task": key, "dim": int(emb.shape[1]), "size": int(len(sub))}, indent=2)
            )
        print(f"[{center}/{mode}] wrote {mdf['prompt_type'].nunique()} indexes -> {out_dir}")

    # note-only (Q9): same retrieval pool as `all`, but the annotation is blanked
    # so the rendered few-shot shows the note WITHOUT the answer. We copy the
    # `all` FAISS index (identical embeddings) and overwrite the parquet with a
    # blanked annotation column — no eval-code change needed.
    note_dir = cd.faiss_root / "note-only"
    if note_dir.exists():
        shutil.rmtree(note_dir)
    note_dir.mkdir(parents=True, exist_ok=True)
    all_dir = cd.faiss_root / "all"
    for f in all_dir.iterdir():
        if f.suffix == ".parquet":
            pq = pd.read_parquet(f)
            pq["annotation"] = ""        # blank the answer
            pq.to_parquet(note_dir / f.name, index=False)
        else:
            (note_dir / f.name).write_bytes(f.read_bytes())
    print(f"[{center}/note-only] built from `all` pool with blanked answers -> {note_dir}")

    check_coverage(center)


def _cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--center", default="INT-SARC", choices=list(CENTERS.keys()))
    ap.add_argument("--check", action="store_true",
                    help="only check FAISS coverage vs prompts.json, don't rebuild")
    args = ap.parse_args()
    if args.check:
        missing = check_coverage(args.center)
        raise SystemExit(1 if missing else 0)
    build_indexes(args.center)


if __name__ == "__main__":
    main()
