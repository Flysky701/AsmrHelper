"""
Qwen3-TTS 模型管理器

功能：
1. 模型单例化 - 避免重复加载 8.4GB 模型
2. 分模型加载 - CustomVoice / VoiceDesign / Base 按需加载
3. 显存管理 - 用完可卸载释放显存
"""

import torch
import os
import threading
from pathlib import Path
from typing import Optional, Dict, Any

from src.config import PROJECT_ROOT  # 统一使用项目根目录


class Qwen3ModelManager:
    """Qwen3 模型管理器 - 单例 + 延迟加载"""

    _instances: Dict[str, Any] = {}
    _lock = threading.Lock()

    # 模型本地路径（相对于 models/qwen3tts/）
    _MODEL_SUBDIRS = {
        "custom_voice": "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "voice_design": "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "base": "models--Qwen--Qwen3-TTS-12Hz-1.7B-Base",
    }

    @classmethod
    def _get_model_dir(cls, model_type: str, download_root: str = None) -> Path:
        """获取模型本地目录的绝对路径"""
        if download_root:
            base = Path(download_root)
        else:
            # 统一使用 PROJECT_ROOT
            base = PROJECT_ROOT / "models" / "qwen3tts"

        model_dir = base / cls._MODEL_SUBDIRS[model_type]
        if not model_dir.exists():
            raise FileNotFoundError(
                f"模型目录不存在: {model_dir}\n"
                f"请从 HuggingFace 下载模型到该目录"
            )
        return model_dir

    @classmethod
    def get_model(cls, model_type: str, download_root: str = None) -> Any:
        """
        获取指定类型的模型（延迟加载，单例复用）

        Args:
            model_type: "custom_voice" | "voice_design" | "base"
            download_root: 模型根目录（默认 models/qwen3tts）

        Returns:
            Qwen3TTSModel 实例
        """
        if model_type not in cls._MODEL_SUBDIRS:
            raise ValueError(f"未知的模型类型: {model_type}")

        with cls._lock:
            # 已加载则直接返回
            if model_type in cls._instances and cls._instances[model_type] is not None:
                print(f"[Qwen3ModelManager] 复用已加载的模型: {model_type}")
                return cls._instances[model_type]

            model_dir = cls._get_model_dir(model_type, download_root)

            # 首次加载
            print(f"[Qwen3ModelManager] 加载模型: {model_type} ({model_dir})...")

            t0 = torch.cuda.Event(enable_timing=True) if torch.cuda.is_available() else None
            t1 = torch.cuda.Event(enable_timing=True) if torch.cuda.is_available() else None

            if t0:
                t0.record()

            from qwen_tts import Qwen3TTSModel

            model = Qwen3TTSModel.from_pretrained(
                str(model_dir),
                device_map="cuda:0",
                dtype=torch.bfloat16,
            )

            if t1:
                t1.record()
                torch.cuda.synchronize()
                print(f"[Qwen3ModelManager] 模型加载完成，耗时: {t0.elapsed_time(t1)/1000:.1f}s")

            cls._instances[model_type] = model
            return model

    @classmethod
    def get_custom_voice_model(cls, download_root: str = None) -> Any:
        """获取 CustomVoice 模型"""
        return cls.get_model("custom_voice", download_root)

    @classmethod
    def get_voice_design_model(cls, download_root: str = None) -> Any:
        """获取 VoiceDesign 模型"""
        return cls.get_model("voice_design", download_root)

    @classmethod
    def get_base_model(cls, download_root: str = None) -> Any:
        """获取 Base 模型 (用于 VoiceClone)"""
        return cls.get_model("base", download_root)

    @classmethod
    def unload(cls, model_type: str):
        """卸载指定模型释放显存"""
        if model_type in cls._instances:
            print(f"[Qwen3ModelManager] 卸载模型: {model_type}")
            cls._instances[model_type] = None
            del cls._instances[model_type]

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    @classmethod
    def unload_all(cls):
        """卸载所有模型"""
        print("[Qwen3ModelManager] 卸载所有模型...")
        for model_type in list(cls._instances.keys()):
            cls.unload(model_type)

    @classmethod
    def is_loaded(cls, model_type: str) -> bool:
        """检查模型是否已加载"""
        return model_type in cls._instances and cls._instances[model_type] is not None

    @classmethod
    def get_gpu_memory_info(cls) -> dict:
        """获取 GPU 显存信息"""
        if not torch.cuda.is_available():
            return {"available": False}

        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3

        return {
            "available": True,
            "allocated_gb": round(allocated, 2),
            "reserved_gb": round(reserved, 2),
            "total_gb": round(total, 2),
            "free_gb": round(total - reserved, 2),
        }
