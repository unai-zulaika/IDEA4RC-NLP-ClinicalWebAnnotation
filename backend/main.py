"""
FastAPI Backend for Clinical Data Curation Platform
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import sys

# Install uvloop for faster async event loop (if available)
try:
    import uvloop
    uvloop.install()
    print("[INFO] uvloop installed — using optimized event loop")
except ImportError:
    pass

# No need to add parent directory - all modules are now local

from routes import server, prompts, upload, annotate, sessions, presets

app = FastAPI(
    title="Clinical Data Curation API",
    description="API for clinical note annotation and curation",
    version="1.0.0"
)

# Configure CORS
import os as _os

_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]

# Allow additional origins via CORS_ORIGINS env var (comma-separated)
_extra_origins = _os.environ.get("CORS_ORIGINS", "")
if _extra_origins:
    _cors_origins.extend([o.strip() for o in _extra_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(server.router, prefix="/api/server", tags=["server"])
app.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(annotate.router, prefix="/api/annotate", tags=["annotate"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(presets.router, prefix="/api/presets", tags=["presets"])


# Prometheus metrics instrumentation
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    print("[INFO] Prometheus metrics enabled at /metrics")
except ImportError:
    print("[WARN] prometheus-fastapi-instrumentator not available, /metrics endpoint disabled")


@app.get("/")
async def root():
    return {"message": "Clinical Data Curation API", "version": "1.0.0"}


@app.get("/api/health")
async def health():
    return {"status": "healthy"}

