"""
Pipeline 产物收集解耦：负责处理流程结束后产生的文件、字幕写入和临时文件垃圾回收。
"""
from pathlib import Path
import shutil
from typing import Dict, List, Optional
from src.utils.formatters import format_timestamp

class ArtifactCollector:
    def __init__(self, config):
        self.config = config
        self.progress_callback = None

    def _report(self, msg: str):
        if self.progress_callback:
            self.progress_callback(msg)

    def write_subtitles(self, active_steps: List[str], timestamped_segments: List[Dict],
                       translations: List[str], by_product_dir: Path, task_name: str, subtitle_lang: str):
        """
        Export subtitle file
        """
        if "translate" not in active_steps and self.config.pipeline_mode != "full":
            return None

        if not timestamped_segments:
            return None

        # In pipeline_mode='full', it's translated, so it exports dual-language.
        fmt = self.config.export_subtitle_format
        base_name = f"{task_name}_subtitle"
        
        path = by_product_dir / f"{base_name}.{fmt}"
        content = ""
        
        if fmt == "srt":
            content = self._build_srt(timestamped_segments, translations)
        elif fmt == "vtt":
            content = self._build_vtt(timestamped_segments, translations)
        elif fmt == "lrc":
            content = self._build_lrc(timestamped_segments, translations)
        else:
            return None

        path.write_text(content, encoding="utf-8")
        self._report(f"  [字幕] 导出 {path.name}")
        return str(path)

    def _build_srt(self, segments: List[Dict], translations: List[str]) -> str:
        lines = []
        for i, seg in enumerate(segments, 1):
            start = format_timestamp(seg["start"], fmt="srt")
            end = format_timestamp(seg["end"], fmt="srt")
            text = seg.get("text", "")
            translation = seg.get("translation", "")
            
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            if text and translation:
                lines.append(f"{text}\n{translation}")
            elif text or translation:
                lines.append(text or translation)
            lines.append("")
        return "\n".join(lines).strip()

    def _build_vtt(self, segments: List[Dict], translations: List[str]) -> str:
        lines = ["WEBVTT", ""]
        for seg in segments:
            start = format_timestamp(seg["start"], fmt="vtt")
            end = format_timestamp(seg["end"], fmt="vtt")
            text = seg.get("text", "")
            translation = seg.get("translation", "")
            
            lines.append(f"{start} --> {end}")
            if text and translation:
                lines.append(f"{text}\n{translation}")
            elif text or translation:
                lines.append(text or translation)
            lines.append("")
        return "\n".join(lines).strip()

    def _build_lrc(self, segments: List[Dict], translations: List[str]) -> str:
        lines = []
        for seg in segments:
            start_ms = int(seg["start"] * 1000)
            minutes = start_ms // 60000
            seconds = (start_ms % 60000) // 1000
            centiseconds = (start_ms % 1000) // 10
            ts = f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]"
            
            text = seg.get("text", "")
            translation = seg.get("translation", "")
            
            if text and translation:
                lines.append(f"{ts}{text}")
                lines.append(f"{ts}{translation}")
            elif text or translation:
                lines.append(f"{ts}{text or translation}")
                
        return "\n".join(lines)

    def collect(self, results: Dict, input_path: Path, mix_path: Path, by_product_dir: Path):
        """
        处理最终结果、清理临时路径等。
        """
        # copy/move the final artifact to mix_path is already done by Mixer, 
        # so this is mostly for cleanup logic or metadata gathering.
        pass
