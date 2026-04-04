"""
GUI 服务模块

包含辅助函数：
- scan_audio_files: 扫描目录下的音频文件
"""

from pathlib import Path
from typing import List

from src.utils.constants import AUDIO_EXTENSIONS


def scan_audio_files(directory: str) -> List[str]:
    """
    扫描目录下的所有音频文件

    Args:
        directory: 目录路径

    Returns:
        音频文件路径列表
    """
    directory = Path(directory)
    if not directory.exists():
        return []

    audio_files = []
    for ext in AUDIO_EXTENSIONS:
        audio_files.extend(directory.glob(f"*{ext}"))
        audio_files.extend(directory.glob(f"*{ext.upper()}"))

    return sorted([str(f) for f in audio_files])
