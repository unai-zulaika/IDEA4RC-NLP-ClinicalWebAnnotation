"""
Quantize google/medgemma-1.5-4b-it for maximum vLLM throughput.

Follows the official llm-compressor multimodal vision quantization guide:
  https://docs.vllm.ai/projects/llm-compressor/en/latest/examples/multimodal_vision/

Uses llm-compressor (vllm-project/llm-compressor) with two strategies:
  1. W4A16 GPTQ (default) — 4-bit weights, 16-bit activations.
     Best throughput: ~2x memory reduction → larger batches → higher tok/s.
     Requires calibration data and compute capability >= 8.0.
  2. FP8 Dynamic — 8-bit weights + activations, no calibration needed.
     Simpler but less memory savings. Requires compute capability >= 8.9.

Install:
    pip install llmcompressor transformers torch datasets compressed-tensors

Run:
    python quantize_model.py              # W4A16 GPTQ (recommended)
    python quantize_model.py --method fp8 # FP8 Dynamic (simpler)

Serve with vLLM (max throughput flags):
    vllm serve ./medgemma-1.5-4b-it-W4A16-G128 \
        --dtype auto \
        --max-model-len 4096 \
        --enable-chunked-prefill \
        --max-num-batched-tokens 8192 \
        --gpu-memory-utilization 0.95 \
        --enforce-eager
"""

import argparse
import time

from transformers import AutoProcessor, Gemma3ForConditionalGeneration

from llmcompressor import oneshot
from llmcompressor.modifiers.quantization import GPTQModifier, QuantizationModifier

MODEL_ID = "google/medgemma-1.5-4b-it"


def quantize_w4a16_gptq(model, processor, model_id):
    """W4A16 GPTQ: best throughput for vLLM serving.

    Following the official multimodal vision example:
    - Pass the full model (not a sub-module)
    - Use ignore patterns to skip lm_head, vision_tower, and multi_modal_projector
    - Let oneshot handle dataset loading and tokenization internally
    """
    save_dir = model_id.rstrip("/").split("/")[-1] + "-W4A16-G128"

    # Oneshot arguments
    BATCH_SIZE = 4
    NUM_CALIBRATION_SAMPLES = 512
    MAX_SEQUENCE_LENGTH = 2048
    DATASET_ID = "flickr30k"
    DATASET_SPLIT = {"calibration": f"test[:{NUM_CALIBRATION_SAMPLES}]"}

    # Recipe — ignore lm_head, vision tower, and multimodal projector
    # per official docs: https://docs.vllm.ai/projects/llm-compressor/en/latest/examples/multimodal_vision/#customizing-gptqmodifier-parameters
    recipe = [
        GPTQModifier(
            targets="Linear",
            scheme="W4A16",
            ignore=[
                "lm_head",
                r"re:model\.vision_tower.*",
                r"re:model\.multi_modal_projector.*",
            ],
        ),
    ]

    print(f"Running GPTQ W4A16 quantization ({NUM_CALIBRATION_SAMPLES} calibration samples)...")
    oneshot(
        model=model,
        processor=processor,
        dataset=DATASET_ID,
        splits=DATASET_SPLIT,
        recipe=recipe,
        batch_size=BATCH_SIZE,
        shuffle_calibration_samples=False,
        max_seq_length=MAX_SEQUENCE_LENGTH,
        num_calibration_samples=NUM_CALIBRATION_SAMPLES,
        output_dir=save_dir,
    )

    # Save processor alongside model
    processor.save_pretrained(save_dir)
    return save_dir


def quantize_fp8_dynamic(model, processor, model_id):
    """FP8 Dynamic: no calibration needed, simpler but less compression."""
    save_dir = model_id.rstrip("/").split("/")[-1] + "-FP8-Dynamic"

    # Recipe — ignore lm_head, vision tower, and multimodal projector
    recipe = [
        QuantizationModifier(
            targets="Linear",
            scheme="FP8_DYNAMIC",
            ignore=[
                "lm_head",
                r"re:model\.vision_tower.*",
                r"re:model\.multi_modal_projector.*",
            ],
        ),
    ]

    print("Running FP8 Dynamic quantization (no calibration needed)...")
    oneshot(model=model, recipe=recipe, output_dir=save_dir)

    # Save processor alongside model
    processor.save_pretrained(save_dir)
    return save_dir


def main():
    parser = argparse.ArgumentParser(description="Quantize MedGemma for vLLM")
    parser.add_argument(
        "--method",
        choices=["w4a16", "fp8"],
        default="w4a16",
        help="Quantization method (default: w4a16 for max throughput)",
    )
    parser.add_argument(
        "--model-id",
        default=MODEL_ID,
        help=f"HuggingFace model ID (default: {MODEL_ID})",
    )
    args = parser.parse_args()

    print(f"Loading {args.model_id}...")
    t0 = time.time()
    model = Gemma3ForConditionalGeneration.from_pretrained(args.model_id, dtype="auto")
    processor = AutoProcessor.from_pretrained(args.model_id, trust_remote_code=True)
    print(f"Model loaded in {time.time() - t0:.1f}s")

    t0 = time.time()
    if args.method == "w4a16":
        save_dir = quantize_w4a16_gptq(model, processor, args.model_id)
    else:
        save_dir = quantize_fp8_dynamic(model, processor, args.model_id)

    elapsed = time.time() - t0
    print(f"\nQuantization complete in {elapsed:.1f}s")
    print(f"Saved to: {save_dir}")
    print(f"\nServe with vLLM:")
    print(f"  vllm serve {save_dir} --dtype auto --max-model-len 4096 "
          f"--enable-chunked-prefill --gpu-memory-utilization 0.95")


if __name__ == "__main__":
    main()
