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

import torch
from contextlib import contextmanager
from typing import Optional, Any


@contextmanager
def gpu_context(component_name: str, injected: Any = None):
    """
    GPU 资源上下文管理器

    Args:
        component_name: 组件名称（用于日志）
        injected: 已注入的组件（不为 None 时跳过自动创建）

    Yields:
        组件实例或 None

    示例:
        with gpu_context("人声分离") as separator:
            if separator is None:
                separator = VocalSeparator()
            result = separator.separate(audio)
        # 自动释放显存
    """
    component = injected
    try:
        yield component
    finally:
        # 释放显存
        if injected is None and component is not None:
            del component
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print(f"[{component_name}] GPU 显存已释放")


def clear_gpu_memory():
    """
    清理 GPU 显存

    相当于 torch.cuda.empty_cache()，但提供日志输出
    """
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        print(f"[GPU Memory] 已清理，当前占用: {allocated:.2f}GB (预留: {reserved:.2f}GB)")
