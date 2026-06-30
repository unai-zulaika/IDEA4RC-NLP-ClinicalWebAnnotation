#!/usr/bin/env python3
"""Q7 on the BIG model: run 27B reasoning-OFF (60-note, k5, filter-on, sanitize-on)
to compare against the existing 27B reasoning-ON baseline (msci_27b_k5).
Switches the backend to the 27B (8000), resumable, backend-resilient. Detached.
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path("/home/zulaika/ClinicalAnnotationWeb")
NLP = ROOT / "pipeline" / "api" / "nlp"
SESS = ROOT / "backend" / "sessions"
CFG = ROOT / "backend" / "config" / "vllm_config.json"
PY = str(ROOT / "backend" / ".venv" / "bin" / "python")
UVICORN = str(ROOT / "backend" / ".venv" / "bin" / "uvicorn")
EXCLUDE = "necrosis_in_biopsy-msci"
OUT = "msci60_27b_noreason"
sys.path.insert(0, str(NLP))
from run_msci_eval import build_session  # noqa: E402


def backend_up():
    try:
        urllib.request.urlopen("http://localhost:8001/api/server/status", timeout=4)
        return True
    except Exception:
        return False


def restart_backend():
    subprocess.run("fuser -k 8001/tcp", shell=True, stderr=subprocess.DEVNULL)
    time.sleep(3)
    subprocess.Popen(
        f"cd {ROOT}/backend && setsid nohup {UVICORN} main:app --port 8001 "
        f"> /tmp/backend_27b.log 2>&1 < /dev/null &", shell=True)
    for _ in range(90):
        if backend_up():
            print("[orch] backend up", flush=True)
            return
        time.sleep(2)
    print("[orch] WARNING backend not up", flush=True)


def session_done(n=60):
    p = SESS / f"{OUT}.json"
    if not p.exists():
        return False
    try:
        return len(json.loads(p.read_text()).get("annotations", {})) >= n
    except Exception:
        return False


def main():
    # 1. point backend at the 27B on :8000
    cfg = json.loads(CFG.read_text())
    cfg["model_name"] = "unaizulaika/medgemma-27b-text-it-W4A16-G128"
    cfg["vllm_endpoint"] = "http://localhost:8000/v1"
    CFG.write_text(json.dumps(cfg, indent=2))
    print("[orch] config -> 27B / :8000, restart", flush=True)
    restart_backend()

    # 2. build the reasoning-off session (k5, filter on)
    if not (SESS / f"{OUT}.json").exists():
        s = build_session(0, True, OUT, "MSCI 27B reasoning-off", {EXCLUDE})
        (SESS / f"{OUT}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))
        print(f"[orch] built {OUT} ({len(s['notes'])} notes)", flush=True)

    # 3. run reasoning-off (--fast-mode), resumable + restart on death
    t0 = time.time()
    for attempt in range(15):
        if session_done():
            break
        if not backend_up():
            restart_backend()
        cmd = [PY, str(NLP / "run_eval_session.py"), "--session-id", OUT,
               "--fewshot-k", "5", "--fast-mode", "--exclude", EXCLUDE, "--chunk", "10"]
        print(f"[orch] run attempt {attempt}", flush=True)
        subprocess.run(cmd, cwd=str(NLP))
    state = "DONE" if session_done() else "INCOMPLETE"
    print(f"[orch] {OUT}: {state} in {(time.time()-t0)/60:.0f} min", flush=True)


if __name__ == "__main__":
    main()
