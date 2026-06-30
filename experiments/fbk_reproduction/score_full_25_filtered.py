"""Score predictions twice — unfiltered (all 60 notes) and filtered (using the
session's report_type_mapping, matching report_msci_filtered.md). Output a
side-by-side markdown table comparing FBK-setup-with-our-methodology against
our system's filtered numbers (parsed from report_msci_filtered.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from full_25_templates import VARIABLES  # noqa: E402
from score_full_25 import classify  # noqa: E402


def load_session_filter(session_path: Path) -> dict[str, set[str]]:
    """Return prompt_type -> set of report_types where this prompt should run."""
    s = json.loads(session_path.read_text())
    mapping = s.get("report_type_mapping") or {}
    out: dict[str, set[str]] = defaultdict(set)
    for rt, prompts in mapping.items():
        for p in prompts:
            out[p].add(rt)
    return out


def score(predictions_path: Path, prompt_filter: dict[str, set[str]] | None) -> dict:
    rows = [json.loads(l) for l in predictions_path.open()]
    by_var: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_var[r["variable"]].append(r)

    out: dict[str, dict] = {}
    for var_name, spec in VARIABLES.items():
        var_rows = by_var.get(var_name, [])
        if prompt_filter is not None:
            allowed = prompt_filter.get(spec.session_key, set())
            var_rows = [r for r in var_rows if r["report_type"] in allowed]
        counts = {"match": 0, "mismatch": 0, "false_positive": 0,
                  "false_negative": 0, "both_empty": 0}
        for r in var_rows:
            cat = classify(r.get("gold", ""), r.get("predicted", ""),
                           spec.unknown_fallback)
            counts[cat] += 1
        n = sum(counts.values())
        out[var_name] = {
            "n": n,
            **counts,
            "correct_rate": (counts["match"] + counts["both_empty"]) / n if n else 0,
            "extract_rate": counts["match"] / n if n else 0,
            "abstain_rate": counts["both_empty"] / n if n else 0,
            "fp_rate": counts["false_positive"] / n if n else 0,
        }
    return out


def parse_ours_from_md(md_path: Path) -> dict[str, dict]:
    """Pull the table rows from report_msci_filtered.md."""
    text = md_path.read_text()
    rows: dict[str, dict] = {}
    pat = re.compile(
        r"\| `([\w_-]+)` \| \*\*(\d+)%\*\* \| (\d+)% \| (\d+)% \| (\d+)% \| (\d+) \|",
    )
    for m in pat.finditer(text):
        name, correct, extract, abstain, fp, n = m.groups()
        rows[name] = {
            "n": int(n),
            "correct_rate": int(correct) / 100,
            "extract_rate": int(extract) / 100,
            "abstain_rate": int(abstain) / 100,
            "fp_rate": int(fp) / 100,
        }
    return rows


def render(
    ours: dict[str, dict],
    fbk_unfiltered: dict[str, dict],
    fbk_filtered: dict[str, dict],
) -> str:
    lines = ["# FBK setup × our methodology — full 25-variable comparison\n"]
    lines.append(
        "Predictions come from Llama-3.1-8B-Instruct + FBK-style strict prompt "
        "+ FAISS-RAG few-shot retrieval (k=5) over the FBK CSV pool. Scored "
        "with our methodology (match / mismatch / FP / FN / both_empty) on the "
        "60 notes from session `3effb5be`.\n"
    )
    lines.append(
        "`Correct%` = (match + both_empty) / N. "
        "`Extract%` = match / N (strict). "
        "`FP%` = false_positive / N. "
        "Lower FP% = better abstention.\n"
    )
    lines.append("Two columns of FBK-setup numbers:")
    lines.append("- **Unfiltered** = all 60 notes per variable (mirrors `report_msci_unfiltered.md`).")
    lines.append("- **Filtered** = only notes whose `report_type` is mapped to that variable "
                 "(mirrors `report_msci_filtered.md`).\n")
    lines.append(
        "| Variable | OURS Correct% (N) | FBK setup Filtered Correct% (N) | FBK setup Unfiltered Correct% (N) | Δ (FBK-filt − OURS) |"
    )
    lines.append("|---|---:|---:|---:|---:|")

    # Map our variable names to the report's display names (strip -msci, sometimes shortened)
    short_to_var = {}
    for var, spec in VARIABLES.items():
        short = spec.session_key.replace("-msci", "")
        short_to_var[short] = var

    rows_sorted = sorted(
        VARIABLES.keys(),
        key=lambda v: -(fbk_filtered.get(v, {}).get("correct_rate", 0)),
    )
    for var in rows_sorted:
        spec = VARIABLES[var]
        short = spec.session_key.replace("-msci", "")
        # Try multiple key variants since our report uses inconsistent names
        candidates = [short, short.replace("-", "_"), short.replace("_", "-"),
                      var, var.replace("_", "-"), var.replace("-", "_")]
        o = next((ours[c] for c in candidates if c in ours), None)
        fu = fbk_unfiltered.get(var, {})
        ff = fbk_filtered.get(var, {})
        o_str = f"{o['correct_rate']*100:.0f}% ({o['n']})" if o else "—"
        ff_str = f"{ff.get('correct_rate',0)*100:.0f}% ({ff.get('n',0)})" if ff.get('n') else "0% (0)"
        fu_str = f"{fu.get('correct_rate',0)*100:.0f}% ({fu.get('n',0)})"
        if o and ff.get('n'):
            delta = ff['correct_rate'] - o['correct_rate']
            delta_str = f"{delta*100:+.0f}"
        else:
            delta_str = "—"
        lines.append(f"| `{short}` | {o_str} | {ff_str} | {fu_str} | {delta_str} |")

    lines.append("")
    lines.append("## Breakdown columns (FBK setup, filtered) — what's driving each number")
    lines.append("")
    lines.append("| Variable | N | match | mismatch | FP | FN | both_empty | Correct% | Extract% | FP% |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for var in rows_sorted:
        spec = VARIABLES[var]
        short = spec.session_key.replace("-msci", "")
        r = fbk_filtered.get(var, {})
        if not r.get("n"):
            lines.append(f"| `{short}` | 0 | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| `{short}` | {r['n']} | {r['match']} | {r['mismatch']} | "
            f"{r['false_positive']} | {r['false_negative']} | {r['both_empty']} | "
            f"{r['correct_rate']*100:.0f}% | {r['extract_rate']*100:.0f}% | "
            f"{r['fp_rate']*100:.0f}% |"
        )

    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--predictions",
        default="experiments/fbk_reproduction/full25/predictions.jsonl",
    )
    ap.add_argument(
        "--session",
        default="backend/sessions/3effb5be-3c84-492f-ab5d-fecedd5c3173.json",
    )
    ap.add_argument(
        "--ours-md",
        default="report_msci_filtered.md",
    )
    ap.add_argument(
        "--out",
        default="experiments/fbk_reproduction/full25/comparison.md",
    )
    args = ap.parse_args()

    pred_path = Path(args.predictions)
    pfilter = load_session_filter(Path(args.session))
    unfilt = score(pred_path, None)
    filt = score(pred_path, pfilter)
    ours = parse_ours_from_md(Path(args.ours_md))

    Path(args.out).write_text(render(ours, unfilt, filt))
    Path(args.out).with_suffix(".json").write_text(
        json.dumps({"ours": ours, "fbk_unfiltered": unfilt, "fbk_filtered": filt}, indent=2)
    )
    print(f"Wrote: {args.out}")
    print()
    # Print the table to stdout
    print((args.out and Path(args.out).read_text()) or "")


if __name__ == "__main__":
    main()
