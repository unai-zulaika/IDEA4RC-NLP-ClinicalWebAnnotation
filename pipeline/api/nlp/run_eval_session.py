#!/usr/bin/env python3
"""Generic, resumable runner: drive the backend /batch over an existing
evaluation-mode session, assemble evaluation_result into the session, save after
each chunk. Survives interruption (re-run with --resume to skip done notes).

  python run_eval_session.py --session-id msci_phase2 --sample 5 --by-gold     # validate
  python run_eval_session.py --session-id msci_phase2 --sample 400 --seed 42   # subset
  python run_eval_session.py --session-id msci_phase2                          # full (resumable)
"""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

NLP_DIR = Path(__file__).resolve().parent
REPO_ROOT = NLP_DIR.parents[2]
SESSIONS_DIR = REPO_ROOT / "backend" / "sessions"
BACKEND = "http://localhost:8001"
DEFAULT_EXCLUDE = "necrosis_in_biopsy-msci,recur_or_prog-msci"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def tally(session: dict) -> dict:
    c: dict[str, int] = {}
    for pm in session["annotations"].values():
        for a in pm.values():
            mt = (a.get("evaluation_result") or {}).get("match_type", "(none)")
            c[mt] = c.get(mt, 0) + 1
    return c


def gold_count(note: dict) -> int:
    return len([x for x in (note.get("annotations") or "").split("|") if x.strip()])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--fewshot-k", type=int, default=5)
    ap.add_argument("--fast-mode", dest="fast_mode", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="0 = all notes")
    ap.add_argument("--by-gold", action="store_true", help="sample highest-gold notes (else random)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chunk", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDE)
    ap.add_argument("--no-resume", dest="resume", action="store_false")
    ap.set_defaults(fast_mode=False, resume=True)
    args = ap.parse_args()

    path = SESSIONS_DIR / f"{args.session_id}.json"
    session = json.loads(path.read_text(encoding="utf-8"))
    session.setdefault("annotations", {})

    exclude = {e.strip() for e in args.exclude.split(",") if e.strip()}
    prompt_types = [p for p in session["prompt_types"] if p not in exclude]

    notes = session["notes"]
    note_ids = [str(n["note_id"]) for n in notes]
    if args.sample:
        if args.by_gold:
            ranked = sorted(notes, key=gold_count, reverse=True)
            note_ids = [str(n["note_id"]) for n in ranked[:args.sample]]
        else:
            rnd = random.Random(args.seed)
            note_ids = sorted(rnd.sample(note_ids, min(args.sample, len(note_ids))))

    if args.resume:
        done = {nid for nid, pm in session["annotations"].items() if pm}
        before = len(note_ids)
        note_ids = [n for n in note_ids if n not in done]
        if before != len(note_ids):
            print(f"[resume] skipping {before - len(note_ids)} already-scored notes")

    st = requests.get(f"{BACKEND}/api/server/status", timeout=10).json()
    print(f"[preflight] model={st.get('model_name')} status={st.get('status')}")
    print(f"[run] session={args.session_id}  notes_to_do={len(note_ids)}  prompts={len(prompt_types)}  "
          f"k={args.fewshot_k} fast_mode={args.fast_mode} exclude={sorted(exclude)}")

    t0 = time.time()
    done_ct = 0
    for ci, chunk in enumerate(chunks(note_ids, args.chunk), 1):
        body = {
            "note_ids": chunk,
            "prompt_types": prompt_types,
            "fewshot_k": args.fewshot_k,
            "use_fewshots": args.fewshot_k > 0,
            "fast_mode": args.fast_mode,
        }
        ct0 = time.time()
        r = requests.post(f"{BACKEND}/api/annotate/batch",
                          params={"session_id": args.session_id},
                          json=body, timeout=args.timeout)
        r.raise_for_status()
        for res in r.json().get("results", []):
            nid = str(res["note_id"])
            slot = session["annotations"].setdefault(nid, {})
            for ann in res.get("annotations", []):
                slot[ann["prompt_type"]] = ann
        session["updated_at"] = _now()
        path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        done_ct += len(chunk)
        print(f"[chunk {ci}] {done_ct}/{len(note_ids)}  {time.time()-ct0:.0f}s  tally={tally(session)}", flush=True)

    print(f"[done] wall={time.time()-t0:.0f}s  scored_notes={len(session['annotations'])}")
    print(f"[final tally] {tally(session)}")
    print(f"Report: python tools/evaluation_report/generate_report.py "
          f"--session backend/sessions/{args.session_id}.json --center MSCI --out report_{args.session_id}.md")


if __name__ == "__main__":
    main()
