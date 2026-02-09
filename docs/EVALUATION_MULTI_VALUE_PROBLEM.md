# Evaluation Problem: Multi-Value Template Evaluation

## Problem Overview

The current evaluation system evaluates annotations at the **prompt level** rather than at the **field/value level**. This means that prompts with templates containing multiple distinct values (e.g., dates, categorical choices, text fields) are evaluated as a single unit, even though different values may require different evaluation metrics.

## Current Evaluation Process

### 1. Evaluation Flow

The evaluation process follows this flow:

1. **Entry Point**: `routes/annotate.py` calls `evaluate_annotation_with_special_cases()`
   - Location: `backend/routes/annotate.py` (lines 760-765, 1225-1230)
   - Passes entire `expected_annotation` and `predicted_annotation` strings

2. **Evaluation Engine**: `lib/evaluation_engine.py` → `evaluate_annotation()`
   - Location: `backend/lib/evaluation_engine.py` (lines 310-369)
   - Performs three types of comparison:
     - **Exact match**: Case-insensitive, Unicode-normalized string comparison
     - **Cosine similarity**: TF-IDF-based similarity score (threshold: ≥0.8)
     - **Per-value extraction**: Generic extraction of dates, numbers, key-value pairs, enumerations

3. **Overall Match Determination**:
   ```python
   overall_match = is_exact_match or is_high_similarity
   ```

### 2. Per-Value Extraction (Limited)

The system does attempt some per-value extraction via `extract_structured_values()`:

**Extracted Value Types**:
- **Dates**: Regex patterns for `DD/MM/YYYY`, `YYYY-MM-DD`, `D/M/YYYY`
- **Numbers with units**: Pattern matching for values like "110 mm", "50 Gy", "34 years"
- **Key-value pairs**: Extracts patterns like "key: value" or "key [value]"
- **Enumerations**: Comma or semicolon-separated lists

**Limitations**:
- Extraction is **generic** and not template-aware
- Does not use `entity_mapping` configurations from prompts
- Cannot distinguish between different template placeholders
- Cannot apply different evaluation metrics per field

### 3. Entity Mappings (Not Used in Evaluation)

Prompts can define `entity_mapping` configurations:

```json
{
  "entity_mapping": {
    "entity_type": "Diagnosis",
    "field_mappings": [
      {
        "template_placeholder": "[value]",
        "entity_type": "Diagnosis",
        "field_name": "grading"
      }
    ]
  }
}
```

**Problem**: These mappings are stored but **not used** during evaluation. The evaluation engine does not parse template placeholders or use field-specific evaluation logic.

## The Problem: Multi-Value Templates

### Example: Re-excision Template

**Template**:
```
"Re-excision was performed on [provide date] and was macroscopically [complete/incomplete]"
```

**Template Placeholders**:
1. `[provide date]` - Date value (e.g., "15/03/2024")
2. `[complete/incomplete]` - Categorical value (e.g., "complete" or "incomplete")
3. `[select result]` - Optional placeholder for missing information

**Current Evaluation Behavior**:

**Example 1**: Both values correct, different format
- **Expected**: `"Re-excision was performed on 15/03/2024 and was macroscopically complete"`
- **Predicted**: `"Re-excision was performed on 15/3/2024 and was macroscopically complete"`
- **Result**: ❌ Mismatch (due to date format difference: `15/03/2024` vs `15/3/2024`)
- **Issue**: Date is semantically correct but format differs

**Example 2**: One value correct, one incorrect
- **Expected**: `"Re-excision was performed on 15/03/2024 and was macroscopically complete"`
- **Predicted**: `"Re-excision was performed on 15/03/2024 and was macroscopically incomplete"`
- **Result**: ❌ Mismatch (entire string comparison fails)
- **Issue**: Cannot see that date is correct but completeness status is wrong

**Example 3**: Missing placeholder handling
- **Expected**: `"Re-excision was performed on [put date] and was macroscopically complete"`
- **Predicted**: `"Re-excision was performed on 15/03/2024 and was macroscopically complete"`
- **Result**: ❌ Mismatch (literal `[put date]` vs actual date)
- **Issue**: Cannot evaluate that date extraction succeeded when expected indicates missing

### Example: Chemotherapy Start Template

**Template**:
```
"pre-operative chemotherapy with [select intent] started on [provide date] and utilized [select regimen] regimen"
```

**Template Placeholders**:
1. `[select intent]` - Categorical value (e.g., "curative", "palliative")
2. `[provide date]` - Date value
3. `[select regimen]` - Text/categorical value (e.g., "AC", "FOLFIRI")

**Current Evaluation Behavior**:
- All three values are evaluated together as a single string
- Cannot determine which specific field(s) are incorrect
- Cannot apply field-specific metrics (e.g., date accuracy vs categorical accuracy)

## Impact of the Problem

### 1. **Loss of Granular Feedback**
- Cannot identify which specific field(s) in a multi-value template are incorrect
- Evaluation results don't provide actionable feedback for improving specific fields

### 2. **Inappropriate Evaluation Metrics**
- Date values might need format-flexible matching (e.g., `15/03/2024` ≈ `15/3/2024`)
- Categorical values need exact match or semantic equivalence
- Text values might need fuzzy matching or synonym handling
- Current system applies the same metric (exact match or cosine similarity) to all fields

### 3. **Inability to Use Entity Mappings**
- `entity_mapping` configurations exist but are ignored during evaluation
- Cannot leverage field-specific evaluation logic even when mappings are defined

### 4. **Inaccurate Performance Metrics**
- A prompt might have 90% accuracy on dates but 50% accuracy on categorical values
- Current system reports a single overall match rate, masking field-specific performance

### 5. **Placeholder Handling Issues**
- Cannot distinguish between:
  - Missing information (placeholder like `[put date]` in expected)
  - Extracted information (actual date in predicted)
  - Should be evaluated as successful extraction, not mismatch

## Technical Details

### Current Evaluation Function Signature

```python
def evaluate_annotation(
    expected: str,
    predicted: str,
    note_id: Optional[str] = None,
    prompt_type: Optional[str] = None
) -> Dict:
```

**Returns**:
```python
{
    'note_id': note_id,
    'prompt_type': prompt_type,
    'exact_match': bool,
    'similarity_score': float,
    'high_similarity': bool,
    'overall_match': bool,
    'expected_annotation': str,
    'predicted_annotation': str,
    'total_values': int,  # Generic extracted values count
    'values_matched': int,  # Generic matched values count
    'value_match_rate': float,  # Generic match rate
    'value_details': List[Dict]  # Generic value comparison details
}
```

### Generic Value Extraction

The `extract_structured_values()` function extracts:
- Dates via regex patterns
- Numbers with units via pattern matching
- Key-value pairs via colon/bracket patterns
- Enumerations via comma/semicolon splitting

**Problem**: This extraction is **not template-aware** and doesn't map to specific template placeholders.

## Proposed Solution Approach

### 1. **Template-Aware Value Extraction**
- Parse template to identify all placeholders (e.g., `[provide date]`, `[complete/incomplete]`)
- Extract values corresponding to each placeholder from both expected and predicted annotations
- Use regex or pattern matching based on placeholder context

### 2. **Field-Level Evaluation**
- Evaluate each extracted value pair independently
- Apply field-specific evaluation metrics:
  - **Dates**: Format-flexible matching (normalize formats before comparison)
  - **Categorical**: Exact match or semantic equivalence
  - **Text**: Fuzzy matching or synonym handling
  - **Numbers**: Tolerance-based matching (e.g., ±5% for measurements)

### 3. **Use Entity Mappings**
- Leverage `entity_mapping.field_mappings` to determine field types
- Apply appropriate evaluation metrics based on field type
- Support custom evaluation logic per field if needed

### 4. **Placeholder Handling**
- Detect placeholder values (e.g., `[put date]`, `[select result]`) in expected annotations
- Treat as "information not available" rather than literal strings
- Evaluate predicted extraction as successful if placeholder was in expected

### 5. **Enhanced Evaluation Results**
- Return field-level evaluation results:
  ```python
  {
      'overall_match': bool,
      'field_results': [
          {
              'field_name': 'date',
              'placeholder': '[provide date]',
              'expected': '15/03/2024',
              'predicted': '15/3/2024',
              'match': True,
              'match_type': 'format_flexible',
              'similarity': 1.0
          },
          {
              'field_name': 'completeness',
              'placeholder': '[complete/incomplete]',
              'expected': 'complete',
              'predicted': 'incomplete',
              'match': False,
              'match_type': 'exact',
              'similarity': 0.0
          }
      ],
      'field_match_rate': 0.5  # 1 out of 2 fields matched
  }
  ```

## Related Files

- **Evaluation Engine**: `backend/lib/evaluation_engine.py`
- **Evaluation Service**: `backend/services/evaluation_service.py`
- **Annotation Routes**: `backend/routes/annotate.py` (lines 760-765, 1225-1230)
- **Prompt Definitions**: `backend/data/prompts/prompts.json`
- **Entity Mapping Schema**: `backend/models/schemas.py` (EntityFieldMapping, EntityMapping)

## Summary

The current evaluation system treats multi-value templates as single strings, preventing:
1. Field-level accuracy assessment
2. Field-specific evaluation metrics
3. Leveraging entity mapping configurations
4. Proper handling of placeholder values
5. Granular feedback for improvement

A solution should implement template-aware value extraction and field-level evaluation to provide accurate, actionable evaluation results.
