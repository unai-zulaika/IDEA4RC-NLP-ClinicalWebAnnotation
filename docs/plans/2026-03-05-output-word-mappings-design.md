# Output Word Mappings — Design Document

**Date:** 2026-03-05
**Status:** Implemented

## Problem

Some prompts instruct the LLM to produce a free-text sentence with a clinically meaningful keyword embedded in it (e.g., `recur_or_prog` can output "There was a recurrence on 15/12/2023." or "There was a progression on [date]."). The existing extraction pipeline handles `[placeholder]` patterns but cannot conditionally branch on a keyword embedded within the sentence itself. This means `diseaseStatus` — a field that should be "recurrence", "progression", or "no_change" — could not be properly extracted from these outputs.

## Solution

An `output_word_mappings` list on `EntityFieldMapping` that defines ordered regex pattern → value pairs. After the LLM generates its output, each pattern is tested in order against `final_output`; the first match sets the field value. The resolved value is stored in a new `derived_field_values` dict on the annotation and used at export time, composing naturally with the existing `value_code_mappings` pipeline.

## Data Flow

```
LLM final_output: "There was a recurrence on 15/12/2023."
    ↓
resolve_output_word_mappings(final_output, entity_mapping)
    pattern "no progression|no recurrence" → no match
    pattern "recurrence" → match → {"diseaseStatus": "recurrence"}
    ↓
AnnotationResult.derived_field_values = {"diseaseStatus": "recurrence"}
    stored in session JSON annotation dict
    ↓
UI: annotation_text shown as-is + "Mapped Values" badge showing "diseaseStatus: recurrence"
    ↓
Export _build_export_rows():
    core_variable = "EpisodeEvent.diseaseStatus"
    field_name = "diseaseStatus"
    derived_field_values["diseaseStatus"] = "recurrence"  ← used instead of regex extraction
    ↓
value_code_mappings["recurrence"] = "recurrence_code_id"  ← composable
    ↓
CSV export row: value = "recurrence_code_id"
```

## Configuration Format

Add `output_word_mappings` to any `EntityFieldMapping` in `prompts.json`:

```json
{
  "template_placeholder": "[FULL_ANNOTATION]",
  "entity_type": "EpisodeEvent",
  "field_name": "diseaseStatus",
  "output_word_mappings": [
    { "pattern": "no progression|no recurrence", "value": "no_change", "flags": "IGNORECASE" },
    { "pattern": "recurrence", "value": "recurrence", "flags": "IGNORECASE" },
    { "pattern": "progression", "value": "progression", "flags": "IGNORECASE" }
  ],
  "value_code_mappings": {
    "no_change": "no_change_code_id",
    "recurrence": "recurrence_code_id",
    "progression": "progression_code_id"
  }
}
```

**Rules:**
- Patterns are Python `re.search()` regexes tested against the raw LLM `final_output`
- First match per field wins (order matters — put more specific patterns first)
- Supported flags: `"IGNORECASE"`, `"MULTILINE"` (comma-separated)
- Invalid regex patterns are silently skipped
- `output_word_mappings` composes with `value_code_mappings`: the matched value is looked up in `value_code_mappings` at export time
- `derived_field_values` is cleared when user manually edits an annotation (so stale values aren't exported)

## Files Changed

| File | Change |
|------|--------|
| `backend/models/schemas.py` | Added `OutputWordMapping` model; added `output_word_mappings` field to `EntityFieldMapping`; added `derived_field_values` to `AnnotationResult` |
| `backend/lib/output_mapper.py` | New utility: `resolve_output_word_mappings()` |
| `backend/lib/prompt_adapter.py` | Preserve `entity_mapping` in adapted prompts dict (was previously dropped) |
| `backend/routes/annotate.py` | Call resolver after LLM response; attach `derived_field_values` to `AnnotationResult` |
| `backend/routes/sessions.py` | Use `derived_field_values` in `_build_export_rows()`; clear on manual edit in `update_session()` |
| `frontend/lib/api.ts` | Added `derived_field_values` to `AnnotationResult` and `SessionAnnotation` interfaces |
| `frontend/components/AnnotationDetailView.tsx` | Show "Mapped Values" badges when `derived_field_values` is non-empty |
| `frontend/app/annotate/[sessionId]/page.tsx` | Pass `derived_field_values` through annotation state |
| `backend/data/latest_prompts/{INT,MSCI,VGR}/prompts.json` | Added `output_word_mappings` to `recur_or_prog` prompt as reference example |
