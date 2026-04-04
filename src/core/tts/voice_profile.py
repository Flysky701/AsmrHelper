"""
Qwen3-TTS 音色配置管理模块

功能：
1. VoiceProfile 数据类 - 统一音色数据结构
2. VoiceProfileManager - 管理音色配置（JSON 持久化）
3. 支持预设/自定义/克隆三种音色类型
"""

import json
import os
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict


@dataclass
class VoiceProfile:
    """音色配置"""
    id: str                           # 唯一标识 (A1-A7, B1-B4, C1-Cn)
    name: str                         # 显示名称
    category: str                     # "preset" | "custom" | "clone"
    engine: str                       # "qwen3_custom" | "qwen3_clone"
    description: str = ""             # 描述
    speaker: str = ""                 # CustomVoice speaker 名称
    instruct: str = ""                # CustomVoice instruct 语气控制
    design_instruct: str = ""         # VoiceDesign 自然语言描述
    ref_audio: str = ""               # 克隆参考音频路径
    prompt_cache: str = ""            # voice_clone_prompt 缓存路径
    generated: bool = False           # 是否已生成

    def is_available(self) -> bool:
        """检查音色是否可用"""
        if self.category == "preset":
            return bool(self.speaker)
        elif self.category in ("custom", "clone"):
            return self.generated and bool(self.prompt_cache)
        return False


class VoiceProfileManager:
    """音色配置管理器（单例，线程安全）"""

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self, config_path: str = None):
        """
        初始化管理器

        Args:
            config_path: 配置文件路径，默认使用 config/voice_profiles.json
        """
        # 使用实例锁而非类锁，避免在 __init__ 中使用类锁（可能导致死锁）
        self._profiles_lock = threading.RLock()
        self._config_lock = threading.RLock()

        if config_path:
            self.config_path = Path(config_path)
        else:
            # 默认使用项目 config 目录
            project_root = Path(__file__).parent.parent.parent.parent
            self.config_path = project_root / "config" / "voice_profiles.json"

        self._profiles: Dict[str, VoiceProfile] = {}
        self._load()

    def _load(self):
        """从 JSON 文件加载音色配置（线程安全）"""
        with self._profiles_lock:
            if not self.config_path.exists():
                print(f"[VoiceProfileManager] 配置文件不存在: {self.config_path}")
                return

            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                profiles = data.get("profiles", [])
                for p in profiles:
                    profile = VoiceProfile(**p)
                    self._profiles[profile.id] = profile

                print(f"[VoiceProfileManager] 加载了 {len(self._profiles)} 个音色配置")

            except Exception as e:
                print(f"[VoiceProfileManager] 加载配置文件失败: {e}")

    def save(self):
        """保存配置到 JSON 文件（线程安全）"""
        with self._profiles_lock:
            with self._config_lock:
                data = {
                    "version": 1,
                    "profiles": [asdict(p) for p in self._profiles.values()]
                }

                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[VoiceProfileManager] 保存了 {len(self._profiles)} 个音色配置")

    def get_by_id(self, profile_id: str) -> Optional[VoiceProfile]:
        """根据 ID 获取音色配置（线程安全）"""
        with self._profiles_lock:
            return self._profiles.get(profile_id)

    def get_presets(self) -> List[VoiceProfile]:
        """获取所有预设音色（线程安全）"""
        with self._profiles_lock:
            return [p for p in self._profiles.values() if p.category == "preset"]

    def get_customs(self) -> List[VoiceProfile]:
        """获取所有自定义音色（VoiceDesign 预生成）（线程安全）"""
        with self._profiles_lock:
            return [p for p in self._profiles.values() if p.category == "custom"]

    def get_clones(self) -> List[VoiceProfile]:
        """获取所有克隆音色（用户上传）（线程安全）"""
        with self._profiles_lock:
            return [p for p in self._profiles.values() if p.category == "clone"]

    def update_generated(self, profile_id: str, generated: bool, ref_audio: str = None, prompt_cache: str = None):
        """
        更新音色生成状态（线程安全）

        Args:
            profile_id: 音色 ID
            generated: 是否已生成
            ref_audio: 参考音频路径（可选）
            prompt_cache: prompt 缓存路径（可选）
        """
        with self._profiles_lock:
            profile = self._profiles.get(profile_id)
            if profile:
                profile.generated = generated
                if ref_audio:
                    profile.ref_audio = ref_audio
                if prompt_cache:
                    profile.prompt_cache = prompt_cache
        self.save()

    def add_clone_profile(self, name: str, ref_audio: str, description: str = "") -> str:
        """
        添加用户克隆音色（线程安全）

        Args:
            name: 音色名称
            ref_audio: 参考音频路径
            description: 描述

        Returns:
            新音色 ID
        """
        with self._profiles_lock:
            # 生成新 ID
            clone_ids = [int(p.id[1:]) for p in self._profiles.values() if p.category == "clone"]
            new_id = f"C{max(clone_ids) + 1 if clone_ids else 1}"

            # 音色目录
            project_root = Path(__file__).parent.parent.parent.parent
            voice_dir = project_root / "models" / "voice_profiles"
            voice_dir.mkdir(parents=True, exist_ok=True)

            profile = VoiceProfile(
                id=new_id,
                name=name,
                category="clone",
                engine="qwen3_clone",
                description=description,
                ref_audio=ref_audio,
                prompt_cache=str(voice_dir / f"{new_id}_prompt.pt"),
                generated=False,
            )

            self._profiles[new_id] = profile

        self.save()
        return new_id

    def add_custom_profile(
        self,
        name: str,
        description: str,
        design_instruct: str,
        ref_audio: str = "",
        prompt_cache: str = "",
    ) -> str:
        """
        添加自定义音色（VoiceDesign 生成的音色）（线程安全）

        Args:
            name: 音色名称
            description: 描述
            design_instruct: VoiceDesign 自然语言描述
            ref_audio: 参考音频路径
            prompt_cache: prompt 缓存路径

        Returns:
            新音色 ID (B 系列)
        """
        with self._profiles_lock:
            # 生成新 ID (B 系列)
            custom_ids = [int(p.id[1:]) for p in self._profiles.values()
                         if p.category == "custom"]
            new_id = f"B{max(custom_ids) + 1 if custom_ids else 1}"

            # 音色目录
            project_root = Path(__file__).parent.parent.parent.parent
            voice_dir = project_root / "models" / "voice_profiles"
            voice_dir.mkdir(parents=True, exist_ok=True)

            profile = VoiceProfile(
                id=new_id,
                name=name,
                category="custom",
                engine="qwen3_clone",
                description=description,
                design_instruct=design_instruct,
                ref_audio=ref_audio,
                prompt_cache=prompt_cache,
                generated=bool(prompt_cache),
            )

            self._profiles[new_id] = profile

        self.save()
        return new_id

    def delete_profile(self, profile_id: str) -> bool:
        """
        删除音色配置（线程安全）

        Args:
            profile_id: 音色 ID

        Returns:
            是否删除成功
        """
        with self._profiles_lock:
            if profile_id not in self._profiles:
                return False

            profile = self._profiles[profile_id]

            # 不能删除预设音色
            if profile.category == "preset":
                print(f"[VoiceProfileManager] 不能删除预设音色: {profile_id}")
                return False

            # 删除 prompt 文件（如果存在）
            if profile.prompt_cache:
                prompt_path = Path(profile.prompt_cache)
                if prompt_path.exists():
                    prompt_path.unlink()
                    print(f"[VoiceProfileManager] 已删除 prompt: {prompt_path}")

            # 删除参考音频（如果是 custom 类型自己生成的）
            if profile.ref_audio and profile.category == "custom":
                ref_path = Path(profile.ref_audio)
                if ref_path.exists() and "_ref.wav" in profile.ref_audio:
                    ref_path.unlink()
                    print(f"[VoiceProfileManager] 已删除参考音频: {ref_path}")

            # 从字典移除
            del self._profiles[profile_id]

        self.save()
        print(f"[VoiceProfileManager] 已删除音色: {profile_id}")
        return True

    def get_all(self) -> List[VoiceProfile]:
        """获取所有音色（线程安全）"""
        with self._profiles_lock:
            return list(self._profiles.values())


def get_voice_manager() -> VoiceProfileManager:
    """获取音色管理器单例（线程安全双重检查锁定）"""
    if VoiceProfileManager._instance is None:
        with VoiceProfileManager._instance_lock:
            if VoiceProfileManager._instance is None:
                VoiceProfileManager._instance = VoiceProfileManager()
    return VoiceProfileManager._instance
