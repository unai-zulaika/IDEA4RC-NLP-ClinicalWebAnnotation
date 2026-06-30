#!/usr/bin/env python3
"""
Experiment registry for the final-review NLP evaluation.

Every run is fully described by an ExpConfig. The run_id is a deterministic
slug of the config so results land in a predictable folder and the harness is
idempotent.

Design choices
--------------
* The systematic study uses the RAW stack (direct vLLM, evaluate_llm_int_prompts.py)
  because it isolates model + prompt + few-shots without the production stack's
  confounds (history splitting, structured output, ICD lookup) and is ~20x faster.
* The REASONING dimension (Q7) and reasoning-quality analysis (Q8) use the
  PRODUCTION stack, because the reasoning field only exists there (fast_mode).
* Switching MODELS requires restarting the vLLM server; the runner validates the
  live model against the config and refuses to run a mismatch. So you serve one
  model, run every config for it, then switch.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict, field
from pathlib import Path

NLP_DIR = Path(__file__).resolve().parent
REPO_ROOT = NLP_DIR.parents[2]
RESULTS_ROOT = REPO_ROOT / "experiments" / "results"
RESULTS_ROOT.mkdir(parents=True, exist_ok=True)


# --- HF model names, used to validate against the live vLLM /v1/models ------
MODEL_SERVED = {
    "4b":     "unaizulaika/medgemma-1.5-4b-it-W4A16-G128",
    "27b":    "unaizulaika/medgemma-27b-text-it-W4A16-G128",
    "qwen8b": "Qwen/Qwen3-8B",   # adjust if you use a quantized community build
}


# --- Per-center data locations ----------------------------------------------
# Only INT-SARC is wired up today; the others are placeholders to fill in once
# their gold sets arrive (same file format as INT-SARC).
@dataclass(frozen=True)
class CenterData:
    notes_csv: Path
    gold_json: Path
    prompts_json: Path
    prompts_center_key: str            # top-level key inside prompts_json (e.g. "INT")
    fewshots_csv: Path
    report_type_mapping: Path
    faiss_root: Path                   # dir containing per-mode FAISS subdirs


CENTERS: dict[str, CenterData] = {
    "INT-SARC": CenterData(
        notes_csv=NLP_DIR / "first_patient_notes.csv",
        gold_json=NLP_DIR / "annotated_patient_notes_with_spans_full_verified.json",
        prompts_json=NLP_DIR / "FBK_scripts" / "prompts.json",
        prompts_center_key="INT",
        # Original export with the faithful CLN placeholders preserved — the
        # source of truth for the complete/incomplete/note-only pools.
        fewshots_csv=REPO_ROOT / "extra_data" / "fewshot_examples_INT_with_missing.csv",
        report_type_mapping=NLP_DIR / "report_type_prompt_mapping_int.json",
        faiss_root=NLP_DIR / "experiments" / "faiss" / "INT-SARC",
    ),
    "MSCI": CenterData(
        # Derived from the 60-note evaluation session via convert_msci_session.py.
        notes_csv=NLP_DIR / "msci_first_patient_notes.csv",
        gold_json=NLP_DIR / "annotated_msci_notes_verified.json",
        prompts_json=NLP_DIR / "FBK_scripts" / "prompts.json",
        prompts_center_key="MSCI",
        # Balanced ~60-per-prompt pool, columns prompt_type/note_text/annotation.
        fewshots_csv=REPO_ROOT / "out" / "MSCI" / "fewshots_msci_faiss.csv",
        report_type_mapping=NLP_DIR / "report_type_prompt_mapping_msci.json",
        faiss_root=NLP_DIR / "experiments" / "faiss" / "MSCI",
    ),
    # "INT-HNC": CenterData(...),   # fill in when gold arrives
    # "VGR":     CenterData(...),
}


FEWSHOT_MODES = ("all", "complete", "incomplete", "note-only")


@dataclass(frozen=True)
class ExpConfig:
    center: str = "INT-SARC"
    model: str = "27b"               # key into MODEL_SERVED
    stack: str = "raw"               # raw | production
    fewshot_k: int = 5               # 0,1,3,5,10
    fewshot_mode: str = "all"        # all | complete | incomplete | note-only
    filter: bool = True              # report-type filter on/off
    reasoning: bool = True           # production fast_mode = not reasoning; ignored for raw
    prompt_version: str = "pre"      # pre | post (clinician workshop)

    def run_id(self) -> str:
        return (
            f"{self.center}__{self.model}__{self.stack}"
            f"__k{self.fewshot_k}__{self.fewshot_mode}"
            f"__filter{int(self.filter)}__reason{int(self.reasoning)}"
            f"__{self.prompt_version}"
        )

    @classmethod
    def from_run_id(cls, run_id: str) -> "ExpConfig":
        """Parse a deterministic run_id slug back into an ExpConfig."""
        parts = run_id.split("__")
        if len(parts) != 8:
            raise ValueError(f"malformed run_id: {run_id}")
        center, model, stack, kpart, mode, fpart, rpart, ver = parts
        if not (kpart.startswith("k") and fpart.startswith("filter")
                and rpart.startswith("reason")):
            raise ValueError(f"malformed run_id parts: {run_id}")
        return cls(
            center=center, model=model, stack=stack,
            fewshot_k=int(kpart[1:]), fewshot_mode=mode,
            filter=bool(int(fpart[len("filter"):])),
            reasoning=bool(int(rpart[len("reason"):])),
            prompt_version=ver,
        )

    def result_dir(self) -> Path:
        d = RESULTS_ROOT / self.run_id()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_dict(self) -> dict:
        return asdict(self)


# --- The matrix: one-factor-at-a-time around an anchor ----------------------

ANCHOR = ExpConfig(
    center="INT-SARC", model="27b", stack="raw",
    fewshot_k=5, fewshot_mode="all", filter=True, reasoning=True, prompt_version="pre",
)


def _vary(anchor: ExpConfig, **overrides) -> ExpConfig:
    base = asdict(anchor)
    base.update(overrides)
    return ExpConfig(**base)


def build_matrix() -> dict[str, list[ExpConfig]]:
    """Return {dimension_name: [configs]} for the no-blocker dimensions on
    INT-SARC. Each list includes the anchor (so dimensions share a baseline).
    """
    matrix: dict[str, list[ExpConfig]] = {}

    # Q4 — few-shot K sweep (raw)
    matrix["fewshot_k"] = [_vary(ANCHOR, fewshot_k=k) for k in (0, 1, 3, 5, 10)]

    # Q5 — report-type filter on/off (raw)
    matrix["filter"] = [_vary(ANCHOR, filter=f) for f in (True, False)]

    # Q3 + Q9 — few-shot mode (raw)
    matrix["fewshot_mode"] = [_vary(ANCHOR, fewshot_mode=m) for m in FEWSHOT_MODES]

    # Q2 — model size (raw). Each requires its own served model.
    matrix["model"] = [_vary(ANCHOR, model=m) for m in ("4b", "27b", "qwen8b")]

    # Q7 — reasoning on/off (PRODUCTION stack), both small and big model
    matrix["reasoning"] = [
        _vary(ANCHOR, stack="production", model=mdl, reasoning=r)
        for mdl in ("4b", "27b")
        for r in (True, False)
    ]

    return matrix


def all_configs() -> list[ExpConfig]:
    seen: dict[str, ExpConfig] = {}
    for configs in build_matrix().values():
        for c in configs:
            seen[c.run_id()] = c
    return list(seen.values())


def configs_for_model(model: str) -> list[ExpConfig]:
    """All distinct configs that need `model` served, so you can run them in one
    sitting before switching the vLLM server."""
    return [c for c in all_configs() if c.model == model]


# Raw dimensions worth sweeping on EVERY model (K, filter, few-shot mode).
# build_matrix() anchors these on 27b; this re-keys them to whichever model you
# have served so you can run the whole raw sweep per model.
RAW_SWEEP_DIMENSIONS = ("fewshot_k", "filter", "fewshot_mode")


def raw_sweep_configs(model: str) -> list[ExpConfig]:
    seen: dict[str, ExpConfig] = {}
    matrix = build_matrix()
    for dim in RAW_SWEEP_DIMENSIONS:
        for c in matrix[dim]:
            c2 = _vary(c, model=model, stack="raw")
            seen[c2.run_id()] = c2
    return list(seen.values())


def production_sweep_configs(model: str) -> list[ExpConfig]:
    """The hospital-representative sweep on the PRODUCTION stack, for dimensions
    that need NO backend restart: few-shot K, report-type filter, reasoning.
    (Model and few-shot-mode need restarts and are driven manually — see
    EXPERIMENTS.md.)"""
    seen: dict[str, ExpConfig] = {}
    # K sweep (reasoning on, filter on, mode all)
    for k in (0, 1, 3, 5, 10):
        c = _vary(ANCHOR, stack="production", model=model, fewshot_k=k)
        seen[c.run_id()] = c
    # filter on/off
    for f in (True, False):
        c = _vary(ANCHOR, stack="production", model=model, filter=f)
        seen[c.run_id()] = c
    # reasoning on/off
    for r in (True, False):
        c = _vary(ANCHOR, stack="production", model=model, reasoning=r)
        seen[c.run_id()] = c
    return list(seen.values())


if __name__ == "__main__":
    # Print the plan grouped by the model that must be served.
    from collections import defaultdict
    by_model: dict[str, list[ExpConfig]] = defaultdict(list)
    for c in all_configs():
        by_model[c.model].append(c)
    total = 0
    for model, configs in sorted(by_model.items()):
        print(f"\n### serve model: {model}  ({MODEL_SERVED.get(model, '?')})  — {len(configs)} runs")
        for c in sorted(configs, key=lambda x: x.run_id()):
            print(f"  {c.run_id()}")
            total += 1
    print(f"\nTotal distinct runs: {total}")
