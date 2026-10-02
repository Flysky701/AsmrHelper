"""
混音模块 - 智能混音原音与配音

功能：
1. 动态音量调整（TTS 音量自动适配原声）
2. 时间偏移（TTS 可提前/延后）
3. 双轨混音（双语模式）
"""

import time
import math
from pathlib import Path
import soundfile as sf
import numpy as np

from ..utils import get_ffmpeg, ensure_dir


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
        if data.size == 0 or not np.isfinite(data).all():
            raise ValueError("混音输入音频为空或包含无效采样")
        # 使用 RMS 作为统一音量口径，避免峰值检测受随机削波影响
        if data.dtype == np.float32 or data.dtype == np.float64:
            return float(np.sqrt(np.mean(np.square(data))))
        return float(np.sqrt(np.mean(np.square(data.astype(np.float64)))) / 32768)

    def mix(
        self,
        original_path: str,
        tts_path: str,
        output_path: str,
        adjust_tts_volume: bool = True,
        output_length: str = "main",
    ) -> str:
        """
        混音原音与 TTS 配音

        Args:
            original_path: 原音文件路径
            tts_path: TTS 配音文件路径
            output_path: 输出文件路径
            adjust_tts_volume: 是否自动调整 TTS 音量
            output_length: main 跟随主音轨；longest 保留偏移后较长的音轨

        Returns:
            str: 输出文件路径
        """
        if output_length not in ("main", "longest"):
            raise ValueError("混音输出长度必须为 main 或 longest")
        if not math.isfinite(self.tts_delay_ms):
            raise ValueError("混音延迟无效")
        original_path = Path(original_path)
        tts_path = Path(tts_path)
        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        print("[Mixer] 混音原音与配音...")
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
        speech_info = sf.info(str(tts_path))
        if info.frames < 1 or speech_info.frames < 1:
            raise ValueError("混音需要非空音频")
        output_duration = (info.duration if output_length == "main" else
                           max(info.duration, speech_info.duration + self.tts_delay_ms / 1000))
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
        # 时间零点之前的配音被裁掉；正偏移补前置静音。
        delay_ms = self.tts_delay_ms
        orig_vol = self.original_volume
        tts_vol_db = tts_gain_db

        # 保留原有音量与 amix normalize 算法，仅改变时间范围。
        tts_filter = f"volume={tts_vol_db}dB"
        if delay_ms < 0:
            # 有界尾部静音保证整条配音移出时间零点时仍产生合法静音轨。
            advance = abs(delay_ms) / 1000
            tts_filter += (f",apad=whole_dur={output_duration + advance},"
                           f"atrim=start={advance}:duration={output_duration},asetpts=PTS-STARTPTS")
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
            f"[0:a]{orig_filter}[orig];[1:a]{tts_filter}[tts];[orig][tts]amix=inputs=2:duration={'first' if output_length == 'main' else 'longest'}[mixed]",
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
