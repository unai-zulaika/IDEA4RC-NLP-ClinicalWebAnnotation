#!/usr/bin/env python3
"""Score INT-SARC topo/morpho extraction at code granularity. Reads a scored session,
emits ONLY aggregate metrics (no note/gold text). See docs/analysis/INT-SARC_topo_morpho_analysis.md.

Morphology (histological-tipo-int): ICD-O-3 code from the model output vs gold -
  exact (8858/3), family (8858, ignore behavior), behavior (/3); + production-resolved
  (annotation_text) vs LLM-raw (raw_response) code, and description match.
Topography (tumorsite-int): gold site category vs model site (normalized + SITE_EQUIV synonyms).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from auto_judge import SITE_EQUIV, _canonical_histology, _norm

SESS = Path("/home/zulaika/ClinicalAnnotationWeb/backend/sessions")
OUT = Path("/home/zulaika/ClinicalAnnotationWeb/exp_out")
CODE_RE = re.compile(r"\b(\d{4})\s*/\s*(\d)\b")

# gold site category -> synonyms the model may emit (extends auto_judge SITE_EQUIV)
SITE_SYNS = {canon: set(forms) for canon, forms in SITE_EQUIV.items()}
SITE_SYNS.update({
    "upper leg": {"upper leg", "thigh", "coscia"},
    "retroperitoneum": {"retroperitoneum", "retroperitoneal"},
    "abdominal wall": {"abdominal wall", "parete addominale"},
    "leg": {"leg", "lower leg", "gamba"},
})


def _last_code(text):
    ms = CODE_RE.findall(text or "")
    return (ms[-1][0], ms[-1][1]) if ms else None


def _site_hit(model_text, gold_site):
    m = _norm(model_text)
    g = _norm(gold_site)
    if g and g in m:
        return True
    for syn in SITE_SYNS.get(g, {g}):
        if _norm(syn) and re.search(rf"\b{re.escape(_norm(syn))}\b", m):
            return True
    return False


def score(session_id):
    d = json.loads((SESS / f"{session_id}.json").read_text())
    morpho = defaultdict(int)
    topo = defaultdict(int)
    per_code = defaultdict(lambda: [0, 0])      # gold_code -> [exact_hits, n]
    confusion = Counter()
    for note in d.get("annotations", {}).values():
        # --- morphology ---
        e = note.get("histological-tipo-int")
        if isinstance(e, dict):
            gold = (e.get("evaluation_result") or {}).get("expected_annotation", "")
            gc = _last_code(gold)
            if gc:
                morpho["n"] += 1
                prod = _last_code(e.get("annotation_text", ""))
                raw = _last_code(e.get("raw_response", ""))
                if prod:
                    if prod == gc:
                        morpho["exact"] += 1; per_code[f"{gc[0]}/{gc[1]}"][0] += 1
                    else:
                        confusion[f"{gc[0]}/{gc[1]} -> {prod[0]}/{prod[1]}"] += 1
                    if prod[0] == gc[0]:
                        morpho["family"] += 1
                    if prod[1] == gc[1]:
                        morpho["behavior"] += 1
                else:
                    morpho["no_code_out"] += 1          # model gave no resolvable code
                if raw == gc:
                    morpho["raw_exact"] += 1
                per_code[f"{gc[0]}/{gc[1]}"][1] += 1
                # description match
                gd = _canonical_histology(gold)
                md = _canonical_histology(e.get("annotation_text", ""))
                if gd and md and gd == md:
                    morpho["descr"] += 1
        # --- topography ---
        t = note.get("tumorsite-int")
        if isinstance(t, dict):
            gold = (t.get("evaluation_result") or {}).get("expected_annotation", "")
            if gold.strip():
                topo["n"] += 1
                if _site_hit(t.get("annotation_text", ""), gold):
                    topo["hit"] += 1

    def pct(a, b):
        return round(morpho[a] / morpho[b] * 100, 1) if morpho.get(b) else None
    nm = morpho.get("n", 0)
    res = {
        "session": session_id,
        "morphology": {
            "n": nm,
            "exact_code_pct": round(morpho["exact"] / nm * 100, 1) if nm else None,
            "family_pct": round(morpho["family"] / nm * 100, 1) if nm else None,
            "behavior_pct": round(morpho["behavior"] / nm * 100, 1) if nm else None,
            "description_pct": round(morpho["descr"] / nm * 100, 1) if nm else None,
            "raw_llm_exact_pct": round(morpho["raw_exact"] / nm * 100, 1) if nm else None,
            "no_code_output": morpho.get("no_code_out", 0),
        },
        "topography": {
            "n": topo.get("n", 0),
            "site_hit_pct": round(topo["hit"] / topo["n"] * 100, 1) if topo.get("n") else None,
        },
        "per_code_reliability": {k: {"exact": v[0], "n": v[1],
                                     "pct": round(v[0] / v[1] * 100)} for k, v in
                                 sorted(per_code.items(), key=lambda x: -x[1][1])[:12]},
        "top_confusions": dict(confusion.most_common(10)),
    }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", nargs="+", required=True)
    ap.add_argument("--name", default="sarc_topomorpho")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    allres = {s: score(s) for s in args.sessions}
    (OUT / f"score_{args.name}.json").write_text(json.dumps(allres, indent=2))
    for s, r in allres.items():
        m, t = r["morphology"], r["topography"]
        print(f"[{s}] morpho n={m['n']} exact={m['exact_code_pct']}% family={m['family_pct']}% "
              f"behavior={m['behavior_pct']}% descr={m['description_pct']}% raw_llm={m['raw_llm_exact_pct']}%  "
              f"| topo n={t['n']} site={t['site_hit_pct']}%")
    print(f"wrote {OUT / f'score_{args.name}.json'}")


if __name__ == "__main__":
    main()
