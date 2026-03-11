# INT → MSCI Variable Mapping Export Report

**Date:** 2026-03-10

---

## Edits Applied to MSCI/prompts.json

| # | Prompt | Edit | Detail |
|---|--------|------|--------|
| 1 | **biopsygrading** | Added value_code_mappings | 7 codes (grades 1/2/3, high/h, low/l) |
| 2 | **chemotherapy_end** | **Bug fix** + added codes | Fixed `[provide date]` field from `reasonForEndOfTreatment` → `endDateSystemicTreatment`; added 4 missing reason codes (completion, toxicity, discontinued, death) |
| 3 | **chemotherapy_start** | Added value_code_mappings | 26 regimen OMOP codes for `[select regimen]` |
| 4 | **radiotherapy_end** | **Bug fix** + added code | Fixed `[put total dose]` field from `rtTreatmentCompletedAsPlanned` → `totalDoseGy`; added `comorbidity` code |
| 5 | **recur_or_prog** | Added value_code_mappings | 2 OMOP codes (recurrence, progression) alongside existing output_word_mappings |
| 6 | **surgerytype** | Added value_code_mappings | 2 codes for marginsAfterSurgery (complete/incomplete) |

---

## Prompts in MSCI but NOT in INT (3)

| Prompt | Description | Entity Mapping |
|--------|-------------|----------------|
| **last_contact_date** | Last follow-up contact date | `PatientFollowUp.lastContact` |
| **patient-bmi** | BMI + date | `Patient.bmi`, `Patient.bmiDate` |
| **patient-weightheight** | Weight/height/date | `Patient.weight`, `Patient.height`, `Patient.weightHeightDate` |

---

## Prompts in INT but NOT in MSCI (5)

| Prompt | Description | Entity Mapping |
|--------|-------------|----------------|
| **reexcision** | Re-excision date + margins | `Surgery.dateOfSurgery`, `Surgery.surgeryType`, `Surgery.marginsAfterSurgery` |
| **response-to** | Response to chemo/radiotherapy | `SystemicTreatment.bestResponseToTreatment` |
| **surgical-mitotic-count** | Surgical specimen mitotic count | `Surgery.surgicalSpecimenMitoticCount` |
| **surgical-specimen-grading** | FNCLCC grading on surgical specimens | `Surgery.surgicalSpecimenGradingOnlyInUntreatedTumours` |
| **tumordepth** | Superficial vs deep | `Diagnosis.deepDepth` |

---

## Already Equal / No Export Needed (14 shared prompts)

| Prompt | Reason |
|--------|--------|
| ageatdiagnosis | No value_code_mappings in either |
| biopsymitoticcount | No value_code_mappings in either |
| gender | Both have identical `{"male": "8507", "female": "8532"}` |
| histological(-tipo/histological) | No value_code_mappings in either |
| necrosis_in_biopsy | No value_code_mappings in either |
| necrosis_in_surgical | No value_code_mappings in either |
| occurrence_cancer | No value_code_mappings in either |
| patient-status | MSCI has broader coverage (DOD, DOC, DUC, Alive) — no export needed |
| previous_cancer_treatment | MSCI has array-based codes (more detailed) — no export needed |
| radiotherapy_start | Both have identical intent mappings |
| recurrencetype | No value_code_mappings in either |
| surgerymargins | Both have identical `{"R0": "1634643", "R1": "1633801", "R2": "1634484"}` |
| tumorbiopsytype | Both have equivalent codes (different key names matching templates) |
| tumordiameter | No value_code_mappings in either |
| tumorsite | No value_code_mappings in either |

---

## Still Missing value_code_mappings (candidates for future enrichment)

These shared prompts have no codes in either center and could benefit from them:

| Prompt | Notes |
|--------|-------|
| **necrosis_in_biopsy** | Could map absent/present/percentage to concept codes |
| **necrosis_in_surgical** | Same as above |
| **recurrencetype** | Could map local/metastatic to concept codes |
| **stage_at_diagnosis** | MSCI uses simple `[value]` → `clinicalStaging`; INT uses complex multi-boolean model — not directly exportable, needs separate design |

Numeric/free-text fields (ageatdiagnosis, biopsymitoticcount, tumordiameter, tumorsite, occurrence_cancer, histological) don't require value_code_mappings.

---

## Known Bugs in VGR

VGR/prompts.json has the same two field_name bugs found and fixed in MSCI:

| Prompt | Bug | Should Be |
|--------|-----|-----------|
| **chemotherapy_end** | `[provide date]` → `reasonForEndOfTreatment` | `endDateSystemicTreatment` |
| **radiotherapy_end** | `[put total dose]` → `rtTreatmentCompletedAsPlanned` | `totalDoseGy` |
