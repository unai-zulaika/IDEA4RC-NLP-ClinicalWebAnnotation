#!/usr/bin/env python3
"""
Generate prompts_proposal.json from the existing prompts.json.

This script:
1. Reads prompts.json
2. Converts all string-only prompts to {"template": ..., "entity_mapping": ...}
3. Adds new prompts for uncovered data model variables
4. Writes the result to prompts_proposal.json
"""

import json
import os
import copy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_PATH = os.path.join(SCRIPT_DIR, "prompts.json")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "prompts_proposal.json")

# ============================================================
# Entity mappings for EXISTING prompts that are currently strings
# ============================================================

INT_ENTITY_MAPPINGS = {
    "necrosis_in_biopsy-int": {
        "entity_type": "Diagnosis",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "biopsyGrading"}
        ]
    },
    "chemotherapy_start-int": {
        "entity_type": "SystemicTreatment",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select intent]", "entity_type": "SystemicTreatment", "field_name": "intent"},
            {"template_placeholder": "[provide date]", "entity_type": "SystemicTreatment", "field_name": "startDateSystemicTreatment"},
            {"template_placeholder": "[select regimen]", "entity_type": "SystemicTreatment", "field_name": "regimen"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "SystemicTreatment", "field_name": "setting"}
        ]
    },
    "surgerytype-fs30-int": {
        "entity_type": "Surgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "Surgery", "field_name": "surgeryType"},
            {"template_placeholder": "DD/MM/YYYY", "entity_type": "Surgery", "field_name": "dateOfSurgery"},
            {"template_placeholder": "[complete/incomplete]", "entity_type": "Surgery", "field_name": "marginsAfterSurgery"}
        ]
    },
    "radiotherapy_start-int": {
        "entity_type": "Radiotherapy",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select intention]", "entity_type": "Radiotherapy", "field_name": "intent"},
            {"template_placeholder": "[please select where]", "entity_type": "Radiotherapy", "field_name": "radiotherapyHospital"},
            {"template_placeholder": "[put date]", "entity_type": "Radiotherapy", "field_name": "startDate"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "Radiotherapy", "field_name": "setting"}
        ]
    },
    "recurrencetype-int": {
        "entity_type": "DiseaseExtent",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[selected type]", "entity_type": "DiseaseExtent", "field_name": "localised"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "EpisodeEvent", "field_name": "diseaseStatus"}
        ]
    },
    "radiotherapy_end-int": {
        "entity_type": "Radiotherapy",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[put total dose]", "entity_type": "Radiotherapy", "field_name": "totalDoseGy"},
            {"template_placeholder": "[put number of]", "entity_type": "Radiotherapy", "field_name": "numberOfFractions"},
            {"template_placeholder": "[put date]", "entity_type": "Radiotherapy", "field_name": "endDate"},
            {"template_placeholder": "[select reason]", "entity_type": "Radiotherapy", "field_name": "rtTreatmentCompletedAsPlanned?"}
        ]
    },
    "tumorbiopsytype-int": {
        "entity_type": "Diagnosis",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[biopsy type]", "entity_type": "Diagnosis", "field_name": "typeOfBiopsy"},
            {"template_placeholder": "[date]", "entity_type": "Diagnosis", "field_name": "dateOfDiagnosis"},
            {"template_placeholder": "[place]", "entity_type": "Diagnosis", "field_name": "biopsyDoneBy"}
        ]
    },
    "necrosis_in_surgical-int": {
        "entity_type": "Surgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "surgicalSpecimenGradingOnlyInUntreatedTumours"}
        ]
    },
    "tumordiameter-int": {
        "entity_type": "Diagnosis.tumorSize",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "tumorSize"},
            {"template_placeholder": "[date]", "entity_type": "Diagnosis", "field_name": "dateOfDiagnosis"}
        ]
    },
    "response-to-int": {
        "entity_type": "SystemicTreatment.treatmentResponse",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select type]", "entity_type": "SystemicTreatment", "field_name": "typeOfSystemicTreatment"},
            {"template_placeholder": "[select response type]", "entity_type": "SystemicTreatment", "field_name": "treatmentResponse"}
        ]
    },
    "stage_at_diagnosis-int": {
        "entity_type": "ClinicalStage",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "ClinicalStage", "field_name": "clinicalStaging"}
        ]
    },
    "chemotherapy_end-int": {
        "entity_type": "SystemicTreatment",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[provide date]", "entity_type": "SystemicTreatment", "field_name": "endDateSystemicTreatment"},
            {"template_placeholder": "[provide number]", "entity_type": "SystemicTreatment", "field_name": "numberOfCycles/Administrations"},
            {"template_placeholder": "[select reason]", "entity_type": "SystemicTreatment", "field_name": "reasonForEndOfTreatment"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "SystemicTreatment", "field_name": "setting"}
        ]
    },
    "occurrence_cancer-int": {
        "entity_type": "Patient.previousMalignantCancerSite",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "previousMalignantCancerSite"}
        ]
    },
    "surgical-specimen-grading-int": {
        "entity_type": "Surgery.surgicalSpecimenGradingOnlyInUntreatedTumours",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[grade or description]", "entity_type": "Surgery", "field_name": "surgicalSpecimenGradingOnlyInUntreatedTumours"}
        ]
    },
    "recur_or_prog-int": {
        "entity_type": "EpisodeEvent",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "EpisodeEvent", "field_name": "diseaseStatus"},
            {"template_placeholder": "[date]", "entity_type": "EpisodeEvent", "field_name": "dateOfEpisode"}
        ]
    },
    "surgical-mitotic-count-int": {
        "entity_type": "Surgery.surgicalSpecimenMitoticCount",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "surgicalSpecimenMitoticCount"}
        ]
    },
}

# Mappings for MSCI prompts (string-only ones)
MSCI_ENTITY_MAPPINGS = {
    "stage_at_diagnosis": {
        "entity_type": "ClinicalStage",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "ClinicalStage", "field_name": "clinicalStaging"}
        ]
    },
    "chemotherapy_start": {
        "entity_type": "SystemicTreatment",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select intent]", "entity_type": "SystemicTreatment", "field_name": "intent"},
            {"template_placeholder": "[provide date]", "entity_type": "SystemicTreatment", "field_name": "startDateSystemicTreatment"},
            {"template_placeholder": "[select regimen]", "entity_type": "SystemicTreatment", "field_name": "regimen"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "SystemicTreatment", "field_name": "setting"}
        ]
    },
    "chemotherapy_end": {
        "entity_type": "SystemicTreatment",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[provide date]", "entity_type": "SystemicTreatment", "field_name": "endDateSystemicTreatment"},
            {"template_placeholder": "[provide number]", "entity_type": "SystemicTreatment", "field_name": "numberOfCycles/Administrations"},
            {"template_placeholder": "[select reason]", "entity_type": "SystemicTreatment", "field_name": "reasonForEndOfTreatment"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "SystemicTreatment", "field_name": "setting"}
        ]
    },
    "radiotherapy_start": {
        "entity_type": "Radiotherapy",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select intention]", "entity_type": "Radiotherapy", "field_name": "intent"},
            {"template_placeholder": "[please select where]", "entity_type": "Radiotherapy", "field_name": "radiotherapyHospital"},
            {"template_placeholder": "[put date]", "entity_type": "Radiotherapy", "field_name": "startDate"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "Radiotherapy", "field_name": "setting"}
        ]
    },
    "radiotherapy_end": {
        "entity_type": "Radiotherapy",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[put total dose]", "entity_type": "Radiotherapy", "field_name": "totalDoseGy"},
            {"template_placeholder": "[put number of]", "entity_type": "Radiotherapy", "field_name": "numberOfFractions"},
            {"template_placeholder": "[put date]", "entity_type": "Radiotherapy", "field_name": "endDate"},
            {"template_placeholder": "[select reason]", "entity_type": "Radiotherapy", "field_name": "rtTreatmentCompletedAsPlanned?"}
        ]
    },
    "surgerytype": {
        "entity_type": "Surgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "Surgery", "field_name": "surgeryType"},
            {"template_placeholder": "DD/MM/YYYY", "entity_type": "Surgery", "field_name": "dateOfSurgery"},
            {"template_placeholder": "[complete/incomplete]", "entity_type": "Surgery", "field_name": "marginsAfterSurgery"}
        ]
    },
    "biopsygrading": {
        "entity_type": "Diagnosis.biopsyGrading",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "grading"}
        ]
    },
    "histological": {
        "entity_type": "Diagnosis.histologySubgroup",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "histologySubgroup"}
        ]
    },
    "tumorsite": {
        "entity_type": "Diagnosis.subsite",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "subsite"}
        ]
    },
    "tumordiameter": {
        "entity_type": "Diagnosis.tumorSize",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "tumorSize"},
            {"template_placeholder": "[date]", "entity_type": "Diagnosis", "field_name": "dateOfDiagnosis"}
        ]
    },
    "tumorbiopsytype": {
        "entity_type": "Diagnosis",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[biopsy type]", "entity_type": "Diagnosis", "field_name": "typeOfBiopsy"},
            {"template_placeholder": "[date]", "entity_type": "Diagnosis", "field_name": "dateOfDiagnosis"},
            {"template_placeholder": "[place]", "entity_type": "Diagnosis", "field_name": "biopsyDoneBy"}
        ]
    },
    "surgerymargins": {
        "entity_type": "Surgery.marginsAfterSurgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "marginsAfterSurgery"}
        ]
    },
    "necrosis_in_surgical": {
        "entity_type": "Surgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "surgicalSpecimenGradingOnlyInUntreatedTumours"}
        ]
    },
    "necrosis_in_biopsy": {
        "entity_type": "Diagnosis",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "biopsyGrading"}
        ]
    },
    "recurrencetype": {
        "entity_type": "DiseaseExtent",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[selected type]", "entity_type": "DiseaseExtent", "field_name": "localised"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "EpisodeEvent", "field_name": "diseaseStatus"}
        ]
    },
    "recur_or_prog": {
        "entity_type": "EpisodeEvent",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "EpisodeEvent", "field_name": "diseaseStatus"},
            {"template_placeholder": "[date]", "entity_type": "EpisodeEvent", "field_name": "dateOfEpisode"}
        ]
    },
    "gender": {
        "entity_type": "Patient.sex",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[male/female/unknown]", "entity_type": "Patient", "field_name": "sex"}
        ]
    },
    "ageatdiagnosis": {
        "entity_type": "Diagnosis.ageAtDiagnosis",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "ageAtDiagnosis"}
        ]
    },
    "biopsymitoticcount": {
        "entity_type": "Diagnosis",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "biopsyMitoticCount"}
        ]
    },
    "previous_cancer_treatment": {
        "entity_type": "Patient",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select one option]", "entity_type": "Patient", "field_name": "previousCancerTreatment"}
        ]
    },
    "occurrence_cancer": {
        "entity_type": "Patient.previousMalignantCancerSite",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "previousMalignantCancerSite"}
        ]
    },
    "patient-status": {
        "entity_type": "PatientFollowUp.statusAtLastFollowUp",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "PatientFollowUp", "field_name": "statusAtLastFollowUp"}
        ]
    },
    "patient-bmi": {
        "entity_type": "Patient",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "bmi"},
            {"template_placeholder": "[DD/MM/YYYY]", "entity_type": "Patient", "field_name": "bmiDate"}
        ]
    },
    "patient-weightheight": {
        "entity_type": "Patient",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[put weight]", "entity_type": "Patient", "field_name": "weight"},
            {"template_placeholder": "[put height]", "entity_type": "Patient", "field_name": "height"},
            {"template_placeholder": "[put date]", "entity_type": "Patient", "field_name": "weightHeightDate"}
        ]
    },
    "last_contact_date": {
        "entity_type": "PatientFollowUp.lastContact",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[date]", "entity_type": "PatientFollowUp", "field_name": "lastContact"}
        ]
    },
}

# Mappings for VGR prompts (string-only ones)
VGR_ENTITY_MAPPINGS = {
    "stage_at_diagnosis": {
        "entity_type": "ClinicalStage",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "ClinicalStage", "field_name": "clinicalStaging"}
        ]
    },
    "chemotherapy_start": {
        "entity_type": "SystemicTreatment",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select intent]", "entity_type": "SystemicTreatment", "field_name": "intent"},
            {"template_placeholder": "[provide date]", "entity_type": "SystemicTreatment", "field_name": "startDateSystemicTreatment"},
            {"template_placeholder": "[select regimen]", "entity_type": "SystemicTreatment", "field_name": "regimen"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "SystemicTreatment", "field_name": "setting"}
        ]
    },
    "chemotherapy_end": {
        "entity_type": "SystemicTreatment",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[provide date]", "entity_type": "SystemicTreatment", "field_name": "endDateSystemicTreatment"},
            {"template_placeholder": "[provide number]", "entity_type": "SystemicTreatment", "field_name": "numberOfCycles/Administrations"},
            {"template_placeholder": "[select reason]", "entity_type": "SystemicTreatment", "field_name": "reasonForEndOfTreatment"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "SystemicTreatment", "field_name": "setting"}
        ]
    },
    "radiotherapy_start": {
        "entity_type": "Radiotherapy",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select intention]", "entity_type": "Radiotherapy", "field_name": "intent"},
            {"template_placeholder": "[please select where]", "entity_type": "Radiotherapy", "field_name": "radiotherapyHospital"},
            {"template_placeholder": "[put date]", "entity_type": "Radiotherapy", "field_name": "startDate"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "Radiotherapy", "field_name": "setting"}
        ]
    },
    "radiotherapy_end": {
        "entity_type": "Radiotherapy",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[put total dose]", "entity_type": "Radiotherapy", "field_name": "totalDoseGy"},
            {"template_placeholder": "[put number of]", "entity_type": "Radiotherapy", "field_name": "numberOfFractions"},
            {"template_placeholder": "[put date]", "entity_type": "Radiotherapy", "field_name": "endDate"},
            {"template_placeholder": "[select reason]", "entity_type": "Radiotherapy", "field_name": "rtTreatmentCompletedAsPlanned?"}
        ]
    },
    "surgerytype": {
        "entity_type": "Surgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "Surgery", "field_name": "surgeryType"},
            {"template_placeholder": "DD/MM/YYYY", "entity_type": "Surgery", "field_name": "dateOfSurgery"},
            {"template_placeholder": "[complete/incomplete]", "entity_type": "Surgery", "field_name": "marginsAfterSurgery"}
        ]
    },
    "biopsygrading": {
        "entity_type": "Diagnosis.biopsyGrading",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "grading"}
        ]
    },
    "histological": {
        "entity_type": "Diagnosis.histologySubgroup",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "histologySubgroup"}
        ]
    },
    "tumorsite": {
        "entity_type": "Diagnosis.subsite",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "subsite"}
        ]
    },
    "tumordepth": {
        "entity_type": "Diagnosis",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[superficial|deep]", "entity_type": "Diagnosis", "field_name": "deepDepth"}
        ]
    },
    "tumorbiopsytype": {
        "entity_type": "Diagnosis",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[biopsy type]", "entity_type": "Diagnosis", "field_name": "typeOfBiopsy"},
            {"template_placeholder": "[date]", "entity_type": "Diagnosis", "field_name": "dateOfDiagnosis"},
            {"template_placeholder": "[place]", "entity_type": "Diagnosis", "field_name": "biopsyDoneBy"}
        ]
    },
    "surgerymargins": {
        "entity_type": "Surgery.marginsAfterSurgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "marginsAfterSurgery"}
        ]
    },
    "surgical-specimen-grading": {
        "entity_type": "Surgery.surgicalSpecimenGradingOnlyInUntreatedTumours",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[grade or description]", "entity_type": "Surgery", "field_name": "surgicalSpecimenGradingOnlyInUntreatedTumours"}
        ]
    },
    "recurrencetype": {
        "entity_type": "DiseaseExtent",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[selected type]", "entity_type": "DiseaseExtent", "field_name": "localised"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "EpisodeEvent", "field_name": "diseaseStatus"}
        ]
    },
    "recur_or_prog": {
        "entity_type": "EpisodeEvent",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "EpisodeEvent", "field_name": "diseaseStatus"},
            {"template_placeholder": "[date]", "entity_type": "EpisodeEvent", "field_name": "dateOfEpisode"}
        ]
    },
    "patient-status": {
        "entity_type": "PatientFollowUp.statusAtLastFollowUp",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "PatientFollowUp", "field_name": "statusAtLastFollowUp"}
        ]
    },
    "previous_cancer_treatment": {
        "entity_type": "Patient",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[select one option]", "entity_type": "Patient", "field_name": "previousCancerTreatment"}
        ]
    },
    "unknown": {
        "entity_type": "Patient.previousMalignantCancerSite",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "previousMalignantCancerSite"}
        ]
    },
    "tumorrupture": {
        "entity_type": "Surgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "Surgery", "field_name": "tumorRupture"}
        ]
    },
    "other-systemic-therapy": {
        "entity_type": "SystemicTreatment",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "SystemicTreatment", "field_name": "typeOfSystemicTreatment"}
        ]
    },
    "reexcision": {
        "entity_type": "Surgery",
        "fact_trigger": None,
        "field_mappings": [
            {"template_placeholder": "[provide date]", "entity_type": "Surgery", "field_name": "dateOfSurgery"},
            {"template_placeholder": "[FULL_ANNOTATION]", "entity_type": "Surgery", "field_name": "surgeryType", "hardcoded_value": "4315400"},
            {"template_placeholder": "[complete/incomplete]", "entity_type": "Surgery", "field_name": "marginsAfterSurgery"}
        ]
    },
}


# ============================================================
# Reasoning block used in all templates
# ============================================================
REASONING_BLOCK = """# Reasoning Requirements (Traceability)
For every entity extracted, you MUST follow this internal logic:
1. **Evidence**: Locate the exact literal phrase or sentence from the note.
2. **Clinical Validation**: Determine if the finding is current, a past medical history (PMH), or a suspicion.
3. **Inference**: Explain the logic used to map the natural language to the standard value (e.g., mapping "Ductal" to "Infiltrating duct carcinoma").
Generate the response in a structured JSON format. Ensure the `reasoning` and `evidence` fields are populated BEFORE the final values to ensure high-fidelity deduction."""

EXAMPLES_BLOCK = """---

Here are few examples for your understanding:
{few_shot_examples}

---

Now process the following note in the same way:

### Input:
- Medical Note: "{{note_original_text}}"

### Response:
Annotation: {{annotation}}"""


def make_new_prompt_template(task_description):
    """Build a full prompt template from a task description string."""
    return f"""{task_description}
{REASONING_BLOCK}

{EXAMPLES_BLOCK}"""


# ============================================================
# NEW PROMPTS for uncovered data model variables (INT section)
# ============================================================

NEW_INT_PROMPTS = {
    "race-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the patient's race or ethnicity.

Output strictly in the following format:
Patient's race: [value].

The values can be from the following options: White, Black or African American, Asian, American Indian or Alaska Native, Native Hawaiian or Other Pacific Islander, Other, Unknown.

If the race or ethnicity is not explicitly stated or unclear, output: "Patient's race: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "race"}
            ]
        }
    },
    "birthyear-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the patient's birth year.

Output strictly in the following format:
Patient's birth year: [value].

The value should be a four-digit year (e.g., 1965).

If the birth year is not explicitly stated or cannot be determined, output: "Patient's birth year: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "birthYear"}
            ]
        }
    },
    "smoking-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the patient's smoking status.

Output strictly in the following format:
Patient's smoking status: [value].

The values can be from the following options: Current smoker, Former smoker (>1yr), Former smoker (<1yr), Never smoked, Unknown.

If the smoking status is not explicitly stated or unclear, output: "Patient's smoking status: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "smoking"}
            ]
        }
    },
    "cigarettespackyears-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the patient's cigarette pack-years smoked during life.

Output strictly in the following format:
Cigarettes pack-years: [value].

The value should be a numeric value representing pack-years (e.g., 20, 35.5).

If the pack-years information is not explicitly stated or unclear, output: "Cigarettes pack-years: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "cigarettesPackYearsSmokedDuringLife"}
            ]
        }
    },
    "alcohol-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the patient's alcohol consumption status.

Output strictly in the following format:
Patient's alcohol status: [value].

The values can be from the following options: Active drinker, Former drinker, Never drinker, Unknown.

If the alcohol status is not explicitly stated or unclear, output: "Patient's alcohol status: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "alcohol"}
            ]
        }
    },
    "bmi-int": {
        "template": make_new_prompt_template(
            """Task: You are a clinical information extraction assistant specialized in structured oncology metadata.

From the medical note provided, extract the Patient's BMI, weight, and height.

Guidelines:
The annotation must follow this exact format:
Patient's BMI: [bmi_value], Weight: [weight]kg, Height: [height]cm.

Extract BMI values expressed as: "BMI", "BMI: 23.8", "BMI 24.7", "BMI 23.8 kg/m2".
European commas (23,8) must be converted to decimal dots (23.8).
Extract weight in kilograms and height in centimeters.

If BMI is not mentioned but weight and height are, calculate BMI = weight(kg) / height(m)^2.
If any value is not available, use "Unknown" for that field.

If none of the values are mentioned, output: "Patient's BMI/weight/height unknown."

Produce only one final annotation, no explanations."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[bmi_value]", "entity_type": "Patient", "field_name": "bmi"},
                {"template_placeholder": "[weight]", "entity_type": "Patient", "field_name": "weight"},
                {"template_placeholder": "[height]", "entity_type": "Patient", "field_name": "height"}
            ]
        }
    },
    "charlsoncomorbidity-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the Charlson Comorbidity Index score.

Output strictly in the following format:
Charlson Comorbidity Index: [value].

The value should be a numeric score (e.g., 0, 1, 2, 3, etc.).

If the Charlson Comorbidity Index is not explicitly stated or unclear, output: "Charlson Comorbidity Index: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "charlsonComorbidityIndex"}
            ]
        }
    },
    "ecogps-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the ECOG Performance Status at diagnosis.

Output strictly in the following format:
ECOG Performance Status: [value].

The values can be from the following options: 0, 1, 2, 3, 4, Unknown.

ECOG Performance Status scale:
- 0: Fully active, able to carry on all pre-disease performance without restriction
- 1: Restricted in physically strenuous activity but ambulatory
- 2: Ambulatory and capable of all selfcare but unable to carry out any work activities
- 3: Capable of only limited selfcare, confined to bed or chair more than 50% of waking hours
- 4: Completely disabled, totally confined to bed or chair

If the ECOG PS is not explicitly stated or unclear, output: "ECOG Performance Status: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "easternCooperativeOncologyGroupPerformanceStatusAtDiagnosis"}
            ]
        }
    },
    "karnofsyindex-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the Karnofsky Performance Index at diagnosis.

Output strictly in the following format:
Karnofsky Performance Index: [value].

The value should be a numeric score between 0 and 100, in increments of 10 (e.g., 0, 10, 20, ..., 90, 100).

Karnofsky scale reference:
- 100: Normal, no complaints, no evidence of disease
- 90: Able to carry on normal activity; minor signs or symptoms of disease
- 80: Normal activity with effort; some signs or symptoms of disease
- 70: Cares for self; unable to carry on normal activity or do active work
- 60: Requires occasional assistance but is able to care for most needs
- 50: Requires considerable assistance and frequent medical care
- 40: Disabled; requires special care and assistance
- 30: Severely disabled; hospitalization indicated, death not imminent
- 20: Very sick; active supportive treatment necessary
- 10: Moribund; fatal processes progressing rapidly
- 0: Dead

If the Karnofsky index is not explicitly stated or unclear, output: "Karnofsky Performance Index: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "karnofsyIndexAtDiagnosis"}
            ]
        }
    },
    "geneticsyndrome-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract any genetic syndrome associated with the patient's condition.

Output strictly in the following format:
Genetic syndrome: [value].

The values can be from the following options: No Genetic syndrome, Olliers disease, Maffuci syndrome, Li-Fraumeni syndrome, McCune-Albright syndrome, Multiple osteochondromas, Neurofibromatosis type 1, Rothmund-Thomson syndrome, Werner syndrome, Retinoblastoma, Paget disease, Other.

If no genetic syndrome is mentioned, output: "Genetic syndrome: No Genetic syndrome."
If the genetic syndrome status is unclear, output: "Genetic syndrome: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Patient",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Patient", "field_name": "geneticSyndrome"}
            ]
        }
    },
    "dateofdiagnosis-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the date of diagnosis.

The date of diagnosis refers to the date when the biopsy or surgical specimen confirmed the diagnosis.

Output strictly in the following format:
Date of diagnosis: [DD/MM/YYYY].

The date must be in DD/MM/YYYY format.

If the date is not explicitly stated or unclear, output: "Date of diagnosis: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Diagnosis",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[DD/MM/YYYY]", "entity_type": "Diagnosis", "field_name": "dateOfDiagnosis"}
            ]
        }
    },
    "radiotherapyinducedsarcoma-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and determine if the sarcoma was radiotherapy-induced.

Output strictly in the following format:
Radiotherapy-induced sarcoma: [value].

The values can be from the following options: Yes, No, Unknown.

Consider a sarcoma as radiotherapy-induced if the note mentions that the tumor developed in a previously irradiated field, or explicitly states radiation-induced or post-radiation sarcoma.

If the information is not explicitly stated or unclear, output: "Radiotherapy-induced sarcoma: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Diagnosis",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "radiotherapyInducedSarcoma"}
            ]
        }
    },
    "histologygroup-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the histology group of the tumor.

Output strictly in the following format:
Histology group: [value].

Identify the broader histology group category (e.g., Soft tissue sarcoma, Bone sarcoma, GIST, etc.) based on the histological type mentioned in the note.

If the histology group is not explicitly stated or unclear, output: "Histology group: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Diagnosis",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "histologyGroup"}
            ]
        }
    },
    "tumorsite-category-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the tumor site category.

Output strictly in the following format:
Tumor site category: [value].

The values can be from the following options: Upper and Lower limbs, Trunk wall, Intra abdominal, Genito urinary, Head and neck, Breast, Intra thoracic, Other.

If the tumor site category is not explicitly stated or unclear, output: "Tumor site category: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Diagnosis",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "site"}
            ]
        }
    },
    "diagnosiscode-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the ICD-O-3 topography or diagnosis code.

Output strictly in the following format:
Diagnosis code (ICD-O-3): [value].

The value should be a valid ICD-O-3 code (e.g., C49.1, C40.2, 8890/3).

If the code is not explicitly stated or unclear, output: "Diagnosis code (ICD-O-3): Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Diagnosis",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "diagnosisCode"}
            ]
        }
    },
    "superficialdepth-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and determine if the tumor has superficial depth.

Output strictly in the following format:
Superficial depth: [value].

The values can be from the following options: Yes, No, Unknown.

A tumor is superficial if it is located entirely above the superficial fascia without invasion of the fascia. A tumor is deep if it is located beneath the superficial fascia, or invades the fascia, or is both superficial and deep.

If the information is not explicitly stated or unclear, output: "Superficial depth: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Diagnosis",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "superficialDepth"}
            ]
        }
    },
    "mitoticindex-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the mitotic index value.

Output strictly in the following format:
Mitotic index: [value].

The value should be a numeric count (e.g., 5/10 HPF, 12/50 HPF, 3 mitoses per 10 HPF).

If the mitotic index is not explicitly stated or unclear, output: "Mitotic index: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Diagnosis",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "mitoticIndex"}
            ]
        }
    },
    "hpvstatus-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the HPV (Human Papillomavirus) status.

Output strictly in the following format:
HPV status: [value].

The values can be from the following options: Positive, Negative, Not tested, Unknown.

Consider HPV status as mentioned in pathology reports, p16 immunohistochemistry results (p16 positive is often a surrogate for HPV positive), or direct HPV testing results.

If the HPV status is not explicitly stated or unclear, output: "HPV status: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Diagnosis",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Diagnosis", "field_name": "hpvStatus"}
            ]
        }
    },
    "clinicalstaging-tnm-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the clinical TNM staging (cT, cN, cM).

Output strictly in the following format:
Clinical TNM staging: cT[t_value] cN[n_value] cM[m_value].

Examples of valid values:
- cT: cT1, cT2, cT3, cT4, cTx, cT1a, cT1b, cT2a, cT2b, cT3a, cT3b, cT4a, cT4b
- cN: cN0, cN1, cN2, cNx, cN1a, cN1b, cN2a, cN2b, cN2c, cN3
- cM: cM0, cM1, cMx, cM1a, cM1b

If any component is not explicitly stated, use "x" for that component (e.g., cTx, cNx, cMx).
If no clinical staging information is found, output: "Clinical TNM staging: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "ClinicalStage",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[t_value]", "entity_type": "ClinicalStage", "field_name": "ct"},
                {"template_placeholder": "[n_value]", "entity_type": "ClinicalStage", "field_name": "cn"},
                {"template_placeholder": "[m_value]", "entity_type": "ClinicalStage", "field_name": "cm"}
            ]
        }
    },
    "pathologicalstaging-tnm-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the pathological TNM staging (pT, pN, pM).

Output strictly in the following format:
Pathological TNM staging: pT[t_value] pN[n_value] pM[m_value].

Examples of valid values:
- pT: pT1, pT2, pT3, pT4, pTx, pT1a, pT1b, pT2a, pT2b, pT3a, pT3b, pT4a, pT4b
- pN: pN0, pN1, pN2, pNx, pN1a, pN1b, pN2a, pN2b, pN2c, pN3
- pM: pM0, pM1, pMx, pM1a, pM1b

If any component is not explicitly stated, use "x" for that component (e.g., pTx, pNx, pMx).
If no pathological staging information is found, output: "Pathological TNM staging: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "PathologicalStage",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[t_value]", "entity_type": "PathologicalStage", "field_name": "pt"},
                {"template_placeholder": "[n_value]", "entity_type": "PathologicalStage", "field_name": "pn"},
                {"template_placeholder": "[m_value]", "entity_type": "PathologicalStage", "field_name": "pm"}
            ]
        }
    },
    "pathologicalstaging-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the overall pathological stage.

Output strictly in the following format:
Pathological stage: [value].

The value should be a standard pathological stage designation (e.g., Stage I, Stage IA, Stage IB, Stage II, Stage IIA, Stage IIB, Stage III, Stage IIIA, Stage IIIB, Stage IV, Stage IVA, Stage IVB).

If the pathological stage is not explicitly stated or unclear, output: "Pathological stage: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "PathologicalStage",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "PathologicalStage", "field_name": "pathologicalStaging"}
            ]
        }
    },
    "sentinelnode-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the sentinel node biopsy result.

Output strictly in the following format:
Sentinel node: [value].

The values can be from the following options: Positive, Negative, Not done, Unknown.

If the sentinel node information is not explicitly stated or unclear, output: "Sentinel node: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "PathologicalStage",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "PathologicalStage", "field_name": "sentinelNode"}
            ]
        }
    },
    "surgeryintention-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the surgery intention.

Output strictly in the following format:
Surgery intention: [value].

The values can be from the following options: Primary treatment, Treatment of recurrence, Other.

If the surgery intention is not explicitly stated or unclear, output: "Surgery intention: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Surgery",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "surgeryIntention"}
            ]
        }
    },
    "tumorrupture-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and determine if the tumor ruptured during surgery.

Output strictly in the following format:
Tumor rupture: [value].

The values can be from the following options: Yes, No, Unknown.

If the tumor rupture information is not explicitly stated or unclear, output: "Tumor rupture: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Surgery",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "tumorRupture"}
            ]
        }
    },
    "surgicalcomplications-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract surgical complications using the Clavien-Dindo Classification.

Output strictly in the following format:
Surgical complications: [value].

The values can be from the following options: Grade I, Grade II, Grade III, Grade IV, Grade V, No complications.

Clavien-Dindo Classification reference:
- Grade I: Any deviation from the normal postoperative course without pharmacological treatment or interventions
- Grade II: Requiring pharmacological treatment (e.g., blood transfusions, total parenteral nutrition)
- Grade III: Requiring surgical, endoscopic, or radiological intervention
- Grade IV: Life-threatening complication requiring ICU management
- Grade V: Death of a patient

If no complications are mentioned, output: "Surgical complications: No complications."
If the information is unclear, output: "Surgical complications: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Surgery",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "surgicalComplications"}
            ]
        }
    },
    "necksurgery-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and determine if neck surgery or neck dissection was performed.

Output strictly in the following format:
Neck surgery: [value].

The values can be from the following options: Yes, No, Unknown.

Consider any mention of neck dissection (radical, modified radical, selective), cervical lymphadenectomy, or neck surgery as positive.

If the neck surgery information is not explicitly stated or unclear, output: "Neck surgery: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Surgery",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Surgery", "field_name": "neckSurgery"}
            ]
        }
    },
    "overalltreatmentresponse-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the overall treatment response.

Output strictly in the following format:
Overall treatment response: [value].

The values can be from the following options: Complete response, Partial response, Stable disease, Progression of disease, Not evaluable.

If the overall treatment response is not explicitly stated or unclear, output: "Overall treatment response: Not evaluable."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "OverallTreatmentResponse",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "OverallTreatmentResponse", "field_name": "overallTreatmentResponse"}
            ]
        }
    },
    "adverseevent-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract adverse events related to treatment.

Output strictly in the following format:
Adverse event: [CTCAE term], Start date: [DD/MM/YYYY], Duration: [value].

Guidelines:
- Use CTCAE (Common Terminology Criteria for Adverse Events) terms when possible.
- Extract the start date of the adverse event in DD/MM/YYYY format.
- Extract the duration if mentioned (e.g., "2 weeks", "3 days", "ongoing").
- If multiple adverse events are present, list each on a separate line.

If no adverse events are mentioned, output: "No adverse events reported."
If the information is unclear, output: "Adverse events: Unknown."

Do not include any explanations, reasoning, extra text beyond the annotation format."""
        ),
        "entity_mapping": {
            "entity_type": "AdverseEvent",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[CTCAE term]", "entity_type": "AdverseEvent", "field_name": "ctcaeTerm"},
                {"template_placeholder": "[DD/MM/YYYY]", "entity_type": "AdverseEvent", "field_name": "startDate"},
                {"template_placeholder": "[value]", "entity_type": "AdverseEvent", "field_name": "duration"}
            ]
        }
    },
    "cancerstartdate-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the cancer start date.

The cancer start date refers to the date when the cancer episode began, which may be the date of first symptoms, first diagnostic imaging, or the date of biopsy.

Output strictly in the following format:
Cancer start date: [DD/MM/YYYY].

The date must be in DD/MM/YYYY format.

If the cancer start date is not explicitly stated or unclear, output: "Cancer start date: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "CancerEpisode",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[DD/MM/YYYY]", "entity_type": "CancerEpisode", "field_name": "cancerStartDate"}
            ]
        }
    },
    "lastcontactdate-int": {
        "template": make_new_prompt_template(
            """Task: You are an expert medical annotator specializing in oncology pathology. Your task is to extract the last contact date from the provided medical note and output it in a precise, templated format.

Output Format:
Last contact date with the patient: [date].

The date must be DD/MM/YYYY format only. Output "Unknown" if date is not found or you are unsure instead of outputting any random date. Do not include explanations, reasoning, or any extra text -- only one final annotation line exactly as specified below."""
        ),
        "entity_mapping": {
            "entity_type": "PatientFollowUp",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[date]", "entity_type": "PatientFollowUp", "field_name": "lastContact"}
            ]
        }
    },
    "followupdate-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the patient follow-up date.

Output strictly in the following format:
Patient follow-up date: [DD/MM/YYYY].

The date must be in DD/MM/YYYY format.

If the follow-up date is not explicitly stated or unclear, output: "Patient follow-up date: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "PatientFollowUp",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[DD/MM/YYYY]", "entity_type": "PatientFollowUp", "field_name": "patientFollowUpDate"}
            ]
        }
    },
    "diseasestatus-followup-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the status of disease at last follow-up.

Output strictly in the following format:
Status of disease at last follow-up: [value].

The values can be from the following options: No Evidence of Disease (NED), Alive With Disease (AWD), Dead of Disease (DOD), Dead of Other Causes (DOC), Unknown.

If the disease status at last follow-up is not explicitly stated or unclear, output: "Status of disease at last follow-up: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "PatientFollowUp",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "PatientFollowUp", "field_name": "statusOfDiseaseAtLastFollowUp"}
            ]
        }
    },
    "radiotherapy-treatment-response-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the radiotherapy treatment response.

Output strictly in the following format:
Radiotherapy treatment response: [value].

The values can be from the following options: Complete response, Partial response, Stable disease, Progression, Not evaluable.

If the radiotherapy treatment response is not explicitly stated or unclear, output: "Radiotherapy treatment response: Not evaluable."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "Radiotherapy",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "Radiotherapy", "field_name": "treatmentResponse"}
            ]
        }
    },
    "systemic-treatment-type-int": {
        "template": make_new_prompt_template(
            """Task: You are a medical text annotation assistant.
Your task is to read a given medical note and extract the type of systemic treatment administered.

Output strictly in the following format:
Type of systemic treatment: [value].

The values can be from the following options: Chemotherapy, Immunotherapy, Targeted therapy, Hormone therapy, Other.

If multiple types are mentioned, list them separated by commas (e.g., "Chemotherapy, Immunotherapy").

If the type of systemic treatment is not explicitly stated or unclear, output: "Type of systemic treatment: Unknown."

Do not include any explanations, reasoning, extra text, the medical note -- only output the annotation value in the specified format above."""
        ),
        "entity_mapping": {
            "entity_type": "SystemicTreatment",
            "fact_trigger": None,
            "field_mappings": [
                {"template_placeholder": "[value]", "entity_type": "SystemicTreatment", "field_name": "typeOfSystemicTreatment"}
            ]
        }
    },
}


def convert_string_prompt(template_str, entity_mapping):
    """Convert a string prompt to {template, entity_mapping} format."""
    return {
        "template": template_str,
        "entity_mapping": entity_mapping
    }


def process_section(section_data, entity_mappings):
    """Process a section: convert string prompts to objects, keep existing objects."""
    result = {}
    for key, value in section_data.items():
        if isinstance(value, str):
            # String-only prompt -> convert to object
            if key in entity_mappings:
                result[key] = convert_string_prompt(value, entity_mappings[key])
            else:
                # No mapping defined: still convert to object with null entity_mapping
                result[key] = {
                    "template": value,
                    "entity_mapping": None
                }
        elif isinstance(value, dict):
            # Already an object with template + entity_mapping
            result[key] = copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def main():
    # 1. Read existing prompts.json
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = {}

    # 2. Process INT section
    int_section = data.get("INT", {})
    result["INT"] = process_section(int_section, INT_ENTITY_MAPPINGS)

    # 3. Add NEW prompts to INT section
    for key, value in NEW_INT_PROMPTS.items():
        if key not in result["INT"]:
            result["INT"][key] = value

    # 4. Process MSCI section
    msci_section = data.get("MSCI", {})
    result["MSCI"] = process_section(msci_section, MSCI_ENTITY_MAPPINGS)

    # 5. Process VGR section
    vgr_section = data.get("VGR", {})
    result["VGR"] = process_section(vgr_section, VGR_ENTITY_MAPPINGS)

    # 6. Copy any other sections unchanged
    for key in data:
        if key not in result:
            result[key] = copy.deepcopy(data[key])

    # 7. Write the result
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Print summary
    for section in ["INT", "MSCI", "VGR"]:
        if section in result:
            total = len(result[section])
            obj_count = sum(1 for v in result[section].values() if isinstance(v, dict) and "template" in v)
            str_count = sum(1 for v in result[section].values() if isinstance(v, str))
            print(f"{section}: {total} prompts total, {obj_count} with template+entity_mapping, {str_count} still string-only")

    print(f"\nOutput written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
