"""
统一模型管理器

通过注册表 + 工厂函数 + 单例缓存，统一管理各类模型的实例化和生命周期。
新增模型只需 register() + 工厂函数，不改现有代码。

用法：
    from src.core.model_manager import get_model_manager

    mgr = get_model_manager()
    translator = mgr.get("llm", "deepseek")
    asr = mgr.get("asr", "faster_whisper", model_size="large-v3")
    tts = mgr.get("tts", "qwen3", voice="Vivian")
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class _RegistryEntry:
    """注册表中的一项：一个 provider 的工厂和默认配置"""
    name: str
    factory: Callable
    config_defaults: Dict[str, str] = field(default_factory=dict)


class ModelManager:
    """
    统一模型管理器

    - 注册表按 category（llm/asr/tts/separator）分组，每组可有多个 provider
    - get() 自动从 Config 读取默认参数，调用方可通过 kwargs 覆盖
    - 每个 (category, name) 组合只创建一次实例（单例）
    - 工厂函数内延迟 import，不触发重依赖加载
    """

    _registry: Dict[str, Dict[str, _RegistryEntry]] = {}
    _category_default_config: Dict[str, str] = {
        "llm": "api.provider",
        "tts": "tts.engine",
    }

    def __init__(self):
        self._instances: Dict[str, Any] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 注册（类方法）
    # ------------------------------------------------------------------

    @classmethod
    def register(
        cls,
        category: str,
        name: str,
        factory: Callable,
        config_defaults: Optional[Dict[str, str]] = None,
    ) -> None:
        """注册一个 model provider（通常在模块加载时调用）"""
        if category not in cls._registry:
            cls._registry[category] = {}
        cls._registry[category][name] = _RegistryEntry(
            name=name,
            factory=factory,
            config_defaults=config_defaults or {},
        )

    @classmethod
    def available(cls, category: str) -> List[str]:
        """列出某 category 下所有已注册的 provider 名称"""
        return list(cls._registry.get(category, {}).keys())

    @classmethod
    def categories(cls) -> List[str]:
        """列出所有已注册的 category"""
        return list(cls._registry.keys())

    # ------------------------------------------------------------------
    # 获取实例（核心方法）
    # ------------------------------------------------------------------

    def get(self, category: str, name: str = None, **kwargs) -> Any:
        """
        获取模型实例（单例 + Config 自动填充 + 调用方 kwargs 覆盖）

        Args:
            category: 模型类别 ("llm" / "asr" / "tts" / "separator")
            name: provider 名称，为 None 时使用 Config 中的默认值
            **kwargs: 传给工厂函数的额外参数，会覆盖 Config 默认值

        Returns:
            模型实例（类型取决于 provider）
        """
        if name is None:
            name = self._default_name(category)

        cat_registry = self._registry.get(category)
        if cat_registry is None:
            raise ValueError(f"未知模型类别: '{category}'，可用: {self.categories()}")
        entry = cat_registry.get(name)
        if entry is None:
            raise ValueError(
                f"未知 provider: '{name}'，{category} 可用: {self.available(category)}"
            )

        cache_key = f"{category}/{name}"

        with self._lock:
            if cache_key in self._instances:
                return self._instances[cache_key]

            # 合并参数：config_defaults → 调用方 kwargs 覆盖
            resolved = self._resolve_config(entry.config_defaults)
            resolved.update(kwargs)

            instance = entry.factory(**resolved)
            self._instances[cache_key] = instance
            return instance

    # ------------------------------------------------------------------
    # 生命周期管理
    # ------------------------------------------------------------------

    def unload(self, category: str, name: str = None) -> None:
        """卸载指定模型实例，释放资源（如 GPU 显存）"""
        if name is None:
            name = self._default_name(category)
        cache_key = f"{category}/{name}"

        with self._lock:
            instance = self._instances.pop(cache_key, None)

        if instance is not None and hasattr(instance, "unload"):
            instance.unload()

        self._try_empty_cuda_cache()

    def unload_all(self) -> None:
        """卸载所有已加载的模型实例"""
        with self._lock:
            instances = list(self._instances.values())
            self._instances.clear()

        for instance in instances:
            if hasattr(instance, "unload"):
                instance.unload()

        self._try_empty_cuda_cache()

    def is_loaded(self, category: str, name: str = None) -> bool:
        """检查指定模型是否已加载"""
        if name is None:
            name = self._default_name(category)
        cache_key = f"{category}/{name}"
        return cache_key in self._instances

    # ------------------------------------------------------------------
    # 便捷方法（带类型提示）
    # ------------------------------------------------------------------

    def get_llm(self, name: str = None, **kwargs) -> Any:
        """获取 LLM 文字处理实例（Translator）"""
        return self.get("llm", name, **kwargs)

    def get_asr(self, name: str = None, **kwargs) -> Any:
        """获取 ASR 语音识别实例"""
        return self.get("asr", name, **kwargs)

    def get_tts(self, name: str = None, **kwargs) -> Any:
        """获取 TTS 语音合成实例"""
        return self.get("tts", name, **kwargs)

    def get_separator(self, name: str = None, **kwargs) -> Any:
        """获取 VocalSeparator 人声分离实例"""
        return self.get("separator", name, **kwargs)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _default_name(self, category: str) -> str:
        """根据 category 从 Config 读取默认 provider 名称"""
        config_key = self._category_default_config.get(category)
        if config_key:
            from src.config import config
            value = config.get(config_key)
            if value:
                return value

        # 没有 Config 映射的 category（如 asr/separator），返回第一个注册项
        cat_registry = self._registry.get(category, {})
        if cat_registry:
            return next(iter(cat_registry))
        raise ValueError(f"无法确定 '{category}' 的默认 provider，且无已注册项")

    @staticmethod
    def _resolve_config(config_defaults: Dict[str, str]) -> Dict[str, Any]:
        """从 Config 读取默认参数"""
        if not config_defaults:
            return {}
        from src.config import config
        resolved = {}
        for param_name, config_path in config_defaults.items():
            resolved[param_name] = config.get(config_path)
        return resolved

    @staticmethod
    def _try_empty_cuda_cache():
        """尝试释放 CUDA 缓存（如果 torch 可用）"""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


# ======================================================================
# 工厂函数（延迟 import，避免加载重依赖）
# ======================================================================

def _make_llm(**kwargs):
    from src.core.translate import Translator
    return Translator(**kwargs)


def _make_deepseek_llm(**kwargs):
    from src.core.translate import Translator
    kwargs.setdefault("provider", "deepseek")
    return Translator(**kwargs)


def _make_openai_llm(**kwargs):
    from src.core.translate import Translator
    kwargs.setdefault("provider", "openai")
    return Translator(**kwargs)


def _make_asr(**kwargs):
    from src.core.asr import ASRRecognizer
    return ASRRecognizer(**kwargs)


def _make_tts(**kwargs):
    from src.core.tts import TTSEngine
    return TTSEngine(**kwargs)


def _make_edge_tts(**kwargs):
    from src.core.tts import TTSEngine
    kwargs.setdefault("engine", "edge")
    return TTSEngine(**kwargs)


def _make_qwen3_tts(**kwargs):
    from src.core.tts import TTSEngine
    kwargs.setdefault("engine", "qwen3")
    return TTSEngine(**kwargs)


def _make_separator(**kwargs):
    from src.core.vocal_separator import VocalSeparator
    return VocalSeparator(**kwargs)


# ======================================================================
# 内置注册
# ======================================================================

# --- LLM / 文字处理 ---
ModelManager.register("llm", "deepseek", _make_deepseek_llm, config_defaults={
    "api_key": "api.deepseek_api_key",
    "base_url": "api.deepseek_base_url",
})
ModelManager.register("llm", "openai", _make_openai_llm, config_defaults={
    "api_key": "api.openai_api_key",
    "base_url": "api.openai_base_url",
})

# --- ASR ---
ModelManager.register("asr", "faster_whisper", _make_asr, config_defaults={
    "model_size": "processing.asr_model",
})

# --- TTS ---
ModelManager.register("tts", "edge", _make_edge_tts, config_defaults={
    "voice": "tts.voice",
})
ModelManager.register("tts", "qwen3", _make_qwen3_tts, config_defaults={
    "voice": "tts.voice",
    "speed": "tts.speed",
})

# --- 人声分离 ---
ModelManager.register("separator", "demucs", _make_separator, config_defaults={
    "model_name": "processing.vocal_model",
})


# ======================================================================
# 模块级单例
# ======================================================================

_manager: Optional[ModelManager] = None
_manager_lock = threading.Lock()


def get_model_manager() -> ModelManager:
    """获取全局 ModelManager 单例"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ModelManager()
    return _manager
