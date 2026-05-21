"""
ScriptToSubtitlePipeline — 台本转字幕完整流水线

流程：
  clean_script: 台本(PDF/TXT) → 清洗后的 TXT（regex 粗洗 + LLM 精洗）
  asr_recognize: MP3 → ASR VTT（已实现，复用 ASRRecognizer）
  llm_align: 清洗 TXT + ASR VTT → LLM 智能重排对齐 → 最终 VTT
"""

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from src.core.subtitle_generator import SubtitleGenerator
from .tool import ScriptToSubtitleTool


class ScriptToSubtitlePipeline:
    """台本(PDF/TXT) → 完整字幕 流水线"""

    @staticmethod
    def _save_debug(debug_dir: Path, stage: str, filename: str, content: str) -> None:
        """保存调试中间文件"""
        stage_dir = debug_dir / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / filename).write_text(content, encoding="utf-8")

    @staticmethod
    def _save_debug_json(debug_dir: Path, stage: str, filename: str, data: Any) -> None:
        """保存调试中间文件（JSON 格式）"""
        stage_dir = debug_dir / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def run(
        self,
        script_path: Union[str, Path],
        audio_path: Union[str, Path],
        output_path: Union[str, Path],
        fmt: str = "vtt",
        use_llm_clean: bool = True,
        asr_model_size: str = "large-v3",
        asr_language: str = "ja",
        track_index: Optional[int] = None,
        vertical_mode: str = "auto",
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        debug_dir: Optional[Union[str, Path]] = None,
    ) -> str:
        """
        完整流程：台本 + 音频 → 字幕文件。

        Args:
            script_path: 台本文件路径（PDF 或 TXT）
            audio_path: MP3/WAV 音频路径
            output_path: 输出字幕文件路径
            fmt: 输出格式 ("vtt" / "srt" / "lrc")
            use_llm_clean: 是否使用 LLM 辅助清洗
            asr_model_size: ASR 模型大小
            asr_language: ASR 语言
            track_index: 指定处理的 Track 索引（从 0 开始）
            vertical_mode: PDF 竖排处理模式 ("auto" / "horizontal" / "vertical")
            progress_callback: 进度回调 fn(stage, percent, message)
            debug_dir: 调试输出目录（可选，设置后保存各阶段中间文件）

        Returns:
            输出文件路径
        """
        cb = progress_callback or (lambda *a: None)
        dbg = Path(debug_dir) if debug_dir else None

        # ---- Stage 1: clean_script - 台本 → 清洗 TXT ----
        cb("clean_script", 0, "正在加载台本文件...")
        raw_text = ScriptToSubtitleTool.load_script(script_path, vertical_mode=vertical_mode)
        if dbg:
            self._save_debug(dbg, "stage1_extract", "01_raw_text.txt", raw_text)

        # ---- 多 Track 检测 ----
        from src.core.script_processor import ScriptProcessor
        sections = ScriptProcessor.detect_scripts(raw_text)
        if len(sections) > 1:
            if track_index is not None and 0 <= track_index < len(sections):
                raw_text = sections[track_index]["text"]
                cb("clean_script", 15, f"检测到 {len(sections)} 个 Track，使用 Track {track_index + 1}: {sections[track_index]['title']}")
            else:
                titles = ", ".join(s["title"] for s in sections)
                cb("clean_script", 15, f"检测到 {len(sections)} 个 Track ({titles})，处理全部")

        cb("clean_script", 30, "正在清洗台本...")
        if use_llm_clean:
            clean_text = ScriptToSubtitleTool.clean_script_with_llm(raw_text, debug_dir=dbg)
        else:
            clean_text = ScriptToSubtitleTool.clean_script(raw_text)
        if dbg:
            self._save_debug(dbg, "stage1_clean", "02_clean_text.txt", clean_text)

        cb("clean_script", 100, f"台本清洗完成，共 {len(clean_text.splitlines())} 行台词")

        # ---- Stage 2: asr_recognize - 音频 → ASR ----
        cb("asr_recognize", 0, "正在语音识别...")
        from src.core.engines.asr import get_asr_registry
        asr = get_asr_registry().get(
            "faster_whisper",
            model_size=asr_model_size,
            language=asr_language,
        )
        asr_results = asr.recognize(
            str(audio_path),
            progress_callback=lambda cur, dur, n: cb("asr_recognize", int(cur / dur * 100) if dur > 0 else 0, f"已识别 {n} 段 ({cur:.1f}s/{dur:.1f}s)"),
        )
        cb("asr_recognize", 100, f"语音识别完成，共 {len(asr_results)} 个片段")
        if dbg:
            self._save_debug_json(dbg, "stage2_asr", "03_asr_results.json", asr_results)

        # ---- Stage 3: llm_align - LLM 对齐 ----
        cb("llm_align", 0, "正在 LLM 智能对齐...")
        entries = ScriptToSubtitleTool.align_with_llm(clean_text, asr_results, debug_dir=dbg)
        cb("llm_align", 80, f"对齐完成，共 {len(entries)} 条字幕")
        if dbg:
            self._save_debug_json(dbg, "stage3_align", "04_aligned_entries.json", entries)

        # ---- 保存 ----
        SubtitleGenerator.save(entries, str(output_path), fmt=fmt)
        if dbg:
            final_content = Path(output_path).read_text(encoding="utf-8")
            self._save_debug(dbg, "stage4_output", f"final.{fmt}", final_content)
        cb("llm_align", 100, f"已保存到 {output_path}")

        return str(output_path)

    def run_from_existing_vtt(
        self,
        script_path: Union[str, Path],
        vtt_path: Union[str, Path],
        output_path: Union[str, Path],
        fmt: str = "vtt",
        use_llm_clean: bool = True,
        track_index: Optional[int] = None,
        vertical_mode: str = "auto",
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        debug_dir: Optional[Union[str, Path]] = None,
    ) -> str:
        """
        已有 ASR 字幕的情况（跳过 asr_recognize）。

        适用场景：之前已经跑过 ASR，现在只需要用台本修正字幕。

        Args:
            script_path: 台本文件路径（PDF 或 TXT）
            vtt_path: 已有的 ASR 字幕路径（VTT/SRT/LRC）
            output_path: 输出路径
            fmt: 输出格式
            use_llm_clean: 是否使用 LLM 辅助清洗
            track_index: 指定处理的 Track 索引（从 0 开始）。当台本包含多个 Track 时，
                         传入此参数仅处理对应 Track 的台词。None 表示处理全部。
            vertical_mode: PDF 竖排处理模式 ("auto" / "horizontal" / "vertical")
            progress_callback: 进度回调
            debug_dir: 调试输出目录（可选）

        Returns:
            输出文件路径
        """
        cb = progress_callback or (lambda *a: None)
        dbg = Path(debug_dir) if debug_dir else None

        # ---- clean_script: 台本 → 清洗 TXT ----
        cb("clean_script", 0, "正在加载台本文件...")
        raw_text = ScriptToSubtitleTool.load_script(script_path, vertical_mode=vertical_mode)
        if dbg:
            self._save_debug(dbg, "stage1_extract", "01_raw_text.txt", raw_text)

        # ---- 多 Track 检测 ----
        from src.core.script_processor import ScriptProcessor
        sections = ScriptProcessor.detect_scripts(raw_text)
        if len(sections) > 1:
            if track_index is not None and 0 <= track_index < len(sections):
                raw_text = sections[track_index]["text"]
                cb("clean_script", 15, f"检测到 {len(sections)} 个 Track，使用 Track {track_index + 1}: {sections[track_index]['title']}")
            else:
                titles = ", ".join(s["title"] for s in sections)
                cb("clean_script", 15, f"检测到 {len(sections)} 个 Track ({titles})，处理全部")

        cb("clean_script", 30, "正在清洗台本...")
        if use_llm_clean:
            clean_text = ScriptToSubtitleTool.clean_script_with_llm(raw_text, debug_dir=dbg)
        else:
            clean_text = ScriptToSubtitleTool.clean_script(raw_text)
        if dbg:
            self._save_debug(dbg, "stage1_clean", "02_clean_text.txt", clean_text)

        cb("clean_script", 100, f"台本清洗完成，共 {len(clean_text.splitlines())} 行台词")

        # ---- 加载已有字幕 ----
        cb("llm_align", 0, "正在加载已有字幕...")
        from src.core.subtitles import load_subtitle_with_timestamps
        asr_results = load_subtitle_with_timestamps(str(vtt_path))
        cb("llm_align", 20, f"已加载 {len(asr_results)} 个字幕片段")
        if dbg:
            self._save_debug_json(dbg, "stage2_asr", "03_asr_results.json", asr_results)

        # ---- llm_align: LLM 对齐 ----
        cb("llm_align", 30, "正在 LLM 智能对齐...")
        entries = ScriptToSubtitleTool.align_with_llm(clean_text, asr_results, debug_dir=dbg)
        cb("llm_align", 80, f"对齐完成，共 {len(entries)} 条字幕")
        if dbg:
            self._save_debug_json(dbg, "stage3_align", "04_aligned_entries.json", entries)

        # ---- 保存 ----
        SubtitleGenerator.save(entries, str(output_path), fmt=fmt)
        if dbg:
            final_content = Path(output_path).read_text(encoding="utf-8")
            self._save_debug(dbg, "stage4_output", f"final.{fmt}", final_content)
        cb("llm_align", 100, f"已保存到 {output_path}")

        return str(output_path)

    def run_text_only(
        self,
        script_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        use_llm_clean: bool = True,
        track_index: Optional[int] = None,
        vertical_mode: str = "auto",
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        debug_dir: Optional[Union[str, Path]] = None,
    ) -> str:
        """
        仅 clean_script：台本 → 清洗后的纯文本（不做 ASR 和对齐）。

        Args:
            script_path: 台本文件路径（PDF 或 TXT）
            output_path: 输出 TXT 路径（可选）
            use_llm_clean: 是否使用 LLM 辅助清洗
            track_index: 指定处理的 Track 索引（从 0 开始）
            vertical_mode: PDF 竖排处理模式 ("auto" / "horizontal" / "vertical")
            progress_callback: 进度回调
            debug_dir: 调试输出目录（可选）

        Returns:
            清洗后的文本
        """
        cb = progress_callback or (lambda *a: None)
        dbg = Path(debug_dir) if debug_dir else None

        cb("clean_script", 0, "正在加载台本文件...")
        raw_text = ScriptToSubtitleTool.load_script(script_path, vertical_mode=vertical_mode)
        if dbg:
            self._save_debug(dbg, "stage1_extract", "01_raw_text.txt", raw_text)

        # ---- 多 Track 检测 ----
        from src.core.script_processor import ScriptProcessor
        sections = ScriptProcessor.detect_scripts(raw_text)
        if len(sections) > 1:
            if track_index is not None and 0 <= track_index < len(sections):
                raw_text = sections[track_index]["text"]
                cb("clean_script", 15, f"检测到 {len(sections)} 个 Track，使用 Track {track_index + 1}: {sections[track_index]['title']}")
            else:
                titles = ", ".join(s["title"] for s in sections)
                cb("clean_script", 15, f"检测到 {len(sections)} 个 Track ({titles})，处理全部")

        cb("clean_script", 30, "正在清洗台本...")
        if use_llm_clean:
            clean_text = ScriptToSubtitleTool.clean_script_with_llm(raw_text, debug_dir=dbg)
        else:
            clean_text = ScriptToSubtitleTool.clean_script(raw_text)
        if dbg:
            self._save_debug(dbg, "stage1_clean", "02_clean_text.txt", clean_text)

        cb("clean_script", 100, f"台本清洗完成，共 {len(clean_text.splitlines())} 行台词")

        if output_path:
            Path(output_path).write_text(clean_text, encoding="utf-8")

        return clean_text
