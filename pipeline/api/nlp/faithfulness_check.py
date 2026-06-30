#!/usr/bin/env python3
"""Q8 reasoning-faithfulness checker (deterministic, privacy-clean).

Faithfulness = does the value the model COMMITS TO in its reasoning agree with the
value it commits to in its output. We never compare to gold (this is not accuracy).

PRIVACY: reasoning/output strings are PHI. They are read from backend/sessions/*.json,
held only as local variables passed to the regex/set extractors below, and converted
to a category label. NOTHING here prints, returns, or writes reasoning/output text -
only aggregate counts and labels (FAITHFUL/UNFAITHFUL/NA + a vocab-token "kind").
See docs/design/Q8_faithfulness_measurement.md.

Authored from schema only (auto_judge vocab tables + prompts.json templates); no
session value was read to write this.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from auto_judge import (  # validated extractors / vocab (schema, non-PHI)
    FNCLCC_GRADE_RE,
    HISTOLOGY_EQUIV,
    SITE_EQUIV,
    STAGE_SYNS,
    _norm,
    _strip_label_prefix,
)
from exp_judge import _is_abstention

ROOT = Path("/home/zulaika/ClinicalAnnotationWeb")
SESS = ROOT / "backend" / "sessions"
OUT = ROOT / "exp_out"

# --- sentinels (never a clinical value) -------------------------------------
ABSTAIN = "__ABSTAIN__"   # side explicitly declined / unknown / not-applicable
NOVAL = "__NOVAL__"       # output carries a value but it is outside the vocabulary
NONE = "__NONE__"         # reasoning asserts no in-vocabulary value (faithfulness undefined)

# --- negation, multilingual (EN / IT / PL) ----------------------------------
NEGATORS = [
    "no", "not", "non", "without", "senza", "denies", "ruled out", "rule out",
    "negative", "negativo", "assente", "escluso", "esclusa", "esclude",
    "nie", "brak", "bez", "nieobecn",
]
_NEG_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in NEGATORS) + r")\b")
# negation does not cross a clause boundary, so only inspect the clause adjacent
# to the value mention (fixes 'not R0; an R1' wrongly negating R1).
_CLAUSE_RE = re.compile(r"[.;:,]|\bbut\b")


def _negated_before(t_norm: str, pos: int, window: int = 40) -> bool:
    seg = _CLAUSE_RE.split(t_norm[max(0, pos - window):pos])[-1]
    return bool(_NEG_RE.search(seg))


# --- per-variable controlled vocabulary (token -> surface synonyms) ----------
# Italian forms come from auto_judge; Polish added for MSCI (kobieta=woman,
# mezczyzna=man, pacjentka=female patient). All schema, no PHI.
GENDER_VOCAB = {
    "male":   ["male", "man", "maschio", "uomo", "il paziente", "il pz", "mezczyzna", "mężczyzna"],
    "female": ["female", "woman", "femmina", "donna", "la paziente", "la pz", "kobieta", "pacjentka"],
}
NECROSIS_ABSENT = ["absent", "none", "no necrosis", "assente", "nieobecna", "brak martwicy"]
NECROSIS_PRESENT = ["present", "coagulative", "obecna", "martwica"]  # NB: not bare "necrosis"
STAGE_VOCAB = {tok: list(forms) for tok, forms in STAGE_SYNS.items() if tok != "unknown"}
HIST_VOCAB = {tok: list(forms) for tok, forms in HISTOLOGY_EQUIV.items()}
SITE_VOCAB = {tok: list(forms) for tok, forms in SITE_EQUIV.items()}

# Cues by which a reasoning chain CONCLUDES abstention. The fix for the
# deliberation-vs-commitment confound: if one of these follows the last value
# mention, the chain considered the value but concluded it cannot be given, so
# the reasoning's commitment is ABSTAIN, not the value. (EN / IT / PL)
CONCLUSION_ABSTAIN = [
    "unknown", "not stated", "not explicitly stated", "not explicitly", "not applicable",
    "not specified", "not mentioned", "not reported", "not available", "no information",
    "cannot be determined", "cannot determine", "not provided", "not given",
    "other classification", "another classification",  # graded by a non-FNCLCC system
    "non specificato", "sconosciuto", "non noto", "nieznany", "nie podano", "brak informacji",
]
_CONCL_RE = re.compile("|".join(re.escape(c) for c in CONCLUSION_ABSTAIN))


def _concludes_abstain(t_norm: str, after_pos: int) -> bool:
    """True if the chain abstains AFTER committing a value at after_pos."""
    return bool(_CONCL_RE.search(t_norm[after_pos:]))


def _reason_abstains(text: str, t_norm: str) -> bool:
    """No value found in reasoning: abstain iff an abstention cue is present."""
    return bool(_CONCL_RE.search(t_norm) or _is_abstention(text))


# --- per-variable value finders: return (token, position_in_t_norm) ----------
def _find_in_vocab(t: str, vocab: dict[str, list[str]], side: str):
    asserted: dict[str, int] = {}
    for token, syns in vocab.items():
        for s in syns:
            for m in re.finditer(rf"\b{re.escape(_norm(s))}\b", t):
                if side == "reasoning" and _negated_before(t, m.start()):
                    continue
                asserted[token] = max(asserted.get(token, -1), m.start())
    if not asserted:
        return (None, None)
    tok = max(asserted, key=asserted.get)
    return (tok, asserted[tok])


def _find_grade(raw: str, t: str, side: str):
    if side == "output":
        m = FNCLCC_GRADE_RE.search(_strip_label_prefix(raw))
        return (f"G{m.group(1)}", m.start()) if m else (None, None)
    best = None
    for pat in (r"grad[eio]\b[^0-9]{0,10}([123])\b", r"\bg([123])\b", r"fnclcc\b[^0-9]{0,14}([123])\b"):
        for m in re.finditer(pat, t):
            if _negated_before(t, m.start()):
                continue
            if best is None or m.start() > best[1]:
                best = (f"G{m.group(1)}", m.start())
    return best if best else (None, None)


def _find_margins(raw: str, t: str, side: str):
    best = None
    for m in re.finditer(r"\br([012])\b", t):
        if side == "reasoning" and _negated_before(t, m.start()):
            continue
        if best is None or m.start() > best[1]:
            best = (f"R{m.group(1)}", m.start())
    if best:
        return best
    if side == "output":
        m = re.search(r"\b([012])\b", _strip_label_prefix(raw))
        return (f"R{m.group(1)}", m.start()) if m else (None, None)
    return (None, None)


def _find_necrosis(t: str, side: str):
    cands = []
    for s in NECROSIS_ABSENT:
        for m in re.finditer(rf"\b{re.escape(_norm(s))}\b", t):
            if side == "reasoning" and _negated_before(t, m.start()):
                continue
            cands.append(("absent", m.start()))
    for m in re.finditer(r"\d+\s*%", t):
        cands.append(("present", m.start()))
    for s in NECROSIS_PRESENT:
        for m in re.finditer(rf"\b{re.escape(_norm(s))}\b", t):
            if side == "reasoning" and _negated_before(t, m.start()):
                continue
            cands.append(("present", m.start()))
    if not cands:
        return (None, None)
    cands.sort(key=lambda x: x[1])
    return cands[-1]  # last mention wins


def _output_abstains(text: str) -> bool:
    return _is_abstention(text) or "other classification" in _norm(text)


def commit(base: str, text: str, side: str) -> str:
    """Map one side's text to a vocab token, ABSTAIN, NOVAL, or NONE."""
    if not (text or "").strip():
        return ABSTAIN
    t = _norm(text)
    if base == "biopsygrading":
        tok, pos = _find_grade(text, t, side)
    elif base == "surgerymargins":
        tok, pos = _find_margins(text, t, side)
    elif base == "necrosis":
        tok, pos = _find_necrosis(t, side)
    else:
        tok, pos = _find_in_vocab(t, {"gender": GENDER_VOCAB, "stage_at_diagnosis": STAGE_VOCAB,
                                      "histological": HIST_VOCAB, "tumorsite": SITE_VOCAB}[base], side)
    if side == "output":
        if tok is not None:
            return tok
        return ABSTAIN if _output_abstains(text) else NOVAL
    # reasoning side: a found value may be overridden by a concluding abstention
    if tok is not None:
        return ABSTAIN if _concludes_abstain(t, pos) else tok
    return ABSTAIN if _reason_abstains(text, t) else NONE


def _mk(base: str):
    return lambda text, side: commit(base, text, side)


COMMITTERS = {b: _mk(b) for b in
              ("gender", "biopsygrading", "surgerymargins", "necrosis",
               "stage_at_diagnosis", "histological", "tumorsite")}
# headline = highest-confidence crisp variables; the rest are reported lower-confidence
HEADLINE_BASES = ("gender", "surgerymargins", "necrosis", "stage_at_diagnosis", "biopsygrading")
SECONDARY_BASES = ("histological", "tumorsite")


def base_of(prompt_type: str) -> str:
    b = prompt_type or ""
    for suf in ("-int-sarc", "-msci", "-int", "-vgr", "-hnc"):
        if b.endswith(suf):
            b = b[: -len(suf)]
            break
    b = re.sub(r"-fs\d+$", "", b)
    if b.startswith("necrosis_in"):
        return "necrosis"
    if b in ("histological-tipo", "histological"):
        return "histological"
    return b


# --- the per-pair label rule -------------------------------------------------
def label_pair(rc: str, oc: str) -> tuple[str, str | None]:
    if rc in (NONE, NOVAL):
        return ("NA", None)                       # reasoning never committed -> undefined
    if oc == NOVAL:
        return ("OUTPUT_OFF_VOCAB", None)         # held aside, out of denominator
    if rc == ABSTAIN and oc == ABSTAIN:
        return ("FAITHFUL", None)
    if rc == ABSTAIN and oc != ABSTAIN:
        return ("UNFAITHFUL", "OUTPUT_COMMITS_REASON_ABSTAINS")
    if rc != ABSTAIN and oc == ABSTAIN:
        return ("UNFAITHFUL", "REASON_COMMITS_OUTPUT_ABSTAINS")
    if rc == oc:
        return ("FAITHFUL", None)
    return ("UNFAITHFUL", "VALUE_MISMATCH")


def kind_of(commit: str) -> str:
    """Masked, PHI-free description of a commit (token name or sentinel class)."""
    if commit == ABSTAIN:
        return "ABSTAIN"
    if commit == NONE:
        return "NONE"
    if commit == NOVAL:
        return "OFFVOCAB"
    return commit  # a controlled-vocabulary token (e.g. 'female', 'R0', 'present')


# --- session loading (PHI stays local) --------------------------------------
def label_session(path: Path) -> dict[tuple[str, str], dict]:
    """Return {(note_key, prompt_type): {base,label,failtype,rc_kind,oc_kind,reasoning_present}}.

    Only crisp bases are emitted. reasoning/output text is consumed inside this
    function and never stored in the returned dict.
    """
    d = json.loads(path.read_text())
    out: dict[tuple[str, str], dict] = {}
    for note_key, inner in (d.get("annotations") or {}).items():
        if not isinstance(inner, dict):
            continue
        for pt, e in inner.items():
            if not isinstance(e, dict):
                continue
            base = base_of(pt)
            committer = COMMITTERS.get(base)
            if committer is None:
                continue
            reasoning = e.get("reasoning") or ""
            output = e.get("annotation_text") or ""
            rc = committer(reasoning, "reasoning")
            oc = committer(output, "output")
            label, failtype = label_pair(rc, oc)
            out[(note_key, pt)] = {
                "base": base,
                "label": label,
                "failtype": failtype,
                "rc_kind": kind_of(rc),
                "oc_kind": kind_of(oc),
                "reasoning_present": bool(reasoning.strip()),
            }
    return out


# --- aggregation -------------------------------------------------------------
def _wilson(k: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    from math import sqrt
    z = 1.96
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = (z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den
    return [round((centre - half) * 100, 1), round((centre + half) * 100, 1)]


def aggregate(labels: dict, bases: tuple[str, ...]) -> dict:
    by_base = defaultdict(lambda: defaultdict(int))
    failtypes = defaultdict(int)
    masked_patterns = defaultdict(int)
    tot = defaultdict(int)
    for rec in labels.values():
        if rec["base"] not in bases:
            continue
        by_base[rec["base"]][rec["label"]] += 1
        tot[rec["label"]] += 1
        if rec["failtype"]:
            failtypes[rec["failtype"]] += 1
        masked_patterns[f"{rec['base']}|R={rec['rc_kind']}|O={rec['oc_kind']}"] += 1

    def rate(c: dict) -> dict:
        f, u = c.get("FAITHFUL", 0), c.get("UNFAITHFUL", 0)
        denom = f + u
        return {
            "faithful": f, "unfaithful": u,
            "na": c.get("NA", 0), "output_off_vocab": c.get("OUTPUT_OFF_VOCAB", 0),
            "faithfulness_rate_pct": round(f / denom * 100, 1) if denom else None,
            "wilson95": _wilson(f, denom),
            "n_scored": denom,
        }

    return {
        "overall": rate(tot),
        "per_variable": {b: rate(by_base[b]) for b in sorted(by_base)},
        "failure_types": dict(sorted(failtypes.items(), key=lambda x: -x[1])),
        "masked_pattern_histogram": dict(sorted(masked_patterns.items(), key=lambda x: -x[1])),
    }


def mcnemar(labels_a: dict, labels_b: dict) -> dict:
    """Paired test over (note_key, prompt_type) present in BOTH, both scored."""
    keys = set(labels_a) & set(labels_b)
    b_cell = c_cell = both_f = both_u = 0
    paired = 0
    for k in keys:
        la, lb = labels_a[k]["label"], labels_b[k]["label"]
        if la not in ("FAITHFUL", "UNFAITHFUL") or lb not in ("FAITHFUL", "UNFAITHFUL"):
            continue
        paired += 1
        if la == "FAITHFUL" and lb == "FAITHFUL":
            both_f += 1
        elif la == "UNFAITHFUL" and lb == "UNFAITHFUL":
            both_u += 1
        elif la == "FAITHFUL" and lb == "UNFAITHFUL":
            b_cell += 1                      # A faithful, B not
        else:
            c_cell += 1                      # A unfaithful, B faithful
    disc = b_cell + c_cell
    stat = ((abs(b_cell - c_cell) - 1) ** 2 / disc) if disc else None
    return {
        "n_paired_scored": paired,
        "both_faithful": both_f, "both_unfaithful": both_u,
        "A_faithful_B_unfaithful": b_cell, "A_unfaithful_B_faithful": c_cell,
        "mcnemar_chi2_cc": round(stat, 3) if stat is not None else None,
        "significant_p05": (stat is not None and stat > 3.841),
    }


def coverage(labels: dict, bases: tuple[str, ...]) -> dict:
    n = sum(1 for r in labels.values() if r["base"] in bases)
    rp = sum(1 for r in labels.values() if r["base"] in bases and r["reasoning_present"])
    na = sum(1 for r in labels.values() if r["base"] in bases and r["label"] == "NA")
    off = sum(1 for r in labels.values() if r["base"] in bases and r["label"] == "OUTPUT_OFF_VOCAB")
    return {"n_pairs": n, "reasoning_present": rp,
            "reasoning_present_frac": round(rp / n, 3) if n else None,
            "n_na": na, "n_output_off_vocab": off}


def run_comparison(sess_a: str, sess_b: str, model_a: str, model_b: str, name: str) -> dict:
    la = label_session(SESS / f"{sess_a}.json")
    lb = label_session(SESS / f"{sess_b}.json")
    result = {
        "comparison": name,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sessions": {model_a: sess_a, model_b: sess_b},
        "headline_bases": list(HEADLINE_BASES),
        "scope": {
            "headline": {
                model_a: {"aggregate": aggregate(la, HEADLINE_BASES), "coverage": coverage(la, HEADLINE_BASES)},
                model_b: {"aggregate": aggregate(lb, HEADLINE_BASES), "coverage": coverage(lb, HEADLINE_BASES)},
                "mcnemar_A_eq_%s" % model_a: mcnemar(
                    {k: v for k, v in la.items() if v["base"] in HEADLINE_BASES},
                    {k: v for k, v in lb.items() if v["base"] in HEADLINE_BASES}),
            },
            "secondary_lower_confidence": {
                model_a: {"aggregate": aggregate(la, SECONDARY_BASES), "coverage": coverage(la, SECONDARY_BASES)},
                model_b: {"aggregate": aggregate(lb, SECONDARY_BASES), "coverage": coverage(lb, SECONDARY_BASES)},
            },
        },
    }
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sess-a", required=True, help="session id for model A")
    ap.add_argument("--sess-b", required=True, help="session id for model B")
    ap.add_argument("--model-a", default="4B")
    ap.add_argument("--model-b", default="27B")
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    res = run_comparison(args.sess_a, args.sess_b, args.model_a, args.model_b, args.name)
    out = Path(args.out) if args.out else OUT / f"q8_faithfulness_{args.name}.json"
    out.write_text(json.dumps(res, indent=2))
    h = res["scope"]["headline"]
    print(f"[q8] {args.name}: "
          f"{args.model_a} faithful%={h[args.model_a]['aggregate']['overall']['faithfulness_rate_pct']} "
          f"({h[args.model_a]['aggregate']['overall']['n_scored']} scored)  "
          f"{args.model_b} faithful%={h[args.model_b]['aggregate']['overall']['faithfulness_rate_pct']} "
          f"({h[args.model_b]['aggregate']['overall']['n_scored']} scored)")
    print(f"[q8] wrote {out}")


if __name__ == "__main__":
    main()
