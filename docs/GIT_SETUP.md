# Git Repository Setup

This project is ready to be initialized as a git repository. All dependencies are self-contained and all external file references have been removed.

## Quick Start

1. **Initialize git repository:**
```bash
cd api/nlp/hitl_web
git init
```

2. **Add all files:**
```bash
git add .
```

3. **Create initial commit:**
```bash
git commit -m "Initial commit: Self-contained Clinical Data Curation Platform"
```

## What's Included

✅ All Python modules copied to `backend/lib/`  
✅ All configuration files in `backend/config/`  
✅ All data files in `backend/data/`  
✅ No external file dependencies  
✅ All imports use local modules  
✅ `.gitignore` configured  
✅ `requirements.txt` with all dependencies  

## What's Excluded (via .gitignore)

- Python cache files (`__pycache__/`, `*.pyc`)
- Node modules (`node_modules/`)
- Virtual environments (`venv/`, `env/`)
- Session data (`backend/sessions/`)
- FAISS index files (but directory structure preserved)
- Environment files (`.env`)
- IDE files (`.vscode/`, `.idea/`)

## Verification

To verify everything works:

```bash
# Test backend imports
cd backend
python3 -c "from lib.prompt_adapter import adapt_int_prompts; print('OK')"
python3 -c "from lib.vllm_runner import VLLMClient; print('OK')"
python3 -c "from lib.evaluation_engine import extract_structured_values; print('OK')"

# Test FastAPI app
python3 -c "from main import app; print('FastAPI app loaded successfully')"
```

## Remote Repository

To push to a remote repository:

```bash
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

## Notes

- The project is completely self-contained
- No need to reference parent directories
- All paths are relative to the project root
- Can be cloned and run independently

