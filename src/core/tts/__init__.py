"""
TTS 语音合成模块 - 支持 Edge-TTS / Qwen3-TTS

功能：将文本转换为语音
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, Literal, List

import edge_tts
import soundfile as sf
import numpy as np


class EdgeTTSEngine:
    """Edge-TTS 引擎"""

    # 预设音色
    VOICES = {
        "zh-CN-XiaoxiaoNeural": "晓晓（女）",
        "zh-CN-YunxiNeural": "云希（男）",
        "zh-CN-YunyangNeural": "云扬（男）",
        "zh-CN-XiaoyiNeural": "小艺（女）",
        "ja-JP-NanamiNeural": "七海（日语女）",
        "ja-JP-KeitaNeural": "惠太（日语男）",
        "en-US-JennyNeural": "Jenny（英语女）",
    }

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ):
        """
        初始化 Edge-TTS 引擎

        Args:
            voice: 音色名称
            rate: 语速 (+/-%)
            volume: 音量 (+/-%)
            pitch: 音调 (+/-Hz)
        """
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch

        print(f"[EdgeTTS] 音色: {voice} ({self.VOICES.get(voice, 'unknown')})")

    async def synthesize_async(self, text: str, output_path: str) -> str:
        """
        异步合成语音

        Args:
            text: 待合成文本
            output_path: 输出文件路径

        Returns:
            str: 输出文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )

        await communicate.save(str(output_path))

        return str(output_path)

    def synthesize(self, text: str, output_path: str) -> str:
        """同步合成语音"""
        return asyncio.run(self.synthesize_async(text, output_path))

    async def _synthesize_all_async(self, sentences: List[str], temp_files: List[Path]):
        """并发合成所有句子（避免多次 asyncio.run 创建新事件循环）"""
        tasks = [
            self.synthesize_async(sent, str(tf))
            for sent, tf in zip(sentences, temp_files)
            if sent.strip()
        ]
        await asyncio.gather(*tasks)

    def synthesize_long_text(self, text: str, output_path: str) -> str:
        """合成长文本（分段处理）"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 按句子分割
        sentences = self._split_sentences(text)
        sentences = [s for s in sentences if s.strip()]

        if not sentences:
            return str(output_path)

        # 生成临时文件列表
        temp_files = [output_path.parent / f"temp_tts_{i}.mp3" for i in range(len(sentences))]

        # 用单个事件循环并发合成所有句子
        asyncio.run(self._synthesize_all_async(sentences, temp_files))

        # 合并音频
        existing = [f for f in temp_files if f.exists()]
        self._merge_audio(existing, output_path)

        # 清理临时文件
        for f in temp_files:
            f.unlink(missing_ok=True)

        return str(output_path)

    def _split_sentences(self, text: str, max_length: int = 500) -> List[str]:
        """按句子分割文本"""
        import re

        # 简单按句号、问号、感叹号分割
        sentences = re.split(r"([。！？])", text)
        result = []
        current = ""

        for i in range(0, len(sentences) - 1, 2):
            sent = sentences[i] + sentences[i + 1]
            if len(current) + len(sent) <= max_length:
                current += sent
            else:
                if current:
                    result.append(current)
                current = sent

        if current:
            result.append(current)

        return result

    def _merge_audio(self, input_files: List[Path], output_path: Path):
        """合并多个音频文件"""
        from ..utils import get_ffmpeg

        if not input_files:
            return

        # 使用 ffmpeg 合并
        import subprocess

        concat_file = output_path.parent / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for fpath in input_files:
                f.write(f"file '{fpath}'\n")

        cmd = [
            get_ffmpeg(),
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
            "-y",
        ]

        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        concat_file.unlink(missing_ok=True)


class Qwen3TTSEngine:
    """Qwen3-TTS 引擎（支持预设音色 + 自定义音色 + 克隆音色）"""

    # 预设音色（兼容旧 API）
    VOICES = [
        "Vivian",
        "Serena",
        "Uncle_Fu",
        "Dylan",
        "Eric",
        "Ryan",
        "Aiden",
        "Ono_Anna",
        "Sohee",
    ]

    # 音色说明
    VOICE_DESC = {
        "Vivian": "Vivian（女声，甜美）",
        "Serena": "Serena（女声，清亮）",
        "Uncle_Fu": "Uncle_Fu（男声，成熟）",
        "Dylan": "Dylan（男声，年轻）",
        "Eric": "Eric（男声，沉稳）",
        "Ryan": "Ryan（男声，温和）",
        "Aiden": "Aiden（男声，自然）",
        "Ono_Anna": "Ono_Anna（日语女声）",
        "Sohee": "Sohee（女声，柔和）",
    }

    def __init__(
        self,
        voice: str = "Vivian",
        speed: float = 1.0,
        voice_profile_id: str = None,
    ):
        """
        初始化 Qwen3-TTS 引擎

        Args:
            voice: 音色名称（兼容旧 API）
            speed: 语速 (0.5-2.0, 1.0=正常)
            voice_profile_id: 音色配置 ID（优先级高于 voice）
        """
        self.voice = voice
        self.speed = max(0.5, min(2.0, speed))
        self.voice_profile_id = voice_profile_id
        self.profile = None
        self.instruct = ""
        self.prompt_cache = None

        # 尝试加载音色配置
        if voice_profile_id:
            try:
                from .voice_profile import get_voice_manager
                manager = get_voice_manager()
                self.profile = manager.get_by_id(voice_profile_id)
                if self.profile:
                    if self.profile.category == "preset":
                        self.voice = self.profile.speaker
                        self.instruct = self.profile.instruct
                    elif self.profile.category in ("custom", "clone"):
                        self.prompt_cache = self.profile.prompt_cache
            except Exception as e:
                print(f"[Qwen3TTS] 加载音色配置失败: {e}")

        # 检查是否安装
        try:
            import qwen_tts
        except ImportError:
            raise ImportError("请先安装 qwen-tts: pip install qwen-tts")

        desc = self.VOICE_DESC.get(self.voice, '')
        if self.profile and self.profile.category in ("custom", "clone"):
            status = "已生成" if self.profile.generated else "未生成"
            print(f"[Qwen3TTS] 音色: {self.profile.name} (prompt_cache: {status})")
        else:
            print(f"[Qwen3TTS] 音色: {self.voice} ({desc}), instruct: '{self.instruct}', 速度: {speed:.1f}x")

    @classmethod
    def _get_custom_model(cls):
        """获取 CustomVoice 模型"""
        from .qwen3_manager import Qwen3ModelManager
        return Qwen3ModelManager.get_custom_voice_model()

    @classmethod
    def _get_base_model(cls):
        """获取 Base 模型（用于克隆）"""
        from .qwen3_manager import Qwen3ModelManager
        return Qwen3ModelManager.get_base_model()

    @classmethod
    def unload_model(cls):
        """手动卸载模型"""
        from .qwen3_manager import Qwen3ModelManager
        Qwen3ModelManager.unload_all()
        print("[Qwen3TTS] 模型已卸载")

    def _synthesize_custom_voice(self, text: str, output_path: Path):
        """使用 CustomVoice 预设音色合成（qwen_tts 0.1.1 API）"""
        model = self._get_custom_model()
        wavs, sr = model.generate_custom_voice(
            text,
            speaker=self.voice,
            language="chinese",
            instruct=self.instruct or None,
        )
        # wavs 是 List[np.ndarray]，取第一个
        import numpy as np
        if wavs and len(wavs) > 0:
            audio = wavs[0].astype(np.float32)
            sf.write(str(output_path), audio, sr)
        else:
            raise RuntimeError("Qwen3-TTS 返回空音频")

    def _synthesize_from_cache(self, text: str, output_path: Path):
        """使用 prompt_cache 合成（自定义/克隆音色，qwen_tts 0.1.1 API）"""
        import torch

        # 检查 prompt_cache 是否存在
        if not self.prompt_cache or not Path(self.prompt_cache).exists():
            raise FileNotFoundError(f"prompt_cache 不存在: {self.prompt_cache}")

        # 加载 prompt_cache
        prompt_cache = torch.load(self.prompt_cache, map_location="cpu")
        prompt_cache["thinks"] = prompt_cache.get("thinks", "")

        # 使用 Base 模型合成（voice_clone）
        model = self._get_base_model()
        wavs, sr = model.generate_voice_clone(
            text,
            language="chinese",
            voice_clone_prompt=prompt_cache,
        )
        import numpy as np
        if wavs and len(wavs) > 0:
            audio = wavs[0].astype(np.float32)
            sf.write(str(output_path), audio, sr)
        else:
            raise RuntimeError("Qwen3-TTS 返回空音频")

    def synthesize(self, text: str, output_path: str) -> str:
        """
        合成语音（根据音色类型选择不同方法）

        Args:
            text: 待合成文本
            output_path: 输出文件路径

        Returns:
            str: 输出文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        t0 = time.time()

        # 根据音色类型选择合成方法
        if self.profile and self.profile.category in ("custom", "clone"):
            if not self.profile.generated:
                raise ValueError(f"音色 {self.profile.name} 尚未生成，请先运行预生成脚本")
            self._synthesize_from_cache(text, output_path)
            print(f"[Qwen3TTS] 自定义音色合成完成，耗时: {time.time()-t0:.1f}s")
        else:
            self._synthesize_custom_voice(text, output_path)
            print(f"[Qwen3TTS] 预设音色合成完成，耗时: {time.time()-t0:.1f}s")

        return str(output_path)


class TTSEngine:
    """
    TTS 引擎（统一接口，支持注册式工厂模式）

    使用方法:
        # 注册新引擎
        TTSEngine.register("cosyvoice", CosyVoiceEngine)

        # 列出可用引擎
        print(TTSEngine.available_engines())  # ["edge", "qwen3", "gptsovits"]

        # 创建引擎
        tts = TTSEngine(engine="edge", voice="zh-CN-XiaoxiaoNeural")
    """

    # 引擎注册表
    _registry: dict = {}
    # 注册的引擎类
    _engine_classes: dict = {}

    @classmethod
    def register(cls, name: str, engine_class, **kwargs):
        """
        注册新 TTS 引擎（开闭原则：新引擎无需修改此类）

        Args:
            name: 引擎名称
            engine_class: 引擎类（必须实现 synthesize 方法）
            **kwargs: 引擎默认参数
        """
        cls._registry[name] = kwargs
        cls._engine_classes[name] = engine_class
        print(f"[TTSEngine] 注册引擎: {name}")

    @classmethod
    def available_engines(cls) -> list:
        """获取可用引擎列表"""
        return list(cls._registry.keys())

    @classmethod
    def get_engine_class(cls, name: str):
        """获取引擎类"""
        if name not in cls._engine_classes:
            raise ValueError(f"未知引擎: {name}，可用: {cls.available_engines()}")
        return cls._engine_classes[name]

    def __init__(
        self,
        engine: Literal["edge", "qwen3", "gptsovits"] = "edge",
        voice: str = "zh-CN-XiaoxiaoNeural",
        speed: float = 1.0,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
        voice_profile_id: str = None,
        # GPT-SoVITS 专用参数
        gptsovits_api_url: str = "http://localhost:9870",
        gptsovits_ref_audio: str = "",
        gptsovits_ref_text: str = "",
        gptsovits_language: str = "zh",
    ):
        """
        初始化 TTS 引擎（使用注册式工厂）

        Args:
            engine: 引擎类型 (edge/qwen3/gptsovits)
            voice: 音色名称
            speed: 语速 (0.5-2.0，仅 Qwen3)
            rate: 语速 (仅 Edge-TTS, +/-%)
            volume: 音量 (仅 Edge-TTS, +/-%)
            pitch: 音调 (仅 Edge-TTS, +/-Hz)
            voice_profile_id: 音色配置 ID（Qwen3 专用）
            gptsovits_api_url: GPT-SoVITS 服务地址
            gptsovits_ref_audio: GPT-SoVITS 参考音频路径
            gptsovits_ref_text: GPT-SoVITS 参考文本
            gptsovits_language: GPT-SoVITS 合成语言
        """
        self.engine_type = engine

        if engine == "edge":
            self.engine = EdgeTTSEngine(
                voice=voice,
                rate=rate,
                volume=volume,
                pitch=pitch,
            )
        elif engine == "qwen3":
            self.engine = Qwen3TTSEngine(
                voice=voice,
                speed=speed,
                voice_profile_id=voice_profile_id,
            )
        elif engine == "gptsovits":
            from .gptsovits import GPTSoVITSEngine
            self.engine = GPTSoVITSEngine(
                api_url=gptsovits_api_url,
                ref_audio_path=gptsovits_ref_audio,
                ref_text=gptsovits_ref_text,
                language=gptsovits_language,
            )
        else:
            raise ValueError(f"不支持的引擎: {engine}，可用: edge/qwen3/gptsovits")

    def synthesize(self, text: str, output_path: str) -> str:
        """合成语音"""
        return self.engine.synthesize(text, output_path)

    def synthesize_long_text(self, text: str, output_path: str) -> str:
        """合成长文本"""
        if hasattr(self.engine, "synthesize_long_text"):
            return self.engine.synthesize_long_text(text, output_path)
        return self.engine.synthesize(text, output_path)

    @property
    def is_available(self) -> bool:
        """检查引擎是否可用"""
        if self.engine_type == "gptsovits":
            return self.engine.is_service_available()
        return True  # edge/qwen3 本地可用


# 注册内置引擎（模块加载时自动注册）
TTSEngine.register("edge", EdgeTTSEngine)
TTSEngine.register("qwen3", Qwen3TTSEngine)
TTSEngine.register("gptsovits", GPTSoVITSEngine)


# 便捷函数
def synthesize_speech(
    text: str,
    output_path: str,
    engine: str = "edge",
    voice: str = "zh-CN-XiaoxiaoNeural",
) -> str:
    """快速合成语音"""
    tts = TTSEngine(engine=engine, voice=voice)
    return tts.synthesize(text, output_path)
