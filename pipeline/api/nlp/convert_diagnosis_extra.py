#!/usr/bin/env python3
"""Build INT-SARC topo/morpho eval sessions from extra_data/diagnosis_extra/.

Two sessions (leakage-safe: this gold is not in any few-shot pool; runs are zero-shot k=0):
  sarc_path_topomorpho : 200 pathology reports -> gold for histological-tipo-int (morpho code)
                         AND tumorsite-int (topo category). Source = pathology diagnosis text.
  sarc_rol_topo        : 150 ROL patient-groups -> gold for tumorsite-int (topo from narrative).

Free-text source columns are PHI and stay on-server; only aggregate scores ever leave.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/zulaika/ClinicalAnnotationWeb")
EXTRA = ROOT / "extra_data" / "diagnosis_extra"
SESS = ROOT / "backend" / "sessions"
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _morpho_gold(descr, code):
    return f"Histological type: {descr} ({code})"


def build_pathology(limit, seed):
    rows = []
    with (EXTRA / "Pathology_SARC.csv").open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f, delimiter=";"):
            code = (r.get("icd_morpho_code_annotation") or "").strip()
            topo = (r.get("icd_topo_annotation") or "").strip()
            descr = (r.get("icd_morpho_annotation") or "").strip()
            text = ((r.get("pathol_repere_description") or "") + "\n"
                    + (r.get("pathol_diagnosis_desciption") or "")).strip()
            if code and topo and len(text) > 40:           # need both gold + real text
                rows.append({"pid": (r.get("patient_id") or "").strip(),
                             "note_id": (r.get("pathology_report_code") or "").strip() or f"path{len(rows)}",
                             "text": text, "topo": topo, "descr": descr, "code": code})
    rng = random.Random(seed)
    rng.shuffle(rows)
    sample = rows[:limit]
    notes = []
    for r in sample:
        gold = f"histological-tipo-int: {_morpho_gold(r['descr'], r['code'])} | tumorsite-int: {r['topo']}"
        notes.append({"text": r["text"], "date": "", "p_id": r["pid"], "note_id": r["note_id"],
                      "report_type": "Pathology", "annotations": gold})
    return notes


def build_rol(limit, seed):
    # group rows by patient, concatenate the labelled narratives, take the modal topo
    by_pid = defaultdict(lambda: {"texts": [], "topo": Counter()})
    with (EXTRA / "ROL_SARC.csv").open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f, delimiter=";"):
            pid = (r.get("patient_id") or "").strip()
            topo = (r.get("icd_topo_annotation") or "").strip()
            label = (r.get("label") or "").strip()
            txt = (r.get("text_field") or "").strip()
            if not pid:
                continue
            if txt:
                by_pid[pid]["texts"].append((label, txt))
            if topo:
                by_pid[pid]["topo"][topo] += 1
    pids = [p for p, v in by_pid.items() if v["topo"] and v["texts"]]
    rng = random.Random(seed)
    rng.shuffle(pids)
    notes = []
    for pid in pids[:limit]:
        v = by_pid[pid]
        text = "\n\n".join(f"{lab}: {t}" for lab, t in v["texts"])[:8000]   # cap note length
        topo = v["topo"].most_common(1)[0][0]
        notes.append({"text": text, "date": "", "p_id": pid, "note_id": f"rol_{pid}",
                      "report_type": "ROL", "annotations": f"tumorsite-int: {topo}"})
    return notes


def write_session(out_id, name, notes, prompt_types):
    s = {"session_id": out_id, "name": name,
         "description": "INT-SARC topo/morpho eval from diagnosis_extra",
         "created_at": _now(), "updated_at": _now(),
         "notes": notes, "annotations": {}, "prompt_types": prompt_types,
         "center": "INT-SARC", "evaluation_mode": "evaluation", "report_type_mapping": {}}
    (SESS / f"{out_id}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {out_id}: {len(notes)} notes, prompts={prompt_types}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path-n", type=int, default=200)
    ap.add_argument("--rol-n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    pn = build_pathology(args.path_n, args.seed)
    write_session("sarc_path_topomorpho", "INT-SARC pathology topo+morpho",
                  pn, ["histological-tipo-int", "tumorsite-int"])
    rn = build_rol(args.rol_n, args.seed)
    write_session("sarc_rol_topo", "INT-SARC ROL topography (narrative)",
                  rn, ["tumorsite-int"])
    # gold code/topo distribution in the sampled sets (schema, for sanity)
    from collections import Counter as C
    pc = C(n["annotations"].split("(")[-1].rstrip(").") for n in pn)
    print(f"  pathology sampled morpho codes: {len(pc)} distinct, top {pc.most_common(5)}")


if __name__ == "__main__":
    main()
