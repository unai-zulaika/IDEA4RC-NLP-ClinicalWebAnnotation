"""Assign each prompt_type a bucket (Reliable / Usable / Unreliable) plus a
short auto-reason and flags. Pure function of the metrics dict — no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

# Display thresholds and minimum samples required to flag a default-bias pattern.
MIN_WRONG_FOR_DEFAULT_BIAS = 3
DEFAULT_BIAS_SHARE = 0.60
DEFAULT_BIAS_MAX_PRED_LEN = 30
HIGH_ABSTENTION_RATE = 0.80
MIN_TOTAL_FOR_SUPPORT = 10
REPORT_TYPE_SKEW_GAP = 0.20  # 20-pp gap between best and worst report_type


@dataclass(frozen=True)
class ClassifierConfig:
    reliable_threshold: float = 0.70
    usable_threshold: float = 0.40
    fp_cap: float = 0.10

    def validate(self) -> None:
        if not 0.0 <= self.usable_threshold < self.reliable_threshold <= 1.0:
            raise ValueError(
                f"Threshold inversion: usable={self.usable_threshold}, "
                f"reliable={self.reliable_threshold}. Required: 0 ≤ usable < reliable ≤ 1."
            )
        if not 0.0 <= self.fp_cap <= 1.0:
            raise ValueError(f"--fp-cap must be in [0, 1], got {self.fp_cap}")


def _dominant_wrong_value(p: dict) -> tuple[str | None, float]:
    """Among predicted values where match_type was NOT 'match', find the most
    common predicted value and its share of the wrong-prediction total.
    Returns (value, share). value is None when there are zero wrong predictions.
    """
    counts = p["counts"]
    n_wrong = counts["mismatch"] + counts["false_positive"] + counts["false_negative"]
    if n_wrong == 0:
        return None, 0.0

    # The histogram is over ALL predictions, including matches. We don't have a
    # per-row predicted breakdown by match_type here — but the aggregator stored
    # the full histogram, and we want the wrong-only signal. Approximation:
    # subtract the 'match' contributions assuming matches predicted = expected.
    #
    # For the default-bias case we're trying to catch, the wrong predictions
    # concentrate on ONE value that is far more common than its match share
    # (e.g. predicts 'female' for both correctly-female cases AND wrong cases).
    # The safest heuristic: only flag default_bias when:
    #   1) the histogram exists (short values only),
    #   2) there are ≥ MIN_WRONG_FOR_DEFAULT_BIAS wrong predictions,
    #   3) the most-predicted value's count exceeds (match count of that value) +
    #      DEFAULT_BIAS_SHARE * n_wrong.
    #
    # Without per-row breakdown we approximate the dominant-wrong-value share by
    # checking: of all predictions, the most common minus (matches that share
    # the same expected value) over n_wrong.
    histogram = p.get("predicted_value_histogram")
    if not histogram:
        return None, 0.0

    # Find the most common predicted value, count its over-representation past
    # the number of correct matches it could explain.
    top_value, top_count = next(iter(histogram.items()))
    # Correct matches contribute at most counts['match'] to the top value (and
    # only if every correct case had this same predicted value). To be
    # conservative, assume up to counts['match'] of top_count are correct.
    n_match = counts["match"]
    wrong_in_top = max(0, top_count - n_match)
    share = wrong_in_top / n_wrong if n_wrong else 0.0
    return top_value, share


def _has_default_bias(p: dict) -> tuple[bool, str | None, float]:
    """Return (flagged, dominant_value, dominant_share)."""
    counts = p["counts"]
    n_wrong = counts["mismatch"] + counts["false_positive"] + counts["false_negative"]
    if n_wrong < MIN_WRONG_FOR_DEFAULT_BIAS:
        return False, None, 0.0
    if p["avg_predicted_length"] > DEFAULT_BIAS_MAX_PRED_LEN:
        return False, None, 0.0
    value, share = _dominant_wrong_value(p)
    if share >= DEFAULT_BIAS_SHARE:
        return True, value, share
    return False, None, 0.0


def _report_type_skew(p: dict) -> tuple[bool, str | None, float]:
    """Detect when one report_type has a markedly lower match_rate than the others."""
    by_rt = p["by_report_type"]
    if len(by_rt) < 2:
        return False, None, 0.0
    rates = [(name, m["match_rate"]) for name, m in by_rt.items() if m["total"] >= 3]
    if len(rates) < 2:
        return False, None, 0.0
    best = max(rates, key=lambda r: r[1])
    worst = min(rates, key=lambda r: r[1])
    gap = best[1] - worst[1]
    if gap >= REPORT_TYPE_SKEW_GAP:
        return True, worst[0], gap
    return False, None, 0.0


def classify_prompt(prompt_name: str, p: dict, cfg: ClassifierConfig) -> dict:
    """Return {bucket, auto_reason, flags} for one prompt_type's metrics.

    Bucketing uses `correctness_rate` (matches + correct abstentions). A
    prompt that correctly abstains 90% of the time can still be Unreliable
    if `abstention_rate` is ≥ HIGH_ABSTENTION_RATE — the variable is rarely
    useful for pre-filling even if the per-call behaviour is right.
    """
    total = p["total"]
    match_rate = p["match_rate"]
    correctness_rate = p["correctness_rate"]
    fp_rate = p["fp_rate"]
    abstention_rate = p["abstention_rate"]
    flags: list[str] = []

    # Rule 1: low support
    if total < MIN_TOTAL_FOR_SUPPORT:
        return {
            "bucket": "unreliable",
            "auto_reason": f"Only {total} annotations attempted; insufficient evidence.",
            "flags": ["low_support"],
        }

    # Rule 2: abstention trap — variable rarely produces a useful value, even
    # when the model is right to abstain.
    if abstention_rate >= HIGH_ABSTENTION_RATE:
        return {
            "bucket": "unreliable",
            "auto_reason": (
                f"Outputs nothing in {abstention_rate:.0%} of cases. "
                f"Variable rarely produces a useful value; likely needs prompt "
                f"redesign or report-type filter."
            ),
            "flags": ["high_abstention"],
        }

    # Rule 3: low correctness
    if correctness_rate < cfg.usable_threshold:
        return {
            "bucket": "unreliable",
            "auto_reason": (
                f"Correct in {correctness_rate:.0%} of N={total} cases "
                f"(extraction {match_rate:.0%}, abstentions {abstention_rate:.0%}), "
                f"below threshold {cfg.usable_threshold:.0%}."
            ),
            "flags": ["low_correctness"],
        }

    # Rule 4: default bias → Usable (regardless of correctness_rate)
    biased, dom_value, dom_share = _has_default_bias(p)
    if biased:
        flags.append(f"default_bias:{dom_value}")
        skewed, worst_rt, gap = _report_type_skew(p)
        if skewed:
            flags.append(f"report_type_skew:{worst_rt}")
        return {
            "bucket": "usable",
            "auto_reason": (
                f"Correct in {correctness_rate:.0%} of cases but skews to "
                f"'{dom_value}' ({dom_share:.0%} of wrong predictions). "
                f"Other cases need verification."
            ),
            "flags": flags,
        }

    # Rule 5: Reliable
    if correctness_rate >= cfg.reliable_threshold and fp_rate <= cfg.fp_cap:
        skewed, worst_rt, gap = _report_type_skew(p)
        if skewed:
            flags.append(f"report_type_skew:{worst_rt}")
        return {
            "bucket": "reliable",
            "auto_reason": (
                f"~{correctness_rate:.0%} correct across N={total} "
                f"(extracted {match_rate:.0%}, abstained correctly "
                f"{abstention_rate:.0%}, FP {fp_rate:.0%})."
            ),
            "flags": flags,
        }

    # Rule 6: Usable (everything else)
    if fp_rate > cfg.fp_cap:
        flags.append("high_fp")
    skewed, worst_rt, gap = _report_type_skew(p)
    if skewed:
        flags.append(f"report_type_skew:{worst_rt}")
    return {
        "bucket": "usable",
        "auto_reason": (
            f"Correct in {correctness_rate:.0%} of N={total} cases "
            f"(extraction {match_rate:.0%}, FP {fp_rate:.0%})."
        ),
        "flags": flags,
    }


def classify_all(metrics: dict, cfg: ClassifierConfig) -> dict:
    """Mutate metrics in place to add bucket/auto_reason/flags per prompt,
    plus a top-level counts.{reliable,usable,unreliable} tally. Returns metrics.
    """
    cfg.validate()
    bucket_tally = {"reliable": 0, "usable": 0, "unreliable": 0}
    for prompt_name, p in metrics["by_prompt"].items():
        result = classify_prompt(prompt_name, p, cfg)
        p.update(result)
        bucket_tally[result["bucket"]] += 1
    metrics["bucket_counts"] = bucket_tally
    metrics["summary_sentence"] = (
        f"{bucket_tally['reliable']} variables reliably extracted, "
        f"{bucket_tally['usable']} usable as suggestions, "
        f"{bucket_tally['unreliable']} unreliable."
    )
    return metrics
