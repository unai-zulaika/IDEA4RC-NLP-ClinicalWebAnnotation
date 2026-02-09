# ICD-O-3 Code Extraction

This document describes the ICD-O-3 code extraction feature for histology and site annotations.

## Overview

The system automatically extracts ICD-O-3 codes from histology and site annotations using multiple strategies:

1. **Exact Code Extraction**: Extracts codes that are already present in the annotation text (e.g., "8805/3", "C71.7")
2. **LLM + CSV Matching**: Uses LLM to extract histology/topography information and matches against diagnosis codes CSV
3. **Pattern Matching**: Falls back to a simple lookup table for common terms (optional)

## Supported Prompts

The following prompt types automatically trigger ICD-O-3 code extraction:

- `histological-tipo-int` - Histological type annotations
- `tumorsite-int` - Tumor site annotations
- Any prompt containing "histolog" or "site" in the name

## Implementation Details

### Backend

The extraction is handled by `backend/lib/icdo3_extractor.py`:

- **`extract_icdo3_from_text(text, prompt_type, note_text, vllm_client)`**: Main extraction function
- **`is_histology_or_site_prompt(prompt_type)`**: Checks if a prompt needs ICD-O-3 extraction
- **`_extract_existing_code(text)`**: Extracts codes already present in text
- **`_extract_with_llm_and_csv_match(text, prompt_type, note_text, vllm_client)`**: Uses LLM to extract and match against CSV
- **`_extract_with_patterns(text, prompt_type)`**: Uses lookup table (optional)

### Schema

ICD-O-3 codes are stored in the `AnnotationResult` model:

```python
class ICDO3CodeInfo(BaseModel):
    code: str  # Full ICD-O-3 code (e.g., "8805/3")
    topography_code: Optional[str] = None  # Topography code (e.g., "C71.7")
    morphology_code: Optional[str] = None  # Morphology code (e.g., "8805/3")
    histology_code: Optional[str] = None  # Histology code (e.g., "8805")
    behavior_code: Optional[str] = None  # Behavior code (e.g., "3")
    description: Optional[str] = None  # Description of the code
    confidence: Optional[float] = None  # Confidence score if available
```

### Integration

The extraction is automatically performed:

1. After the LLM generates an annotation
2. Only for histology/site prompts
3. As a post-processing step before storing the annotation

## Setup Options

### Option 1: LLM + CSV Matching (Default)

The system uses LLM to extract histology/topography information from clinical notes and matches against the diagnosis codes CSV file (377K rows).

**Setup:**

1. Ensure vLLM server is running (required for LLM extraction)
2. Ensure CSV file is available at `backend/data/diagnosis_codes/diagnosis-codes-list.csv`
3. The CSV will be automatically indexed on first use

**How it works:**

- **For histology prompts** (`histological-tipo-int`): LLM extracts histology description, matches against CSV to find morphology codes
- **For site prompts** (`tumorsite-int`): LLM extracts tumor site, matches against CSV to find topography codes
- **Combined**: Can extract both histology and topography codes and match combined codes

**Pros:**
- Can extract codes from natural language descriptions
- High accuracy with CSV matching
- Uses existing vLLM infrastructure
- No Java dependencies

**Cons:**
- Requires vLLM server to be running
- CSV indexing takes ~2-3 seconds on startup

**Note:** The system gracefully falls back to pattern extraction if LLM extraction fails or CSV is not available.

### Option 2: Pattern Extraction (Fallback)

Extracts codes that are already present in the annotation text using regex patterns.

**Pros:**
- No dependencies
- Fast and lightweight
- Works immediately

**Cons:**
- Only extracts codes already in text
- Cannot infer codes from descriptions

### Option 3: Lookup Table (Custom)

Create a JSON lookup table at `backend/data/icdo3_lookup.json`:

```json
{
  "leiomyosarcoma": {
    "code": "8890/3",
    "morphology_code": "8890/3",
    "histology_code": "8890",
    "behavior_code": "3",
    "description": "Leiomyosarcoma, NOS"
  },
  "undifferentiated sarcoma": {
    "code": "8805/3",
    "morphology_code": "8805/3",
    "histology_code": "8805",
    "behavior_code": "3",
    "description": "Sarcoma, undifferentiated, NOS"
  }
}
```

**Pros:**
- Fast lookup
- Customizable
- No external dependencies

**Cons:**
- Requires manual maintenance
- Limited to predefined terms

## Usage

The extraction happens automatically. No manual intervention is required.

### Example

For an annotation like:
```
Histological type: Sarcoma, undifferentiated, pleomorphic, NOS ([select ICD-O-3 code]).
```

The system will:
1. Try to extract an existing code from the text
2. If not found, use LLM to extract histology/topography and match against CSV
3. If CSV matching fails, try lookup table (if available)
4. Store the result in `annotation.icdo3_code`

### Frontend Display

ICD-O-3 codes are displayed in the annotation detail view with:
- Full code
- Morphology code breakdown
- Topography code (if available)
- Description (if available)
- Confidence score (if available)

## References

- [ICD-O-3 Documentation](https://apps.who.int/iris/bitstream/handle/10665/96612/9789241548496_eng.pdf)

