"""
Enhanced VLLM Client Service with metrics support
"""

import requests
from typing import Dict, Optional, Any, List
from pathlib import Path
import sys

# Import from local lib directory
try:
    from lib.vllm_runner import VLLMClient, load_vllm_config, is_vllm_available as check_vllm_available
except ImportError:
    # Fallback if vllm_runner not available
    VLLMClient = None
    def load_vllm_config(*args, **kwargs):
        return {"use_vllm": False}
    def check_vllm_available():
        return False


class EnhancedVLLMClient:
    """Enhanced VLLM client with metrics and model switching support"""
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize enhanced VLLM client"""
        if config_path is None:
            # Default to vllm_config.json in config directory
            backend_dir = Path(__file__).parent.parent
            config_path = backend_dir / "config" / "vllm_config.json"
        self.config = load_vllm_config(config_path)
        self._client: Optional[VLLMClient] = None
        self._init_client()
    
    def _init_client(self):
        """Initialize underlying VLLM client"""
        if self.config.get("use_vllm", False) and VLLMClient is not None:
            try:
                self._client = VLLMClient(
                    endpoint=self.config["vllm_endpoint"],
                    model_name=self.config["model_name"],
                    timeout=self.config.get("timeout", 30)
                )
            except Exception as e:
                print(f"[WARN] Failed to initialize VLLM client: {e}")
                import traceback
                traceback.print_exc()
                self._client = None
    
    def is_available(self) -> bool:
        """Check if VLLM is available"""
        # Check if VLLM is enabled in config
        if not self.config.get("use_vllm", False):
            return False
        
        # Try to initialize client if not already initialized
        if self._client is None:
            self._init_client()
        
        # Check if client is initialized (don't rely on global state)
        if self._client is None:
            return False
        
        # Also test connection directly
        try:
            base_endpoint = self.config["vllm_endpoint"].rstrip('/')
            if base_endpoint.endswith('/v1'):
                base_endpoint = base_endpoint[:-3]
            response = requests.get(f"{base_endpoint}/v1/models", timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"[DEBUG] VLLM availability check failed: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status"""
        try:
            # Test connection directly
            base_endpoint = self.config["vllm_endpoint"].rstrip('/')
            if base_endpoint.endswith('/v1'):
                base_endpoint = base_endpoint[:-3]
            
            response = requests.get(f"{base_endpoint}/v1/models", timeout=5)
            if response.status_code == 200:
                return {
                    "status": "available",
                    "endpoint": self.config["vllm_endpoint"],
                    "model_name": self.config["model_name"]
                }
            else:
                return {"status": "error", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            # If client exists but connection fails, still return error status
            if self._client is not None:
                return {"status": "error", "error": str(e)}
            return {"status": "unavailable", "error": "VLLM not initialized"}
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get server metrics from vLLM /metrics endpoint"""
        if not self.is_available():
            return {}
        
        try:
            base_endpoint = self.config["vllm_endpoint"].rstrip('/')
            if base_endpoint.endswith('/v1'):
                base_endpoint = base_endpoint[:-3]
            
            # Try /metrics endpoint
            response = requests.get(f"{base_endpoint}/metrics", timeout=5)
            if response.status_code == 200:
                # Parse Prometheus metrics format
                metrics_text = response.text
                metrics = self._parse_prometheus_metrics(metrics_text)
                return metrics
            else:
                # Fallback: try /health or other endpoints
                return {}
        except Exception as e:
            print(f"[WARN] Failed to fetch metrics: {e}")
            return {}
    
    def _parse_prometheus_metrics(self, metrics_text: str) -> Dict[str, Any]:
        """Parse Prometheus metrics format"""
        metrics = {}
        for line in metrics_text.split('\n'):
            if line.startswith('#') or not line.strip():
                continue
            
            # Parse metric lines like: metric_name{labels} value
            if '{' in line:
                parts = line.split('{', 1)
                metric_name = parts[0].strip()
                rest = parts[1].rsplit('}', 1)
                value_str = rest[1].strip() if len(rest) > 1 else rest[0]
            else:
                parts = line.split()
                if len(parts) >= 2:
                    metric_name = parts[0]
                    value_str = parts[1]
                else:
                    continue
            
            try:
                value = float(value_str)
                metrics[metric_name] = value
            except ValueError:
                continue
        
        # Extract useful metrics
        result = {}
        
        # GPU memory metrics
        if 'vllm:gpu_memory_used_bytes' in metrics:
            result['gpu_memory_used_gb'] = metrics['vllm:gpu_memory_used_bytes'] / (1024**3)
        if 'vllm:gpu_memory_total_bytes' in metrics:
            result['gpu_memory_total_gb'] = metrics['vllm:gpu_memory_total_bytes'] / (1024**3)
        
        # Throughput metrics
        if 'vllm:num_requests_running' in metrics:
            result['active_requests'] = int(metrics['vllm:num_requests_running'])
        
        # Try to find other common metrics
        for key, value in metrics.items():
            if 'throughput' in key.lower() or 'tokens_per_sec' in key.lower():
                result['throughput_tokens_per_sec'] = value
            elif 'requests_per_sec' in key.lower():
                result['throughput_requests_per_sec'] = value
        
        return result
    
    def list_models(self) -> List[Dict[str, Any]]:
        """List available models (including Multi-LoRA adapters)"""
        if not self.is_available():
            return []
        
        try:
            base_endpoint = self.config["vllm_endpoint"].rstrip('/')
            if base_endpoint.endswith('/v1'):
                base_endpoint = base_endpoint[:-3]
            
            response = requests.get(f"{base_endpoint}/v1/models", timeout=5)
            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get('data', []):
                    models.append({
                        'id': model.get('id', ''),
                        'name': model.get('id', ''),
                        'is_active': model.get('id') == self.config["model_name"]
                    })
                return models
        except Exception as e:
            print(f"[WARN] Failed to list models: {e}")
        
        return []
    
    def switch_model(self, model_name: str) -> bool:
        """Switch active model (requires vLLM server restart or Multi-LoRA support)"""
        # Note: This may require server restart or Multi-LoRA API call
        # For now, just update config
        self.config["model_name"] = model_name
        # Reinitialize client
        self._init_client()
        return True
    
    def generate(self, prompt: str, max_new_tokens: int = 128, 
                 temperature: float = 0.0, return_logprobs: bool = False) -> Dict[str, Any]:
        """Generate text using VLLM"""
        if not self._client:
            raise RuntimeError("VLLM client not initialized")
        
        return self._client.generate(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            logprobs=1 if return_logprobs else None
        )


# Global instance
_vllm_client: Optional[EnhancedVLLMClient] = None


def get_vllm_client(config_path: Optional[Path] = None, force_reload: bool = False) -> EnhancedVLLMClient:
    """Get or create global VLLM client instance
    
    Args:
        config_path: Optional path to vllm_config.json
        force_reload: If True, reinitialize the client even if it exists
    """
    global _vllm_client
    if _vllm_client is None or force_reload:
        # Default to vllm_config.json in config directory
        if config_path is None:
            backend_dir = Path(__file__).parent.parent
            config_path = backend_dir / "config" / "vllm_config.json"
        _vllm_client = EnhancedVLLMClient(config_path)
    return _vllm_client


def reset_vllm_client():
    """Reset the global VLLM client instance (useful after moving project directory)"""
    global _vllm_client
    _vllm_client = None

