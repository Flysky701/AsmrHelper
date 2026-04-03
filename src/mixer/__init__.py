"""
混音模块 - 智能混音原音与配音

功能：
1. 动态音量调整（TTS 音量自动适配原声）
2. 时间偏移（TTS 可提前/延后）
3. 双轨混音（双语模式）
"""

import time
from pathlib import Path
from typing import Optional, Tuple
import soundfile as sf
import numpy as np

from ..utils import get_ffmpeg, ensure_dir


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
        data, sr = sf.read(audio_path)
        if data.dtype == np.float32 or data.dtype == np.float64:
            return float(np.max(np.abs(data)))
        else:
            return float(np.sqrt(np.mean(data**2)) / 32768)

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

        # 构建 ffmpeg 命令
        delay_ms = max(0, self.tts_delay_ms)
        orig_vol = self.original_volume
        tts_vol_db = tts_gain_db

        cmd = [
            get_ffmpeg(),
            "-i", str(original_path),
            "-i", str(tts_path),
            "-filter_complex",
            f"[0:a]volume={orig_vol}[orig];[1:a]volume={tts_vol_db}dB,adelay={delay_ms}|{delay_ms}[tts];[orig][tts]amix=inputs=2:duration=first[mixed]",
            "-map", "[mixed]",
            "-ar", "44100",
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

    def build_aligned_tts(
        self,
        segments: list,
        tts_engine,
        output_path: str,
        reference_duration: float,
        sample_rate: int = 44100,
        tts_speed_range: tuple = (0.8, 1.2),
        fade_in_ms: int = 30,
        fade_out_ms: int = 50,
    ) -> str:
        """
        逐句合成 TTS 并按时间戳拼装到时间轴上（解决时间轴对齐问题）

        核心逻辑：
        1. 对每句翻译单独合成 TTS
        2. 按原音时间戳将 TTS 放置到正确位置
        3. 段间填充静音或自动拉伸

        Args:
            segments: 带时间戳的段落 [{start, end, text, translation}, ...]
            tts_engine: TTS 引擎实例
            output_path: 输出文件路径
            reference_duration: 参考音频总时长（秒）
            sample_rate: 采样率
            tts_speed_range: TTS 语速允许范围 (min, max)
            fade_in_ms: 淡入时长（毫秒）
            fade_out_ms: 淡出时长（毫秒）

        Returns:
            str: 输出文件路径
        """
        import shutil  # 用于临时目录清理

        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        # 创建空的时间轴（与原音等长的静音）
        total_samples = int(reference_duration * sample_rate)
        timeline = np.zeros(total_samples, dtype=np.float32)

        # 创建临时目录
        temp_dir = output_path.parent / "tts_temp"
        temp_dir.mkdir(exist_ok=True)

        print(f"[Mixer] 逐句合成 TTS ({len(segments)} 句)...")

        synthesized_count = 0
        for i, seg in enumerate(segments):
            translation = seg.get("translation", "")
            if not translation.strip():
                continue

            start_sec = seg["start"]
            end_sec = seg["end"]
            original_duration = end_sec - start_sec

            # 1. 合成单句 TTS
            temp_tts = temp_dir / f"tts_{i:04d}.wav"
            try:
                tts_engine.synthesize(translation, str(temp_tts))
            except Exception as e:
                print(f"  [WARN] 第 {i+1} 句 TTS 失败: {e}")
                continue

            # 2. 读取 TTS 音频
            try:
                tts_data, tts_sr = sf.read(str(temp_tts))
            except Exception as e:
                print(f"  [WARN] 第 {i+1} 句读取失败: {e}")
                continue

            # 重采样（如需要）
            if tts_sr != sample_rate:
                try:
                    import librosa
                    tts_data = librosa.resample(tts_data, orig_sr=tts_sr, target_sr=sample_rate)
                except ImportError:
                    # 没有 librosa，使用 soundfile 重采样
                    _temp_wav = output_path.parent / f"_resample_temp_{i}.wav"
                    sf.write(str(_temp_wav), tts_data, tts_sr)
                    # 用 ffmpeg 重采样
                    import subprocess
                    ffmpeg_path = get_ffmpeg()
                    subprocess.run(
                        [ffmpeg_path, "-i", str(_temp_wav), "-ar", str(sample_rate), "-ac", "2", str(_temp_wav.with_suffix(".48k.wav"))],
                        capture_output=True, check=True,
                    )
                    tts_data, tts_sr = sf.read(str(_temp_wav.with_suffix(".48k.wav")))
                    _temp_wav.unlink(missing_ok=True)
                    _temp_wav.with_suffix(".48k.wav").unlink(missing_ok=True)

            tts_duration = len(tts_data) / sample_rate

            # 3. 处理时长差异（TTS 过长时加速）
            if tts_duration > original_duration * tts_speed_range[1]:
                target_duration = original_duration * tts_speed_range[1]
                speed_factor = tts_duration / target_duration

                try:
                    import pytsmod
                    tts_data = pytsmod.time_stretch(
                        tts_data,
                        sample_rate,
                        target_rate=speed_factor,
                    )
                    tts_duration = len(tts_data) / sample_rate
                    print(f"  [{i+1}] 加速 {speed_factor:.2f}x: {tts_duration:.1f}s -> {target_duration:.1f}s")
                except ImportError:
                    print(f"  [WARN] 第 {i+1} 句 TTS 过长 ({tts_duration:.1f}s > {original_duration:.1f}s)，需要安装 pytsmod")
                    # 截断到原音长度
                    max_samples = int(original_duration * sample_rate)
                    tts_data = tts_data[:max_samples]
                    tts_duration = len(tts_data) / sample_rate

            # 4. 应用淡入淡出
            tts_data = _apply_fade(tts_data.astype(np.float32), sample_rate, fade_in_ms, fade_out_ms)

            # 5. 放置到时间轴
            start_sample = int(start_sec * sample_rate)
            end_sample = start_sample + len(tts_data)

            # 边界保护
            if start_sample >= total_samples:
                continue
            if end_sample > total_samples:
                end_sample = total_samples
                tts_data = tts_data[:end_sample - start_sample]

            # 叠加（避免覆盖之前的内容）
            available = end_sample - start_sample
            if available > 0:
                timeline[start_sample:end_sample] += tts_data[:available].astype(np.float32)
                synthesized_count += 1

            # 清理临时文件
            temp_tts.unlink(missing_ok=True)

        # 6. 归一化（防止溢出）
        max_val = np.max(np.abs(timeline))
        if max_val > 0.95:
            timeline = timeline * 0.95 / max_val
            print(f"[Mixer] 归一化: {max_val:.2f} -> 0.95")

        # 7. 保存为 WAV
        sf.write(str(output_path), timeline, sample_rate)

        # 清理临时目录
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

        print(f"[Mixer] 时间轴拼装完成: {output_path.name} ({synthesized_count}/{len(segments)} 句)")
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
