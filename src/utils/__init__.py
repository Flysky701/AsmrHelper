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


def run_ffmpeg(cmd: list, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    """运行 ffmpeg 命令"""
    cmd = [get_ffmpeg()] + cmd[1:] if cmd[0] == "ffmpeg" else cmd
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        timeout=timeout,  # 防止 ffmpeg 卡死
    )


def find_vtt_file(input_path: Path, extra_dirs: list = None) -> Optional[Path]:
    """
    查找匹配的 VTT 字幕文件

    Args:
        input_path: 音频文件路径
        extra_dirs: 额外搜索目录列表

    Returns:
        VTT 文件路径，未找到返回 None
    """
    # 可能的 VTT 文件名
    possible_names = [
        f"{input_path.name}.vtt",
        f"{input_path.stem}.vtt",
        f"{input_path.name.removesuffix(input_path.suffix)}.vtt",
    ]

    # 搜索目录
    search_dirs = [input_path.parent]

    # 添加 ASMR_O 子目录
    asmr_o_dir = input_path.parent / "ASMR_O"
    if asmr_o_dir.exists():
        search_dirs.append(asmr_o_dir)

    # 添加额外目录
    if extra_dirs:
        for d in extra_dirs:
            if d and Path(d).exists():
                search_dirs.append(Path(d))

    # 去重
    search_dirs = list(dict.fromkeys(search_dirs))

    # 搜索
    for search_dir in search_dirs:
        for name in possible_names:
            vtt_path = search_dir / name
            if vtt_path.exists():
                return vtt_path

    return None


def sanitize_filename(name: str) -> str:
    """
    将文件名转换为安全格式

    Args:
        name: 原始文件名

    Returns:
        安全的文件名（只保留字母数字和常用符号）
    """
    return "".join(c if c.isalnum() or c in " _-()" else "_" for c in name)
