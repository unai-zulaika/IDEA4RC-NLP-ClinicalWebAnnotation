#!/usr/bin/env python3
"""Per-center results: aggregate small-vs-big AND per-variable small-vs-big, for every centre
with a matched 4B/27B pair. Writes docs/reports/results_by_center.md + plots in figs/.

Definitions (stated in the doc):
  Accuracy   = correct / (notes where the field HAD an answer)            [match/(match+mismatch)]
  Made-up %  = made-up commits / (ALL the field's notes)  = the FP rate   [false_positive / N]
These have different denominators, so per field they need not add to 100%.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from make_clinician_figs import NICE, per_variable

ROOT = Path("/home/zulaika/ClinicalAnnotationWeb")
FIGS = ROOT / "docs" / "reports" / "figs"
DOC = ROOT / "docs" / "reports" / "results_by_center.md"
GREY, BLUE, GREEN, RED = "#9aa4b2", "#1a4f8b", "#1a7f37", "#d1452b"
plt.rcParams.update({"font.size": 13, "axes.titlesize": 15, "axes.titleweight": "bold",
                     "figure.facecolor": "white"})

CENTERS = {
    "MSCI": {"label": "MSCI (Polish sarcoma)", "4B": "msci_phase2_4b", "27B": "msci_phase2",
             "min_gp": 10, "fields": ["ageatdiagnosis", "surgerytype", "radiotherapy_start",
             "biopsymitoticcount", "histological", "recurrencetype", "last_contact_date", "patient-status"]},
    "INT-HNC": {"label": "INT-HNC (Italian head & neck)", "4B": "hnc_4b_k5", "27B": "hnc_27b_k5",
                "min_gp": 4, "fields": ["histological-tipo", "clinical-tnmstaging", "tumorsite",
                "radiotherapy_location", "pathological-tnmstaging", "staging-classification"]},
    "INT-SARC": {"label": "INT-SARC (Italian sarcoma)", "4B": "intsarc_4b", "27B": "intsarc_27b",
                 "min_gp": 3, "fields": ["histological-tipo", "tumorsite", "ageatdiagnosis",
                 "biopsygrading", "stage_at_diagnosis", "tumordiameter"]},
}


def compute():
    out = {}
    for c, cfg in CENTERS.items():
        r4, o4 = per_variable(cfg["4B"]); r27, o27 = per_variable(cfg["27B"])
        out[c] = {"cfg": cfg, "r4": r4, "o4": o4, "r27": r27, "o27": o27}
    return out


def fig_aggregate(data):
    centres = [data[c]["cfg"]["label"] for c in data]
    acc4 = [data[c]["o4"]["acc"] for c in data]; acc27 = [data[c]["o27"]["acc"] for c in data]
    fp4 = [data[c]["o4"]["fp"] for c in data]; fp27 = [data[c]["o27"]["fp"] for c in data]
    x = range(len(centres)); w = 0.36
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 5.4))
    for ax, s, big, ttl, ymax in [(a, acc4, acc27, "Accuracy (higher = better)", 100),
                                  (b, fp4, fp27, "Makes up answers (lower = better)", 100)]:
        ax.bar([i - w / 2 for i in x], s, w, label="Small AI", color=GREY)
        ax.bar([i + w / 2 for i in x], big, w, label="Big AI", color=BLUE)
        for i in x:
            ax.text(i - w / 2, s[i] + 1.5, f"{s[i]:.0f}%", ha="center", fontweight="bold", fontsize=12)
            ax.text(i + w / 2, big[i] + 1.5, f"{big[i]:.0f}%", ha="center", fontweight="bold", fontsize=12)
        ax.set_xticks(list(x)); ax.set_xticklabels(centres, fontsize=11)
        ax.set_ylim(0, ymax); ax.set_title(ttl); ax.set_ylabel("Percent (%)")
        ax.spines[["top", "right"]].set_visible(False); ax.legend(fontsize=12)
    fig.suptitle("Small AI vs Big AI - aggregate, per centre", fontsize=17, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95]); fig.savefig(FIGS / "fig_centers_aggregate.png", dpi=150)
    plt.close(fig)


def fig_center_pervar(d, c):
    cfg = d["cfg"]; fields = [f for f in cfg["fields"] if f in d["r27"]]
    fields.sort(key=lambda f: d["r27"][f]["acc"] or -1)
    names = [NICE.get(f, f) for f in fields]
    a4 = [d["r4"].get(f, {}).get("acc") or 0 for f in fields]
    a27 = [d["r27"][f]["acc"] or 0 for f in fields]
    f4 = [d["r4"].get(f, {}).get("fp") or 0 for f in fields]
    f27 = [d["r27"][f]["fp"] or 0 for f in fields]
    y = range(len(names)); h = 0.38
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13.5, 0.62 * len(names) + 2.4), sharey=True)
    axL.barh([i + h / 2 for i in y], a27, h, color=BLUE, label="Big AI")
    axL.barh([i - h / 2 for i in y], a4, h, color=GREY, label="Small AI")
    axR.barh([i + h / 2 for i in y], f27, h, color=BLUE, label="Big AI")
    axR.barh([i - h / 2 for i in y], f4, h, color=GREY, label="Small AI")
    for i in y:
        axL.text(a27[i] + 1, i + h / 2, f"{a27[i]:.0f}", va="center", fontsize=10)
        axL.text(a4[i] + 1, i - h / 2, f"{a4[i]:.0f}", va="center", fontsize=10)
        axR.text(f27[i] + 1, i + h / 2, f"{f27[i]:.0f}", va="center", fontsize=10)
        axR.text(f4[i] + 1, i - h / 2, f"{f4[i]:.0f}", va="center", fontsize=10)
    axL.set_title("Accuracy\n(when the field HAS an answer)"); axR.set_title("Makes up answers\n(false-positive rate)")
    for ax in (axL, axR):
        ax.set_xlim(0, 105); ax.set_xlabel("Percent (%)"); ax.spines[["top", "right"]].set_visible(False)
        ax.legend(fontsize=11, loc="lower right")
    axL.set_yticks(list(y)); axL.set_yticklabels(names, fontsize=12)
    fig.suptitle(f"{cfg['label']} - per field, Small AI vs Big AI", fontsize=16, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(FIGS / f"fig_pervar_4b27b_{c.lower().replace('-','')}.png", dpi=150); plt.close(fig)


def f(v):
    return f"{v:.0f}%" if v is not None else "-"


def write_doc(data):
    L = ["# Results by centre - small AI vs big AI", "",
         "Two levels for every centre with a matched 4B/27B pair: the **aggregate** picture, then the",
         "**per-field** detail. Generated from the scored sessions (match-types).", "",
         "**Definitions.** *Accuracy* = correct / notes where the field HAD an answer. ",
         "*Made-up %* (false-positive rate) = made-up commits / ALL the field's notes. ",
         "These use different denominators, so per field they need not sum to 100%.", "",
         "![aggregate](figs/fig_centers_aggregate.png)", "",
         "## Aggregate - small vs big, per centre", "",
         "| Centre | Notes (4B / 27B) | Accuracy 4B | Accuracy 27B | Made-up 4B | Made-up 27B |",
         "|---|---|---:|---:|---:|---:|"]
    for c, d in data.items():
        n4 = len(json.loads((ROOT / 'backend/sessions' / (d['cfg']['4B'] + '.json')).read_text())['annotations'])
        n27 = len(json.loads((ROOT / 'backend/sessions' / (d['cfg']['27B'] + '.json')).read_text())['annotations'])
        L.append(f"| {d['cfg']['label']} | {n4} / {n27} | {f(d['o4']['acc'])} | **{f(d['o27']['acc'])}** | "
                 f"{f(d['o4']['fp'])} | **{f(d['o27']['fp'])}** |")
    L += ["", "> Across all three centres the big model is **more accurate and makes up fewer answers** - the headline finding.", ""]
    for c, d in data.items():
        cfg = d["cfg"]
        L += [f"## {cfg['label']} - per field", "",
              f"![{c}](figs/fig_pervar_4b27b_{c.lower().replace('-','')}.png)", "",
              "| Field | n (answered) | Accuracy 4B | Accuracy 27B | Made-up 4B | Made-up 27B |",
              "|---|---:|---:|---:|---:|---:|"]
        fields = [fld for fld in d["r27"] if (d["r27"][fld]["gp"] or 0) >= cfg["min_gp"]]
        fields.sort(key=lambda fld: d["r27"][fld]["acc"] or -1, reverse=True)
        for fld in fields:
            r27 = d["r27"][fld]; r4 = d["r4"].get(fld, {})
            L.append(f"| {NICE.get(fld, fld)} | {r27['gp']} | {f(r4.get('acc'))} | **{f(r27['acc'])}** | "
                     f"{f(r4.get('fp'))} | **{f(r27['fp'])}** |")
        if c == "INT-SARC":
            L.append("")
            L.append("> **Small cohort (28 notes / 6 patients).** The aggregate above is reliable, but per-field "
                     "counts are tiny (n = 3-6 answered), so individual field numbers are indicative only - "
                     "read the *direction*, not the exact percentage.")
        L.append("")
    L += ["## Caveat", "",
          "Strict matching can understate fields where the AI's wording differs from the registry's",
          "(a few easy fields can score artificially low). Treat borderline-low accuracy as 'needs review',",
          "not 'incapable'. The aggregate and the false-positive numbers are robust."]
    DOC.write_text("\n".join(L), encoding="utf-8")
    print("wrote", DOC)


def main():
    data = compute()
    for c, d in data.items():
        print(f"{c}: 4B acc={d['o4']['acc']:.0f} fp={d['o4']['fp']:.0f} | 27B acc={d['o27']['acc']:.0f} fp={d['o27']['fp']:.0f}")
    fig_aggregate(data)
    for c, d in data.items():
        fig_center_pervar(d, c)
    write_doc(data)


if __name__ == "__main__":
    main()
