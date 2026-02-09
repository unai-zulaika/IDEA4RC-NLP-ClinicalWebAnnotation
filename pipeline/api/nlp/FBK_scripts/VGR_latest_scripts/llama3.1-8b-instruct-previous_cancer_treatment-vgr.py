from unsloth import FastLanguageModel, is_bfloat16_supported
from unsloth.chat_templates import get_chat_template
import torch, os
import unicodedata
from datasets import load_dataset
from transformers import TrainingArguments, TextStreamer
from trl import SFTTrainer, SFTConfig
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from sentence_transformers import SentenceTransformer
from sentence_transformers import SentenceTransformer, util

# Load model and tokenizer
model, tokenizer = FastLanguageModel.from_pretrained(
#    model_name = "TheBloke/Llama-2-7B-fp16",
    model_name = "unsloth/Meta-Llama-3.1-8B-Instruct",
#    model_name = "/data/disk1/share/sghosh/saved_models/rag/surgery/llama2-7b_fp16-surgery-rag_w_test_window/llama_2_7b-surgery-rag",
    max_seq_length=100000,
    dtype=None,
    load_in_4bit=True,
#    gpu_memory_utilization = 0.6 # Reduce if out of memory
)

# Set up the chat template
tokenizer = get_chat_template(
    tokenizer,
    mapping={"role": "from", "content": "value", "user": "human", "assistant": "gpt"},
    chat_template="chatml",
)

## START NEW ADD ###
import pandas as pd
from sklearn.model_selection import train_test_split

# Read DataFrames from CSV files
df1 = pd.read_csv('Swedish_data.csv')
merged_df = df1.dropna(subset=['annotation', 'note_original_text'])

# Print sizes of the original DataFrames
print(f"\n\nSize of Phase 1 Data: {merged_df.shape}")

def filter_annotations(example):
    annotation = example["annotation"]
    if annotation is None:
        return False  # Skip rows with missing annotations
    return "previous cancer treatment" in annotation.lower()

df_filtered = merged_df[merged_df.apply(filter_annotations, axis=1)]
# Count rows before duplicate removal
before = len(df_filtered)
print('Before: ', before)
# Drop duplicates
df_filtered = df_filtered.drop_duplicates(subset=["note_original_text", "annotation"], keep='first')

# Count rows after duplicate removal
after = len(df_filtered)
print('After: ', after)

# Print number of duplicates removed
print(f"Duplicates removed: {before - after}")


# Split into train (72%), dev (8%), and test (20%)
train_df, test_df = train_test_split(df_filtered, test_size=0.2, random_state=42)
#train_df, dev_df = train_test_split(temp_df, test_size=0.1, random_state=42)

#fewshot_df = train_df+dev_df
fewshot_df = test_df
#test_df = train_df.sample(n=50, random_state=42)
test_df = train_df
train_df = fewshot_df

# Sample one row for each distinct category
sampled_df = train_df.drop_duplicates(subset=['annotation'], keep='first')

from datasets import Dataset, DatasetDict


# Assuming train_df, test_df, dev_df are already loaded and filtered

# Initialize SentenceTransformer model for embeddings
embedding_model = SentenceTransformer('all-mpnet-base-v2')

# Convert DataFrames to Dataset objects
train_dataset = Dataset.from_pandas(train_df)
#dev_dataset = Dataset.from_pandas(dev_df)
test_dataset = Dataset.from_pandas(test_df)

print('TEST: ', test_dataset["note_original_text"][7])
print(len(test_dataset["note_original_text"][7].split()))
# Create a DatasetDict with the new "fewshot" split
train_data = DatasetDict({
    "train": train_dataset,
#    "validation": dev_dataset,
    "test": test_dataset,
})

# Apply filtering and count the samples
def count_filtered_samples(dataset, name):
    filtered_dataset = dataset.filter(filter_annotations)
    print(f"{name} samples: {len(filtered_dataset)}")
    return filtered_dataset

filtered_train = count_filtered_samples(train_data['train'], "Train")
#filtered_dev = count_filtered_samples(train_data["validation"], "Dev")
filtered_test = count_filtered_samples(train_data["test"], "Test")

## Calculate embeddings for all training examples ONCE, outside the function
#train_embeddings = embedding_model.encode(train_dataset["note_original_text"])

## Function to get few-shot examples using RAG
#def get_rag_few_shot_examples(input_example, train_dataset, train_embeddings, num_samples):
#    input_text = input_example["note_original_text"]
#    input_embedding = embedding_model.encode([input_text])[0]
#
#    # Calculate cosine similarities
#    similarities = cosine_similarity([input_embedding], train_embeddings)[0]
#
#    # Get indices of top similar examples
#    top_indices = np.argsort(similarities)[-num_samples:][::-1]
#
#    # Return top similar examples as a DataFrame
#    few_shot_examples = pd.DataFrame(train_dataset[top_indices])
#    return few_shot_examples

embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

def get_rag_few_shot_examples(input_example, train_dataset, num_samples):
    input_text = input_example["note_original_text"]
    input_highlight = input_example["processed_highlight"]
    input_annotation = input_example["annotation"]

    input_combo = input_text
    input_embedding = embedding_model.encode([input_combo])[0]

    similarities = []
    for idx, train_ex in enumerate(train_dataset):
        train_note = train_ex["note_original_text"]

        # Skip if note_original_text is the same
        if train_note.strip() == input_text.strip():
            continue

        train_combo = train_note
        train_embedding = embedding_model.encode([train_combo])[0]

        sim = util.cos_sim(input_embedding, train_embedding).item()
        similarities.append((sim, idx))

    # Sort and select top similar examples
    top_indices = sorted(similarities, key=lambda x: x[0], reverse=True)[:num_samples]
    top_examples = [train_dataset[i] for _, i in top_indices]

    return pd.DataFrame(top_examples)

def format_few_shot_examples(examples):
    formatted_examples = []
    for _, row in examples.iterrows():
        formatted_examples.append(f"""
Example:
- Medical Note: {row['note_original_text']}
- Annotation: {row['annotation']}
""")
    return "\n".join(formatted_examples)

def generate_prompt_template(few_shot_examples, static_samples):
    return f"""Task:
You are a clinical information extraction assistant. From the given medical note, identify and classify whether the patient has received any previous cancer treatment.
If treatments are present, list them exactly as mentioned (e.g., surgery, chemotherapy, radiation, other) following the provided output patterns.

Always present the output in the following structured format and in English:
Annotation: Previous cancer treatment: [select one option].

Allowed output options (strictly select one):

Previous cancer treatment: radiation, chemotherapy.
Previous cancer treatment: radiation, other.
Previous cancer treatment: radiation, surgery, other.
Previous cancer treatment: surgery, chemotherapy, radiation, other.
Previous cancer treatment: surgery, radiation, other.
Previous cancer treatment: surgery, radiation.
Previous cancer treatment: surgery.

If the note does not contain sufficient information to determine the category, select the most appropriate of:
No previous cancer treatments.
No previous or concurrent cancers.

Output only the classification string in the exact format above. Do not include explanations, reasoning, or any extra text.

---

Here are few examples for your understanding:
{static_samples}
{few_shot_examples}

---

Now process the following note in the same way:

### Input:
- Medical Note: "{{note_original_text}}"

### Response:
Annotation: {{annotation}}"""

# Data preprocessing with RAG few-shot examples
def preprocess_function_rag(example):
    few_shot_examples = get_rag_few_shot_examples(example, filtered_train, num_samples=len(filtered_train))
    formatted_few_shot_examples = format_few_shot_examples(few_shot_examples)
    prompt_template = generate_prompt_template(formatted_few_shot_examples)

    input_text = prompt_template.format(
        note_original_text=example["note_original_text"],
#        processed_highlight=example["processed_highlight"],
        annotation=""
    )

    output_text = example["annotation"]

    model_inputs = tokenizer(input_text, max_length=100000, padding="max_length", truncation=True)
    labels = tokenizer(output_text, max_length=100000, padding="max_length", truncation=True)["input_ids"]
    labels = [(l if l != tokenizer.pad_token_id else -100) for l in labels]
    model_inputs["labels"] = labels
    return model_inputs

## Apply preprocessing to the dataset
#tokenized_train = filtered_train.map(preprocess_function_rag, batched=False, remove_columns=["note_original_text", "processed_highlight", "annotation"])
#tokenized_dev = filtered_dev.map(preprocess_function_rag, batched=False, remove_columns=["note_original_text", "processed_highlight", "annotation"])
#tokenized_test = filtered_test.map(preprocess_function_rag, batched=False, remove_columns=["note_original_text", "processed_highlight", "annotation"])
#
## Function to visualize a few samples with the full prompt
#def print_sample_prompts(dataset, num_samples):
#	for i in range(num_samples):
#		input_ids = dataset[i]["input_ids"]
#		if isinstance(input_ids[0], list):  # Handle nested list
#			input_ids = input_ids[0]
#		input_text = tokenizer.decode(input_ids, skip_special_tokens=True)        
#		print(f"=== Sample {i + 1} ===\n")
#		print(input_text)
#		print("\n" + "=" * 80 + "\n")
#
#print_sample_prompts(tokenized_train, num_samples=20)
#
## Do model patching and add fast LoRA weights
#model = FastLanguageModel.get_peft_model(
#    model,
#    r = 8,
#    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
#                      "gate_proj", "up_proj", "down_proj",],
#    lora_alpha = 16,
#    lora_dropout = 0, # Supports any, but = 0 is optimized
#    bias = "none",    # Supports any, but = "none" is optimized
#    # [NEW] "unsloth" uses 30% less VRAM, fits 2x larger batch sizes!
#    use_gradient_checkpointing = "unsloth", # True or "unsloth" for very long context
#    random_state = 3407,
#    max_seq_length = 4096,
#    use_rslora = False,  # We support rank stabilized LoRA
#    loftq_config = None, # And LoftQ
#)
#
#trainer = SFTTrainer(
#    model = model,
#    train_dataset = tokenized_train,
#    tokenizer = tokenizer,
#    args = SFTConfig(
#        dataset_text_field = "text",
#        max_seq_length = 4096,
#        per_device_train_batch_size = 3,
#        gradient_accumulation_steps = 1,
#        warmup_steps = 5,
#	fp16 = True,
#	bf16 = False,
#        max_steps = 300,
#        logging_steps = 1,
#	fp16_backend = 'auto',
#	gradient_checkpointing=True,
#        output_dir = "outputs",
#        optim = "adamw_8bit",
#        seed = 3407,
#    ),
#)
#
#os.environ['UNSLOTH_RETURN_LOGITS'] = '1'
#
## Train the model
#trainer_stats = trainer.train()
#
## Save the trained model
#model.save_pretrained("/data/disk1/share/sghosh/llama_2_7b-surgery-rag")
#tokenizer.save_pretrained("/data/disk1/share/sghosh/llama_2_7b-surgery-rag")
#
#if True: model.save_pretrained_merged("/data/disk1/share/sghosh/llama_2_7b-surgery-rag", tokenizer, save_method = "merged_16bit",)

### Enable only for INFERENCE ####

FastLanguageModel.for_inference(model) # Enable native 2x faster inference

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def calculate_cosine_similarity(string1, string2):
    # Create the TfidfVectorizer
    vectorizer = TfidfVectorizer()
    
    # Fit and transform the strings into TF-IDF feature vectors
    tfidf_matrix = vectorizer.fit_transform([string1, string2])
    
    # Compute cosine similarity
    similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
    
    # Print strings if similarity exceeds the threshold=
#    print(f"String 1: {string1}")
#    print(f"String 2: {string2}")
#    print(f"Cosine Similarity: {similarity:.2f}")
        
    return similarity

data_def = [
'Tumor longest diameter unknown',
'Tumor longest diameter: [put value]mm (at initial imaging on [put date])'
]


def get_rag_few_shot_examples_test(input_example, train_dataset, num_samples):
    input_text = input_example["note_original_text"]
    input_annotation = ""

    input_combo = input_text
    input_embedding = embedding_model.encode([input_combo])[0]

    similarities = []
    for idx, train_ex in enumerate(train_dataset):
        train_note = train_ex["note_original_text"]

        # Skip if note_original_text is the same
        if train_note.strip() == input_text.strip():
            continue

        train_combo = train_note
        train_embedding = embedding_model.encode([train_combo])[0]

        sim = util.cos_sim(input_embedding, train_embedding).item()
        similarities.append((sim, idx))

    # Sort and select top similar examples
    top_indices = sorted(similarities, key=lambda x: x[0], reverse=True)[:num_samples]   
    top_examples = [train_dataset[i] for _, i in top_indices]

    return pd.DataFrame(top_examples)

# Get few-shot examples again (same as in preprocessing)
few_shot_examples = get_rag_few_shot_examples_test(
    filtered_test[0],  # or any test example just to pass structure
    filtered_train,
    num_samples=len(filtered_train)
)

# Format few-shot examples
formatted_few_shot_examples = format_few_shot_examples(few_shot_examples)
static_samples = format_few_shot_examples(sampled_df)

# Create prompt template
prompt_template = generate_prompt_template(formatted_few_shot_examples, static_samples)

import nltk
from nltk.tokenize import sent_tokenize, word_tokenize

# Download tokenizer models (if not already)
nltk.download("punkt")

def truncate_if_needed(doc_text: str, excerpt: str, max_words: int = 500, window: int = 5) -> str:
    # Check word count
    total_words = len(word_tokenize(doc_text))
    if total_words <= max_words:
        return doc_text  # No truncation needed

    # Tokenize into sentences
    sentences = sent_tokenize(doc_text)
    
    # Find index of the sentence containing the excerpt
    excerpt_sentence_idx = -1
    excerpt = excerpt.strip()
    
    for i, sentence in enumerate(sentences):
        if excerpt in sentence:
            excerpt_sentence_idx = i
            break

    # If excerpt not found, skip this instance
    if excerpt_sentence_idx == -1:
        return None

    # Define start and end index with the surrounding context
    start = max(0, excerpt_sentence_idx - window)
    end = min(len(sentences), excerpt_sentence_idx + window + 1)

    # Get truncated version
    truncated_text = ' '.join(sentences[start:end])
    return truncated_text

em = 0; wm = 0; cs = 0; tc = 1; flag = 1
for org_txt, hlt, annt in zip(filtered_test["note_original_text"], filtered_test["processed_highlight"], filtered_test["annotation"]):

#    org_txt = truncate_if_needed(org_txt, hlt)

    annt = annt.replace(',','.')
    inputs = tokenizer(
    [
        prompt_template.format(
            note_original_text=org_txt,
            annotation=""
        )
    ],     
    truncation=True,
    max_length=100000 - 100,  # reserve space for generation, 
return_tensors = "pt").to("cuda")

    output_ids = model.generate(**inputs, max_new_tokens = 100, use_cache=True,
        temperature=1.5,  # Control the 'randomness' of outputs
top_p = 0.1,        
repetition_penalty=1.1  # Avoid repeated outputs
    )
    generated_text = tokenizer.batch_decode(output_ids)
    print('\n\nTest Sample: ', tc)
    tc += 1
    print('Gold Annotation:\n', annt)
    try:
        pred1 = generated_text[0].split('### Response:')[1]
#        print('\n[BEFORE]---Generated (Raw) Annotation:\n', pred1)
        preds = generated_text[0].split('### Response:\n')[1].split('\n')[0].replace('Annotation:', '').strip().split('.')[0].replace('<|im_end|>','').replace('<br>', '').strip()
#        preds = preds.split('\n')[0]
        print('---\nGenerated (Raw) Annotation:\n', preds)
    except:
        flag += 1
#        print('\nFlag Example:\n',generated_text[0])
        print('\n\nLengthy: ', len(org_txt.split()))

        org_txt = truncate_if_needed(org_txt, hlt)
        inputs = tokenizer(
        [
            prompt_template.format(
                note_original_text=org_txt,
                annotation=""
            )
        ],     
        truncation=True,
        max_length=100000 - 100,  # reserve space for generation, 
    return_tensors = "pt").to("cuda")
    
        output_ids = model.generate(**inputs, max_new_tokens = 100, use_cache=True,
            temperature=1.5,  # Control the 'randomness' of outputs
    top_p = 0.1,        
    repetition_penalty=1.1  # Avoid repeated outputs
        )
        generated_text = tokenizer.batch_decode(output_ids)
        pred1 = generated_text[0].split('### Response:')[1]
#        print('\n[BEFORE]---Generated (Raw) Annotation:\n', pred1)
        preds = generated_text[0].split('### Response:\n')[1].split('\n')[0].replace('Annotation:', '').strip().split('.')[0].replace('<|im_end|>','').replace('<br>', '').strip()
#        preds = preds.split('\n')[0]
        print('---\nGenerated (Raw) Annotation:\n', preds)

    cossim = calculate_cosine_similarity(preds,annt)
    cossim = round(cossim, 2)

#    print('\n\nTest Sample: ', tc)
#    tc += 1
#    print('Gold Annotation:\n', annt)
#    print('\n----\nGenerated (Raw) Annotation:\n', generated_text[0].split('### Response:\nAnnotation:')[1].split('\n')[1].strip())

    preds_list = preds.strip().split(' ')
    annt_list = annt.strip().split(' ')

#    if any(preds in item for item in data_def):
#        preds = ''
#        print('\nStatus: !!! Unable to Generate !!!')
    if unicodedata.normalize('NFKC', preds) == unicodedata.normalize('NFKC', annt):
        em += 1
        print('\nStatus: ==== Exact Match ====')
    elif (len(preds) == len(annt) and cossim >= 0.8) or cossim == 1.0:
        em += 1
        print('\nStatus: ==== Exact Match ====')
    elif cossim >= 0.55:
        cs += 1
        status = f'Partial Match (CosSim: {cossim:.2f})'
        print(f'\nStatus: {status}')
    else:
        print('Mismatch note: ', org_txt)
        status = f'Mismatch (CosSim: {cossim:.2f})'
        print(f"\nStatus: {status}")
        preds = ''

    import torch, gc
    torch.cuda.empty_cache()
    gc.collect()

#print('\n# Exact Matches: ', em)
##print('# Partial Matches: ', cs)
#print('Hit Percent: ', (em/len(filtered_test))*100)

# Print summary statistics
print('\n# Exact Matches: ', em)
print('# Partial Matches: ', cs)
print('Hit Percent: ', ((em + cs) / len(filtered_test)) * 100)
print('Flag count: ', flag)
