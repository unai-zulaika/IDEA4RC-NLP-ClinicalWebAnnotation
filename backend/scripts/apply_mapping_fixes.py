"""
Apply all mapping fixes based on user review:

1. radiotherapy_end: fix toxicity (4162594→4161588) and intolerance (4240582→4105297) codes in INT/VGR
2. patient-status: add DOD/DOC/DUC/Alive + INT item-8 (with trailing period)
3. recurrencetype:
   - EpisodeEvent.diseaseStatus: add recurrence/progression codes
   - Replace single DiseaseExtent.localised with 14 boolean field_mappings
4. tumorrupture (VGR): add "Tumor ruptured." → true
5. SystemicTreatment.setting / Radiotherapy.setting: add value_code_mappings to [FULL_ANNOTATION] entries
6. stage_at_diagnosis MSCI/VGR (latest+fast) + fast_INT:
   Replace [value]→clinicalStaging with [FULL_ANNOTATION]→boolean fields (INT pattern)
"""
import json, copy
from pathlib import Path

BASE = Path(__file__).parent.parent / "data"


def load(path): return json.load(open(path))
def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Saved {path}")


# ── helpers ────────────────────────────────────────────────────────────────
def get_fm(data, var, placeholder=None, field_name=None):
    """Return list of matching field_mapping entries."""
    fms = data.get(var, {}).get("entity_mapping", {}).get("field_mappings", [])
    return [fm for fm in fms
            if (placeholder is None or fm.get("template_placeholder") == placeholder)
            and (field_name is None or fm.get("field_name") == field_name)]


def set_vcm(data, var, placeholder, field_name, vcm):
    for fm in get_fm(data, var, placeholder=placeholder, field_name=field_name):
        fm["value_code_mappings"] = vcm
        return True
    return False


# ── 1. radiotherapy_end code fixes ─────────────────────────────────────────
RT_END_VCM_INT_VGR = {
    "completion":          "44788181",
    "toxicity":            "4161588",   # was 4162594
    "comorbidity":         "2000100030",
    "patient intolerance": "4105297",   # was 4240582
    "discontinued":        "37017062",
    "death":               "4306655",
}


def fix_radiotherapy_end(data, center):
    # INT/VGR use field_name "rtTreatmentCompletedAsPlanned" or "rtTreatmentCompletedAsPlanned?"
    for fn in ("rtTreatmentCompletedAsPlanned", "rtTreatmentCompletedAsPlanned?"):
        for fm in get_fm(data, "radiotherapy_end", placeholder="[select reason]", field_name=fn):
            if "value_code_mappings" in fm:
                fm["value_code_mappings"] = RT_END_VCM_INT_VGR
                print(f"    [{center}] radiotherapy_end.{fn}: codes updated")


# ── 2. patient-status: add death outcomes ──────────────────────────────────
DEATH_OUTCOMES_INT = {
    "Dead of Disease (DOD)":       "2000100072",
    "Dead of Other Cause (DOC)":   "2000100073",
    "Dead of Unknown Cause (DUC)": "2000100074",
    "Alive":                       "4230556",
    # INT template item 8 (AWD localised tumor with period)
    "Alive With Disease (AWD) - localised tumor.": "2000100075",
}
DEATH_OUTCOMES_VGR = {
    "Dead of Disease (DOD)":       "2000100072",
    "Dead of Other Cause (DOC)":   "2000100073",
    "Dead of Unknown Cause (DUC)": "2000100074",
    "Alive":                       "4230556",
}


def fix_patient_status(data, center, extra):
    for fm in get_fm(data, "patient-status", field_name="statusOfPatientAtLastFollowUp"):
        vcm = fm.setdefault("value_code_mappings", {})
        vcm.update(extra)
        print(f"    [{center}] patient-status: added {len(extra)} death-outcome entries")
        return


# ── 3. recurrencetype ──────────────────────────────────────────────────────
# 3a. EpisodeEvent.diseaseStatus — same as recur_or_prog
DISEASE_STATUS_VCM = {
    "recurrence": "2000100002",
    "progression": "32949",
}

# 3b. 14 DiseaseExtent boolean field_mappings keyed by [selected type] values
#     (only True entries; "local [select site if metastatic]" sub-template → treat as "local")
DISEASE_EXTENT_FIELDS = [
    ("localised", {
        "local": True,
    }),
    ("locoRegional", {}),
    ("isTransitMetastasisWithClinicalConfirmation", {}),
    ("isMultifocalTumor", {}),
    ("regionalNodalMetastases", {}),
    ("softTissue", {
        "metastatic bone, soft tissue": True,
        "metastatic lung, bone, soft tissue": True,
        "metastatic lung, soft tissue": True,
        "metastatic other, soft tissue": True,
        "metastatic soft tissue": True,
        "metastatic soft tissue, lung, other": True,
    }),
    ("distantLymphNode", {}),
    ("lung", {
        "metastatic liver, lung, bone": True,
        "metastatic lung": True,
        "metastatic lung, bone, soft tissue": True,
        "metastatic lung, soft tissue": True,
        "metastatic soft tissue, lung, other": True,
    }),
    ("metastasisatbone", {
        "metastatic bone": True,
        "metastatic bone, soft tissue": True,
        "metastatic liver, lung, bone": True,
        "metastatic lung, bone, soft tissue": True,
    }),
    ("liver", {
        "metastatic liver": True,
        "metastatic liver, lung, bone": True,
    }),
    ("pleura", {}),
    ("peritoneum", {}),
    ("brain", {
        "metastatic brain": True,
    }),
    ("otherViscera", {
        "metastatic other": True,
        "metastatic other, soft tissue": True,
        "metastatic soft tissue, lung, other": True,
    }),
]


def fix_recurrencetype(data, center):
    if "recurrencetype" not in data:
        return
    em = data["recurrencetype"]["entity_mapping"]
    old_fms = em["field_mappings"]

    # Build new field_mappings
    new_fms = []

    # 14 DiseaseExtent boolean fields (all use [selected type] placeholder)
    for field_name, vcm in DISEASE_EXTENT_FIELDS:
        fm = {
            "template_placeholder": "[selected type]",
            "entity_type": "DiseaseExtent",
            "field_name": field_name,
        }
        if vcm:
            fm["value_code_mappings"] = vcm
        new_fms.append(fm)

    # EpisodeEvent.diseaseStatus ([FULL_ANNOTATION])
    new_fms.append({
        "template_placeholder": "[FULL_ANNOTATION]",
        "entity_type": "EpisodeEvent",
        "field_name": "diseaseStatus",
        "value_code_mappings": DISEASE_STATUS_VCM,
    })

    em["field_mappings"] = new_fms
    print(f"    [{center}] recurrencetype: rebuilt field_mappings ({len(new_fms)} entries)")


# ── 4. tumorrupture ────────────────────────────────────────────────────────
def fix_tumorrupture(data, center):
    if "tumorrupture" not in data:
        return
    for fm in get_fm(data, "tumorrupture", placeholder="[FULL_ANNOTATION]", field_name="tumorRupture"):
        fm["value_code_mappings"] = {"Tumor ruptured.": True}
        print(f"    [{center}] tumorrupture.tumorRupture: added mapping")


# ── 5. setting ([FULL_ANNOTATION]) ─────────────────────────────────────────
SETTING_VCM = {
    "pre-operative concomitant to systemic treatment": "2000100031",
    "post-operative concomitant to systemic treatment": "2000100032",
    "definitive concomitant to systemic treatment": "2000100034",
    "pre-operative":  "4059384",
    "post-operative": "4058775",
    "definitive":     "2000100033",
}

SETTING_VARS = ["chemotherapy_start", "chemotherapy_end", "radiotherapy_start"]


def fix_setting(data, center):
    for var in SETTING_VARS:
        if var not in data:
            continue
        for fm in get_fm(data, var, placeholder="[FULL_ANNOTATION]"):
            if fm.get("field_name") == "setting":
                fm["value_code_mappings"] = SETTING_VCM
                print(f"    [{center}] {var}.setting: added setting VCM")


# ── 6. stage_at_diagnosis ──────────────────────────────────────────────────
# INT pattern (same possible answers: localized / loco-regional / metastatic)
STAGE_INT_MSCI_FMS = [
    {
        "template_placeholder": "[FULL_ANNOTATION]",
        "entity_type": "ClinicalStage",
        "field_name": "localised",
        "value_code_mappings": {
            "Stage at diagnosis: loco-regional (In transit metastasis).": False,
            "Stage at diagnosis: metastatic (regional nodal metastases).": False,
        },
    },
    {
        "template_placeholder": "[FULL_ANNOTATION]",
        "entity_type": "ClinicalStage",
        "field_name": "locoRegional",
        "value_code_mappings": {
            "Stage at diagnosis: loco-regional (In transit metastasis).": True,
        },
    },
    {
        "template_placeholder": "[FULL_ANNOTATION]",
        "entity_type": "ClinicalStage",
        "field_name": "isTransitMetastasisWithClinicalConfirmation",
        "value_code_mappings": {
            "Stage at diagnosis: loco-regional (In transit metastasis).": True,
            "Stage at diagnosis: metastatic (regional nodal metastases).": True,
        },
    },
]

# VGR has additional answers
STAGE_VGR_FMS = [
    {
        "template_placeholder": "[FULL_ANNOTATION]",
        "entity_type": "ClinicalStage",
        "field_name": "localised",
        "value_code_mappings": {
            "Stage at diagnosis: loco-regional (multifocal).": False,
            "Stage at diagnosis: loco-regional (In transit metastasis).": False,
            "Stage at diagnosis: metastatic (regional nodal metastases).": False,
            "Stage at diagnosis: distant metastases (lung).": False,
            "Stage at diagnosis: distant metastases (soft tissue).": False,
            "Stage at diagnosis: distant metastases (bone).": False,
            "Stage at diagnosis: distant metastases (brain).": False,
            "Stage at diagnosis: distant metastases (lung, bone, soft tissue).": False,
            "Stage at diagnosis: distant metastases (lung, soft tissue).": False,
        },
    },
    {
        "template_placeholder": "[FULL_ANNOTATION]",
        "entity_type": "ClinicalStage",
        "field_name": "locoRegional",
        "value_code_mappings": {
            "Stage at diagnosis: loco-regional (multifocal).": True,
            "Stage at diagnosis: loco-regional (In transit metastasis).": True,
        },
    },
    {
        "template_placeholder": "[FULL_ANNOTATION]",
        "entity_type": "ClinicalStage",
        "field_name": "isTransitMetastasisWithClinicalConfirmation",
        "value_code_mappings": {
            "Stage at diagnosis: loco-regional (In transit metastasis).": True,
            "Stage at diagnosis: metastatic (regional nodal metastases).": True,
            "Stage at diagnosis: distant metastases (lung).": True,
            "Stage at diagnosis: distant metastases (soft tissue).": True,
            "Stage at diagnosis: distant metastases (bone).": True,
            "Stage at diagnosis: distant metastases (brain).": True,
            "Stage at diagnosis: distant metastases (lung, bone, soft tissue).": True,
            "Stage at diagnosis: distant metastases (lung, soft tissue).": True,
        },
    },
    {
        "template_placeholder": "[FULL_ANNOTATION]",
        "entity_type": "ClinicalStage",
        "field_name": "isMultifocalTumor",
        "value_code_mappings": {
            "Stage at diagnosis: loco-regional (multifocal).": True,
        },
    },
]


def fix_stage_at_diagnosis(data, center, new_fms):
    if "stage_at_diagnosis" not in data:
        return
    em = data["stage_at_diagnosis"]["entity_mapping"]
    em["field_mappings"] = copy.deepcopy(new_fms)
    print(f"    [{center}] stage_at_diagnosis: replaced with {len(new_fms)} boolean field_mappings")


# ── main ───────────────────────────────────────────────────────────────────
def process(path, center,
            fix_rt_end=False,
            patient_status_extra=None,
            fix_recurrence=False,
            fix_rupture=False,
            fix_set=False,
            stage_fms=None):
    data = load(path)
    if fix_rt_end:
        fix_radiotherapy_end(data, center)
    if patient_status_extra:
        fix_patient_status(data, center, patient_status_extra)
    if fix_recurrence:
        fix_recurrencetype(data, center)
    if fix_rupture:
        fix_tumorrupture(data, center)
    if fix_set:
        fix_setting(data, center)
    if stage_fms is not None:
        fix_stage_at_diagnosis(data, center, stage_fms)
    save(path, data)


if __name__ == "__main__":
    print("\n=== Applying mapping fixes ===\n")

    # ── latest_INT ─────────────────────────────────────────────────────────
    print("--- latest_INT ---")
    process(BASE / "latest_prompts/INT/prompts.json", "latest_INT",
            fix_rt_end=True,
            patient_status_extra=DEATH_OUTCOMES_INT,
            fix_recurrence=True,
            fix_set=True)
    # stage_at_diagnosis already correct in latest_INT — no change needed

    # ── latest_MSCI ────────────────────────────────────────────────────────
    print("--- latest_MSCI ---")
    process(BASE / "latest_prompts/MSCI/prompts.json", "latest_MSCI",
            fix_recurrence=True,
            fix_set=True,
            stage_fms=STAGE_INT_MSCI_FMS)

    # ── latest_VGR ─────────────────────────────────────────────────────────
    print("--- latest_VGR ---")
    process(BASE / "latest_prompts/VGR/prompts.json", "latest_VGR",
            fix_rt_end=True,
            patient_status_extra=DEATH_OUTCOMES_VGR,
            fix_recurrence=True,
            fix_rupture=True,
            fix_set=True,
            stage_fms=STAGE_VGR_FMS)

    # ── fast_INT ───────────────────────────────────────────────────────────
    print("--- fast_INT ---")
    process(BASE / "fast_prompts/INT/prompts.json", "fast_INT",
            fix_rt_end=True,
            patient_status_extra=DEATH_OUTCOMES_INT,
            fix_recurrence=True,
            fix_set=True,
            stage_fms=STAGE_INT_MSCI_FMS)  # fast_INT had old [value]→clinicalStaging

    # ── fast_MSCI ──────────────────────────────────────────────────────────
    print("--- fast_MSCI ---")
    process(BASE / "fast_prompts/MSCI/prompts.json", "fast_MSCI",
            fix_recurrence=True,
            fix_set=True,
            stage_fms=STAGE_INT_MSCI_FMS)

    # ── fast_VGR ───────────────────────────────────────────────────────────
    print("--- fast_VGR ---")
    process(BASE / "fast_prompts/VGR/prompts.json", "fast_VGR",
            fix_rt_end=True,
            patient_status_extra=DEATH_OUTCOMES_VGR,
            fix_recurrence=True,
            fix_rupture=True,
            fix_set=True,
            stage_fms=STAGE_VGR_FMS)

    print("\n=== Done ===")
