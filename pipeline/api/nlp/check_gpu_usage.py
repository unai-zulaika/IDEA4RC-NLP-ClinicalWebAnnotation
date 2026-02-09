#!/usr/bin/env python3
"""
Script to verify GPU usage with llama.cpp
This helps diagnose why nvidia-smi might not show processes.
"""

import os
from pathlib import Path
import time

def check_gpu_before_after():
    """Check GPU memory before and after loading llama.cpp model"""
    
    # Try to get GPU info before
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        
        print("=" * 60)
        print("GPU Status BEFORE Model Loading")
        print("=" * 60)
        mem_before = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util_before = pynvml.nvmlDeviceGetUtilizationRates(handle)
        procs_before = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        
        print(f"GPU Memory Used: {mem_before.used / (1024**3):.2f}GB / {mem_before.total / (1024**3):.2f}GB")
        print(f"GPU Utilization: {util_before.gpu}%")
        print(f"Active GPU Processes: {len(procs_before)}")
        if procs_before:
            for proc in procs_before:
                print(f"  PID {proc.pid}: {proc.usedGpuMemory / (1024**3):.2f}GB")
        print()
        
        # Load model
        from llama_cpp import Llama
        
        model_path = Path("meta-llama-3.1-8b-instruct-q4_k_m.gguf")
        if not model_path.exists():
            print(f"ERROR: Model not found at {model_path}")
            return
        
        print("Loading llama.cpp model with n_gpu_layers=-1...")
        os.environ['LLAMA_N_GPU_LAYERS'] = '-1'
        
        llm = Llama(
            model_path=str(model_path),
            n_ctx=2048,
            n_gpu_layers=-1,
            verbose=True  # Enable verbose to see GPU info
        )
        
        time.sleep(2)  # Wait for GPU allocation
        
        print("\n" + "=" * 60)
        print("GPU Status AFTER Model Loading")
        print("=" * 60)
        mem_after = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util_after = pynvml.nvmlDeviceGetUtilizationRates(handle)
        procs_after = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        
        print(f"GPU Memory Used: {mem_after.used / (1024**3):.2f}GB / {mem_after.total / (1024**3):.2f}GB")
        print(f"Memory Increase: {(mem_after.used - mem_before.used) / (1024**3):.2f}GB")
        print(f"GPU Utilization: {util_after.gpu}%")
        print(f"Active GPU Processes: {len(procs_after)}")
        if procs_after:
            for proc in procs_after:
                print(f"  PID {proc.pid}: {proc.usedGpuMemory / (1024**3):.2f}GB")
        else:
            print("  ⚠️  No processes in nvidia-smi process list")
            print("  Note: llama.cpp uses CUDA but may not always show as a process")
            print(f"  However, GPU memory increased by {(mem_after.used - mem_before.used) / (1024**3):.2f}GB")
            print("  This indicates GPU is being used (memory allocated)")
        
        # Test inference to see if GPU utilization increases
        print("\n" + "=" * 60)
        print("Testing Inference (watch GPU utilization)")
        print("=" * 60)
        print("Running inference...")
        
        result = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is 2+2? Answer in one word."}
            ],
            max_tokens=10
        )
        
        time.sleep(1)
        
        util_during = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem_during = pynvml.nvmlDeviceGetMemoryInfo(handle)
        
        print(f"\nDuring Inference:")
        print(f"  GPU Utilization: {util_during.gpu}%")
        print(f"  Memory Usage: {mem_during.used / (1024**3):.2f}GB")
        
        print("\n" + "=" * 60)
        print("CONCLUSION")
        print("=" * 60)
        if (mem_after.used - mem_before.used) > 100 * (1024**2):  # More than 100MB increase
            print("✓ GPU IS BEING USED")
            print("  - GPU memory was allocated (indicates CUDA usage)")
            if util_during.gpu > 0:
                print(f"  - GPU utilization increased during inference ({util_during.gpu}%)")
            print("\nWhy nvidia-smi might show 'No processes':")
            print("  1. llama.cpp uses CUDA through C++ bindings")
            print("  2. Process tracking in nvidia-smi may not always capture CUDA contexts")
            print("  3. GPU memory is allocated but process name might not appear")
            print("\nTo verify GPU usage:")
            print("  - Check GPU memory usage (should increase)")
            print("  - Monitor GPU utilization during inference (watch -n 1 nvidia-smi)")
            print("  - Check temperature/fan speed (should increase during compute)")
        else:
            print("⚠ GPU MAY NOT BE USED")
            print("  - Memory increase was minimal")
            print("  - Check if CUDA is properly configured")
        
        pynvml.nvmlShutdown()
        
    except ImportError:
        print("pynvml not installed. Install with: pip install nvidia-ml-py3")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_gpu_before_after()

