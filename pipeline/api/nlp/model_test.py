from synthetic_dataset_generator import generate_synthetic_histology_df
from build_faiss import build_task_index
from model_runner import load_prompts_from_json, init_model, get_prompt, run_model_with_prompt
from runtime_store import FewShotStore
import pandas as pd

df = generate_synthetic_histology_df(200)
build_task_index("histology", df)

PROMPTS_PATH = "prompts.json"
MODEL_PATH = "meta-llama-3.1-8b-instruct-q4_k_m.gguf"

# one-time init
load_prompts_from_json(PROMPTS_PATH)
init_model(MODEL_PATH)
STORE = FewShotStore()

fewshots = STORE.topk("histology", "Microscopy confirms liposarcoma.", k=2)
print(fewshots)

prompt = get_prompt("histology", fewshots, "Microscopy confirms liposarcoma.")
res = run_model_with_prompt(prompt)
print(f"Prompt:\n{prompt}\n")
print("#####" * 10)
print("Response:")

print(res["normalized"])
