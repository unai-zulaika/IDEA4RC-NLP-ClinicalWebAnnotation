# Diagnosis vs Recurrence/Metastasis Disambiguation

## Problem

The NLP system sometimes marks recurrences or metastases as diagnoses (and vice versa). Each prompt (`stage_at_diagnosis`, `recurrencetype`, `recur_or_prog`) runs independently on the same note with no shared context about whether the note describes an initial diagnosis or a recurrence/follow-up. This leads to:

- `stage_at_diagnosis` extracting "distant metastases" from notes describing recurrent disease
- `recurrencetype` firing on notes that describe metastatic disease at initial presentation
- No mutual exclusion between diagnosis-stage and recurrence annotations

## Approach: Pre-Classification + Prompt Guardrails

Two-part fix:
1. **Note clinical context classifier** — lightweight LLM pre-pass that classifies the note before annotation prompts run
2. **Prompt guardrails** — inject the classification into affected prompts with explicit exclusion instructions

### Part 1: Note Context Classifier

#### Classification Taxonomy

```
initial_diagnosis  — Note describes the primary/initial diagnosis
recurrence         — Note describes disease recurrence after prior treatment
progression        — Note describes disease progression (worsening without remission)
follow_up          — Note describes routine follow-up, no new disease event
mixed              — Note contains BOTH initial diagnosis info AND recurrence/progression info
unknown            — Cannot determine from the note text
```

#### Integration with History Splitting

The existing history splitter (`note_splitter.py`) already classifies events as `"diagnosis"`, `"recurrence"`, `"follow_up"`, etc. When a note has been split:
- **Derive context from split result**: If all events are "diagnosis" → `initial_diagnosis`. If events include "recurrence" → `mixed` or `recurrence` depending on whether diagnosis events are also present.
- **No extra LLM call needed** for split notes.

For non-split notes (majority of notes):
- Run a single lightweight LLM call with a small token budget (~128 tokens)
- Cache the result like the split cache: `(session_id, note_id) -> NoteContextResult`

#### New File: `backend/lib/note_context_classifier.py`

```python
# Responsibilities:
# 1. Derive context from NoteSplitResult when available
# 2. Run LLM classification when split result is not available
# 3. Cache results per (session_id, note_id)

class NoteContextResult:
    clinical_context: str  # One of the taxonomy values
    confidence: float      # 0.0-1.0
    reasoning: str         # Brief explanation

def derive_context_from_split(split_result: NoteSplitResult) -> NoteContextResult:
    """Derive clinical context from existing split events without LLM call."""
    event_types = {e.event_type for e in split_result.events}
    has_diagnosis = "diagnosis" in event_types
    has_recurrence = "recurrence" in event_types
    # ... logic to map event combinations to context

async def classify_note_context(
    note_text: str,
    vllm_client: Any,
    session_id: str,
    note_id: str,
) -> NoteContextResult:
    """Classify note via LLM when no split result available."""
    # Single LLM call, small token budget, guided decoding
```

#### Pre-Classification Prompt

Stored in `backend/data/system_prompts/classify_note_context.txt`:

```
You are a clinical note classifier. Determine the clinical context of this note.

Classify as exactly ONE of:
- initial_diagnosis: Note describes the primary/first diagnosis of the disease
- recurrence: Note describes disease recurrence after prior treatment/remission
- progression: Note describes disease progression or worsening
- follow_up: Routine follow-up, no new disease event
- mixed: Contains BOTH initial diagnosis AND recurrence/progression information
- unknown: Cannot determine

Key signals:
- Initial diagnosis: first presentation, biopsy confirming diagnosis, no prior treatment history for this disease
- Recurrence: "recidiva", "recurrence", disease returning after treatment/remission
- Progression: "progressione", "progression", disease worsening despite treatment
- Mixed: history notes that summarize initial diagnosis AND subsequent recurrences

Output JSON: {"clinical_context": "<value>", "confidence": <0.0-1.0>, "reasoning": "<brief>"}
```

### Part 2: Prompt Modifications

#### Injection Mechanism

Add a new template variable `{{clinical_context}}` to affected prompts. The `_get_prompt()` function in `annotate.py` replaces it with the classification result. The `update_prompt_placeholders()` function in `prompt_wrapper.py` handles the substitution.

#### Affected Prompts (all 3 centers: INT, MSCI, VGR)

**1. `stage_at_diagnosis` / `stage_at_diagnosis-int`**

Add before "Possible Answers":
```
# Clinical Context
This note has been classified as: {{clinical_context}}.

IMPORTANT RULES:
- If clinical_context is "recurrence" or "progression": Do NOT extract stage at diagnosis from recurrence/metastasis events. Only extract if the note ALSO contains information about the ORIGINAL/INITIAL diagnosis staging.
- If clinical_context is "mixed": Extract ONLY the stage that applies to the INITIAL diagnosis, not to later recurrences.
- If clinical_context is "follow_up": The note likely does not contain diagnosis staging. Output "Unknown stage at diagnosis." unless the initial stage is explicitly mentioned.
```

**2. `recurrencetype` / `recurrencetype-int`**

Add before "Possible Output Templates":
```
# Clinical Context
This note has been classified as: {{clinical_context}}.

IMPORTANT RULES:
- If clinical_context is "initial_diagnosis": Do NOT classify metastatic disease at initial presentation as a recurrence. Output "None" unless there is explicit evidence of disease returning AFTER a prior treatment or remission period.
- If clinical_context is "mixed": Extract ONLY the recurrence/progression type, not initial staging information.
```

**3. `recur_or_prog` / `recur_or_prog-int`**

Add before "Follow these rules":
```
# Clinical Context
This note has been classified as: {{clinical_context}}.

IMPORTANT RULES:
- If clinical_context is "initial_diagnosis": The note describes initial diagnosis, NOT recurrence/progression. Output "There was no progression/recurrence." unless there is explicit evidence of disease returning after treatment.
- If clinical_context is "follow_up" with no disease event: Output "There was no progression/recurrence."
```

### Part 3: Pipeline Integration

In `backend/routes/annotate.py`, the `process_note()` function (line 1304):

```
1. Run history detection (existing, line 1358-1393)
2. NEW: Run note context classification
   a. If note was split → derive_context_from_split(note_split_result)
   b. Else → classify_note_context(note_text, vllm_client, session_id, note_id)
3. Store context result
4. Pass context to _process_single_prompt → _get_prompt (via new parameter)
5. _get_prompt replaces {{clinical_context}} in template
```

The context classification runs AFTER history detection but BEFORE prompt processing, adding minimal latency (one small LLM call for non-split notes, zero for split notes).

### Part 4: Response Payload

Add `clinical_context` to `ProcessNoteResponse` alongside existing `history_detection`:

```python
clinical_context: Optional[Dict] = None
# Example: {"clinical_context": "recurrence", "confidence": 0.85, "reasoning": "...", "source": "llm"|"derived_from_split"}
```

## Files to Modify

| File | Change |
|------|--------|
| `backend/lib/note_context_classifier.py` | **NEW** — classifier logic + cache |
| `backend/data/system_prompts/classify_note_context.txt` | **NEW** — classification prompt |
| `backend/data/prompts/prompts.json` | Modify 9 prompts (3 per center) to add `{{clinical_context}}` |
| `backend/routes/annotate.py` | Integrate classifier in `process_note()`, pass context to `_get_prompt()` |
| `backend/lib/prompt_wrapper.py` | Handle `{{clinical_context}}` placeholder in `update_prompt_placeholders()` |
| `backend/models/schemas.py` | Add `clinical_context` to `ProcessNoteResponse` |

## Verification

1. **Unit test**: `backend/tests/test_note_context_classifier.py`
   - Test `derive_context_from_split()` with various event combinations
   - Test classification prompt formatting
   - Test cache behavior

2. **Integration test**: Process the problematic Patient 1009204 note (sarcoma with bilateral pulmonary metastases)
   - Verify `stage_at_diagnosis` no longer captures metastatic recurrence as staging
   - Verify `recurrencetype` correctly captures the recurrence

3. **Regression test**: Process a known initial-diagnosis note
   - Verify `stage_at_diagnosis` still works correctly
   - Verify `recurrencetype` outputs "None" for pure diagnosis notes

4. **Manual validation**: Re-process a session with the fix and compare annotations before/after
