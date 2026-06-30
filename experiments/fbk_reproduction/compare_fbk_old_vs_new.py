"""Compare FBK's own published MSCI numbers (slide 22, 'MSCI-Sarcoma:
Completion Status') against the same FBK setup re-scored with our methodology.

The point: same predictions, two different evaluation metrics. The gap is the
metric, not the model.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

# FBK's reported per-variable accuracy (their MSCI Completion Status slide 22),
# keyed by our internal variable name.
FBK_REPORTED = {
    "radiotherapy_start": 84.62,
    "tumordiameter": 85.0,
    "tumorbiopsytype": 62.96,         # FBK calls this "Tumor Type"
    "radiotherapy_end": 83.33,
    "surgerytype": 96.15,
    "ageatdiagnosis": 89.47,
    "gender": 64.0,
    "tumorsite": 80.77,
    "chemotherapy_end": 87.5,
    "chemotherapy_start": 62.5,
    "previous_cancer_treatment": 64.29,
    "recur_or_prog": 90.0,            # "Recurrence/Progression"
    "recurrencetype": 84.62,
    "necrosis_in_biopsy": 100.0,
    "necrosis_in_surgical": 100.0,
    "biopsy_mitotic_count": 100.0,
    "patient-status": 90.0,
    "patient-weightheight": 100.0,
    "patient-bmi": 87.5,
    "occurrence_cancer": 42.86,
    "biopsygrading": 55.0,
    "surgerymargins": 57.14,
    "last_contact_date": 12.5,
    "stage_at_diagnosis": 45.0,
    "histological": 59.26,
}


def main() -> None:
    data = json.loads(Path("experiments/fbk_reproduction/full25/comparison.json").read_text())
    ff = data["fbk_filtered"]

    rows = []
    for var, fbk_val in FBK_REPORTED.items():
        ours_val = ff.get(var, {}).get("correct_rate", 0) * 100
        rows.append((var, fbk_val, ours_val, ours_val - fbk_val))

    rows.sort(key=lambda r: -r[1])

    print(
        "| Variable | FBK report (EM+PM) | Same setup, our methodology | Δ |"
    )
    print("|---|---:|---:|---:|")
    for var, fbk_val, ours_val, delta in rows:
        print(f"| `{var}` | {fbk_val:.1f}% | {ours_val:.0f}% | {delta:+.1f} |")

    print()
    print(f"**Mean FBK reported:** "
          f"{statistics.mean([r[1] for r in rows]):.1f}%")
    print(f"**Mean same setup, our methodology:** "
          f"{statistics.mean([r[2] for r in rows]):.1f}%")
    print(f"**Mean gap:** "
          f"{statistics.mean([r[3] for r in rows]):+.1f} percentage points")

    # How many of FBK's '100%' claims survive at >= 80% under our scoring?
    near100 = [r for r in rows if r[1] >= 99]
    print(f"\nFBK's '100%' claims under our scoring: "
          f"{', '.join(f'{r[0]}={r[2]:.0f}%' for r in near100)}")


if __name__ == "__main__":
    main()
