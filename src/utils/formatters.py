"""Formatting helpers for timestamp strings."""

from __future__ import annotations


def format_timestamp(seconds: float, fmt: str = "srt") -> str:
    """Format seconds into subtitle timestamps.

    Supported formats:
    - srt: HH:MM:SS,mmm
    - vtt: HH:MM:SS.mmm
    - lrc: [MM:SS.xx]
    """
    if fmt == "lrc":
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"[{minutes:02d}:{secs:05.2f}]"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)

    if fmt == "srt":
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
