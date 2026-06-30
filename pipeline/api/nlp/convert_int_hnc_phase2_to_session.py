#!/usr/bin/env python3
"""Build an evaluation-mode session from the INT-HNC Phase 2 CSV.

Same sentence-level "phase2" format as MSCI, but HNC gold is matched to one of the
26 HNC variables PURELY by the English `annotation` string (node_id / dict_id are
NOT used and the dict-212 decode table is not in the repo). The 26 predicates below
are transcribed verbatim from each backend/data/INT-HNC-Scripts/*.py filter_annotations
(14 plain startswith, the rest lowercased-substring, 3 with compound AND/NOT logic).

Gold keys are emitted with the `-int-hnc` suffix so they align with the backend
prompt_type + FAISS index (wrong suffix silently runs zero-shot). center is set
EXPLICITLY to INT-HNC. Output: backend/sessions/<out-id>.json, ready for
run_eval_session.py and tools/evaluation_report --center INT-HNC.
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
CSV_PATH = REPO_ROOT / "extra_data" / "INT_HNC" / "H&N_data-phase2.csv"
RTYPE_JSON = NLP_DIR / "report_type_prompt_mapping_int_hnc.json"  # optional (Q5); ok if absent
SESSIONS_DIR = REPO_ROOT / "backend" / "sessions"
SUFFIX = "-int-hnc"

# csv field size: note_original_text can be long
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _sw(prefix):
    return lambda a: a.startswith(prefix)


# (variable_key -> predicate(raw_annotation) -> bool). Verbatim from the 26
# backend/data/INT-HNC-Scripts/*.py filter_annotations. Mutually exclusive on this CSV.
MATCHERS = OrderedDict([
    ("alcohol-habits", _sw("Alcohol habits")),
    ("beam-quality", _sw("Beam quality")),
    ("before-treatment-patient-diagnosed",
     _sw("Before treatment Patient was diagnosed of following comorbidities")),
    ("chemotherapy_start", lambda a: "intent started" in a.lower() and "chemotherapy" in a.lower()
        and "[select setting of systemic treatment]" not in a.lower()),
    ("clinical-tnmstaging", lambda a: "ctt" in a.lower()),
    ("disease-status", _sw("Update of the disease status done")),
    ("histological-tipo", _sw("Histolog")),
    ("hpv-status", _sw("HPV status")),
    ("last-followup-date", _sw("Last follow-up date")),
    ("neck-surgery-laterality", lambda a: "neck surgery was performed" in a.lower()),
    ("pathological-tnmstaging", lambda a: "ptt" in a.lower()),
    ("patient-status", _sw("Status of the patient at last follow-up")),
    ("plasmatic-ebv-dna-status", _sw("Plasmatic EBV DNA")),
    ("radiotherapy_end", lambda a: "radiotherapy in total of" in a.lower()),
    ("radiotherapy_location", lambda a: "radiotherapy on" in a.lower()),
    ("radiotherapy_start", lambda a: "intention was started" in a.lower() and "radiotherapy" in a.lower()),
    ("site-of-metastatic", _sw("Site of metastatic disease")),
    ("smoking-status", _sw("Smoking status")),
    ("staging-classification", _sw("Staging classification")),
    ("surgery-reconstruction", lambda a: "reconstruction was performed" in a.lower()
        and "[select surgery type] [with/without]" not in a.lower()
        and "[select surgery type] with reconstruction was performed on [provide date]" not in a.lower()),
    ("surgerymargins", lambda a: "margins after surgery" in a.lower()),
    ("surgical-specimen-grading", lambda a: "surgical specimen grading" in a.lower()),
    ("systemic-treatment-ended", lambda a: "systemic treatment ended on" in a.lower()),
    ("systemic-treatment-started", lambda a: "systemic treatment alone target therapy" in a.lower()
        or "systemic treatment alone immunotherapy" in a.lower()),
    ("tumorbiopsytype", _sw("Baseline/primary tumor")),
    ("tumorsite", _sw("Tumor site")),
])
SESSION_KEYS = [f"{k}{SUFFIX}" for k in MATCHERS]


def _match_keys(annotation: str) -> list[str]:
    """All variable keys whose predicate matches (should be 0 or 1)."""
    a = annotation.strip()
    return [k for k, pred in MATCHERS.items() if pred(a)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-id", default="int_hnc_phase2")
    ap.add_argument("--name", default="INT-HNC Phase 2 (179 patients)")
    args = ap.parse_args()

    notes: "OrderedDict[str, dict]" = OrderedDict()
    matched = unmatched = multi = matched_rows = 0
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
                "gold": [], "seen": set(),
            })
            ann = (r.get("annotation") or "").strip()
            if not ann:
                continue
            keys = _match_keys(ann)
            if not keys:
                unmatched += 1
                continue
            if len(keys) > 1:
                multi += 1
                print(f"  [MULTI-MATCH] {keys} <- annotation routed ambiguously", file=sys.stderr)
            matched_rows += 1
            key = keys[0]
            item = f"{key}{SUFFIX}: {ann}"
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

    rtype_mapping = json.loads(RTYPE_JSON.read_text(encoding="utf-8")) if RTYPE_JSON.exists() else {}
    session = {
        "session_id": args.out_id, "name": args.name,
        "description": "INT-HNC Phase 2 gold, assembled by convert_int_hnc_phase2_to_session.py",
        "created_at": _now(), "updated_at": _now(),
        "notes": session_notes, "annotations": {},
        "prompt_types": SESSION_KEYS, "center": "INT-HNC",
        "evaluation_mode": "evaluation", "report_type_mapping": rtype_mapping,
    }
    out = SESSIONS_DIR / f"{args.out_id}.json"
    out.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    patients = len({n["p_id"] for n in session_notes if n["p_id"]})
    print(f"wrote {out.name}")
    print(f"  notes={len(session_notes)}  patients={patients}  notes_with_gold={notes_with_gold}")
    print(f"  matched_rows={matched_rows}  unique_gold_items={matched}  unmatched={unmatched}  multi_match={multi}")
    print("  gold items per variable:")
    for k in MATCHERS:
        print(f"    {k}: {per_var.get(k, 0)}")

    # Hard guards: a mapping bug must fail loudly, not silently invalidate the sweep.
    assert multi == 0, f"AMBIGUOUS gold routing: {multi} annotations matched >1 variable"
    assert len(session_notes) == 521, f"expected 521 notes, got {len(session_notes)}"
    assert patients == 179, f"expected 179 patients, got {patients}"
    # raw matching rows + unmatched rows must reconcile to the validated CSV totals
    assert matched_rows == 1395, f"matched_rows={matched_rows}, expected 1395 (validated)"
    assert unmatched == 179, f"unmatched={unmatched}, expected 179 (validated)"
    print("  [asserts passed]")


if __name__ == "__main__":
    main()
