#!/usr/bin/env python3
"""Chain: wait for the INT-HNC GPU job to free, then run the INT-SARC topo/morpho eval
on 27B (headline) then 4B, k=0, and score. Direct run_eval, no orchestrator (avoids the
health-check thrash). Sessions built by convert_diagnosis_extra.py.
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
MODELS = {
    "27b": ("unaizulaika/medgemma-27b-text-it-W4A16-G128", "http://localhost:8000/v1"),
    "4b": ("unaizulaika/medgemma-1.5-4b-it-W4A16-G128", "http://localhost:8005/v1"),
}
BASES = ["sarc_path_topomorpho", "sarc_rol_topo"]


def scored(sid):
    try:
        return len(json.loads((SESS / f"{sid}.json").read_text()).get("annotations", {}))
    except Exception:
        return 0


def n_notes(sid):
    return len(json.loads((SESS / f"{sid}.json").read_text())["notes"])


def backend_up():
    try:
        urllib.request.urlopen("http://localhost:8001/api/server/status", timeout=10)
        return True
    except Exception:
        return False


def restart_backend():
    subprocess.run("fuser -k 8001/tcp", shell=True, stderr=subprocess.DEVNULL)
    time.sleep(4)
    subprocess.Popen(f"cd {ROOT}/backend && setsid nohup {UVICORN} main:app --port 8001 "
                     f"> /tmp/backend_sarc.log 2>&1 < /dev/null &", shell=True)
    for _ in range(120):
        if backend_up():
            time.sleep(5)
            print("[sarc] backend up", flush=True)
            return
        time.sleep(3)
    print("[sarc] WARNING backend not up", flush=True)


def set_model(tag):
    cfg = json.loads(CFG.read_text())
    cfg["model_name"], cfg["vllm_endpoint"] = MODELS[tag]
    cfg["history_splitting"]["enabled"] = False
    CFG.write_text(json.dumps(cfg, indent=2))


def run_eval(sid):
    subprocess.run([PY, str(NLP / "run_eval_session.py"), "--session-id", sid,
                    "--fewshot-k", "0", "--exclude", "", "--chunk", "1", "--timeout", "2400"],
                   cwd=str(NLP))


def main():
    print("[sarc] waiting for INT-HNC (hnc_27b_50) to free the GPU ...", flush=True)
    while scored("hnc_27b_50") < 50:
        time.sleep(120)
    print("[sarc] GPU free; starting topo/morpho eval", flush=True)

    produced = []
    for tag in ("27b", "4b"):
        set_model(tag)
        restart_backend()
        for base in BASES:
            sid = f"{base}_{tag}"
            s = json.loads((SESS / f"{base}.json").read_text())
            s["session_id"] = sid
            s["annotations"] = {}
            (SESS / f"{sid}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))
            target = n_notes(sid)
            print(f"[sarc] === {sid} ({target} notes) ===", flush=True)
            for attempt in range(3):
                if scored(sid) >= target:
                    break
                if not backend_up():
                    restart_backend()
                run_eval(sid)
            produced.append(sid)
            print(f"[sarc] {sid}: {scored(sid)}/{target}", flush=True)

    # score
    subprocess.run([PY, str(NLP / "score_topo_morpho.py"), "--sessions", *produced,
                    "--name", "sarc_topomorpho_all"], cwd=str(ROOT))
    # restore 27B
    set_model("27b")
    print("[sarc] ALL DONE", flush=True)


if __name__ == "__main__":
    main()
