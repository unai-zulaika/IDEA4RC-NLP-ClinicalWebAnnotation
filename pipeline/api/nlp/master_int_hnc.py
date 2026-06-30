#!/usr/bin/env python3
"""Full INT-HNC question matrix (Q2/Q3/Q4/Q5/Q7) on 4B + 27B, leakage-safe.

Eval sessions (int_hnc_eval / int_hnc_eval60) exclude the few-shot-pool patients.
Dimension sweeps run on the 60-note subset (MSCI pattern); Q2 headline on the full
385-note eval set. Resumable, backend-resilient, model-switching. Run detached.

Score each finished session with:
  tools/evaluation_report/generate_report.py --session backend/sessions/<id>.json --center INT-HNC
"""
import json
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path("/home/zulaika/ClinicalAnnotationWeb")
NLP = ROOT / "pipeline" / "api" / "nlp"
SESS = ROOT / "backend" / "sessions"
CFG = ROOT / "backend" / "config" / "vllm_config.json"
PY = str(ROOT / "backend" / ".venv" / "bin" / "python")
UVICORN = str(ROOT / "backend" / ".venv" / "bin" / "uvicorn")

MODELS = {
    "4b":  ("unaizulaika/medgemma-1.5-4b-it-W4A16-G128", "http://localhost:8005/v1"),
    "27b": ("unaizulaika/medgemma-27b-text-it-W4A16-G128", "http://localhost:8000/v1"),
}

# (out_id, base_session, model, k, fast_mode, sanitize, use_filter)
# Compute-aware: 30-note subset. 27B (clean, deployable) is primary across all dims;
# 4B is the model-size contrast only (it loop-hallucinates on long Italian HNC notes,
# ~3-4 min/note, so a full 4B sweep is infeasible). 385-note runs dropped.
CONFIGS = [
    # Scoped to Q2 headline at k=5 (user decision): per-variable HNC reliability on the
    # deployable 27B + the 4B model-size contrast. 15-note subset, history-split off.
    ("hnc_27b_k5", "int_hnc_eval60", "27b", 5, False, True, False),  # Q2 headline (deployable model)
    ("hnc_4b_k5",  "int_hnc_eval60", "4b",  5, False, True, False),  # Q2 contrast
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
        f"> /tmp/backend_hnc.log 2>&1 < /dev/null &", shell=True)
    for _ in range(120):
        if backend_up():
            print("[orch] backend up", flush=True)
            time.sleep(4)
            return
        time.sleep(2)
    print("[orch] WARNING backend not up", flush=True)


def write_cfg(model_tag, sanitize):
    cfg = json.loads(CFG.read_text())
    name, endpoint = MODELS[model_tag]
    changed = False
    if cfg.get("model_name") != name:
        cfg["model_name"] = name
        cfg["vllm_endpoint"] = endpoint
        changed = True
    if cfg.get("sanitize_fewshots") != sanitize:
        cfg["sanitize_fewshots"] = sanitize
        changed = True
    if changed:
        CFG.write_text(json.dumps(cfg, indent=2))
    return changed


def report_type_mapping():
    """Empirical: which prompt_types have gold under each note_name (report type)."""
    base = json.loads((SESS / "int_hnc_eval.json").read_text())
    m = defaultdict(set)
    for n in base["notes"]:
        rt = (n.get("report_type") or "").strip()
        for part in (n.get("annotations") or "").split(" | "):
            if ": " in part:
                m[rt].add(part.split(": ", 1)[0].strip())
    return {rt: sorted(v) for rt, v in m.items()}


def build_session(out_id, base, use_filter):
    base_s = json.loads((SESS / f"{base}.json").read_text())
    s = dict(base_s)
    s["session_id"] = out_id
    s["annotations"] = {}
    s["report_type_mapping"] = report_type_mapping() if use_filter else {}
    (SESS / f"{out_id}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))
    return len(s["notes"])


def session_done(out_id, n):
    p = SESS / f"{out_id}.json"
    if not p.exists():
        return False
    try:
        return len(json.loads(p.read_text()).get("annotations", {})) >= n
    except Exception:
        return False


def main():
    t0 = time.time()
    for out_id, base, model, k, fast, sanitize, use_filter in CONFIGS:
        n_notes = len(json.loads((SESS / f"{base}.json").read_text())["notes"])
        print(f"\n[orch] === {out_id}  model={model} k={k} fast={fast} san={sanitize} "
              f"filter={use_filter} notes={n_notes} ===", flush=True)
        if session_done(out_id, n_notes):
            print(f"[orch] {out_id} complete, skip", flush=True)
            continue
        if write_cfg(model, sanitize) or not backend_up():
            restart_backend()
        if not (SESS / f"{out_id}.json").exists() or not session_done(out_id, 1):
            build_session(out_id, base, use_filter)
        for attempt in range(15):
            if session_done(out_id, n_notes):
                break
            if not backend_up():
                restart_backend()
            # chunk=1: each note is its own POST so it completes under the timeout and
            # saves incrementally (chunk=5 deadlocked: 5 heavy notes > 1800s -> retry forever)
            cmd = [PY, str(NLP / "run_eval_session.py"), "--session-id", out_id,
                   "--fewshot-k", str(k), "--exclude", "", "--chunk", "1", "--timeout", "3000"]
            if fast:
                cmd.append("--fast-mode")
            print(f"[orch] run {out_id} attempt {attempt}", flush=True)
            subprocess.run(cmd, cwd=str(NLP))
        print(f"[orch] {out_id}: {'DONE' if session_done(out_id, n_notes) else 'INCOMPLETE'}", flush=True)
    # restore 27B + sanitize-on
    write_cfg("27b", True)
    print(f"\n[orch] ALL INT-HNC RUNS DONE in {(time.time()-t0)/3600:.2f}h", flush=True)


if __name__ == "__main__":
    main()
