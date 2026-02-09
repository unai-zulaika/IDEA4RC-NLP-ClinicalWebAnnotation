"""
Server status and metrics routes
"""

from fastapi import APIRouter, HTTPException
from typing import List

from services.vllm_client import get_vllm_client
from models.schemas import ServerStatus, ServerMetrics, ModelInfo

router = APIRouter()


@router.get("/status", response_model=ServerStatus)
async def get_server_status():
    """Get vLLM server status"""
    client = get_vllm_client()
    status = client.get_status()
    
    return ServerStatus(
        status=status.get("status", "unknown"),
        model_name=status.get("model_name"),
        endpoint=status.get("endpoint")
    )


@router.get("/metrics", response_model=ServerMetrics)
async def get_server_metrics():
    """Get server metrics (GPU memory, throughput, etc.)"""
    client = get_vllm_client()
    
    if not client.is_available():
        raise HTTPException(status_code=503, detail="VLLM server not available")
    
    metrics = client.get_metrics()
    
    return ServerMetrics(
        gpu_memory_used_gb=metrics.get("gpu_memory_used_gb"),
        gpu_memory_total_gb=metrics.get("gpu_memory_total_gb"),
        gpu_utilization_percent=metrics.get("gpu_utilization_percent"),
        throughput_tokens_per_sec=metrics.get("throughput_tokens_per_sec"),
        throughput_requests_per_sec=metrics.get("throughput_requests_per_sec"),
        active_requests=metrics.get("active_requests")
    )


@router.get("/models", response_model=List[ModelInfo])
async def list_models():
    """List available models (including Multi-LoRA adapters)"""
    client = get_vllm_client()
    
    if not client.is_available():
        return []
    
    models = client.list_models()
    return [ModelInfo(**model) for model in models]


@router.post("/models/switch")
async def switch_model(model_name: str):
    """Switch active model/LoRA"""
    client = get_vllm_client()
    
    if not client.is_available():
        raise HTTPException(status_code=503, detail="VLLM server not available")
    
    success = client.switch_model(model_name)
    
    if success:
        return {"message": f"Switched to model: {model_name}", "model_name": model_name}
    else:
        raise HTTPException(status_code=500, detail="Failed to switch model")

