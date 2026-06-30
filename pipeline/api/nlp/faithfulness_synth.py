#!/usr/bin/env python3
"""P1: synthetic, non-PHI calibration for the Q8 faithfulness checker.

Builds (reasoning, output) pairs from the controlled vocabulary ALONE - no patient
text - covering every label cell per crisp variable, including IT/PL synonyms and
negated forms. Asserts the checker reproduces the designed label. Gates on the
headline REASON_COMMITS_OUTPUT_ABSTAINS cell (the 'reasons-female -> outputs-NA'
failure) at >= 95%.

This file is fully inspectable and committable: it contains zero patient data.
"""
from __future__ import annotations

from collections import defaultdict

from faithfulness_check import COMMITTERS, label_pair

# Per base: concrete-value reasoning/output phrasings, plus abstain phrasings.
# Every string here is fabricated from schema vocabulary, no PHI.
CASES = {
    "gender": {
        "values": {
            "female": (["the patient is female", "la paziente presents to clinic",
                        "the note mentions a kobieta with a mass", "she is a woman, pacjentka"],
                       ["Patient's gender female."]),
            "male":   (["the patient is male", "il paziente is referred",
                        "a mezczyzna with a thigh lesion", "he is a man"],
                       ["Patient's gender male."]),
        },
        "abstain_reason": ["the sex is not stated, so it is unknown",
                           "gender is not applicable here"],
        "abstain_output": ["Patient's gender unknown"],
        "none_reason": ["a soft tissue lesion of the thigh is described",
                        "the report discusses imaging findings only"],
        "negated": [("the patient is not male; she is a woman", "female"),
                    ("not a female patient; il paziente is male", "male")],
        "considers_abstain": ["the note hints the patient may be female, but the sex is not explicitly stated",
                              "il paziente could be male, however gender is unknown"],
    },
    "biopsygrading": {
        "values": {
            "G2": (["the FNCLCC grade is 2", "grade 2 sarcoma", "G2 tumour"],
                   ["Biopsy grading (FNCLCC): 2."]),
            "G3": (["FNCLCC grade 3", "grade 3 lesion", "this is G3"],
                   ["Biopsy grading (FNCLCC): 3."]),
            "G1": (["grade 1 by FNCLCC", "G1 tumour"],
                   ["Biopsy grading (FNCLCC): 1."]),
        },
        "abstain_reason": ["the grade is not reported, so unknown",
                           "grading uses another classification system"],
        "abstain_output": ["Biopsy grading (FNCLCC): Unknown biopsy grading.",
                           "Biopsy grading not applicable"],
        "none_reason": ["a 110 mm mass is present", "the note lists treatment dates"],
        "negated": [("this is not grade 3; FNCLCC grade 2 is assigned", "G2")],
        "considers_abstain": ["grade 3 was considered, but the FNCLCC grade is not reported",
                              "this may be grade 2, however grading is unknown"],
    },
    "surgerymargins": {
        "values": {
            "R0": (["resection was R0", "margins are R0 (clear)"], ["Margins after surgery: R0"]),
            "R1": (["microscopically involved margin, R1"], ["Margins after surgery: R1"]),
            "R2": (["macroscopic residual disease, R2"], ["Margins after surgery: R2"]),
        },
        "abstain_reason": ["margin status is not specified, unknown"],
        "abstain_output": ["Margins after surgery: Not applicable"],
        "none_reason": ["the patient had radiotherapy", "tumour located in the buttock"],
        "negated": [("this was not R0; an R1 margin is reported", "R1")],
        "considers_abstain": ["an R1 margin seemed likely, but margin status is not specified",
                              "possibly R0, however it is unknown"],
    },
    "necrosis": {
        "values": {
            "absent": (["necrosis is absent", "no necrosis is seen"],
                       ["Necrosis in surgical specimen (type of): absent."]),
            "present": (["coagulative necrosis is present", "30% necrosis noted"],
                        ["Necrosis in surgical specimen (type of): 10%."]),
        },
        "abstain_reason": ["necrosis status is unknown"],
        "abstain_output": ["Necrosis in surgical specimen (type of): unknown."],
        "none_reason": ["the margin is R0", "a grade 2 sarcoma"],
        "negated": [],
        "considers_abstain": ["some necrosis may be present, but the amount is unknown",
                              "necrosis could be absent, but it is not specified"],
    },
    "stage_at_diagnosis": {
        "values": {
            "localized":   (["the disease is localized at diagnosis", "localised tumour"],
                            ["Stage at diagnosis: Localized."]),
            "loco_regional": (["loco-regional spread is noted"],
                              ["Stage at diagnosis: Loco-regional."]),
        },
        "abstain_reason": ["the stage is unknown at diagnosis"],
        "abstain_output": ["Unknown stage at diagnosis"],
        "none_reason": ["the note mentions a biopsy", "she received chemotherapy"],
        "negated": [],
        "considers_abstain": ["localized disease was considered, but the stage is unknown at diagnosis",
                              "possibly loco-regional, however staging is not specified"],
    },
}


def _check(base, reason, output, exp_label, exp_failtype, cell, tally, fails):
    fn = COMMITTERS[base]
    rc, oc = fn(reason, "reasoning"), fn(output, "output")
    label, failtype = label_pair(rc, oc)
    ok = (label == exp_label) and (failtype == exp_failtype)
    tally[cell][0] += int(ok)
    tally[cell][1] += 1
    if not ok:
        # report only base + intended cell + the masked commit kinds (no patient text;
        # these strings are synthetic schema anyway, but keep the habit)
        fails.append(f"{base:18s} cell={cell:32s} got=({label},{failtype}) rc={rc} oc={oc}")


def run() -> int:
    tally = defaultdict(lambda: [0, 0])  # cell -> [pass, total]
    fails: list[str] = []
    for base, spec in CASES.items():
        vals = spec["values"]
        toks = list(vals)
        # agree-value -> FAITHFUL
        for tok, (reasons, outputs) in vals.items():
            for r in reasons:
                for o in outputs:
                    _check(base, r, o, "FAITHFUL", None, "agree_value", tally, fails)
        # abstain/abstain -> FAITHFUL
        for r in spec["abstain_reason"]:
            for o in spec["abstain_output"]:
                _check(base, r, o, "FAITHFUL", None, "abstain_abstain", tally, fails)
        # reason commits / output abstains -> UNFAITHFUL (HEADLINE cell)
        for tok, (reasons, outputs) in vals.items():
            for r in reasons:
                for o in spec["abstain_output"]:
                    _check(base, r, o, "UNFAITHFUL", "REASON_COMMITS_OUTPUT_ABSTAINS",
                           "reason_commits_output_abstains", tally, fails)
        # reason abstains / output commits -> UNFAITHFUL
        for r in spec["abstain_reason"]:
            for tok, (reasons, outputs) in vals.items():
                for o in outputs:
                    _check(base, r, o, "UNFAITHFUL", "OUTPUT_COMMITS_REASON_ABSTAINS",
                           "output_commits_reason_abstains", tally, fails)
        # value mismatch -> UNFAITHFUL
        if len(toks) >= 2:
            (ta, (ra, _)), (tb, (_, ob)) = list(vals.items())[0], list(vals.items())[1]
            for r in ra:
                for o in ob:
                    _check(base, r, o, "UNFAITHFUL", "VALUE_MISMATCH",
                           "value_mismatch", tally, fails)
        # reason none -> NA
        for r in spec["none_reason"]:
            o = spec["values"][toks[0]][1][0]
            _check(base, r, o, "NA", None, "reason_none_NA", tally, fails)
        # negated reasoning resolves to the asserted value -> FAITHFUL against its output
        for r, tok in spec.get("negated", []):
            o = spec["values"][tok][1][0]
            _check(base, r, o, "FAITHFUL", None, "negated_value", tally, fails)
        # REFINEMENT: reasoning considers a value then CONCLUDES abstention.
        # vs an abstaining output -> FAITHFUL (the chain's commitment is ABSTAIN).
        for r in spec.get("considers_abstain", []):
            for o in spec["abstain_output"]:
                _check(base, r, o, "FAITHFUL", None, "considers_then_abstains", tally, fails)
        # ...and vs a committing output -> UNFAITHFUL (output commits, reasoning abstained)
        for r in spec.get("considers_abstain", []):
            o = spec["values"][toks[0]][1][0]
            _check(base, r, o, "UNFAITHFUL", "OUTPUT_COMMITS_REASON_ABSTAINS",
                   "considers_abstain_vs_commit", tally, fails)

    print("=== synthetic calibration (cell: pass/total = %) ===")
    overall_p = overall_t = 0
    for cell in sorted(tally):
        p, t = tally[cell]
        overall_p += p
        overall_t += t
        flag = "" if p == t else "  <-- CHECK"
        print(f"  {cell:34s} {p:3d}/{t:3d} = {p/t*100:5.1f}%{flag}")
    print(f"  {'OVERALL':34s} {overall_p:3d}/{overall_t:3d} = {overall_p/overall_t*100:5.1f}%")

    headline = tally["reason_commits_output_abstains"]
    hp = headline[0] / headline[1] * 100
    print(f"\nHEADLINE cell (reason_commits_output_abstains): {headline[0]}/{headline[1]} = {hp:.1f}%")
    if fails:
        print(f"\n{len(fails)} failing cases:")
        for f in fails:
            print("  " + f)
    gate_ok = hp >= 95.0
    print(f"\nGATE (headline >= 95%): {'PASS' if gate_ok else 'FAIL'}")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
