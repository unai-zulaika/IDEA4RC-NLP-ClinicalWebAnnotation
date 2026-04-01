# History Note Splitting — Evaluation Review

**Date:** 20260331_110223
**Session:** 04779998-49d... (INT-SARC)
**Notes evaluated:** 3
**Prompt types:** chemotherapy_start-int-sarc, radiotherapy_start-int-sarc, recurrencetype-int-sarc, surgerytype-int-sarc

## Summary

| Metric | Value |
|--------|-------|
| Total comparisons | 12 |
| Baseline total values | 12 |
| Splitting total values | 38 |
| Cases with more values | 9 |
| Improvement rate | 75% |

## Detailed Results

### Note 1: `{[DWH_Data].[DOC]|AMB_SARC_Visita|ds_evoluzione_storia|1409|`

**Detection:** confidence=0.90, dates=3, markers=5, treatments=['surgery', 'chemotherapy']

**Split result:** 5 events (split_time=9.85s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 3.85s):
  - `post-operative chemotherapy with Adriamycin and Dacarbazine started on 03/03/2021 and utilized Adriamycin and Dacarbazin`
- **With splitting** (2 values, 4.63s):
  - [1] `post-operative chemotherapy with minor response started on 2021-06-29 and utilized Adriamycin and Dacarbazine regimen.`
  - [2] `post-operative chemotherapy with started on and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06/2019): [ok] `Not applicable`
  - Event 1 (chemotherapy, date=06/2019): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 2 (follow_up, date=06/2019): [ok] `Not applicable`
  - Event 3 (diagnosis, date=02/2021): [ok] `Not applicable`
  - Event 4 (chemotherapy, date=03/2021): [ok] `post-operative chemotherapy with minor response started on 2021-06-29 and utilized Adriamycin and Da`
- **Gold annotation:** `therapeutic (without surgery) chemotherapy with curative started on 15/03/2021 and utilized Doxorubicin + Dacarbazine re`

**radiotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 1.32s):
  - `Not applicable`
- **With splitting** (1 values, 3.67s):
  - [1] `Not applicable`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06/2019): [ok] `Not applicable`
  - Event 1 (chemotherapy, date=06/2019): [ok] `Not applicable`
  - Event 2 (follow_up, date=06/2019): [ok] `Not applicable`
  - Event 3 (diagnosis, date=02/2021): [ok] `Not applicable`
  - Event 4 (chemotherapy, date=03/2021): [ok] `Not applicable`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 0.8s):
  - `Type of recurrence/progression: metastatic`
- **With splitting** (3 values, 5.12s):
  - [1] `Type of recurrence/progression: None`
  - [2] `Type of recurrence/progression: local`
  - [3] `Type of recurrence/progression: Not applicable`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06/2019): [ok] `Not applicable`
  - Event 1 (chemotherapy, date=06/2019): [ok] `Not applicable`
  - Event 2 (follow_up, date=06/2019): [ok] `Type of recurrence/progression: None`
  - Event 3 (diagnosis, date=02/2021): [ok] `Type of recurrence/progression: local`
  - Event 4 (chemotherapy, date=03/2021): [ok] `Type of recurrence/progression: Not applicable`
- **Gold annotation:** `Type of recurrence/progression: metastatic soft tissue.`

**surgerytype-int-sarc** [=]

- **Baseline** (1 value, 1.07s):
  - `Surgical procedure was performed on 06/06/2019 and was macroscopically complete.`
- **With splitting** (1 values, 4.01s):
  - [1] `Surgical procedure was performed on 2021-06-29 and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06/2019): [ok] `Surgical procedure was performed on 2021-06-29 and was macroscopically complete.`
  - Event 1 (chemotherapy, date=06/2019): [ok] `Not applicable`
  - Event 2 (follow_up, date=06/2019): [ok] `Not applicable`
  - Event 3 (diagnosis, date=02/2021): [ok] `Not applicable`
  - Event 4 (chemotherapy, date=03/2021): [ok] `Not applicable`

---

### Note 2: `{[DWH_Data].[DOC]|INT_Anamnesi|ds_evoluzione_storia|74671|10`

**Detection:** confidence=0.90, dates=19, markers=10, treatments=['surgery', 'chemotherapy']

**Split result:** 14 events (split_time=8.27s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.53s):
  - `post-operative chemotherapy with post-operative started on 27/07/2021 and utilized CT con Adriamicina e Dacarbazina regi`
- **With splitting** (4 values, 10.8s):
  - [1] `post-operative chemotherapy with adjuvant started on and utilized gemcitabine+dacarbazine regimen.`
  - [2] `post-operative chemotherapy with adiuvante started on and utilized Gemcitabina-Dacarbazina regimen.`
  - [3] `post-operative chemotherapy with negative started on and utilized regimen.`
  - [4] `post-operative chemotherapy with started on and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `post-operative chemotherapy with adjuvant started on and utilized gemcitabine+dacarbazine regimen.`
  - Event 1 (surgery, date=07-2019): [ok] `Not applicable`
  - Event 2 (surgery, date=05-08-2019): [ok] `Not applicable`
  - Event 3 (surgery, date=02-10-2019): [ok] `Not applicable`
  - Event 4 (chemotherapy, date=20-03-2020): [ok] `post-operative chemotherapy with adiuvante started on and utilized Gemcitabina-Dacarbazina regimen.`
  - Event 5 (follow_up, date=20-03-2020): [ok] `post-operative chemotherapy with negative started on and utilized regimen.`
  - Event 6 (follow_up, date=24-09-2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=12-02-2021): [ok] `Not applicable`
  - Event 8 (follow_up, date=09-03-2021): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 9 (chemotherapy, date=27-07-2021): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 10 (surgery, date=27-07-2021): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 11 (follow_up, date=30-11-2021): [ok] `Not applicable`
  - Event 12 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 13 (follow_up, date=06-05-2022): [ok] `Not applicable`

**radiotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 1.56s):
  - `post-operative radiotherapy with gemcitabina+dacarbazina intention started 27/07/2021`
- **With splitting** (1 values, 10.11s):
  - [1] `Not applicable`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Not applicable`
  - Event 1 (surgery, date=07-2019): [ok] `Not applicable`
  - Event 2 (surgery, date=05-08-2019): [ok] `Not applicable`
  - Event 3 (surgery, date=02-10-2019): [ok] `Not applicable`
  - Event 4 (chemotherapy, date=20-03-2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=20-03-2020): [ok] `Not applicable`
  - Event 6 (follow_up, date=24-09-2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=12-02-2021): [ok] `Not applicable`
  - Event 8 (follow_up, date=09-03-2021): [ok] `Not applicable`
  - Event 9 (chemotherapy, date=27-07-2021): [ok] `Not applicable`
  - Event 10 (surgery, date=27-07-2021): [ok] `Not applicable`
  - Event 11 (follow_up, date=30-11-2021): [ok] `Not applicable`
  - Event 12 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 13 (follow_up, date=06-05-2022): [ok] `Not applicable`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 1.62s):
  - `metastatic other`
- **With splitting** (4 values, 12.55s):
  - [1] `Type of recurrence/progression: None`
  - [2] `Type of recurrence/progression: Not applicable`
  - [3] `Type of recurrence/progression: metastatic soft tissue.`
  - [4] `Type of recurrence/progression: local`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Type of recurrence/progression: None`
  - Event 1 (surgery, date=07-2019): [ok] `Not applicable`
  - Event 2 (surgery, date=05-08-2019): [ok] `Type of recurrence/progression: None`
  - Event 3 (surgery, date=02-10-2019): [ok] `Not applicable`
  - Event 4 (chemotherapy, date=20-03-2020): [ok] `Type of recurrence/progression: Not applicable`
  - Event 5 (follow_up, date=20-03-2020): [ok] `Type of recurrence/progression: None`
  - Event 6 (follow_up, date=24-09-2020): [ok] `Type of recurrence/progression: None`
  - Event 7 (follow_up, date=12-02-2021): [ok] `Not applicable`
  - Event 8 (follow_up, date=09-03-2021): [ok] `Type of recurrence/progression: metastatic`
  - Event 9 (chemotherapy, date=27-07-2021): [ok] `Not applicable`
  - Event 10 (surgery, date=27-07-2021): [ok] `Type of recurrence/progression: local`
  - Event 11 (follow_up, date=30-11-2021): [ok] `Type of recurrence/progression: None`
  - Event 12 (follow_up, date=12-04-2022): [ok] `Type of recurrence/progression: None`
  - Event 13 (follow_up, date=06-05-2022): [ok] `Type of recurrence/progression: metastatic soft tissue.`

**surgerytype-int-sarc** [**+**]

- **Baseline** (1 value, 12.95s):
  - `{"reasoning": "The medical note describes several surgical procedures performed on the patient. The first procedure ment`
- **With splitting** (3 values, 11.42s):
  - [1] `Surgical procedure was performed on 2022-06-14 and was macroscopically complete.`
  - [2] `Surgical procedure was performed on 14/06/2022 and was macroscopically complete.`
  - [3] `Surgical procedure was performed on DD/MM/YYYY and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Surgical procedure was performed on 2022-06-14 and was macroscopically.`
  - Event 1 (surgery, date=07-2019): [ok] `Surgical procedure was performed on 14/06/2022 and was macroscopically complete.`
  - Event 2 (surgery, date=05-08-2019): [ok] `Surgical procedure was performed on 2022-06-14 and was macroscopically complete.`
  - Event 3 (surgery, date=02-10-2019): [ok] `Surgical procedure was performed on DD/MM/YYYY and was macroscopically complete.`
  - Event 4 (chemotherapy, date=20-03-2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=20-03-2020): [ok] `Not applicable`
  - Event 6 (follow_up, date=24-09-2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=12-02-2021): [ok] `Not applicable`
  - Event 8 (follow_up, date=09-03-2021): [ok] `Not applicable`
  - Event 9 (chemotherapy, date=27-07-2021): [ok] `Not applicable`
  - Event 10 (surgery, date=27-07-2021): [ok] `Surgical procedure was performed on 2022-06-14 and was macroscopically complete.`
  - Event 11 (follow_up, date=30-11-2021): [ok] `Not applicable`
  - Event 12 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 13 (follow_up, date=06-05-2022): [ok] `Not applicable`

---

### Note 3: `{[DWH_Data].[DOC]|AMB_LROL_due|ds_ana_remota|14425|423557|1}`

**Detection:** confidence=0.90, dates=15, markers=7, treatments=['surgery', 'chemotherapy']

**Split result:** 12 events (split_time=8.59s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.45s):
  - `post-operative chemotherapy with post-operative started on 30-03-2021 and utilized CT with Adriamycin and Dacarbazina re`
- **With splitting** (5 values, 13.15s):
  - [1] `post-operative chemotherapy with adjuvant started on 01/01/2020 and utilized schemagemcitabina+dacarbazina regimen.`
  - [2] `post-operative chemotherapy with started on 20-03-2020 and utilized regimen.`
  - [3] `post-operative chemotherapy with started on and utilized regimen.`
  - [4] `post-operative chemotherapy with neoadjuvant started on 09-03-2021 and utilized altretà regimen.`
  - [5] `post-operative chemotherapy with Intravenous chemotherapy started on 24-06-2021 and utilized Adriamycin and Dacarbazine `
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `post-operative chemotherapy with adjuvant started on 01/01/2020 and utilized schemagemcitabina+dacar`
  - Event 1 (follow_up, date=20-03-2020): [ok] `post-operative chemotherapy with started on 20-03-2020 and utilized regimen.`
  - Event 2 (follow_up, date=24-09-2020): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 3 (follow_up, date=12-02-2021): [ok] `Not applicable`
  - Event 4 (follow_up, date=09-03-2021): [ok] `post-operative chemotherapy with neoadjuvant started on 09-03-2021 and utilized altretà regimen.`
  - Event 5 (chemotherapy, date=03-2021): [ok] `post-operative chemotherapy with Intravenous chemotherapy started on 24-06-2021 and utilized Adriamy`
  - Event 6 (follow_up, date=27-07-2021): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 7 (surgery, date=28-07-2021): [ok] `Not applicable`
  - Event 8 (follow_up, date=30-11-2021): [ok] `Not applicable`
  - Event 9 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 10 (follow_up, date=06-05-2022): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 11 (surgery, date=15-06-2022): [ok] `Not applicable`

**radiotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 2.05s):
  - `post-operative radiotherapy with conventional intention started 24-06-2021 on 24-06-2021`
- **With splitting** (4 values, 11.35s):
  - [1] `post-operative radiotherapy (conventional) with INT intention started 24-06-2021`
  - [2] `post-operative radiotherapy (conventional) with intention started [please select where] on.`
  - [3] `post-operative radiotherapy (conventional) with select intention started.`
  - [4] `pre-operative radiotherapy with intention started.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Not applicable`
  - Event 1 (follow_up, date=20-03-2020): [ok] `Not applicable`
  - Event 2 (follow_up, date=24-09-2020): [ok] `Not applicable`
  - Event 3 (follow_up, date=12-02-2021): [ok] `Not applicable`
  - Event 4 (follow_up, date=09-03-2021): [ok] `Not applicable`
  - Event 5 (chemotherapy, date=03-2021): [ok] `post-operative radiotherapy (conventional) with INT intention started 24-06-2021`
  - Event 6 (follow_up, date=27-07-2021): [ok] `post-operative radiotherapy (conventional) with intention started [please select where] on.`
  - Event 7 (surgery, date=28-07-2021): [ok] `post-operative radiotherapy (conventional) with select intention started.`
  - Event 8 (follow_up, date=30-11-2021): [ok] `pre-operative radiotherapy with intention started.`
  - Event 9 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 10 (follow_up, date=06-05-2022): [ok] `Not applicable`
  - Event 11 (surgery, date=15-06-2022): [ok] `Not applicable`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 1.8s):
  - `metastatic`
- **With splitting** (3 values, 10.42s):
  - [1] `Type of recurrence/progression: local`
  - [2] `Type of recurrence/progression: None`
  - [3] `Type of recurrence/progression: metastatic`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Not applicable`
  - Event 1 (follow_up, date=20-03-2020): [ok] `Type of recurrence/progression: local`
  - Event 2 (follow_up, date=24-09-2020): [ok] `Type of recurrence/progression: None`
  - Event 3 (follow_up, date=12-02-2021): [ok] `Type of recurrence/progression: local`
  - Event 4 (follow_up, date=09-03-2021): [ok] `Type of recurrence/progression: metastatic`
  - Event 5 (chemotherapy, date=03-2021): [ok] `Not applicable`
  - Event 6 (follow_up, date=27-07-2021): [ok] `Type of recurrence/progression: metastatic`
  - Event 7 (surgery, date=28-07-2021): [ok] `Type of recurrence/progression: local`
  - Event 8 (follow_up, date=30-11-2021): [ok] `Type of recurrence/progression: None`
  - Event 9 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 10 (follow_up, date=06-05-2022): [ok] `Type of recurrence/progression: local`
  - Event 11 (surgery, date=15-06-2022): [ok] `Not applicable`

**surgerytype-int-sarc** [**+**]

- **Baseline** (1 value, 0.9s):
  - `Surgical procedure was performed on 2019-06-06 and was macroscopically complete.`
- **With splitting** (7 values, 12.0s):
  - [1] `Surgical procedure was performed on 06/06/2019 and was macroscopically complete.`
  - [2] `Surgical procedure was performed on 24/09/2020 and was macroscopically complete.`
  - [3] `Surgical procedure was performed on 12/02/2021 and was macroscopically.`
  - [4] `Surgical procedure was performed on 27/07/2021 and was macroscopically incomplete.`
  - [5] `Surgical procedure was performed on 28/07/2021 and was macroscopically complete.`
  - [6] `Surgical procedure was performed on 30/11/2021 and was macroscopically complete.`
  - [7] `Local excision was performed on 15/06/2022 and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Surgical procedure was performed on 06/06/2019 and was macroscopically complete.`
  - Event 1 (follow_up, date=20-03-2020): [ok] `Not applicable`
  - Event 2 (follow_up, date=24-09-2020): [ok] `Surgical procedure was performed on 24/09/2020 and was macroscopically complete.`
  - Event 3 (follow_up, date=12-02-2021): [ok] `Surgical procedure was performed on 12/02/2021 and was macroscopically.`
  - Event 4 (follow_up, date=09-03-2021): [ok] `Not applicable`
  - Event 5 (chemotherapy, date=03-2021): [ok] `Not applicable`
  - Event 6 (follow_up, date=27-07-2021): [ok] `Surgical procedure was performed on 27/07/2021 and was macroscopically incomplete.`
  - Event 7 (surgery, date=28-07-2021): [ok] `Surgical procedure was performed on 28/07/2021 and was macroscopically complete.`
  - Event 8 (follow_up, date=30-11-2021): [ok] `Surgical procedure was performed on 30/11/2021 and was macroscopically complete.`
  - Event 9 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 10 (follow_up, date=06-05-2022): [ok] `Not applicable`
  - Event 11 (surgery, date=15-06-2022): [ok] `Local excision was performed on 15/06/2022 and was macroscopically complete.`

---

## Scoring Rubric

For each note, assess:

| Criterion | Score (1-5) | Notes |
|-----------|-------------|-------|
| **Split quality**: Were events correctly identified and separated? | | |
| **Completeness**: Were all events in the note captured? | | |
| **Extraction quality**: Were values correctly extracted from sub-notes? | | |
| **Deduplication**: Were true duplicates removed without losing unique values? | | |
| **Non-regression**: Did splitting NOT hurt any prompt type that worked in baseline? | | |
