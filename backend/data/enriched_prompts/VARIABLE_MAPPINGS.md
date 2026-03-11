# Variable Mappings — Enriched Prompts

This document explains the `value_code_mappings` added to the enriched prompt files in `backend/data/enriched_prompts/{INT,MSCI,VGR}/prompts.json`.

## What Are value_code_mappings?

Each prompt template instructs the LLM to produce a specific textual annotation (e.g., `"Margins after surgery: R0"`). When exporting annotated data to CSV in coded format, these text values must be converted to IDEA4RC numeric code IDs.

`value_code_mappings` is a dictionary on a `field_mapping` entry:
```json
"value_code_mappings": {
  "<llm_output_text>": "<idea4rc_code_id>"
}
```

The codes are **OMOP/IDEA4RC concept IDs** looked up from `data/dictionaries/id2codes_dict.json` and cross-validated against real patient data in `SARC_V2(in).csv`.

---

## Methodology

For each prompt and its field_mappings:
1. **Field type determined** from `synthetic_idea4rc_csv.csv` (`types` column: Code, Integer, Boolean, Date, Float, String, ElementReference). Only `Code`-type fields need `value_code_mappings`.
2. **LLM output text identified** from the prompt template (allowed options / format constraints).
3. **Code looked up** in `data/dictionaries/id2codes_dict.json` by matching the category (via `CORE_VARIABLE_TO_CATEGORY` in `backend/lib/code_resolver.py`) and label.
4. **Code validated** against values appearing in `SARC_V2(in).csv` for the matching `core_variable`.

---

## Mappings Added

### 1. `gender` → `Patient.sex`
**Centers**: INT, MSCI
**Field**: `sex` | **Placeholder**: `[male/female/unknown]`
**Source**: `id2codes_dict.json` category `"Sex"`
**SARC validation**: `Patient.sex` values include `8532`

| LLM Text | Code | Label |
|----------|------|-------|
| `male` | `8507` | Sex - Male |
| `female` | `8532` | Sex - Female |

> `"unknown"` has no corresponding code in the dictionary — omitted.

---

### 2. `tumorbiopsytype` → `Diagnosis.typeOfBiopsy`
**Centers**: INT, MSCI, VGR
**Field**: `typeOfBiopsy` | **Placeholder**: `[biopsy type]`
**Source**: `id2codes_dict.json` category `"Type of biopsy"`
**SARC validation**: codes 4171863, 4321878, 4321986, 4228202 all present in data

| LLM Text | Code | Label |
|----------|------|-------|
| `Fine needle biopsy` | `4171863` | Type of biopsy - Fine needle biopsy |
| `Core needle biopsy` | `4321878` | Type of biopsy - Core needle biopsy |
| `Incisional biopsy` | `4321986` | Type of biopsy - Incisional biopsy |
| `Excisional biopsy` | `4228202` | Type of biopsy - Excisional biopsy |
| `Excision` | `4279903` | Type of biopsy - Excision |

---

### 3. `surgerymargins` → `Surgery.marginsAfterSurgery`
**Centers**: INT, MSCI, VGR
**Field**: `marginsAfterSurgery` | **Placeholder**: `[R0 or R1 or R2]` (INT/MSCI) / `[value]` (VGR)
**Source**: `id2codes_dict.json` category `"Margins after surgery"`
**SARC validation**: codes 1634643, 1633801, 1634484 all present

| LLM Text | Code | Label |
|----------|------|-------|
| `R0` | `1634643` | Margins after surgery - R0: No residual tumor |
| `R1` | `1633801` | Margins after surgery - R1: Microscopic residual tumor |
| `R2` | `1634484` | Margins after surgery - R2: Macroscopic residual tumor |

---

### 4. `reexcision` → `Surgery.marginsAfterSurgery`
**Centers**: INT, VGR
**Field**: `marginsAfterSurgery` | **Placeholder**: `[complete/incomplete]`
**Source**: Same "Margins after surgery" codes. Re-excision template uses "macroscopically complete" (= R0, no residual tumor) and "macroscopically incomplete" (= R2, macroscopic residual). R1 (microscopic) is not an explicit LLM option in this prompt.

| LLM Text | Code | Label |
|----------|------|-------|
| `complete` | `1634643` | Margins after surgery - R0: No residual tumor |
| `incomplete` | `1634484` | Margins after surgery - R2: Macroscopic residual tumor |

---

### 5. `patient-status` → `PatientFollowUp.statusAtLastFollowUp`
**Centers**: INT, MSCI, VGR
**Field**: `statusAtLastFollowUp` | **Placeholder**: `[value]`
**Source**: `id2codes_dict.json` category `"Status of patient at last follow-up"`
**SARC validation**: codes 2000100071, 2000100072, 2000100075 present

| LLM Text | Code | Label |
|----------|------|-------|
| `Alive, No Evidence of Disease (NED)` | `2000100071` | Status of patient at last follow-up - Alive, No Evidence of Disease (NED) |
| `Dead of Disease (DOD)` | `2000100072` | Status of patient at last follow-up - Dead of Disease (DOD) |
| `Dead of Other Cause (DOC)` | `2000100073` | Status of patient at last follow-up - Dead of Other Cause (DOC) |
| `Dead of Unknown Cause (DUC)` | `2000100074` | Status of patient at last follow-up - Dead of Unknown Cause (DUC) |
| `Alive With Disease (AWD)` | `2000100075` | Status of patient at last follow-up - Alive With Disease (AWD) |
| `Alive` | `4230556` | Status of patient at last follow-up - Alive |

---

### 6. `tumordepth` → `Diagnosis.deepDepth`
**Centers**: INT, VGR
**Field**: `deepDepth` | **Placeholder**: `[superficial|deep]`
**Source**: `id2codes_dict.json` category `"Deep depth"` (note trailing space in dict key)
**Reasoning**: The two possible LLM outputs directly correspond to the only two codes in this category.

| LLM Text | Code | Label |
|----------|------|-------|
| `deep` | `36768749` | Deep depth - Invasion into the fascia (Deep) |
| `superficial` | `36768911` | Deep depth - NO Invasion (Superficial) |

---

### 7. `radiotherapy_start` → `Radiotherapy.intent`
**Centers**: INT, MSCI, VGR
**Field**: `intent` | **Placeholder**: `[select intention]`
**Source**: `id2codes_dict.json` category `"Intent"`
**SARC validation**: codes 4162591, 4179711 present in `Radiotherapy.intent` values

| LLM Text | Code | Label |
|----------|------|-------|
| `curative` | `4162591` | Intent - Curative procedure intent |
| `palliative` | `4179711` | Intent - Palliative |

---

### 8. `chemotherapy_start` → `SystemicTreatment.intent`
**Centers**: INT, MSCI, VGR
**Field**: `intent` | **Placeholder**: `[select intent]`
**Source**: Same `"Intent"` codes as radiotherapy_start. The chemotherapy start prompt also distinguishes pre-operative (curative) from palliative chemotherapy.

| LLM Text | Code | Label |
|----------|------|-------|
| `curative` | `4162591` | Intent - Curative procedure intent |
| `palliative` | `4179711` | Intent - Palliative |

---

### 9. `radiotherapy_end` → `Radiotherapy.rtTreatmentCompletedAsPlanned?`
**Centers**: INT, MSCI, VGR
**Field**: `rtTreatmentCompletedAsPlanned?` | **Placeholder**: `[select reason]`
**Source**: `id2codes_dict.json` category `"RT Treatment Completed as Planned?"`
**SARC validation**: code 44788181 (Completed successfully) present

| LLM Text | Code | Label |
|----------|------|-------|
| `completed successfully` | `44788181` | RT Treatment Completed as Planned? - Completed successfully |
| `discontinued by patient` | `37017062` | RT Treatment Completed as Planned? - Procedure discontinued by patient |
| `intolerance` | `4105297` | RT Treatment Completed as Planned? - Intolerance |
| `death` | `4306655` | RT Treatment Completed as Planned? - Death |
| `acute radiotherapy toxicity` | `4161588` | RT Treatment Completed as Planned? - Radiotherapy course change due to acute radiotherapy toxicity |

---

### 10. `chemotherapy_end` → `SystemicTreatment.reasonForEndOfTreatment`
**Centers**: INT, MSCI, VGR
**Field**: `reasonForEndOfTreatment` | **Placeholder**: `[select reason]`
**Source**: `id2codes_dict.json` category `"Reason for end of treatment"`
**SARC values present**: 37017063, 4162594, 4240582, 4306655, 44788181
**Partial mapping only**: SARC codes 37017063 and 4162594 are NOT found in `id2codes_dict.json` — their text labels cannot be determined from available data.

| LLM Text | Code | Label |
|----------|------|-------|
| `intolerance to drug` | `4240582` | Reason for end of treatment - Intolerance to drug |
| `treatment ended due to comorbidity` | `2000100030` | Reason for end of treatment - Treatment ended due to comorbidity |

> **Gap**: SARC codes `37017063` and `4162594` are missing from the dictionary. These likely correspond to additional end-of-treatment reasons not yet resolved.

---

### 11. `response-to` → `SystemicTreatment.treatmentResponse`
**Centers**: INT, MSCI
**Field**: `treatmentResponse` | **Placeholder**: `[select response type]`
**Source**: `id2codes_dict.json` category `"Overall Treatment response (based on imaging alone; no recist or other criteria)"`
**SARC validation**: codes 32949, 32946 present (code 32956 appears in SARC but is NOT in the dictionary)

| LLM Text | Code | Label |
|----------|------|-------|
| `complete response` | `32946` | Overall Treatment response - Complete Remission |
| `partial response` | `32947` | Overall Treatment response - Partial Remission |
| `stable disease` | `32948` | Overall Treatment response - Stable Disease |
| `progression` | `32949` | Overall Treatment response - Progression |

> **Gap**: SARC code `32956` is present in real data but not found in the dictionary.

---

### 12. `response-to` → `SystemicTreatment.typeOfSystemicTreatment`
**Centers**: INT, MSCI
**Field**: `typeOfSystemicTreatment` | **Placeholder**: `[select type]`
**Source**: `id2codes_dict.json` category `"type of systemic treatment"`
**SARC validation**: code 4273629 (Chemotherapy) present

| LLM Text | Code | Label |
|----------|------|-------|
| `chemotherapy` | `4273629` | type of systemic treatment - Chemotherapy |
| `immunotherapy` | `40310107` | type of systemic treatment - Immunotherapy |

---

### 13. `other-systemic-therapy` → `SystemicTreatment.typeOfSystemicTreatment`
**Centers**: VGR only
**Field**: `typeOfSystemicTreatment`
**Source**: Same codes as mapping #12 above.

| LLM Text | Code | Label |
|----------|------|-------|
| `chemotherapy` | `4273629` | type of systemic treatment - Chemotherapy |
| `immunotherapy` | `40310107` | type of systemic treatment - Immunotherapy |

---

## Mappings NOT Added (Insufficient Data)

| Prompt | Field | Reason |
|--------|-------|--------|
| `biopsygrading` | `Diagnosis.grading` | `id2codes_dict.json` has no `"Grading"` category. SARC codes 1633749, 1634085, 1634752, 1635587 cannot be labeled. Existing partial mapping (`"1"→"1634371"`, `"2"→"1634752"`) was preserved unchanged. |
| `surgical-specimen-grading` | `Surgery.surgicalSpecimenGradingOnlyInUntreatedTumours` | Same grading issue. SARC code 1634752 appears but cannot confirm label without "Grading" category in dict. |
| `histological-tipo` / `histological` | `Diagnosis.histologySubgroup` | ~150+ ICD-O-3 histology entries in dict; LLM outputs free-form ICD-O-3 type names that require fuzzy matching. The `CodeResolver` class handles this at runtime. |
| `tumorsite` | `Diagnosis.subsite` | 100+ anatomical subsite codes in dict; anatomical site names are best resolved at runtime by `CodeResolver`. |
| `stage_at_diagnosis` | `ClinicalStage.clinicalStaging` | The prompt outputs `"localized"` / `"loco-regional"` / `"metastatic"` but the dict contains AJCC/UICC staging codes (Stage I–IV). These are different classification systems. Mapping cannot be inferred. |
| `recurrencetype` | `DiseaseExtent.localised` | In `synthetic_idea4rc_csv.csv`, `DiseaseExtent.localised` is typed as `Boolean` (TRUE/FALSE), not `Code`. The LLM output `"local"` / `"metastatic"` cannot be mapped to boolean codes. |
| `occurrence_cancer` | `Patient.previousMalignantCancerSite` | Free-text cancer site description output by LLM. No structured code mapping applicable. |
| `previous_cancer_treatment` | `Patient.previousCancerTreatment` | SARC code `4121697` not found in dict. Dict options ("Comprehensive medication therapy review", "Immunological therapy") don't match prompt output options. |
| `surgerytype` | `Surgery.surgeryType` | Placeholder is `[FULL_ANNOTATION]` (entire annotation text). No reliable text→code conversion from full annotation string. |
| `recur_or_prog` | `EpisodeEvent.diseaseStatus` | Placeholder is `[FULL_ANNOTATION]`. Dict only has `"Recurrence"→2000100002`; full annotation text not directly mappable. |
| `necrosis_in_biopsy` | `Diagnosis.biopsyGrading` | Entity mapping uses `biopsyGrading` field for necrosis, but no "Necrosis" category in dict. Percentage / present / absent outputs have no code. |
| `necrosis_in_surgical` | `Surgery.surgicalSpecimenGradingOnlyInUntreatedTumours` | Same — no "Necrosis" category in dict. |
| `biopsymitoticcount` | `Diagnosis.biopsyMitoticCount` | **Integer** type — numeric count, no code mapping needed. |
| `surgical-mitotic-count` | `Surgery.surgicalSpecimenMitoticCount` | **Integer** type — no code mapping needed. |
| `tumordiameter` | `Diagnosis.tumorSize` | **Float** type (mm) — no code mapping needed. |
| `ageatdiagnosis` | `Diagnosis.ageAtDiagnosis` | **Integer** type — no code mapping needed. |
| `last_contact_date` (MSCI) | `PatientFollowUp.lastContact` | **Date** type — no code mapping needed. |
| `patient-bmi` (MSCI) | `Patient.bmi` | **Float** type — no code mapping needed. |
| `patient-weightheight` (MSCI) | `Patient.weight`, `Patient.height` | **Float** types — no code mapping needed. |
| `tumorrupture` (VGR) | `Surgery.tumorRupture` | **Boolean** type — no code mapping needed. |

---

## Summary by Center

| Center | Prompts (total) | Mappings Added | Notes |
|--------|----------------|----------------|-------|
| INT | 27 | 12 fields across 10 prompts | Includes `gender`, `response-to`, `reexcision`, `tumordepth` |
| MSCI | 25 | 8 fields across 8 prompts | No `reexcision`/`tumordepth`/`other-systemic-therapy`; has `response-to` |
| VGR | 22 | 10 fields across 9 prompts | Has `other-systemic-therapy`, `tumorrupture` (Boolean, not mapped), `reexcision`, `tumordepth` |

**Total new `value_code_mappings` entries added**: 30 across all three centers.

---

## Data Sources Referenced

| File | Role |
|------|------|
| `data/dictionaries/id2codes_dict.json` | Authoritative `code_id → "Category - Label"` reference |
| `SARC_V2(in).csv` | Real RedCap sarcoma data — validates which codes appear in practice |
| `synthetic_idea4rc_csv.csv` | Synthetic data — identifies field data types (`Code`, `Integer`, etc.) |
| `backend/lib/code_resolver.py` | Shows `CORE_VARIABLE_TO_CATEGORY` mapping (category name per core_variable) |
