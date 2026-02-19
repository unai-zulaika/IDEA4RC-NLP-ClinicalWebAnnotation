# Clinical Annotation Platform

A comprehensive platform for human-in-the-loop annotation of clinical notes using LLM-powered extraction, with integrated NLP pipeline for data ingestion and quality validation.

## Overview

This platform provides:
- **Annotation Web Interface**: Human-in-the-loop review of LLM-extracted clinical entities
- **Annotation API**: FastAPI backend for LLM inference, session management, and ICD-O-3 code lookup
- **NLP Pipeline**: Automated data ingestion, entity linking, and quality checks
- **Pipeline Dashboard**: Streamlit-based monitoring for pipeline status and progress

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │           Annotation Web UI                  │
                    │           (Next.js, port 3000)              │
                    └─────────────────┬───────────────────────────┘
                                      │ HTTP
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Annotation API                               │
│                 (FastAPI, port 8001)                            │
│  • Session management     • Few-shot retrieval (FAISS)          │
│  • vLLM integration       • ICD-O-3 code lookup                 │
│  • Prompt management      • Annotation evaluation               │
└─────────────────────────────────────────────────────────────────┘
                                      │
               ┌──────────────────────┼──────────────────────┐
               ▼                      ▼                      ▼
┌──────────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
│   Pipeline API       │  │   vLLM Server    │  │  Pipeline Dashboard  │
│ (FastAPI, port 8000) │  │ (port configured)│  │ (Streamlit, port 8501)│
│ • NLP processing     │  │ • LLM inference  │  │ • Progress monitoring │
│ • Entity linking     │  │                  │  │ • Task management     │
│ • Quality checks     │  │                  │  │ • Quality reports     │
└──────────────────────┘  └──────────────────┘  └──────────────────────┘
```

## Prerequisites & Host Setup

### Minimum Requirements

| Component | Requirement |
|-----------|-------------|
| **OS** | Linux (tested on Ubuntu 22.04+) |
| **Docker** | Docker Engine 24+ with Compose V2 |
| **RAM** | 8 GB minimum (16 GB recommended) |

### GPU Requirements (for LLM inference)

LLM inference requires an NVIDIA GPU. This applies whether you run vLLM inside Docker or externally.

| Component | Requirement |
|-----------|-------------|
| **GPU** | NVIDIA GPU with sufficient VRAM for your model (24 GB+ for 27B models, 8 GB+ for 3B models) |
| **NVIDIA Driver** | 550+ (CUDA 12.4) or 570+ (CUDA 12.8+) |
| **CUDA** | 12.4+ (bundled with the driver) |

Check your current driver and CUDA version:

```bash
nvidia-smi
```

### Installing Docker

```bash
# Install Docker (if not already installed)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for the group change to take effect
```

### Installing NVIDIA Container Toolkit (required for vLLM in Docker)

Skip this if you plan to run vLLM outside Docker.

```bash
# Add the NVIDIA Container Toolkit repository
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Install and configure
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify GPU access from Docker
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

## Quick Start

### 1. Clone and configure

```bash
git clone <repository-url>
cd clinical-annotation-platform
cp .env.example .env
```

Edit `.env` to set your vLLM model and parameters (see [vLLM Configuration](#vllm-configuration)).

### 2. Choose a deployment mode

There are two ways to deploy the platform, depending on whether you want vLLM managed by Docker or running separately.

---

#### Option A: Full stack with vLLM in Docker (GPU required)

Everything runs in Docker, including the vLLM inference server. Requires NVIDIA Container Toolkit (see above).

```bash
docker compose -f docker-compose.yml -f docker-compose.vllm.yml up -d
```

This starts all 5 services. The annotation API automatically connects to vLLM via the Docker network. On the first run, the model weights are downloaded and cached in a Docker volume.

| Service | URL |
|---------|-----|
| Annotation UI | http://localhost:3000 |
| Annotation API | http://localhost:8001 |
| Pipeline API | http://localhost:8000 |
| Pipeline Dashboard | http://localhost:8501 |
| vLLM API | http://localhost:8080 |

To stop everything:

```bash
docker compose -f docker-compose.yml -f docker-compose.vllm.yml down
```

**CUDA compatibility note:** The default vLLM image (`vllm/vllm-openai:latest`) requires a recent NVIDIA driver. If you get a `forward compatibility was attempted on non supported HW` error, either upgrade your driver or set a compatible image in `.env`:

```bash
# For NVIDIA driver 550.x / CUDA 12.4
VLLM_IMAGE=vastai/vllm:v0.8.5-cuda-12.4-pytorch-2.6.0-py312
```

---

#### Option B: App in Docker + vLLM running externally

The 4 application services run in Docker. You run vLLM separately (in a virtual environment, on a different machine, etc.). This is useful if you already have a vLLM setup or need more control over the GPU environment.

**Step 1 — Start vLLM externally:**

```bash
# In a virtual environment with vllm installed
pip install vllm

vllm serve unsloth/medgemma-27b-text-it-unsloth-bnb-4bit \
  --max-model-len 16384 \
  --max-num-seqs 32 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager
```

vLLM will serve on `http://localhost:8000` by default.

**Step 2 — Start the application:**

```bash
docker compose up -d
```

The annotation API connects to vLLM at `http://host.docker.internal:8000` (the host machine's port 8000). To change this, set `VLLM_API_URL` in `.env`:

```bash
# Example: vLLM running on a different machine
VLLM_API_URL=http://192.168.1.100:8000
```

| Service | URL |
|---------|-----|
| Annotation UI | http://localhost:3000 |
| Annotation API | http://localhost:8001 |
| Pipeline API | http://localhost:8000 |
| Pipeline Dashboard | http://localhost:8501 |

To stop the app:

```bash
docker compose down
```

### 3. Verify the deployment

```bash
# Check all containers are running
docker ps

# Check annotation API health
curl http://localhost:8001/api/server/status

# Check vLLM is reachable (use port 8080 for Option A, 8000 for Option B)
curl http://localhost:8080/v1/models
```

---

### Option C: Bare-Metal Deployment (without Docker)

Deploy each component directly on the host. This gives full control over each service and avoids the Docker layer entirely.

#### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **OS** | Linux (Ubuntu 22.04+ recommended) | macOS works for development |
| **Python** | 3.11+ | 3.9+ for the pipeline dashboard only |
| **Node.js** | 20+ | With npm |
| **NVIDIA GPU** | Optional | Required only if running vLLM locally |
| **NVIDIA Driver** | 550+ / CUDA 12.4+ | Only if using a GPU |
| **build-essential, cmake** | Latest | Needed to compile native Python deps (FAISS, torch, etc.) |

Install system packages (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake curl git
```

#### 1. Clone and configure

```bash
git clone <repository-url>
cd clinical-annotation-platform
cp .env.example .env
```

Edit `.env` to match your bare-metal setup. The key variables are:

```bash
# Point to wherever your vLLM server is running
VLLM_API_URL=http://localhost:8000

# The annotation API port (backend)
ANNOTATION_API_PORT=8001

# The URL the frontend uses to reach the backend (browser-side, so use localhost or your host IP)
NEXT_PUBLIC_API_URL=http://localhost:8001

# Pipeline ↔ backend/frontend communication
NLP_BACKEND_URL=http://localhost:8001
NLP_FRONTEND_URL=http://localhost:3000
```

---

#### 2. Backend (Annotation API)

The backend is a FastAPI application that handles sessions, prompts, CSV uploads, LLM inference via vLLM, FAISS-based few-shot retrieval, and ICD-O-3 code lookup.

**Port:** 8001

```bash
cd backend

# Create and activate a virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies (includes PyTorch, FAISS, vLLM client, sentence-transformers, etc.)
pip install -r requirements.txt
```

**Create required directories** (these are normally created by Docker):

```bash
mkdir -p sessions data/faiss_store
```

**Configure the vLLM connection.** The backend reads `config/vllm_config.json`:

```json
{
  "use_vllm": true,
  "vllm_endpoint": "http://localhost:8000/v1",
  "model_name": "unsloth/medgemma-27b-text-it-unsloth-bnb-4bit",
  "batch_size": 8,
  "timeout": 150
}
```

Update `vllm_endpoint` to match your vLLM server address. These values can also be overridden with environment variables: `VLLM_ENDPOINT`, `VLLM_MODEL_NAME`, `VLLM_BATCH_SIZE`, `VLLM_TIMEOUT`.

**Start the backend:**

```bash
# Development (with auto-reload)
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Production
uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4
```

**Verify:**

```bash
curl http://localhost:8001/api/server/status
# Expected: {"status": "ok", ...}

curl http://localhost:8001/api/health
# Expected: {"status": "healthy"}
```

> **Note on CORS:** The backend allows requests from `http://localhost:3000` and `http://localhost:3001` by default. If you serve the frontend from a different origin, update the `allow_origins` list in `backend/main.py`.

---

#### 3. Frontend (Annotation Web UI)

The frontend is a Next.js 14 application (React 18, TypeScript, Tailwind CSS) with standalone output mode.

**Port:** 3000

```bash
cd frontend

# Install Node.js dependencies
npm ci
```

**Set the API URL.** The frontend needs to know where the backend is. This is a build-time variable:

```bash
export NEXT_PUBLIC_API_URL=http://localhost:8001
```

Or create a `frontend/.env.local` file:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8001
```

##### Development mode

```bash
npm run dev
```

Opens at http://localhost:3000 with hot-reload.

##### Production build and run

```bash
# Build (generates .next/standalone)
npm run build

# Start the production server
cd .next/standalone
node server.js
```

The standalone build bundles everything into a single directory. If you need static assets (images, CSS), copy them:

```bash
cp -r .next/static .next/standalone/.next/static
cp -r public .next/standalone/public 2>/dev/null || true
```

Then run:

```bash
PORT=3000 HOSTNAME=0.0.0.0 node .next/standalone/server.js
```

**Verify:** Open http://localhost:3000 in your browser. The dashboard should load and show the navigation bar.

---

#### 4. Pipeline (NLP Processing) — Optional

The pipeline consists of two services: the **Pipeline API** (FastAPI) for NLP processing, entity linking, and quality checks, and the **Pipeline Dashboard** (Streamlit) for monitoring.

Skip this section if you only need the annotation workflow (upload CSV → LLM annotation → review).

##### 4a. Pipeline API

**Port:** 8000 (or 8010 if vLLM already uses 8000)

```bash
cd pipeline/api

# Create and activate a virtual environment (separate from backend)
python3.11 -m venv venv
source venv/bin/activate

# Install system dependencies needed for compilation
# (build-essential and cmake should already be installed from prerequisites)

# Install Python dependencies
pip install -r requirements.txt
```

**Create the results directory:**

```bash
mkdir -p /data/results/data
# Or use a local path and set APP_PATH accordingly:
mkdir -p ./results/data
export APP_PATH=$(pwd)/results/data
```

**Configure environment variables:**

```bash
export APP_PATH=/data/results/data          # Where pipeline outputs are stored
export NLP_BACKEND_URL=http://localhost:8001 # Annotation API URL
export NLP_FRONTEND_URL=http://localhost:3000 # Annotation Web UI URL
```

**Configure the vLLM connection.** The pipeline has its own config at `nlp/vllm_config.json`:

```json
{
  "use_vllm": true,
  "vllm_endpoint": "http://localhost:8000/v1",
  "model_name": "unsloth/Llama-3.2-3B-Instruct-unsloth-bnb-4bit",
  "batch_size": 8,
  "timeout": 30
}
```

> **Port conflict:** If vLLM is already running on port 8000, start the pipeline API on a different port (e.g., 8010) and update `PIPELINE_API_URL` accordingly in the dashboard environment.

**Start the Pipeline API:**

```bash
# Development
uvicorn app:app --host 0.0.0.0 --port 8010 --reload

# Production
uvicorn app:app --host 0.0.0.0 --port 8010 --workers 2
```

**Verify:**

```bash
curl http://localhost:8010/docs
# Should return the FastAPI Swagger UI
```

##### 4b. Pipeline Dashboard

**Port:** 8501

```bash
cd pipeline/status_web

# Create and activate a virtual environment
python3.9 -m venv venv   # Python 3.9+ is sufficient
source venv/bin/activate

pip install -r requirements.txt
```

**Configure environment variables:**

```bash
export PIPELINE_API_URL=http://localhost:8010  # Pipeline API URL (use 8010 if vLLM is on 8000)
export NLP_BACKEND_URL=http://localhost:8001   # Annotation API URL
export NLP_FRONTEND_URL=http://localhost:3000  # Annotation Web UI URL
```

**Start the dashboard:**

```bash
streamlit run app.py \
  --server.port 8501 \
  --server.address 0.0.0.0
```

**Verify:** Open http://localhost:8501 in your browser.

---

#### 5. vLLM Server (GPU Inference)

The platform requires a vLLM server for LLM inference. This can run on the same machine (if it has a GPU) or on a remote GPU server.

```bash
# Create a dedicated virtual environment
python3.11 -m venv vllm-env
source vllm-env/bin/activate

pip install vllm
```

**Start vLLM:**

```bash
vllm serve unsloth/medgemma-27b-text-it-unsloth-bnb-4bit \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 16384 \
  --max-num-seqs 32 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager
```

For gated models (Llama, Gemma), set your HuggingFace token:

```bash
export HF_TOKEN=hf_your_token_here
```

**Smaller model alternative** (requires less VRAM):

```bash
vllm serve unsloth/Llama-3.2-3B-Instruct-unsloth-bnb-4bit \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 8192 \
  --max-num-seqs 32 \
  --gpu-memory-utilization 0.85
```

**Verify:**

```bash
curl http://localhost:8000/v1/models
# Should list the loaded model
```

> **Remote vLLM:** If vLLM runs on a different machine, update `vllm_endpoint` in both `backend/config/vllm_config.json` and `pipeline/api/nlp/vllm_config.json` to point to `http://<gpu-host>:<port>/v1`.

---

#### 6. Bare-metal service summary

Once all components are running, you should have:

| Service | URL | Process |
|---------|-----|---------|
| Annotation Web UI | http://localhost:3000 | `node server.js` or `npm run dev` |
| Annotation API | http://localhost:8001 | `uvicorn main:app --port 8001` |
| Pipeline API | http://localhost:8010 | `uvicorn app:app --port 8010` |
| Pipeline Dashboard | http://localhost:8501 | `streamlit run app.py` |
| vLLM Server | http://localhost:8000 | `vllm serve ...` |

#### 7. Running as systemd services (production)

For a production bare-metal deployment, create systemd unit files so services start on boot and restart on failure. Here is an example for the annotation API:

```ini
# /etc/systemd/system/annotation-api.service
[Unit]
Description=Clinical Annotation API
After=network.target

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/clinical-annotation-platform/backend
Environment="VLLM_ENDPOINT=http://localhost:8000/v1"
ExecStart=/opt/clinical-annotation-platform/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/annotation-web.service
[Unit]
Description=Clinical Annotation Web UI
After=annotation-api.service

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/clinical-annotation-platform/frontend/.next/standalone
Environment="PORT=3000"
Environment="HOSTNAME=0.0.0.0"
ExecStart=/usr/bin/node server.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/pipeline-api.service
[Unit]
Description=Clinical Pipeline API
After=network.target

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/clinical-annotation-platform/pipeline/api
Environment="APP_PATH=/data/results/data"
Environment="NLP_BACKEND_URL=http://localhost:8001"
Environment="NLP_FRONTEND_URL=http://localhost:3000"
ExecStart=/opt/clinical-annotation-platform/pipeline/api/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8010 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/pipeline-dashboard.service
[Unit]
Description=Clinical Pipeline Dashboard
After=pipeline-api.service

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/clinical-annotation-platform/pipeline/status_web
Environment="PIPELINE_API_URL=http://localhost:8010"
Environment="NLP_BACKEND_URL=http://localhost:8001"
Environment="NLP_FRONTEND_URL=http://localhost:3000"
ExecStart=/opt/clinical-annotation-platform/pipeline/status_web/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start all services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now annotation-api annotation-web pipeline-api pipeline-dashboard
```

Check status:

```bash
sudo systemctl status annotation-api annotation-web pipeline-api pipeline-dashboard
```

#### 8. Verify the full stack

```bash
# Backend health
curl http://localhost:8001/api/server/status

# Frontend loads
curl -s http://localhost:3000 | head -5

# vLLM is reachable from the backend
curl http://localhost:8000/v1/models

# Pipeline API (if deployed)
curl http://localhost:8010/docs

# Pipeline Dashboard (if deployed)
curl -s http://localhost:8501 | head -5
```

## Project Structure

```
clinical-annotation-platform/
├── backend/                    # Annotation API (FastAPI)
│   ├── main.py                # Application entry point
│   ├── routes/                # API endpoints
│   │   ├── annotate.py       # Note processing & extraction
│   │   ├── sessions.py       # Session management
│   │   ├── prompts.py        # Prompt CRUD
│   │   ├── upload.py         # CSV upload
│   │   └── server.py         # Server status & metrics
│   ├── services/             # Business logic
│   ├── models/               # Pydantic schemas
│   ├── lib/                  # Shared utilities
│   │   ├── vllm_runner.py   # vLLM client
│   │   ├── fewshot_builder.py # FAISS-based retrieval
│   │   ├── icdo3_*.py       # ICD-O-3 extraction
│   │   └── evaluation_engine.py
│   └── data/                 # Prompts, few-shots, codes
│
├── frontend/                  # Annotation Web UI (Next.js)
│   ├── app/                  # Next.js app router pages
│   │   ├── page.tsx         # Dashboard
│   │   ├── upload/          # CSV upload
│   │   ├── prompts/         # Prompt editor
│   │   └── annotate/[id]/   # Annotation interface
│   ├── components/          # React components
│   └── lib/                 # API client & utilities
│
├── pipeline/                 # NLP Pipeline (from IDEA4RC)
│   ├── api/                 # Pipeline API
│   │   ├── app.py          # FastAPI application
│   │   └── nlp/            # NLP processing modules
│   ├── status_web/         # Streamlit dashboard
│   └── helm/               # Kubernetes charts
│
├── data/                    # Shared data files
│   ├── diagnosis_codes/    # ICD-O-3 CSV files
│   └── dictionaries/       # Sarcoma mappings, code lookups
│
├── docs/                    # Documentation
├── scripts/                 # Utility scripts
├── docker-compose.yml       # Production deployment
├── docker-compose.vllm.yml  # vLLM GPU inference server overlay
├── docker-compose.dev.yml   # Development overrides
└── .env.example            # Environment configuration template
```

## Features

### Annotation Interface
- Side-by-side view: clinical note with highlighted evidence spans
- Multi-value field support with add/remove functionality
- "Show reasoning" toggle for LLM explanations
- Session-based workflow with auto-save
- ICD-O-3 code lookup with morphology/topography search

### Prompt Management
- Monaco Editor-based prompt editing
- Multi-center support (INT, MSCI, VGR variants)
- Few-shot example retrieval using FAISS

### NLP Pipeline
- Batch processing of clinical notes
- Entity extraction and linking to IDEA4RC data model
- Quality validation with Great Expectations
- Progress monitoring via Streamlit dashboard

## API Endpoints

### Annotation API (port 8001)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/server/status` | GET | Server health check |
| `/api/server/metrics` | GET | GPU/memory metrics |
| `/api/prompts` | GET | List all prompts |
| `/api/prompts/{type}` | PUT | Update prompt |
| `/api/upload/csv` | POST | Upload clinical notes CSV |
| `/api/annotate/process` | POST | Process single note |
| `/api/sessions` | POST | Create annotation session |
| `/api/sessions/{id}` | GET/PUT | Get/update session |

### Pipeline API (port 8000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/nlp/process` | POST | Run NLP pipeline on CSV |
| `/link` | POST | Link extracted entities |
| `/quality-check` | POST | Validate output |
| `/sessions/{id}/export` | GET | Export results |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_API_URL` | `http://localhost:8000` | vLLM server URL |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8001` | Frontend API endpoint |
| `NLP_BACKEND_URL` | `http://localhost:8001` | Pipeline → Annotation API |
| `NLP_FRONTEND_URL` | `http://localhost:3000` | Pipeline → Annotation UI |

See [vLLM Configuration](#vllm-configuration) for the full list of vLLM-specific variables.

## Development

### Running Tests

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

### Docker Development Mode

```bash
# Run with hot-reload enabled
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## vLLM Configuration

The platform uses [vLLM](https://docs.vllm.ai/) to serve LLM inference via an OpenAI-compatible API. See [Quick Start](#quick-start) for deployment instructions and [Prerequisites](#gpu-requirements-for-llm-inference) for host setup.

All vLLM Docker parameters are configured via `.env`:

```bash
VLLM_IMAGE=vllm/vllm-openai:latest
VLLM_MODEL=unsloth/medgemma-27b-text-it-unsloth-bnb-4bit
VLLM_MAX_MODEL_LEN=16384
VLLM_MAX_NUM_SEQS=32
VLLM_GPU_MEM_UTIL=0.85
VLLM_HOST_PORT=8080
VLLM_EXTRA_ARGS=
# HF_TOKEN=
```

### vLLM Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_IMAGE` | `vllm/vllm-openai:latest` | Docker image for vLLM (change for CUDA compatibility) |
| `VLLM_MODEL` | `unsloth/medgemma-27b-text-it-unsloth-bnb-4bit` | HuggingFace model ID to serve |
| `VLLM_MAX_MODEL_LEN` | `16384` | Maximum sequence length (context window) |
| `VLLM_MAX_NUM_SEQS` | `32` | Maximum number of concurrent sequences |
| `VLLM_GPU_MEM_UTIL` | `0.85` | Fraction of GPU memory to use (0.0-1.0) |
| `VLLM_HOST_PORT` | `8080` | Host port to expose the vLLM API on |
| `VLLM_EXTRA_ARGS` | *(empty)* | Additional vLLM CLI arguments |
| `HF_TOKEN` | *(empty)* | HuggingFace token for gated models (Llama, Gemma, etc.) |

#### Switching Models

Edit `.env` and restart the vLLM container:

```bash
# Example: switch to a smaller model
VLLM_MODEL=unsloth/Llama-3.2-3B-Instruct-unsloth-bnb-4bit
VLLM_MAX_MODEL_LEN=8192
```

```bash
docker compose -f docker-compose.yml -f docker-compose.vllm.yml up -d vllm
```

#### Extra Arguments

Use `VLLM_EXTRA_ARGS` for any additional vLLM flags not covered by dedicated variables:

```bash
VLLM_EXTRA_ARGS=--dtype half --tensor-parallel-size 2
```

Common flags:

| Flag | Description |
|------|-------------|
| `--dtype half` | Force FP16 dtype |
| `--tensor-parallel-size N` | Split model across N GPUs |
| `--quantization bitsandbytes` | Explicit BNB quantization (auto-detected for most models) |
| `--max-num-batched-tokens N` | Max tokens per batch for throughput tuning |
| `--disable-log-requests` | Reduce logging verbosity |

#### Model Cache

Model weights are stored in the `vllm-cache` Docker volume and persist across restarts. To clear the cache and re-download:

```bash
docker volume rm clinicalannotationweb_vllm-cache
```

### Backend-Level vLLM Config

In addition to the Docker-level configuration, the backend application has its own config at `backend/config/vllm_config.json`:

```json
{
  "use_vllm": true,
  "vllm_endpoint": "http://localhost:8000/v1",
  "model_name": "unsloth/medgemma-27b-text-it-unsloth-bnb-4bit",
  "batch_size": 8,
  "timeout": 150
}
```

These can be overridden with environment variables: `USE_VLLM`, `VLLM_ENDPOINT`, `VLLM_MODEL_NAME`, `VLLM_BATCH_SIZE`, `VLLM_TIMEOUT`.

The pipeline has a separate config at `pipeline/api/nlp/vllm_config.json` with the same format.

### Verifying vLLM

```bash
# Check container status
docker ps --filter name=vllm

# Check loaded model
curl http://localhost:8080/v1/models

# Check health via the annotation API
curl http://localhost:8001/api/server/status
```

## Data Storage

The application stores runtime data in the following directories:

### Session Data (`backend/sessions/`)

The `backend/sessions/` directory stores annotation session data:
- **Session files**: Each annotation session is saved as a JSON file named with the session UUID (e.g., `{session-id}.json`). These files contain the session state, annotations, and metadata.
- **Report type mappings**: The `report_type_mappings.json` file stores mappings between report types and their corresponding annotation configurations.

Session files are automatically created when a new annotation session is started and updated as annotations are made.

### Prompt Data (`backend/data/prompts/`)

The `backend/data/prompts/` directory stores prompt templates and configurations:
- **Prompt templates**: JSON files containing prompt templates for different annotation tasks and centers (INT, MSCI, VGR variants).
- **Prompt generation scripts**: Python scripts for generating and managing prompt templates.

Prompts can be edited through the web interface's prompt editor, which updates the files in this directory.

## Data Requirements

### Input CSV Format

| Column | Required | Description |
|--------|----------|-------------|
| `text` | Yes | Clinical note text |
| `p_id` | Yes | Patient ID |
| `note_id` | Yes | Note identifier |
| `date` | No | Note date |
| `report_type` | No | Type of clinical report |
| `annotations` | No | Pre-existing annotations (JSON) |

