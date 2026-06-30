#!/usr/bin/env python3
"""Build a leakage-safe INT-HNC few-shot pool + eval sessions from int_hnc_phase2.json.

Retrieval (fewshot_builder.get_fewshot_examples) does NOT exclude the query note, so
the few-shot pool MUST come from a disjoint set of PATIENTS. We hold out a deterministic
fraction of the 179 pids for the pool and evaluate on the rest.

Outputs:
  int_hnc_fewshots_pool.csv         pool rows (prompt_type bare, note_text, annotation) -> upload ?center=INT-HNC
  backend/sessions/int_hnc_eval.json    eval notes (non-pool patients) for Q2/Q5/Q7
  backend/sessions/int_hnc_eval60.json  top-60-by-gold eval notes for Q3/Q4/Q7 dimension sweeps
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

NLP = Path(__file__).resolve().parent
ROOT = NLP.parents[2]
SESS = ROOT / "backend" / "sessions"
SUFFIX = "-int-hnc"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_gold(annotations: str) -> list[tuple[str, str]]:
    """'key-int-hnc: ann | key2-int-hnc: ann2' -> [(bare_key, ann), ...]."""
    out = []
    for part in (annotations or "").split(" | "):
        part = part.strip()
        if not part or ": " not in part:
            continue
        key, val = part.split(": ", 1)
        key = key.strip()
        if key.endswith(SUFFIX):
            key = key[: -len(SUFFIX)]
        out.append((key, val.strip()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="int_hnc_phase2")
    ap.add_argument("--pool-frac", type=float, default=0.30, help="fraction of patients held out for the pool")
    ap.add_argument("--eval60", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    session = json.loads((SESS / f"{args.session}.json").read_text(encoding="utf-8"))
    notes = session["notes"]

    # group notes by patient, split patients into pool vs eval (deterministic)
    by_pid = defaultdict(list)
    for n in notes:
        by_pid[n.get("p_id") or n["note_id"]].append(n)
    pids = sorted(by_pid)
    rng = random.Random(args.seed)
    rng.shuffle(pids)
    n_pool = max(1, round(len(pids) * args.pool_frac))
    pool_pids = set(pids[:n_pool])
    eval_pids = set(pids[n_pool:])

    pool_notes = [n for p in pool_pids for n in by_pid[p]]
    eval_notes = [n for p in eval_pids for n in by_pid[p]]

    # --- pool CSV (dedup on (key, note_text, annotation)); bare prompt_type ---
    pool_rows = []
    seen = set()
    per_var = defaultdict(int)
    for n in pool_notes:
        text = n.get("text") or ""
        for key, ann in parse_gold(n.get("annotations", "")):
            sig = (key, text, ann)
            if sig in seen:
                continue
            seen.add(sig)
            pool_rows.append({"prompt_type": key, "note_text": text, "annotation": ann})
            per_var[key] += 1
    pool_csv = NLP / "int_hnc_fewshots_pool.csv"
    with pool_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["prompt_type", "note_text", "annotation"])
        w.writeheader()
        w.writerows(pool_rows)

    # --- eval sessions (annotations reset; same center/prompt_types/report_type_mapping) ---
    def mk_session(out_id, notes_subset, name):
        s = dict(session)
        s["session_id"] = out_id
        s["name"] = name
        s["notes"] = notes_subset
        s["annotations"] = {}
        s["created_at"] = s["updated_at"] = _now()
        (SESS / f"{out_id}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    mk_session("int_hnc_eval", eval_notes, "INT-HNC eval (non-pool patients)")
    gold_count = lambda n: len([1 for _ in parse_gold(n.get("annotations", ""))])
    eval60 = sorted(eval_notes, key=gold_count, reverse=True)[: args.eval60]
    mk_session("int_hnc_eval60", eval60, "INT-HNC eval 60 (dimension sweeps)")

    print(f"patients: pool={len(pool_pids)} eval={len(eval_pids)} (total {len(pids)})")
    print(f"notes: pool={len(pool_notes)} eval={len(eval_notes)}  eval60={len(eval60)}")
    print(f"pool rows={len(pool_rows)} -> {pool_csv.name}")
    print("pool examples per variable (k available):")
    for k in sorted(per_var):
        print(f"    {k:34s} {per_var[k]}")
    missing = [k for k in [r.split(': ')[0] for n in notes for r in [n.get('annotations','')]] if False]
    zero = sorted(set(f"{key}" for n in notes for key, _ in parse_gold(n.get("annotations", ""))) - set(per_var))
    if zero:
        print(f"  WARNING: variables with 0 pool examples (will run zero-shot): {zero}")


if __name__ == "__main__":
    main()
