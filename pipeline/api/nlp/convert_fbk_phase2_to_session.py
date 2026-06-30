#!/usr/bin/env python3
"""Build a full evaluation-mode session from the FBK Phase 2 MSCI CSV.

The Phase 2 CSV is sentence-level: each annotation row carries an `annotation`
string in CLN format ("Histological type: ...", "Patient's gender female.", ...).
We group rows by note, prefix-match each annotation to a variable using the
fbk_reproduction VarSpec.pool_prefixes, and re-key it as "<session_key>: <annotation>"
so the backend evaluation parser (annotate.py:1009-1027) finds the gold by prompt_type.

Output: backend/sessions/<out-id>.json  (evaluation_mode=evaluation), ready to run
via run_eval_session.py and bucket via tools/evaluation_report.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

NLP_DIR = Path(__file__).resolve().parent
REPO_ROOT = NLP_DIR.parents[2]
sys.path.insert(0, str(REPO_ROOT / "experiments" / "fbk_reproduction"))
from full_25_templates import VARIABLES  # noqa: E402

CSV_PATH = REPO_ROOT / "FBK_MSCI" / "MSCI_Data_25_patients_phase2_data.csv"
RTYPE_JSON = NLP_DIR / "report_type_prompt_mapping_msci.json"
SESSIONS_DIR = REPO_ROOT / "backend" / "sessions"

# (prefix, session_key), longest prefix first so specific prefixes win.
PREFIX_MAP = sorted(
    [(p, v.session_key) for v in VARIABLES.values() for p in v.pool_prefixes],
    key=lambda x: -len(x[0]),
)
SESSION_KEYS = [v.session_key for v in VARIABLES.values()]


def _match_key(annotation: str) -> str | None:
    a = annotation.strip()
    for prefix, key in PREFIX_MAP:
        if a.startswith(prefix):
            return key
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-id", default="msci_phase2")
    ap.add_argument("--name", default="MSCI FBK Phase 2 (133 patients)")
    args = ap.parse_args()

    notes: "OrderedDict[str, dict]" = OrderedDict()
    matched = 0
    unmatched = 0
    per_var: dict[str, int] = {}
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            nid = str(r.get("internal_note_id", "")).strip()
            if not nid:
                continue
            n = notes.setdefault(nid, {
                "text": (r.get("note_original_text") or r.get("note_text") or ""),
                "date": r.get("note_date", "") or "",
                "p_id": str(r.get("pid", "")).strip(),
                "report_type": (r.get("note_name") or "").strip(),
                "gold": [],          # list of "session_key: annotation"
                "seen": set(),       # dedup
            })
            ann = (r.get("annotation") or "").strip()
            if not ann:
                continue
            key = _match_key(ann)
            if key is None:
                unmatched += 1
                continue
            item = f"{key}: {ann}"
            if item not in n["seen"]:
                n["seen"].add(item)
                n["gold"].append(item)
                matched += 1
                per_var[key] = per_var.get(key, 0) + 1

    session_notes = []
    notes_with_gold = 0
    for nid, n in notes.items():
        if n["gold"]:
            notes_with_gold += 1
        session_notes.append({
            "text": n["text"], "date": n["date"], "p_id": n["p_id"],
            "note_id": nid, "report_type": n["report_type"],
            "annotations": " | ".join(n["gold"]),
        })

    rtype_mapping = json.loads(RTYPE_JSON.read_text(encoding="utf-8"))
    rt_keys = set(rtype_mapping.keys())
    rt_match = sum(1 for n in session_notes if n["report_type"] in rt_keys)

    session = {
        "session_id": args.out_id,
        "name": args.name,
        "description": "FBK Phase 2 gold, assembled by convert_fbk_phase2_to_session.py",
        "created_at": _now(),
        "updated_at": _now(),
        "notes": session_notes,
        "annotations": {},
        "prompt_types": SESSION_KEYS,
        "center": "MSCI",
        "evaluation_mode": "evaluation",
        "report_type_mapping": rtype_mapping,
    }
    out = SESSIONS_DIR / f"{args.out_id}.json"
    out.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    patients = len({n["p_id"] for n in session_notes if n["p_id"]})
    print(f"wrote {out.name}")
    print(f"  notes={len(session_notes)}  patients={patients}  notes_with_gold={notes_with_gold}")
    print(f"  gold items matched={matched}  unmatched_annotation_rows={unmatched}")
    print(f"  report_type in mapping: {rt_match}/{len(session_notes)} notes")
    print("  gold items per variable:")
    for k in SESSION_KEYS:
        print(f"    {k}: {per_var.get(k, 0)}")


if __name__ == "__main__":
    main()
