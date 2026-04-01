# Multi-Event Extraction for History/Anamnesis Notes

## Problem

Clinical notes of type "anamnesis" contain a patient's full clinical history with multiple events across different dates. For example, a single note might describe:

- Breast-conserving surgery (1999)
- Mastectomy with TRAM flap reconstruction (2010)
- Brachytherapy (2013)
- Sarcoma resection (2017)
- Sarcoma recurrence and amputation (2025)

When the annotation pipeline processes these notes, each prompt type (e.g., `surgerytype`, `chemotherapy_start`) extracts only **one value** because:

1. Prompts are designed for singular extraction ("extract THE surgery")
2. The chunking system early-exits after the first confident result
3. `final_output` in the structured output is a single string
4. No aggregation logic exists across sub-sections of a note

This means that for a patient with 5 surgeries, only the first (or most prominent) one is extracted.

## Solution Overview

The feature adds a **pre-processing pipeline** that:

1. **Detects** history/anamnesis notes using heuristics
2. **Splits** them into individual clinical events via an LLM pre-pass
3. **Processes** each event independently through the existing annotation pipeline
4. **Aggregates** results with deduplication into a single annotation with multiple values

This only activates for **repeatable entity types** (cardinality 0 in `entities_cardinality.json`): Surgery, SystemicTreatment, Radiotherapy, etc. Non-repeatable entities (Patient, Diagnosis, ClinicalStage) always process the full original note.

## Architecture

```
                        +-----------------------+
                        |   Note submitted for  |
                        |     processing        |
                        +-----------+-----------+
                                    |
                        +-----------v-----------+
                        | History Note Detector  |
                        | (heuristic-based)      |
                        +-----------+-----------+
                                    |
                          +---------+---------+
                          |                   |
                    is_history=True    is_history=False
                          |                   |
                +---------v---------+         |
                | LLM Note Splitter |         |
                | (one LLM call)    |         |
                +---------+---------+         |
                          |                   |
              +-----------+-----------+       |
              |                       |       |
        repeatable entity      non-repeatable |
        (cardinality 0)        (cardinality 1)|
              |                       |       |
    +---------v---------+     +-------v-------v----+
    | Process each sub- |     | Process full note  |
    | note independently|     | (existing pipeline)|
    +--------+----------+     +--------------------+
             |
    +--------v----------+
    | Result Aggregator  |
    | (dedup + merge)    |
    +--------+----------+
             |
    +--------v----------+
    | AnnotationResult   |
    | with values[]      |
    +--------------------+
```

## Components

### 1. History Note Detector

**File:** `backend/lib/history_detector.py`

Heuristic-based detection using four criteria (OR logic):

| Criterion | Threshold | Example |
|-----------|-----------|---------|
| **Report type keywords** | Any match | `"anamnesis"`, `"wywiad"`, `"anamnesi"`, `"storia clinica"`, `"anamnes"`, `"epikryza"` |
| **Date count** | 3+ distinct dates | `DD.MM.YYYY`, `MM-YYYY`, `DD-MM-YYYY`, `(YYYY)`, ISO format |
| **Event markers** | 3+ occurrences | PL: `"stan po"`, `"po operacji"`; IT: `"intervento chirurgico"`, `"sottoposta a"`; SV: `"opererad"`, `"genomgått"` |
| **Treatment diversity** | 2+ types | Detects surgery, chemotherapy, radiotherapy, recurrence keywords (multilingual) |

Detection requires at least one **strong signal**:
- Report type match alone is sufficient
- Date count + event markers together
- Event markers + diverse treatment types
- 5+ dates + diverse treatment types

**API:**
```python
from lib.history_detector import get_history_detector

detector = get_history_detector()
details = detector.get_detection_details(note_text, report_type="")
# Returns: {
#   "is_history": True,
#   "confidence": 0.9,
#   "detected_events_estimate": 5,
#   "detection_methods": ["date_count", "event_markers", "diverse_treatments"],
#   "date_count": 5,
#   "distinct_years": 4,
#   "event_marker_count": 4,
#   "treatment_types_found": ["surgery", "chemotherapy", "radiotherapy"]
# }
```

### 2. Note Splitter

**File:** `backend/lib/note_splitter.py`

Uses an LLM call with a dedicated prompt (`backend/data/system_prompts/split_history_note.txt`) to split a history note into individual clinical events.

**Input:** Full history note text
**Output:** `NoteSplitResult` containing:
- `shared_context`: Patient-level info (demographics, primary diagnosis) prepended to each event
- `events`: List of `ClinicalEvent` objects, each with `event_text`, `event_type`, and `event_date`
- `was_split`: Whether splitting succeeded (more than one event extracted)

**Key behaviors:**
- Uses **guided decoding** (JSON schema) when available for reliable output
- **Caches** results in memory by `(session_id, note_id)` to avoid re-splitting when processing multiple prompt types
- **Falls back** gracefully: if LLM fails or returns a single event, the original note is processed as-is
- Each sub-note is constructed as: `"{shared_context}\n\n{event_text}"`

**Event types recognized:** `surgery`, `chemotherapy`, `radiotherapy`, `diagnosis`, `recurrence`, `biopsy`, `other_treatment`, `follow_up`, `other`

### 3. Repeatable Entity Detection

**File:** `backend/routes/annotate.py` (function `_is_repeatable_entity`)

Determines whether a prompt type corresponds to a repeatable entity using:
- The prompt's `entity_mapping.entity_type` field (e.g., `"SystemicTreatment"`)
- The `entities_cardinality.json` config (cardinality `0` = repeatable, `1` = non-repeatable)

**Repeatable entities** (splitting applied):
- `SystemicTreatment` (chemotherapy_start, chemotherapy_end, drugs, etc.)
- `Surgery` (surgerytype, surgerymargins, etc.)
- `Radiotherapy` (radiotherapy_start, radiotherapy_end, etc.)
- `EpisodeEvent` (recurrence, progression)
- `OtherLocalTreatment`, `AdverseEvent`, `DiseaseExtent`

**Non-repeatable entities** (full note processed):
- `Patient` (gender, patient-status)
- `Diagnosis` (histological-tipo, tumorsite, ageatdiagnosis)
- `ClinicalStage`, `PathologicalStage`, `PatientFollowUp`

### 4. Result Aggregator

**File:** `backend/lib/result_aggregator.py`

Merges multiple `AnnotationResult` objects from sub-note processing into a single result.

**Deduplication logic:**
- Normalizes text (lowercase, strip punctuation, collapse whitespace)
- Normalizes dates to canonical format for comparison
- Detects substring duplicates (same event mentioned in overlapping sub-notes)
- Detects same-date duplicates where remaining text matches
- Filters out null/empty results (`"Unknown"`, `"N/A"`, `"Not mentioned"`, etc.)

**Output structure:**
- `annotation_text`: The first (chronologically earliest) extraction
- `values[]`: All unique extractions as separate `AnnotationValue` entries, sorted chronologically
- `reasoning`: Combined reasoning from all sub-notes (joined with ` | `)
- `multi_value_info`: Metadata dict with `was_split`, `total_events_detected`, `unique_values_extracted`, `split_method`

### 5. Chunk Early-Exit Fix

**File:** `backend/routes/annotate.py` (chunk loop, ~line 1167)

Previously, when a note was split into chunks (due to exceeding the context window), processing stopped at the **first chunk** that produced a confident result. This meant events in later chunks were never extracted.

**Fix:** For repeatable entity types, the chunk loop now collects results from **all chunks** and aggregates them. Non-repeatable entities retain the original early-exit behavior for efficiency.

## Integration Points

The feature is integrated into all four annotation endpoints:

| Endpoint | Route | Integration |
|----------|-------|-------------|
| **Single note** | `POST /api/annotate/process` | Detection + splitting before parallel prompt processing |
| **Batch** | `POST /api/annotate/batch` | Pre-splits all history notes in parallel before processing |
| **Batch stream** | `POST /api/annotate/batch-stream` | Per-note detection and splitting in the streaming loop |
| **Sequential** | `POST /api/annotate/sequential` | Per-note detection and splitting in the sequential loop |

In all cases:
1. History detection runs once per note
2. LLM splitting runs once per note (shared across all prompt types)
3. `_process_prompt_with_splitting()` routes each prompt type to either sub-note processing (repeatable) or full-note processing (non-repeatable)

## Export

**File:** `backend/routes/sessions.py` (`_build_export_rows`)

When a multi-value annotation (`multi_value_info.was_split = true` and `values.length > 1`) is exported:

- Each value in `values[]` becomes its own CSV row
- Dates are extracted per-value for accurate `date_ref` assignment
- An `event_index` column distinguishes extractions from the same note
- `record_id` is assigned per `(patient_id, entity, date_ref)` tuple, so events with different dates get different record IDs

Single-value annotations export unchanged.

## Frontend UI Feedback

### During Processing — Progress Banner

**File:** `frontend/app/annotate/[sessionId]/page.tsx`

When a history note is detected during single-note processing, a **purple banner** appears above the progress bar showing:

- **Detection summary:** "History note detected — splitting into N events"
- **Criteria breakdown:** e.g., "5 dates · 4 event markers · surgery, chemotherapy, radiotherapy"
- **Collapsible event list:** "Show events" toggle reveals each split event with:
  - Event number, type badge (surgery/chemotherapy/radiotherapy/recurrence/...), date
  - Truncated event text (first 200 chars)

For **batch processing**, a purple summary line shows:
- "N history notes detected — M total events extracted via splitting"
- Post-completion report includes: "History notes: N/total split into M events"

### After Processing — Annotation Display

**File:** `frontend/components/AnnotationViewer.tsx`

- Multi-value annotations display a purple badge: **"N events extracted"**
- Each extracted value is shown as a separate purple-bordered row labeled "Event 1", "Event 2", etc.
- Non-split annotations display normally in a single gray box
- `MultiValueInfo` and `HistoryDetection` interfaces in `frontend/lib/api.ts`

### SSE Payload

The `history_detection` object is sent in SSE progress events (first progress event per note) and includes:

```typescript
interface HistoryDetection {
  is_history: boolean
  was_split: boolean
  events_count: number
  detection_methods: string[]    // 'report_type' | 'date_count' | 'event_markers' | 'diverse_treatments'
  date_count: number
  event_marker_count: number
  treatment_types_found: string[]
  events: SplitEvent[]           // Individual split events with text, type, date
}
```

### E2E Tests

**File:** `frontend/e2e/history-splitting-feedback.spec.ts`

4 Playwright tests using mocked SSE endpoints (no real vLLM needed):
1. Multi-value badge visible after processing a history note
2. No badge when note is not a history note
3. History summary in batch completion report
4. Badge renders correct event count from pre-existing annotations

## Configuration

**File:** `backend/config/vllm_config.json`

```json
{
  "history_splitting": {
    "enabled": true,
    "detection_thresholds": {
      "min_date_count": 3,
      "min_event_markers": 3,
      "min_distinct_treatment_types": 2
    },
    "max_events": 20,
    "max_new_tokens": 4096
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Master switch for the entire feature |
| `min_date_count` | `3` | Minimum distinct dates to trigger detection |
| `min_event_markers` | `3` | Minimum event markers (e.g., "stan po") |
| `min_distinct_treatment_types` | `2` | Minimum different treatment types |
| `max_events` | `20` | Maximum events in JSON schema for guided decoding |
| `max_new_tokens` | `4096` | Token budget for the splitting LLM call |

Set `"enabled": false` to disable splitting entirely and revert to single-value extraction.

## Data Models

### Backend (Pydantic)

```python
# backend/models/annotation_models.py

class ClinicalEvent(BaseModel):
    event_text: str       # Sub-note text for this event
    event_type: str       # surgery, chemotherapy, radiotherapy, diagnosis, etc.
    event_date: str | None  # Primary date if identifiable

class NoteSplitResult(BaseModel):
    shared_context: str        # Patient-level context prepended to each event
    events: list[ClinicalEvent]
    original_text: str         # Original unsplit note
    was_split: bool            # True if >1 event extracted

class MultiValueInfo(BaseModel):
    was_split: bool = False
    total_events_detected: int = 0
    unique_values_extracted: int = 0
    split_method: str = "none"  # "llm" or "none"
```

### Frontend (TypeScript)

```typescript
// frontend/lib/api.ts

interface MultiValueInfo {
  was_split: boolean
  total_events_detected: number
  unique_values_extracted: number
  split_method: string
}
```

Added as `multi_value_info?: MultiValueInfo` to both `AnnotationResult` and `SessionAnnotation`.

## Testing

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `backend/test_history_detection.py` | 20 | Detection heuristics, thresholds, edge cases, report types, multilingual (Polish, Italian, Swedish) |
| `backend/test_note_splitter.py` | 37 | JSON parsing, fallbacks, caching, sub-note construction, deduplication, aggregation, chronological ordering |
| `frontend/e2e/history-splitting-feedback.spec.ts` | 4 | UI feedback: progress banner, multi-value badges, batch reports (mocked SSE, no vLLM needed) |

### Running Tests

```bash
cd backend
.venv/bin/python -m pytest test_history_detection.py test_note_splitter.py -v
```

### Key Test Scenarios

- Polish history notes with multiple surgeries/treatments are detected
- Simple single-event notes are NOT detected (no false positives)
- LLM failure falls back to unsplit processing
- Split results are cached per `(session_id, note_id)`
- Duplicate extractions are deduplicated
- Null results (`"Unknown"`, `"N/A"`) are filtered out
- Results are sorted chronologically by date
- Multiple values aggregate correctly with combined reasoning

## Limitations and Future Work

1. **Splitting quality depends on LLM**: The split prompt works well for structured clinical notes with clear date markers, but may need tuning for unusual note formats.

2. **Cost**: Each history note incurs one extra LLM call for splitting. For batch processing of many history notes, this adds latency proportional to the number of history notes.

3. **No per-value evaluation**: The evaluation system compares against a single gold annotation. Multi-value evaluation (comparing sets of extracted values against sets of expected values) is not yet implemented.

4. **No user override**: Users cannot manually mark a note as history/non-history. The detection is fully automatic based on heuristics.

## Supported Languages

The detector includes multilingual support for event markers, date patterns, treatment keywords, and report type keywords:

| Language | Report Type Keywords | Event Markers | Treatment Keywords |
|----------|---------------------|---------------|-------------------|
| **English** | `anamnesis`, `history`, `epicrisis` | `status post`, `s/p`, `condition after` | `surgery`, `chemotherapy`, `radiotherapy`, `recurrence` |
| **Polish** | `wywiad`, `historia`, `przebieg`, `epikryza` | `stan po`, `po operacji`, `po chemioterapii`, ... | `operacja`, `chemioterapia`, `radioterapii`, `wznowa` |
| **Italian** | `anamnesi`, `storia clinica`, `sintesi clinica`, `evoluzione`, `decorso` | `intervento chirurgico`, `sottoposta a`, `eseguita il`, `E.I.:`, ... | `isteroannessectomia`, `chemioterapia`, `gemcitabina`, `recidiva`, ... |
| **Swedish** | `anamnes`, `sjukhistoria` | `opererad`, `behandlad med`, `status efter`, `genomgått` | `operation`, `kemoterapi`, `strålbehandling`, `recidiv` |

Date formats supported: `DD.MM.YYYY`, `DD/MM/YYYY`, `DD-MM-YYYY`, `MM.YYYY`, `MM/YYYY`, `MM-YYYY`, `YYYY-MM-DD` (ISO), `(YYYY)`.
