#!/usr/bin/env python3
"""
Swap the backend's few-shot store to a specific mode pool, so the production
stack (which reads a fixed dir) uses the complete / incomplete / note-only /
all pool we built with exp_build_fewshots.py.

  python exp_load_backend_fewshots.py --center INT-SARC --mode incomplete
  python exp_load_backend_fewshots.py --restore        # put the original back

The backend loads `backend/data/faiss_store/` once at startup, so after swapping
you MUST restart the backend for it to take effect. This script prints the
reminder.

Few-shot quality on production also interacts with the backend's
`sanitize_fewshots` flag (backend/config/vllm_config.json):
  * sanitize_fewshots = true  -> placeholders stripped (Option A: "does the
    system's cleaning protect against messy CLN annotations?")
  * sanitize_fewshots = false -> placeholders kept (Option B: faithful
    "how much do messy few-shots hurt?")
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from exp_registry import CENTERS, REPO_ROOT

BACKEND_STORE = REPO_ROOT / "backend" / "data" / "faiss_store"
BACKUP_STORE = REPO_ROOT / "backend" / "data" / "faiss_store__original_backup"


def _backup_once() -> None:
    if BACKEND_STORE.exists() and not BACKUP_STORE.exists():
        shutil.copytree(BACKEND_STORE, BACKUP_STORE)
        print(f"[backup] saved original backend store -> {BACKUP_STORE}")


def load_mode(center: str, mode: str) -> None:
    src = CENTERS[center].faiss_root / mode
    if not src.exists():
        raise SystemExit(f"[FATAL] pool missing: {src}\n"
                         f"        run: python exp_build_fewshots.py --center {center}")
    _backup_once()
    if BACKEND_STORE.exists():
        shutil.rmtree(BACKEND_STORE)
    shutil.copytree(src, BACKEND_STORE)
    n = len(list(BACKEND_STORE.glob("*.index")))
    print(f"[load] {center}/{mode} -> {BACKEND_STORE}  ({n} prompt indexes)")
    print("[!] RESTART THE BACKEND for this to take effect:")
    print("      cd backend && uvicorn main:app --port 8001")


def restore() -> None:
    if not BACKUP_STORE.exists():
        raise SystemExit("[FATAL] no backup found; nothing to restore")
    if BACKEND_STORE.exists():
        shutil.rmtree(BACKEND_STORE)
    shutil.copytree(BACKUP_STORE, BACKEND_STORE)
    print(f"[restore] original backend store restored from {BACKUP_STORE}")
    print("[!] RESTART THE BACKEND.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--center", default="INT-SARC")
    ap.add_argument("--mode", choices=["all", "complete", "incomplete", "note-only"])
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    if args.restore:
        restore()
    elif args.mode:
        load_mode(args.center, args.mode)
    else:
        raise SystemExit("specify --mode <m> or --restore")


if __name__ == "__main__":
    main()
