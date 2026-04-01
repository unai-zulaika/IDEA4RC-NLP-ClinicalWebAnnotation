# History Note Splitting — Evaluation Review

**Date:** 20260331_111612
**Session:** 04779998-49d... (INT-SARC)
**Notes evaluated:** 10
**Prompt types:** chemotherapy_start-int-sarc, radiotherapy_start-int-sarc, recurrencetype-int-sarc, surgerytype-int-sarc

## Summary

| Metric | Value |
|--------|-------|
| Total comparisons | 40 |
| Baseline total values | 66 |
| Splitting total values | 102 |
| Cases with more values | 22 |
| Improvement rate | 55% |

## Detailed Results

### Note 1: `{[DWH_Data].[DOC]|AMB_SARC_Visita|ds_evoluzione_storia|1409|`

**Detection:** confidence=0.90, dates=3, markers=5, treatments=['surgery', 'chemotherapy']

**Split result:** 5 events (split_time=3.02s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 3.55s):
  - `post-operative chemotherapy with Adriamycin and Dacarbazine started on 03/03/2021 and utilized Adriamycin and Dacarbazin`
- **With splitting** (2 values, 4.69s):
  - [1] `pre-operative chemotherapy with started on 2021-06-29 and utilized Adriamycin and Dacarbazine regimen.`
  - [2] `post-operative chemotherapy with started on and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06/2019): [ok] `Not applicable`
  - Event 1 (chemotherapy, date=06/2019): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 2 (follow_up, date=06/2019): [ok] `Not applicable`
  - Event 3 (diagnosis, date=02/2021): [ok] `Not applicable`
  - Event 4 (chemotherapy, date=03/2021): [ok] `pre-operative chemotherapy with started on 2021-06-29 and utilized Adriamycin and Dacarbazine regime`
- **Gold annotation:** `therapeutic (without surgery) chemotherapy with curative started on 15/03/2021 and utilized Doxorubicin + Dacarbazine re`

**radiotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 1.3s):
  - `Not applicable`
- **With splitting** (1 values, 3.57s):
  - [1] `Not applicable`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06/2019): [ok] `Not applicable`
  - Event 1 (chemotherapy, date=06/2019): [ok] `Not applicable`
  - Event 2 (follow_up, date=06/2019): [ok] `Not applicable`
  - Event 3 (diagnosis, date=02/2021): [ok] `Not applicable`
  - Event 4 (chemotherapy, date=03/2021): [ok] `Not applicable`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 0.85s):
  - `Type of recurrence/progression: metastatic.`
- **With splitting** (3 values, 4.97s):
  - [1] `Type of recurrence/progression: Not applicable`
  - [2] `Type of recurrence/progression: None`
  - [3] `Type of recurrence/progression: local`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06/2019): [ok] `Type of recurrence/progression: Not applicable`
  - Event 1 (chemotherapy, date=06/2019): [ok] `Type of recurrence/progression: None`
  - Event 2 (follow_up, date=06/2019): [ok] `Type of recurrence/progression: None`
  - Event 3 (diagnosis, date=02/2021): [ok] `Type of recurrence/progression: local`
  - Event 4 (chemotherapy, date=03/2021): [ok] `Type of recurrence/progression: Not applicable`
- **Gold annotation:** `Type of recurrence/progression: metastatic soft tissue.`

**surgerytype-int-sarc** [=]

- **Baseline** (1 value, 1.05s):
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

**Split result:** 14 events (split_time=9.87s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.47s):
  - `post-operative chemotherapy with post-operative started on 27/07/2021 and utilized CT con Adriamicina e Dacarbazina regi`
- **With splitting** (5 values, 14.49s):
  - [1] `post-operative chemotherapy with started on and utilized regimen.`
  - [2] `post-operative chemotherapy with adiuvante started on 02-10-2019 and utilized Gemcitabina-Dacarbazina (q3w) regimen.`
  - [3] `post-operative chemotherapy with started on 20-03-2020 and utilized regimen.`
  - [4] `post-operative chemotherapy with INT started on 27-03-2021 and utilized CT con Adriamicina e Dacarbazina regimen.`
  - [5] `post-operative chemotherapy with surgery started on 06-05-2022 and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 1 (surgery, date=07-2019): [ok] `Not applicable`
  - Event 2 (surgery, date=05-08-2019): [ok] `Not applicable`
  - Event 3 (chemotherapy, date=02-10-2019): [ok] `post-operative chemotherapy with adiuvante started on 02-10-2019 and utilized Gemcitabina-Dacarbazin`
  - Event 4 (follow_up, date=20-03-2020): [ok] `post-operative chemotherapy with started on 20-03-2020 and utilized regimen.`
  - Event 5 (follow_up, date=24-09-2020): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 6 (follow_up, date=12-02-2021): [ok] `Not applicable`
  - Event 7 (follow_up, date=09-03-2021): [ok] `Not applicable`
  - Event 8 (chemotherapy, date=27-03-2021): [ok] `post-operative chemotherapy with INT started on 27-03-2021 and utilized CT con Adriamicina e Dacarba`
  - Event 9 (follow_up, date=27-07-2021): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 10 (surgery, date=28-07-2021): [ok] `Not applicable`
  - Event 11 (follow_up, date=30-11-2021): [ok] `Not applicable`
  - Event 12 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 13 (follow_up, date=06-05-2022): [ok] `post-operative chemotherapy with surgery started on 06-05-2022 and utilized regimen.`

**radiotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.48s):
  - `post-operative radiotherapy with gemcitabina+dacarbazina intention started 27/07/2021`
- **With splitting** (4 values, 13.37s):
  - [1] `post-operative radiotherapy with select intention started altrove on 24-09-2020.`
  - [2] `post-operative radiotherapy with intention started [please select where] on.`
  - [3] `post-operative radiotherapy (conventional) with intention started [please select where] on.`
  - [4] `pre-operative radiotherapy (conventional) with total body irradiation intention started 30-11-2021 on 30-11-2021.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Not applicable`
  - Event 1 (surgery, date=07-2019): [ok] `Not applicable`
  - Event 2 (surgery, date=05-08-2019): [ok] `Not applicable`
  - Event 3 (chemotherapy, date=02-10-2019): [ok] `Not applicable`
  - Event 4 (follow_up, date=20-03-2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=24-09-2020): [ok] `post-operative radiotherapy with select intention started altrove on 24-09-2020.`
  - Event 6 (follow_up, date=12-02-2021): [ok] `post-operative radiotherapy with intention started [please select where] on.`
  - Event 7 (follow_up, date=09-03-2021): [ok] `Not applicable`
  - Event 8 (chemotherapy, date=27-03-2021): [ok] `Not applicable`
  - Event 9 (follow_up, date=27-07-2021): [ok] `post-operative radiotherapy (conventional) with intention started [please select where] on.`
  - Event 10 (surgery, date=28-07-2021): [ok] `post-operative radiotherapy with select intention started.`
  - Event 11 (follow_up, date=30-11-2021): [ok] `pre-operative radiotherapy (conventional) with total body irradiation intention started 30-11-2021 o`
  - Event 12 (follow_up, date=12-04-2022): [ok] `Not applicable`
  - Event 13 (follow_up, date=06-05-2022): [ok] `Not applicable`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 1.56s):
  - `metastatic other`
- **With splitting** (5 values, 14.06s):
  - [1] `Type of recurrence/progression: Not applicable`
  - [2] `Type of recurrence/progression: metastatic.`
  - [3] `Type of recurrence/progression: None`
  - [4] `Type of recurrence/progression: local`
  - [5] `Type of recurrence/progression: residual.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Type of recurrence/progression: Not applicable`
  - Event 1 (surgery, date=07-2019): [ok] `Type of recurrence/progression: metastatic`
  - Event 2 (surgery, date=05-08-2019): [ok] `Type of recurrence/progression: None`
  - Event 3 (chemotherapy, date=02-10-2019): [ok] `Type of recurrence/progression: None`
  - Event 4 (follow_up, date=20-03-2020): [ok] `Type of recurrence/progression: metastatic.`
  - Event 5 (follow_up, date=24-09-2020): [ok] `Type of recurrence/progression: None`
  - Event 6 (follow_up, date=12-02-2021): [ok] `Type of recurrence/progression: local`
  - Event 7 (follow_up, date=09-03-2021): [ok] `Type of recurrence/progression: metastatic`
  - Event 8 (chemotherapy, date=27-03-2021): [ok] `Type of recurrence/progression: Not applicable`
  - Event 9 (follow_up, date=27-07-2021): [ok] `Type of recurrence/progression: local`
  - Event 10 (surgery, date=28-07-2021): [ok] `Type of recurrence/progression: residual.`
  - Event 11 (follow_up, date=30-11-2021): [ok] `Type of recurrence/progression: None`
  - Event 12 (follow_up, date=12-04-2022): [ok] `Type of recurrence/progression: None`
  - Event 13 (follow_up, date=06-05-2022): [ok] `Type of recurrence/progression: local`

**surgerytype-int-sarc** [**+**]

- **Baseline** (1 value, 12.83s):
  - `{"reasoning": "The medical note describes several surgical procedures performed on the patient. The first procedure ment`
- **With splitting** (8 values, 13.13s):
  - [1] `Surgical procedure was performed on 06/06/2019 and was macroscopically complete.`
  - [2] `Surgical procedure was performed on 07/07/2019 and was macroscopically complete.`
  - [3] `Limb operation was performed on 05/08/2019 and was macroscopically complete.`
  - [4] `Surgical procedure was performed on 12/02/2021 and was macroscopically.`
  - [5] `Surgical procedure was performed on 28/07/2021 and was macroscopically complete.`
  - [6] `Surgical procedure was performed on 30/11/2021 and was macroscopically complete.`
  - [7] `Surgical procedure was performed on 06/05/2022 and was macroscopically complete.`
  - [8] `TC torace/addome completo con mdc: oncologicamente negativa.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=06-2019): [ok] `Surgical procedure was performed on 06/06/2019 and was macroscopically complete.`
  - Event 1 (surgery, date=07-2019): [ok] `Surgical procedure was performed on 07/07/2019 and was macroscopically complete.`
  - Event 2 (surgery, date=05-08-2019): [ok] `Limb operation was performed on 05/08/2019 and was macroscopically complete.`
  - Event 3 (chemotherapy, date=02-10-2019): [ok] `Not applicable`
  - Event 4 (follow_up, date=20-03-2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=24-09-2020): [ok] `Not applicable`
  - Event 6 (follow_up, date=12-02-2021): [ok] `Surgical procedure was performed on 12/02/2021 and was macroscopically.`
  - Event 7 (follow_up, date=09-03-2021): [ok] `Not applicable`
  - Event 8 (chemotherapy, date=27-03-2021): [ok] `Not applicable`
  - Event 9 (follow_up, date=27-07-2021): [ok] `Not applicable`
  - Event 10 (surgery, date=28-07-2021): [ok] `Surgical procedure was performed on 28/07/2021 and was macroscopically complete.`
  - Event 11 (follow_up, date=30-11-2021): [ok] `Surgical procedure was performed on 30/11/2021 and was macroscopically complete.`
  - Event 12 (follow_up, date=12-04-2022): [ok] `TC torace/addome completo con mdc: oncologicamente negativa.`
  - Event 13 (follow_up, date=06-05-2022): [ok] `Surgical procedure was performed on 06/05/2022 and was macroscopically complete.`

---

### Note 3: `{[DWH_Data].[DOC]|AMB_LROL_due|ds_ana_remota|14425|423557|1}`

**Detection:** confidence=0.90, dates=15, markers=7, treatments=['surgery', 'chemotherapy']

**Split result:** 1 events (split_time=25.66s, was_split=False)

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 1.39s):
  - `post-operative chemotherapy with adjuvant started on 30-03-2021 and utilized CT con Adriamicina e Dacarbazina regimen.`
- **With splitting** (1 values, 0.0s):
  - [1] `post-operative chemotherapy with adjuvant started on 30-03-2021 and utilized CT con Adriamicina e Dacarbazina regimen.`

**radiotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 2.01s):
  - `post-operative radiotherapy with conventional intention started 24-06-2021 on 24-06-2021`
- **With splitting** (1 values, 0.0s):
  - [1] `post-operative radiotherapy with conventional intention started 24-06-2021 on 24-06-2021`

**recurrencetype-int-sarc** [=]

- **Baseline** (1 value, 2.02s):
  - `Type of recurrence/progression: metastatic`
- **With splitting** (1 values, 0.0s):
  - [1] `Type of recurrence/progression: metastatic`

**surgerytype-int-sarc** [=]

- **Baseline** (1 value, 2.06s):
  - `Limb operation was performed on 28-07-2021 and was macroscopically complete.`
- **With splitting** (1 values, 0.0s):
  - [1] `Limb operation was performed on 28-07-2021 and was macroscopically complete.`

---

### Note 4: `{[DWH_Data].[DOC]|INT_LDO|ds_ana_patol_pros|84527|139000|1}`

**Detection:** confidence=0.90, dates=8, markers=4, treatments=['surgery', 'chemotherapy', 'recurrence']

**Split result:** 7 events (split_time=3.89s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.0s):
  - `post-operative chemotherapy with post-operative started on 08/2022 and utilized Trabectedina regimen.`
- **With splitting** (2 values, 6.17s):
  - [1] `post-operative chemotherapy with Trabectedin started on 08/2022 and utilized Trabectedin regimen.`
  - [2] `post-operative chemotherapy with started on and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (recurrence, date=05/2022): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 1 (surgery, date=06/2022): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 2 (chemotherapy, date=08/2022): [ok] `post-operative chemotherapy with Trabectedin started on 08/2022 and utilized Trabectedin regimen.`
  - Event 3 (radiotherapy, date=08/05/2022): [ok] `Not applicable`
  - Event 4 (biopsy, date=07/2023): [ok] `Not applicable`
  - Event 5 (biopsy, date=31/01/2024): [ok] `Not applicable`
  - Event 6 (follow_up, date=13/02): [ok] `Not applicable`
- **Gold annotation:** `therapeutic (without surgery) chemotherapy with life expectancy prolongation started on 15/06/2022 and utilized trabecte`

**radiotherapy_start-int-sarc** [=]

- **Baseline** (2 value, 12.65s):
  - `{
"reasoning": "The note mentions radiotherapy details including the intention (RT), the dose (45 Gy), and the start dat`
- **With splitting** (2 values, 7.14s):
  - [1] `pre-operative radiotherapy with intention started.`
  - [2] `post-operative radiotherapy with intention started [please select where] on.`
- **Sub-note extractions:**
  - Event 0 (recurrence, date=05/2022): [ok] `Not applicable`
  - Event 1 (surgery, date=06/2022): [ok] `pre-operative radiotherapy with intention started.`
  - Event 2 (chemotherapy, date=08/2022): [ok] `Not applicable`
  - Event 3 (radiotherapy, date=08/05/2022): [ok] `post-operative radiotherapy with intention started [please select where] on.`
  - Event 4 (biopsy, date=07/2023): [ok] `Not applicable`
  - Event 5 (biopsy, date=31/01/2024): [ok] `Not applicable`
  - Event 6 (follow_up, date=13/02): [ok] `Not applicable`
- **Gold annotation:** `therapeutic (radiotherapy without surgery) radiotherapy (conventional) with prolongation of life intention started outsi`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 1.32s):
  - `Type of recurrence/progression: local`
- **With splitting** (3 values, 6.13s):
  - [1] `Type of recurrence/progression: local.`
  - [2] `Type of recurrence/progression: metastatic.`
  - [3] `Type of recurrence/progression: Not applicable`
- **Sub-note extractions:**
  - Event 0 (recurrence, date=05/2022): [ok] `Type of recurrence/progression: local`
  - Event 1 (surgery, date=06/2022): [ok] `Type of recurrence/progression: metastatic.`
  - Event 2 (chemotherapy, date=08/2022): [ok] `Type of recurrence/progression: Not applicable`
  - Event 3 (radiotherapy, date=08/05/2022): [ok] `Type of recurrence/progression: Not applicable`
  - Event 4 (biopsy, date=07/2023): [ok] `Type of recurrence/progression: local.`
  - Event 5 (biopsy, date=31/01/2024): [ok] `Type of recurrence/progression: local`
  - Event 6 (follow_up, date=13/02): [ok] `Type of recurrence/progression: local`
- **Gold annotation:** `Type of recurrence/progression: metastatic soft tissue.`

**surgerytype-int-sarc** [**+**]

- **Baseline** (1 value, 1.17s):
  - `Surgical procedure was performed on 06/2022 and was macroscopically complete.`
- **With splitting** (3 values, 5.69s):
  - [1] `Limb operation was performed on 06/2022 and was macroscopically.`
  - [2] `Local excision was performed on 31/01/2024 and was macroscopically complete.`
  - [3] `Local excision was performed on 2024-03-19 and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (recurrence, date=05/2022): [ok] `Not applicable`
  - Event 1 (surgery, date=06/2022): [ok] `Limb operation was performed on 06/2022 and was macroscopically.`
  - Event 2 (chemotherapy, date=08/2022): [ok] `Not applicable`
  - Event 3 (radiotherapy, date=08/05/2022): [ok] `Not applicable`
  - Event 4 (biopsy, date=07/2023): [ok] `Local excision was performed on 2024-03-19 and was macroscopically complete.`
  - Event 5 (biopsy, date=31/01/2024): [ok] `Local excision was performed on 31/01/2024 and was macroscopically complete.`
  - Event 6 (follow_up, date=13/02): [ok] `Not applicable`

---

### Note 5: `{[DWH_Data].[DOC]|MULTI_SAR_Visita|ds_ana_remota|60|538752|1`

**Detection:** confidence=0.90, dates=14, markers=4, treatments=['surgery', 'chemotherapy', 'recurrence']

**Split result:** 14 events (split_time=8.62s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 1.63s):
  - `post-operative chemotherapy with RT started on 28/04/2020 and utilized RT regimen.`
- **With splitting** (1 values, 11.84s):
  - [1] `post-operative chemotherapy with started on and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=29/11/2019): [ok] `Not applicable`
  - Event 1 (diagnosis, date=08/01/2020): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 2 (diagnosis, date=20/01/2020): [ok] `Not applicable`
  - Event 3 (diagnosis, date=05/02/2020): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 4 (radiotherapy, date=21/02/2020-01/04/2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=28/04/2020): [ok] `Not applicable`
  - Event 6 (other, date=11/05/2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=14/05/2020): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 8 (follow_up, date=15/05/2020): [ok] `Not applicable`
  - Event 9 (surgery, date=18/05/2020): [ok] `Not applicable`
  - Event 10 (other, date=26/07/2020): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 11 (follow_up, date=23/08/2020): [ok] `Not applicable`
  - Event 12 (other, date=24/08/2020): [ok] `Not applicable`
  - Event 13 (other, date=24/08/2020): [ok] `Not applicable`

**radiotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.0s):
  - `Not applicable`
- **With splitting** (3 values, 12.78s):
  - [1] `pre-operative radiotherapy with pre-operative intention started 21/02/2020 on 01/04/2020.`
  - [2] `post-operative radiotherapy (conventional) with select intention started 15/05/2020 on 15/05/2020.`
  - [3] `post-operative radiotherapy (conventional) with intention started [please select where] on.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=29/11/2019): [ok] `Not applicable`
  - Event 1 (diagnosis, date=08/01/2020): [ok] `Not applicable`
  - Event 2 (diagnosis, date=20/01/2020): [ok] `Not applicable`
  - Event 3 (diagnosis, date=05/02/2020): [ok] `Not applicable`
  - Event 4 (radiotherapy, date=21/02/2020-01/04/2020): [ok] `pre-operative radiotherapy with pre-operative intention started 21/02/2020 on 01/04/2020.`
  - Event 5 (follow_up, date=28/04/2020): [ok] `Not applicable`
  - Event 6 (other, date=11/05/2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=14/05/2020): [ok] `post-operative radiotherapy (conventional) with intention started [please select where] on.`
  - Event 8 (follow_up, date=15/05/2020): [ok] `post-operative radiotherapy (conventional) with select intention started 15/05/2020 on 15/05/2020.`
  - Event 9 (surgery, date=18/05/2020): [ok] `Not applicable`
  - Event 10 (other, date=26/07/2020): [ok] `Not applicable`
  - Event 11 (follow_up, date=23/08/2020): [ok] `Not applicable`
  - Event 12 (other, date=24/08/2020): [ok] `Not applicable`
  - Event 13 (other, date=24/08/2020): [ok] `Not applicable`
- **Gold annotation:** `Response to pre-operative radiotherapy was: progression.`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 2.03s):
  - `None`
- **With splitting** (4 values, 11.82s):
  - [1] `Type of recurrence/progression: metastatic.`
  - [2] `Type of recurrence/progression: None`
  - [3] `Type of recurrence/progression: local`
  - [4] `Type of recurrence/progression: Not applicable`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=29/11/2019): [ok] `Type of recurrence/progression: metastatic`
  - Event 1 (diagnosis, date=08/01/2020): [ok] `Type of recurrence/progression: metastatic.`
  - Event 2 (diagnosis, date=20/01/2020): [ok] `Type of recurrence/progression: None`
  - Event 3 (diagnosis, date=05/02/2020): [ok] `Type of recurrence/progression: local`
  - Event 4 (radiotherapy, date=21/02/2020-01/04/2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=28/04/2020): [ok] `Type of recurrence/progression: None`
  - Event 6 (other, date=11/05/2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=14/05/2020): [ok] `Not applicable`
  - Event 8 (follow_up, date=15/05/2020): [ok] `Type of recurrence/progression: local`
  - Event 9 (surgery, date=18/05/2020): [ok] `Not applicable`
  - Event 10 (other, date=26/07/2020): [ok] `Type of recurrence/progression: local`
  - Event 11 (follow_up, date=23/08/2020): [ok] `Type of recurrence/progression: Not applicable`
  - Event 12 (other, date=24/08/2020): [ok] `Not applicable`
  - Event 13 (other, date=24/08/2020): [ok] `Not applicable`

**surgerytype-int-sarc** [**+**]

- **Baseline** (1 value, 1.81s):
  - `Limb operation was performed on 28/04/2020 and was macroscopically complete.`
- **With splitting** (4 values, 12.17s):
  - [1] `Surgical procedure was performed on 29/11/2019 and was macroscopically complete.`
  - [2] `Surgical procedure was performed on 05/02/2020 and was macroscopically complete.`
  - [3] `Limb operation was performed on 18/05/2020 and was macroscopically complete.`
  - [4] `Surgical procedure was performed on DD/MM/YYYY and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=29/11/2019): [ok] `Surgical procedure was performed on 29/11/2019 and was macroscopically complete.`
  - Event 1 (diagnosis, date=08/01/2020): [ok] `Not applicable`
  - Event 2 (diagnosis, date=20/01/2020): [ok] `Not applicable`
  - Event 3 (diagnosis, date=05/02/2020): [ok] `Surgical procedure was performed on 05/02/2020 and was macroscopically complete.`
  - Event 4 (radiotherapy, date=21/02/2020-01/04/2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=28/04/2020): [ok] `Not applicable`
  - Event 6 (other, date=11/05/2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=14/05/2020): [ok] `Not applicable`
  - Event 8 (follow_up, date=15/05/2020): [ok] `Not applicable`
  - Event 9 (surgery, date=18/05/2020): [ok] `Limb operation was performed on 18/05/2020 and was macroscopically complete.`
  - Event 10 (other, date=26/07/2020): [ok] `Not applicable`
  - Event 11 (follow_up, date=23/08/2020): [ok] `Not applicable`
  - Event 12 (other, date=24/08/2020): [ok] `Not applicable`
  - Event 13 (other, date=24/08/2020): [ok] `Surgical procedure was performed on DD/MM/YYYY and was macroscopically complete.`

---

### Note 6: `{[DWH_Data].[DOC]|AMB_ROL_due|ds_ana_remota|248669|452236|1}`

**Detection:** confidence=0.80, dates=13, markers=3, treatments=['surgery', 'recurrence']

**Split result:** 17 events (split_time=8.38s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [-]

- **Baseline** (4 value, 12.38s):
  - `{
"reasoning": "The note mentions 'Avvio sirolimus 5 mg/die' on 25/07/2021 and 'Avvio sirolimus 5 mg/die' on 28/07/2022.`
- **With splitting** (2 values, 13.07s):
  - [1] `post-operative chemotherapy with started on 29/09/2022 and utilized Nab-Sirolimus regimen.`
  - [2] `post-operative chemotherapy with started on and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=09/2019): [ok] `Not applicable`
  - Event 1 (diagnosis, date=18/11/2019): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 2 (diagnosis, date=24/12/2019): [ok] `Not applicable`
  - Event 3 (surgery, date=30/01/2020): [ok] `Not applicable`
  - Event 4 (surgery, date=28/05/2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=03/2021): [ok] `Not applicable`
  - Event 6 (diagnosis, date=06/2021): [ok] `Not applicable`
  - Event 7 (radiotherapy, date=2021): [ok] `Not applicable`
  - Event 8 (diagnosis, date=2021): [ok] `Not applicable`
  - Event 9 (other_treatment, date=25/07/2021): [ok] `Not applicable`
  - Event 10 (follow_up, date=09/2021): [ok] `Not applicable`
  - Event 11 (diagnosis, date=09/2021): [ok] `Not applicable`
  - Event 12 (surgery, date=28/07/2022): [ok] `Not applicable`
  - Event 13 (diagnosis, date=26/09/2022): [ok] `Not applicable`
  - Event 14 (diagnosis, date=26/09/2022): [ok] `Not applicable`
  - Event 15 (diagnosis, date=26/09/2022): [ok] `Not applicable`
  - Event 16 (other_treatment, date=29/09/2022): [ok] `post-operative chemotherapy with started on 29/09/2022 and utilized Nab-Sirolimus regimen.`
- **Gold annotation:** `therapeutic (without surgery) chemotherapy with life expectancy prolongation started on 25/07/2021 and utilized sirolimu`

**radiotherapy_start-int-sarc** [-]

- **Baseline** (21 value, 12.47s):
  - `{
"reasoning": "The note mentions 'RT' (radiotherapy) in the context of 'lesioni scheletriche' (skeletal lesions) and sp`
- **With splitting** (2 values, 15.18s):
  - [1] `pre-operative radiotherapy with intention started 18/11/2019 on.`
  - [2] `post-operative radiotherapy (conventional) with follow-up intention started.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=09/2019): [ok] `Not applicable`
  - Event 1 (diagnosis, date=18/11/2019): [ok] `pre-operative radiotherapy with intention started 18/11/2019 on.`
  - Event 2 (diagnosis, date=24/12/2019): [ok] `Not applicable`
  - Event 3 (surgery, date=30/01/2020): [ok] `Not applicable`
  - Event 4 (surgery, date=28/05/2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=03/2021): [ok] `Not applicable`
  - Event 6 (diagnosis, date=06/2021): [ok] `Not applicable`
  - Event 7 (radiotherapy, date=2021): [ok] `post-operative radiotherapy (conventional) with follow-up intention started.`
  - Event 8 (diagnosis, date=2021): [ok] `Not applicable`
  - Event 9 (other_treatment, date=25/07/2021): [ok] `Not applicable`
  - Event 10 (follow_up, date=09/2021): [ok] `Not applicable`
  - Event 11 (diagnosis, date=09/2021): [ok] `Not applicable`
  - Event 12 (surgery, date=28/07/2022): [ok] `Not applicable`
  - Event 13 (diagnosis, date=26/09/2022): [ok] `Not applicable`
  - Event 14 (diagnosis, date=26/09/2022): [ok] `Not applicable`
  - Event 15 (diagnosis, date=26/09/2022): [ok] `Not applicable`
  - Event 16 (other_treatment, date=29/09/2022): [ok] `Not applicable`
- **Gold annotation:** `therapeutic (radiotherapy without surgery) radiotherapy (conventional) with palliative intention started [please select `

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 2.07s):
  - `Type of recurrence/progression: metastatic.`
- **With splitting** (6 values, 14.88s):
  - [1] `Type of recurrence/progression: Not applicable`
  - [2] `Type of recurrence/progression: None`
  - [3] `Type of recurrence/progression: progressione di malattia`
  - [4] `Type of recurrence/progression: metastatic bone.`
  - [5] `Type of recurrence/progression: metastatic liver, lung.`
  - [6] `Type of recurrence/progression: metastatic soft tissue.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=09/2019): [ok] `Not applicable`
  - Event 1 (diagnosis, date=18/11/2019): [ok] `Type of recurrence/progression: Not applicable`
  - Event 2 (diagnosis, date=24/12/2019): [ok] `Type of recurrence/progression: None`
  - Event 3 (surgery, date=30/01/2020): [ok] `Type of recurrence/progression: None`
  - Event 4 (surgery, date=28/05/2020): [ok] `Type of recurrence/progression: None`
  - Event 5 (follow_up, date=03/2021): [ok] `Not applicable`
  - Event 6 (diagnosis, date=06/2021): [ok] `Type of recurrence/progression: progressione di malattia`
  - Event 7 (radiotherapy, date=2021): [ok] `Not applicable`
  - Event 8 (diagnosis, date=2021): [ok] `Type of recurrence/progression: None`
  - Event 9 (other_treatment, date=25/07/2021): [ok] `Not applicable`
  - Event 10 (follow_up, date=09/2021): [ok] `Type of recurrence/progression: None`
  - Event 11 (diagnosis, date=09/2021): [ok] `Not applicable`
  - Event 12 (surgery, date=28/07/2022): [ok] `Type of recurrence/progression: metastatic bone.`
  - Event 13 (diagnosis, date=26/09/2022): [ok] `Type of recurrence/progression: metastatic liver, lung.`
  - Event 14 (diagnosis, date=26/09/2022): [ok] `Type of recurrence/progression: metastatic.`
  - Event 15 (diagnosis, date=26/09/2022): [ok] `Type of recurrence/progression: metastatic soft tissue.`
  - Event 16 (other_treatment, date=29/09/2022): [ok] `Not applicable`
- **Gold annotation:** `Type of recurrence/progression: local [select site if metastatic].`

**surgerytype-int-sarc** [**+**]

- **Baseline** (1 value, 1.18s):
  - `Local excision was performed on 18/11/2019 and was macroscopically complete.`
- **With splitting** (6 values, 13.82s):
  - [1] `Surgical procedure was performed on 09/2019 and was macroscopically.`
  - [2] `Surgical procedure was performed on 30/01/2020 and was macroscopically.`
  - [3] `Surgical procedure was performed on 28/05/2020 and was macroscopically complete.`
  - [4] `Local excision was performed on 09/2021 and was macroscopically complete.`
  - [5] `Surgical procedure was performed on 28/07/2022 and was macroscopically.`
  - [6] `Surgical procedure was performed on DD/MM/YYYY and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (surgery, date=09/2019): [ok] `Surgical procedure was performed on 09/2019 and was macroscopically.`
  - Event 1 (diagnosis, date=18/11/2019): [ok] `Not applicable`
  - Event 2 (diagnosis, date=24/12/2019): [ok] `Not applicable`
  - Event 3 (surgery, date=30/01/2020): [ok] `Surgical procedure was performed on 30/01/2020 and was macroscopically.`
  - Event 4 (surgery, date=28/05/2020): [ok] `Surgical procedure was performed on 28/05/2020 and was macroscopically complete.`
  - Event 5 (follow_up, date=03/2021): [ok] `Not applicable`
  - Event 6 (diagnosis, date=06/2021): [ok] `Not applicable`
  - Event 7 (radiotherapy, date=2021): [ok] `Not applicable`
  - Event 8 (diagnosis, date=2021): [ok] `Not applicable`
  - Event 9 (other_treatment, date=25/07/2021): [ok] `Not applicable`
  - Event 10 (follow_up, date=09/2021): [ok] `Not applicable`
  - Event 11 (diagnosis, date=09/2021): [ok] `Local excision was performed on 09/2021 and was macroscopically complete.`
  - Event 12 (surgery, date=28/07/2022): [ok] `Surgical procedure was performed on 28/07/2022 and was macroscopically.`
  - Event 13 (diagnosis, date=26/09/2022): [ok] `Not applicable`
  - Event 14 (diagnosis, date=26/09/2022): [ok] `Not applicable`
  - Event 15 (diagnosis, date=26/09/2022): [ok] `Surgical procedure was performed on DD/MM/YYYY and was macroscopically complete.`
  - Event 16 (other_treatment, date=29/09/2022): [ok] `Not applicable`

---

### Note 7: `{[DWH_Data].[DOC]|AMB_ROL_due|ds_ana_remota|163235|423557|1}`

**Detection:** confidence=0.60, dates=2, markers=5, treatments=['surgery', 'chemotherapy']

**Split result:** 1 events (split_time=25.39s, was_split=False)

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 1.8s):
  - `post-operative chemotherapy with palliative started on 09.03.2021 and utilized gemcitabine+dacarbazina regimen.`
- **With splitting** (1 values, 0.0s):
  - [1] `post-operative chemotherapy with palliative started on 09.03.2021 and utilized gemcitabine+dacarbazina regimen.`
- **Gold annotation:** `post-operative chemotherapy ended on 15/01/2020 after 5 of cycles because of completion.`

**radiotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 0.72s):
  - `Not applicable`
- **With splitting** (1 values, 0.0s):
  - [1] `Not applicable`

**recurrencetype-int-sarc** [=]

- **Baseline** (1 value, 0.78s):
  - `Type of recurrence/progression: metastatic`
- **With splitting** (1 values, 0.0s):
  - [1] `Type of recurrence/progression: metastatic`

**surgerytype-int-sarc** [=]

- **Baseline** (1 value, 1.33s):
  - `Surgical procedure was performed on 06/03/2019 and was macroscopically complete.`
- **With splitting** (1 values, 0.0s):
  - [1] `06/03/2019`

---

### Note 8: `{[DWH_Data].[DOC]|AMB_ROL_due|ds_sint_clin|94012|423557|1}`

**Detection:** confidence=0.50, dates=1, markers=3, treatments=['chemotherapy', 'recurrence']

**Split result:** 7 events (split_time=3.02s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.55s):
  - `post-operative chemotherapy with curative started on 21.6.2019 and utilized gemcitabine + dacarbazine regimen.`
- **With splitting** (2 values, 4.52s):
  - [1] `post-operative chemotherapy with ongoing treatment started on and utilized gemcitabine + dacarbazine regimen.`
  - [2] `post-operative chemotherapy with started on and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=null): [ok] `Not applicable`
  - Event 1 (surgery, date=21/06/2019): [ok] `Not applicable`
  - Event 2 (chemotherapy, date=null): [ok] `post-operative chemotherapy with ongoing treatment started on and utilized gemcitabine + dacarbazine`
  - Event 3 (other, date=null): [ok] `Not applicable`
  - Event 4 (other, date=null): [ok] `Not applicable`
  - Event 5 (other, date=null): [ok] `Not applicable`
  - Event 6 (other, date=null): [ok] `post-operative chemotherapy with started on and utilized regimen.`

**radiotherapy_start-int-sarc** [=]

- **Baseline** (1 value, 1.16s):
  - `Not applicable`
- **With splitting** (1 values, 4.28s):
  - [1] `Not applicable`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=null): [ok] `Not applicable`
  - Event 1 (surgery, date=21/06/2019): [ok] `Not applicable`
  - Event 2 (chemotherapy, date=null): [ok] `Not applicable`
  - Event 3 (other, date=null): [ok] `Not applicable`
  - Event 4 (other, date=null): [ok] `Not applicable`
  - Event 5 (other, date=null): [ok] `Not applicable`
  - Event 6 (other, date=null): [ok] `Not applicable`

**recurrencetype-int-sarc** [=]

- **Baseline** (1 value, 0.96s):
  - `Not applicable`
- **With splitting** (1 values, 4.98s):
  - [1] `Type of recurrence/progression: None`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=null): [ok] `Not applicable`
  - Event 1 (surgery, date=21/06/2019): [ok] `Not applicable`
  - Event 2 (chemotherapy, date=null): [ok] `Not applicable`
  - Event 3 (other, date=null): [ok] `Not applicable`
  - Event 4 (other, date=null): [ok] `Type of recurrence/progression: None`
  - Event 5 (other, date=null): [ok] `Type of recurrence/progression: None`
  - Event 6 (other, date=null): [ok] `Not applicable`

**surgerytype-int-sarc** [=]

- **Baseline** (1 value, 1.2s):
  - `Surgical procedure was performed on 21.6.2019 and was macroscopically complete.`
- **With splitting** (1 values, 4.55s):
  - [1] `Surgical procedure was performed on 21/06/2019 and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=null): [ok] `Not applicable`
  - Event 1 (surgery, date=21/06/2019): [ok] `Surgical procedure was performed on 21/06/2019 and was macroscopically complete.`
  - Event 2 (chemotherapy, date=null): [ok] `Not applicable`
  - Event 3 (other, date=null): [ok] `Not applicable`
  - Event 4 (other, date=null): [ok] `Not applicable`
  - Event 5 (other, date=null): [ok] `Not applicable`
  - Event 6 (other, date=null): [ok] `Not applicable`

---

### Note 9: `{[DWH_Data].[DOC]|INT_Anamnesi|ds_evoluzione_storia|48869|70`

**Detection:** confidence=0.50, dates=6, markers=1, treatments=['surgery', 'chemotherapy']

**Split result:** 10 events (split_time=4.55s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.24s):
  - `post-operative chemotherapy with Epirubicina-Ifosfamide started on 13/11/2019 and utilized Epirubicina-Ifosfamide regime`
- **With splitting** (3 values, 8.51s):
  - [1] `post-operative chemotherapy with intra-tumor injection started on 25/10/2019 and utilized intra-tumor injection regimen.`
  - [2] `post-operative chemotherapy with INT started on 13/11/2019 and utilized Epirubicina-Ifosfamide regimen.`
  - [3] `post-operative chemotherapy with INT, RT started on 09/12/2019 and utilized INT, RT regimen.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=2017-09-01): [ok] `Not applicable`
  - Event 1 (surgery, date=2018-01-01): [ok] `Not applicable`
  - Event 2 (diagnosis, date=2018-01-01): [ok] `Not applicable`
  - Event 3 (recurrence, date=2018-10-01): [ok] `Not applicable`
  - Event 4 (biopsy, date=2019-10-25): [ok] `post-operative chemotherapy with intra-tumor injection started on 25/10/2019 and utilized intra-tumo`
  - Event 5 (diagnosis, date=2019-10-25): [ok] `Not applicable`
  - Event 6 (chemotherapy, date=2019-11-13): [ok] `post-operative chemotherapy with INT started on 13/11/2019 and utilized Epirubicina-Ifosfamide regim`
  - Event 7 (radiotherapy, date=2019-12-09): [ok] `post-operative chemotherapy with INT, RT started on 09/12/2019 and utilized INT, RT regimen.`
  - Event 8 (surgery, date=2020-02-28): [ok] `Not applicable`
  - Event 9 (other_treatment, date=2020-02-28): [ok] `Not applicable`
- **Gold annotation:** `pre-operative chemotherapy with curative started on 13/11/2019 and utilized Epirubicin + Ifosfamide regimen.`

**radiotherapy_start-int-sarc** [**+**]

- **Baseline** (1 value, 1.18s):
  - `post-operative radiotherapy with intention started [please select where] on.`
- **With splitting** (2 values, 8.41s):
  - [1] `pre-operative radiotherapy with INT intention started 09/12/2019 on 20/01/2020.`
  - [2] `post-operative radiotherapy with intention started [please select where] on.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=2017-09-01): [ok] `Not applicable`
  - Event 1 (surgery, date=2018-01-01): [ok] `Not applicable`
  - Event 2 (diagnosis, date=2018-01-01): [ok] `Not applicable`
  - Event 3 (recurrence, date=2018-10-01): [ok] `Not applicable`
  - Event 4 (biopsy, date=2019-10-25): [ok] `Not applicable`
  - Event 5 (diagnosis, date=2019-10-25): [ok] `Not applicable`
  - Event 6 (chemotherapy, date=2019-11-13): [ok] `Not applicable`
  - Event 7 (radiotherapy, date=2019-12-09): [ok] `pre-operative radiotherapy with INT intention started 09/12/2019 on 20/01/2020.`
  - Event 8 (surgery, date=2020-02-28): [ok] `post-operative radiotherapy with intention started [please select where] on.`
  - Event 9 (other_treatment, date=2020-02-28): [ok] `post-operative radiotherapy with intention started [please select where] on.`
- **Gold annotation:** `pre-operative radiotherapy (conventional) with curative intention started at the hosptial on 09/12/2019.`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 1.0s):
  - `Type of recurrence/progression: local`
- **With splitting** (4 values, 8.05s):
  - [1] `Type of recurrence/progression: local.`
  - [2] `Type of recurrence/progression: Not applicable`
  - [3] `Type of recurrence/progression: metastatic soft tissue.`
  - [4] `Type of recurrence/progression: None`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=2017-09-01): [ok] `Type of recurrence/progression: local.`
  - Event 1 (surgery, date=2018-01-01): [ok] `Not applicable`
  - Event 2 (diagnosis, date=2018-01-01): [ok] `Type of recurrence/progression: Not applicable`
  - Event 3 (recurrence, date=2018-10-01): [ok] `Type of recurrence/progression: local.`
  - Event 4 (biopsy, date=2019-10-25): [ok] `Not applicable`
  - Event 5 (diagnosis, date=2019-10-25): [ok] `Type of recurrence/progression: metastatic soft tissue.`
  - Event 6 (chemotherapy, date=2019-11-13): [ok] `Not applicable`
  - Event 7 (radiotherapy, date=2019-12-09): [ok] `Not applicable`
  - Event 8 (surgery, date=2020-02-28): [ok] `Type of recurrence/progression: metastatic soft tissue.`
  - Event 9 (other_treatment, date=2020-02-28): [ok] `Type of recurrence/progression: None`
- **Gold annotation:** `Type of recurrence/progression: local soft tissue.`

**surgerytype-int-sarc** [**+**]

- **Baseline** (1 value, 1.71s):
  - `Limb operation was performed on 20/02/2020 and was macroscopically complete.`
- **With splitting** (3 values, 7.94s):
  - [1] `Surgical procedure was performed on 10/10/2018 and was macroscopically.`
  - [2] `Surgical procedure was performed on 28/02/2020 and was macroscopically complete.`
  - [3] `Surgical procedure was performed on 29/07/2020 and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=2017-09-01): [ok] `Not applicable`
  - Event 1 (surgery, date=2018-01-01): [ok] `Surgical procedure was performed on 29/07/2020 and was macroscopically complete.`
  - Event 2 (diagnosis, date=2018-01-01): [ok] `Not applicable`
  - Event 3 (recurrence, date=2018-10-01): [ok] `Surgical procedure was performed on 10/10/2018 and was macroscopically.`
  - Event 4 (biopsy, date=2019-10-25): [ok] `Not applicable`
  - Event 5 (diagnosis, date=2019-10-25): [ok] `Not applicable`
  - Event 6 (chemotherapy, date=2019-11-13): [ok] `Not applicable`
  - Event 7 (radiotherapy, date=2019-12-09): [ok] `Not applicable`
  - Event 8 (surgery, date=2020-02-28): [ok] `Surgical procedure was performed on 28/02/2020 and was macroscopically complete.`
  - Event 9 (other_treatment, date=2020-02-28): [ok] `Not applicable`

---

### Note 10: `{[DWH_Data].[DOC]|INT_LDO_ROL|ds_ana_remota|21036|71215|1}`

**Detection:** confidence=0.50, dates=10, markers=1, treatments=['chemotherapy', 'recurrence']

**Split result:** 9 events (split_time=5.76s, was_split=True)

**Shared context:** Patient-level information: demographics, primary cancer diagnosis, key identifiers

#### Prompt Comparisons

**chemotherapy_start-int-sarc** [-]

- **Baseline** (2 value, 1.42s):
  - `pre-operative chemotherapy with pre-operative started on 21/02/2020 and utilized RT regimen.
post-operative chemotherapy`
- **With splitting** (1 values, 7.58s):
  - [1] `post-operative chemotherapy with started on and utilized regimen.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=29/11/2019): [ok] `Not applicable`
  - Event 1 (biopsy, date=08/01/2020): [ok] `Not applicable`
  - Event 2 (diagnosis, date=20/01/2020): [ok] `Not applicable`
  - Event 3 (diagnosis, date=05/02/2020): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 4 (radiotherapy, date=21/02/2020-01/04/2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=28/04/2020): [ok] `Not applicable`
  - Event 6 (other_treatment, date=11/05/2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=14/05/2020): [ok] `post-operative chemotherapy with started on and utilized regimen.`
  - Event 8 (follow_up, date=15/05/2020): [ok] `Not applicable`

**radiotherapy_start-int-sarc** [**+**]

- **Baseline** (2 value, 1.39s):
  - `pre-operative radiotherapy with pre-operative intention started 21/02/2020-01/04/2020.`
- **With splitting** (3 values, 8.71s):
  - [1] `pre-operative radiotherapy with pre-operative intention started 21/02/2020 on 01/04/2020.`
  - [2] `post-operative radiotherapy (conventional) with select intention started 15/05/2020 on 15/05/2020.`
  - [3] `post-operative radiotherapy (conventional) with intention started [please select where] on.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=29/11/2019): [ok] `Not applicable`
  - Event 1 (biopsy, date=08/01/2020): [ok] `Not applicable`
  - Event 2 (diagnosis, date=20/01/2020): [ok] `Not applicable`
  - Event 3 (diagnosis, date=05/02/2020): [ok] `Not applicable`
  - Event 4 (radiotherapy, date=21/02/2020-01/04/2020): [ok] `pre-operative radiotherapy with pre-operative intention started 21/02/2020 on 01/04/2020.`
  - Event 5 (follow_up, date=28/04/2020): [ok] `Not applicable`
  - Event 6 (other_treatment, date=11/05/2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=14/05/2020): [ok] `post-operative radiotherapy (conventional) with intention started [please select where] on.`
  - Event 8 (follow_up, date=15/05/2020): [ok] `post-operative radiotherapy (conventional) with select intention started 15/05/2020 on 15/05/2020.`
- **Gold annotation:** `pre-operative radiotherapy (conventional) with curative intention started [please select where] on 21/02/2020.`

**recurrencetype-int-sarc** [**+**]

- **Baseline** (1 value, 2.15s):
  - `Type of recurrence/progression: local.`
- **With splitting** (3 values, 7.75s):
  - [1] `Type of recurrence/progression: metastatic.`
  - [2] `Type of recurrence/progression: local.`
  - [3] `Type of recurrence/progression: None`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=29/11/2019): [ok] `Type of recurrence/progression: metastatic`
  - Event 1 (biopsy, date=08/01/2020): [ok] `Type of recurrence/progression: metastatic.`
  - Event 2 (diagnosis, date=20/01/2020): [ok] `Type of recurrence/progression: local.`
  - Event 3 (diagnosis, date=05/02/2020): [ok] `Type of recurrence/progression: local`
  - Event 4 (radiotherapy, date=21/02/2020-01/04/2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=28/04/2020): [ok] `Type of recurrence/progression: None`
  - Event 6 (other_treatment, date=11/05/2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=14/05/2020): [ok] `Not applicable`
  - Event 8 (follow_up, date=15/05/2020): [ok] `Type of recurrence/progression: local`

**surgerytype-int-sarc** [**+**]

- **Baseline** (1 value, 1.96s):
  - `Not applicable`
- **With splitting** (3 values, 9.02s):
  - [1] `Surgical procedure was performed on 29/11/2019 and was macroscopically complete.`
  - [2] `Surgical procedure was performed on 14/05/2020 and was macroscopically.`
  - [3] `Surgical procedure was performed on 15/05/2020 and was macroscopically complete.`
- **Sub-note extractions:**
  - Event 0 (diagnosis, date=29/11/2019): [ok] `Surgical procedure was performed on 29/11/2019 and was macroscopically complete.`
  - Event 1 (biopsy, date=08/01/2020): [ok] `Not applicable`
  - Event 2 (diagnosis, date=20/01/2020): [ok] `Not applicable`
  - Event 3 (diagnosis, date=05/02/2020): [ok] `Not applicable`
  - Event 4 (radiotherapy, date=21/02/2020-01/04/2020): [ok] `Not applicable`
  - Event 5 (follow_up, date=28/04/2020): [ok] `Not applicable`
  - Event 6 (other_treatment, date=11/05/2020): [ok] `Not applicable`
  - Event 7 (follow_up, date=14/05/2020): [ok] `Surgical procedure was performed on 14/05/2020 and was macroscopically.`
  - Event 8 (follow_up, date=15/05/2020): [ok] `Surgical procedure was performed on 15/05/2020 and was macroscopically complete.`

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
