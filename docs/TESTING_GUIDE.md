# Testing Guide for ICD-O-3 LLM-Based Extraction System

This guide explains how to test the new ICD-O-3 extraction system and view feedback in the UI.

## Prerequisites

1. **Backend Server**: Ensure the FastAPI backend is running
   ```bash
   cd backend
   uvicorn main:app --reload --port 8001
   ```

2. **Frontend Server**: Ensure the Next.js frontend is running
   ```bash
   cd frontend
   npm run dev
   ```

3. **vLLM Server**: Ensure vLLM server is running (required for LLM extraction)
   - The system will fallback to other methods if vLLM is not available

4. **CSV File**: Ensure the diagnosis codes CSV is accessible
   - Default location: `backend/data/diagnosis_codes/diagnosis-codes-list.csv`
   - Or at project root: `IDEA4RC - Diagnosis codes - diagnosis-codes-list.csv`

## Testing Methods

### Method 1: Backend Unit Tests

Run the test script to verify the extraction system:

```bash
cd backend
python test_icdo3_llm_extraction.py
```

**What it tests:**
- CSV indexer loading and matching
- LLM extraction (if vLLM is available)
- Full integration with sample notes

**Expected Output:**
```
ICD-O-3 LLM-Based Extraction Test
============================================================
Testing CSV Indexer
✓ CSV indexer loaded successfully
  Query codes indexed: 377190
  Morphology codes indexed: ...
  Topography codes indexed: ...

Testing LLM-Based Extraction
✓ vLLM client available
✓ LLM extraction successful:
  Code: 8805/3-C71.7
  Query Code: 8805/3-C71.7
  Match Method: llm_csv_combined
  Match Score: 0.9
```

### Method 2: UI Testing (Recommended)

#### Step 1: Upload CSV with Clinical Notes

1. Navigate to `http://localhost:3000/upload`
2. Upload a CSV file with columns: `text`, `date`, `p_id`, `note_id`, `report_type`
3. Ensure at least one note contains histology or site information

**Example CSV row:**
```csv
text,date,p_id,note_id,report_type
"CCE|MODULO: AMB_TRD_Visita; TESTO: SARCOMA INDIFFERENZIATO A CELLULE FUSATE E PLEOMORFE CON STROMA MIXOIDE...",2024-01-01,001,001,Biopsy
```

#### Step 2: Create Session

1. Select prompt types that trigger ICD-O-3 extraction:
   - `histological-tipo-int` (for histology)
   - `tumorsite-int` (for tumor site)
2. Click "Create Session & Start Annotation"

#### Step 3: Process Notes

1. Navigate to the annotation page (`/annotate/[sessionId]`)
2. Click "Process Note" for a note with histology/site information
3. Wait for processing to complete

#### Step 4: View ICD-O-3 Codes

1. **In Annotation List**: Look for annotations with prompt types `histological-tipo-int` or `tumorsite-int`
2. **Click on Annotation**: Click on the annotation card to open the detail view
3. **View ICD-O-3 Section**: Scroll down to see the "ICD-O-3 Code" section

**What you'll see:**
- **Query Code (CSV)**: The matched code from CSV (e.g., "8940/0-C00.2") - highlighted in green
- **Code**: The primary ICD-O-3 code
- **Morphology**: Morphology code (e.g., "8940/0")
- **Topography**: Topography code (e.g., "C00.2")
- **Description**: Full description from CSV
- **Match Method**: How the code was matched:
  - `exact` - Code found directly in text
  - `llm_csv_exact` - LLM extracted exact code, matched in CSV
  - `llm_csv_combined` - LLM extracted codes, matched combined morphology+topography
  - `llm_csv_morphology_text` - LLM extracted morphology + text matching
  - `llm_csv_text` - Text-only matching
  - `jsl` - John Snow Labs extraction
  - `pattern` - Pattern matching fallback
- **Match Score**: Confidence score (0.0-1.0):
  - Green (≥80%): High confidence
  - Yellow (50-79%): Medium confidence
  - Red (<50%): Low confidence

### Method 3: Batch Processing

1. In the annotation page, click "Process All Notes"
2. Monitor the progress bar
3. After completion, check each note's annotations for ICD-O-3 codes

## Understanding the Feedback

### Match Method Colors

- **Green**: Best matches (exact, LLM+CSV combined)
- **Blue**: John Snow Labs matches
- **Yellow**: Text-based or pattern matches

### Match Score Interpretation

- **0.9-1.0**: Very high confidence (exact or combined code match)
- **0.7-0.9**: High confidence (morphology + text match)
- **0.5-0.7**: Medium confidence (text-only match)
- **0.3-0.5**: Low confidence (partial match)
- **<0.3**: Very low confidence

### What to Look For

1. **Query Code Present**: If you see a "Query Code (CSV)" field, the system successfully matched against the CSV
2. **Match Method**: Check which extraction method was used
3. **Match Score**: Higher scores indicate better matches
4. **Description**: Verify the description matches the clinical note

## Troubleshooting

### No ICD-O-3 Code Extracted

**Possible causes:**
1. vLLM server not running → System falls back to other methods
2. Note doesn't contain histology/site information
3. CSV file not found → Check `backend/config/icdo3_config.json`
4. Prompt type not recognized → Ensure prompt type contains "histolog" or "tumor" + "site"

**Check logs:**
- Backend console will show extraction attempts and failures
- Look for `[INFO]` or `[WARN]` messages about ICD-O-3 extraction

### Low Match Scores

**Possible causes:**
1. LLM extraction didn't find exact codes → Check raw_response in detail view
2. Text doesn't match CSV entries → Check description field
3. Note is ambiguous → System may return partial matches

**Solutions:**
- Check the "Why" toggle to see reasoning
- Review raw LLM response in detail view
- Verify note contains clear histology/site information

### CSV Not Loading

**Check:**
1. CSV file exists at configured path
2. File permissions are correct
3. Backend logs show CSV loading messages

**Fix:**
- Update `backend/config/icdo3_config.json` with correct path
- Ensure CSV file is readable

## Example Test Cases

### Test Case 1: Exact Code in Text
```
Note: "Histological type: Sarcoma (8805/3)"
Expected: Code extracted directly, match_method="exact", match_score=1.0
```

### Test Case 2: LLM Extraction + CSV Match
```
Note: "SARCOMA INDIFFERENZIATO A CELLULE FUSATE E PLEOMORFE CON STROMA MIXOIDE"
Expected: LLM extracts histology, matches against CSV, returns query_code
```

### Test Case 3: Site Extraction
```
Note: "Tumor site: Brain stem"
Expected: Topography code extracted (C71.7), matched in CSV
```

## Debugging Tips

1. **Check Backend Logs**: Look for `[INFO]` messages about extraction
2. **View Raw Response**: In annotation detail view, check "Raw Response" tab
3. **Check Match Method**: Different methods indicate different extraction paths
4. **Verify CSV Match**: Query code presence confirms CSV matching worked

## Performance Notes

- **First Load**: CSV indexing takes ~2-3 seconds (one-time cost)
- **LLM Extraction**: ~1-2 seconds per note (same as annotation processing)
- **CSV Matching**: <100ms (indexed lookup is fast)

## Next Steps

After testing:
1. Review match scores and methods
2. Verify extracted codes against known diagnoses
3. Check if descriptions match clinical notes
4. Report any issues or improvements needed
