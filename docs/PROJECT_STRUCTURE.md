# Project Structure

This project is **completely self-contained** within the `api/nlp/hitl_web/` directory. All dependencies have been copied and organized professionally.

## Directory Structure

```
hitl_web/
├── backend/                 # FastAPI backend
│   ├── lib/                 # Library modules (self-contained)
│   │   ├── __init__.py
│   │   ├── vllm_runner.py      # VLLM client integration
│   │   ├── prompt_adapter.py   # Prompt template adaptation
│   │   ├── fewshot_builder.py   # FAISS-based few-shot builder
│   │   └── evaluation_engine.py # Structured value extraction
│   ├── config/              # Configuration files
│   │   ├── __init__.py
│   │   └── vllm_config.json     # VLLM server configuration
│   ├── data/                 # Data files
│   │   ├── __init__.py
│   │   ├── prompts/            # Prompt templates
│   │   │   ├── __init__.py
│   │   │   └── prompts.json    # INT prompt templates
│   │   └── faiss_store/        # FAISS indexes (created at runtime)
│   ├── models/               # Pydantic models/schemas
│   │   └── schemas.py
│   ├── routes/               # API route handlers
│   │   ├── annotate.py
│   │   ├── prompts.py
│   │   ├── server.py
│   │   ├── sessions.py
│   │   └── upload.py
│   ├── services/             # Service layer
│   │   └── vllm_client.py
│   ├── sessions/             # Session storage (created at runtime)
│   ├── main.py               # FastAPI app entry point
│   └── README.md
├── frontend/                 # Next.js frontend
│   ├── app/                  # Next.js app directory
│   ├── components/           # React components
│   ├── lib/                  # Frontend utilities
│   └── package.json
├── fewshots_example.csv      # Example few-shot CSV
├── FEWSHOTS_FORMAT.md        # Few-shot format documentation
├── QUICKSTART.md             # Quick start guide
├── README.md                 # Main project README
└── PROJECT_STRUCTURE.md      # This file
```

## Self-Contained Design

### What Was Copied

All external dependencies from `api/nlp/` have been copied:

1. **Python Modules** → `backend/lib/`:
   - `vllm_runner.py` → `lib/vllm_runner.py`
   - `prompt_adapter.py` → `lib/prompt_adapter.py`
   - `fewshot_builder.py` → `lib/fewshot_builder.py`
   - `evaluation_engine.py` → `lib/evaluation_engine.py`

2. **Configuration Files** → `backend/config/`:
   - `vllm_config.json` → `config/vllm_config.json`

3. **Data Files** → `backend/data/`:
   - `FBK_scripts/prompts.json` → `data/prompts/prompts.json`

### Updated Imports

All imports have been updated to use local modules:

- `from vllm_runner import ...` → `from lib.vllm_runner import ...`
- `from prompt_adapter import ...` → `from lib.prompt_adapter import ...`
- `from fewshot_builder import ...` → `from lib.fewshot_builder import ...`
- `from evaluation_engine import ...` → `from lib.evaluation_engine import ...`

### Updated File Paths

All file paths have been updated to use local directories:

- `api/nlp/vllm_config.json` → `backend/config/vllm_config.json`
- `api/nlp/FBK_scripts/prompts.json` → `backend/data/prompts/prompts.json`
- `api/nlp/faiss_store/` → `backend/data/faiss_store/`
- `api/nlp/hitl_web/sessions/` → `backend/sessions/`

## No External Dependencies

The project now has **zero dependencies** on files outside `api/nlp/hitl_web/`. Everything needed to run the application is contained within this directory.

## Benefits

1. **Portability**: The entire project can be moved or copied independently
2. **Isolation**: Changes to parent directory won't affect this project
3. **Clarity**: All dependencies are visible and organized
4. **Professional Structure**: Clean separation of concerns (lib, config, data, routes, services)

