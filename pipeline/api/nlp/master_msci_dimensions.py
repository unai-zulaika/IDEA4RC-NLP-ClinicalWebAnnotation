#!/usr/bin/env python3
"""Orchestrate the MSCI dimension sweep on the 4B / 60-note set, unattended.

Dimensions (k5/all/filter-on/reason-on/sanitize-on is the shared baseline):
  Q4 few-shot count : k = 0,1,3,5,10
  Q5 report filter  : filter off  (session built without report_type_mapping)
  Q7 reasoning      : reasoning off (--fast-mode)
  Q3 pool cleanliness: sanitize_fewshots off (realistic/placeholdered)

One session per config (resumable). Auto-restarts the backend if it dies, toggles
sanitize_fewshots for Q3, and restores it at the end. Built to survive disconnect.
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
EXCLUDE = "necrosis_in_biopsy-msci"   # match the 60-note baseline (recur_or_prog kept)
sys.path.insert(0, str(NLP))
from run_msci_eval import build_session  # noqa: E402

# (out_id, fewshot_k, fast_mode, use_filter, sanitize)
CONFIGS = [
    ("msci60_4b_k0",        0, False, True,  True),
    ("msci60_4b_k1",        1, False, True,  True),
    ("msci60_4b_k3",        3, False, True,  True),
    ("msci60_4b_k5",        5, False, True,  True),   # baseline
    ("msci60_4b_k10",      10, False, True,  True),
    ("msci60_4b_nofilter",  5, False, False, True),   # Q5
    ("msci60_4b_noreason",  5, True,  True,  True),    # Q7
    ("msci60_4b_sanoff",    5, False, True,  False),   # Q3
]


def backend_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:8001/api/server/status", timeout=4)
        return True
    except Exception:
        return False


def restart_backend() -> None:
    subprocess.run("fuser -k 8001/tcp", shell=True, stderr=subprocess.DEVNULL)
    time.sleep(3)
    subprocess.Popen(
        f"cd {ROOT}/backend && setsid nohup {UVICORN} main:app --port 8001 "
        f"> /tmp/backend_dim.log 2>&1 < /dev/null &", shell=True)
    for _ in range(90):
        if backend_up():
            print("[orch] backend up", flush=True)
            return
        time.sleep(2)
    print("[orch] WARNING: backend did not come back up", flush=True)


def set_sanitize(val: bool) -> None:
    cfg = json.loads(CFG.read_text())
    if cfg.get("sanitize_fewshots") == val:
        if not backend_up():
            restart_backend()
        return
    cfg["sanitize_fewshots"] = val
    CFG.write_text(json.dumps(cfg, indent=2))
    print(f"[orch] sanitize_fewshots={val} -> restart", flush=True)
    restart_backend()


def session_done(out_id: str, n: int = 60) -> bool:
    p = SESS / f"{out_id}.json"
    if not p.exists():
        return False
    try:
        return len(json.loads(p.read_text()).get("annotations", {})) >= n
    except Exception:
        return False


def main() -> None:
    t0 = time.time()
    for out_id, k, fast, use_filter, sanitize in CONFIGS:
        print(f"\n[orch] === {out_id}  k={k} fast={fast} filter={use_filter} san={sanitize} ===", flush=True)
        if session_done(out_id):
            print(f"[orch] {out_id} already complete, skip", flush=True)
            continue
        set_sanitize(sanitize)
        if not (SESS / f"{out_id}.json").exists():
            s = build_session(0, use_filter, out_id, f"MSCI 4B dim {out_id}", {EXCLUDE})
            (SESS / f"{out_id}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))
            print(f"[orch] built session {out_id} ({len(s['notes'])} notes)", flush=True)
        for attempt in range(12):
            if session_done(out_id):
                break
            if not backend_up():
                restart_backend()
            cmd = [PY, str(NLP / "run_eval_session.py"), "--session-id", out_id,
                   "--fewshot-k", str(k), "--exclude", EXCLUDE, "--chunk", "10"]
            if fast:
                cmd.append("--fast-mode")
            print(f"[orch] run {out_id} attempt {attempt}", flush=True)
            subprocess.run(cmd, cwd=str(NLP))
        print(f"[orch] {out_id}: {'DONE' if session_done(out_id) else 'INCOMPLETE'}", flush=True)

    set_sanitize(True)  # restore default for later runs
    print(f"\n[orch] ALL DONE in {(time.time()-t0)/3600:.2f}h", flush=True)


if __name__ == "__main__":
    main()
