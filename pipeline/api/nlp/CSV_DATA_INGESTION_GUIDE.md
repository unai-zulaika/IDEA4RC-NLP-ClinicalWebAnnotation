# CSV Data Ingestion Guide for NLP Pipeline

## Overview

This guide describes how to prepare CSV files for ingestion into the IDEA4RC NLP pipeline. The pipeline processes clinical notes using LLM-based annotation and regex pattern matching to extract structured medical data.

---

## Required CSV Format

### File Structure

| Column | Header Name | Data Type | Required | Description |
|--------|-------------|-----------|----------|-------------|
| A | `text` | String | **Yes** | The clinical note text content |
| B | `date` | Date | **Yes** | Date of the clinical note |
| C | `p_id` | Integer/String | **Yes** | Patient identifier |
| D | `note_id` | Integer | **Yes** | Unique note identifier |
| E | `report_type` | String | **Yes** | Type of clinical report |

### Visual Example

```
┌────────────────────────────────────────────────────┬────────────┬──────┬─────────┬──────────────┐
│ text                                               │ date       │ p_id │ note_id │ report_type  │
├────────────────────────────────────────────────────┼────────────┼──────┼─────────┼──────────────┤
│ Lorem ipsum dolor sit amet, consectetur...         │ 14/03/2024 │ 3    │ 1       │ radiology    │
│ Patient's BMI is 23.5. The diagnosis was...        │ 14/08/2023 │ 3    │ 2       │ radiology    │
│ Mauris a velit sed urna molestie elementum...      │ 14/03/2024 │ 3    │ 3       │ radiology    │
│ Quisque mollis, dolor non tincidunt eleifend...    │ 14/03/2024 │ 3    │ 4       │ radiology    │
│ Phasellus bibendum purus vel pulvinar fringilla... │ 14/03/2024 │ 3    │ 5       │ staging      │
│ Charlson Comorbidity index 3                       │ 14/03/2024 │ 3    │ 6       │ radiology    │
│ Fusce auctor sagittis maximus. Morbi sodales...    │ 14/03/2024 │ 3    │ 7       │ consultation │
│ Margins after surgery: R2                          │ 14/08/2023 │ 3    │ 8       │ radiology    │
└────────────────────────────────────────────────────┴────────────┴──────┴─────────┴──────────────┘
```

---

## Column Specifications

### 1. `text` (Column A)

**Description:** Contains the full clinical note text that will be processed by the NLP pipeline.

**Requirements:**
- Can contain multi-line text (paragraphs)
- Must be enclosed in double quotes (`"`) if it contains:
  - Line breaks
  - The delimiter character (semicolon `;` or comma `,`)
  - Double quotes (escape as `""`)
- No maximum length limit, but longer texts increase processing time

**Example content:**
```
"Adam Martinez presented to the clinic complaining of mild discomfort in the affected region. During initial evaluation on 15/11/2024, basic physical examination and imaging studies were performed.

Radiological assessment suggested a lesion measuring approximately 35 mm located in the lower limb. Pathology later confirmed the diagnosis of leiomyosarcoma. A biopsy was performed, and the FNCLCC grade was determined to be 3.

The multidisciplinary team discussed the case and decided on post-operative radiotherapy with curative intent."
```

### 2. `date` (Column B)

**Description:** The date associated with the clinical note.

**Supported formats:**
| Format | Example | Notes |
|--------|---------|-------|
| `DD/MM/YYYY` | `14/03/2024` | **Preferred** |
| `YYYY-MM-DD` | `2024-03-14` | ISO 8601 format |
| `D/M/YYYY` | `3/5/2024` | Single-digit day/month |

**Requirements:**
- Must be a valid date
- Used as fallback reference date if no date is extracted from the text

### 3. `p_id` (Column C)

**Description:** Patient identifier used to group related records.

**Requirements:**
- Must be unique per patient
- Can be integer or string
- Will be propagated to all extracted entities for the same patient

**Examples:** `3`, `5`, `9`, `PAT001`, `P-2024-001`

### 4. `note_id` (Column D)

**Description:** Unique identifier for each clinical note.

**Requirements:**
- Must be unique across the dataset
- Used for traceability back to source documents
- Integer values recommended

**Examples:** `1`, `2`, `3`, `100`, `2024001`

### 5. `report_type` (Column E)

**Description:** Classification of the clinical document type.

**Common values:**

| Value | Description |
|-------|-------------|
| `radiology` | Imaging and radiology reports |
| `staging` | Cancer staging assessments |
| `oncology` | Oncology consultation notes |
| `consultation` | General consultation records |
| `pathology` | Pathology/biopsy reports |
| `surgery` | Surgical notes and reports |
| `follow-up` | Follow-up visit notes |

---

## Delimiter Configuration

The pipeline **auto-detects** the delimiter based on the first line of the CSV file.

### Supported Delimiters

| Delimiter | Character | When to Use |
|-----------|-----------|-------------|
| Semicolon | `;` | **Recommended** - Better for European formats and text with commas |
| Comma | `,` | Standard CSV format |

### Semicolon-Delimited Example (Recommended)

```csv
text;date;p_id;note_id;report_type
"Patient's BMI is 23.5. The diagnosis was Hypertension.";14/08/2023;3;2;radiology
"Charlson Comorbidity index 3";14/03/2024;3;6;radiology
```

### Comma-Delimited Example

```csv
text,date,p_id,note_id,report_type
"Patient's BMI is 23.5. The diagnosis was Hypertension.",14/08/2023,3,2,radiology
"Charlson Comorbidity index 3",14/03/2024,3,6,radiology
```

---

## Multi-line Text Handling

Clinical notes often span multiple paragraphs. The pipeline handles multi-line text automatically.

### Using Excel or Spreadsheet Applications

Simply paste or type your multi-paragraph text directly into the cell. When you save as CSV, the application automatically handles the formatting.

```
┌────────────────────────────────────────────────────────────────┐
│ text (Column A)                                                │
├────────────────────────────────────────────────────────────────┤
│ Adam Martinez presented to the clinic complaining of mild      │
│ discomfort.                                                    │
│                                                                │
│ Radiological assessment suggested a lesion measuring           │
│ approximately 35 mm.                                           │
│                                                                │
│ The multidisciplinary team discussed the case.                 │
└────────────────────────────────────────────────────────────────┘
```

### Creating CSV Manually (Text Editor)

If you're editing the raw CSV file directly in a text editor, multi-line text will be quoted automatically by most CSV tools. The pipeline's `pandas.read_csv()` function handles both quoted and standard text seamlessly.

> **Note:** You do not need to manually add quotes around your text. The pipeline processes the content regardless of quoting.

---

## Special Character Handling

The pipeline handles special characters automatically. When using Excel or spreadsheet applications, simply type your text normally—the application manages CSV formatting on export.

### Quotes Within Text

Clinical notes can contain double quotes without any special handling:

```
Patient stated "I feel better today" during follow-up.
```

### Semicolons and Commas Within Text

Text can contain semicolons, commas, and other punctuation naturally:

```
Diagnosis: leiomyosarcoma; Grade: 3; Location: lower limb
```

> **Note:** When exporting from Excel, these characters are handled automatically. Manual CSV editing may require standard CSV escaping rules.

---

## Complete Example File

Below is a complete, valid example CSV file:

```csv
text;date;p_id;note_id;report_type
"Adam Martinez presented to the clinic complaining of mild discomfort in the affected region. During initial evaluation on 15/11/2024, basic physical examination and imaging studies were performed. The patient appeared stable and cooperative, reporting previous medical history including no relevant comorbidities. 

Radiological assessment suggested a lesion measuring approximately 35 mm located in the lower limb. Pathology later confirmed the diagnosis of leiomyosarcoma. A biopsy was performed, and the FNCLCC grade was determined to be 3. The tumor depth was classified as superficial, and mitotic count reported as not assessable. 

The multidisciplinary team discussed the case and decided on post-operative radiotherapy with curative intent. The treatment started on 10/05/2025 and response was partial response. The patient was last seen on 08/10/2025 and was noted to be alive with no evidence of disease. ";15/11/2024;5;1;staging
"Kathryn Kaiser MD presented to the clinic complaining of mild discomfort in the affected region. During initial evaluation on 22/02/2025, basic physical examination and imaging studies were performed. The patient appeared stable and cooperative, reporting previous medical history including diabetes mellitus type II. 

Radiological assessment suggested a lesion measuring approximately 116 mm located in the lower limb. Pathology later confirmed the diagnosis of synovial sarcoma. A biopsy was performed, and the FNCLCC grade was determined to be 2. The tumor depth was classified as deep, and mitotic count reported as not assessable. 

The multidisciplinary team discussed the case and decided on pre-operative chemotherapy with curative intent. The treatment started on 18/07/2025 and response was stable disease. The patient was last seen on 08/10/2025 and was noted to be alive with no evidence of disease. ";22/02/2025;9;2;oncology
```

---

## Validation Checklist

Before submitting your CSV file, verify:

- [ ] **Header row present** with exact column names: `text`, `date`, `p_id`, `note_id`, `report_type`
- [ ] **All 5 columns populated** for every row
- [ ] **Dates in valid format** (DD/MM/YYYY or YYYY-MM-DD)
- [ ] **Consistent delimiter** throughout the file
- [ ] **UTF-8 encoding** used for the file
- [ ] **No trailing commas/semicolons** at end of rows
- [ ] **Unique `note_id`** values across the dataset

---

## Encoding Requirements

| Setting | Value |
|---------|-------|
| Character Encoding | **UTF-8** |
| Line Endings | LF (`\n`) or CRLF (`\r\n`) |
| BOM (Byte Order Mark) | Not required, but supported |

---

## Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `KeyError: 'text'` | Missing or misspelled header | Ensure header row has exact column names |
| `ParserError` | Malformed CSV structure | Re-export from Excel using "CSV UTF-8" format |
| Empty values extracted | Invalid date format | Use DD/MM/YYYY or YYYY-MM-DD |
| Missing patient data | Empty `p_id` values | Ensure all rows have patient IDs |
| Duplicate records | Same `note_id` used twice | Use unique note identifiers |

---

## Excel Export Instructions

If creating the CSV from Microsoft Excel:

1. **Prepare your data** with columns in order: text, date, p_id, note_id, report_type
2. **File → Save As**
3. Select **"CSV UTF-8 (Comma delimited) (*.csv)"**
4. Click **Save**

> **Note:** Excel uses comma as default delimiter. If you need semicolon delimiter, use "Save As" → "CSV (MS-DOS)" and manually replace commas in a text editor, or configure your system's list separator.

---

## Contact

For questions about data formatting or pipeline issues, contact the IDEA4RC NLP team.

---

*Document Version: 1.0*  
*Last Updated: November 2024*

