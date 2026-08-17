"""
配置文件模块

支持从 config.json 或 config.toml 读取配置
默认配置文件位置: 项目根目录 / 用户配置目录
"""

from copy import deepcopy
import os
import json
import threading
from pathlib import Path
from typing import Dict, Any, List, Tuple


# 项目配置目录
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "config.json"


class Config:
    """配置管理器"""

    _instance = None
    _lock = threading.Lock()
    _state_lock = threading.RLock()
    _config: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """加载配置文件"""
        # 创建配置目录（如果不存在）
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._config = self.build_effective_config()

        # 如果配置文件不存在，创建默认配置
        if not CONFIG_FILE.exists():
            self.save()

    def _default_config(self) -> Dict[str, Any]:
        """返回内置默认配置。"""
        return {
            "api": {
                "provider": "deepseek",
                "deepseek_api_key": "",
                "openai_api_key": "",
                "deepseek_base_url": "https://api.deepseek.com",
                "openai_base_url": "https://api.openai.com/v1",
            },
            "tts": {
                "engine": "edge",
                "voice": "zh-CN-XiaoxiaoNeural",
                "speed": 1.0,
            },
            "paths": {
                "output_dir": "",
                "vtt_dir": "",
                "model_cache_dir": "",
                "temp_dir": "",
            },
            "processing": {
                "original_volume": 0.85,
                "tts_volume": 0.5,
                "tts_delay": 0,
                "vocal_model": "htdemucs",
                "asr_model": "faster-whisper-base",
            },
        }

    def _merge_config(self, base: dict, update: dict):
        """深度合并配置"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def _apply_env_overrides(self, target: Dict[str, Any]):
        """从环境变量覆盖配置。"""
        if os.environ.get("DEEPSEEK_API_KEY"):
            target["api"]["deepseek_api_key"] = os.environ["DEEPSEEK_API_KEY"]
        if os.environ.get("OPENAI_API_KEY"):
            target["api"]["openai_api_key"] = os.environ["OPENAI_API_KEY"]

    def _read_config_file(self) -> Dict[str, Any]:
        """读取配置文件内容。"""
        if not CONFIG_FILE.exists():
            return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            print(f"[Config] 加载配置文件: {CONFIG_FILE}")
            return user_config
        except Exception as e:
            print(f"[Config] 加载配置失败: {e}")
            return {}

    def build_effective_config(
        self,
        config_override: Dict[str, Any] | None = None,
        include_env: bool = True,
    ) -> Dict[str, Any]:
        """构建生效配置视图。"""
        effective = self._default_config()
        self._merge_config(effective, self._read_config_file())
        if config_override:
            self._merge_config(effective, config_override)
        if include_env:
            self._apply_env_overrides(effective)
        return effective

    def reload(self):
        """重新加载生效配置。"""
        self._config = self.build_effective_config()

    def save(self, config_data: Dict[str, Any] | None = None):
        """原子保存配置；失败必须向调用方报告。"""
        data = config_data if config_data is not None else self._config
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = CONFIG_FILE.with_name(
            f".{CONFIG_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, CONFIG_FILE)
            print(f"[Config] 保存配置文件: {CONFIG_FILE}")
        except Exception as e:
            temp_file.unlink(missing_ok=True)
            print(f"[Config] 保存配置失败: {e}")
            raise OSError(f"保存配置失败: {e}") from e

    def get_file_config(self) -> Dict[str, Any]:
        """返回磁盘配置视图（不含环境变量覆盖）。"""
        return self._read_config_file()

    def to_dict(self) -> Dict[str, Any]:
        """返回当前生效配置副本。"""
        return deepcopy(self._config)

    def persist_updates(self, updates: Dict[str, Any]):
        """将部分配置合并到磁盘配置并重新加载。"""
        with self._state_lock:
            file_config = self.get_file_config()
            self._merge_config(file_config, updates)
            self.save(config_data=file_config)
            self.reload()

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号路径，如 'api.deepseek_api_key'"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        """设置配置值，支持点号路径"""
        keys = key.split(".")
        target = self._config
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

    @property
    def deepseek_api_key(self) -> str:
        return self.get("api.deepseek_api_key", "")

    @property
    def openai_api_key(self) -> str:
        return self.get("api.openai_api_key", "")

    def get_api_key(self, provider: str = "deepseek") -> str:
        """获取指定 provider 的 API Key"""
        if provider == "deepseek":
            return self.deepseek_api_key
        elif provider == "openai":
            return self.openai_api_key
        return ""

    def validate(self, config_data: Dict[str, Any] | None = None) -> Tuple[bool, List[str]]:
        """
        验证配置有效性（Phase 3）

        Returns:
            Tuple[bool, List[str]]: (是否有效, 错误信息列表)
        """
        errors: List[str] = []
        target = config_data if config_data is not None else self._config

        # 验证 API 配置
        provider = self._get_from_mapping(target, "api.provider", "")
        if provider not in ("deepseek", "openai"):
            errors.append(f"api.provider 必须是 'deepseek' 或 'openai'，当前: {provider}")

        if provider and not self._get_api_key_from_mapping(target, provider):
            errors.append(f"API provider '{provider}' 的 API Key 未设置")

        # 验证 TTS 配置
        tts_engine = self._get_from_mapping(target, "tts.engine", "")
        if tts_engine not in ("edge", "qwen3", "kokoro"):
            errors.append(f"tts.engine 必须是 'edge'、'qwen3' 或 'kokoro'，当前: {tts_engine}")

        speed = self._get_from_mapping(target, "tts.speed", 1.0)
        if not self._is_number(speed) or speed < 0.1 or speed > 3.0:
            errors.append(f"tts.speed 必须在 0.1-3.0 之间，当前: {speed}")

        # 验证音量配置
        orig_vol = self._get_from_mapping(target, "processing.original_volume", 0.85)
        tts_vol = self._get_from_mapping(target, "processing.tts_volume", 0.5)
        if not self._is_number(orig_vol) or not (0 <= orig_vol <= 1.5):
            errors.append(f"processing.original_volume 必须在 0-1.5 之间，当前: {orig_vol}")
        if not self._is_number(tts_vol) or not (0 <= tts_vol <= 2.0):
            errors.append(f"processing.tts_volume 必须在 0-2.0 之间，当前: {tts_vol}")

        # 验证模型配置
        vocal_model = self._get_from_mapping(target, "processing.vocal_model", "")
        if vocal_model not in ("htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx", "mdx_extra"):
            errors.append(f"processing.vocal_model 不支持: {vocal_model}")

        return (len(errors) == 0, errors)

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _get_from_mapping(self, mapping: Dict[str, Any], key: str, default: Any = None) -> Any:
        """从指定映射获取点路径配置。"""
        keys = key.split(".")
        value: Any = mapping
        for current in keys:
            if isinstance(value, dict):
                value = value.get(current)
                if value is None:
                    return default
            else:
                return default
        return value

    def _get_api_key_from_mapping(self, mapping: Dict[str, Any], provider: str = "deepseek") -> str:
        """从指定映射中获取 provider API Key。"""
        if provider == "deepseek":
            return self._get_from_mapping(mapping, "api.deepseek_api_key", "")
        if provider == "openai":
            return self._get_from_mapping(mapping, "api.openai_api_key", "")
        return ""


# 全局配置实例
config = Config()


def get_api_key(provider: str = "deepseek") -> str:
    """获取 API Key（便捷函数）"""
    return config.get_api_key(provider)
