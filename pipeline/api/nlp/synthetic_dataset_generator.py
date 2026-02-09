# synthetic_histology_df.py
import pandas as pd
from random import choice, randint
from datetime import date, timedelta

HISTO_TYPES = [
    ("Leiomyosarcoma", "8890/3"),
    ("Liposarcoma", "8850/3"),
    ("Synovial sarcoma", "9040/3"),
    ("Osteosarcoma", "9180/3"),
    ("Rhabdomyosarcoma", "8900/3"),
    ("Angiosarcoma", "9120/3"),
    ("Chondrosarcoma", "9220/3"),
]

TEMPLATES = [
    "Histological examination shows a {name}, consistent with ICD-O-3 code {code}.",
    "Diagnosis: {name} ({code}).",
    "Microscopy confirms {name} type, ICD-O-3: {code}.",
    "Pathology report indicates {name}.",
    "Specimen compatible with {name}, classified as {code}.",
]


def generate_synthetic_histology_df(n=50, start_year=2015):
    """Create a synthetic labeled dataframe for few-shot testing."""
    rows = []
    base_date = date(start_year, 1, 1)
    for i in range(n):
        hist_name, code = choice(HISTO_TYPES)
        note = choice(TEMPLATES).format(name=hist_name, code=code)
        ann = f"Annotation: Histological type: {hist_name} (ICD-O-3: {code})."
        d = base_date + timedelta(days=randint(0, 365 * 8))
        rows.append({"note_original_text": note,
                    "annotation": ann, "date": d.isoformat()})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = generate_synthetic_histology_df(50)
    print(df.head())
    df.to_csv("synthetic_histology.csv", index=False)
    print("✅ synthetic_histology.csv written.")
