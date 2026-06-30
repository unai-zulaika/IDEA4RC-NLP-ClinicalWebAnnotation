#!/usr/bin/env python3
"""P3: local LLM-judge calibration of the deterministic Q8 faithfulness checker.

For a sample of (reasoning, output) pairs, a LOCAL vLLM model extracts the value the
REASONING commits to and the value the OUTPUT commits to (constrained to the variable's
controlled vocabulary). The SCRIPT then applies the same label_pair rule, so the judge
and the deterministic checker differ ONLY in commit extraction - which is the thing under
test. We report Cohen's kappa(deterministic, judge), overall and on the headline cell.

PRIVACY: the judge is a LOCAL vLLM endpoint (no external API). reasoning/output go into
the judge prompt on-box only; this script NEVER prints or writes reasoning/output/judge
prose - only aggregate kappa/counts and a deny-by-default masked reason. Run the judge's
vLLM with request logging disabled. Use a NEUTRAL judge or cross-judge; never let a model
judge its own traces. See docs/design/Q8_faithfulness_measurement.md.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

from faithfulness_check import (
    ABSTAIN, HEADLINE_BASES, NONE, NOVAL, SESS, base_of, commit, label_pair,
)

OUT = Path("/home/zulaika/ClinicalAnnotationWeb/exp_out")

# Human-readable controlled vocabulary shown to the judge (schema, no PHI).
VOCAB_DISPLAY = {
    "gender": ["male", "female"],
    "biopsygrading": ["G1", "G2", "G3"],
    "surgerymargins": ["R0", "R1", "R2"],
    "necrosis": ["present", "absent"],
    "stage_at_diagnosis": ["localized", "loco_regional", "distant_lung", "distant_other", "distant_nodal"],
}
JUDGE_SYS = (
    "You are a strict annotation auditor. You are given a model's free-text REASONING and "
    "its final OUTPUT for one clinical variable. Decide, for each side independently, which "
    "controlled-vocabulary value that side COMMITS TO. 'Commits to' means concludes as the "
    "answer - not merely mentions or considers then rejects. If a side declines / says unknown "
    "/ not applicable / not available, its commit is ABSTAIN (not NONE). NONE is only for a "
    "side that never addresses the variable at all. "
    "Return ONLY JSON with exactly these two keys and no other text: "
    "{\"reasoning_commit\": <value|ABSTAIN|NONE>, \"output_commit\": <value|ABSTAIN|NONE>}. "
    "Do not include any clinical detail or free text - only the two controlled values."
)


def _judge_call(endpoint: str, model: str, base: str, reasoning: str, output: str) -> dict | None:
    vocab = VOCAB_DISPLAY.get(base, [])
    user = (f"Variable: {base}\nControlled vocabulary: {vocab} (or ABSTAIN / NONE)\n\n"
            f"REASONING:\n{reasoning}\n\nOUTPUT:\n{output}\n\nReturn the JSON now.")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": JUDGE_SYS}, {"role": "user", "content": user}],
        "temperature": 0, "top_p": 1, "max_tokens": 256, "seed": 7,
        # structured extraction needs no chain-of-thought; disabling Qwen3 thinking gives
        # a direct, reliably-parseable JSON answer (harmless for non-thinking judges).
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            content = json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception:
        return None
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _norm_commit(raw, base: str) -> str:
    """Map a judge string to our sentinel space; off-vocab -> NOVAL."""
    if raw is None:
        return NONE
    s = str(raw).strip()
    su = s.upper()
    if su in ("ABSTAIN", "UNKNOWN", "NOT APPLICABLE", "N/A"):
        return ABSTAIN
    if su in ("NONE", "NULL", ""):
        return NONE
    for v in VOCAB_DISPLAY.get(base, []):
        if s.lower() == v.lower():
            return v
    return NOVAL


def load_pairs(session_path: Path):
    """Yield (key, base, reasoning, output, det_rc, det_oc) for crisp pairs. Text stays local."""
    d = json.loads(session_path.read_text())
    for note_key, inner in (d.get("annotations") or {}).items():
        if not isinstance(inner, dict):
            continue
        for pt, e in inner.items():
            if not isinstance(e, dict):
                continue
            base = base_of(pt)
            if base not in HEADLINE_BASES:
                continue
            reasoning = e.get("reasoning") or ""
            output = e.get("annotation_text") or ""
            det_rc = commit(base, reasoning, "reasoning")
            det_oc = commit(base, output, "output")
            yield (f"{note_key}|{pt}", base, reasoning, output, det_rc, det_oc)


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """pairs of (a_label, b_label) over a 2-class {FAITHFUL,UNFAITHFUL} space."""
    n = len(pairs)
    if not n:
        return None
    agree = sum(1 for a, b in pairs if a == b)
    po = agree / n
    cats = ["FAITHFUL", "UNFAITHFUL"]
    pe = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n)
             for c in cats)
    return round((po - pe) / (1 - pe), 3) if pe != 1 else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sess", required=True)
    ap.add_argument("--model-label", required=True, help="e.g. 4B (the model whose traces are judged)")
    ap.add_argument("--judge-endpoint", required=True, help="e.g. http://localhost:8000/v1")
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    pairs = list(load_pairs(SESS / f"{args.sess}.json"))
    # stratify: oversample the headline failure cell, keep a spread of the rest
    by_label = defaultdict(list)
    for p in pairs:
        det_label = label_pair(p[4], p[5])[0]
        by_label[det_label].append(p)
    sample = []
    quota = {"UNFAITHFUL": args.n // 2, "FAITHFUL": args.n // 3, "NA": args.n // 6}
    for lab, q in quota.items():
        pool = by_label.get(lab, [])
        rng.shuffle(pool)
        sample.extend(pool[:q])
    rng.shuffle(sample)

    compared, off_vocab, judged_ok = [], 0, 0
    masked_hist = defaultdict(int)
    for key, base, reasoning, output, det_rc, det_oc in sample:
        det_label = label_pair(det_rc, det_oc)[0]
        jr = _judge_call(args.judge_endpoint, args.judge_model, base, reasoning, output)
        if jr is None:
            continue
        judged_ok += 1
        jrc = _norm_commit(jr.get("reasoning_commit"), base)
        off_vocab += int(jrc == NOVAL)
        # isolate the test to reasoning-commit extraction: pair the JUDGE's reasoning
        # commit with the DETERMINISTIC (reliable) output commit.
        j_label, _ = label_pair(jrc, det_oc)
        if det_label in ("FAITHFUL", "UNFAITHFUL") and j_label in ("FAITHFUL", "UNFAITHFUL"):
            compared.append((det_label, j_label))
            masked_hist[f"{base}|det={det_label[:1]}|judge={j_label[:1]}"] += 1

    result = {
        "session": args.sess, "model_judged": args.model_label,
        "judge_model": args.judge_model, "judge_endpoint": args.judge_endpoint,
        "n_sampled": len(sample), "n_judged_ok": judged_ok, "n_compared_scored": len(compared),
        "cohen_kappa_det_vs_judge": cohen_kappa(compared),
        "agreement_matrix": dict(masked_hist),
        "judge_off_vocab_rate": round(off_vocab / judged_ok, 3) if judged_ok else None,
        "gate_kappa_ge_0.6": (cohen_kappa(compared) or 0) >= 0.6,
    }
    OUT.mkdir(exist_ok=True)
    out = OUT / f"q8_judge_{args.sess}_by_{args.judge_model.split('/')[-1]}.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"[q8-judge] {args.sess} judged by {args.judge_model.split('/')[-1]}: "
          f"kappa={result['cohen_kappa_det_vs_judge']} "
          f"(n={result['n_compared_scored']}, judged_ok={judged_ok}, "
          f"off_vocab={result['judge_off_vocab_rate']})")
    print(f"[q8-judge] gate kappa>=0.6: {'PASS' if result['gate_kappa_ge_0.6'] else 'FAIL'}  ->  {out}")


if __name__ == "__main__":
    main()
