# Output Word Mappings — Prompts UI Editor Design

**Date:** 2026-03-05
**Status:** Approved, pending implementation

## Context

`output_word_mappings` was implemented in the backend (see `2026-03-05-output-word-mappings-design.md`). The feature allows regex patterns to be tested against the LLM `final_output` at annotation time to derive field values. Currently the patterns must be hand-edited in `prompts.json`. This design adds a first-class UI editor in the `/prompts` page.

## Decisions

- **Layout:** Collapsible section inside each field mapping card (mirrors existing `value_code_mappings` pattern)
- **Flags UI:** Two checkboxes — "Case-insensitive" (IGNORECASE) and "Multiline" (MULTILINE)
- **Ordering:** Up/down reorder buttons (order matters — first match wins)
- **Approach:** Inline, not modal

## Files to Change

1. `frontend/lib/api.ts` — add `OutputWordMapping` interface; add `output_word_mappings?: OutputWordMapping[]` to `EntityFieldMapping`
2. `frontend/components/EntityMappingEditor.tsx` — add collapsible "Output Word Mappings" section per field mapping

## Design Detail

### TypeScript types (`frontend/lib/api.ts`)

```typescript
export interface OutputWordMapping {
  pattern: string   // Python re.search() regex tested against LLM final_output
  value: string     // Value to store for this field if pattern matches
  flags?: string    // Comma-separated: "IGNORECASE", "MULTILINE"
}

// Add to EntityFieldMapping:
output_word_mappings?: OutputWordMapping[]
```

### EntityMappingEditor section per field mapping

After the existing "Value-to-Code Mappings" collapsible, add:

**Collapsed (header):**
```
▶ Output Word Mappings (N patterns)
```
Click toggles expansion.

**Expanded:**
```
▼ Output Word Mappings (N patterns)
  ℹ️ Patterns tested in order; first match sets field value. Composes with Value-to-Code Mappings.

  Row 1: [Pattern input (regex)          ] [Value input   ] [↑][↓][×]
         [ ] Case-insensitive  [ ] Multiline

  Row 2: [Pattern input                  ] [Value input   ] [↑][↓][×]
         [ ] Case-insensitive  [ ] Multiline

  [+ Add Pattern]
```

**Per-row fields:**
- Pattern: `<input type="text" placeholder="e.g. no progression|no recurrence">` — full width
- Value: `<input type="text" placeholder="e.g. no_change">` — shorter
- `↑` / `↓` buttons: move row up/down in the list (disabled at first/last position)
- `×`: delete the row
- Checkboxes on next line: "Case-insensitive" and "Multiline"

**Serialization:**
On save, flags checkboxes translate to a comma-separated string in the `flags` field:
- Neither checked → `flags: undefined`
- Only IGNORECASE → `flags: "IGNORECASE"`
- Both → `flags: "IGNORECASE,MULTILINE"`

### No backend changes needed

The backend Pydantic schema already accepts `output_word_mappings` on `EntityFieldMapping`. The `PUT /api/prompts/{type}` endpoint persists whatever is sent, including this new field.
