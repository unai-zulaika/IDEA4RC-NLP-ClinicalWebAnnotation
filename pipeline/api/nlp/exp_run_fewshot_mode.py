#!/usr/bin/env python3
"""
Pseudo-automated few-shot mode sweep on the PRODUCTION stack.

The backend's FAISS pool is loaded once with the original-with-placeholders
fewshot file (extra_data/fewshot_examples_INT_with_missing.csv). After that,
the `sanitize_fewshots` flag in backend/config/vllm_config.json gives the two
main contrasts of Q3 without any pool swap:

  sanitize=true  → placeholders stripped at render  → "complete-effective"
  sanitize=false → placeholders kept                → "incomplete-faithful"

The driver:
  1. Edits the flag.
  2. Waits for the user to restart the backend (polls /api/server/status).
  3. Runs and judges the cell.
  4. Moves on to the next mode.

Use:
  python exp_run_fewshot_mode.py --model 4b
  python exp_run_fewshot_mode.py --model 4b --only complete   # just one mode
  python exp_run_fewshot_mode.py --model 4b --include-note-only  # also do the pool swap

Note-only requires a pool swap (no flag blanks the annotations), so it's
opt-in. When enabled the driver also calls exp_load_backend_fewshots.py
between cells and pauses for the same restart cycle.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

BACKEND_CFG = Path("/home/zulaika/ClinicalAnnotationWeb/backend/config/vllm_config.json")
BACKEND_STATUS_URL = os.environ.get("BACKEND_STATUS_URL", "http://localhost:8001/api/server/status")
PY = sys.executable


def set_sanitize(flag: bool) -> None:
    cfg = json.loads(BACKEND_CFG.read_text())
    cfg["sanitize_fewshots"] = flag
    BACKEND_CFG.write_text(json.dumps(cfg, indent=2))
    print(f"[cfg] sanitize_fewshots -> {flag}")


def wait_for_backend(timeout: int = 600) -> None:
    print(f"  >>> RESTART THE BACKEND NOW <<<")
    print(f"      (e.g.  cd backend && uvicorn main:app --port 8001 --reload  )")
    print(f"  polling {BACKEND_STATUS_URL} ...")
    deadline = time.time() + timeout
    last_state: str | None = None
    while time.time() < deadline:
        try:
            r = requests.get(BACKEND_STATUS_URL, timeout=3)
            if r.status_code == 200:
                state = r.json().get("status", "?")
                if state != last_state:
                    print(f"  status: {state}")
                    last_state = state
                if state in ("ready", "ok", "running", "available"):
                    print("  backend is up.")
                    return
        except Exception:
            pass
        time.sleep(3)
    raise SystemExit("backend did not come up in time")


def run_cell(run_id: str) -> None:
    print(f"\n=== run+judge: {run_id} ===")
    subprocess.run([PY, "exp_run.py", "--run-id", run_id], check=True)
    subprocess.run([PY, "exp_judge.py", "--run-id", run_id], check=True)


def swap_pool(mode: str) -> None:
    print(f"[pool] swapping backend faiss store to mode={mode}")
    subprocess.run([PY, "exp_load_backend_fewshots.py", "--mode", mode], check=True)


def restore_pool() -> None:
    print("[pool] restoring original backend faiss store")
    subprocess.run([PY, "exp_load_backend_fewshots.py", "--restore"], check=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="e.g. 4b, 27b")
    ap.add_argument("--center", default="INT-SARC")
    ap.add_argument("--only", choices=["complete", "incomplete", "note-only", "all"],
                    help="run just one of the modes")
    ap.add_argument("--include-note-only", action="store_true",
                    help="also do the note-only pool swap (needs exp_load_backend_fewshots)")
    args = ap.parse_args()

    # The plan: each item is (mode-label, sanitize-flag, needs-pool-swap, run-id-mode-key)
    plan: list[tuple[str, bool, bool, str]] = [
        ("complete-effective (sanitize=on)",  True,  False, "complete"),
        ("incomplete-faithful (sanitize=off)", False, False, "incomplete"),
    ]
    if args.include_note_only:
        plan.append(("note-only (pool swap)", True, True, "note-only"))

    if args.only:
        plan = [p for p in plan if p[3] == args.only]
        if not plan:
            raise SystemExit(f"--only {args.only} not in plan")

    print(f"Plan: {[p[0] for p in plan]}")
    for label, sanitize, needs_swap, mode_key in plan:
        print(f"\n##### {label} #####")
        if needs_swap:
            swap_pool(mode_key)
        set_sanitize(sanitize)
        wait_for_backend()
        run_id = (f"{args.center}__{args.model}__production"
                  f"__k5__{mode_key}__filter1__reason1__pre")
        run_cell(run_id)

    if args.include_note_only:
        print("\n(remember: restore the pool to the original 'all' file when done)")
        # leave restore to the user — they may want to keep note-only loaded


if __name__ == "__main__":
    main()
