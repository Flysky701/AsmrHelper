"""
Qwen3-TTS model manager.

This manager keeps runtime singleton behavior, while the actual on-disk
location of the models is resolved through the shared model resource layer.
"""

import threading
from pathlib import Path
from typing import Any, Dict

import torch


class Qwen3ModelManager:
    """Singleton-style lazy loader for Qwen3 TTS models."""

    _instances: Dict[str, Any] = {}
    _lock = threading.Lock()
    _MODEL_IDS = {
        "custom_voice": "qwen3-custom-voice",
        "voice_design": "qwen3-voice-design",
        "base": "qwen3-base",
    }
    _MODEL_SUBDIRS = {
        "custom_voice": "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "voice_design": "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "base": "models--Qwen--Qwen3-TTS-12Hz-1.7B-Base",
    }

    @classmethod
    def _get_model_dir(cls, model_type: str, download_root: str = None) -> Path:
        if download_root:
            model_dir = Path(download_root) / cls._MODEL_SUBDIRS[model_type]
        else:
            from src.core.resources import get_model_service

            service = get_model_service()
            model_dir = service.resolve_install_dir(cls._MODEL_IDS[model_type])

        if not model_dir.exists():
            raise FileNotFoundError(
                f"模型目录不存在: {model_dir}\n"
                "请先通过项目内模型管理命令下载对应模型。"
            )
        return model_dir

    @classmethod
    def get_model(cls, model_type: str, download_root: str = None) -> Any:
        if model_type not in cls._MODEL_SUBDIRS:
            raise ValueError(f"未知的模型类型: {model_type}")

        with cls._lock:
            if model_type in cls._instances and cls._instances[model_type] is not None:
                print(f"[Qwen3ModelManager] 复用已加载的模型: {model_type}")
                return cls._instances[model_type]

            model_dir = cls._get_model_dir(model_type, download_root)
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
        return cls.get_model("custom_voice", download_root)

    @classmethod
    def get_voice_design_model(cls, download_root: str = None) -> Any:
        return cls.get_model("voice_design", download_root)

    @classmethod
    def get_base_model(cls, download_root: str = None) -> Any:
        return cls.get_model("base", download_root)

    @classmethod
    def unload(cls, model_type: str):
        if model_type in cls._instances:
            print(f"[Qwen3ModelManager] 卸载模型: {model_type}")
            cls._instances[model_type] = None
            del cls._instances[model_type]

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    @classmethod
    def unload_all(cls):
        print("[Qwen3ModelManager] 卸载所有模型...")
        for model_type in list(cls._instances.keys()):
            cls.unload(model_type)

    @classmethod
    def is_loaded(cls, model_type: str) -> bool:
        return model_type in cls._instances and cls._instances[model_type] is not None

    @classmethod
    def get_gpu_memory_info(cls) -> dict:
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
