#!/usr/bin/env python3
"""Chain the INT-HNC Q2 headline: wait for the (already-running) 27B k5 run to finish,
then switch the backend to 4B and run the 4B k5 contrast. No orchestrator / no
health-check restarts (those killed saturated runs mid-note). Direct, sequential, robust.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path("/home/zulaika/ClinicalAnnotationWeb")
NLP = ROOT / "pipeline" / "api" / "nlp"
SESS = ROOT / "backend" / "sessions"
CFG = ROOT / "backend" / "config" / "vllm_config.json"
PY = str(ROOT / "backend" / ".venv" / "bin" / "python")
UVICORN = str(ROOT / "backend" / ".venv" / "bin" / "uvicorn")
M4B = ("unaizulaika/medgemma-1.5-4b-it-W4A16-G128", "http://localhost:8005/v1")


def scored(sid):
    try:
        return len(json.loads((SESS / f"{sid}.json").read_text()).get("annotations", {}))
    except Exception:
        return 0


def backend_up():
    try:
        urllib.request.urlopen("http://localhost:8001/api/server/status", timeout=10)
        return True
    except Exception:
        return False


def restart_backend():
    subprocess.run("fuser -k 8001/tcp", shell=True, stderr=subprocess.DEVNULL)
    time.sleep(4)
    subprocess.Popen(
        f"cd {ROOT}/backend && setsid nohup {UVICORN} main:app --port 8001 "
        f"> /tmp/backend_hnc.log 2>&1 < /dev/null &", shell=True)
    for _ in range(120):
        if backend_up():
            time.sleep(5)
            print("[chain] backend up", flush=True)
            return
        time.sleep(3)
    print("[chain] WARNING backend did not come up", flush=True)


def run_eval(sid, k):
    # resume by default so a mid-run retry continues (session starts empty -> first pass is full)
    cmd = [PY, str(NLP / "run_eval_session.py"), "--session-id", sid,
           "--fewshot-k", str(k), "--exclude", "", "--chunk", "1", "--timeout", "3000"]
    subprocess.run(cmd, cwd=str(NLP))


def main():
    # 1. wait for the already-running 27B k5 to finish (15 notes)
    print("[chain] waiting for hnc_27b_k5 to reach 15/15 ...", flush=True)
    last = -1
    while scored("hnc_27b_k5") < 15:
        n = scored("hnc_27b_k5")
        if n != last:
            print(f"[chain] hnc_27b_k5: {n}/15", flush=True)
            last = n
        time.sleep(60)
    print("[chain] hnc_27b_k5 DONE", flush=True)

    # 2. build the 4B session (copy of the 15-note eval subset)
    s = json.loads((SESS / "int_hnc_eval60.json").read_text())
    s["session_id"] = "hnc_4b_k5"
    s["annotations"] = {}
    (SESS / "hnc_4b_k5.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))

    # 3. switch backend to 4B and restart
    cfg = json.loads(CFG.read_text())
    cfg["model_name"], cfg["vllm_endpoint"] = M4B
    CFG.write_text(json.dumps(cfg, indent=2))
    restart_backend()

    # 4. run the 4B k5 contrast
    print("[chain] running hnc_4b_k5 ...", flush=True)
    for attempt in range(3):
        if scored("hnc_4b_k5") >= 15:
            break
        run_eval("hnc_4b_k5", 5)
    print(f"[chain] hnc_4b_k5: {scored('hnc_4b_k5')}/15 DONE", flush=True)

    # 5. restore 27B in config
    cfg = json.loads(CFG.read_text())
    cfg["model_name"] = "unaizulaika/medgemma-27b-text-it-W4A16-G128"
    cfg["vllm_endpoint"] = "http://localhost:8000/v1"
    CFG.write_text(json.dumps(cfg, indent=2))
    print("[chain] ALL Q2 HNC RUNS DONE", flush=True)


if __name__ == "__main__":
    main()
