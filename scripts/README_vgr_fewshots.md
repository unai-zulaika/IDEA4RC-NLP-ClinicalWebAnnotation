# Build a VGR few-shot CSV from an annotation export

`build_vgr_fewshots.py` converts a VGR annotation export into a CSV you can
upload on the platform under **Upload page → "Upload Few-Shots"** (center **VGR**).

## What you need

From the export you get four files (names contain a number and timestamp):

| File | Used? | Purpose |
|------|-------|---------|
| `annotated_notes_export_*.json` | **required** | note text (clinical input) + inline annotations |
| `data_items_export_*.json` | recommended | authoritative annotation list, joined by `internal_note_id` |
| `data_items_def_export_*.json` | not needed | template definitions (placeholders) |
| `highlights_export_*.json` | not needed | highlighted spans |

Only the two left-hand files are read. The script needs **no third-party
packages** — just Python 3.

## Run it

```bash
# Point it at the folder with the export files (auto-detects the right ones):
python scripts/build_vgr_fewshots.py --input-dir path/to/export_folder -o vgr_fewshots.csv
```

Or pass the files explicitly (globs are fine):

```bash
python scripts/build_vgr_fewshots.py \
    --notes      'path/to/annotated_notes_export_*.json' \
    --data-items 'path/to/data_items_export_*.json' \
    -o vgr_fewshots.csv
```

Then on the platform: **Upload page → "Upload Few-Shots" → center `VGR` →
select `vgr_fewshots.csv`**.

## Output format

A CSV with exactly the three columns the platform expects:

```csv
prompt_type,note_text,annotation
tumorsite,"<original clinical note>","Tumor site (Upper and Lower limbs): Upper leg."
histological,"<original clinical note>","Histological type: ... (8912/3)."
```

* `prompt_type` is the **bare** VGR prompt key (e.g. `tumorsite`, `histological`).
  Do **not** add a `-vgr` suffix — the upload endpoint adds the center suffix
  itself, and retrieval strips it back when matching.
* `note_text` is always the **original** note (never the annotated version), so
  the answer is not leaked into the example.
* `annotation` is the structured sentence expected for that note + prompt type.

## How annotations are found

For each annotation the script pairs it with its note's clean clinical text and
classifies it into a VGR prompt key. Annotations come from two sources, then are
de-duplicated, so it works whether or not the cross-file `internal_note_id`
values line up:

1. **`data_items_export`** — the authoritative annotation rows, joined to their
   note by `internal_note_id`.
2. **Inline parse of `annotated_notes_export`** — each note's `note_text` already
   contains the English annotation sentences interleaved with the original text;
   those lines are extracted and paired with `note_original_text`.

The run prints a summary: how many rows per prompt type, how many came from each
source, and a sample of any annotation sentences it could **not** classify.

## Tuning

* If the summary lists unclassified annotations you care about, add a rule to the
  `VGR_PATTERNS` table near the top of the script (it maps a regex → VGR prompt
  key; first match wins, so put specific rules before generic ones).
* `--max-per-type N` caps examples per prompt type.
* `--keep-placeholders` keeps annotations that still contain template
  placeholders like `[provide date]` (dropped by default as low-quality).
* `--delimiter ';'` writes a semicolon-separated file (the platform accepts both).
