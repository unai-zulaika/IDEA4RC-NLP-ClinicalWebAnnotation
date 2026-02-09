import pandas as pd
import json
from pathlib import Path
import re
from itertools import count


# data = pd.read_excel(
#     "/home/zulaika/IDEA4RC-NLP-Ingestion/api/nlp/sarcoma_dictionary___v1_0_14_5_2025_18_34_59.xlsx",
#     sheet_name="Sentences",
#     engine='openpyxl'
# )

# final_json = {}
# regexp_json = {}
# values_json = {}

# # loop data rows
# for index, row in data.iterrows():
#     # get the first column value
#     sentence_id = row["SENTENCE_ID"]

#     # get the third column value
#     sentence_name = row["SENTENCE_NAME"]

#     sentence_content = row["SENTENCE_CONTENT"]

#     # create a dictionary for the current row
#     row_dict = {
#         "sentence_id": sentence_id,
#         "sentence_name": sentence_name,
#         "sentence_content": sentence_content,
#         "parameters": []
#     }

#     # add the row dictionary to the final JSON under the first column value as key
#     final_json[sentence_id] = row_dict
#     regexp_json[sentence_id] = ""

# data = pd.read_excel(
#     "/home/zulaika/IDEA4RC-NLP-Ingestion/api/nlp/sarcoma_dictionary___v1_0_14_5_2025_18_34_59.xlsx",
#     sheet_name="Parameters",
#     engine='openpyxl'
# )

# for index, row in data.iterrows():
#     # get the first column value
#     sentence_id = row["SENTENCE_ID"]

#     # get the third column value
#     parameter_name = row["PARAMETER_NAME"]

#     parameter_type = row["PARAMETER_TYPE"]
#     possible_values = row["LIST_CONTENT"]
#     # separate possible values by comma if they are not empty
#     if pd.isna(possible_values):
#         possible_values = []
#     else:
#         possible_values = [value.strip() for value in possible_values.split(",") if value.strip()]

#     # create a dictionary for the current row
#     row_dict = {
#         "parameter_name": parameter_name,
#         "parameter_type": parameter_type,
#         "possible_values": [{value: ""} for value in possible_values],
#         "associated_variable": "",
#     }

#     # add the row dictionary to the final JSON under the first column value as key
#     final_json[sentence_id]["parameters"].append(row_dict)
#     for value in possible_values:
#         values_json[f"{sentence_id}_{value}"] = ""


#     # now save json
# output_path = Path("sarcoma_dictionary_updated.json")
# with open(output_path, "w") as f:
#     json.dump(final_json, f, indent=4)

# # save regexp json
# output_path = Path("sarcoma_dictionary_regexp_updated.json")
# with open(output_path, "w") as f:
#     json.dump(regexp_json, f, indent=4)
# # save values json
# output_path = Path("sarcoma_dictionary_values_updated.json")
# with open(output_path, "w") as f:
#     json.dump(values_json, f, indent=4)


# open the sarcoma_dictionary.json
with open("sarcoma_dictionary.json", "r") as f:
    sarcoma_dict = json.load(f)

new_regexp_dict = {}

# loop each element
for key, value in sarcoma_dict.items():
    sentence = value["sentence_content"]

    # find all placeholders
    slots = list(re.finditer(r'\[.*?\]', sentence))

    # use a counter instead of nonlocal idx
    slot_counter = count(0)

    def replace_slot(m):
        i = next(slot_counter)
        is_last = i == len(slots) - 1
        # for the last slot, capture up to the period/EOL; otherwise use lazy
        return r'([^.]+)' if is_last else r'(.+?)'

    # build regex
    regexp = re.sub(r'\[.*?\]', replace_slot, sentence)
    # allow optional trailing period/whitespace
    if regexp.strip().endswith('([^.]+)'):
        regexp = regexp + r'\s*(?:\.|$)'

    new_regexp_dict[key] = regexp

# save the new regexp dictionary
output_path = Path("auto_regexp.json")
with open(output_path, "w") as f:
    json.dump(new_regexp_dict, f, indent=4)
