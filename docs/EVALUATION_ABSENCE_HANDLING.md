# Evaluation of Absence/None Cases

## Problem Analysis

### Current Issue
When evaluating annotations:
- **Expected**: `""` (empty, meaning no annotation expected)
- **Predicted**: `"Tumor depth: Not specified"` (LLM correctly identifies absence)

**Current Result**: ❌ Mismatch (False Positive)

**Expected Result**: ✅ Match (Both indicate absence)

### Root Cause

The `is_no_annotation_indicator()` function uses patterns that require the ENTIRE string to match, but structured annotations have format:
- `"Tumor depth: Not specified"`
- `"Biopsy grading: Unknown biopsy grading"`
- `"Margins after surgery: [select result]"`

The patterns like `^not\s+specified$` only match if the entire string is "not specified", not when it's part of a structured annotation.

## Current Logic Flow

1. **Expected is empty** → `expected_is_empty = True`
2. **Predicted is "Tumor depth: Not specified"** → `is_no_annotation_indicator()` returns `False` (doesn't match `^not\s+specified$`)
3. **Result**: Special case 3 triggered → False Positive (mismatch)

## Solution Approaches

### Approach 1: Extract Value from Structured Annotations (Recommended)
Extract the value part after the colon and check if it indicates absence.

**Pros**: 
- Handles structured format correctly
- Works for all prompt types
- Most accurate

**Cons**:
- Requires parsing structured format
- Need to handle edge cases (no colon, multiple colons)

### Approach 2: Pattern Matching Anywhere in Text
Change patterns to match anywhere in the text, not just at start/end.

**Pros**:
- Simple implementation
- Catches most cases

**Cons**:
- May have false positives (e.g., "The tumor was not specified to be malignant" would match)
- Less precise

### Approach 3: Prompt-Type-Specific Patterns
Use prompt-type-specific patterns to extract the value portion.

**Pros**:
- Very accurate for known formats
- Handles edge cases well

**Cons**:
- Requires maintenance for each prompt type
- Less generalizable

## Recommended Solution: Hybrid Approach

Combine Approach 1 and 2:
1. Try to extract value from structured format (after colon)
2. Check both the full text and extracted value against absence patterns
3. Use word boundary matching to avoid false positives

## Implementation

The fix has been implemented in `backend/services/evaluation_service.py`:

### Enhanced `is_no_annotation_indicator()` Function

**Key Improvements:**
1. **Extracts value from structured annotations**: 
   - Detects format "Label: Value" and extracts the value part
   - Example: "Tumor depth: Not specified" → extracts "Not specified"

2. **Checks multiple text parts**:
   - Checks both the full normalized text AND the extracted value
   - Catches cases where absence indicator is in the value portion

3. **Uses word boundaries**:
   - Patterns use `\b` word boundaries to avoid false positives
   - Example: "not specified" matches, but "specified" alone doesn't

4. **Handles placeholder values**:
   - Detects placeholders like "[select result]", "[put date]", etc.
   - These indicate the LLM couldn't find information

### Patterns Detected

The function now detects:
- Simple absence: "none", "n/a", "na", "unknown"
- Explicit absence: "not specified", "not available", "not applicable"
- Information absence: "no information", "information not available"
- Placeholder values: "[select result]", "[put date]", etc.
- Structured absence: "Tumor depth: Not specified", "Biopsy grading: Unknown"

### Example Cases

| Expected | Predicted | Result | Reason |
|----------|-----------|--------|--------|
| `""` | `"Tumor depth: Not specified"` | ✅ Match | Value "Not specified" indicates absence |
| `""` | `"Biopsy grading: Unknown biopsy grading"` | ✅ Match | "Unknown" indicates absence |
| `""` | `"Margins after surgery: [select result]"` | ✅ Match | Placeholder indicates absence |
| `""` | `"Tumor depth: deep"` | ❌ Mismatch | Actual value present (false positive) |
| `"Tumor depth: superficial"` | `"Tumor depth: Not specified"` | ❌ Mismatch | Expected value, got absence (false negative) |

## Solution Implementation

### Two-Pronged Approach

We've implemented a **two-pronged solution** to handle absence cases:

#### 1. **Prompt-Level Standardization** (Prevention)
Updated `backend/lib/prompt_wrapper.py` to enforce a standard absence format in prompts:
- **Standard Format**: "Not applicable" (consistent across all prompts)
- **Structured Format**: "[Label]: Not applicable" (e.g., "Tumor depth: Not applicable")
- **Instructions**: Explicitly tells the model to use "Not applicable" consistently

#### 2. **Post-Processing Normalization** (Correction)
Created `backend/lib/annotation_normalizer.py` to normalize variations:
- Detects absence indicators: "Not specified", "Not available", "Unknown", etc.
- Normalizes to standard format: "Not applicable" or "[Label]: Not applicable"
- Applied automatically after LLM generation

### Benefits

1. **Consistency**: All absence cases use the same format
2. **Reliability**: Works even if model doesn't follow instructions perfectly
3. **Evaluation Accuracy**: Standardized format makes evaluation matching easier
4. **Maintainability**: Single source of truth for absence format

### Code Changes

**New File**: `backend/lib/annotation_normalizer.py`
- `normalize_absence_indicator()`: Normalizes absence indicators
- `normalize_annotation_output()`: Main normalization function

**Updated**: `backend/routes/annotate.py`
- All annotation extraction points now normalize absence indicators
- Applied to both structured and fallback generation paths

**Updated**: `backend/lib/prompt_wrapper.py`
- Enhanced instructions for standardized absence format
- More explicit guidance on when and how to use "Not applicable"

## Testing

To test the fix:
1. Process a note with no expected annotation for a prompt type
2. LLM may predict absence in various formats (e.g., "Not specified", "Unknown", "Not available")
3. Post-processing normalizes to: "Tumor depth: Not applicable" (or "Not applicable")
4. Evaluation should show ✅ Match, not ❌ Mismatch

