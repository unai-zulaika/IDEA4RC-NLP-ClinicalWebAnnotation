#!/bin/bash
# Corrected Q3 (few-shot pool quality) on the 4B production stack — FULL 8-cell
# interaction table: 4 pools x 2 sanitize settings, with REAL pool swaps.
#
# This replaces the earlier confounded Q3 cells (which used the full 'all' pool
# + a near-no-op sanitize toggle and were 86.9% identical to each other).
#
# Each cell = swap the backend FAISS store to the pool, set sanitize_fewshots,
# restart the backend, run + judge. Pools grouped to minimise swaps.
#
# Run unattended under nohup. Output -> /tmp/q3_full_4b.log
# Pre-conditions: vLLM serving 4B on :8000. Pools already rebuilt clean.

set -u
cd /home/zulaika/ClinicalAnnotationWeb/pipeline/api/nlp
PY=/home/zulaika/ClinicalAnnotationWeb/backend/.venv/bin/python
BACKEND_CFG=/home/zulaika/ClinicalAnnotationWeb/backend/config/vllm_config.json
STATUS_URL=http://localhost:8001/api/server/status

log() { echo "[$(date '+%F %T')] $*"; }

set_sanitize() {
  $PY - "$1" <<'EOF'
import json, sys
p = '/home/zulaika/ClinicalAnnotationWeb/backend/config/vllm_config.json'
d = json.load(open(p))
d['sanitize_fewshots'] = (sys.argv[1] == 'true')
json.dump(d, open(p, 'w'), indent=2)
EOF
  log "sanitize_fewshots = $1"
}

restart_backend() {
  pkill -f "uvicorn main:app --port 8001" 2>/dev/null
  sleep 4
  cd /home/zulaika/ClinicalAnnotationWeb/backend
  nohup uvicorn main:app --port 8001 >> /tmp/backend.log 2>&1 &
  disown
  cd /home/zulaika/ClinicalAnnotationWeb/pipeline/api/nlp
  for i in {1..120}; do
    if curl -sf -m 3 "${STATUS_URL}" >/dev/null 2>&1; then
      log "backend up after $((i*3))s"; sleep 5; return 0
    fi
    sleep 3
  done
  log "FATAL: backend did not come up"; exit 1
}

load_pool() {  # $1 = mode (all|complete|incomplete|note-only)
  log "loading pool '$1' into backend store"
  $PY exp_load_backend_fewshots.py --mode "$1" 2>&1 | sed 's/^/[load] /'
}

run_cell() {  # $1 = run_id label suffix (mode token), pool already loaded + sanitize set + backend restarted
  local rid="INT-SARC__4b__production__k5__$1__filter1__reason1__pre"
  log "---- cell: $1 ----"
  $PY exp_run.py --run-id "$rid" --force 2>&1 | sed "s/^/[$1] /"
  local rc=${PIPESTATUS[0]}
  [ "$rc" -ne 0 ] && { log "FATAL: cell $1 exited $rc"; exit "$rc"; }
  $PY exp_judge.py --run-id "$rid" 2>&1 | sed "s/^/[$1] /"
}

log "===== Q3 full 8-cell (4B production) starting ====="
curl -sf -m 3 http://localhost:8000/v1/models >/dev/null || { log "FATAL: vLLM down"; exit 1; }

# pool=all
load_pool all
set_sanitize true;  restart_backend; run_cell all_san1
set_sanitize false; restart_backend; run_cell all_san0

# pool=complete (1183, no placeholders -> sanitize is a no-op here, but run both for symmetry)
load_pool complete
set_sanitize true;  restart_backend; run_cell complete_san1
set_sanitize false; restart_backend; run_cell complete_san0

# pool=incomplete (421, ALL placeholders -> sanitize matters a lot here)
load_pool incomplete
set_sanitize true;  restart_backend; run_cell incomplete_san1
set_sanitize false; restart_backend; run_cell incomplete_san0

# pool=note-only (annotations blanked at build time)
load_pool note-only
set_sanitize true;  restart_backend; run_cell noteonly_san1
set_sanitize false; restart_backend; run_cell noteonly_san0

# Restore production defaults: 'all' pool + sanitize=true
load_pool all
set_sanitize true
restart_backend

log "===== Q3 full 8-cell DONE ====="
log "Summary (4B production Q3 interaction table):"
for c in all complete incomplete noteonly; do
  for s in 1 0; do
    d="INT-SARC__4b__production__k5__${c}_san${s}__filter1__reason1__pre"
    $PY - "$d" "$c" "$s" <<'EOF'
import json, sys, os
d, c, s = sys.argv[1], sys.argv[2], sys.argv[3]
p = f"/home/zulaika/ClinicalAnnotationWeb/experiments/results/{d}/metrics.json"
if os.path.exists(p):
    m = json.load(open(p))
    print(f"  pool={c:11s} sanitize={'on ' if s=='1' else 'off'}  acc={m['accuracy_pct']}%  halluc={m['hallucination_rate_pct']}%  uncertain={m['n_uncertain']}/{m['n_gold_absent']}")
else:
    print(f"  pool={c:11s} sanitize={s}  MISSING")
EOF
  done
done
