#!/usr/bin/env python3
"""Overnight: INT-SARC 28-note set on 27B then 4B (k=0, history-split off, strict scorer),
so the per-centre comparison can include INT-SARC. Direct run_eval (no orchestrator thrash).
Leaves scored sessions intsarc_27b / intsarc_4b and writes exp_out/intsarc_results.json.
"""
import json
import subprocess
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path("/home/zulaika/ClinicalAnnotationWeb")
NLP = ROOT / "pipeline" / "api" / "nlp"
SESS = ROOT / "backend" / "sessions"
CFG = ROOT / "backend" / "config" / "vllm_config.json"
OUT = ROOT / "exp_out"
PY = str(ROOT / "backend" / ".venv" / "bin" / "python")
UVICORN = str(ROOT / "backend" / ".venv" / "bin" / "uvicorn")
MODELS = {"27b": ("unaizulaika/medgemma-27b-text-it-W4A16-G128", "http://localhost:8000/v1"),
          "4b": ("unaizulaika/medgemma-1.5-4b-it-W4A16-G128", "http://localhost:8005/v1")}


def scored(sid):
    try:
        return len(json.loads((SESS / f"{sid}.json").read_text()).get("annotations", {}))
    except Exception:
        return 0


def backend_up():
    try:
        urllib.request.urlopen("http://localhost:8001/api/server/status", timeout=10); return True
    except Exception:
        return False


def restart_backend():
    subprocess.run("fuser -k 8001/tcp", shell=True, stderr=subprocess.DEVNULL); time.sleep(4)
    subprocess.Popen(f"cd {ROOT}/backend && setsid nohup {UVICORN} main:app --port 8001 "
                     f"> /tmp/backend_intsarc.log 2>&1 < /dev/null &", shell=True)
    for _ in range(120):
        if backend_up():
            time.sleep(5); print("[intsarc] backend up", flush=True); return
        time.sleep(3)
    print("[intsarc] WARNING backend not up", flush=True)


def set_model(tag):
    cfg = json.loads(CFG.read_text())
    cfg["model_name"], cfg["vllm_endpoint"] = MODELS[tag]
    cfg["history_splitting"]["enabled"] = False
    CFG.write_text(json.dumps(cfg, indent=2))


def run_eval(sid):
    subprocess.run([PY, str(NLP / "run_eval_session.py"), "--session-id", sid, "--fewshot-k", "5",
                    "--exclude", "", "--chunk", "1", "--timeout", "2400"], cwd=str(NLP))


def base_of(pt):
    for suf in ("-int-sarc", "-int"):
        if pt.endswith(suf):
            return pt[:-len(suf)]
    return pt


def pervar(sid):
    d = json.loads((SESS / f"{sid}.json").read_text())
    agg = defaultdict(lambda: defaultdict(int))
    for note in d.get("annotations", {}).values():
        for pt, e in note.items():
            if isinstance(e, dict):
                mt = (e.get("evaluation_result") or {}).get("match_type")
                if mt:
                    agg[base_of(pt)][mt] += 1
    rows = {}
    tot = defaultdict(int)
    for b, c in agg.items():
        for k, v in c.items():
            tot[k] += v
        m, mm, fp, fn, be = (c["match"], c["mismatch"], c["false_positive"], c["false_negative"], c["both_empty"])
        rows[b] = {"acc": round(m / (m + mm) * 100) if (m + mm) else None, "gp": m + mm + fn,
                   "fp": round(fp / (m + mm + fp + fn + be) * 100) if (m + mm + fp + fn + be) else None}
    m, mm = tot["match"], tot["mismatch"]
    n = sum(tot.values())
    overall = {"acc": round(m / (m + mm) * 100) if (m + mm) else None,
               "fp": round(tot["false_positive"] / n * 100) if n else None}
    return rows, overall


def main():
    t0 = time.time()
    base = json.loads((SESS / "intsarc_eval.json").read_text())
    target = len(base["notes"])
    for tag in ("27b", "4b"):
        sid = f"intsarc_{tag}"
        set_model(tag); restart_backend()
        s = dict(base); s["session_id"] = sid; s["annotations"] = {}
        s["report_type_mapping"] = {}            # no per-note filter (old map used -int-sarc keys)
        (SESS / f"{sid}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))
        print(f"[intsarc] === {sid} ({target} notes) ===", flush=True)
        for attempt in range(4):
            if scored(sid) >= target:
                break
            if not backend_up():
                restart_backend()
            run_eval(sid)
        print(f"[intsarc] {sid}: {scored(sid)}/{target}", flush=True)
    # score
    r27, o27 = pervar("intsarc_27b"); r4, o4 = pervar("intsarc_4b")
    OUT.mkdir(exist_ok=True)
    res = {"center": "INT-SARC", "notes": target,
           "overall": {"4B": o4, "27B": o27},
           "per_variable": {b: {"4B": r4.get(b), "27B": r27.get(b)} for b in sorted(set(r27) | set(r4))}}
    (OUT / "intsarc_results.json").write_text(json.dumps(res, indent=2))
    set_model("27b")  # restore
    print(f"[intsarc] DONE in {(time.time()-t0)/3600:.2f}h  | 4B acc={o4['acc']} fp={o4['fp']} | 27B acc={o27['acc']} fp={o27['fp']}", flush=True)
    print(f"[intsarc] wrote {OUT/'intsarc_results.json'}", flush=True)


if __name__ == "__main__":
    main()
