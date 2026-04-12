"""
GPU 资源上下文管理器

提供统一的 GPU 资源管理接口，用于：
1. 自动管理模型加载和卸载
2. 显存清理
3. 异常安全的资源释放

使用方式：
    from src.utils.gpu_context import gpu_context

    with gpu_context("模型名称"):
        model = load_model()
        result = model.predict()
    # 自动释放显存
"""

from contextlib import contextmanager
from typing import Optional, Any


def _get_torch():
    try:
        import torch
        return torch
    except ImportError:
        return None


@contextmanager
def gpu_context(component_name: str, injected: Any = None):
    component = injected
    try:
        yield component
    finally:
        if injected is None and component is not None:
            del component
        torch = _get_torch()
        if torch and torch.cuda.is_available():
            torch.cuda.empty_cache()
            print(f"[{component_name}] GPU 显存已释放")


def clear_gpu_memory():
    torch = _get_torch()
    if torch and torch.cuda.is_available():
        torch.cuda.empty_cache()
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        print(f"[GPU Memory] 已清理，当前占用: {allocated:.2f}GB (预留: {reserved:.2f}GB)")
