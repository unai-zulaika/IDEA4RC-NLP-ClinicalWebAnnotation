"""
VLLM Runner Module

Provides VLLM backend integration for LLM inference.
Supports batch inference and falls back to llama.cpp if VLLM is unavailable.
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Global VLLM client state
_VLLM_CLIENT: Optional['VLLMClient'] = None
_USE_VLLM: bool = False


class VLLMClient:
    """Client for VLLM server API."""
    
    def __init__(self, endpoint: str, model_name: str, timeout: int = 30):
        """
        Initialize VLLM client.
        
        Args:
            endpoint: VLLM server endpoint (e.g., "http://localhost:8000/v1")
            model_name: Model name to use
            timeout: Request timeout in seconds
        """
        self.endpoint = endpoint.rstrip('/')
        self.model_name = model_name
        self.timeout = timeout
        
        # Setup session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Test connection
        self._test_connection()
    
    def _test_connection(self) -> None:
        """Test connection to VLLM server."""
        try:
            # VLLM OpenAI-compatible API uses /v1/models endpoint
            # Remove /v1 from endpoint if present, then add /v1/models
            base_endpoint = self.endpoint.rstrip('/')
            if base_endpoint.endswith('/v1'):
                base_endpoint = base_endpoint[:-3]
            
            response = self.session.get(
                f"{base_endpoint}/v1/models",
                timeout=5
            )
            if response.status_code == 200:
                models = response.json()
                print(f"[VLLM] Connected to server at {self.endpoint}")
                if 'data' in models and len(models['data']) > 0:
                    available_models = [m.get('id', 'unknown') for m in models['data']]
                    print(f"[VLLM] Available models: {', '.join(available_models)}")
            else:
                raise ConnectionError(f"VLLM server returned status {response.status_code}")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to connect to VLLM server at {self.endpoint}: {e}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to VLLM server at {self.endpoint}: {e}")
    def generate(self, 
                 prompt: str,
                 max_new_tokens: int = 128,
                 temperature: float = 0.1,
                 logprobs: Optional[int] = None,
                 **kwargs) -> Dict[str, Any]:
        """
        Generate text using VLLM server.
        
        Args:
            prompt: Input prompt
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            logprobs: Number of logprobs to return per token (None to disable)
            **kwargs: Additional parameters
        
        Returns:
            Dictionary with 'raw', 'normalized' output, and optionally 'logprobs'
        """
        url = f"{self.endpoint}/chat/completions"
        
        # Determine if this is a simple completion prompt (no system message needed)
        # Simple prompts are very short and don't contain medical annotation instructions
        is_simple_prompt = (
            len(prompt.strip()) < 100 and
            "annotation" not in prompt.lower() and
            "medical" not in prompt.lower() and
            "extract" not in prompt.lower() and
            "task" not in prompt.lower()
        )
        
        # Build messages - use system message only for structured prompts
        messages = []
        if not is_simple_prompt:
            messages.append({
                "role": "system",
                "content": "You are a medical text annotation assistant. Follow the instructions carefully and provide concise, focused responses in the exact format requested. Be especially concise in the reasoning field - provide only essential points in 2-3 sentences maximum."
            })
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": temperature,
            **kwargs
        }
        
        # Try with logprobs first if requested
        if logprobs is not None:
            payload["logprobs"] = logprobs
        
        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            result = response.json()
            raw_output = result["choices"][0]["message"]["content"]
            
            # Normalize: extract first line
            first_line = raw_output.strip().splitlines()[0].strip()
            
            # Extract logprobs if available
            # VLLM chat completions may return logprobs in different locations:
            # 1. result["choices"][0]["logprobs"] (completions API)
            # 2. result["choices"][0]["message"]["logprobs"] (chat completions API)
            logprobs_data = None
            if logprobs is not None:
                choice = result["choices"][0]
                
                # Try multiple possible locations for logprobs
                if "logprobs" in choice:
                    logprobs_data = choice["logprobs"]
                elif "message" in choice and isinstance(choice["message"], dict) and "logprobs" in choice["message"]:
                    logprobs_data = choice["message"]["logprobs"]
                
                # Debug: log the response structure
                if logprobs_data is None:
                    print(f"    [DEBUG] Logprobs requested but not found. Choice keys: {list(choice.keys())}")
                    if "message" in choice:
                        print(f"    [DEBUG] Message keys: {list(choice['message'].keys()) if isinstance(choice['message'], dict) else 'not a dict'}")
                elif isinstance(logprobs_data, dict):
                    logprobs_keys = list(logprobs_data.keys())
                    print(f"    [DEBUG] Logprobs dict keys: {logprobs_keys}")
                    
                    # Check for token_logprobs or content array
                    if "token_logprobs" in logprobs_data:
                        token_logprobs = logprobs_data.get("token_logprobs")
                        if token_logprobs is None or len(token_logprobs) == 0:
                            print(f"    [DEBUG] token_logprobs exists but is empty")
                        else:
                            print(f"    [DEBUG] Found {len(token_logprobs)} token logprobs")
                    elif "content" in logprobs_data:
                        # VLLM chat completions may return logprobs as content array
                        content_logprobs = logprobs_data.get("content")
                        if isinstance(content_logprobs, list) and len(content_logprobs) > 0:
                            print(f"    [DEBUG] Found content array with {len(content_logprobs)} items")
                            # Extract token_logprobs from content array
                            # Each item might have "token", "logprob", "top_logprobs", etc.
                            if isinstance(content_logprobs[0], dict):
                                first_item_keys = list(content_logprobs[0].keys())
                                print(f"    [DEBUG] First content item keys: {first_item_keys}")
                                # Try to extract logprobs from content array
                                extracted_logprobs = []
                                for item in content_logprobs:
                                    if isinstance(item, dict):
                                        # Try different possible keys
                                        if "logprob" in item:
                                            extracted_logprobs.append(item["logprob"])
                                        elif "token_logprob" in item:
                                            extracted_logprobs.append(item["token_logprob"])
                                
                                if extracted_logprobs:
                                    # Convert to expected format
                                    logprobs_data = {"token_logprobs": extracted_logprobs}
                                    print(f"    [DEBUG] Extracted {len(extracted_logprobs)} logprobs from content array")
                                else:
                                    print(f"    [DEBUG] Could not extract logprobs from content array")
                    else:
                        print(f"    [DEBUG] Logprobs dict does not contain 'token_logprobs' or 'content'")
                else:
                    print(f"    [DEBUG] Logprobs is not a dict: {type(logprobs_data)}")
            
            return {
                "raw": raw_output,
                "normalized": first_line,
                "logprobs": logprobs_data
            }
        except requests.exceptions.RequestException as e:
            # If logprobs was requested and we got a 400 error, retry without logprobs
            if logprobs is not None and hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 400:
                    # Retry without logprobs
                    payload_without_logprobs = payload.copy()
                    payload_without_logprobs.pop("logprobs", None)
                    
                    try:
                        response = self.session.post(
                            url,
                            json=payload_without_logprobs,
                            timeout=self.timeout
                        )
                        response.raise_for_status()
                        
                        result = response.json()
                        raw_output = result["choices"][0]["message"]["content"]
                        first_line = raw_output.strip().splitlines()[0].strip()
                        
                        # Log that logprobs aren't supported
                        print(f"    [WARN] VLLM server doesn't support logprobs parameter, continuing without confidence data")
                        
                        return {
                            "raw": raw_output,
                            "normalized": first_line,
                            "logprobs": None  # Explicitly None to indicate not available
                        }
                    except requests.exceptions.RequestException as retry_error:
                        # If retry also fails, raise original error
                        raise RuntimeError(f"VLLM API request failed: {e}")
            
            # For other errors, raise as before
            raise RuntimeError(f"VLLM API request failed: {e}")
    
    def generate_batch(self,
                       prompts: List[str],
                       max_new_tokens: int = 128,
                       temperature: float = 0.1,
                       **kwargs) -> List[Dict[str, str]]:
        """
        Generate text for multiple prompts in batch.
        
        Args:
            prompts: List of input prompts
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters
        
        Returns:
            List of dictionaries with 'raw' and 'normalized' output
        """
        url = f"{self.endpoint}/chat/completions"
        
        # Prepare batch requests
        results = []
        for prompt in prompts:
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a concise medical text annotation assistant."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": max_new_tokens,
                "temperature": temperature,
                **kwargs
            }
            
            try:
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.timeout
                )
                response.raise_for_status()
                
                result = response.json()
                raw_output = result["choices"][0]["message"]["content"]
                first_line = raw_output.strip().splitlines()[0].strip()
                
                results.append({
                    "raw": raw_output,
                    "normalized": first_line
                })
            except requests.exceptions.RequestException as e:
                # Return error result for this prompt
                results.append({
                    "raw": f"ERROR: {str(e)}",
                    "normalized": f"ERROR: {str(e)}"
                })
        
        return results


def load_vllm_config(config_path: Optional[Path] = None) -> Dict:
    """
    Load VLLM configuration from file or environment variables.
    
    Args:
        config_path: Path to config file (optional)
    
    Returns:
        Configuration dictionary
    """
    # Load defaults from config file first
    use_vllm = False
    vllm_endpoint = "http://localhost:8000/v1"
    model_name = "meta-llama/Llama-3.1-8B-Instruct"
    batch_size = 8
    timeout = 30

    if config_path and config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                use_vllm = config.get("use_vllm", use_vllm)
                vllm_endpoint = config.get("vllm_endpoint", vllm_endpoint)
                model_name = config.get("model_name", model_name)
                batch_size = config.get("batch_size", batch_size)
                timeout = config.get("timeout", timeout)
        except Exception as e:
            print(f"[WARN] Failed to load VLLM config from {config_path}: {e}")

    # Environment variables override config file
    if os.getenv("USE_VLLM"):
        use_vllm = os.getenv("USE_VLLM", "false").lower() == "true"
    if os.getenv("VLLM_ENDPOINT"):
        vllm_endpoint = os.getenv("VLLM_ENDPOINT")
    if os.getenv("VLLM_MODEL_NAME"):
        model_name = os.getenv("VLLM_MODEL_NAME")
    if os.getenv("VLLM_BATCH_SIZE"):
        batch_size = int(os.getenv("VLLM_BATCH_SIZE"))
    if os.getenv("VLLM_TIMEOUT"):
        timeout = int(os.getenv("VLLM_TIMEOUT"))

    return {
        "use_vllm": use_vllm,
        "vllm_endpoint": vllm_endpoint,
        "model_name": model_name,
        "batch_size": batch_size,
        "timeout": timeout
    }


def init_model_vllm(config_path: Optional[Path] = None) -> bool:
    """
    Initialize VLLM client.
    
    Args:
        config_path: Path to VLLM config file (optional)
    
    Returns:
        True if VLLM was successfully initialized, False otherwise
    """
    global _VLLM_CLIENT, _USE_VLLM
    
    config = load_vllm_config(config_path)
    
    if not config["use_vllm"]:
        print("[VLLM] VLLM disabled in configuration")
        return False
    
    try:
        _VLLM_CLIENT = VLLMClient(
            endpoint=config["vllm_endpoint"],
            model_name=config["model_name"],
            timeout=config["timeout"]
        )
        _USE_VLLM = True
        print(f"[VLLM] Initialized successfully with model: {config['model_name']}")
        return True
    except Exception as e:
        print(f"[WARN] Failed to initialize VLLM: {e}")
        print("[WARN] Falling back to llama.cpp")
        _USE_VLLM = False
        _VLLM_CLIENT = None
        return False


def run_model_with_prompt_vllm(prompt: str,
                               max_new_tokens: int = 128,
                               temperature: float = 0.1,
                               return_logprobs: bool = False) -> Dict[str, Any]:
    """
    Run model with prompt using VLLM backend.
    
    Args:
        prompt: Input prompt
        max_new_tokens: Maximum tokens to generate
        temperature: Sampling temperature
        return_logprobs: If True, request logprobs from VLLM API
    
    Returns:
        Dictionary with 'raw', 'normalized' output, and optionally 'logprobs'
    """
    global _VLLM_CLIENT
    
    if _VLLM_CLIENT is None:
        raise RuntimeError("VLLM client not initialized. Call init_model_vllm() first.")
    
    logprobs_param = 1 if return_logprobs else None
    
    return _VLLM_CLIENT.generate(
        prompt=prompt,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        logprobs=logprobs_param
    )


def is_vllm_available() -> bool:
    """Check if VLLM is available and initialized."""
    return _USE_VLLM and _VLLM_CLIENT is not None
