#!/bin/bash
# Run FastAPI backend server

cd "$(dirname "$0")"
uvicorn main:app --reload --host 0.0.0.0 --port 8001

