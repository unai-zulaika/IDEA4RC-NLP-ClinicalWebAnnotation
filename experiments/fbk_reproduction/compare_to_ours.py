"""Apples-to-apples comparison: our system (MedGemma + our prompts) vs FBK
reproduction (Llama-3.1-8B + FBK prompts) scored on the SAME metric.

For each of the 4 target variables we:
  1. Pull our predictions from the MSCI session JSON, keeping only cases with a
     real gold annotation (i.e. expected_annotation != '[NO EXPECTED ANNOTATION]').
  2. Score with EM, VAL-EM, PM @ {0.6, 0.77, 0.95}.
  3. Print side-by-side with the FBK reproduction numbers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from rag_retriever import embed  # noqa: E402

# Our session uses these prompt type names; FBK uses these short names.
PROMPT_MAP = {
    "biopsy_mitotic_count": "biopsymitoticcount-msci",
    "necrosis_in_biopsy": "necrosis_in_biopsy-msci",
    "necrosis_in_surgical": "necrosis_in_surgical-msci",
    "patient_weight_height": "patient-weightheight-msci",
}


def value_after_colon(s: str) -> str:
    s = s.strip().rstrip(".")
    if ":" in s:
        return s.rsplit(":", 1)[-1].strip().lower()
    return s.strip().lower()


def collect_pairs_from_session(
    session_path: Path,
) -> dict[str, list[tuple[str, str, str]]]:
    """Return {variable: [(note_id, gold, predicted), ...]} for gold-present cases."""
    data = json.loads(session_path.read_text())
    ann = data["annotations"]
    out: dict[str, list[tuple[str, str, str]]] = {v: [] for v in PROMPT_MAP}
    for nid, note_ann in ann.items():
        for fbk_var, our_key in PROMPT_MAP.items():
            entry = note_ann.get(our_key)
            if not entry:
                continue
            er = entry.get("evaluation_result")
            if not er:
                continue
            gold = er.get("expected_annotation", "") or ""
            pred = er.get("predicted_annotation", "") or ""
            # Skip cases where gold is empty (FBK never evaluates these).
            if not gold.strip() or gold.strip() == "[NO EXPECTED ANNOTATION]":
                continue
            out[fbk_var].append((nid, gold.strip(), pred.strip()))
    return out


def score(pairs: list[tuple[str, str, str]], thresholds: list[float]) -> dict:
    if not pairs:
        return {"n": 0}
    golds = [g for _, g, _ in pairs]
    preds = [p for _, _, p in pairs]
    g_emb = embed(golds)
    p_emb = embed(preds)
    sims = (g_emb * p_emb).sum(axis=1)

    n = len(pairs)
    em = sum(1 for g, p in zip(golds, preds) if g == p)
    val_em = sum(1 for g, p in zip(golds, preds) if value_after_colon(g) == value_after_colon(p))

    row = {
        "n": n,
        "em": em / n,
        "val_em": val_em / n,
    }
    for t in thresholds:
        acc = sum(1 for g, p, s in zip(golds, preds, sims) if g == p or s >= t) / n
        row[f"pm{t}"] = acc
    return row


def load_fbk_rescore(rescore_path: Path) -> dict:
    """Return {variable: row_dict_with_mean_values} from rescore.json."""
    data = json.loads(rescore_path.read_text())
    out: dict[str, dict] = {}
    for var, agg in data["aggregate"].items():
        out[var] = {
            "n": int(round(np.mean([data["per_seed"][i]["variables"][var]["n"] for i in range(len(data["per_seed"]))]))),
            "em": agg["em_rate_mean"],
            "val_em": agg["value_em_rate_mean"],
            "pm0.6": agg["acc@PM0.6_mean"],
            "pm0.77": agg["acc@PM0.77_mean"],
            "pm0.95": agg["acc@PM0.95_mean"],
        }
    return out


def print_table(title: str, rows: dict[str, dict]) -> None:
    print(f"\n=== {title} ===")
    cols = ["N", "EM", "VAL-EM", "PM>=0.6", "PM>=0.77", "PM>=0.95"]
    header = ["variable"] + cols
    print("  " + "  ".join(f"{h:>10s}" for h in header))
    for var, r in rows.items():
        if not r or r.get("n", 0) == 0:
            print(f"  {var[:18]:>10s}  {'(no data)':>10s}")
            continue
        line = [
            var[:18],
            f"{r['n']:>10d}",
            f"{r['em']*100:5.1f}",
            f"{r['val_em']*100:5.1f}",
            f"{r['pm0.6']*100:5.1f}",
            f"{r['pm0.77']*100:5.1f}",
            f"{r['pm0.95']*100:5.1f}",
        ]
        print("  " + "  ".join(f"{c:>10s}" for c in line))


def print_side_by_side(ours: dict[str, dict], fbk: dict[str, dict]) -> None:
    print("\n=== Side-by-side (mean across whichever runs available) ===")
    print(f"  {'variable':<22s} {'metric':<10s}  {'OURS':>8s}  {'FBK-repro':>10s}  {'delta':>8s}")
    metrics = [("EM", "em"), ("VAL-EM", "val_em"), ("PM>=0.6", "pm0.6"), ("PM>=0.77", "pm0.77"), ("PM>=0.95", "pm0.95")]
    for var in PROMPT_MAP:
        o = ours.get(var, {})
        f = fbk.get(var, {})
        for label, key in metrics:
            ov = o.get(key)
            fv = f.get(key)
            if ov is None or fv is None or o.get("n", 0) == 0:
                continue
            delta = ov - fv
            line = (
                f"  {var:<22s} {label:<10s}  "
                f"{ov*100:7.1f}%  {fv*100:9.1f}%  {delta*100:+7.1f}"
            )
            print(line)
        if o.get("n"):
            print(f"  {'':<22s} {'(N)':<10s}  {o['n']:>7d}   {f.get('n','-'):>9}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--session",
        default="backend/sessions/6c677cda-a335-4566-857c-7f5344b732cd.json",
        help="Our MSCI session JSON (default = unfiltered).",
    )
    ap.add_argument(
        "--fbk-rescore",
        default="experiments/fbk_reproduction/rescore.json",
        help="The rescore.json produced by rescore.py.",
    )
    ap.add_argument(
        "--out",
        default="experiments/fbk_reproduction/comparison.json",
    )
    ap.add_argument(
        "--thresholds",
        nargs="+",
        type=float,
        default=[0.6, 0.77, 0.95],
    )
    args = ap.parse_args()

    pairs_by_var = collect_pairs_from_session(Path(args.session))
    ours: dict[str, dict] = {}
    for var, pairs in pairs_by_var.items():
        ours[var] = score(pairs, args.thresholds)

    fbk = load_fbk_rescore(Path(args.fbk_rescore))

    print(f"Session: {args.session}")
    print(f"FBK rescore: {args.fbk_rescore}")
    print_table("OURS (MedGemma + JSON-reasoning prompt, full-note eval)", ours)
    print_table("FBK REPRODUCTION (Llama-3.1-8B + strict prompt, per-annotation eval)", fbk)
    print_side_by_side(ours, fbk)

    Path(args.out).write_text(json.dumps({"ours": ours, "fbk": fbk}, indent=2))
    print(f"\nWrote: {args.out}")


if __name__ == "__main__":
    main()
