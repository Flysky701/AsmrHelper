"""
TTS 语音合成模块 - 支持 Edge-TTS / Qwen3-TTS

功能：将文本转换为语音
"""

import asyncio
import re

import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Literal, List

import edge_tts
import soundfile as sf


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)
import numpy as np

from src.utils import get_ffmpeg, ensure_dir


def _clean_text_for_tts(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = cleaned.replace('\u200b', '')
    cleaned = cleaned.replace('\ufeff', '')
    cleaned = cleaned.strip('。？！，、；：""''「」『』【】()（）…—·')
    if not cleaned or re.match(r'^[\s。？！，、；：""''「」『』【】()（）…—·]*$', cleaned):
        return ""
    return cleaned


def _apply_fade(audio: np.ndarray, sample_rate: int, fade_in_ms: int = 30, fade_out_ms: int = 50) -> np.ndarray:
    audio = audio.copy()
    fade_in_samples = int(fade_in_ms * sample_rate / 1000)
    fade_out_samples = int(fade_out_ms * sample_rate / 1000)
    if fade_in_samples > 0 and len(audio) > fade_in_samples:
        audio[:fade_in_samples] *= np.linspace(0, 1, fade_in_samples)
    if fade_out_samples > 0 and len(audio) > fade_out_samples:
        audio[-fade_out_samples:] *= np.linspace(1, 0, fade_out_samples)
    return audio


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
            output_path: 输出文件路径（必须是 .wav 格式）

        Returns:
            str: 输出文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Edge-TTS 默认输出 MP3（有损），先用临时文件存储再转为 WAV
        temp_mp3 = output_path.with_suffix(".mp3")

        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )

        await communicate.save(str(temp_mp3))

        # 转换为 WAV 无损格式（强制 WAV 输出）
        try:
            self._convert_to_wav(temp_mp3, output_path)
        finally:
            # 确保清理临时 mp3 文件（无论转换成功与否）
            temp_mp3.unlink(missing_ok=True)

        return str(output_path)

    def _convert_to_wav(self, input_path: Path, output_path: Path):
        """将音频转换为 WAV 无损格式"""
        ffmpeg_path = get_ffmpeg()
        cmd = [
            ffmpeg_path,
            "-i", str(input_path),
            "-acodec", "pcm_f32le",  # 32-bit float WAV
            "-ar", "44100",
            "-ac", "2",
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

    def synthesize(self, text: str, output_path: str) -> str:
        """同步合成语音"""
        return _run_async(self.synthesize_async(text, output_path))

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

        # 生成临时文件列表（WAV 格式避免有损压缩）
        temp_files = [output_path.parent / f"temp_tts_{i}.wav" for i in range(len(sentences))]

        # 用单个事件循环并发合成所有句子
        _run_async(self._synthesize_all_async(sentences, temp_files))

        # 合并音频
        existing = [f for f in temp_files if f.exists()]
        self._merge_audio(existing, output_path)

        # 清理临时文件
        for f in temp_files:
            f.unlink(missing_ok=True)

        return str(output_path)

    def _split_sentences(self, text: str, max_length: int = 500) -> List[str]:
        """按句子分割文本"""
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

        if len(sentences) % 2 == 1 and sentences[-1].strip():
            if len(current) + len(sentences[-1]) <= max_length:
                current += sentences[-1]
            else:
                if current:
                    result.append(current)
                current = sentences[-1]

        if current:
            result.append(current)

        return result

    def _merge_audio(self, input_files: List[Path], output_path: Path):
        """合并多个音频文件"""
        if not input_files:
            return

        # 使用 ffmpeg 合并
        concat_file = output_path.parent / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for fpath in input_files:
                escaped = str(fpath).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

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

    @staticmethod
    def speed_instruct(tts_duration: float, target_duration: float) -> str:
        if target_duration <= 0:
            return ""
        ratio = tts_duration / target_duration
        if ratio <= 1.2:
            return ""
        elif ratio <= 1.5:
            return "语速稍快"
        elif ratio <= 2.0:
            return "语速加快"
        elif ratio <= 3.0:
            return "用比较快的语速说"
        else:
            return "用非常快的语速说"

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
                  注：qwen_tts 0.1.1 不支持 speed 参数，此字段保留供未来版本使用。
                  当前通过 mixer 的时域压缩/拉伸来对齐时长。
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

    def _synthesize_from_cache(self, text: str, output_path: str) -> str:
        """使用 prompt_cache 合成（自定义/克隆音色，qwen_tts 0.1.1 API）"""
        import torch

        # 检查 prompt_cache 是否存在
        if not self.prompt_cache or not Path(self.prompt_cache).exists():
            raise FileNotFoundError(f"prompt_cache 不存在: {self.prompt_cache}")

        # 加载 prompt_cache (PyTorch 2.6+ 需要 weights_only=False)
        # prompt_cache 是 list[VoiceClonePromptItem]，直接传给 generate_voice_clone
        prompt_cache = torch.load(self.prompt_cache, map_location="cpu", weights_only=False)

        # 使用 Base 模型合成（voice_clone）
        model = self._get_base_model()
        
        print(f"[Qwen3TTS] 使用 prompt_cache 合成，文本长度: {len(text)}")
        
        # 使用 torch.no_grad() 禁用梯度计算，提高推理速度并减少显存占用
        with torch.no_grad():
            wavs, sr = model.generate_voice_clone(
                text,
                language="chinese",
                voice_clone_prompt=prompt_cache,
            )
        if wavs and len(wavs) > 0:
            audio = wavs[0].astype(np.float32)
            duration = len(audio) / sr
            print(f"[Qwen3TTS] 生成音频时长: {duration:.1f}s")
            # 使用 FLOAT subtype 避免量化失真
            sf.write(str(output_path), audio, sr, subtype="FLOAT")
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
        return self._synthesize(text, output_path, instruct=self.instruct or None)

    def synthesize_with_instruct(self, text: str, output_path: str, instruct: str) -> str:
        """
        使用自定义 instruct 提示词合成语音

        用于 mixer 时域压缩场景：通过 instruct 控制语速来缩短时长，而非后处理压缩。

        Args:
            text: 待合成文本
            output_path: 输出文件路径
            instruct: 自然语言提示词，如 "语速加快"、"用稍快的语速说"

        Returns:
            str: 输出文件路径
        """
        return self._synthesize(text, output_path, instruct=instruct)

    def _synthesize(self, text: str, output_path: str, instruct: str = None) -> str:
        """内部合成方法，支持自定义 instruct"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        t0 = time.time()

        # 根据音色类型选择合成方法
        if self.profile and self.profile.category in ("custom", "clone"):
            if not self.profile.generated:
                raise ValueError(f"音色 {self.profile.name} 尚未生成，请先运行预生成脚本")
            # 克隆音色：instruct 不支持（API 不接受），回退到后处理
            self._synthesize_from_cache(text, output_path)
            print(f"[Qwen3TTS] 自定义音色合成完成，耗时: {time.time()-t0:.1f}s")
        else:
            # 预设音色：支持 instruct 参数
            model = self._get_custom_model()
            import torch
            
            # 使用 torch.no_grad() 禁用梯度计算，提高推理速度并减少显存占用
            with torch.no_grad():
                wavs, sr = model.generate_custom_voice(
                    text,
                    speaker=self.voice,
                    language="chinese",
                    instruct=instruct,
                )
            if wavs and len(wavs) > 0:
                audio = wavs[0].astype(np.float32)
                sf.write(str(output_path), audio, sr, subtype="FLOAT")
            else:
                raise RuntimeError("Qwen3-TTS 返回空音频")
            print(f"[Qwen3TTS] 预设音色合成完成(instruct: {instruct!r})，耗时: {time.time()-t0:.1f}s")

        return str(output_path)


class TTSEngine:
    """
    TTS 引擎（统一接口，支持注册式工厂模式）

    使用方法:
        # 注册新引擎
        TTSEngine.register("cosyvoice", CosyVoiceEngine)

        # 列出可用引擎
        print(TTSEngine.available_engines())  # ["edge", "qwen3"]

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
        engine: Literal["edge", "qwen3"] = "edge",
        voice: str = "zh-CN-XiaoxiaoNeural",
        speed: float = 1.0,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
        voice_profile_id: str = None,
    ):
        """
        初始化 TTS 引擎（使用注册式工厂）

        Args:
            engine: 引擎类型 (edge/qwen3)
            voice: 音色名称
            speed: 语速 (0.5-2.0，仅 Qwen3)
            rate: 语速 (仅 Edge-TTS, +/-%)
            volume: 音量 (仅 Edge-TTS, +/-%)
            pitch: 音调 (仅 Edge-TTS, +/-Hz)
            voice_profile_id: 音色配置 ID（Qwen3 专用）
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
        else:
            raise ValueError(f"不支持的引擎: {engine}，可用: edge/qwen3")

    def synthesize(self, text: str, output_path: str) -> str:
        """合成语音"""
        return self.engine.synthesize(text, output_path)

    def synthesize_long_text(self, text: str, output_path: str) -> str:
        """合成长文本"""
        if hasattr(self.engine, "synthesize_long_text"):
            return self.engine.synthesize_long_text(text, output_path)
        return self.engine.synthesize(text, output_path)

    def synthesize_segments(
        self,
        segments: list,
        output_dir: str,
        output_path: str,
        reference_duration: float = 0,
        sample_rate: int = 44100,
        max_tts_ratio: float = 1.2,
        compress_ratio: float = 0.75,
        fade_in_ms: int = 30,
        fade_out_ms: int = 50,
    ) -> str:
        """
        逐句合成 TTS 并按时间戳拼装到时间轴上

        核心逻辑：
        1. 对每句翻译单独合成 TTS（带重试）
        2. 按原音时间戳将 TTS 放置到正确位置
        3. TTS 超过原音频时长时的压缩策略取决于引擎类型：
           - Edge-TTS: 使用 pytsmod.ola() 时域压缩（后处理）
           - Qwen3-TTS: 使用自然语言提示词（如"语速加快"）重新合成
        4. 应用淡入淡出
        5. 归一化并保存

        Args:
            segments: 片段列表，每个包含 text, start_time, end_time
            output_dir: 输出目录（用于临时文件）
            output_path: 最终输出文件路径
            reference_duration: 参考音频总时长（秒），0 则自动计算
            sample_rate: 目标采样率
            max_tts_ratio: TTS 超过原音频此时长的比例阈值（超过则压缩）
            compress_ratio: 固定压缩 stretch_factor（仅 Edge-TTS OLA 使用）
            fade_in_ms: 淡入时长（毫秒）
            fade_out_ms: 淡出时长（毫秒）

        Returns:
            str: 输出文件路径
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = Path(output_path)

        if not segments:
            sf.write(str(output_path), np.zeros((1024, 2), dtype=np.float32), sample_rate, subtype="FLOAT")
            return str(output_path)

        temp_dir = output_dir / "tts_temp"
        temp_dir.mkdir(exist_ok=True)

        is_qwen3 = isinstance(self.engine, Qwen3TTSEngine)
        is_edge = isinstance(self.engine, EdgeTTSEngine)
        engine_type = "qwen3" if is_qwen3 else "edge"
        print(f"[TTS] 逐句合成 ({len(segments)} 句), 引擎: {engine_type}")

        synthesized_count = 0
        failed_count = 0
        total_segments = len(segments)

        valid_indices = []
        valid_texts = []
        valid_temp_files = []
        seg_meta = {}

        for i, seg in enumerate(segments):
            translation = seg.get("text", "").strip()
            if not translation:
                continue
            original_text = translation
            translation = _clean_text_for_tts(translation)
            if not translation.strip():
                continue
            temp_tts = temp_dir / f"tts_{i:04d}.wav"
            valid_indices.append(i)
            valid_texts.append(translation)
            valid_temp_files.append(temp_tts)
            seg_meta[i] = {
                "original_text": original_text,
                "start_sec": seg.get("start_time", 0),
                "end_sec": seg.get("end_time", seg.get("start_time", 0) + 5.0),
            }

        if is_edge and valid_texts:
            print(f"  [EdgeTTS] 并发合成 {len(valid_texts)} 句...")
            t_syn = time.time()
            _run_async(self.engine._synthesize_all_async(valid_texts, valid_temp_files))
            print(f"  [EdgeTTS] 并发合成完成，耗时: {time.time()-t_syn:.1f}s")
        else:
            for idx, (text, temp_file) in enumerate(zip(valid_texts, valid_temp_files)):
                i = valid_indices[idx]
                success = False
                last_error = None
                for retry in range(3):
                    try:
                        self.engine.synthesize(text, str(temp_file))
                        if temp_file.exists() and temp_file.stat().st_size > 0:
                            success = True
                            break
                    except Exception as e:
                        last_error = e
                        if retry < 2:
                            print(f"  [DEBUG] 第 {i+1} 句重试 {retry+1}: {str(e)[:80]}")
                            time.sleep(0.5)
                if not success:
                    failed_count += 1
                    meta = seg_meta[i]
                    display_text = (meta["original_text"][:50] + "...") if len(meta["original_text"]) > 50 else meta["original_text"]
                    print(f"  [WARN] 第 {i+1} 句 TTS 失败: {last_error}")
                    print(f"         原文: {display_text!r}")

        timeline_samples = int(reference_duration * sample_rate) if reference_duration > 0 else 0
        timeline = np.zeros(timeline_samples, dtype=np.float32) if timeline_samples > 0 else None

        for idx, (i, temp_tts) in enumerate(zip(valid_indices, valid_temp_files)):
            if (idx + 1) % 10 == 0 or idx == 0:
                print(f"  [进度] 后处理中... {idx+1}/{len(valid_indices)} 句")

            meta = seg_meta[i]
            start_sec = meta["start_sec"]
            end_sec = meta["end_sec"]
            original_duration = end_sec - start_sec

            if not temp_tts.exists() or temp_tts.stat().st_size == 0:
                failed_count += 1
                continue

            try:
                tts_data, tts_sr = sf.read(str(temp_tts))
            except Exception as e:
                print(f"  [WARN] 第 {i+1} 句读取失败: {e}")
                continue

            if tts_sr != sample_rate:
                try:
                    import librosa
                    tts_data = librosa.resample(tts_data, orig_sr=tts_sr, target_sr=sample_rate)
                except ImportError:
                    _temp_wav = output_dir / f"_resample_temp_{i}.wav"
                    _temp_48k = _temp_wav.with_suffix(".48k.wav")
                    try:
                        sf.write(str(_temp_wav), tts_data, tts_sr, subtype="FLOAT")
                        subprocess.run(
                            [get_ffmpeg(), "-i", str(_temp_wav), "-ar", str(sample_rate), "-ac", "2", str(_temp_48k)],
                            capture_output=True, check=True,
                        )
                        tts_data, tts_sr = sf.read(str(_temp_48k))
                    finally:
                        _temp_wav.unlink(missing_ok=True)
                        _temp_48k.unlink(missing_ok=True)

            if tts_data.ndim > 1:
                tts_data = np.mean(tts_data, axis=1)

            tts_duration = len(tts_data) / sample_rate

            if tts_duration > original_duration * max_tts_ratio:
                if is_qwen3:
                    original_tts_duration = tts_duration
                    instruct = Qwen3TTSEngine.speed_instruct(tts_duration, original_duration)
                    if instruct and hasattr(self.engine, 'synthesize_with_instruct'):
                        try:
                            temp_tts_fast = temp_dir / f"tts_{i:04d}_fast.wav"
                            self.engine.synthesize_with_instruct(translation, str(temp_tts_fast), instruct=instruct)
                            if temp_tts_fast.exists() and temp_tts_fast.stat().st_size > 0:
                                tts_data_new, tts_sr_new = sf.read(str(temp_tts_fast))
                                if tts_sr_new != sample_rate:
                                    try:
                                        import librosa
                                        tts_data_new = librosa.resample(tts_data_new, orig_sr=tts_sr_new, target_sr=sample_rate)
                                    except ImportError:
                                        pass
                                if tts_data_new.ndim > 1:
                                    tts_data_new = np.mean(tts_data_new, axis=1)
                                tts_duration_new = len(tts_data_new) / sample_rate
                                if tts_duration_new < original_tts_duration:
                                    tts_data = tts_data_new
                                    tts_duration = tts_duration_new
                                    print(f"  [{i+1}] Qwen3 instruct 重合成: {original_tts_duration:.1f}s -> {tts_duration:.1f}s (instruct: {instruct!r})")
                                else:
                                    print(f"  [{i+1}] Qwen3 instruct 未缩短 ({tts_duration_new:.1f}s >= {original_tts_duration:.1f}s)，保留原始")
                                temp_tts_fast.unlink(missing_ok=True)
                            else:
                                print(f"  [{i+1}] Qwen3 instruct 重合成失败，保留原始")
                        except Exception as e:
                            print(f"  [{i+1}] Qwen3 instruct 重合成异常: {e}，保留原始")
                else:
                    original_tts_duration = tts_duration
                    try:
                        import pytsmod
                        win_size = int(sample_rate * 0.100)
                        syn_hop_size = int(sample_rate * 0.025)
                        tts_data = pytsmod.ola(tts_data, compress_ratio, win_size=win_size, syn_hop_size=syn_hop_size)
                        tts_duration = len(tts_data) / sample_rate
                        print(f"  [{i+1}] OLA 压缩 {1/compress_ratio:.2f}x: {original_tts_duration:.1f}s -> {tts_duration:.1f}s")
                    except ImportError:
                        print(f"  [WARN] 第 {i+1} 句 TTS 过长 ({tts_duration:.1f}s > {original_duration:.1f}s)，需要安装 pytsmod")
                        max_samples = int(original_duration * sample_rate)
                        tts_data = tts_data[:max_samples]
                        tts_duration = len(tts_data) / sample_rate

            tts_data = _apply_fade(tts_data.astype(np.float32), sample_rate, fade_in_ms, fade_out_ms)

            start_sample = int(start_sec * sample_rate)
            end_sample = start_sample + len(tts_data)

            if start_sample < 0:
                skip_samples = abs(start_sample)
                tts_data = tts_data[skip_samples:]
                start_sample = 0
                end_sample = start_sample + len(tts_data)
                if len(tts_data) == 0:
                    continue

            if timeline is None:
                timeline_samples = end_sample + int(sample_rate)
                timeline = np.zeros(timeline_samples, dtype=np.float32)

            if start_sample >= len(timeline):
                continue
            if end_sample > len(timeline):
                end_sample = len(timeline)
                tts_data = tts_data[:end_sample - start_sample]

            available = end_sample - start_sample
            if available > 0:
                timeline[start_sample:end_sample] += tts_data[:available].astype(np.float32)
                synthesized_count += 1


        if timeline is None or len(timeline) == 0:
            sf.write(str(output_path), np.zeros((1024, 2), dtype=np.float32), sample_rate, subtype="FLOAT")
        else:
            max_val = np.max(np.abs(timeline))
            if max_val > 0.95:
                timeline = timeline * 0.95 / max_val
                print(f"[TTS] 归一化: {max_val:.2f} -> 0.95")
            stereo = np.column_stack([timeline, timeline])
            sf.write(str(output_path), stereo, sample_rate, subtype="FLOAT")

        shutil.rmtree(temp_dir, ignore_errors=True)

        skip_count = len(segments) - synthesized_count - failed_count
        print(f"[TTS] 时间轴拼装完成: {output_path.name}")
        print(f"  成功: {synthesized_count} 句, 失败: {failed_count} 句, 跳过(空): {skip_count} 句")
        return str(output_path)

    @property
    def is_available(self) -> bool:
        """检查引擎是否可用"""
        return True  # edge/qwen3 本地可用


# 注册内置引擎（模块加载时自动注册）
TTSEngine.register("edge", EdgeTTSEngine)
TTSEngine.register("qwen3", Qwen3TTSEngine)


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
