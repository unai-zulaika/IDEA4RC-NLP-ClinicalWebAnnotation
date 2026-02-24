#!/bin/bash

# Script to run the NLP pipeline (API + Streamlit status web)
# Usage: ./run.sh

set +e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$SCRIPT_DIR/api"
STATUS_DIR="$SCRIPT_DIR/status_web"

cleanup() {
    local exit_code=${1:-0}
    echo -e "\n${YELLOW}Shutting down pipeline services...${NC}"
    [ -n "$TAIL_API_PID" ] && kill $TAIL_API_PID 2>/dev/null
    [ -n "$TAIL_STATUS_PID" ] && kill $TAIL_STATUS_PID 2>/dev/null
    [ -n "$API_PID" ] && kill $API_PID 2>/dev/null
    [ -n "$STATUS_PID" ] && kill $STATUS_PID 2>/dev/null
    [ -f "$API_LOG" ] && rm -f "$API_LOG"
    [ -f "$STATUS_LOG" ] && rm -f "$STATUS_LOG"
    echo -e "${GREEN}Cleanup complete.${NC}"
    exit $exit_code
}

trap 'cleanup 130' SIGINT
trap 'cleanup 143' SIGTERM
trap 'cleanup ${EXIT_CODE:-0}' EXIT

# Validate directories
for dir in "$API_DIR" "$STATUS_DIR"; do
    if [ ! -d "$dir" ]; then
        echo -e "${RED}Error: Directory not found: $dir${NC}"
        exit 1
    fi
done

# Set up virtual environments if missing
setup_venv() {
    local dir="$1"
    local name="$2"
    if [ ! -d "$dir/.venv" ]; then
        echo -e "${YELLOW}Creating virtual environment for $name...${NC}"
        python3 -m venv "$dir/.venv"
        "$dir/.venv/bin/pip" install --upgrade pip -q
        "$dir/.venv/bin/pip" install -r "$dir/requirements.txt" -q
    fi
}

setup_venv "$API_DIR" "API"
setup_venv "$STATUS_DIR" "Status Web"

echo -e "${GREEN}Starting NLP Pipeline...${NC}"
echo -e "${BLUE}API:${NC}        http://localhost:8010"
echo -e "${BLUE}Status Web:${NC} http://localhost:8501"
echo -e "${YELLOW}Press Ctrl+C to stop both services${NC}\n"

API_LOG=$(mktemp)
STATUS_LOG=$(mktemp)

# Start API backend
echo -e "${GREEN}Starting pipeline API...${NC}"
(cd "$API_DIR" && PYTHONPATH="$API_DIR:$PYTHONPATH" .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8010 --reload > "$API_LOG" 2>&1) &
API_PID=$!

sleep 2
if ! kill -0 $API_PID 2>/dev/null; then
    echo -e "${RED}Error: Pipeline API failed to start${NC}"
    [ -s "$API_LOG" ] && cat "$API_LOG"
    exit 1
fi

# Start Streamlit status web
echo -e "${GREEN}Starting status web...${NC}"
(cd "$STATUS_DIR" && .venv/bin/streamlit run app.py --server.port=8501 --server.address=0.0.0.0 > "$STATUS_LOG" 2>&1) &
STATUS_PID=$!

sleep 3
if ! kill -0 $STATUS_PID 2>/dev/null; then
    echo -e "${RED}Error: Status web failed to start${NC}"
    [ -s "$STATUS_LOG" ] && cat "$STATUS_LOG"
    exit 1
fi

echo -e "\n${GREEN}Both pipeline services are running. Logs below:${NC}\n"
echo -e "${YELLOW}========================================${NC}\n"

(
    tail -f "$API_LOG" | while IFS= read -r line || [ -n "$line" ]; do
        echo -e "${BLUE}[API]${NC} ${line}"
    done
) &
TAIL_API_PID=$!

(
    tail -f "$STATUS_LOG" | while IFS= read -r line || [ -n "$line" ]; do
        echo -e "${GREEN}[STATUS]${NC} ${line}"
    done
) &
TAIL_STATUS_PID=$!

wait $API_PID $STATUS_PID
EXIT_CODE=$?
