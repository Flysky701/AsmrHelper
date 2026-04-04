"""
GPU 资源管理器 - 控制 GPU 并发访问，防止 OOM

功能：
1. Semaphore 控制 GPU 模型数量（避免同时加载多个大模型导致 OOM）
2. 支持上下文管理器，方便资源申请/释放
3. 提供显存监控信息

使用方式：
    from src.core.gpu_manager import gpu_lock

    # 在 GPU 密集操作中使用
    with gpu_lock:
        separator = VocalSeparator(model_name="htdemucs")
        separator.separate(...)
"""

import threading
import torch
from typing import Optional


class GPUManager:
    """
    GPU 资源管理器

    使用信号量控制 GPU 访问，防止多线程同时在 GPU 上加载大模型导致 OOM。

    适用场景：
    - Demucs 人声分离 (~1.5GB VRAM)
    - Whisper ASR (~3GB VRAM)
    - Qwen3-TTS (~2GB VRAM)

    RTX 4070 Ti SUPER (16GB) 建议同时运行不超过 1 个 GPU 模型。
    """

    _instance: Optional["GPUManager"] = None
    _lock = threading.Lock()

    def __new__(cls, max_concurrent: int = 1):
        """单例模式，确保全局只有一个 GPU 管理器"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self, max_concurrent: int = 1):
        """
        初始化 GPU 管理器

        Args:
            max_concurrent: 最大并发 GPU 操作数（默认 1，避免 OOM）
        """
        if self._initialized:
            # 单例已初始化，如果参数不同则更新信号量
            if max_concurrent != self._max_concurrent:
                print(f"[GPU Manager] 更新最大并发: {self._max_concurrent} -> {max_concurrent}")
                self._max_concurrent = max_concurrent
                self._semaphore = threading.Semaphore(max_concurrent)
            return
        self._initialized = True

        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._active_count = 0
        self._count_lock = threading.Lock()

        print(f"[GPU Manager] 初始化，最大并发: {max_concurrent}")
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            total_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
            print(f"[GPU Manager] GPU: {gpu_name}, 显存: {total_mem:.1f}GB")
        else:
            print("[GPU Manager] 未检测到 CUDA GPU，将使用 CPU")

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        申请 GPU 资源

        Args:
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            bool: 是否成功获取资源
        """
        result = self._semaphore.acquire(timeout=timeout)
        if result:
            with self._count_lock:
                self._active_count += 1
        return result

    def release(self):
        """释放 GPU 资源"""
        with self._count_lock:
            if self._active_count > 0:
                self._active_count -= 1
        self._semaphore.release()

    def __enter__(self):
        """上下文管理器入口"""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.release()
        # 释放 GPU 显存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return False

    @property
    def active_count(self) -> int:
        """当前活跃的 GPU 操作数"""
        with self._count_lock:
            return self._active_count

    def get_gpu_memory_info(self) -> dict:
        """获取 GPU 显存使用信息"""
        if not torch.cuda.is_available():
            return {"available": False}

        device = torch.cuda.current_device()
        props = torch.cuda.get_device_properties(device)
        total_mem = props.total_memory / 1024**3
        allocated = torch.cuda.memory_allocated(device) / 1024**3
        reserved = torch.cuda.memory_reserved(device) / 1024**3

        return {
            "available": True,
            "name": props.name,
            "total_gb": total_mem,
            "allocated_gb": allocated,
            "reserved_gb": reserved,
            "free_gb": total_mem - reserved,
            "active_operations": self._active_count,
        }

    def print_memory_status(self):
        """打印当前 GPU 显存状态"""
        info = self.get_gpu_memory_info()
        if info["available"]:
            print(
                f"[GPU] {info['name']} | "
                f"已用: {info['allocated_gb']:.1f}GB | "
                f"缓存: {info['reserved_gb']:.1f}GB | "
                f"空闲: {info['free_gb']:.1f}GB | "
                f"活跃操作: {info['active_operations']}/{self._max_concurrent}"
            )
        else:
            print("[GPU] CPU 模式")

    def clear_cache(self):
        """清理 GPU 显存缓存"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print("[GPU Manager] 显存缓存已清理")


# 全局 GPU 锁实例（默认最大并发 1）
# 可通过修改 max_concurrent 调整并发度
def get_gpu_lock(max_concurrent: int = 1) -> GPUManager:
    """获取全局 GPU 锁实例"""
    return GPUManager(max_concurrent=max_concurrent)


# 便捷的全局实例
gpu_lock = GPUManager(max_concurrent=1)
