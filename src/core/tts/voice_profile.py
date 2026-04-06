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

from src.config import PROJECT_ROOT  # 统一使用项目根目录


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
    ref_audio: str = ""               # 克隆参考音频路径（支持相对路径 ${PROJECT_ROOT}）
    prompt_cache: str = ""            # voice_clone_prompt 缓存路径（支持相对路径 ${PROJECT_ROOT}）
    generated: bool = False           # 是否已生成

    def _resolve_path(self, path: str) -> str:
        """
        解析路径，支持 ${PROJECT_ROOT} 占位符

        Args:
            path: 原始路径（可能包含 ${PROJECT_ROOT}）

        Returns:
            str: 解析后的绝对路径
        """
        if not path:
            return path

        # 支持 ${PROJECT_ROOT} 占位符
        if path.startswith("${PROJECT_ROOT}"):
            return str(PROJECT_ROOT) + path[len("${PROJECT_ROOT}"):]

        # 如果已经是绝对路径，保持不变（兼容旧数据）
        if Path(path).is_absolute():
            return path

        # 相对路径，基于项目根目录解析
        return str(PROJECT_ROOT / path)

    def _make_relative_path(self, path: str) -> str:
        """
        将绝对路径转换为相对路径（使用 ${PROJECT_ROOT} 占位符）

        Args:
            path: 绝对路径

        Returns:
            str: 相对路径（含 ${PROJECT_ROOT}）
        """
        if not path:
            return path

        try:
            path_obj = Path(path).resolve()
            project_root = PROJECT_ROOT.resolve()

            # 检查是否是项目内的路径
            if path_obj.is_relative_to(project_root):
                relative = path_obj.relative_to(project_root)
                return f"${{PROJECT_ROOT}}/{relative.as_posix()}"
        except (ValueError, TypeError):
            pass

        # 无法相对化，保持原样
        return path

    def get_ref_audio_path(self) -> str:
        """获取解析后的参考音频路径"""
        return self._resolve_path(self.ref_audio)

    def get_prompt_cache_path(self) -> str:
        """获取解析后的 prompt 缓存路径"""
        return self._resolve_path(self.prompt_cache)

    def set_ref_audio_path(self, path: str):
        """设置参考音频路径（自动转换为相对路径）"""
        self.ref_audio = self._make_relative_path(path)

    def set_prompt_cache_path(self, path: str):
        """设置 prompt 缓存路径（自动转换为相对路径）"""
        self.prompt_cache = self._make_relative_path(path)

    def is_available(self) -> bool:
        """检查音色是否可用"""
        if self.category == "preset":
            return bool(self.speaker)
        elif self.category in ("custom", "clone"):
            # 检查解析后的路径是否存在
            prompt_path = self.get_prompt_cache_path()
            return self.generated and bool(prompt_path) and Path(prompt_path).exists()
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
            # 统一使用 PROJECT_ROOT
            self.config_path = PROJECT_ROOT / "config" / "voice_profiles.json"

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
            ref_audio: 参考音频路径（可选，自动转换为相对路径）
            prompt_cache: prompt 缓存路径（可选，自动转换为相对路径）
        """
        with self._profiles_lock:
            profile = self._profiles.get(profile_id)
            if profile:
                profile.generated = generated
                if ref_audio:
                    profile.set_ref_audio_path(ref_audio)
                if prompt_cache:
                    profile.set_prompt_cache_path(prompt_cache)
            # 在同一锁内保存，避免竞态条件
            self.save()

    def add_clone_profile(self, name: str, ref_audio: str, description: str = "") -> str:
        """
        添加用户克隆音色（线程安全）

        Args:
            name: 音色名称
            ref_audio: 参考音频路径（自动转换为相对路径）
            description: 描述

        Returns:
            新音色 ID
        """
        with self._profiles_lock:
            # 生成新 ID
            clone_ids = [int(p.id[1:]) for p in self._profiles.values() if p.category == "clone"]
            next_num = max(clone_ids) + 1 if clone_ids else 1
            new_id = f"C{next_num}"

            # 音色目录（统一使用 PROJECT_ROOT）
            voice_dir = PROJECT_ROOT / "models" / "voice_profiles"
            voice_dir.mkdir(parents=True, exist_ok=True)

            profile = VoiceProfile(
                id=new_id,
                name=name,
                category="clone",
                engine="qwen3_clone",
                description=description,
                ref_audio="",  # 稍后设置
                prompt_cache="",  # 稍后设置
                generated=False,
            )

            # 使用相对路径设置
            profile.set_ref_audio_path(ref_audio)
            profile.set_prompt_cache_path(str(voice_dir / f"{new_id}_prompt.pt"))

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
            ref_audio: 参考音频路径（自动转换为相对路径）
            prompt_cache: prompt 缓存路径（自动转换为相对路径）

        Returns:
            新音色 ID (B 系列)
        """
        with self._profiles_lock:
            # 生成新 ID (B 系列)
            custom_ids = [int(p.id[1:]) for p in self._profiles.values()
                         if p.category == "custom"]
            new_id = f"B{max(custom_ids) + 1 if custom_ids else 1}"

            # 音色目录（统一使用 PROJECT_ROOT）
            voice_dir = PROJECT_ROOT / "models" / "voice_profiles"
            voice_dir.mkdir(parents=True, exist_ok=True)

            profile = VoiceProfile(
                id=new_id,
                name=name,
                category="custom",
                engine="qwen3_clone",
                description=description,
                design_instruct=design_instruct,
                ref_audio="",  # 稍后设置
                prompt_cache="",  # 稍后设置
                generated=bool(prompt_cache),
            )

            # 使用相对路径设置
            if ref_audio:
                profile.set_ref_audio_path(ref_audio)
            if prompt_cache:
                profile.set_prompt_cache_path(prompt_cache)

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
            prompt_path_str = profile.get_prompt_cache_path()
            if prompt_path_str:
                prompt_path = Path(prompt_path_str)
                if prompt_path.exists():
                    prompt_path.unlink()
                    print(f"[VoiceProfileManager] 已删除 prompt: {prompt_path}")

            # 删除参考音频（如果是 custom 类型自己生成的）
            ref_path_str = profile.get_ref_audio_path()
            if ref_path_str and profile.category == "custom":
                ref_path = Path(ref_path_str)
                if ref_path.exists() and "_ref.wav" in str(ref_path):
                    ref_path.unlink()
                    print(f"[VoiceProfileManager] 已删除参考音频: {ref_path}")

            # 从字典移除
            del self._profiles[profile_id]

        self.save()
        print(f"[VoiceProfileManager] 已删除音色: {profile_id}")
        return True

    def get_all(self) -> List[VoiceProfile]:
        """获取所有音色（线程安全，返回浅拷贝列表）"""
        with self._profiles_lock:
            return list(self._profiles.values())

    def add_profile(self, profile: "VoiceProfile"):
        """
        添加音色到管理器（线程安全）

        Args:
            profile: VoiceProfile 实例
        """
        with self._profiles_lock:
            self._profiles[profile.id] = profile
        self.save()
        print(f"[VoiceProfileManager] 已添加音色: {profile.name} ({profile.id})")


def get_voice_manager() -> VoiceProfileManager:
    """获取音色管理器单例（线程安全双重检查锁定）"""
    if VoiceProfileManager._instance is None:
        with VoiceProfileManager._instance_lock:
            if VoiceProfileManager._instance is None:
                VoiceProfileManager._instance = VoiceProfileManager()
    return VoiceProfileManager._instance
