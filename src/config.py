"""
配置文件模块

支持从 config.json 或 config.toml 读取配置
默认配置文件位置: 项目根目录 / 用户配置目录
"""

import os
import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


# 项目配置目录
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "config.json"


class Config:
    """配置管理器"""

    _instance = None
    _lock = threading.Lock()
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

        # 默认配置
        self._config = {
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
            },
            "processing": {
                "original_volume": 0.85,
                "tts_volume": 0.5,
                "tts_delay": 0,
                "vocal_model": "htdemucs",
                "asr_model": "base",
            },
        }

        # 加载配置文件
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                self._merge_config(self._config, user_config)
                print(f"[Config] 加载配置文件: {CONFIG_FILE}")
            except Exception as e:
                print(f"[Config] 加载配置失败: {e}")

        # 合并环境变量（环境变量优先级最高）
        self._load_from_env()

        # 如果配置文件不存在，创建默认配置
        if not CONFIG_FILE.exists():
            self.save()

    def _merge_config(self, base: dict, update: dict):
        """深度合并配置"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def _load_from_env(self):
        """从环境变量加载配置"""
        if os.environ.get("DEEPSEEK_API_KEY"):
            self._config["api"]["deepseek_api_key"] = os.environ["DEEPSEEK_API_KEY"]
        if os.environ.get("OPENAI_API_KEY"):
            self._config["api"]["openai_api_key"] = os.environ["OPENAI_API_KEY"]

    def save(self):
        """保存配置到文件"""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=4, ensure_ascii=False)
            print(f"[Config] 保存配置文件: {CONFIG_FILE}")
        except Exception as e:
            print(f"[Config] 保存配置失败: {e}")

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

    def validate(self) -> Tuple[bool, List[str]]:
        """
        验证配置有效性（Phase 3）

        Returns:
            Tuple[bool, List[str]]: (是否有效, 错误信息列表)
        """
        errors: List[str] = []

        # 验证 API 配置
        provider = self.get("api.provider", "")
        if provider not in ("deepseek", "openai"):
            errors.append(f"api.provider 必须是 'deepseek' 或 'openai'，当前: {provider}")

        if provider and not self.get_api_key(provider):
            errors.append(f"API provider '{provider}' 的 API Key 未设置")

        # 验证 TTS 配置
        tts_engine = self.get("tts.engine", "")
        if tts_engine not in ("edge", "qwen3"):
            errors.append(f"tts.engine 必须是 'edge' 或 'qwen3'，当前: {tts_engine}")

        speed = self.get("tts.speed", 1.0)
        if not isinstance(speed, (int, float)) or speed < 0.1 or speed > 3.0:
            errors.append(f"tts.speed 必须在 0.1-3.0 之间，当前: {speed}")

        # 验证音量配置
        orig_vol = self.get("processing.original_volume", 0.85)
        tts_vol = self.get("processing.tts_volume", 0.5)
        if not (0 <= orig_vol <= 1.5):
            errors.append(f"processing.original_volume 必须在 0-1.5 之间，当前: {orig_vol}")
        if not (0 <= tts_vol <= 2.0):
            errors.append(f"processing.tts_volume 必须在 0-2.0 之间，当前: {tts_vol}")

        # 验证模型配置
        vocal_model = self.get("processing.vocal_model", "")
        if vocal_model not in ("htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx", "mdx_extra"):
            errors.append(f"processing.vocal_model 不支持: {vocal_model}")

        return (len(errors) == 0, errors)


# 全局配置实例
config = Config()


def get_api_key(provider: str = "deepseek") -> str:
    """获取 API Key（便捷函数）"""
    return config.get_api_key(provider)
