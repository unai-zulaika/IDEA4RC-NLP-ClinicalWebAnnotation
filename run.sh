#!/bin/bash

# Script to run both backend and frontend with logs
# Usage: ./run.sh

# Don't exit on error - we want to handle cleanup properly
set +e

# Load nvm if it exists (needed for npm to be available)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion


# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Function to cleanup background processes on exit
cleanup() {
    local exit_code=${1:-0}
    echo -e "\n${YELLOW}Shutting down services...${NC}"
    if [ ! -z "$TAIL_BACKEND_PID" ]; then
        kill $TAIL_BACKEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$TAIL_FRONTEND_PID" ]; then
        kill $TAIL_FRONTEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    # Clean up log files
    if [ ! -z "$BACKEND_LOG" ] && [ -f "$BACKEND_LOG" ]; then
        rm -f "$BACKEND_LOG"
    fi
    if [ ! -z "$FRONTEND_LOG" ] && [ -f "$FRONTEND_LOG" ]; then
        rm -f "$FRONTEND_LOG"
    fi
    echo -e "${GREEN}Cleanup complete.${NC}"
    exit $exit_code
}

# Set up trap to cleanup on script exit
trap 'cleanup 130' SIGINT
trap 'cleanup 143' SIGTERM
trap 'cleanup ${EXIT_CODE:-0}' EXIT

# Check if backend directory exists
if [ ! -d "$BACKEND_DIR" ]; then
    echo -e "${RED}Error: Backend directory not found at $BACKEND_DIR${NC}"
    exit 1
fi

# Check if frontend directory exists
if [ ! -d "$FRONTEND_DIR" ]; then
    echo -e "${RED}Error: Frontend directory not found at $FRONTEND_DIR${NC}"
    exit 1
fi

# Check if npm is available
if ! command -v npm &> /dev/null; then
    echo -e "${RED}Error: npm is not installed or not in PATH${NC}"
    exit 1
fi

# Check if node_modules exists in frontend
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo -e "${YELLOW}Warning: node_modules not found in frontend directory${NC}"
    echo -e "${YELLOW}You may need to run 'npm install' in the frontend directory first${NC}"
fi

echo -e "${GREEN}Starting Clinical Annotation Web Application...${NC}"
echo -e "${BLUE}Backend:${NC} FastAPI on http://localhost:8001"
echo -e "${BLUE}Frontend:${NC} Next.js on http://localhost:3000"
echo -e "${YELLOW}Press Ctrl+C to stop both services${NC}\n"

# Create temporary log files
BACKEND_LOG=$(mktemp)
FRONTEND_LOG=$(mktemp)

# Start backend
echo -e "${GREEN}Starting backend...${NC}"
cd "$BACKEND_DIR" || {
    echo -e "${RED}Error: Failed to change to backend directory${NC}"
    exit 1
}

# Use subshell to ensure proper directory context
(cd "$BACKEND_DIR" && bash run.sh > "$BACKEND_LOG" 2>&1) &
BACKEND_PID=$!

# Verify backend process started
sleep 2
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}Error: Backend failed to start${NC}"
    echo -e "${YELLOW}Backend log output:${NC}"
    if [ -s "$BACKEND_LOG" ]; then
        cat "$BACKEND_LOG"
    else
        echo -e "  (log file is empty - process may have exited immediately)"
    fi
    exit 1
fi

# Start frontend
echo -e "${GREEN}Starting frontend...${NC}"
cd "$FRONTEND_DIR" || {
    echo -e "${RED}Error: Failed to change to frontend directory${NC}"
    exit 1
}

# Verify we're in the right directory and package.json exists
if [ ! -f "package.json" ]; then
    echo -e "${RED}Error: package.json not found in frontend directory${NC}"
    exit 1
fi

# Use nohup to ensure process continues even if terminal disconnects
# and run in the frontend directory explicitly
(cd "$FRONTEND_DIR" && npm run dev > "$FRONTEND_LOG" 2>&1) &
FRONTEND_PID=$!

# Verify frontend process started
sleep 3
if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    echo -e "${RED}Error: Frontend failed to start${NC}"
    echo -e "${YELLOW}Frontend log output:${NC}"
    if [ -s "$FRONTEND_LOG" ]; then
        cat "$FRONTEND_LOG"
    else
        echo -e "  (log file is empty - process may have exited immediately)"
    fi
    echo -e "\n${YELLOW}Troubleshooting tips:${NC}"
    echo -e "  1. Check if node_modules exists: ls -la $FRONTEND_DIR/node_modules"
    echo -e "  2. Try running manually: cd $FRONTEND_DIR && npm run dev"
    exit 1
fi

# Show initial logs to verify both are starting
echo -e "${GREEN}Verifying services started...${NC}"
sleep 1
if [ -s "$BACKEND_LOG" ]; then
    echo -e "${BLUE}Backend initial output:${NC}"
    head -5 "$BACKEND_LOG" | sed "s/^/  /"
fi
if [ -s "$FRONTEND_LOG" ]; then
    echo -e "${GREEN}Frontend initial output:${NC}"
    head -5 "$FRONTEND_LOG" | sed "s/^/  /"
fi

# Show logs
echo -e "\n${GREEN}Both services are running. Logs will appear below:${NC}\n"
echo -e "${YELLOW}========================================${NC}\n"

# Tail both log files with colored prefixes in background
# Using bash while loop to properly interpret color codes
(
    tail -f "$BACKEND_LOG" | while IFS= read -r line || [ -n "$line" ]; do
        echo -e "${BLUE}[BACKEND]${NC} ${line}"
    done
) &
TAIL_BACKEND_PID=$!

(
    tail -f "$FRONTEND_LOG" | while IFS= read -r line || [ -n "$line" ]; do
        echo -e "${GREEN}[FRONTEND]${NC} ${line}"
    done
) &
TAIL_FRONTEND_PID=$!

# Wait for backend or frontend to exit
wait $BACKEND_PID $FRONTEND_PID
EXIT_CODE=$?

