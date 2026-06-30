#!/usr/bin/env python3
"""Convert the 60-note MSCI evaluation session into the harness data layout
(parallel to convert_int_data.py, but the source is a finished session JSON
rather than a gold CSV).

  Source:
    backend/sessions/3effb5be-3c84-492f-ab5d-fecedd5c3173.json
    The gold lives at  session["annotations"][note_id][prompt_type]
                              ["evaluation_result"]["expected_annotation"].

  Output (in pipeline/api/nlp/):
    msci_first_patient_notes.csv               (text;date;p_id;note_id;report_type)
    annotated_msci_notes_verified.json         ([{patient_id, notes:[...]}])

Unlike the INT converter, MSCI gold is prompt-keyed, so each annotation string
keeps its key:  "<prompt_type>: <expected_value>".  That preserves the mapping a
future MSCI-aware matcher needs (the INT raw stack strips the key and re-derives
it via regex; we do NOT want that for MSCI).
"""
from __future__ import annotations

import csv
import json
from collections import OrderedDict
from pathlib import Path

NLP_DIR = Path(__file__).resolve().parent
REPO_ROOT = NLP_DIR.parents[2]

SESSION = REPO_ROOT / "backend" / "sessions" / "3effb5be-3c84-492f-ab5d-fecedd5c3173.json"
NOTES_OUT = NLP_DIR / "msci_first_patient_notes.csv"
GOLD_OUT = NLP_DIR / "annotated_msci_notes_verified.json"

NOTE_COLS = ["text", "date", "p_id", "note_id", "report_type"]


def _expected(ann: dict) -> str:
    er = ann.get("evaluation_result") if isinstance(ann, dict) else None
    if not isinstance(er, dict):
        return ""
    val = er.get("expected_annotation")
    if val is None:
        return ""
    return str(val).strip()


def main() -> None:
    session = json.loads(SESSION.read_text(encoding="utf-8"))
    notes = session.get("notes", [])
    ann_by_note = session.get("annotations", {})  # {note_id: {prompt: ann_dict}}

    # notes CSV (no annotation column), semicolon-delimited + QUOTE_ALL like INT
    with NOTES_OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=NOTE_COLS, delimiter=";", quotechar='"',
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        for n in notes:
            w.writerow({c: n.get(c, "") for c in NOTE_COLS})

    patients: "OrderedDict[str, list]" = OrderedDict()
    n_ann = 0
    for n in notes:
        nid = str(n.get("note_id"))
        prompt_map = ann_by_note.get(nid, {}) if isinstance(ann_by_note, dict) else {}
        items = []
        if isinstance(prompt_map, dict):
            for prompt_type, ann in prompt_map.items():
                exp = _expected(ann)
                if exp:
                    items.append(f"{prompt_type}: {exp}")
                    n_ann += 1
        patients.setdefault(n.get("p_id"), []).append({
            "text": n.get("text", ""),
            "date": n.get("date", ""),
            "p_id": n.get("p_id"),
            "note_id": n.get("note_id"),
            "report_type": n.get("report_type", ""),
            "annotations": items,
        })

    gold = [{"patient_id": pid, "notes": ns} for pid, ns in patients.items()]
    GOLD_OUT.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"notes={len(notes)} patients={len(gold)} gold-annotation-items={n_ann}")
    print(f"wrote {NOTES_OUT.name} + {GOLD_OUT.name}")


if __name__ == "__main__":
    main()
