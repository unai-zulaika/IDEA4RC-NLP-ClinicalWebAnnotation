# Testing the NLP Validation UI Integration

This guide explains how to test the integration between the NLP Validation UI and the IDEA4RC Data Ingestion Pipeline.

## Prerequisites

Ensure you have the following installed:
- Python 3.9+
- Node.js 18+
- Required Python packages for each service

## 1. Start All Services

Open 4 terminal windows and start each service:

### Terminal 1: NLP Backend (Port 8001)
```bash
cd /home/zulaika/ClinicalAnnotationWeb/backend
uvicorn main:app --port 8001 --reload
```

### Terminal 2: NLP Frontend (Port 3000)
```bash
cd /home/zulaika/ClinicalAnnotationWeb/frontend
npm run dev
```

### Terminal 3: IDEA4RC API (Port 8010)
```bash
cd /home/zulaika/ClinicalAnnotationWeb/IDEA4RC-NLP-Ingestion/api
uvicorn app:app --port 8010 --reload
```

### Terminal 4: IDEA4RC Status Web / Streamlit (Port 8501)
```bash
cd /home/zulaika/ClinicalAnnotationWeb/IDEA4RC-NLP-Ingestion/status_web
streamlit run app.py --server.port 8501
```

## 2. Verify Services Are Running

Check each service is accessible:
- **NLP Backend**: http://localhost:8001/docs (FastAPI Swagger UI)
- **NLP Frontend**: http://localhost:3000
- **IDEA4RC API**: http://localhost:8010/docs (FastAPI Swagger UI)
- **Streamlit UI**: http://localhost:8501

## 3. Test the OPTION 1A Workflow

### Step 1: Open Streamlit UI
1. Open http://localhost:8501 in your browser
2. Scroll down to **"OPTION 1A: Full process with NLP Validation"**

### Step 2: Upload Test Files
1. **Select disease type**: Choose "sarcoma" or "head_and_neck"
2. **Upload structured data**: Use `MSCI_DEMO_NT_V3.xlsx` or similar structured data file
3. **Upload unstructured text**: Use `patients_notes_with_annotations_short.csv` or similar file with free text

The unstructured text file should have these columns:
- `text` - The clinical note text
- `date` - Date of the note
- `p_id` - Patient ID
- `note_id` - Unique note identifier
- `report_type` - Type of report (e.g., "pathology", "radiology")

### Step 3: Create NLP Session
1. Click **"1. Create NLP Session"** button
2. Wait for success message: "NLP Session created: {session_id}"
3. A link will appear: **"Open NLP Validation UI"**

### Step 4: Validate Annotations in NLP UI
1. Click the **"Open NLP Validation UI"** link (opens in new tab)
2. In the NLP UI:
   - Process notes using the available prompt types
   - Review and validate histology-topography annotations
   - Edit any incorrect annotations
   - The annotations are auto-saved
3. Return to the Streamlit tab when done

### Step 5: Continue Pipeline
1. Back in Streamlit, click **"3. Continue Pipeline"**
2. Watch the progress bar as it:
   - Fetches validated NLP data (10%)
   - Loads structured data (20%)
   - Merges data (30%)
   - Links rows (50%)
   - Runs quality checks (80%)
   - Completes (100%)

### Step 6: Download Results
1. Scroll down to **"Check Pipeline Status"**
2. Enter the Task ID shown after pipeline completion
3. Click **"Check Status"**
4. Download the result files:
   - **Processed Texts** (merged structured + NLP data)
   - **Linked Data** (after linking service)
   - **Quality Check** (final output)

## 4. Test Individual Endpoints

### Test Export Endpoint (NLP Backend)
```bash
# Replace {session_id} with an actual session ID
curl http://localhost:8001/api/sessions/{session_id}/export
```

Expected output: CSV with columns `patient_id`, `record_id`, `core_variable`, `date_ref`, `value`, `types`, `icdo3_code`

### Test Create Session Endpoint (IDEA4RC API)
```bash
curl -X POST "http://localhost:8010/nlp/create_session" \
  -F "text_file=@patients_notes.csv" \
  -F "session_name=Test Session" \
  -F "prompt_types=histological-tipo-int,tumorsite-int"
```

Expected output: `{"session_id": "...", "name": "Test Session", ...}`

### Test Continue Pipeline Endpoint (IDEA4RC API)
```bash
curl -X POST "http://localhost:8010/pipeline/continue" \
  -F "structured_file=@structured_data.csv" \
  -F "session_id={session_id}" \
  -F "disease_type=sarcoma"
```

Expected output: `{"task_id": "...", "message": "Pipeline continuation started"}`

## 5. Verify Data Flow

### Check NLP Session Was Created
```bash
curl http://localhost:8001/api/sessions
```
Look for your session in the list.

### Check Session Content
```bash
curl http://localhost:8001/api/sessions/{session_id}
```
Verify notes and annotations are present.

### Check Pipeline Status
```bash
curl http://localhost:8010/status/{task_id}
```
Should show `step`, `progress`, and `result` fields.

### Check Pipeline Logs
```bash
curl http://localhost:8010/logs/{task_id}
```
Review detailed logs for troubleshooting.

## 6. Common Issues and Solutions

### Issue: "Failed to create session: NLP backend unavailable"
- **Cause**: NLP Backend (port 8001) is not running
- **Solution**: Start the NLP backend service

### Issue: "Failed to fetch validated NLP data"
- **Cause**: Session ID is invalid or session has no annotations
- **Solution**: Verify session exists and has validated annotations

### Issue: "Continue Pipeline" button is disabled
- **Cause**: Either NLP session wasn't created or structured data wasn't uploaded
- **Solution**:
  1. Upload structured data file first
  2. Click "Create NLP Session" to create session
  3. Both must be done before continuing

### Issue: Pipeline fails at "Linking rows"
- **Cause**: Data format mismatch between NLP output and linking service expectations
- **Solution**: Check the merged data format matches what the linking service expects

### Issue: Validation link doesn't work
- **Cause**: NLP Frontend (port 3000) is not running
- **Solution**: Start the frontend service with `npm run dev`

## 7. Environment Variables

You can customize service URLs with these environment variables:

```bash
# For IDEA4RC API (app.py)
export NLP_BACKEND_URL="http://localhost:8001"

# For Streamlit UI (status_web/app.py)
export NLP_BACKEND_URL="http://localhost:8001"
export NLP_FRONTEND_URL="http://localhost:3000"
export API_HOST="localhost:8010"
```

## 8. Sample Test Data

### Minimal Unstructured Text CSV
```csv
text,date,p_id,note_id,report_type
"Adenocarcinoma of the lung, grade 2",2024-01-15,P001,N001,pathology
"Squamous cell carcinoma of the skin",2024-01-16,P002,N002,pathology
```

### Minimal Structured Data CSV
```csv
patient_id,variable,value,date
P001,age,65,2024-01-15
P001,gender,M,2024-01-15
P002,age,72,2024-01-16
P002,gender,F,2024-01-16
```

## 9. Reset Workflow

If you need to start over:
1. Click **"Reset Option 1A Workflow"** button in Streamlit
2. This clears the session ID and stored structured data
3. You can then upload new files and create a new session
