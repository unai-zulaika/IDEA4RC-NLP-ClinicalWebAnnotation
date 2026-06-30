"""Run the FBK reproduction experiment for the 4 target MSCI variables.

Reproduces FBK's protocol for MSCI:
  - Llama-3.1-8B-Instruct via vLLM (OpenAI-compatible API).
  - For each variable: deduplicate annotations, 80/20 split (pool/test),
    RAG-select few-shots, prompt the model with strict format, score EM + PM.
  - Runs over multiple seeds to bound noise.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import openai
from tqdm import tqdm

# Local imports
sys.path.insert(0, str(Path(__file__).parent))
from build_dataset import build  # noqa: E402
from evaluator import evaluate  # noqa: E402
from prompts import VARIABLES, render_prompt  # noqa: E402
from rag_retriever import top_k  # noqa: E402

DEFAULT_VLLM_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "meta-llama/Llama-3.1-8B-Instruct"


def make_client(vllm_url: str) -> openai.OpenAI:
    return openai.OpenAI(base_url=vllm_url, api_key="EMPTY")


def call_model(
    client: openai.OpenAI,
    model: str,
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.0,
) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


def run_variable(
    client: openai.OpenAI,
    model: str,
    variable: str,
    pool: list[dict],
    test: list[dict],
    rag_k: int,
    pm_threshold: float,
) -> dict[str, Any]:
    """Run one variable end-to-end. Returns metric dict and per-sample log."""
    pool_notes = [p["note_text"] for p in pool]
    samples: list[dict] = []
    pairs: list[tuple[str, str]] = []

    for ex in tqdm(test, desc=f"{variable}", leave=False):
        idx = top_k(ex["note_text"], pool_notes, rag_k)
        few_shots = [(pool[i]["note_text"], pool[i]["annotation"]) for i in idx]
        prompt = render_prompt(variable, ex["note_text"], few_shots)
        t0 = time.time()
        try:
            pred = call_model(client, model, prompt)
        except Exception as e:  # noqa: BLE001
            pred = f"<<ERROR: {e}>>"
        elapsed = time.time() - t0
        samples.append(
            {
                "note_id": ex["note_id"],
                "gold": ex["annotation"],
                "predicted": pred,
                "few_shot_ids": [pool[i]["note_id"] for i in idx],
                "latency_s": elapsed,
            }
        )
        pairs.append((ex["annotation"], pred))

    metrics = evaluate(pairs, pm_threshold=pm_threshold)
    return {
        "variable": variable,
        "n_pool": len(pool),
        "n_test": len(test),
        "rag_k": rag_k,
        "metrics": {
            "n": metrics.n,
            "exact_match": metrics.exact_match,
            "partial_match": metrics.partial_match,
            "mismatch": metrics.mismatch,
            "accuracy": metrics.accuracy,
            "em_rate": metrics.em_rate,
            "pm_rate": metrics.pm_rate,
            "avg_similarity": metrics.avg_similarity,
        },
        "samples": samples,
    }


def load_split(path: Path) -> tuple[list[dict], list[dict]]:
    pool, test = [], []
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            split = row.pop("split")
            (pool if split == "pool" else test).append(row)
    return pool, test


def run_one_seed(
    csv_path: Path,
    splits_dir: Path,
    seed: int,
    client: openai.OpenAI,
    model: str,
    variables: list[str],
    pm_threshold: float,
) -> dict[str, Any]:
    summary = build(csv_path, splits_dir, seed)
    results: dict[str, Any] = {"seed": seed, "variables": {}}
    for var in variables:
        path = Path(summary[var]["path"])
        pool, test = load_split(path)
        rag_k = summary[var]["rag_k"]
        res = run_variable(client, model, var, pool, test, rag_k, pm_threshold)
        results["variables"][var] = res
        m = res["metrics"]
        print(
            f"  [{var}] N={m['n']} EM={m['exact_match']} PM={m['partial_match']} "
            f"acc={m['accuracy']:.3f}"
        )
    return results


def aggregate_across_seeds(per_seed: list[dict]) -> dict[str, dict]:
    """Compute mean ± std of accuracy/EM/PM per variable."""
    agg: dict[str, dict] = {}
    by_var: dict[str, list[dict]] = {}
    for s in per_seed:
        for var, r in s["variables"].items():
            by_var.setdefault(var, []).append(r["metrics"])
    for var, ms in by_var.items():
        accs = [m["accuracy"] for m in ms]
        ems = [m["em_rate"] for m in ms]
        pms = [m["pm_rate"] for m in ms]
        agg[var] = {
            "n_seeds": len(ms),
            "accuracy_mean": statistics.mean(accs),
            "accuracy_std": statistics.stdev(accs) if len(accs) > 1 else 0.0,
            "em_mean": statistics.mean(ems),
            "em_std": statistics.stdev(ems) if len(ems) > 1 else 0.0,
            "pm_mean": statistics.mean(pms),
            "pm_std": statistics.stdev(pms) if len(pms) > 1 else 0.0,
        }
    return agg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="FBK_MSCI/MSCI_Data_25_patients.csv")
    ap.add_argument("--splits-dir", default="experiments/fbk_reproduction/splits")
    ap.add_argument("--out", default="experiments/fbk_reproduction/results.json")
    ap.add_argument("--vllm-url", default=DEFAULT_VLLM_URL)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--seeds", nargs="+", type=int, default=[42, 7, 123])
    ap.add_argument(
        "--variables",
        nargs="+",
        default=list(VARIABLES.keys()),
    )
    ap.add_argument("--pm-threshold", type=float, default=0.6)
    args = ap.parse_args()

    client = make_client(args.vllm_url)
    print(f"Endpoint: {args.vllm_url}")
    print(f"Model:    {args.model}")
    print(f"Seeds:    {args.seeds}")
    print(f"Variables: {args.variables}")
    print()

    per_seed: list[dict] = []
    for seed in args.seeds:
        print(f"=== Seed {seed} ===")
        res = run_one_seed(
            Path(args.csv),
            Path(args.splits_dir),
            seed,
            client,
            args.model,
            args.variables,
            args.pm_threshold,
        )
        per_seed.append(res)

    final = {
        "config": {
            "model": args.model,
            "vllm_url": args.vllm_url,
            "csv": args.csv,
            "seeds": args.seeds,
            "variables": args.variables,
            "pm_threshold": args.pm_threshold,
        },
        "per_seed": per_seed,
        "aggregate": aggregate_across_seeds(per_seed),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(final, indent=2))
    print(f"\nWrote: {out}")
    print()
    print("=== Aggregate (mean ± std across seeds) ===")
    fbk_targets = {
        "biopsy_mitotic_count": 100.0,
        "necrosis_in_biopsy": 100.0,
        "necrosis_in_surgical": 100.0,
        "patient_weight_height": 100.0,
    }
    for var, a in final["aggregate"].items():
        target = fbk_targets.get(var)
        delta = (a["accuracy_mean"] * 100) - target if target else None
        line = (
            f"  {var:25s} acc={a['accuracy_mean']*100:5.1f} ± {a['accuracy_std']*100:4.1f}  "
            f"EM={a['em_mean']*100:5.1f}  PM={a['pm_mean']*100:5.1f}"
        )
        if delta is not None:
            line += f"   FBK={target:.0f} (Δ={delta:+.1f})"
        print(line)


if __name__ == "__main__":
    main()
