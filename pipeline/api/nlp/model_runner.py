# prompts_runtime.py
import os
import json
import platform
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

try:
    import pynvml
except ImportError:
    pynvml = None

from llama_cpp import Llama

# Try to import VLLM runner (optional)
try:
    from vllm_runner import init_model_vllm, is_vllm_available, run_model_with_prompt_vllm, load_vllm_config
    VLLM_AVAILABLE = True
except ImportError:
    VLLM_AVAILABLE = False
    print("[INFO] VLLM runner not available (optional dependency)")


# ---------- Global state (kept hot in production) ----------
_LLM: Optional[Llama] = None
_PROMPTS: Dict[str, Dict] = {}
_USE_VLLM: bool = False


# ---------- 1) Prompt loading & building ----------
def load_prompts_from_json(json_path: str | Path) -> None:
    """Load (or hot-reload) all prompt templates into memory."""
    global _PROMPTS
    with open(json_path, "r", encoding="utf-8") as f:
        _PROMPTS = json.load(f)


def get_prompt(task_key: str,
               # list of (note_text, annotation)
               fewshots: List[Tuple[str, str]],
               note_text: str) -> str:
    """
    Build the final prompt string from the JSON template by key.
    - fewshots: list of (note_text, annotation) pairs
    - note_text: the incoming note to process
    """
    if task_key not in _PROMPTS:
        raise KeyError(f"No prompt found for task '{task_key}'. "
                       f"Known: {list(_PROMPTS.keys())}")
    template = _PROMPTS[task_key]["template"]

    fewshots_text = "\n".join(
        f"Example:\n- Medical Note: {n}\n- Annotation: {a}\n"
        for (n, a) in fewshots
    )

    return template.format(fewshots=fewshots_text, note=note_text)


# ---------- 2) Model init (GPU → CPU fallback) & inference ----------
def _default_threads() -> int:
    env = os.getenv("LLAMA_N_THREADS")
    if env and env.isdigit():
        return int(env)
    try:
        import psutil
        n = psutil.cpu_count(logical=False) or psutil.cpu_count(
            logical=True) or 4
    except Exception:
        n = os.cpu_count() or 4
    return max(1, n - 1)


def _detect_vram_gb() -> Optional[float]:
    if pynvml is None:
        return None
    try:
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(h)
        return float(info.total / (1024**3))
    except Exception:
        return None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def _pick_n_gpu_layers(model_layers: int = 32) -> int:
    env = os.getenv("LLAMA_N_GPU_LAYERS")
    if env is not None:
        try:
            return int(env)
        except ValueError:
            pass
    if platform.system() == "Darwin":
        return -1  # Metal build → request "all", runtime will cap

    vram = _detect_vram_gb()
    if vram is None:
        return -1  # optimistically try all; fallback catches failures
    if vram >= 6.0:
        return -1
    if vram >= 4.0:
        return int(model_layers * 0.75)
    if vram >= 2.5:
        return int(model_layers * 0.33)
    return 0


def init_model(model_path: str,
               n_ctx: int = 8192,  # Increased from 4096 to use more VRAM and handle longer prompts
               model_layers: int = 32,
               vllm_config_path: Optional[Path] = None) -> None:
    """
    Initialize a global Llama() instance once (keep it hot).
    Tries VLLM first if configured, then llama.cpp with GPU offload, falls back to CPU.
    
    Args:
        model_path: Path to model file (for llama.cpp fallback)
        n_ctx: Context window size
        model_layers: Number of model layers
        vllm_config_path: Optional path to VLLM config file
    """
    global _LLM, _USE_VLLM
    
    # Try VLLM first if available
    if VLLM_AVAILABLE:
        script_dir = Path(__file__).resolve().parent
        if vllm_config_path is None:
            vllm_config_path = script_dir / "vllm_config.json"
        
        if init_model_vllm(vllm_config_path):
            _USE_VLLM = True
            print("[model_runner] Using VLLM backend")
            return
    
    # Fall back to llama.cpp
    _USE_VLLM = False
    if _LLM is not None:
        return  # already initialized

    n_threads = _default_threads()
    try_gpu = _pick_n_gpu_layers(model_layers=model_layers)

    for n_gpu_layers in ([try_gpu] if try_gpu == 0 else [try_gpu, 0]):
        try:
            print(
                f"[llama.cpp] init n_gpu_layers={n_gpu_layers}, n_threads={n_threads}")
            
            # Try with flash_attn first (better VRAM efficiency), fallback without if not supported
            try_flash_attn = True
            llama_params = {
                "model_path": model_path,
                "n_ctx": n_ctx,
                "n_threads": n_threads,
                # n_batch: Number of tokens processed in parallel during PROMPT EVALUATION phase
                # - During prompt processing (before generation), tokens are batched for efficiency
                # - Higher n_batch = more tokens processed at once = faster prompt evaluation = more VRAM
                # - Does NOT batch multiple prompts together (still sequential)
                # - Example: If prompt has 500 tokens, with n_batch=1024, all 500 are processed in one batch
                # - If prompt has 2000 tokens, with n_batch=1024, it processes in 2 batches (1024 + 976)
                "n_batch": 1024,  # Increased from 512 to better utilize VRAM for prompt processing
                "n_gpu_layers": n_gpu_layers,   # -1: all, 0: CPU
                "verbose": False,
                # n_ubatch: Unbatch size for attention computation (parallelization within attention)
                # - Controls how many tokens attend to each other in parallel
                # - Lower = less VRAM, higher = more parallelization (if VRAM allows)
                "n_ubatch": 512,  # Unbatch size for attention (can help with memory efficiency)
            }
            
            # Try with flash_attn if GPU layers > 0
            if n_gpu_layers > 0:
                try:
                    llama_params["flash_attn"] = True
                    _LLM = Llama(**llama_params)
                    print("[llama.cpp] Initialized with flash_attn=True (optimized VRAM usage)")
                except Exception as e:
                    # Flash attention not supported, try without
                    print(f"[llama.cpp] flash_attn not available: {e}")
                    print("[llama.cpp] Falling back to flash_attn=False")
                    llama_params.pop("flash_attn", None)
                    _LLM = Llama(**llama_params)
            else:
                _LLM = Llama(**llama_params)
            print("[llama.cpp] model ready")
            
            # Verify GPU usage by checking memory
            if n_gpu_layers > 0:
                try:
                    if pynvml:
                        pynvml.nvmlInit()
                        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        print(f"[llama.cpp] GPU memory allocated: {mem_info.used / (1024**3):.2f}GB")
                        pynvml.nvmlShutdown()
                except Exception:
                    pass  # GPU monitoring optional
            
            return
        except Exception as e:
            print(
                f"[llama.cpp] init failed (n_gpu_layers={n_gpu_layers}): {e}")
            _LLM = None
    raise RuntimeError("Could not initialize llama.cpp (GPU+CPU both failed).")


def run_model_with_prompt(prompt: str,
                          max_new_tokens: int = 128,
                          temperature: float = 0.1,
                          return_logprobs: bool = False) -> Dict[str, Any]:
    """
    Run the (already-initialized) LLM on a ready-to-go prompt string.
    Routes to VLLM if available, otherwise uses llama.cpp.
    Returns {"raw": full_text, "normalized": first_line_after_response, "logprobs": ...}.
    
    Args:
        prompt: Input prompt
        max_new_tokens: Maximum tokens to generate
        temperature: Sampling temperature
        return_logprobs: If True, request logprobs (VLLM only, ignored for llama.cpp)
    
    Returns:
        Dictionary with 'raw', 'normalized', and optionally 'logprobs' (None for llama.cpp)
    """
    global _USE_VLLM
    
    # Route to VLLM if available and initialized
    if _USE_VLLM and VLLM_AVAILABLE and is_vllm_available():
        try:
            return run_model_with_prompt_vllm(
                prompt=prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                return_logprobs=return_logprobs
            )
        except Exception as e:
            print(f"[WARN] VLLM request failed: {e}, falling back to llama.cpp")
            _USE_VLLM = False
    
    # Fall back to llama.cpp (logprobs not supported)
    if _LLM is None:
        raise RuntimeError(
            "Model not initialized. Call init_model(...) first.")

    out = _LLM.create_chat_completion(
        messages=[
            {"role": "system",
                "content": "You are a concise medical text annotation assistant."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_new_tokens,
        temperature=temperature,
    )
    raw = out["choices"][0]["message"]["content"]

    # Normalize: extract the first line (your prompts end with "Annotation: ")
    # If you prefer to split by "### Response:", do it here.
    first_line = raw.strip().splitlines()[0].strip()

    return {"raw": raw, "normalized": first_line, "logprobs": None}
