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


def cut_audio_by_subtitle(
    audio_path: str,
    subtitle_entries: list,
    output_dir: str,
    prefix: str = "segment",
) -> list:
    """
    根据字幕时间轴切分音频为多个片段

    Args:
        audio_path: 输入音频文件路径
        subtitle_entries: 字幕条目列表 [{start, end, text}, ...]
        output_dir: 输出目录
        prefix: 输出文件前缀

    Returns:
        List[dict]: [{path, start, end, text, index}, ...] 切分后的音频片段信息
    """
    import soundfile as sf
    import numpy as np

    # 确保输出目录存在
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 读取音频
    data, sr = sf.read(audio_path)
    if len(data.shape) == 1:
        # 单声道
        pass
    else:
        # 多声道，取第一个声道或混合
        data = data[:, 0]  # 取单声道

    results = []
    for i, entry in enumerate(subtitle_entries):
        start_sec = entry["start"]
        end_sec = entry["end"]
        text = entry.get("text", "")

        # 计算采样点
        start_sample = int(start_sec * sr)
        end_sample = int(end_sec * sr)

        # 确保不越界
        end_sample = min(end_sample, len(data))

        # 提取片段
        segment = data[start_sample:end_sample]

        # 计算实际时长（基于采样点数）
        actual_duration = len(segment) / sr

        # 生成输出文件名
        safe_text = sanitize_filename(text[:20]) if text else f"seg{i+1}"
        output_file = output_path / f"{prefix}_{i+1:03d}_{safe_text}.wav"

        # 保存片段
        sf.write(str(output_file), segment, sr)

        results.append({
            "path": str(output_file),
            "start": start_sec,
            "end": end_sec,
            "text": text,
            "index": i + 1,
            "duration": actual_duration,
        })

    return results


# 导出设计模式
from src.utils.patterns import singleton

# 导出 GPU 上下文管理器
from src.utils.gpu_context import gpu_context, clear_gpu_memory
