# Quick Start Guide

## Prerequisites

1. Python 3.8+ with pip
2. Node.js 18+ with npm
3. vLLM server running (or configure to use llama.cpp fallback)

## Backend Setup

```bash
cd api/nlp/hitl_web/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The backend will be available at http://localhost:8001

Note: Port 8001 is used because vLLM runs on port 8000.

## Frontend Setup

```bash
cd api/nlp/hitl_web/frontend
npm install
npm run dev
```

The frontend will be available at http://localhost:3000

## Usage Flow

1. **Start Backend**: Run `uvicorn main:app --reload` in `backend/` directory
2. **Start Frontend**: Run `npm run dev` in `frontend/` directory
3. **Upload CSV**: Navigate to http://localhost:3000/upload
   - Upload a CSV file with columns: `text`, `date`, `p_id`, `note_id`, `report_type`
   - Select prompt types to run
   - Click "Create Session & Start Annotation"
4. **Annotate**: You'll be redirected to the annotation interface
   - Click "Process Note" to run LLM extraction
   - Review highlighted evidence spans
   - Edit annotations in the right panel
   - Navigate between notes

## Configuration

### Backend

- vLLM endpoint: Configured in `vllm_config.json` (parent directory)
- Session storage: JSON files in `hitl_web/sessions/` directory

### Frontend

- API URL: Set `NEXT_PUBLIC_API_URL` environment variable (defaults to http://localhost:8001)

## Troubleshooting

1. **Backend won't start**: Check that all dependencies are installed and vLLM server is running
2. **Frontend can't connect**: Verify `NEXT_PUBLIC_API_URL` matches backend URL
3. **No prompts available**: Ensure `FBK_scripts/prompts.json` exists in parent directory
4. **Processing fails**: Check vLLM server logs and ensure model is loaded

