#!/usr/bin/env python3
"""
Run one (or many) experiment configs and save predictions.

  python exp_run.py --run-id INT-SARC__27b__raw__k5__all__filter1__reason1__pre
  python exp_run.py --model 27b            # run every config that needs 27b served
  python exp_run.py --model 27b --stack raw   # only the raw ones

The runner validates that the live vLLM server is serving the model the config
expects, then dispatches to the raw or production eval and writes:

  experiments/results/<run_id>/config.json
  experiments/results/<run_id>/predictions.csv     (note_id, prompt_type, gold, pred)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from exp_registry import (
    CENTERS, MODEL_SERVED, ExpConfig, all_configs, configs_for_model,
    raw_sweep_configs, production_sweep_configs,
)

NLP_DIR = Path(__file__).resolve().parent
RAW_VLLM = "http://localhost:8000/v1"
BACKEND = "http://localhost:8001"


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

def _live_raw_model() -> str | None:
    try:
        r = requests.get(f"{RAW_VLLM}/models", timeout=5)
        r.raise_for_status()
        return r.json()["data"][0]["id"]
    except Exception:
        return None


def _assert_model(cfg: ExpConfig) -> None:
    expected = MODEL_SERVED[cfg.model]
    live = _live_raw_model()
    if live is None:
        sys.exit(f"[FATAL] No vLLM server reachable at {RAW_VLLM}. "
                 f"Start: CUDA_VISIBLE_DEVICES=N vllm serve {expected} ...")
    if live != expected:
        sys.exit(f"[FATAL] Live model is '{live}' but config needs '{expected}'.\n"
                 f"        Restart vLLM with {expected} (and, for production runs, "
                 f"point backend/config/vllm_config.json at it and restart the backend).")


# ---------------------------------------------------------------------------
# Stack-appropriate report-type mapping
# ---------------------------------------------------------------------------

def _raw_report_type_mapping(cfg: ExpConfig, out_path: Path) -> Path:
    """The canonical mapping uses '-int-sarc' keys (production). The raw pipeline
    prompts use '-int'. Rewrite the suffix and special-case surgerytype."""
    canon = json.loads(CENTERS[cfg.center].report_type_mapping.read_text())
    rewritten = {}
    for report_type, prompts in canon.items():
        new = []
        for p in prompts:
            p2 = p.replace("-int-sarc", "-int")
            if p2 == "surgerytype-int":
                p2 = "surgerytype-fs30-int"
            new.append(p2)
        rewritten[report_type] = new
    out_path.write_text(json.dumps(rewritten, indent=2))
    return out_path


# ---------------------------------------------------------------------------
# RAW stack
# ---------------------------------------------------------------------------

def _sync_vllm_config(cfg: ExpConfig) -> None:
    """Point pipeline/api/nlp/vllm_config.json at the config's model + the raw
    endpoint, so evaluate_llm_int_prompts.py talks to the right server."""
    path = NLP_DIR / "vllm_config.json"
    conf = json.loads(path.read_text()) if path.exists() else {}
    conf.update({
        "use_vllm": True,
        "vllm_endpoint": f"{RAW_VLLM}",
        "model_name": MODEL_SERVED[cfg.model],
        "batch_size": conf.get("batch_size", 8),
        "timeout": conf.get("timeout", 150),
    })
    path.write_text(json.dumps(conf, indent=2))


def run_raw(cfg: ExpConfig) -> None:
    cd = CENTERS[cfg.center]
    rdir = cfg.result_dir()
    faiss_dir = cd.faiss_root / cfg.fewshot_mode
    if not faiss_dir.exists():
        sys.exit(f"[FATAL] FAISS dir missing: {faiss_dir}\n"
                 f"        Run: python exp_build_fewshots.py --center {cfg.center}")
    _sync_vllm_config(cfg)

    cmd = [
        sys.executable, str(NLP_DIR / "evaluate_llm_int_prompts.py"),
        "--notes-csv",   str(cd.notes_csv),
        "--json-file",   str(cd.gold_json),
        "--prompts-json", str(cd.prompts_json),
        "--model-path",  MODEL_SERVED[cfg.model],
        "--faiss-dir",   str(faiss_dir),
    ]
    if cfg.fewshot_k == 0:
        cmd.append("--no-fewshots")
    else:
        cmd += ["--fewshot-k", str(cfg.fewshot_k)]
    if cfg.filter:
        mapping = _raw_report_type_mapping(cfg, rdir / "report_type_mapping_raw.json")
        cmd += ["--report-type-mapping", str(mapping)]
    # note-only (Q9) is handled by the blanked-annotation FAISS index built by
    # exp_build_fewshots.py — no extra flag needed.

    print(f"[run] {cfg.run_id()}\n      {' '.join(cmd)}")
    t0 = time.time()
    subprocess.run(cmd, cwd=str(NLP_DIR), check=True)
    print(f"[run] finished in {time.time()-t0:.0f}s")

    # Collect predictions from the eval's detailed CSV.
    detailed = NLP_DIR / "llm_evaluation_detailed.csv"
    df = pd.read_csv(detailed, sep=";", engine="python", on_bad_lines="skip")
    preds = df[["note_id", "p_id", "report_type", "prompt_type",
                "expected_annotation", "predicted_annotation"]].rename(
        columns={"expected_annotation": "gold", "predicted_annotation": "pred"})
    preds.to_csv(rdir / "predictions.csv", index=False)
    (rdir / "config.json").write_text(json.dumps(cfg.to_dict(), indent=2))
    print(f"[run] wrote {len(preds)} predictions -> {rdir / 'predictions.csv'}")


# ---------------------------------------------------------------------------
# PRODUCTION stack
# ---------------------------------------------------------------------------

def run_production(cfg: ExpConfig) -> None:
    rdir = cfg.result_dir()
    # Delegate to evaluate_via_backend.py with explicit args (added below).
    cmd = [
        sys.executable, str(NLP_DIR / "evaluate_via_backend.py"),
        "--center",     cfg.center,
        "--model",      MODEL_SERVED[cfg.model],
        "--fewshot-k",  str(cfg.fewshot_k),
        "--out",        str(rdir / "predictions.csv"),
    ]
    cmd.append("--fast-mode" if not cfg.reasoning else "--no-fast-mode")
    cmd.append("--filter" if cfg.filter else "--no-filter")
    print(f"[run] {cfg.run_id()} (production)\n      {' '.join(cmd)}")
    t0 = time.time()
    subprocess.run(cmd, cwd=str(NLP_DIR), check=True)
    print(f"[run] finished in {time.time()-t0:.0f}s")
    (rdir / "config.json").write_text(json.dumps(cfg.to_dict(), indent=2))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def run_one(cfg: ExpConfig, skip_done: bool = True) -> None:
    rdir = cfg.result_dir()
    if skip_done and (rdir / "predictions.csv").exists():
        print(f"[skip] {cfg.run_id()} already has predictions.csv")
        return
    _assert_model(cfg)
    if cfg.stack == "raw":
        run_raw(cfg)
    elif cfg.stack == "production":
        run_production(cfg)
    else:
        sys.exit(f"unknown stack {cfg.stack}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", help="run a single config by its run_id")
    ap.add_argument("--model", help="run every config that needs this model served")
    ap.add_argument("--stack", choices=["raw", "production"], help="restrict to one stack")
    ap.add_argument("--raw-sweep", action="store_true",
                    help="raw-stack dimension sweep (K, filter, few-shot mode) on --model — internal control")
    ap.add_argument("--prod-sweep", action="store_true",
                    help="PRODUCTION-stack sweep (K, filter, reasoning) on --model — the hospital-representative runs")
    ap.add_argument("--force", action="store_true", help="re-run even if predictions exist")
    args = ap.parse_args()

    if args.run_id:
        cfg = next((c for c in all_configs() if c.run_id() == args.run_id), None)
        if cfg is None:
            try:
                cfg = ExpConfig.from_run_id(args.run_id)
            except ValueError:
                cfg = None
        if cfg is None:
            sys.exit(f"unknown run-id {args.run_id}")
        targets = [cfg]
    elif args.prod_sweep:
        if not args.model:
            sys.exit("--prod-sweep needs --model")
        targets = production_sweep_configs(args.model)
    elif args.raw_sweep:
        if not args.model:
            sys.exit("--raw-sweep needs --model")
        targets = raw_sweep_configs(args.model)
    elif args.model:
        targets = configs_for_model(args.model)
        if args.stack:
            targets = [c for c in targets if c.stack == args.stack]
    else:
        sys.exit("specify --run-id, --model, or --raw-sweep --model")

    print(f"[plan] {len(targets)} run(s)")
    for cfg in targets:
        run_one(cfg, skip_done=not args.force)


if __name__ == "__main__":
    main()
