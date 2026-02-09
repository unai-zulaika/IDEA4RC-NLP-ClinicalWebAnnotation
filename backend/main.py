"""
FastAPI Backend for Clinical Data Curation Platform
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import sys

# No need to add parent directory - all modules are now local

from routes import server, prompts, upload, annotate, sessions

app = FastAPI(
    title="Clinical Data Curation API",
    description="API for clinical note annotation and curation",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],  # Next.js default + deployed port
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


@app.get("/")
async def root():
    return {"message": "Clinical Data Curation API", "version": "1.0.0"}


@app.get("/api/health")
async def health():
    return {"status": "healthy"}

