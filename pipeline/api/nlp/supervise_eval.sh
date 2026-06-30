#!/usr/bin/env bash
# Supervisor for a long eval run: keep resuming run_eval_session.py, and if the
# backend dies, restart it and resume, until all sampled notes are scored.
# Robust to backend SIGKILL / blips and to disconnects (run it backgrounded).
#   ./supervise_eval.sh <session-id> <sample> <seed> <target>
set -u
ROOT=/home/zulaika/ClinicalAnnotationWeb
PY="$ROOT/backend/.venv/bin/python"
UVICORN="$ROOT/backend/.venv/bin/uvicorn"
SID="${1:-msci_phase2_4b}"
SAMPLE="${2:-400}"
SEED="${3:-42}"
TARGET="${4:-$SAMPLE}"

count_done() {
  "$PY" - "$SID" <<'PY'
import json, sys
p = f"/home/zulaika/ClinicalAnnotationWeb/backend/sessions/{sys.argv[1]}.json"
try:
    print(len(json.load(open(p, encoding="utf-8")).get("annotations", {})))
except Exception:
    print(0)
PY
}

ensure_backend() {
  if curl -s --max-time 4 http://localhost:8001/api/server/status >/dev/null 2>&1; then
    return
  fi
  echo "[sup] backend down -> restarting"
  local P
  P=$(fuser 8001/tcp 2>/dev/null)
  [ -n "$P" ] && kill $P 2>/dev/null
  for p in $P; do timeout 15 tail --pid="$p" -f /dev/null 2>/dev/null; done
  ( cd "$ROOT/backend" && setsid nohup "$UVICORN" main:app --port 8001 > /tmp/backend_4b.log 2>&1 < /dev/null & )
  curl -s --retry 60 --retry-delay 2 --retry-connrefused --max-time 120 \
    http://localhost:8001/api/server/status >/dev/null 2>&1
}

for attempt in $(seq 1 30); do
  d=$(count_done)
  echo "[sup] attempt $attempt: $d/$TARGET scored"
  if [ "$d" -ge "$TARGET" ]; then echo "[sup] DONE ($d/$TARGET)"; break; fi
  ensure_backend
  # run_eval_session resumes by default (skips already-scored notes); no --resume flag.
  ( cd "$ROOT/pipeline/api/nlp" && "$PY" run_eval_session.py \
      --session-id "$SID" --sample "$SAMPLE" --seed "$SEED" ) \
    || echo "[sup] run exited nonzero (backend likely died) - retrying"
done
echo "[sup] FINAL: $(count_done)/$TARGET scored"
