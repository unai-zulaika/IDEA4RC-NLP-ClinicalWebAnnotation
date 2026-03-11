# Output Word Mappings Editor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an "Output Word Mappings" collapsible section to each field mapping card in the Entity Mapping Editor (`/prompts`) so users can define ordered regex pattern → value mappings without hand-editing `prompts.json`.

**Architecture:** Two changes only — add `OutputWordMapping` TypeScript types to `api.ts`, then add an `OutputWordMappingsSection` component inside `EntityMappingEditor.tsx` that mirrors the existing `ValueCodeMappingsSection` pattern. No backend changes needed (Pydantic already accepts `output_word_mappings`).

**Tech Stack:** React 18, TypeScript, Tailwind CSS. No new dependencies.

---

### Task 1: Add TypeScript types

**Files:**
- Modify: `frontend/lib/api.ts` (find the `EntityFieldMapping` interface)

**Step 1: Add `OutputWordMapping` interface**

Find the block containing `EntityFieldMapping` in `frontend/lib/api.ts`. Add this new interface directly above `EntityFieldMapping`:

```typescript
export interface OutputWordMapping {
  pattern: string   // Python re.search() regex tested against LLM final_output
  value: string     // Value to store for this field if pattern matches
  flags?: string    // Comma-separated: "IGNORECASE", "MULTILINE"
}
```

**Step 2: Add `output_word_mappings` field to `EntityFieldMapping`**

Inside the `EntityFieldMapping` interface, add after `value_code_mappings`:

```typescript
  output_word_mappings?: OutputWordMapping[]
```

**Step 3: Verify TypeScript compiles**

```bash
cd /home/zulaika/ClinicalAnnotationWeb/frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors (or only pre-existing unrelated errors).

**Step 4: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat: add OutputWordMapping TypeScript interface to EntityFieldMapping"
```

---

### Task 2: Add `OutputWordMappingsSection` component

**Files:**
- Modify: `frontend/components/EntityMappingEditor.tsx`

The component is added as a sibling to `ValueCodeMappingsSection` at the top of the file, then rendered after `<ValueCodeMappingsSection .../>` in each field mapping card.

**Step 1: Add the import for `OutputWordMapping`**

At line 4, change:
```typescript
import type { EntityMapping, EntityFieldMapping } from '@/lib/api'
```
to:
```typescript
import type { EntityMapping, EntityFieldMapping, OutputWordMapping } from '@/lib/api'
```

**Step 2: Add `OutputWordMappingsSection` component**

Insert this new component immediately after the closing `}` of `ValueCodeMappingsSection` (after line 104) and before the `interface EntityMappingEditorProps` declaration:

```typescript
function OutputWordMappingsSection({
  mappings,
  onChange,
}: {
  mappings?: OutputWordMapping[]
  onChange: (mappings: OutputWordMapping[] | undefined) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const list = mappings || []

  const addPattern = () => {
    onChange([...list, { pattern: '', value: '', flags: 'IGNORECASE' }])
    setExpanded(true)
  }

  const removePattern = (i: number) => {
    const updated = list.filter((_, idx) => idx !== i)
    onChange(updated.length > 0 ? updated : undefined)
  }

  const updatePattern = (i: number, patch: Partial<OutputWordMapping>) => {
    const updated = list.map((item, idx) => idx === i ? { ...item, ...patch } : item)
    onChange(updated)
  }

  const moveUp = (i: number) => {
    if (i === 0) return
    const updated = [...list]
    ;[updated[i - 1], updated[i]] = [updated[i], updated[i - 1]]
    onChange(updated)
  }

  const moveDown = (i: number) => {
    if (i === list.length - 1) return
    const updated = [...list]
    ;[updated[i], updated[i + 1]] = [updated[i + 1], updated[i]]
    onChange(updated)
  }

  const hasFlag = (flags: string | undefined, flag: string) =>
    (flags || '').split(',').map(f => f.trim()).includes(flag)

  const toggleFlag = (i: number, flag: string, checked: boolean) => {
    const current = (list[i].flags || '').split(',').map(f => f.trim()).filter(Boolean)
    const next = checked
      ? Array.from(new Set([...current, flag]))
      : current.filter(f => f !== flag)
    updatePattern(i, { flags: next.length > 0 ? next.join(',') : undefined })
  }

  return (
    <div className="mt-2 border border-purple-200 rounded-md">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex justify-between items-center px-2 py-1.5 text-xs font-medium text-purple-800 bg-purple-50 hover:bg-purple-100 rounded-t-md"
      >
        <span>Output Word Mappings {list.length > 0 && `(${list.length} pattern${list.length > 1 ? 's' : ''})`}</span>
        <span>{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>
      {expanded && (
        <div className="p-2 space-y-2">
          <p className="text-xs text-gray-500">
            Regex patterns tested against LLM output in order; first match sets the field value. Composes with Value-to-Code Mappings.
          </p>
          {list.map((owm, i) => (
            <div key={i} className="border border-purple-100 rounded p-2 bg-purple-50 space-y-1.5">
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={owm.pattern}
                  onChange={(e) => updatePattern(i, { pattern: e.target.value })}
                  placeholder="Pattern (e.g. recurrence)"
                  className="flex-1 px-2 py-1 border border-gray-300 rounded text-xs font-mono"
                />
                <input
                  type="text"
                  value={owm.value}
                  onChange={(e) => updatePattern(i, { value: e.target.value })}
                  placeholder="Value (e.g. recurrence)"
                  className="w-32 px-2 py-1 border border-gray-300 rounded text-xs"
                />
                <button
                  type="button"
                  onClick={() => moveUp(i)}
                  disabled={i === 0}
                  className="px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded text-xs hover:bg-gray-300 disabled:opacity-30"
                  title="Move up"
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => moveDown(i)}
                  disabled={i === list.length - 1}
                  className="px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded text-xs hover:bg-gray-300 disabled:opacity-30"
                  title="Move down"
                >
                  ↓
                </button>
                <button
                  type="button"
                  onClick={() => removePattern(i)}
                  className="px-1.5 py-0.5 bg-red-500 text-white rounded text-xs hover:bg-red-600"
                  title="Remove pattern"
                >
                  ×
                </button>
              </div>
              <div className="flex items-center gap-3 pl-0.5">
                <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={hasFlag(owm.flags, 'IGNORECASE')}
                    onChange={(e) => toggleFlag(i, 'IGNORECASE', e.target.checked)}
                    className="rounded"
                  />
                  Case-insensitive
                </label>
                <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={hasFlag(owm.flags, 'MULTILINE')}
                    onChange={(e) => toggleFlag(i, 'MULTILINE', e.target.checked)}
                    className="rounded"
                  />
                  Multiline
                </label>
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={addPattern}
            className="text-xs text-purple-700 hover:text-purple-900 font-medium"
          >
            + Add Pattern
          </button>
        </div>
      )}
    </div>
  )
}
```

**Step 3: Render it in each field mapping card**

Find this block in `EntityMappingEditor.tsx` (around line 381-385):

```tsx
                  {/* Value-to-Code Mappings */}
                  <ValueCodeMappingsSection
                    mappings={fm.value_code_mappings}
                    onChange={(vcm) => updateFieldMapping(index, { value_code_mappings: vcm })}
                  />
```

Add the new section immediately after it:

```tsx
                  {/* Value-to-Code Mappings */}
                  <ValueCodeMappingsSection
                    mappings={fm.value_code_mappings}
                    onChange={(vcm) => updateFieldMapping(index, { value_code_mappings: vcm })}
                  />
                  {/* Output Word Mappings */}
                  <OutputWordMappingsSection
                    mappings={fm.output_word_mappings}
                    onChange={(owm) => updateFieldMapping(index, { output_word_mappings: owm })}
                  />
```

**Step 4: Verify TypeScript compiles**

```bash
cd /home/zulaika/ClinicalAnnotationWeb/frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors (or only pre-existing unrelated errors).

**Step 5: Verify the dev server starts**

```bash
cd /home/zulaika/ClinicalAnnotationWeb/frontend && npm run build 2>&1 | tail -20
```

Expected: build completes without errors.

**Step 6: Commit**

```bash
git add frontend/components/EntityMappingEditor.tsx
git commit -m "feat: add Output Word Mappings editor section to Entity Mapping Editor"
```

---

### Task 3: Manual verification

Navigate to `http://localhost:3000/prompts`, select a prompt (e.g. `recur_or_prog-int`), open the Entity Mapping Editor. For the `diseaseStatus` field mapping:

1. Click "Output Word Mappings (3 patterns)" — the section expands showing 3 rows
2. Each row shows a pattern input (purple, monospace font), a value input, ↑/↓/× buttons
3. The "Case-insensitive" checkbox is checked on each row
4. Add a new pattern via "+ Add Pattern" — a blank row appears
5. Reorder with ↑/↓ — order changes
6. Delete a row with ×
7. Save the mapping — verify it persists when you reload the prompt

**No automated tests needed** — this is a pure UI change with no new backend logic. The `output_word_mappings` data already flows correctly through the backend pipeline (covered by the existing annotation runtime).
