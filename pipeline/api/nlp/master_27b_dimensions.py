#!/usr/bin/env python3
"""27B dimension sweep (Q4/Q5/Q3) on the 60-note set, to match the 4B coverage.
Already have on the 27B: k5 baseline (msci_27b_k5), reasoning on/off (Q7). This adds
Q4 k=0,1,3,10; Q5 filter-off; Q3 sanitize-off. Points the backend at the 27B (:8000),
resumable, backend-resilient, detached.
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
M27 = "unaizulaika/medgemma-27b-text-it-W4A16-G128"
sys.path.insert(0, str(NLP))
from run_msci_eval import build_session  # noqa: E402

# (out_id, k, fast_mode, use_filter, sanitize)
CONFIGS = [
    ("msci60_27b_k0",        0, False, True,  True),
    ("msci60_27b_k1",        1, False, True,  True),
    ("msci60_27b_k3",        3, False, True,  True),
    ("msci60_27b_k10",      10, False, True,  True),
    ("msci60_27b_nofilter",  5, False, False, True),
    ("msci60_27b_sanoff",    5, False, True,  False),
]


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
        f"> /tmp/backend_27bdim.log 2>&1 < /dev/null &", shell=True)
    for _ in range(90):
        if backend_up():
            print("[orch] backend up", flush=True)
            return
        time.sleep(2)
    print("[orch] WARNING backend not up", flush=True)


def write_cfg(model_27b: bool, sanitize: bool):
    cfg = json.loads(CFG.read_text())
    changed = False
    if model_27b and cfg.get("model_name") != M27:
        cfg["model_name"] = M27
        cfg["vllm_endpoint"] = "http://localhost:8000/v1"
        changed = True
    if cfg.get("sanitize_fewshots") != sanitize:
        cfg["sanitize_fewshots"] = sanitize
        changed = True
    if changed:
        CFG.write_text(json.dumps(cfg, indent=2))
    return changed


def session_done(out_id, n=60):
    p = SESS / f"{out_id}.json"
    if not p.exists():
        return False
    try:
        return len(json.loads(p.read_text()).get("annotations", {})) >= n
    except Exception:
        return False


def main():
    t0 = time.time()
    # ensure backend is on the 27B from the start
    if write_cfg(True, True) or not backend_up():
        restart_backend()
    for out_id, k, fast, use_filter, sanitize in CONFIGS:
        print(f"\n[orch] === {out_id}  k={k} filter={use_filter} san={sanitize} ===", flush=True)
        if session_done(out_id):
            print(f"[orch] {out_id} already complete, skip", flush=True)
            continue
        if write_cfg(True, sanitize):
            restart_backend()
        elif not backend_up():
            restart_backend()
        if not (SESS / f"{out_id}.json").exists():
            s = build_session(0, use_filter, out_id, f"MSCI 27B dim {out_id}", {EXCLUDE})
            (SESS / f"{out_id}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))
            print(f"[orch] built session {out_id} ({len(s['notes'])} notes)", flush=True)
        for attempt in range(12):
            if session_done(out_id):
                break
            if not backend_up():
                restart_backend()
            cmd = [PY, str(NLP / "run_eval_session.py"), "--session-id", out_id,
                   "--fewshot-k", str(k), "--exclude", EXCLUDE, "--chunk", "10"]
            print(f"[orch] run {out_id} attempt {attempt}", flush=True)
            subprocess.run(cmd, cwd=str(NLP))
        print(f"[orch] {out_id}: {'DONE' if session_done(out_id) else 'INCOMPLETE'}", flush=True)
    write_cfg(True, True)  # restore sanitize on, keep 27B
    print(f"\n[orch] ALL 27B DIMS DONE in {(time.time()-t0)/3600:.2f}h", flush=True)


if __name__ == "__main__":
    main()
