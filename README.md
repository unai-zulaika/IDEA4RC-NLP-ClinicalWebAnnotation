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

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd clinical-annotation-platform

# Copy environment file and configure
cp .env.example .env
# Edit .env to set your vLLM model and parameters (see vLLM section below)

# Full stack with vLLM (GPU required)
docker compose -f docker-compose.yml -f docker-compose.vllm.yml up -d

# Or app only (vLLM running externally)
docker compose up -d

# Access the applications:
# - Annotation UI: http://localhost:3000
# - Annotation API: http://localhost:8001
# - Pipeline API: http://localhost:8000
# - Pipeline Dashboard: http://localhost:8501
# - vLLM API (when enabled): http://localhost:8080
```

### Local Development

#### Prerequisites
- Python 3.11+
- Node.js 20+
- vLLM server running (or compatible OpenAI API endpoint)

#### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt

# Start the API server
uvicorn main:app --reload --port 8001
```

#### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 in your browser.

#### Pipeline Setup (Optional)

```bash
cd pipeline/api
pip install -r requirements.txt
uvicorn app:app --port 8000

# In another terminal, for the dashboard:
cd pipeline/status_web
pip install -r requirements.txt
streamlit run app.py --server.port 8501
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

The platform uses [vLLM](https://docs.vllm.ai/) to serve LLM inference via an OpenAI-compatible API. There are two ways to run it: as a Docker container alongside the app, or externally.

### Prerequisites

- NVIDIA GPU with sufficient VRAM for your chosen model
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed

### Running vLLM with Docker Compose

The `docker-compose.vllm.yml` overlay adds a vLLM container to the stack. All parameters are configured via `.env`:

```bash
# .env
VLLM_MODEL=unsloth/medgemma-27b-text-it-unsloth-bnb-4bit
VLLM_MAX_MODEL_LEN=16384
VLLM_MAX_NUM_SEQS=32
VLLM_GPU_MEM_UTIL=0.85
VLLM_HOST_PORT=8080
VLLM_EXTRA_ARGS=
# HF_TOKEN=
```

```bash
docker compose -f docker-compose.yml -f docker-compose.vllm.yml up -d
```

When using this overlay, the annotation API automatically connects to vLLM via the Docker network (`http://vllm:8000`), and vLLM is exposed on the host at port 8080.

#### vLLM Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
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

### Running vLLM Externally

If you prefer to run vLLM outside Docker (e.g., in a virtual environment):

```bash
pip install vllm

vllm serve unsloth/medgemma-27b-text-it-unsloth-bnb-4bit \
  --max-model-len 16384 \
  --max-num-seqs 32 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager
```

Then start the app without the vLLM overlay:

```bash
docker compose up -d
```

The annotation API defaults to connecting to `http://host.docker.internal:8000` (your host machine's port 8000). Override this with `VLLM_API_URL` in `.env` if needed.

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

## Deployment

### Docker Compose (Single Server)

```bash
# Without vLLM
docker compose up -d

# With vLLM (GPU required)
docker compose -f docker-compose.yml -f docker-compose.vllm.yml up -d
```

### Kubernetes (Helm)

```bash
cd pipeline/helm
helm install clinical-platform ./charts
```

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

## License

[Specify license]

## Contributing

[Contribution guidelines]
