from linking_service import link_rows
import pandas as pd


# load file from test_data
data = pd.read_excel(
    "/home/zulaika/IDEA4RC-NLP-Ingestion/test_data/MSCI_DEMO_NT_V2_CLEAN.xlsx",
)

link_rows(data, linking_criteria={"by_date": True})
