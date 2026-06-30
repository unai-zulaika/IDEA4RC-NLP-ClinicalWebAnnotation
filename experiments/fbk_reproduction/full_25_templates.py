"""FBK-style strict-format templates for all 25 MSCI variables.

Each template:
  - one-sentence task description (FBK slide 11 style)
  - exact output format (taken from FBK slide 10 where shown; otherwise inferred
    from gold examples in the session)
  - Unknown-fallback string (so the model can abstain)
  - annotation_prefix used to pull few-shot pool from FBK CSV
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VarSpec:
    name: str                       # short id used in scripts
    session_key: str                # prompt_type in our session JSON
    task: str                       # 1-line task description
    output_format: str              # exact format string
    unknown_fallback: str           # output when not present
    pool_prefixes: tuple[str, ...]  # annotation-text prefixes to match in FBK CSV


VARIABLES: dict[str, VarSpec] = {
    # ---- variables FBK explicitly showed templates for (slide 10/11) ----
    "biopsy_mitotic_count": VarSpec(
        "biopsy_mitotic_count",
        "biopsymitoticcount-msci",
        "Identify the biopsy mitotic count from the medical note.",
        "Biopsy mitotic count: [value]HPF/mm2.",
        "Unknown biopsy mitotic count.",
        ("Biopsy mitotic count:", "Surgical specimen mitotic count:"),
    ),
    "histological": VarSpec(
        "histological",
        "histological-msci",
        "Identify the histological type from the medical note.",
        "Histological type: [type] ([ICD-O-3 code]).",
        "Unknown histological type.",
        ("Histological type:",),
    ),
    "necrosis_in_surgical": VarSpec(
        "necrosis_in_surgical",
        "necrosis_in_surgical-msci",
        "Identify whether necrosis is present in the surgical specimen.",
        "Necrosis in surgical specimen (type of): [absent | present | unknown].",
        "Unknown necrosis in surgical specimen.",
        ("Necrosis in surgical",),
    ),
    "necrosis_in_biopsy": VarSpec(
        "necrosis_in_biopsy",
        "necrosis_in_biopsy-msci",
        "Identify whether necrosis is present in the biopsy specimen.",
        "Necrosis in biopsy specimen (type of): [absent | present | unknown].",
        "Unknown necrosis in biopsy specimen.",
        ("Necrosis in biopsy",),
    ),
    "surgerytype": VarSpec(
        "surgerytype",
        "surgerytype-msci",
        "Identify the surgery type and result from the medical note.",
        "[Primary | Re-excision] surgery was performed on DD/MM/YYYY and was macroscopically [complete | incomplete].",
        "Unknown surgery type.",
        ("Primary surgery was", "Re-excision was", "Surgery was performed", "Re-excision performed"),
    ),
    "tumordiameter": VarSpec(
        "tumordiameter",
        "tumordiameter-msci",
        "Identify the tumor's longest diameter and the date of initial imaging.",
        "Tumor longest diameter: [value]mm (at initial imaging on DD/MM/YYYY).",
        "Unknown tumor diameter.",
        ("Tumor longest diameter:",),
    ),
    "previous_cancer_treatment": VarSpec(
        "previous_cancer_treatment",
        "previous_cancer_treatment-msci",
        "Identify what previous cancer treatment(s) the patient received.",
        "Previous cancer treatment: [surgery | radiation | chemotherapy | comma-separated list].",
        "Not applicable",
        ("Previous cancer treatment:",),
    ),
    # ---- the remaining 19 variables (templates inferred from gold examples) ----
    "stage_at_diagnosis": VarSpec(
        "stage_at_diagnosis",
        "stage_at_diagnosis-msci",
        "Identify the stage of disease at diagnosis from the medical note.",
        "Stage at diagnosis: [localized | locally advanced | distant metastases (specify)].",
        "Unknown stage at diagnosis.",
        ("Stage at diagnosis:",),
    ),
    "ageatdiagnosis": VarSpec(
        "ageatdiagnosis",
        "ageatdiagnosis-msci",
        "Identify the patient's age at diagnosis from the medical note.",
        "Age at diagnosis [N] years.",
        "Unknown age at diagnosis.",
        ("Age at diagnosis",),
    ),
    "patient-status": VarSpec(
        "patient-status",
        "patient-status-msci",
        "Identify the patient's status at last follow-up.",
        "Status of the patient at last follow-up: [Alive, No Evidence of Disease (NED) | Alive With Disease (AWD) - [details] | Deceased | Lost to follow-up].",
        "Unknown patient status.",
        ("Status of the patient at last follow-up", "Patient has been lost to follow-up"),
    ),
    "occurrence_cancer": VarSpec(
        "occurrence_cancer",
        "occurrence_cancer-msci",
        "Identify whether the patient has had another cancer (other than the index sarcoma).",
        "Occurrence of other cancer [details].",
        "Not applicable",
        ("Occurrence of other cancer",),
    ),
    "recurrencetype": VarSpec(
        "recurrencetype",
        "recurrencetype-msci",
        "Identify the type of recurrence or progression mentioned in the note.",
        "Type of recurrence/progression: [local | regional | distant metastases (specify site)].",
        "There was no progression/recurrence.",
        ("Type of recurrence/progression:", "There was no progression/recurrence."),
    ),
    "gender": VarSpec(
        "gender",
        "gender-msci",
        "Identify the patient's gender from the medical note.",
        "Patient's gender [male | female].",
        "Unknown gender.",
        ("Patient's gender",),
    ),
    "tumorsite": VarSpec(
        "tumorsite",
        "tumorsite-msci",
        "Identify the tumor site / depth from the medical note.",
        "Tumor site: [body part]. (Optionally also: Tumor depth: [superficial | deep].)",
        "Unknown tumor site.",
        ("Tumor site:", "Tumor depth:"),
    ),
    "chemotherapy_start": VarSpec(
        "chemotherapy_start",
        "chemotherapy_start-msci",
        "Identify chemotherapy start information from the medical note.",
        "[pre-operative | post-operative | therapeutic] chemotherapy with [curative | palliative] started on DD/MM/YYYY and utilized [regimen] regimen.",
        "Unknown chemotherapy start.",
        ("pre-operative chemotherapy", "post-operative chemotherapy", "therapeutic chemotherapy"),
    ),
    "recur_or_prog": VarSpec(
        "recur_or_prog",
        "recur_or_prog-msci",
        "Identify whether there is any recurrence or progression in the note.",
        "Recurrence/progression: [yes (specify) | no].",
        "There was no progression/recurrence.",
        ("Recurrence/progression:", "There was no progression/recurrence."),
    ),
    "patient-bmi": VarSpec(
        "patient-bmi",
        "patient-bmi-msci",
        "Identify the patient's BMI and evaluation date.",
        "Patient's BMI [value] (evaluated on DD/MM/YYYY).",
        "Unknown BMI.",
        ("Patient's BMI",),
    ),
    "chemotherapy_end": VarSpec(
        "chemotherapy_end",
        "chemotherapy_end-msci",
        "Identify chemotherapy end information from the medical note.",
        "[pre-operative | post-operative | therapeutic] chemotherapy ended on DD/MM/YYYY after [N] of cycles because of [reason].",
        "Unknown chemotherapy end.",
        ("pre-operative chemotherapy ended", "post-operative chemotherapy ended", "therapeutic chemotherapy ended"),
    ),
    "patient-weightheight": VarSpec(
        "patient-weightheight",
        "patient-weightheight-msci",
        "Identify the patient's weight and height from the medical note.",
        "Patient's weight [N]kg and height [N]cm (evaluated on DD/MM/YYYY).",
        "Unknown weight and height.",
        ("Patient's weight",),
    ),
    "last_contact_date": VarSpec(
        "last_contact_date",
        "last_contact_date-msci",
        "Identify the last contact date with the patient.",
        "Last contact date with the patient: DD/MM/YYYY.",
        "Unknown last contact date.",
        ("Last contact date with the patient:",),
    ),
    "radiotherapy_start": VarSpec(
        "radiotherapy_start",
        "radiotherapy_start-msci",
        "Identify radiotherapy start information.",
        "[pre-operative | post-operative | therapeutic] radiotherapy ([conventional | particle-based]) with [curative | palliative] intention started at the hosptial on DD/MM/YYYY.",
        "Unknown radiotherapy start.",
        ("pre-operative radiotherapy", "post-operative radiotherapy", "therapeutic radiotherapy", "intra-operative radiotherapy"),
    ),
    "biopsygrading": VarSpec(
        "biopsygrading",
        "biopsygrading-msci",
        "Identify biopsy grading (FNCLCC) from the medical note.",
        "Biopsy grading (FNCLCC): [1 | 2 | 3 | Other classification system high | Other classification system low].",
        "Unknown biopsy grading.",
        ("Biopsy grading (FNCLCC):", "Surgical specimen grading"),
    ),
    "tumorbiopsytype": VarSpec(
        "tumorbiopsytype",
        "tumorbiopsytype-msci",
        "Identify the baseline/primary tumor biopsy type, date, and place.",
        "Baseline/primary tumor [biopsy type] biopsy has been performed on DD/MM/YYYY in [place].",
        "Lack of information about biopsy.",
        ("Baseline/primary tumor", "Lack of information about biopsy"),
    ),
    "surgerymargins": VarSpec(
        "surgerymargins",
        "surgerymargins-msci",
        "Identify the surgical resection margin classification.",
        "Margins after surgery: [R0 | R1 | R2].",
        "Unknown surgical margins.",
        ("Margins after surgery:",),
    ),
    "radiotherapy_end": VarSpec(
        "radiotherapy_end",
        "radiotherapy_end-msci",
        "Identify radiotherapy end information.",
        "[pre-operative | post-operative | therapeutic] radiotherapy in total of [N]Gy in [N] fractions ended on DD/MM/YYYY because of [reason].",
        "Unknown radiotherapy end.",
        ("pre-operative radiotherapy in", "post-operative radiotherapy in", "therapeutic radiotherapy in"),
    ),
}


def render(var: VarSpec, note_text: str, few_shots: list[tuple[str, str]]) -> str:
    examples = []
    for i, (note, ann) in enumerate(few_shots, start=1):
        examples.append(
            f"Example {i}:\n"
            f"### Input:\n- Medical Note: \"{note}\"\n"
            f"### Response:\nAnnotation: {ann}"
        )
    ex_block = "\n\n".join(examples) if examples else "(no examples)"
    return (
        f"Task: You are an expert medical annotator specializing in extracting "
        f"structured clinical information from oncology notes. "
        f"{var.task}\n\n"
        f"Format:\n{var.output_format}\n"
        f"(If not explicitly stated or unclear, output: \"{var.unknown_fallback}\")\n\n"
        f"Do not include any explanations, reasoning, extra text, or the medical "
        f"note — only output the annotation value in the specified format above.\n\n"
        f"Here are few examples for your understanding:\n\n{ex_block}\n\n"
        f"Now process the following note in the same way:\n\n"
        f"### Input:\n- Medical Note: \"{note_text}\"\n"
        f"### Response:\nAnnotation:"
    )
