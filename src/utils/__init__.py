"""
工具函数模块
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple
import imageio_ffmpeg


def get_ffmpeg() -> str:
    """获取 ffmpeg 路径（使用 imageio_ffmpeg 内置版本）"""
    return imageio_ffmpeg.get_ffmpeg_exe()


def get_audio_duration(audio_path: str) -> float:
    """获取音频时长（秒）"""
    import soundfile as sf
    data, sr = sf.read(audio_path)
    return len(data) / sr


def get_audio_info(audio_path: str) -> dict:
    """获取音频信息"""
    import soundfile as sf
    import numpy as np

    data, sr = sf.read(audio_path)
    return {
        "duration": len(data) / sr,
        "sample_rate": sr,
        "channels": data.shape[1] if len(data.shape) > 1 else 1,
        "samples": len(data),
        "peak": float(np.max(np.abs(data))),
        "rms": float(np.sqrt(np.mean(data**2))),
    }


def ensure_dir(path: str) -> Path:
    """确保目录存在"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_ffmpeg(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    """运行 ffmpeg 命令"""
    cmd = [get_ffmpeg()] + cmd[1:] if cmd[0] == "ffmpeg" else cmd
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )
