#!/bin/bash
# Development startup script
# Usage: ./scripts/dev.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Starting Clinical Annotation Platform in development mode..."
echo ""
echo "Services:"
echo "  - Annotation API:  http://localhost:8001"
echo "  - Annotation Web:  http://localhost:3000"
echo "  - Pipeline API:    http://localhost:8000 (if started)"
echo "  - Pipeline Dashboard: http://localhost:8501 (if started)"
echo ""

# Run the main run.sh from project root
cd "$PROJECT_DIR"
./run.sh
