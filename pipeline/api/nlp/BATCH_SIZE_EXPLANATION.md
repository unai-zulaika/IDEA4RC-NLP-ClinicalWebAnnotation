# Understanding `n_batch` in llama.cpp

## What `n_batch` Does

`n_batch` in llama.cpp controls **how many tokens are processed in parallel during the PROMPT EVALUATION phase**, not batch inference of multiple prompts.

## Two Phases of LLM Inference

### 1. **Prompt Evaluation Phase** (uses `n_batch`)
- **What happens**: Your entire prompt is processed through the model
- **Example**: Your prompt has 800 tokens (instructions + few-shot examples + note text)
- **With n_batch=1024**: All 800 tokens are processed in ONE parallel batch
- **With n_batch=512**: The 800 tokens are split into 2 batches (512 + 288)
- **Result**: Creates key-value (KV) cache for the prompt tokens

### 2. **Generation Phase** (autoregressive, one token at a time)
- **What happens**: Model generates output tokens one-by-one
- **Process**: Token 1 → Token 2 → Token 3 → ... (sequential)
- **Uses**: The KV cache from phase 1 + newly generated tokens

## What's Included in Each Batch?

### Example: Processing Your Medical Note Prompt

**Your prompt structure:**
```
System message: "You are an expert medical annotator..."
Instructions: "Extract tumor depth..."
Few-shot examples: 
  - Example 1: note_text_1 + annotation_1
  - Example 2: note_text_2 + annotation_2
Your note: "15 marzo 2018\n\nMotivo della visita..."
```

**Tokenization:**
- Entire prompt → ~2000 tokens (example)

**With n_batch=1024:**
- **Batch 1**: Tokens 0-1023 (first 1024 tokens)
- **Batch 2**: Tokens 1024-1999 (remaining 976 tokens)

**What's processed together in Batch 1:**
- System message tokens
- Instruction tokens  
- Part of few-shot examples
- All processed in parallel (parallel matrix operations)

**What's processed together in Batch 2:**
- Remaining few-shot tokens
- Your actual note text tokens
- All processed in parallel

## Impact of `n_batch` on Performance

| n_batch | Prompt Processing | VRAM Usage | Speed |
|---------|------------------|------------|-------|
| 256 | More batches needed | Lower | Slower |
| 512 | Medium batches | Medium | Medium |
| 1024 | Fewer batches | Higher | Faster |
| 2048 | Single batch (for short prompts) | Highest | Fastest |

## Important Notes

1. **NOT Multiple Prompts**: `n_batch` does NOT allow processing multiple different prompts in parallel
   - Each note-prompt combination is still processed sequentially
   - You run: prompt_1 → wait → prompt_2 → wait → prompt_3...

2. **Within-Single-Prompt Batching**: It batches TOKENS within a SINGLE prompt
   - If your prompt has 500 tokens and n_batch=1024, all 500 are processed together
   - If your prompt has 3000 tokens and n_batch=1024, it's split into 3 batches

3. **VRAM Impact**: 
   - Larger `n_batch` = more tokens processed simultaneously = more VRAM needed
   - But only during prompt evaluation, not during generation

4. **Optimal Value**: 
   - Should be >= maximum prompt token length for best performance
   - Your prompts are likely 2000-4000 tokens → n_batch=1024 or 2048 is good
   - Setting it too high wastes VRAM if prompts are shorter

## Current Setup

- **n_batch = 1024**: Good for prompts up to 1024 tokens in one batch
- **n_ctx = 8192**: Maximum context window (prompt + generation)
- **Result**: Most prompts process in 1-2 batches during evaluation phase

## Why This Matters

- **Faster prompt evaluation**: Processing 1024 tokens at once is faster than 512
- **Better GPU utilization**: More parallel operations = GPU stays busier
- **More VRAM usage**: Uses available VRAM efficiently without going over limit

