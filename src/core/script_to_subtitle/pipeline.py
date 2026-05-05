"""
PDFToSubtitlePipeline — PDF 台本转字幕完整流水线

流程：
  fun1: PDF → 清洗后的 TXT（regex 粗洗 + LLM 精洗）
  fun2: MP3 → ASR VTT（已实现，复用 ASRRecognizer）
  fun3: 清洗 TXT + ASR VTT → LLM 智能重排对齐 → 最终 VTT
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from src.core.subtitle_generator import SubtitleGenerator
from .tool import ScriptToSubtitleTool


class PDFToSubtitlePipeline:
    """PDF 台本 → 完整字幕 流水线"""

    def run(
        self,
        pdf_path: Union[str, Path],
        audio_path: Union[str, Path],
        output_path: Union[str, Path],
        fmt: str = "vtt",
        use_llm_clean: bool = True,
        asr_model_size: str = "large-v3",
        asr_language: str = "ja",
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
    ) -> str:
        """
        完整流程：PDF + 音频 → 字幕文件。

        Args:
            pdf_path: PDF 台本路径
            audio_path: MP3/WAV 音频路径
            output_path: 输出字幕文件路径
            fmt: 输出格式 ("vtt" / "srt" / "lrc")
            use_llm_clean: 是否使用 LLM 辅助清洗
            asr_model_size: ASR 模型大小
            asr_language: ASR 语言
            progress_callback: 进度回调 fn(stage, percent, message)

        Returns:
            输出文件路径
        """
        cb = progress_callback or (lambda *a: None)

        # ---- Stage 1: fun1 - PDF → 清洗 TXT ----
        cb("fun1", 0, "正在加载 PDF 台本...")
        raw_text = ScriptToSubtitleTool.load_script(pdf_path)

        cb("fun1", 30, "正在清洗台本...")
        if use_llm_clean:
            clean_text = ScriptToSubtitleTool.clean_script_with_llm(raw_text)
        else:
            clean_text = ScriptToSubtitleTool.clean_script(raw_text)

        cb("fun1", 100, f"台本清洗完成，共 {len(clean_text.splitlines())} 行台词")

        # ---- Stage 2: fun2 - 音频 → ASR ----
        cb("fun2", 0, "正在语音识别...")
        from src.core.model_manager import get_model_manager
        asr = get_model_manager().get_asr(
            "faster_whisper",
            model_size=asr_model_size,
            language=asr_language,
        )
        asr_results = asr.recognize(
            str(audio_path),
            progress_callback=lambda pct, msg: cb("fun2", int(pct), msg),
        )
        cb("fun2", 100, f"语音识别完成，共 {len(asr_results)} 个片段")

        # ---- Stage 3: fun3 - LLM 对齐 ----
        cb("fun3", 0, "正在 LLM 智能对齐...")
        entries = ScriptToSubtitleTool.align_with_llm(clean_text, asr_results)
        cb("fun3", 80, f"对齐完成，共 {len(entries)} 条字幕")

        # ---- 保存 ----
        SubtitleGenerator.save(entries, str(output_path), fmt=fmt)
        cb("fun3", 100, f"已保存到 {output_path}")

        return str(output_path)

    def run_from_existing_vtt(
        self,
        pdf_path: Union[str, Path],
        vtt_path: Union[str, Path],
        output_path: Union[str, Path],
        fmt: str = "vtt",
        use_llm_clean: bool = True,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
    ) -> str:
        """
        已有 ASR 字幕的情况（跳过 fun2）。

        适用场景：之前已经跑过 ASR，现在只需要用台本修正字幕。

        Args:
            pdf_path: PDF 台本路径
            vtt_path: 已有的 ASR 字幕路径（VTT/SRT/LRC）
            output_path: 输出路径
            fmt: 输出格式
            use_llm_clean: 是否使用 LLM 辅助清洗
            progress_callback: 进度回调

        Returns:
            输出文件路径
        """
        cb = progress_callback or (lambda *a: None)

        # ---- fun1: PDF → 清洗 TXT ----
        cb("fun1", 0, "正在加载 PDF 台本...")
        raw_text = ScriptToSubtitleTool.load_script(pdf_path)

        cb("fun1", 30, "正在清洗台本...")
        if use_llm_clean:
            clean_text = ScriptToSubtitleTool.clean_script_with_llm(raw_text)
        else:
            clean_text = ScriptToSubtitleTool.clean_script(raw_text)

        cb("fun1", 100, f"台本清洗完成，共 {len(clean_text.splitlines())} 行台词")

        # ---- 加载已有字幕 ----
        cb("fun3", 0, "正在加载已有字幕...")
        from src.core.translate import load_subtitle_with_timestamps
        asr_results = load_subtitle_with_timestamps(str(vtt_path))
        cb("fun3", 20, f"已加载 {len(asr_results)} 个字幕片段")

        # ---- fun3: LLM 对齐 ----
        cb("fun3", 30, "正在 LLM 智能对齐...")
        entries = ScriptToSubtitleTool.align_with_llm(clean_text, asr_results)
        cb("fun3", 80, f"对齐完成，共 {len(entries)} 条字幕")

        # ---- 保存 ----
        SubtitleGenerator.save(entries, str(output_path), fmt=fmt)
        cb("fun3", 100, f"已保存到 {output_path}")

        return str(output_path)

    def run_text_only(
        self,
        pdf_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        use_llm_clean: bool = True,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
    ) -> str:
        """
        仅 fun1：PDF → 清洗后的纯文本（不做 ASR 和对齐）。

        Args:
            pdf_path: PDF 台本路径
            output_path: 输出 TXT 路径（可选）
            use_llm_clean: 是否使用 LLM 辅助清洗
            progress_callback: 进度回调

        Returns:
            清洗后的文本
        """
        cb = progress_callback or (lambda *a: None)

        cb("fun1", 0, "正在加载 PDF 台本...")
        raw_text = ScriptToSubtitleTool.load_script(pdf_path)

        cb("fun1", 30, "正在清洗台本...")
        if use_llm_clean:
            clean_text = ScriptToSubtitleTool.clean_script_with_llm(raw_text)
        else:
            clean_text = ScriptToSubtitleTool.clean_script(raw_text)

        cb("fun1", 100, f"台本清洗完成，共 {len(clean_text.splitlines())} 行台词")

        if output_path:
            Path(output_path).write_text(clean_text, encoding="utf-8")

        return clean_text
