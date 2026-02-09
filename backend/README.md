# Backend Structure

This directory contains the FastAPI backend for the Clinical Data Curation Platform.

## Directory Structure

```
backend/
├── lib/                    # Library modules (self-contained)
│   ├── __init__.py
│   ├── vllm_runner.py      # VLLM client integration
│   ├── prompt_adapter.py   # Prompt template adaptation
│   ├── fewshot_builder.py  # FAISS-based few-shot example builder
│   └── evaluation_engine.py # Structured value extraction
├── config/                 # Configuration files
│   ├── __init__.py
│   └── vllm_config.json    # VLLM server configuration
├── data/                   # Data files
│   ├── __init__.py
│   ├── prompts/            # Prompt templates
│   │   ├── __init__.py
│   │   └── prompts.json    # INT prompt templates
│   └── faiss_store/        # FAISS indexes for few-shot examples
├── models/                 # Pydantic models/schemas
│   └── schemas.py
├── routes/                 # API route handlers
│   ├── annotate.py         # Annotation processing
│   ├── prompts.py          # Prompt management
│   ├── server.py           # Server status/metrics
│   ├── sessions.py         # Session management
│   └── upload.py           # File uploads
├── services/               # Service layer
│   └── vllm_client.py      # Enhanced VLLM client
├── sessions/               # Session storage (created at runtime)
├── main.py                 # FastAPI application entry point
└── README.md               # This file
```

## Self-Contained Design

This backend is **completely self-contained** within the `hitl_web` directory. All dependencies have been copied from the parent `api/nlp/` directory:

- **Library modules** (`lib/`): All utility modules are local
- **Configuration** (`config/`): All config files are local
- **Data files** (`data/`): All data files are local

No external dependencies on files outside `api/nlp/hitl_web/` are required.

## Running the Backend

```bash
cd backend
uvicorn main:app --reload --port 8001
```

## Configuration

Edit `config/vllm_config.json` to configure the VLLM server connection:

```json
{
  "use_vllm": true,
  "vllm_endpoint": "http://localhost:8000/v1",
  "model_name": "meta-llama/Llama-3.1-8B-Instruct",
  "batch_size": 8,
  "timeout": 30
}
```

## Data Files

- **Prompts**: Edit `data/prompts/prompts.json` to modify prompt templates
- **FAISS Indexes**: Built automatically in `data/faiss_store/` when few-shot examples are available
- **Sessions**: Stored in `sessions/` directory (created at runtime)

