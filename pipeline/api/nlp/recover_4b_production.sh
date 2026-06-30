#!/bin/bash
# Master recovery script for the 4B production sweep.
#
# Rebuilds the FAISS pools with the correct -int-sarc suffix, reloads the
# backend, then re-runs the full 4B production sweep (K + filter + reasoning),
# the complete-effective cell, and the incomplete-faithful cell, with the
# required backend restart between the latter two. Judges everything and
# regenerates analysis artifacts.
#
# Designed to run unattended under nohup. All output appended to
# /tmp/recover_4b.log. Pre-conditions: vLLM serving 4B on :8000.

set -u
cd /home/zulaika/ClinicalAnnotationWeb/pipeline/api/nlp
PY=/home/zulaika/ClinicalAnnotationWeb/backend/.venv/bin/python
BACKEND_CFG=/home/zulaika/ClinicalAnnotationWeb/backend/config/vllm_config.json
STATUS_URL=http://localhost:8001/api/server/status

log() { echo "[$(date '+%F %T')] $*"; }

set_sanitize() {
  local val="$1"
  $PY - <<EOF
import json
p = '${BACKEND_CFG}'
d = json.load(open(p))
d['sanitize_fewshots'] = ${val}
json.dump(d, open(p, 'w'), indent=2)
EOF
  log "sanitize_fewshots set to ${val}"
}

restart_backend() {
  log "restarting backend..."
  pkill -f "uvicorn main:app --port 8001" 2>/dev/null
  sleep 4
  cd /home/zulaika/ClinicalAnnotationWeb/backend
  nohup uvicorn main:app --port 8001 >> /tmp/backend.log 2>&1 &
  disown
  cd - >/dev/null
  for i in {1..120}; do
    if curl -sf -m 3 "${STATUS_URL}" >/dev/null 2>&1; then
      log "backend up after $((i*3))s"
      sleep 5
      return 0
    fi
    sleep 3
  done
  log "FATAL: backend did not come up"
  return 1
}

run_step() {
  local name="$1"; shift
  log "---- step: ${name} ----"
  "$@" 2>&1 | sed "s/^/[${name}] /"
  local rc=${PIPESTATUS[0]}
  if [ "${rc}" -ne 0 ]; then
    log "FATAL: ${name} exited ${rc}"
    exit "${rc}"
  fi
}

log "===== 4B production recovery starting ====="

# 0. Sanity-check vLLM
if ! curl -sf -m 3 http://localhost:8000/v1/models >/dev/null; then
  log "FATAL: vLLM not reachable on :8000"
  exit 1
fi
log "vLLM is up"

# 1. Rebuild the FAISS pools (correct suffix now)
run_step rebuild-pools $PY exp_build_fewshots.py --center INT-SARC

# 2. Load the 'all' pool into the backend store
run_step load-pool-all $PY exp_load_backend_fewshots.py --mode all

# 3. sanitize=true for the anchor + prod sweep + complete cell
set_sanitize True
restart_backend

# 4. Quick verification: hit the status endpoint, watch backend log for absence
#    of "No index found" warnings on the next request.
log "first 5 [WARN] lines in backend log AFTER restart (should NOT mention -int-sarc):"
sleep 2
tail -50 /tmp/backend.log | grep -E "WARN|index|loaded" | tail -10 | sed 's/^/  /'

# 5. Re-run the 4B production sweep (7 cells), forcing overwrite
run_step prod-sweep $PY exp_run.py --model 4b --prod-sweep --force

# 6. Run the complete-effective cell (sanitize already true)
run_step complete-effective $PY exp_run.py \
  --run-id INT-SARC__4b__production__k5__complete__filter1__reason1__pre --force

# 7. Flip to sanitize=false, restart, run the incomplete-faithful cell
set_sanitize False
restart_backend
run_step incomplete-faithful $PY exp_run.py \
  --run-id INT-SARC__4b__production__k5__incomplete__filter1__reason1__pre --force

# 8. Restore sanitize=true so the backend is left in production-default state
set_sanitize True

# 9. Judge everything
run_step judge-all $PY exp_judge.py --all

# 10. Regenerate analysis artifacts
run_step analyze $PY exp_analyze.py --all --model 4b --stack production
run_step raw-vs-prod $PY exp_raw_vs_prod.py --model 4b

log "===== 4B production recovery DONE ====="
log "Summary of all 4B production metrics:"
ls -1 /home/zulaika/ClinicalAnnotationWeb/experiments/results/ \
  | grep "INT-SARC__4b__production" \
  | while read d; do
      $PY - <<EOF
import json
m = json.load(open('/home/zulaika/ClinicalAnnotationWeb/experiments/results/${d}/metrics.json'))
print(f'  ${d}  acc={m["accuracy_pct"]}%  halluc={m["hallucination_rate_pct"]}%  uncertain={m["n_uncertain"]}/{m["n_gold_absent"]}')
EOF
  done
