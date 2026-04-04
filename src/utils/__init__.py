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
    查找匹配的 VTT 字幕文件（向后兼容）

    Args:
        input_path: 音频文件路径
        extra_dirs: 额外搜索目录列表

    Returns:
        VTT 文件路径，未找到返回 None
    """
    # 优先只搜索 .vtt 文件
    subtitle_exts = [".vtt"]
    return _find_subtitle_file_impl(input_path, extra_dirs, subtitle_exts)


def find_subtitle_file(input_path: Path, extra_dirs: list = None, extensions: list = None) -> Optional[Path]:
    """
    查找匹配的字幕文件（支持多种格式）

    优先级: .vtt > .srt > .lrc

    Args:
        input_path: 音频文件路径
        extra_dirs: 额外搜索目录列表
        extensions: 指定要搜索的格式列表，如 [".vtt", ".srt", ".lrc"]

    Returns:
        字幕文件路径，未找到返回 None
    """
    if extensions is None:
        extensions = [".vtt", ".srt", ".lrc"]
    return _find_subtitle_file_impl(input_path, extra_dirs, extensions)


def _find_subtitle_file_impl(input_path: Path, extra_dirs: list, extensions: list) -> Optional[Path]:
    """
    通用字幕文件搜索实现

    Args:
        input_path: 音频文件路径
        extra_dirs: 额外搜索目录列表
        extensions: 要搜索的格式列表

    Returns:
        字幕文件路径，未找到返回 None
    """
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

    # 为每个格式生成可能的文件名
    possible_names_by_ext = {}
    for ext in extensions:
        possible_names_by_ext[ext] = [
            f"{input_path.name}{ext}",
            f"{input_path.stem}{ext}",
            f"{input_path.name.removesuffix(input_path.suffix)}{ext}",
        ]

    # 按优先级搜索（先 vtt，再 srt，再 lrc）
    for search_dir in search_dirs:
        for ext in extensions:
            for name in possible_names_by_ext[ext]:
                subtitle_path = search_dir / name
                if subtitle_path.exists():
                    return subtitle_path

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


# 导出设计模式
from src.utils.patterns import singleton

# 导出 GPU 上下文管理器
from src.utils.gpu_context import gpu_context, clear_gpu_memory
