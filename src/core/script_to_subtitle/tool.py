"""
ScriptToSubtitleTool - 台本转字幕统一工具类

将「PDF/TXT 台本 → 纯净台词 → 与 ASR 结果对齐替换 → 输出带时间轴字幕」
这一完整流程封装为统一接口，方便 GUI、CLI 及批量流水线调用。
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from src.core.subtitle_generator import SubtitleGenerator
from src.core.script_processor import ScriptProcessor

LENTICULAR_BRACKET_PATTERN = re.compile(r'【[^】]*】')


class ScriptToSubtitleTool:
    """台本转字幕统一工具类"""

    # ------------------------------------------------------------------ #
    # 1. 统一加载接口
    # ------------------------------------------------------------------ #
    @staticmethod
    def load_script(source: Union[str, Path]) -> str:
        """
        从 PDF 或 TXT 文件提取原始文本。

        Args:
            source: 文件路径（.pdf 或 .txt）

        Returns:
            提取的原始文本
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            text, _ = SubtitleGenerator._extract_pdf_text_with_pages(str(path))
            return text
        elif suffix == ".txt":
            return path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"不支持的文件格式: {suffix}，仅支持 .pdf 和 .txt")

    # ------------------------------------------------------------------ #
    # 2. 台本清洗与台词提取
    # ------------------------------------------------------------------ #
    @staticmethod
    def clean_script(raw_text: str, options: Optional[Dict[str, Any]] = None) -> str:
        """
        清洗台本：去除元数据、动作描述、页码、标题等，仅保留人物台词并拼接为纯文本。

        Args:
            raw_text: 原始台本文本
            options: 可选配置
                - filter_actions: bool = True  是否过滤动作描述
                - action_mode: str = "remove"   动作描述处理方式 ("remove"|"bracket_keep"|"keep")
                - include_character: bool = False  是否在输出中包含角色名前缀

        Returns:
            清洗后的纯台词文本
        """
        if options is None:
            options = {}

        filter_actions = options.get("filter_actions", True)
        action_mode = options.get("action_mode", "remove")
        include_character = options.get("include_character", False)
        keep_actions = not filter_actions or action_mode == "keep"

        # Step 1: 去除元数据（登场人物、あらすじ、トラックNo 等）
        text = ScriptProcessor.filter_script_metadata(raw_text)

        # Step 2: 过滤动作描述（括号内容、星号包围等）
        if filter_actions and action_mode != "keep":
            text = SubtitleGenerator.filter_stage_directions(text, mode=action_mode)
            text = LENTICULAR_BRACKET_PATTERN.sub('', text)

        # Step 3: 提取结构化台词
        dialogue_entries = ScriptProcessor.extract_dialogue(text)

        # Step 4: 拼接为纯文本
        clean_text = ScriptProcessor.to_subtitle_text(
            dialogue_entries,
            include_character=include_character,
            include_actions=keep_actions,
        )

        return clean_text

    # ------------------------------------------------------------------ #
    # 3. ASR 对齐与替换
    # ------------------------------------------------------------------ #
    @staticmethod
    def align_with_asr(
        clean_text: str,
        asr_results: List[Dict[str, Any]],
        total_duration: float,
        options: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        将清洗后的台词与 ASR 识别结果对齐，输出带时间轴的字幕条目。

        Args:
            clean_text: 清洗后的台词文本
            asr_results: ASR 识别结果 [{"start": float, "end": float, "text": str}, ...]
            total_duration: 音频总时长（秒）
            options: 可选配置
                - fmt: str = "srt"          输出格式
                - lang: str = "zh"          语言标识
                - filter_actions: bool = True
                - action_mode: str = "remove"
                - return_alignment_info: bool = False  是否返回对齐详情

        Returns:
            字幕条目列表 [{"start": float, "end": float, "text": str}, ...]
        """
        if options is None:
            options = {}

        # ASR 结果为空或无效时，回退到按字符数均匀分配时间轴
        if not asr_results:
            return SubtitleGenerator.generate_from_text(
                text=clean_text,
                total_duration=total_duration,
                fmt=options.get("fmt", "srt"),
                lang=options.get("lang", "zh"),
                filter_actions=options.get("filter_actions", True),
                action_mode=options.get("action_mode", "remove"),
            )

        return SubtitleGenerator.align_text_with_asr(
            user_text=clean_text,
            asr_results=asr_results,
            total_duration=total_duration,
            fmt=options.get("fmt", "srt"),
            lang=options.get("lang", "zh"),
            filter_actions=options.get("filter_actions", True),
            action_mode=options.get("action_mode", "remove"),
            return_alignment_info=options.get("return_alignment_info", False),
        )

    # ------------------------------------------------------------------ #
    # 4. 导出字幕文件
    # ------------------------------------------------------------------ #
    @staticmethod
    def save(entries: List[Dict[str, Any]], output_path: Union[str, Path], fmt: str = "srt") -> None:
        """
        将字幕条目保存为文件。

        Args:
            entries: 字幕条目列表
            output_path: 输出文件路径
            fmt: 输出格式 (srt/vtt/lrc)
        """
        SubtitleGenerator.save(entries, str(output_path), fmt=fmt)

    # ------------------------------------------------------------------ #
    # 5. LLM 增强方法
    # ------------------------------------------------------------------ #
    @staticmethod
    def clean_script_with_llm(
        raw_text: str,
        options: Optional[Dict[str, Any]] = None,
        debug_dir: Optional[Union[str, Path]] = None,
    ) -> str:
        """
        regex 粗洗 + LLM 精洗。

        先用 regex 去除元数据和动作描述，再用 LLM 从复杂格式中提取纯净对话。

        Args:
            raw_text: 原始台本文本
            options: 清洗选项（同 clean_script）
            debug_dir: 调试输出目录（可选）

        Returns:
            每行一句台词的纯净文本
        """
        rough_text = ScriptToSubtitleTool.clean_script(raw_text, options)
        if debug_dir:
            from pathlib import Path as P
            dbg = P(debug_dir) if not isinstance(debug_dir, Path) else debug_dir
            dbg.mkdir(parents=True, exist_ok=True)
            (dbg / "01_rough_clean.txt").write_text(rough_text, encoding="utf-8")
        try:
            from .llm_processor import LLMProcessor
            processor = LLMProcessor()
            result = processor.clean_script(rough_text, debug_dir=debug_dir)
            if debug_dir:
                (dbg / "02_llm_clean.txt").write_text(result, encoding="utf-8")
            return result
        except Exception as e:
            print(f"[ScriptToSubtitle] LLM 清洗失败，使用 regex 结果: {e}")
            return rough_text

    @staticmethod
    def align_with_llm(
        clean_text: str,
        asr_results: List[Dict[str, Any]],
        output_path: Optional[Union[str, Path]] = None,
        fmt: str = "vtt",
        debug_dir: Optional[Union[str, Path]] = None,
    ) -> List[Dict[str, Any]]:
        """
        LLM 智能重排对齐：将台本与 ASR 结果对齐，修正错字，处理顺序差异。

        Args:
            clean_text: 清洗后的台词文本（每行一句）
            asr_results: ASR 识别结果
            output_path: 输出文件路径（可选）
            fmt: 输出格式
            debug_dir: 调试输出目录（可选）

        Returns:
            字幕条目列表 [{"start": float, "end": float, "text": str}, ...]
        """
        from .llm_processor import LLMProcessor
        processor = LLMProcessor(debug_dir=debug_dir)
        script_lines = [line.strip() for line in clean_text.split('\n') if line.strip()]
        entries = processor.align_and_reorder(script_lines, asr_results)
        if output_path:
            SubtitleGenerator.save(entries, str(output_path), fmt=fmt)
        return entries

    # ------------------------------------------------------------------ #
    # 6. 一键流程（便捷方法）
    # ------------------------------------------------------------------ #
    @classmethod
    def process(
        cls,
        source: Union[str, Path],
        asr_results: Optional[List[Dict[str, Any]]] = None,
        total_duration: float = 0.0,
        output_path: Optional[Union[str, Path]] = None,
        fmt: str = "srt",
        options: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        一键完成「加载 → 清洗 → 对齐 → 保存」完整流程。

        Args:
            source: 台本文件路径（PDF/TXT）
            asr_results: ASR 识别结果（可选）
            total_duration: 音频总时长（秒）
            output_path: 输出文件路径（可选）
            fmt: 输出格式
            options: 清洗/对齐配置

        Returns:
            字幕条目列表
        """
        raw_text = cls.load_script(source)
        clean_text = cls.clean_script(raw_text, options)
        entries = cls.align_with_asr(clean_text, asr_results or [], total_duration, options)

        if output_path:
            cls.save(entries, output_path, fmt=fmt)

        return entries
