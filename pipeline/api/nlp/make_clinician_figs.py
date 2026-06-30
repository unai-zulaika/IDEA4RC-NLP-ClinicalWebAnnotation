#!/usr/bin/env python3
"""Generate clinician-friendly figures (accuracy + made-up/false-positive rates) from the
scored sessions. Aggregate match-types only - no patient text. PNGs -> docs/reports/figs/.
"""
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("/home/zulaika/ClinicalAnnotationWeb")
SESS = ROOT / "backend" / "sessions"
FIGS = ROOT / "docs" / "reports" / "figs"
FIGS.mkdir(parents=True, exist_ok=True)

GREEN, RED, BLUE, GREY = "#1a7f37", "#d1452b", "#1a4f8b", "#9aa4b2"
plt.rcParams.update({"font.size": 14, "axes.titlesize": 18, "axes.titleweight": "bold",
                     "figure.facecolor": "white"})

# plain-language names for the technical field keys
NICE = {
    "gender": "Sex", "ageatdiagnosis": "Age at diagnosis", "tumorsite": "Tumour site",
    "histological": "Histology type", "histological-tipo": "Histology type",
    "stage_at_diagnosis": "Stage", "biopsygrading": "Biopsy grade",
    "surgerytype": "Surgery type", "surgerymargins": "Surgical margins",
    "patient-status": "Patient status", "radiotherapy_start": "Radiotherapy start",
    "radiotherapy_end": "Radiotherapy end", "chemotherapy_start": "Chemo start",
    "chemotherapy_end": "Chemo end", "biopsymitoticcount": "Mitotic count",
    "tumordiameter": "Tumour size", "patient-bmi": "Body-mass index",
    "patient-weightheight": "Weight/height", "occurrence_cancer": "Other cancer",
    "previous_cancer_treatment": "Prior cancer treatment", "last_contact_date": "Last contact date",
    "recurrencetype": "Recurrence type", "recur_or_prog": "Recurrence/progression",
    "clinical-tnmstaging": "Clinical TNM stage", "pathological-tnmstaging": "Pathological TNM stage",
    "hpv-status": "HPV status", "smoking-status": "Smoking status",
    "neck-surgery-laterality": "Neck surgery side", "radiotherapy_location": "Radiotherapy site",
    "surgical-mitotic-count": "Surgical mitotic count", "necrosis_in_surgical": "Necrosis",
    "tumorbiopsytype": "Biopsy type", "staging-classification": "Staging system",
    "disease-status": "Disease status",
}


def base_of(pt):
    for suf in ("-int-hnc", "-int-sarc", "-msci", "-int"):
        if pt.endswith(suf):
            return pt[: -len(suf)]
    return pt


def per_variable(session):
    d = json.loads((SESS / f"{session}.json").read_text())
    agg = defaultdict(lambda: defaultdict(int))
    for note in d.get("annotations", {}).values():
        for pt, e in note.items():
            if not isinstance(e, dict):
                continue
            mt = (e.get("evaluation_result") or {}).get("match_type")
            if mt:
                agg[base_of(pt)][mt] += 1
    rows = {}
    tot = defaultdict(int)
    for b, c in agg.items():
        for k, v in c.items():
            tot[k] += v
        m, mm, fp, fn, be = (c.get("match", 0), c.get("mismatch", 0), c.get("false_positive", 0),
                             c.get("false_negative", 0), c.get("both_empty", 0))
        scored = m + mm                       # report convention: accuracy over answered-and-judged
        gp = m + mm + fn                      # gold-present (how many notes had this field)
        n = m + mm + fp + fn + be
        rows[b] = {"acc": (m / scored * 100) if scored else None, "gp": gp,
                   "fp": (fp / n * 100) if n else None, "n": n}
    m, mm, fp, fn, be = (tot["match"], tot["mismatch"], tot["false_positive"],
                         tot["false_negative"], tot["both_empty"])
    overall = {"acc": m / (m + mm) * 100 if (m + mm) else 0,
               "fp": fp / (m + mm + fp + fn + be) * 100 if (m + mm + fp + fn + be) else 0}
    return rows, overall


def fig_model_size(acc4, acc27, fp4, fp27):
    """MSCI: small vs big on accuracy, made-up answers, repeats-itself."""
    labels = ["Accuracy\n(higher better)", "Makes up answers\n(lower better)", "Repeats itself\n(lower better)"]
    small = [acc4, fp4, 18.7]
    big = [acc27, fp27, 0.1]
    x = range(len(labels))
    w = 0.36
    fig, ax = plt.subplots(figsize=(11, 6.2))
    b1 = ax.bar([i - w / 2 for i in x], small, w, label="Small AI", color=GREY)
    b2 = ax.bar([i + w / 2 for i in x], big, w, label="Big AI", color=BLUE)
    for bars in (b1, b2):
        for r in bars:
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 1.5, f"{r.get_height():.0f}%",
                    ha="center", fontsize=14, fontweight="bold")
    ax.set_xticks(list(x)); ax.set_xticklabels(labels)
    ax.set_ylabel("Percent (%)"); ax.set_ylim(0, 100)
    ax.set_title("Small AI vs Big AI - same 400 sarcoma notes (MSCI)")
    ax.legend(loc="upper right", fontsize=14)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIGS / "fig_model_size.png", dpi=150); plt.close(fig)


def fig_pervar(rows, title, outfile, include):
    """Two separate panels (different denominators) so the bars are never read as a sum."""
    items = [(b, rows[b]) for b in include if b in rows and rows[b].get("acc") is not None]
    items.sort(key=lambda x: x[1]["acc"])
    names = [NICE.get(b, b) for b, _ in items]
    acc = [r["acc"] for _, r in items]
    fp = [r["fp"] or 0 for _, r in items]
    print(f"  -- {outfile} --")
    for (b, r) in items:
        print(f"     {NICE.get(b,b):24s} acc={r['acc']:.0f}% made_up={(r['fp'] or 0):.0f}% n={r['gp']}")
    y = list(range(len(names)))
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 0.58 * len(names) + 2.4), sharey=True)
    axL.barh(y, acc, color=GREEN, height=0.6)
    axR.barh(y, fp, color=RED, height=0.6)
    for i, v in enumerate(acc):
        axL.text(v + 1.5, i, f"{v:.0f}%", va="center", fontsize=12)
    for i, v in enumerate(fp):
        axR.text(v + 1.5, i, f"{v:.0f}%", va="center", fontsize=12, color=RED)
    axL.set_title("Accuracy\nwhen the field HAS an answer", fontsize=15)
    axR.set_title("Makes things up\nwhen the field is EMPTY", fontsize=15)
    for ax in (axL, axR):
        ax.set_xlim(0, 105); ax.set_xlabel("Percent (%)")
        ax.spines[["top", "right"]].set_visible(False)
    axL.set_yticks(y); axL.set_yticklabels(names, fontsize=12)
    fig.suptitle(title + "\n(two separate measures, different groups of notes - they do NOT add to 100%)",
                 fontsize=16, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(FIGS / outfile, dpi=150); plt.close(fig)
    names = [NICE.get(b, b) + f"  (n={r['gp']})" for b, r in items]
    acc = [r["acc"] for _, r in items]
    fp = [r["fp"] or 0 for _, r in items]
    y = range(len(names))
    h = 0.38
    fig, ax = plt.subplots(figsize=(11.5, 0.62 * len(names) + 2))
    ax.barh([i + h / 2 for i in y], acc, h, color=GREEN, label="Accuracy (when answer exists)")
    ax.barh([i - h / 2 for i in y], fp, h, color=RED, label="Makes up answers (empty fields)")
    for i, (a, f) in enumerate(zip(acc, fp)):
        ax.text(a + 1, i + h / 2, f"{a:.0f}%", va="center", fontsize=11)
        ax.text(f + 1, i - h / 2, f"{f:.0f}%", va="center", fontsize=11, color=RED)
    ax.set_yticks(list(y)); ax.set_yticklabels(names, fontsize=12)
    ax.set_xlim(0, 100); ax.set_xlabel("Percent (%)")
    ax.set_title(title)
    ax.legend(loc="lower right", fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIGS / outfile, dpi=150); plt.close(fig)


def fig_fp_centres(data):
    """Made-up-answer rate, small vs big, per centre."""
    centres = list(data.keys())
    small = [data[c][0] for c in centres]
    big = [data[c][1] for c in centres]
    x = range(len(centres))
    w = 0.36
    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.bar([i - w / 2 for i in x], small, w, label="Small AI", color=GREY)
    ax.bar([i + w / 2 for i in x], big, w, label="Big AI", color=BLUE)
    for i in x:
        ax.text(i - w / 2, small[i] + 1.5, f"{small[i]:.0f}%", ha="center", fontweight="bold")
        ax.text(i + w / 2, big[i] + 1.5, f"{big[i]:.0f}%", ha="center", fontweight="bold")
    ax.set_xticks(list(x)); ax.set_xticklabels(centres)
    ax.set_ylim(0, 100); ax.set_ylabel("Made-up answers (%)")
    ax.set_title("How often the AI invents an answer on empty fields")
    ax.legend(fontsize=13); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIGS / "fig_fp_centres.png", dpi=150); plt.close(fig)


def main():
    msci27, o27 = per_variable("msci_phase2")
    msci4, o4 = per_variable("msci_phase2_4b")
    hnc27, ho27 = per_variable("hnc_27b_50")
    print(f"MSCI  4B acc={o4['acc']:.0f} fp={o4['fp']:.0f} | 27B acc={o27['acc']:.0f} fp={o27['fp']:.0f}")
    print(f"INT-HNC 27B acc={ho27['acc']:.0f} fp={ho27['fp']:.0f}")
    fig_model_size(o4["acc"], o27["acc"], o4["fp"], o27["fp"])
    # curated, defensible fields (exclude strict-match accuracy artifacts), spanning the range
    MSCI_FIELDS = ["ageatdiagnosis", "surgerytype", "radiotherapy_start", "biopsymitoticcount",
                   "histological", "recurrencetype", "last_contact_date", "patient-status"]
    HNC_FIELDS = ["histological-tipo", "clinical-tnmstaging", "tumorsite", "radiotherapy_location",
                  "pathological-tnmstaging", "staging-classification"]
    fig_pervar(msci27, "How reliable is each field? - Big AI, MSCI sarcoma", "fig_pervar_msci.png", MSCI_FIELDS)
    fig_pervar(hnc27, "How reliable is each field? - Big AI, INT-HNC head & neck", "fig_pervar_hnc.png", HNC_FIELDS)
    # made-up rate per centre: small vs big (INT-HNC small from the 15-note read = 68; INT-SARC k=5 = 77/47)
    fig_fp_centres({"MSCI\n(Polish sarcoma)": (o4["fp"], o27["fp"]),
                    "INT-HNC\n(Italian H&N)": (68.0, ho27["fp"]),
                    "INT-SARC\n(Italian sarcoma)": (77.0, 47.0)})
    print("figures written to", FIGS)


if __name__ == "__main__":
    main()
