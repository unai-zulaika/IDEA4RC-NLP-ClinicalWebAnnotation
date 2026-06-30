"""Re-run only the (note, variable) pairs that errored in predictions.jsonl.

Adds aggressive note + few-shot truncation to fit in the 8192-token context.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm_asyncio

sys.path.insert(0, str(Path(__file__).parent))
from full_25_templates import VARIABLES, render  # noqa: E402
from rag_retriever import embed  # noqa: E402
from run_full_25 import build_pools  # noqa: E402

VLLM_URL = "http://localhost:8000/v1"
MODEL = "meta-llama/Llama-3.1-8B-Instruct"
SESSION_PATH = "backend/sessions/3effb5be-3c84-492f-ab5d-fecedd5c3173.json"
PRED_PATH = Path("experiments/fbk_reproduction/full25/predictions.jsonl")
CSV_PATH = "FBK_MSCI/MSCI_Data_25_patients.csv"
RAG_K = 3                  # smaller k for long notes
MAX_NOTE_CHARS = 3000      # ~750 tokens
MAX_SHOT_CHARS = 1200      # ~300 tokens each
MAX_CONCURRENT = 8


def truncate(s: str, lim: int) -> str:
    return s if len(s) <= lim else s[:lim] + "…[truncated]"


async def call(client, prompt, sem):
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


async def run_one(client, sem, note: dict, spec, pool, gold: str) -> dict:
    text = truncate(note["text"], MAX_NOTE_CHARS)
    if pool:
        k = min(RAG_K, len(pool))
        pool_texts = [truncate(p[0], MAX_SHOT_CHARS) for p in pool]
        q_emb = embed([text])[0]
        p_emb = embed(pool_texts)
        sims = p_emb @ q_emb
        top = np.argsort(-sims)[:k]
        few_shots = [(pool_texts[i], pool[i][1]) for i in top]
    else:
        few_shots = []
    prompt = render(spec, text, few_shots)
    pred = await call(client, prompt, sem)
    return {
        "note_id": note["note_id"],
        "report_type": note["report_type"],
        "variable": spec.name,
        "predicted": pred,
        "gold": gold,
    }


async def main_async() -> None:
    session = json.loads(Path(SESSION_PATH).read_text())
    notes_by_id = {n["note_id"]: n for n in session["notes"]}
    pools = build_pools(CSV_PATH)

    existing = [json.loads(l) for l in PRED_PATH.open()]
    failed = [r for r in existing if r["predicted"].startswith("<<ERROR")]
    print(f"Found {len(failed)} failed predictions to redo (out of {len(existing)})")

    client = AsyncOpenAI(base_url=VLLM_URL, api_key="EMPTY")
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    tasks = []
    for r in failed:
        note = notes_by_id.get(r["note_id"])
        if not note:
            continue
        spec = VARIABLES[r["variable"]]
        tasks.append(run_one(client, sem, note, spec, pools[r["variable"]], r.get("gold", "")))

    print(f"Running {len(tasks)} re-tries (concurrency={MAX_CONCURRENT})…")
    new_results = await tqdm_asyncio.gather(*tasks)

    # Merge — replace failed entries by (note_id, variable) key
    new_by_key = {(r["note_id"], r["variable"]): r for r in new_results}
    out: list[dict] = []
    for r in existing:
        key = (r["note_id"], r["variable"])
        if key in new_by_key:
            merged = dict(r)
            merged.update(new_by_key[key])
            out.append(merged)
        else:
            out.append(r)

    PRED_PATH.write_text("\n".join(json.dumps(o) for o in out) + "\n")
    remaining_errors = sum(1 for o in out if o["predicted"].startswith("<<ERROR"))
    print(f"After re-run: {remaining_errors} errors remaining.")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
