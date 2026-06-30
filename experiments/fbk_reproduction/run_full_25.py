"""End-to-end experiment: FBK setup (Llama-3.1-8B + strict prompt + RAG) on
ALL 25 MSCI variables across the 60 notes from our existing session.

Outputs: experiments/fbk_reproduction/full25/
  - predictions.jsonl  — one line per (note_id, variable, predicted, gold)
  - per_variable.json  — match/mismatch/FP/FN/both_empty counts per variable
  - summary.md         — markdown table comparable to report_msci_filtered.md
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm_asyncio

sys.path.insert(0, str(Path(__file__).parent))
from full_25_templates import VARIABLES, VarSpec, render  # noqa: E402
from rag_retriever import embed  # noqa: E402

VLLM_URL = "http://localhost:8000/v1"
MODEL = "meta-llama/Llama-3.1-8B-Instruct"
CSV_PATH = "FBK_MSCI/MSCI_Data_25_patients.csv"
SESSION_PATH = "backend/sessions/3effb5be-3c84-492f-ab5d-fecedd5c3173.json"
OUT_DIR = Path("experiments/fbk_reproduction/full25")
RAG_K = 5
MAX_CONCURRENT = 8


# ----------------- pool building -----------------

def build_pools(csv_path: str) -> dict[str, list[tuple[str, str]]]:
    """For each variable, return [(note_text, annotation), ...] from the FBK CSV
    where annotation starts with one of the variable's pool_prefixes and is
    deduped by (note_id, annotation)."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False).fillna("")
    pools: dict[str, list[tuple[str, str]]] = {}
    for var_name, spec in VARIABLES.items():
        mask = df["annotation"].str.lstrip().str.startswith(spec.pool_prefixes)
        sub = df[mask]
        seen = set()
        pool: list[tuple[str, str]] = []
        for _, row in sub.iterrows():
            note_id = row["internal_note_id"].strip()
            ann = row["annotation"].strip()
            if (note_id, ann) in seen:
                continue
            seen.add((note_id, ann))
            txt = (row.get("note_original_text") or "").strip()
            if not txt or txt == "None":
                txt = (row.get("note_text") or "").strip()
            if not txt:
                continue
            pool.append((txt, ann))
        pools[var_name] = pool
    return pools


# ----------------- LLM -----------------

async def call(client: AsyncOpenAI, prompt: str, sem: asyncio.Semaphore) -> str:
    async with sem:
        try:
            r = await client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.0,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001
            return f"<<ERROR: {e}>>"


async def run_one(client, sem, note: dict, spec: VarSpec, pool: list[tuple[str, str]]) -> dict:
    text = note["text"]
    if pool:
        # RAG
        k = min(RAG_K, len(pool))
        pool_texts = [p[0] for p in pool]
        q_emb = embed([text])[0]
        pool_emb = embed(pool_texts)
        sims = pool_emb @ q_emb
        top = np.argsort(-sims)[:k]
        few_shots = [pool[i] for i in top]
    else:
        few_shots = []
    prompt = render(spec, text, few_shots)
    pred = await call(client, prompt, sem)
    return {
        "note_id": note["note_id"],
        "report_type": note["report_type"],
        "variable": spec.name,
        "predicted": pred,
        "few_shot_pool_size": len(pool),
    }


async def main_async() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = json.loads(Path(SESSION_PATH).read_text())
    notes = session["notes"]

    print(f"Building FBK pools for {len(VARIABLES)} variables …")
    pools = build_pools(CSV_PATH)
    for v, p in pools.items():
        print(f"  {v}: pool size {len(p)}")

    client = AsyncOpenAI(base_url=VLLM_URL, api_key="EMPTY")
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    tasks = []
    for note in notes:
        for var_name, spec in VARIABLES.items():
            tasks.append(run_one(client, sem, note, spec, pools[var_name]))

    print(f"\nRunning {len(tasks)} inference calls "
          f"(concurrency={MAX_CONCURRENT}) …")
    results = await tqdm_asyncio.gather(*tasks)

    # Attach gold from session
    ann = session["annotations"]
    rt_map = {}  # for filtered-report report_type filtering
    with (OUT_DIR / "predictions.jsonl").open("w") as f:
        for r in results:
            nid = r["note_id"]
            spec = VARIABLES[r["variable"]]
            entry = ann.get(nid, {}).get(spec.session_key)
            gold = ""
            if entry and isinstance(entry, dict):
                er = entry.get("evaluation_result") or {}
                ge = er.get("expected_annotation", "")
                if ge and ge != "[NO EXPECTED ANNOTATION]":
                    gold = ge
            r["gold"] = gold
            f.write(json.dumps(r) + "\n")

    print(f"\nWrote: {OUT_DIR / 'predictions.jsonl'}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
