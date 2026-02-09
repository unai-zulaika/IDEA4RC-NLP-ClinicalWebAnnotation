# Hospital Testing Guide

This guide explains how to use the testing tools with your actual data formats.

## Data Formats

### 1. Unstructured Input (`first_patient_notes.csv`)
**Format**: Semicolon-delimited CSV
**Columns**: `text`, `date`, `p_id`, `note_id`, `report_type`

**Example**:
```csv
text;date;p_id;note_id;report_type
"15 marzo 2018...";2018-03-15;P001;P001_2018-03-15_consultation_1;consultation
```

### 2. Structured Output (from pipeline)
**Format**: Comma or semicolon-delimited CSV
**Columns**: `patient_id`, `original_source`, `core_variable`, `date_ref`, `value`, `record_id`, `note_id`, `types`, etc.

**Example**:
```csv
patient_id,original_source,core_variable,date_ref,value,record_id,note_id,types
3,NLP_LLM,Patient.sex,2024-03-14,8532,1,P001_2018-03-15_consultation_1,CodeableConcept
```

**Note**: The pipeline converts `p_id` → `patient_id` in structured output. The analysis tools handle both.

### 3. Gold Standard Annotations (`annotated_patient_notes_with_spans_full_verified.json`)
**Format**: JSON with nested structure
**Structure**:
```json
[
  {
    "patient_id": "P001",
    "notes": [
      {
        "text": "...",
        "date": "2018-03-15",
        "p_id": "P001",
        "note_id": "P001_2018-03-15_consultation_1",
        "report_type": "consultation",
        "annotations": [
          "Patient's gender Female",
          "Age at diagnosis 34 years",
          ...
        ]
      }
    ]
  }
]
```

## Testing Workflows

### A. LLM Evaluation Standalone

**Purpose**: Test LLM performance on entity identification and date extraction.

**Command**:
```bash
cd api/nlp
python evaluate_llm_int_prompts.py \
  --notes-csv first_patient_notes.csv \
  --json-file annotated_patient_notes_with_spans_full_verified.json \
  --prompts-json FBK_scripts/prompts.json \
  --model-path meta-llama-3.1-8b-instruct-q4_k_m.gguf
```

**Outputs**:
- `llm_evaluation_detailed.csv` - Detailed comparison (gold vs predicted vs original text)
- `llm_evaluation_summary.csv` - Summary per prompt type
- `llm_evaluation_report.json` - Complete statistics
- `llm_evaluation_dates.csv` - **NEW**: Date-specific evaluation
- `llm_evaluation_comparison.html` - **NEW**: Interactive HTML report

**Key Features**:
- ✓/✗ visual indicators for matches
- Side-by-side comparison in HTML
- Separate date accuracy metrics
- Filterable/searchable reports

### B. Full Ingestion Pipeline Analysis

**Purpose**: Analyze the complete pipeline from unstructured text → LLM annotations → structured CSV.

**Step 1**: Run the pipeline (via API or `process_texts.py`)
**Step 2**: Analyze results

**Command**:
```bash
cd api/nlp
python analyze_pipeline_results.py \
  --input-texts first_patient_notes.csv \
  --output-structured structured_output.csv \
  --llm-annotations llm_annotations.csv  # Optional
```

**Outputs**:
- `pipeline_summary_statistics.json` - Complete statistics
- `pipeline_summary_statistics.csv` - Summary in CSV format
- `pipeline_comparison_report.csv` - Input vs output comparison
- `pipeline_comparison_report.html` - **NEW**: Interactive HTML report

**Key Metrics**:
- Total notes processed
- Entities extracted per note
- Core variables coverage
- Date extraction rate
- Error rate (if LLM annotations provided)

### C. Optional: VLLM Backend

**Purpose**: Use local VLLM server for faster batch inference.

**Setup**:
1. Start VLLM server:
```bash
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --port 8000
```

2. Configure (choose one):
   - Edit `vllm_config.json`: Set `"use_vllm": true`
   - Or set environment: `export USE_VLLM=true`

**Usage**: Same commands as above - VLLM will be used automatically if available.

## Column Name Compatibility

The tools handle column name variations:
- **Input texts**: `p_id` (from `first_patient_notes.csv`)
- **Structured output**: `patient_id` (from pipeline)
- **Analysis tools**: Automatically normalize both to work together

## Date Evaluation

The date evaluation module (`date_evaluation.py`) provides:
- **Exact date matching**: Full date match (DD/MM/YYYY or YYYY-MM-DD)
- **Partial matching**: Year-month match, year-only match
- **Metrics**: Precision, recall, F1-score per prompt type
- **Separate report**: `llm_evaluation_dates.csv` with date-specific metrics

## Tips for Hospital Testing

1. **Start with small subset**: Test with a few notes first to verify setup
2. **Check HTML reports**: They provide the best visual comparison
3. **Monitor date accuracy**: Use `llm_evaluation_dates.csv` to identify date extraction issues
4. **Compare both pipelines**: Run both LLM evaluation and full pipeline analysis
5. **Use VLLM if available**: Significantly faster for batch processing

## Troubleshooting

**Issue**: Column not found errors
- **Solution**: Check that CSV files have expected columns (`note_id`, `p_id`, `text`, etc.)

**Issue**: JSON loading fails
- **Solution**: Verify JSON structure matches expected format (patient → notes → annotations)

**Issue**: VLLM not connecting
- **Solution**: Check server is running, verify endpoint in `vllm_config.json`

**Issue**: Date evaluation shows low accuracy
- **Solution**: Check date formats in annotations - may need to normalize formats
