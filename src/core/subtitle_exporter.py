"""
字幕导出器 - 多格式字幕文件生成

支持格式：
1. SRT - SubRip 字幕格式（通用播放器兼容）
2. VTT - WebVTT 格式（网页播放器）
3. LRC - 歌词格式（音乐播放器）

功能：
1. 从 timestamped_segments 导出字幕
2. 支持单语/双语模式
3. 多格式自动选择
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional


# 字幕段落类型
SubtitleSegment = Dict[str, Any]
# start: float (秒)
# end: float (秒)
# text: str (原文)
# translation: str (译文，可选)


class SubtitleExporter:
    """
    字幕导出器

    支持 SRT、VTT、LRC 三种格式导出
    """

    def __init__(self):
        """初始化字幕导出器"""
        pass

    def export_srt(
        self,
        segments: List[SubtitleSegment],
        output_path: str,
        bilingual: bool = False,
    ) -> bool:
        """
        导出 SRT 格式字幕

        SRT 格式示例：
        1
        00:00:01,000 --> 00:00:04,000
        原文文本

        Args:
            segments: 字幕段落列表
            output_path: 输出文件路径
            bilingual: 是否双语模式（原文+译文）

        Returns:
            是否导出成功
        """
        try:
            lines = []
            for i, seg in enumerate(segments, 1):
                start = self.format_timestamp_srt(seg["start"])
                end = self.format_timestamp_srt(seg["end"])
                text = seg.get("text", "").strip()
                translation = seg.get("translation", "").strip()

                # 序号
                lines.append(str(i))

                # 时间轴
                lines.append(f"{start} --> {end}")

                # 内容
                if bilingual and translation:
                    lines.append(f"{text}")
                    lines.append(f"{translation}")
                elif translation:
                    lines.append(f"{translation}")
                else:
                    lines.append(f"{text}")

                lines.append("")  # 空行分隔

            # 写入文件
            Path(output_path).write_text("\n".join(lines), encoding="utf-8")
            return True

        except Exception as e:
            print(f"[SubtitleExporter] SRT 导出失败: {e}")
            return False

    def export_vtt(
        self,
        segments: List[SubtitleSegment],
        output_path: str,
        bilingual: bool = False,
    ) -> bool:
        """
        导出 VTT (WebVTT) 格式字幕

        VTT 格式示例：
        WEBVTT

        00:00:01.000 --> 00:00:04.000
        原文文本

        Args:
            segments: 字幕段落列表
            output_path: 输出文件路径
            bilingual: 是否双语模式

        Returns:
            是否导出成功
        """
        try:
            lines = ["WEBVTT", ""]  # VTT 头部

            for i, seg in enumerate(segments, 1):
                start = self.format_timestamp_vtt(seg["start"])
                end = self.format_timestamp_vtt(seg["end"])
                text = seg.get("text", "").strip()
                translation = seg.get("translation", "").strip()

                # 时间轴
                lines.append(f"{start} --> {end}")

                # 内容
                if bilingual and translation:
                    lines.append(f"{text}")
                    lines.append(f"{translation}")
                elif translation:
                    lines.append(f"{translation}")
                else:
                    lines.append(f"{text}")

                lines.append("")  # 空行分隔

            # 写入文件
            Path(output_path).write_text("\n".join(lines), encoding="utf-8-sig")  # UTF-8 BOM
            return True

        except Exception as e:
            print(f"[SubtitleExporter] VTT 导出失败: {e}")
            return False

    def export_lrc(
        self,
        segments: List[SubtitleSegment],
        output_path: str,
        bilingual: bool = False,
    ) -> bool:
        """
        导出 LRC (歌词) 格式字幕

        LRC 格式示例：
        [00:00.00] 原文文本
        [00:00.00] <00:00.00> 译文

        Args:
            segments: 字幕段落列表
            output_path: 输出文件路径
            bilingual: 是否双语模式

        Returns:
            是否导出成功
        """
        try:
            lines = []

            for seg in segments:
                start = self.format_timestamp_lrc(seg["start"])
                text = seg.get("text", "").strip()
                translation = seg.get("translation", "").strip()

                # 时间标签行
                if bilingual and translation:
                    # 双语模式：原文在上，译文在下（使用偏移时间）
                    lines.append(f"[{start}] {text}")
                    # 译文使用相同时间或稍后
                    end_start = self.format_timestamp_lrc(seg["end"])
                    lines.append(f"[{end_start}] {translation}")
                elif translation:
                    lines.append(f"[{start}] {translation}")
                else:
                    lines.append(f"[{start}] {text}")

            # 写入文件
            Path(output_path).write_text("\n".join(lines), encoding="utf-8")
            return True

        except Exception as e:
            print(f"[SubtitleExporter] LRC 导出失败: {e}")
            return False

    def export_auto(
        self,
        segments: List[SubtitleSegment],
        output_path: str,
        fmt: str = "srt",
        bilingual: bool = False,
    ) -> bool:
        """
        自动根据扩展名选择格式导出

        Args:
            segments: 字幕段落列表
            output_path: 输出文件路径
            fmt: 格式提示 (srt/vtt/lrc/auto)
            bilingual: 是否双语模式

        Returns:
            是否导出成功
        """
        if fmt == "auto":
            # 根据扩展名自动选择
            ext = Path(output_path).suffix.lower().lstrip(".")
            if ext == "vtt":
                fmt = "vtt"
            elif ext == "lrc":
                fmt = "lrc"
            else:
                fmt = "srt"

        if fmt == "vtt":
            return self.export_vtt(segments, output_path, bilingual)
        elif fmt == "lrc":
            return self.export_lrc(segments, output_path, bilingual)
        else:
            return self.export_srt(segments, output_path, bilingual)

    @staticmethod
    def format_timestamp_srt(seconds: float) -> str:
        """
        格式化时间戳为 SRT 格式

        SRT 格式: HH:MM:SS,mmm

        Args:
            seconds: 秒数

        Returns:
            格式化后的时间字符串
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @staticmethod
    def format_timestamp_vtt(seconds: float) -> str:
        """
        格式化时间戳为 VTT 格式

        VTT 格式: HH:MM:SS.mmm

        Args:
            seconds: 秒数

        Returns:
            格式化后的时间字符串
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

    @staticmethod
    def format_timestamp_lrc(seconds: float) -> str:
        """
        格式化时间戳为 LRC 格式

        LRC 格式: [MM:SS.xx] 或 [MM:SS]

        Args:
            seconds: 秒数

        Returns:
            格式化后的时间字符串
        """
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)

        return f"{minutes:02d}:{secs:02d}.{centisecs:02d}"

    def validate_segments(self, segments: List[SubtitleSegment]) -> List[SubtitleSegment]:
        """
        验证并清理字幕段落

        Args:
            segments: 原始字幕段落列表

        Returns:
            清理后的字幕段落列表
        """
        valid = []

        for seg in segments:
            # 检查必要字段
            if "start" not in seg or "end" not in seg:
                continue

            # 检查时间有效性
            if seg["start"] < 0 or seg["end"] < seg["start"]:
                continue

            # 确保有文本
            text = seg.get("text", "").strip()
            translation = seg.get("translation", "").strip()

            if not text and not translation:
                continue

            valid.append(seg)

        return valid


# 全局单例
_subtitle_exporter: Optional[SubtitleExporter] = None


def get_subtitle_exporter() -> SubtitleExporter:
    """获取字幕导出器单例"""
    global _subtitle_exporter
    if _subtitle_exporter is None:
        _subtitle_exporter = SubtitleExporter()
    return _subtitle_exporter
