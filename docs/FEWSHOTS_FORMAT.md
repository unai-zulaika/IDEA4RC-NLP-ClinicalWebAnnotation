# Few-Shot Examples CSV Format

## Overview
Few-shot examples help improve the quality of LLM annotations by providing similar examples. You can upload a CSV file with few-shot examples that will be used during annotation processing.

## CSV Format

### Required Columns
The CSV file must contain exactly three columns:

1. **`prompt_type`** (string): The prompt type identifier (e.g., `gender-int`, `biopsygrading-int`, `surgerymargins-int`)
2. **`note_text`** (string): The full medical note text
3. **`annotation`** (string): The expected annotation for that note and prompt type

### Delimiter
- Supports both semicolon (`;`) and comma (`,`) delimiters
- The system will try semicolon first, then fall back to comma

### Example CSV

```csv
prompt_type,note_text,annotation
gender-int,"Patient is a 65-year-old male presenting with chest pain.","Patient's gender male."
biopsygrading-int,"The biopsy shows a high-grade sarcoma with FNCLCC grade 3.","Biopsy grading (FNCLCC): 3."
surgerymargins-int,"Surgical resection was performed with clear margins (R0).","Margins after surgery: R0."
tumordepth-int,"The tumor extends deep into the muscle tissue.","Tumor depth: deep."
ageatdiagnosis-int,"Patient is a 45-year-old female diagnosed in 2020.","Age at diagnosis: 45 years."
```

### With Semicolon Delimiter

```csv
prompt_type;note_text;annotation
gender-int;"Patient is a 65-year-old male presenting with chest pain.";"Patient's gender male."
biopsygrading-int;"The biopsy shows a high-grade sarcoma with FNCLCC grade 3.";"Biopsy grading (FNCLCC): 3."
```

## How It Works

1. **Upload**: Upload the CSV file via the "Upload Few-Shots" section on the Upload page
2. **Storage**: Examples are stored in memory, grouped by `prompt_type`
3. **Retrieval**: During annotation:
   - If FAISS is available: Uses semantic similarity search (like `evaluate_llm_int_prompts.py`)
   - If CSV few-shots are uploaded: Uses the uploaded examples (first k examples for each prompt type)
   - If neither: Runs in zero-shot mode (no few-shots)

## Tips

- **Multiple examples per prompt type**: You can include multiple rows with the same `prompt_type` - all will be stored
- **Quality matters**: Use high-quality, verified annotations as examples
- **Relevance**: Examples should be representative of the types of notes you'll be processing
- **Format consistency**: Ensure annotation format matches what the prompt expects (see `prompts.json`)

## Getting Examples from Your Data

If you have the `annotated_patient_notes_with_spans_full_verified.json` file, you can extract few-shot examples:

1. Each patient has notes with annotations
2. Each annotation should be matched to a prompt type (see `map_annotation_to_prompt` in `fewshot_builder.py`)
3. Extract note text and corresponding annotation for each prompt type
4. Format as CSV with the three required columns

## Example Python Script to Generate CSV

```python
import json
import pandas as pd
from fewshot_builder import map_annotation_to_prompt

# Load your annotated JSON
with open('annotated_patient_notes_with_spans_full_verified.json', 'r') as f:
    data = json.load(f)

fewshot_rows = []

for patient in data:
    for note in patient.get('notes', []):
        note_text = note.get('note_original_text', '')
        for annotation in note.get('annotations', []):
            # Try to match annotation to prompt type
            for prompt_type in ['gender-int', 'biopsygrading-int', ...]:  # Add all prompt types
                if map_annotation_to_prompt(annotation, prompt_type):
                    fewshot_rows.append({
                        'prompt_type': prompt_type,
                        'note_text': note_text,
                        'annotation': annotation
                    })

df = pd.DataFrame(fewshot_rows)
df.to_csv('fewshots.csv', index=False, sep=',')
```

