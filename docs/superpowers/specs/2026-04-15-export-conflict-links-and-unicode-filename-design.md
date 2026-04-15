# Export conflict links + Unicode filename fix

Design date: 2026-04-15

## Context

User feedback (2026-04-15) on the Export flow raised two concrete issues plus one
informational observation:

1. **Navigation pain**: the cardinality-conflict modal lists conflicts but gives
   no way to jump to the offending notes. On large sessions the user must
   manually click through the note list to locate each conflict.
2. **Phantom conflict**: one patient remained on the conflict list after the
   user "removed all his annotations". Root cause is not yet confirmed; the
   most likely explanation is that the user could not identify which note
   still carried an annotation (solved by #1), but a real backend bug in
   `_build_export_rows` cannot be ruled out without more information.
3. **JSON export crash** when the session name contains non-ASCII letters:
   ```
   UnicodeEncodeError: 'latin-1' codec can't encode character '\u0119'
   ```
   Traces to a Polish `ę` leaking into the `Content-Disposition` header,
   which Starlette encodes as latin-1.

An additional point in the email — 290/690 radiotherapy notes without extracted
dates — is hardware-dependent and out of scope for this spec.

## Goals

- Let the user click a conflicting value in the Export conflict modal and jump
  straight to the note that produced it, without closing the modal.
- Stop the JSON export from crashing when the session name contains non-ASCII
  characters (common for Polish / other i18n session names).
- Produce a diagnostic signal that will either confirm the phantom-conflict
  issue is just a visibility problem, or pinpoint the real bug for follow-up.

## Non-goals

- No change to cardinality rules, conflict detection logic, or deduplication.
- No refactor of the Export pipeline or the conflict data flow outside of
  surfacing already-available `_note_id` / `_prompt_type` through to the UI.
- No change to radiotherapy date extraction.
- No multi-select / bulk resolution in the modal — one click, one jump.

## Design

### Fix A — Unicode-safe JSON export filename

File: [backend/routes/sessions.py:1387-1393](../../backend/routes/sessions.py#L1387-L1393)

Current code:

```python
safe_name = re.sub(r"[^\w\-]", "_", session.get("name", session_id))
filename = f"{safe_name}_{session_id}.json"
return StreamingResponse(
    io.BytesIO(json_bytes),
    media_type="application/json",
    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
)
```

Problem: Python's `\w` matches Unicode word characters by default, so `ę`, `ą`,
`ö`, etc. survive sanitisation and land in the HTTP header. Starlette encodes
headers as latin-1 and raises `UnicodeEncodeError`.

Fix: strip to ASCII for the legacy `filename=` parameter, and add an RFC 5987
`filename*=UTF-8''...` parameter so clients that honour it still see a
readable Unicode name.

```python
from urllib.parse import quote as _url_quote

raw_name = session.get("name", session_id)
ascii_name = re.sub(r"[^\w\-]", "_", raw_name, flags=re.ASCII)
# Collapse runs of underscores and trim edge underscores
ascii_name = re.sub(r"_+", "_", ascii_name).strip("_") or session_id
ascii_filename = f"{ascii_name}_{session_id}.json"

utf8_filename = f"{raw_name}_{session_id}.json"
encoded = _url_quote(utf8_filename, safe="")

headers = {
    "Content-Disposition": (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{encoded}"
    )
}
```

Rationale:
- `flags=re.ASCII` makes `\w` match only `[A-Za-z0-9_]`, so `ę` → `_`.
- Keeping both forms means legacy browsers still work, modern browsers show
  the pretty name.
- Fallback to `session_id` if stripping leaves an empty string (e.g. name was
  all non-ASCII punctuation).

### Fix B — Surface source note_ids on conflicts; make modal jumpable

#### B1 — Backend schema change

File: [backend/models/schemas.py:449-465](../../backend/models/schemas.py#L449-L465)

Add a `ConflictSource` model carrying the note/prompt that produced a given
value, and attach a list of sources to each `ExportConflict`:

```python
class ConflictSource(BaseModel):
    value: str
    note_id: str
    prompt_type: str

class ExportConflict(BaseModel):
    patient_id: str
    core_variable: str
    date_ref: Optional[str] = None
    conflicting_values: List[str]
    conflict_type: str
    sources: List[ConflictSource] = []
```

`conflicting_values` is kept for backward-compatibility with existing code
paths and tests; `sources` is the new per-row detail.

#### B2 — Populate sources in `_validate_and_deduplicate_rows`

File: [backend/routes/sessions.py:983-1065](../../backend/routes/sessions.py#L983-L1065)

Rows already carry `_note_id` and `_prompt_type` (see
[backend/routes/sessions.py:894-909](../../backend/routes/sessions.py#L894-L909)).
Today the deduplicator groups by `(entity, core_variable, date_ref, value)` and
drops the source identifiers. Change the two grouping dicts from
`Dict[tuple, set]` to `Dict[tuple, List[ConflictSource]]` so each contributing
row is remembered. When emitting a conflict, sort `sources` by note_id for
stable output and deduplicate `(value, note_id, prompt_type)` triples.

```python
non_rep_sources: Dict[tuple, List[ConflictSource]] = defaultdict(list)
rep_sources: Dict[tuple, List[ConflictSource]] = defaultdict(list)

for row in deduped:
    entity = row['entity']
    card = cardinality.get(entity)
    src = ConflictSource(
        value=row['value'],
        note_id=row.get('_note_id', ''),
        prompt_type=row.get('_prompt_type', ''),
    )
    if card == 1:
        non_rep_sources[(row['patient_id'], row['core_variable'])].append(src)
    else:
        non_rep_sources  # unchanged
        rep_sources[(row['patient_id'], row['core_variable'], row['date_ref'])].append(src)
```

Then when emitting a conflict, derive `conflicting_values` from
`{s.value for s in sources}` and attach the sorted, de-duplicated source list.

#### B3 — Thread the schema through the frontend

File: [frontend/lib/api.ts:110-121](../../frontend/lib/api.ts#L110-L121)

Mirror the backend schema:

```ts
export interface ConflictSource {
  value: string
  note_id: string
  prompt_type: string
}

export interface ExportConflict {
  patient_id: string
  core_variable: string
  date_ref: string | null
  conflicting_values: string[]
  conflict_type: 'non_repeatable' | 'repeatable_same_date'
  sources: ConflictSource[]
}
```

#### B4 — Jump-to-note affordance in the modal

File: [frontend/app/annotate/[sessionId]/page.tsx:1516-1590](../../frontend/app/annotate/[sessionId]/page.tsx#L1516-L1590)

Replace the current value chips block with per-source chips. Each chip shows
the conflicting value and a clickable note reference. The modal stays open so
the user can keep working through the list.

Sketch:

```tsx
<td className="py-2">
  <div className="flex flex-col gap-1">
    {c.sources.map((s, j) => (
      <div key={j} className="flex items-center gap-2">
        <span className="inline-block px-1.5 py-0.5 text-xs rounded bg-gray-100 text-gray-700 font-mono">
          {s.value}
        </span>
        <button
          type="button"
          onClick={() => jumpToNote(s.note_id, s.prompt_type)}
          className="text-xs text-primary-600 hover:text-primary-800 underline"
          title={`Jump to note ${s.note_id}`}
        >
          → {shortNoteLabel(s.note_id)}
        </button>
      </div>
    ))}
  </div>
</td>
```

`jumpToNote` reuses the existing pattern at
[frontend/app/annotate/[sessionId]/page.tsx:151-153](../../frontend/app/annotate/[sessionId]/page.tsx#L151-L153):

```ts
const jumpToNote = (noteId: string, promptType: string) => {
  const idx = session.notes.findIndex(n => n.note_id === noteId)
  if (idx === -1) return
  setSelectedNoteIndex(idx)
  setScrollToPromptType(promptType)
  // Do NOT close the modal — user can continue ticking off conflicts
}
```

`shortNoteLabel` returns a truncated form of the note_id (e.g. last 8 chars
with ellipsis) to keep rows compact. Full id stays in the `title` tooltip.

Edge cases:
- Missing note (note_id not found in `session.notes`) — render the chip as a
  disabled span with a tooltip "note not found" instead of a button.
- Empty `sources` array on a legacy conflict object — fall back to the current
  chip-only rendering so old clients don't break.

### Phantom-conflict diagnostic

No separate logic needed — once B4 is shipped, every conflict row exposes the
exact notes that contributed. Two outcomes:

- If the phantom case was a visibility problem, the user clicks through, sees
  no remaining annotation, and the conflict no longer reproduces after a
  fresh export validation.
- If the conflict survives deletion, the source note_id is visible and we can
  reproduce the bug directly (open session JSON, inspect
  `annotations[note_id][prompt_type]`, see whether `annotation_text` is still
  populated or whether a stale `values[]` array survives).

If a true backend bug surfaces from that, it gets its own fix in a follow-up
spec — deliberately out of scope here.

## Tests

### Backend
- Extend `backend/test_session_import_export.py` with a test that exports a
  session whose name contains Polish `ę` and asserts the response status is
  200, `Content-Disposition` decodes cleanly as latin-1, and the
  `filename*=UTF-8''` parameter round-trips the original name.
- Extend `backend/test_export_cardinality.py`:
  - `test_conflict_sources_populated`: a non-repeatable conflict carries both
    contributing `ConflictSource`s with their `note_id` and `prompt_type`.
  - `test_conflict_sources_deduplicated`: identical `(value, note_id,
    prompt_type)` triples appear once.
  - `test_conflict_sources_repeatable_same_date`: for same-date repeatable
    conflicts, each differing value's source note is preserved.

### Frontend
- No automated test harness exists for the frontend (per `CLAUDE.md`). Manual
  verification:
  1. Create a session with two notes for the same patient where the same
     non-repeatable field resolves to conflicting values.
  2. Attempt export → conflict modal opens → each conflicting value shows a
     clickable note link.
  3. Click a link → note opens in the main editor, modal stays open, target
     prompt is scrolled into view.
  4. Resolve the conflict, re-run export, confirm the conflict is gone.
  5. Create a session named with a Polish name (`Próba ę`) and export as JSON
     → download succeeds, file name contains a sensible ASCII fallback.

## Rollout

- Single PR covering all three fixes. No migrations, no flags.
- Backwards compatible: `sources` defaults to `[]` on the backend; frontend
  falls back to the old rendering when `sources` is empty.

## Risks

- **Old sessions**: sessions created before this change have no `_note_id` in
  their cached row builds, but `_build_export_rows` always reconstructs rows
  from `session['annotations']` on each request, so `_note_id` is always
  populated on live builds — no migration needed.
- **Header length**: RFC 5987 encoding can make very long Unicode names
  produce long headers. Not a practical concern for session names capped at
  a few hundred characters.
- **Phantom-conflict investigation may surface a real bug** that is not fixed
  by this spec. That is accepted — this spec is scoped to visibility; any
  follow-up bug gets its own fix.
