from sklearn.model_selection import train_test_split
import pandas as pd
from unsloth import FastLanguageModel, is_bfloat16_supported
from unsloth.chat_templates import get_chat_template
import torch
import os
import unicodedata
from datasets import load_dataset
from transformers import TrainingArguments, TextStreamer
from trl import SFTTrainer, SFTConfig
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from sentence_transformers import SentenceTransformer
from sentence_transformers import SentenceTransformer, util


## START NEW ADD ###

# Read DataFrames from CSV files
df1 = pd.read_csv('Swedish_data.csv')
merged_df = df1.dropna(
    subset=['annotation', 'note_original_text', 'processed_highlight'])

# Print sizes of the original DataFrames
print(f"\n\nSize of Phase 1 Data: {merged_df.shape}")


def filter_annotations(example):
    annotation = example["annotation"]
    if annotation is None:
        return False  # Skip rows with missing annotations
    return example["annotation"].startswith("Histolog")


df_filtered = merged_df[merged_df.apply(filter_annotations, axis=1)]
build_task_index("histology", df_filtered)
