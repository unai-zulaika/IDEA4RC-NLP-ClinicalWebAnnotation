#!/usr/bin/env python3
"""Run an MSCI evaluation pass via the backend (production stack) and assemble a
session JSON that tools/evaluation_report can bucket.

Notes + gold come from the existing 60-note MSCI session; the gold is written into
each note's `annotations` string so the backend scores in evaluation mode (it parses
"<prompt>: <value> | ..." per backend/routes/annotate.py:1009-1027). The /batch
response carries evaluation_result per annotation, which we assemble into
session["annotations"][note_id][prompt_type] and SAVE AFTER EACH CHUNK, so a long
unattended run survives interruption.

Usage:
  python run_msci_eval.py --limit 3                 # validation run (3 notes)
  python run_msci_eval.py --fewshot-k 5 --out-id msci_27b_k5   # full run
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

NLP_DIR = Path(__file__).resolve().parent
REPO_ROOT = NLP_DIR.parents[2]
SRC_SESSION = REPO_ROOT / "backend" / "sessions" / "3effb5be-3c84-492f-ab5d-fecedd5c3173.json"
GOLD_JSON = NLP_DIR / "annotated_msci_notes_verified.json"
RTYPE_JSON = NLP_DIR / "report_type_prompt_mapping_msci.json"
SESSIONS_DIR = REPO_ROOT / "backend" / "sessions"
BACKEND = "http://localhost:8001"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_session(limit: int, use_filter: bool, out_id: str, name: str, exclude: set) -> dict:
    src = json.loads(SRC_SESSION.read_text(encoding="utf-8"))
    prompt_types = [p for p in src["prompt_types"] if p not in exclude]
    gold = json.loads(GOLD_JSON.read_text(encoding="utf-8"))
    gold_by_note: dict[str, list[str]] = {}
    for pat in gold:
        for n in pat["notes"]:
            gold_by_note[str(n["note_id"])] = n.get("annotations", [])

    notes = []
    for n in src["notes"]:
        nid = str(n["note_id"])
        notes.append({
            "text": n["text"],
            "date": n.get("date", ""),
            "p_id": n.get("p_id"),
            "note_id": nid,
            "report_type": n.get("report_type", ""),
            "annotations": " | ".join(gold_by_note.get(nid, [])),
        })
    if limit:
        notes = notes[:limit]

    session = {
        "session_id": out_id,
        "name": name,
        "description": "MSCI production eval assembled by run_msci_eval.py",
        "created_at": _now(),
        "updated_at": _now(),
        "notes": notes,
        "annotations": {},
        "prompt_types": prompt_types,
        "center": "MSCI",
        "evaluation_mode": "evaluation",
        "report_type_mapping": json.loads(RTYPE_JSON.read_text(encoding="utf-8")) if use_filter else None,
    }
    return session


def save(session: dict) -> Path:
    p = SESSIONS_DIR / f"{session['session_id']}.json"
    session["updated_at"] = _now()
    p.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def tally(session: dict) -> dict:
    c: dict[str, int] = {}
    for pm in session["annotations"].values():
        for ann in pm.values():
            er = ann.get("evaluation_result") or {}
            mt = er.get("match_type", "(none)")
            c[mt] = c.get(mt, 0) + 1
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = all notes")
    ap.add_argument("--fewshot-k", type=int, default=5)
    ap.add_argument("--fast-mode", dest="fast_mode", action="store_true")
    ap.add_argument("--no-fast-mode", dest="fast_mode", action="store_false")
    ap.add_argument("--no-filter", dest="use_filter", action="store_false")
    ap.add_argument("--chunk", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--out-id", default="msci_27b_eval")
    ap.add_argument("--name", default="MSCI 27B production eval (W4A16)")
    ap.add_argument("--exclude", default="necrosis_in_biopsy-msci",
                    help="comma-sep prompt_types to skip (no MSCI few-shots -> would pull INT)")
    ap.set_defaults(fast_mode=False, use_filter=True)
    args = ap.parse_args()
    exclude = {e.strip() for e in args.exclude.split(",") if e.strip()}

    # preflight
    st = requests.get(f"{BACKEND}/api/server/status", timeout=10).json()
    print(f"[preflight] backend model={st.get('model_name')} endpoint={st.get('endpoint')} status={st.get('status')}")

    session = build_session(args.limit, args.use_filter, args.out_id, args.name, exclude)
    path = save(session)
    note_ids = [n["note_id"] for n in session["notes"]]
    print(f"[session] {path.name}  notes={len(note_ids)}  prompts={len(session['prompt_types'])}  "
          f"k={args.fewshot_k} fast_mode={args.fast_mode} filter={args.use_filter}")

    t0 = time.time()
    done = 0
    for ci, chunk in enumerate(chunks(note_ids, args.chunk), 1):
        body = {
            "note_ids": chunk,
            "prompt_types": session["prompt_types"],
            "fewshot_k": args.fewshot_k,
            "use_fewshots": args.fewshot_k > 0,
            "fast_mode": args.fast_mode,
        }
        ct0 = time.time()
        r = requests.post(f"{BACKEND}/api/annotate/batch",
                          params={"session_id": session["session_id"]},
                          json=body, timeout=args.timeout)
        r.raise_for_status()
        data = r.json()
        for res in data.get("results", []):
            nid = str(res["note_id"])
            slot = session["annotations"].setdefault(nid, {})
            for ann in res.get("annotations", []):
                slot[ann["prompt_type"]] = ann
        save(session)
        done += len(chunk)
        print(f"[chunk {ci}] {done}/{len(note_ids)} notes  {time.time()-ct0:.0f}s  tally={tally(session)}")

    print(f"[done] wall={time.time()-t0:.0f}s  session={path}")
    print(f"[final tally] {tally(session)}")
    print(f"Report:  python tools/evaluation_report/generate_report.py "
          f"--session backend/sessions/{session['session_id']}.json --center MSCI --out report_msci_27b.md")


if __name__ == "__main__":
    main()
