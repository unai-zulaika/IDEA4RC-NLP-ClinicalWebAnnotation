# ICD-O-3 Code Extraction

This document describes the ICD-O-3 code extraction feature for histology and site annotations.

## Overview

The system automatically extracts ICD-O-3 codes from histology and site annotations using multiple strategies:

1. **Pattern Extraction**: Extracts codes that are already present in the annotation text (e.g., "8805/3", "C71.7")
2. **John Snow Labs NLP Model**: Uses the `sbiobertresolve_icdo_base` model for advanced extraction (optional)
3. **Lookup Table**: Falls back to a simple lookup table for common terms (optional)

## Supported Prompts

The following prompt types automatically trigger ICD-O-3 code extraction:

- `histological-tipo-int` - Histological type annotations
- `tumorsite-int` - Tumor site annotations
- Any prompt containing "histolog" or "site" in the name

## Implementation Details

### Backend

The extraction is handled by `backend/lib/icdo3_extractor.py`:

- **`extract_icdo3_from_text(text, prompt_type)`**: Main extraction function
- **`is_histology_or_site_prompt(prompt_type)`**: Checks if a prompt needs ICD-O-3 extraction
- **`_extract_existing_code(text)`**: Extracts codes already present in text
- **`_extract_with_johnsnowlabs(text, prompt_type)`**: Uses John Snow Labs model (optional)
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

### Option 1: Pattern Extraction Only (Default)

No additional setup required. The system will extract codes that are already present in the annotation text using regex patterns.

**Pros:**
- No dependencies
- Fast and lightweight
- Works immediately

**Cons:**
- Only extracts codes already in text
- Cannot infer codes from descriptions

### Option 2: John Snow Labs NLP Model (Advanced)

For advanced extraction that can map histology descriptions to ICD-O-3 codes, Spark NLP is already included in `requirements.txt`. The models will be automatically downloaded on first use.

**Setup:**

1. Ensure Spark NLP is installed (already in requirements.txt):
```bash
pip install spark-nlp==4.4.0
```

2. The following models will be automatically downloaded on first use:
   - `sentence_detector_dl_healthcare` - Sentence detection
   - `embeddings_clinical` - Clinical word embeddings
   - `ner_jsl` - Medical NER model
   - `sbiobert_base_cased_mli` - BioBERT sentence embeddings
   - `sbiobertresolve_icdo_base` - ICD-O-3 resolver model

3. Test the extraction:
```bash
cd backend
python test_icdo3_extraction.py
```

**How it works:**

- **For histology prompts** (`histological-tipo-int`): Extracts morphology codes like `9050/3` (Mesothelioma, malignant)
- **For site prompts** (`tumorsite-int`): Extracts topography codes like `C71.7` (Brain stem)

The system uses a singleton pattern to reuse Spark session and pipeline for efficiency.

**Pros:**
- Can extract codes from natural language descriptions
- High accuracy
- Uses state-of-the-art NLP models
- Automatically prioritizes morphology codes for histology, topography codes for site

**Cons:**
- Requires Spark NLP installation (already in requirements)
- Slower first-time setup (model downloads)
- Requires more memory

**Note:** The system gracefully falls back to pattern extraction if Spark NLP is not available or if extraction fails.

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
2. If not found, try John Snow Labs model (if available)
3. If not available, try lookup table (if available)
4. Store the result in `annotation.icdo3_code`

### Frontend Display

ICD-O-3 codes are displayed in the annotation detail view with:
- Full code
- Morphology code breakdown
- Topography code (if available)
- Description (if available)
- Confidence score (if available)

## References

- [John Snow Labs ICD-O Resolver Model](https://nlp.johnsnowlabs.com/2021/07/02/sbiobertresolve_icdo_base_en.html)
- [ICD-O-3 Documentation](https://apps.who.int/iris/bitstream/handle/10665/96612/9789241548496_eng.pdf)

