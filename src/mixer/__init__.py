"""
混音模块 - 智能混音原音与配音

功能：
1. 动态音量调整（TTS 音量自动适配原声）
2. 时间偏移（TTS 可提前/延后）
3. 双轨混音（双语模式）
"""

import time
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple
import soundfile as sf
import numpy as np

from ..utils import get_ffmpeg, ensure_dir


def _clean_text_for_tts(text: str) -> str:
    """
    清理文本以适配 TTS 引擎

    Args:
        text: 原始文本

    Returns:
        str: 清理后的文本
    """
    if not text:
        return ""

    # 移除可能导致 Edge-TTS 问题的特殊字符
    # 保留中文、英文、数字、基本标点
    cleaned = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', text)

    # 移除多余的空白字符
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Edge-TTS 对某些字符可能有问题，替换或移除
    # 移除控制字符和零宽字符
    cleaned = cleaned.replace('\u200b', '')  # 零宽空格
    cleaned = cleaned.replace('\ufeff', '')  # BOM

    # 移除开头和结尾的标点符号（Edge-TTS 无法处理纯标点）
    cleaned = cleaned.strip('。？！，、；：""''「」『』【】()（）…—·')

    # 如果清理后只剩标点或为空，返回空字符串
    if not cleaned or re.match(r'^[\s。？！，、；：""''「」『』【】()（）…—·]*$', cleaned):
        return ""

    return cleaned


def _apply_fade(audio: np.ndarray, sample_rate: int, fade_in_ms: int = 30, fade_out_ms: int = 50) -> np.ndarray:
    """
    应用淡入淡出

    Args:
        audio: 音频数据
        sample_rate: 采样率
        fade_in_ms: 淡入时长（毫秒）
        fade_out_ms: 淡出时长（毫秒）

    Returns:
        np.ndarray: 处理后的音频
    """
    audio = audio.copy()
    fade_in_samples = int(fade_in_ms * sample_rate / 1000)
    fade_out_samples = int(fade_out_ms * sample_rate / 1000)

    # 淡入
    if fade_in_samples > 0 and len(audio) > fade_in_samples:
        audio[:fade_in_samples] *= np.linspace(0, 1, fade_in_samples)

    # 淡出
    if fade_out_samples > 0 and len(audio) > fade_out_samples:
        audio[-fade_out_samples:] *= np.linspace(1, 0, fade_out_samples)

    return audio


class Mixer:
    """智能混音器（支持时间轴对齐 TTS）"""

    def __init__(
        self,
        original_volume: float = 0.85,
        tts_volume_ratio: float = 0.5,
        tts_delay_ms: float = 0,
    ):
        """
        初始化混音器

        Args:
            original_volume: 原音音量 (0.0-1.0)
            tts_volume_ratio: TTS 音量相对于原声的比例
            tts_delay_ms: TTS 延迟（正=延后，负=提前），单位毫秒
        """
        self.original_volume = original_volume
        self.tts_volume_ratio = tts_volume_ratio
        self.tts_delay_ms = tts_delay_ms

    def detect_volume(self, audio_path: str) -> float:
        """检测音频音量"""
        data, _ = sf.read(audio_path)
        # 使用 RMS 作为统一音量口径，避免峰值检测受随机削波影响
        if data.dtype == np.float32 or data.dtype == np.float64:
            return float(np.sqrt(np.mean(np.square(data))))
        return float(np.sqrt(np.mean(np.square(data.astype(np.float64)))) / 32768)

    @staticmethod
    def _qwen3_speed_instruct(tts_duration: float, target_duration: float) -> str:
        """
        根据 TTS 超出目标的程度，生成对应的自然语言速度提示词

        Args:
            tts_duration: TTS 实际时长
            target_duration: 目标时长（原音频时长）

        Returns:
            str: instruct 提示词，如果超出不大则返回空字符串（不值得重合成）
        """
        if target_duration <= 0:
            return ""
        ratio = tts_duration / target_duration
        if ratio <= 1.2:
            # 超出不明显，不重合成
            return ""
        elif ratio <= 1.5:
            return "语速稍快"
        elif ratio <= 2.0:
            return "语速加快"
        elif ratio <= 3.0:
            return "用比较快的语速说"
        else:
            return "用非常快的语速说"

    def mix(
        self,
        original_path: str,
        tts_path: str,
        output_path: str,
        adjust_tts_volume: bool = True,
    ) -> str:
        """
        混音原音与 TTS 配音

        Args:
            original_path: 原音文件路径
            tts_path: TTS 配音文件路径
            output_path: 输出文件路径
            adjust_tts_volume: 是否自动调整 TTS 音量

        Returns:
            str: 输出文件路径
        """
        original_path = Path(original_path)
        tts_path = Path(tts_path)
        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        print(f"[Mixer] 混音原音与配音...")
        print(f"  原音: {original_path.name}")
        print(f"  配音: {tts_path.name}")

        # 检测原音音量
        orig_peak = self.detect_volume(str(original_path))
        print(f"  原音峰值: {orig_peak:.2f}")

        # 计算 TTS 音量
        tts_peak = self.detect_volume(str(tts_path))
        if adjust_tts_volume and orig_peak > 0:
            tts_volume = orig_peak * self.tts_volume_ratio
            tts_gain_db = 20 * np.log10(tts_volume / tts_peak) if tts_peak > 0 else 0
        else:
            tts_volume = tts_peak * self.tts_volume_ratio
            tts_gain_db = 20 * np.log10(self.tts_volume_ratio)

        print(f"  TTS 音量比例: {self.tts_volume_ratio} (gain: {tts_gain_db:.1f}dB)")

        # 计算延迟样本数
        info = sf.info(str(original_path))
        delay_samples = int(self.tts_delay_ms * info.samplerate / 1000)
        print(f"  TTS 延迟: {self.tts_delay_ms}ms ({delay_samples} samples)")

        t0 = time.time()

        # 获取输入文件格式，输出与输入格式一致
        input_ext = original_path.suffix.lower()
        output_ext = output_path.suffix.lower() if output_path.suffix else input_ext

        # 根据输出格式选择编码器
        if output_ext == ".mp3":
            acodec = "libmp3lame"
            ar = "44100"
        elif output_ext in (".m4a", ".aac"):
            acodec = "aac"
            ar = "44100"
        elif output_ext == ".flac":
            acodec = "flac"
            ar = str(info.samplerate)
        else:
            # 默认 WAV 输出：使用 32-bit float 无损
            acodec = "pcm_f32le"
            ar = "44100"

        # 构建 ffmpeg 命令
        # 延迟：负值表示TTS提前（需要在TTS前端padding）；正值表示TTS延后
        delay_ms = self.tts_delay_ms
        orig_vol = self.original_volume
        tts_vol_db = tts_gain_db

        # 准备 pad/echo 滤镜实现负延迟（提前）
        tts_filter = f"volume={tts_vol_db}dB"
        if delay_ms < 0:
            # 负延迟：TTS提前，先padding静音再输出
            abs_delay_ms = abs(delay_ms)
            # 使用apad在TTS前面添加静音，atrim限制总时长
            tts_filter += f",apad=whole_dur={info.duration + abs_delay_ms/1000}s,atrim=start={abs_delay_ms/1000}:duration={info.duration}"
            orig_filter = f"volume={orig_vol},adelay=0|0"
        elif delay_ms > 0:
            # 正延迟：TTS延后，使用adelay
            tts_filter += f",adelay={delay_ms}|{delay_ms}"
            orig_filter = f"volume={orig_vol}"
        else:
            orig_filter = f"volume={orig_vol}"

        # 如果输出格式需要特定采样率，应用转换
        final_ar = ar
        if output_ext in (".mp3", ".m4a", ".aac"):
            # 有损格式使用 44100Hz
            final_ar = "44100"
        elif output_ext == ".flac":
            final_ar = str(info.samplerate)  # FLAC 保持原采样率

        cmd = [
            get_ffmpeg(),
            "-i", str(original_path),
            "-i", str(tts_path),
            "-filter_complex",
            f"[0:a]{orig_filter}[orig];[1:a]{tts_filter}[tts];[orig][tts]amix=inputs=2:duration=first[mixed]",
            "-map", "[mixed]",
            "-acodec", acodec,
            "-ar", final_ar,
            "-ac", "2",
            str(output_path),
            "-y",
        ]

        import subprocess

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            raise RuntimeError(f"混音失败: {result.stderr}")

        print(f"[Mixer] 混音完成，耗时: {time.time()-t0:.1f}s")
        print(f"  输出: {output_path.name}")

        return str(output_path)

    def mix_bilingual(
        self,
        original_path: str,
        left_channel_path: str,
        right_channel_path: str,
        output_path: str,
    ) -> str:
        """
        双语双轨混音

        Args:
            original_path: 原音文件
            left_channel_path: 左声道音频（日文配音）
            right_channel_path: 右声道音频（中文配音）
            output_path: 输出文件

        Returns:
            str: 输出文件路径
        """
        print(f"[Mixer] 双语双轨混音...")

        t0 = time.time()

        import subprocess

        cmd = [
            get_ffmpeg(),
            "-i", str(original_path),
            "-i", str(left_channel_path),
            "-i", str(right_channel_path),
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=first[orig];[orig][2:a]amix=inputs=2:duration=first[out]",
            "-map", "[out]",
            "-ar", "44100",
            "-ac", "2",
            str(output_path),
            "-y",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            raise RuntimeError(f"双语混音失败: {result.stderr}")

        print(f"[Mixer] 双语混音完成，耗时: {time.time()-t0:.1f}s")

        return str(output_path)


# 便捷函数
def mix_audio(
    original_path: str,
    tts_path: str,
    output_path: str,
    tts_volume_ratio: float = 0.5,
    tts_delay_ms: float = 0,
) -> str:
    """快速混音"""
    mixer = Mixer(
        original_volume=0.85,
        tts_volume_ratio=tts_volume_ratio,
        tts_delay_ms=tts_delay_ms,
    )
    return mixer.mix(original_path, tts_path, output_path)
