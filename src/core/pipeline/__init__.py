"""
流水线模块 - 统一调度 ASMR 处理流程

功能：
1. 串联人声分离、ASR、翻译、TTS、混音
2. 支持多种预设流程（asmr_bilingual, auto_subtitle 等）
3. DAG 任务调度
"""

import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal, Callable
from dataclasses import dataclass, field
from enum import Enum

from ..vocal_separator import VocalSeparator
from ..asr import ASRRecognizer
from ..translate import Translator
from ..tts import TTSEngine
from src.mixer import Mixer
from src.utils import ensure_dir
import soundfile as sf


@dataclass
class PipelineConfig:
    """流水线配置"""

    # 输入输出
    input_path: str = ""
    output_dir: str = ""
    vtt_path: Optional[str] = None  # 字幕文件路径（优先翻译此文件）

    # 人声分离
    use_vocal_separator: bool = True
    vocal_model: str = "htdemucs"

    # ASR
    use_asr: bool = True
    asr_model: str = "base"
    asr_language: str = "ja"

    # 翻译
    use_translate: bool = True
    translate_provider: str = "deepseek"
    translate_model: str = "deepseek-chat"
    source_lang: str = "日文"
    target_lang: str = "中文"

    # TTS
    use_tts: bool = True
    tts_engine: str = "edge"
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    qwen3_voice: str = "Vivian"
    voice_profile_id: Optional[str] = None  # 音色配置 ID
    tts_speed: float = 1.0  # Qwen3 语速（注：当前 qwen_tts 0.1.1 不支持 speed 参数，保留供未来使用）
    max_tts_ratio: float = 1.2  # TTS 超过原音频此时长的比例阈值（超过则压缩）
    compress_ratio: float = 0.75  # 固定压缩 stretch_factor（1/0.75 = 1.33x 压缩）

    # 混音
    use_mixer: bool = True
    original_volume: float = 0.85
    tts_volume_ratio: float = 0.5
    tts_delay_ms: float = 0

    # 高级
    skip_existing: bool = False

    # 输出模式 (报告 report_16)
    output_mode: str = "single"  # "single" | "batch"
    batch_root_dir: str = ""     # 批量模式下的根目录（Main_Product/ 和 BY_Product/ 在此目录下）

    # ===== 步骤解耦输出模式 =====
    # "full"          -> 完整 5 步 (默认, 向后兼容)
    # "asr_only"      -> 仅 ASR (自动跳过翻译/TTS/混音)
    # "subtitle_only" -> ASR + 翻译 + 导出字幕文件
    # "tts_only"      -> ASR + 翻译 + TTS (不混音)
    # "custom"        -> 严格按 use_* 布尔开关决定
    pipeline_mode: str = "full"
    export_subtitle_format: str = "srt"  # srt | vtt | lrc

    # 字幕清理 (report_18)
    clean_subtitle: bool = True  # 是否清理字幕（删除拟声词、说话人名字）
    clean_sound_effects: bool = True  # 删除拟声词
    clean_speaker_names: bool = True  # 删除说话人名字


class Pipeline:
    """处理流水线"""

    PRESETS = {
        "asmr_bilingual": "ASMR 双语双轨（人声分离 + ASR + 翻译 + TTS + 混音）",
        "asr_only": "仅 ASR 识别",
        "translate_only": "仅翻译文本",
        "tts_only": "仅 TTS 合成",
        "auto_subtitle": "自动字幕（ASR + 翻译）",
    }

    def __init__(self, config: PipelineConfig,
                 separator=None, recognizer=None,
                 translator=None, tts_engine=None, mixer=None):
        """
        初始化流水线（支持依赖注入）

        Args:
            config: 流水线配置
            separator: 人声分离器实例（可选，默认自动创建）
            recognizer: ASR 识别器实例（可选，默认自动创建）
            translator: 翻译器实例（可选，默认自动创建）
            tts_engine: TTS 引擎实例（可选，默认自动创建）
            mixer: 混音器实例（可选，默认自动创建）
        """
        self.config = config
        self.steps = []
        self.results = {}

        # 依赖注入的组件（支持外部传入，便于测试和复用）
        self._injected_separator = separator
        self._injected_recognizer = recognizer
        self._injected_translator = translator
        self._injected_tts_engine = tts_engine
        self._injected_mixer = mixer

    @classmethod
    def create_from_config(cls, config: PipelineConfig) -> "Pipeline":
        """工厂方法，从配置创建（保持向后兼容）"""
        return cls(config=config)

    def _resolve_output_dirs(self) -> tuple:
        """
        统一解析输出目录（按 report_16 修复）

        单文件模式结构:
            {name}_output/
            ├── {name}_mix.{ext}      # 成品
            └── BY_Product/           # 中间文件
                ├── vocal.wav
                └── ...

        批量模式结构:
            root_output/
            ├── Main_Product/         # 所有成品
            │   └── {name}_mix.{ext}
            └── BY_Product/           # 中间文件
                └── {name}_by/
                    └── ...

        Returns:
            (mix_path, by_product_dir, task_name)
        """
        config = self.config
        input_path = Path(config.input_path)
        task_name = input_path.stem
        input_ext = input_path.suffix  # 保留原始音频后缀

        if config.output_mode == "batch" and config.batch_root_dir:
            # 批量模式
            root_dir = Path(config.batch_root_dir)
            main_product_dir = root_dir / "Main_Product"
            by_product_dir = root_dir / "BY_Product" / f"{task_name}_by"
        else:
            # 单文件模式
            if config.output_dir:
                base_dir = Path(config.output_dir)
            else:
                base_dir = input_path.parent / f"{task_name}_output"
            main_product_dir = base_dir
            by_product_dir = base_dir / "BY_Product"

        # 成品路径: <name>_mix.<ext> (输出格式与输入格式一致)
        mix_path = main_product_dir / f"{task_name}_mix{input_ext}"

        ensure_dir(main_product_dir)
        ensure_dir(by_product_dir)

        return mix_path, by_product_dir, task_name

    def _resolve_active_steps(self, has_subtitle: bool, is_chinese_subtitle: bool) -> List[str]:
        """
        根据配置和输入条件确定实际执行的步骤列表

        Args:
            has_subtitle: 是否有字幕文件
            is_chinese_subtitle: 字幕是否为中文

        Returns:
            如 ["vocal_separator", "asr", "translate"]
        """
        config = self.config
        mode = config.pipeline_mode

        if mode == "full":
            # 完整模式：与现在行为一致（智能跳过的步骤由字幕条件决定）
            steps = ["vocal_separator", "asr", "translate", "tts", "mixer"]
            return steps

        elif mode == "asr_only":
            # 仅 ASR：只做分离 + ASR
            steps = []
            if config.use_vocal_separator:
                steps.append("vocal_separator")
            if config.use_asr:
                steps.append("asr")
            return steps

        elif mode == "subtitle_only":
            # ASR + 翻译 + 导出字幕
            steps = []
            if config.use_vocal_separator:
                steps.append("vocal_separator")
            if config.use_asr:
                steps.append("asr")
            if config.use_translate and not is_chinese_subtitle:
                steps.append("translate")
            return steps

        elif mode == "tts_only":
            # ASR + 翻译 + TTS（不混音）
            steps = []
            if config.use_vocal_separator:
                steps.append("vocal_separator")
            steps.extend(["asr", "translate", "tts"])
            return steps

        elif mode == "custom":
            # 严格按开关
            steps = []
            if config.use_vocal_separator:
                steps.append("vocal_separator")
            if config.use_asr:
                steps.append("asr")
            if config.use_translate:
                steps.append("translate")
            if config.use_tts:
                steps.append("tts")
            if config.use_mixer:
                steps.append("mixer")
            return steps

        else:
            # 未知模式，降级为 full
            return ["vocal_separator", "asr", "translate", "tts", "mixer"]

    def _export_subtitles(
        self,
        segments: List[Dict],
        translations: Optional[List[str]],
        output_dir: Path,
        fmt: str,
        task_name: str,
        subtitle_lang: str = "ja",
    ) -> Optional[Path]:
        """
        将 timestamped_segments 导出为结构化字幕文件

        Args:
            segments: 时间戳段落列表
            translations: 翻译文本列表 (可选，为 None 时仅导出日语)
            output_dir: 输出目录
            fmt: 格式 (srt | vtt | lrc)
            task_name: 任务名称 (用于文件名)
            subtitle_lang: 字幕语言描述

        Returns:
            导出的文件路径，或 None (格式不支持)
        """
        if not segments:
            return None

        base_name = f"{task_name}_subtitle"

        if fmt == "srt":
            path = output_dir / f"{base_name}.srt"
            content = self._build_srt(segments, translations)
        elif fmt == "vtt":
            path = output_dir / f"{base_name}.vtt"
            content = self._build_vtt(segments, translations)
        elif fmt == "lrc":
            path = output_dir / f"{base_name}.lrc"
            content = self._build_lrc(segments, translations)
        else:
            return None

        path.write_text(content, encoding="utf-8")
        return path

    def _build_srt(self, segments: List[Dict], translations: Optional[List[str]]) -> str:
        """构建 SRT 格式字幕"""
        lines = []
        for i, seg in enumerate(segments, 1):
            start = self._format_timestamp(seg["start"], fmt="srt")
            end = self._format_timestamp(seg["end"], fmt="srt")
            text = seg.get("text", "")
            translation = seg.get("translation", "") if translations else ""

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            if translation:
                lines.append(f"{text}")
                lines.append(f"{translation}")
            else:
                lines.append(f"{text}")
            lines.append("")
        return "\n".join(lines)

    def _build_vtt(self, segments: List[Dict], translations: Optional[List[str]]) -> str:
        """构建 VTT 格式字幕"""
        lines = ["WEBVTT", ""]
        for seg in segments:
            start = self._format_timestamp(seg["start"], fmt="vtt")
            end = self._format_timestamp(seg["end"], fmt="vtt")
            text = seg.get("text", "")
            translation = seg.get("translation", "") if translations else ""

            lines.append(f"{start} --> {end}")
            if translation:
                lines.append(f"{text}")
                lines.append(f"{translation}")
            else:
                lines.append(f"{text}")
            lines.append("")
        return "\n".join(lines)

    def _build_lrc(self, segments: List[Dict], translations: Optional[List[str]]) -> str:
        """构建 LRC 格式字幕"""
        lines = []
        for seg in segments:
            start_ms = int(seg["start"] * 1000)
            minutes = start_ms // 60000
            seconds = (start_ms % 60000) // 1000
            centiseconds = start_ms % 1000
            timestamp = f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]"

            text = seg.get("text", "")
            translation = seg.get("translation", "") if translations else ""

            if translation:
                lines.append(f"{timestamp}{text}")
                lines.append(f"{timestamp}{translation}")
            else:
                lines.append(f"{timestamp}{text}")
        return "\n".join(lines)

    @staticmethod
    def _format_timestamp(seconds: float, fmt: str = "srt") -> str:
        """格式化时间戳"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)

        if fmt == "srt":
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        else:  # vtt
            return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

    def run(
        self,
        preset: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        运行流水线（支持 VTT 智能跳过）

        智能流程选择：
        - 有中文 VTT → Step1(分离) + Step4(TTS) + Step5(混音) = 3步，省 51s
        - 有日文 VTT → Step1(分离) + Step3(翻译VTT) + Step4(TTS) + Step5(混音) = 4步，省 23s
        - 无 VTT → Step1~5 = 5步（完整流程）

        Args:
            preset: 预设流程名称
            progress_callback: 进度回调函数（接收消息字符串），供 GUI 实时显示

        Returns:
            Dict: 处理结果
        """
        import torch  # 延迟导入，避免顶层依赖

        from ..translate import (
            load_subtitle_translations,
            load_subtitle_with_timestamps,
            detect_subtitle_language,
            load_and_clean_subtitle,
        )

        config = self.config
        input_path = Path(config.input_path)

        # 统一解析输出目录（按 report_16 修复）
        mix_path, by_product_dir, task_name = self._resolve_output_dirs()

        def _report(msg: str):
            """内部进度报告（打印 + 回调）"""
            print(msg)
            if progress_callback:
                progress_callback(msg)

        # ===== 字幕预检测 (支持 VTT / SRT / LRC) =====
        subtitle_path = config.vtt_path  # 字段名保持 vtt_path，实际支持多种格式
        subtitle_translations = None
        subtitle_lang = None
        has_subtitle = False
        is_chinese_subtitle = False

        if subtitle_path and Path(subtitle_path).exists():
            subtitle_translations = load_subtitle_translations(subtitle_path)
            if subtitle_translations:
                # 字幕清理（删除拟声词、说话人名字）
                if config.clean_subtitle:
                    from ..translate import clean_subtitle_batch
                    subtitle_translations = clean_subtitle_batch(
                        subtitle_translations,
                        clean_sound_effects=config.clean_sound_effects,
                        clean_speaker_names=config.clean_speaker_names,
                    )
                subtitle_lang = detect_subtitle_language(subtitle_translations)
                has_subtitle = True
                is_chinese_subtitle = subtitle_lang == "zh"

        # ===== 步骤解析 (支持 pipeline_mode 解耦) =====
        # 获取字幕格式描述
        subtitle_ext = Path(subtitle_path).suffix.upper() if subtitle_path else ""
        subtitle_type = subtitle_ext.lstrip(".") or "VTT"

        # 根据 pipeline_mode 解析实际执行的步骤
        active_steps = self._resolve_active_steps(has_subtitle, is_chinese_subtitle)
        total_steps = len(active_steps)
        current_step = 0

        # 为 full 模式注入智能跳过步骤（保持与原来一致的步骤显示逻辑）
        if config.pipeline_mode == "full":
            # full 模式下，字幕触发跳过但仍计入步骤数
            display_steps = ["vocal_separator"]
            if not has_subtitle:
                display_steps.append("asr")
            if not is_chinese_subtitle:
                display_steps.append("translate")
            display_steps.extend(["tts", "mixer"])
            total_steps = len(display_steps)

        _report("=" * 60)
        _report(f"ASMR Helper 流水线")
        _report(f"预设: {preset or 'custom'}")
        _report(f"输入: {input_path}")
        _report(f"成品: {mix_path.parent}/{mix_path.name}")
        _report(f"中间: {by_product_dir}/")
        if has_subtitle:
            _report(f"字幕: {Path(subtitle_path).name} ({subtitle_type}格式, 语言: {subtitle_lang})")
        _report(f"流程: {total_steps} 步 [{config.pipeline_mode}]" + (" (智能跳过优化)" if (has_subtitle and config.pipeline_mode == "full") else ""))
        _report("=" * 60)

        results = {
            "input": str(input_path),
            "output_dir": str(by_product_dir),
            "mix_path": str(mix_path),
            "steps": {},
            "subtitle_lang": subtitle_lang,  # 保持 vtt_lang 字段名兼容
            "subtitle_type": subtitle_type,
            "total_steps": total_steps,
        }

        t0 = time.time()

        # ===== Step 1: 人声分离 =====
        if "vocal_separator" not in active_steps:
            # 不执行分离，直接使用原音频
            results["vocal_path"] = str(input_path)
            if has_subtitle:
                _report(f"[1/{total_steps}] [跳过] 人声分离 (有{subtitle_type}字幕，直接使用原音频)")
                results["steps"]["vocal_separator"] = {"duration": 0, "skipped": True, "source": "original"}
            else:
                _report(f"[1/{total_steps}] [跳过] 人声分离 (直接使用输入文件)")
        elif config.use_vocal_separator:
            vocal_path = by_product_dir / "vocal.wav"
            current_step += 1
            if config.skip_existing and vocal_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] 人声分离已存在: {vocal_path.name}")
            else:
                _report("")
                _report(f"[{current_step}/{total_steps}] 人声分离 (Demucs)...")
                t1 = time.time()

                try:
                    # 使用注入的组件或创建新实例
                    if self._injected_separator is not None:
                        separator = self._injected_separator
                    else:
                        separator = VocalSeparator(model_name=config.vocal_model)

                    sep_results = separator.separate(
                        str(input_path),
                        str(by_product_dir),
                        stems=["vocals"],
                    )
                    vocal_path = Path(sep_results.get("vocals", ""))

                    results["steps"]["vocal_separator"] = {
                        "duration": time.time() - t1,
                        "output": str(vocal_path),
                    }
                except Exception as e:
                    # 降级：使用原音作为人声
                    _report(f"[WARN] 人声分离失败，使用原音: {e}")
                    results["steps"]["vocal_separator"] = {
                        "error": str(e),
                        "recoverable": True,
                    }
                    vocal_path = input_path
                finally:
                    # 释放 Demucs 模型显存
                    if self._injected_separator is None and 'separator' in locals():
                        del separator
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

            results["vocal_path"] = str(vocal_path)
        else:
            results["vocal_path"] = str(input_path)

        # ===== Step 2: 时间戳获取 (ASR 或字幕) =====
        asr_text_path = by_product_dir / "asr_result.txt"
        asr_results = []
        timestamped_segments = []  # [{start, end, text, translation}, ...] 贯穿整个流程

        if "asr" not in active_steps:
            # 不执行 ASR：从字幕加载时间戳
            if has_subtitle:
                current_step += 1
                _report(f"[{current_step}/{total_steps}] [跳过] ASR (使用{subtitle_type}字幕时间戳)")

                # 加载并清理字幕
                if config.clean_subtitle:
                    subtitle_entries = load_and_clean_subtitle(
                        subtitle_path,
                        clean_sound_effects=config.clean_sound_effects,
                        clean_speaker_names=config.clean_speaker_names,
                    )
                else:
                    subtitle_entries = load_subtitle_with_timestamps(subtitle_path)

                timestamped_segments = [
                    {"start": e["start"], "end": e["end"], "text": e["text"]}
                    for e in subtitle_entries
                ]
                results["steps"]["asr"] = {"duration": 0, "skipped": True, "source": subtitle_type.lower(), "segments": len(timestamped_segments), "cleaned": config.clean_subtitle}
        elif has_subtitle:
            # 有字幕但需做 ASR（pipeline_mode != full 时）
            current_step += 1
            _report(f"[{current_step}/{total_steps}] [跳过] ASR (使用{subtitle_type}字幕时间戳)")

            if config.clean_subtitle:
                subtitle_entries = load_and_clean_subtitle(
                    subtitle_path,
                    clean_sound_effects=config.clean_sound_effects,
                    clean_speaker_names=config.clean_speaker_names,
                )
            else:
                subtitle_entries = load_subtitle_with_timestamps(subtitle_path)

            timestamped_segments = [
                {"start": e["start"], "end": e["end"], "text": e["text"]}
                for e in subtitle_entries
            ]
            results["steps"]["asr"] = {"duration": 0, "skipped": True, "source": subtitle_type.lower(), "segments": len(timestamped_segments), "cleaned": config.clean_subtitle}
        else:
            # 无字幕，正常执行 ASR
            current_step += 1
            if config.skip_existing and asr_text_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] ASR 已存在: {asr_text_path.name}")
                for line in asr_text_path.read_text(encoding="utf-8").split("\n"):
                    if line.strip() and not line.startswith("["):
                        asr_results.append({"text": line.strip()})
            else:
                _report("")
                _report(f"[{current_step}/{total_steps}] ASR 语音识别 (Whisper)...")
                t1 = time.time()

                try:
                    if self._injected_recognizer is not None:
                        recognizer = self._injected_recognizer
                    else:
                        recognizer = ASRRecognizer(
                            model_size=config.asr_model,
                            language=config.asr_language,
                        )

                    asr_results = recognizer.recognize(
                        results["vocal_path"],
                        str(asr_text_path),
                    )

                    # 保留时间戳信息
                    timestamped_segments = asr_results.copy()

                    results["steps"]["asr"] = {
                        "duration": time.time() - t1,
                        "segments": len(asr_results),
                        "output": str(asr_text_path),
                    }
                except Exception as e:
                    _report(f"[WARN] ASR 识别失败: {e}")
                    results["steps"]["asr"] = {
                        "error": str(e),
                        "recoverable": True,
                    }
                    asr_results = []
                    timestamped_segments = []
                finally:
                    # 释放 Whisper 模型显存
                    if self._injected_recognizer is None and 'recognizer' in locals():
                        del recognizer
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

            # ===== ASR 后导出字幕 (非 full 模式) =====
            if config.pipeline_mode != "full" and "translate" not in active_steps:
                # asr_only 模式：ASR 后直接导出字幕
                exported_path = self._export_subtitles(
                    segments=timestamped_segments,
                    translations=None,
                    output_dir=by_product_dir,
                    fmt=config.export_subtitle_format,
                    task_name=task_name,
                    subtitle_lang="ja",
                )
                if exported_path:
                    _report(f"[导出] 字幕文件: {exported_path.name}")
                    results["exported_subtitle"] = str(exported_path)

        results["asr_results"] = asr_results
        results["timestamped_segments"] = timestamped_segments

        # ===== Step 3: 翻译 (保留时间戳) =====
        translated_path = by_product_dir / "translated.txt"
        translations = []

        if "translate" not in active_steps:
            # 不执行翻译（asr_only 模式或有中文字幕时）
            if is_chinese_subtitle:
                current_step += 1
                translations = subtitle_translations
                translated_path.write_text("\n".join(translations), encoding="utf-8")
                _report(f"[{current_step}/{total_steps}] [跳过] 翻译 ({subtitle_type}字幕已是中文，{len(translations)} 条)")
                for seg, trans in zip(timestamped_segments, translations):
                    seg["translation"] = trans
                results["steps"]["translate"] = {
                    "duration": 0.0,
                    "segments": len(translations),
                    "source": f"{subtitle_type.lower()}_zh",
                    "skipped": True,
                    "output": str(translated_path),
                }
        elif is_chinese_subtitle:
            # 中文字幕：已是翻译结果，直接使用
            current_step += 1
            translations = subtitle_translations
            translated_path.write_text("\n".join(translations), encoding="utf-8")
            _report(f"[{current_step}/{total_steps}] [跳过] 翻译 ({subtitle_type}字幕已是中文，{len(translations)} 条)")

            # 为 timestamped_segments 填充 translation 字段
            for seg, trans in zip(timestamped_segments, translations):
                seg["translation"] = trans

            results["steps"]["translate"] = {
                "duration": 0.0,
                "segments": len(translations),
                "source": f"{subtitle_type.lower()}_zh",
                "skipped": True,
                "output": str(translated_path),
            }

            # ===== 翻译后导出字幕 (非 full 模式) =====
            if config.pipeline_mode != "full" and "tts" not in active_steps:
                exported_path = self._export_subtitles(
                    segments=timestamped_segments,
                    translations=translations,
                    output_dir=by_product_dir,
                    fmt=config.export_subtitle_format,
                    task_name=task_name,
                    subtitle_lang="zh",
                )
                if exported_path:
                    _report(f"[导出] 字幕文件: {exported_path.name}")
                    results["exported_subtitle"] = str(exported_path)
        elif has_subtitle and subtitle_lang in ("ja", "mixed"):
            # 日文/混合字幕：需要翻译
            current_step += 1
            _report("")
            _report(f"[{current_step}/{total_steps}] 翻译 ({subtitle_type} {subtitle_lang} -> 中文)...")
            t1 = time.time()

            try:
                if self._injected_translator is not None:
                    translator = self._injected_translator
                else:
                    translator = Translator(provider=config.translate_provider, model=config.translate_model)

                translations = translator.translate_batch(
                    subtitle_translations,
                    source_lang="日文",
                    target_lang="中文",
                )
                translated_path.write_text("\n".join(translations), encoding="utf-8")

                results["steps"]["translate"] = {
                    "duration": time.time() - t1,
                    "segments": len(translations),
                    "source": f"{subtitle_type.lower()}_ja",
                    "output": str(translated_path),
                }
            except Exception as e:
                _report(f"[WARN] 翻译失败，使用原文: {e}")
                results["steps"]["translate"] = {
                    "error": str(e),
                    "recoverable": True,
                }
                translations = subtitle_translations  # 降级：使用原文

            # 为 timestamped_segments 填充 translation 字段
            for seg, trans in zip(timestamped_segments, translations):
                seg["translation"] = trans

            # ===== 翻译后导出字幕 (非 full 模式) =====
            if config.pipeline_mode != "full" and "tts" not in active_steps:
                exported_path = self._export_subtitles(
                    segments=timestamped_segments,
                    translations=translations,
                    output_dir=by_product_dir,
                    fmt=config.export_subtitle_format,
                    task_name=task_name,
                    subtitle_lang="ja",
                )
                if exported_path:
                    _report(f"[导出] 字幕文件: {exported_path.name}")
                    results["exported_subtitle"] = str(exported_path)
        elif config.use_translate and asr_results:
            # 无 VTT：正常 ASR + 翻译
            current_step += 1
            if config.skip_existing and translated_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] 翻译已存在: {translated_path.name}")
                translations = [
                    line for line in translated_path.read_text(encoding="utf-8").split("\n")
                    if line.strip()
                ]
            else:
                _report("")
                _report(f"[{current_step}/{total_steps}] 翻译 (DeepSeek)...")
                t1 = time.time()

                try:
                    if self._injected_translator is not None:
                        translator = self._injected_translator
                    else:
                        translator = Translator(provider=config.translate_provider, model=config.translate_model)

                    texts = [r["text"] for r in asr_results]
                    translations = translator.translate_batch(
                        texts,
                        source_lang=config.source_lang,
                        target_lang=config.target_lang,
                    )

                    translated_path.write_text("\n".join(translations), encoding="utf-8")

                    results["steps"]["translate"] = {
                        "duration": time.time() - t1,
                        "segments": len(translations),
                        "source": "api",
                        "output": str(translated_path),
                    }
                except Exception as e:
                    _report(f"[WARN] 翻译失败，使用原文: {e}")
                    results["steps"]["translate"] = {
                        "error": str(e),
                        "recoverable": True,
                    }
                    translations = [r["text"] for r in asr_results]  # 降级：使用原文

            # 为 timestamped_segments 填充 translation 字段
            for seg, trans in zip(timestamped_segments, translations):
                seg["translation"] = trans

            # ===== 翻译后导出字幕 (非 full 模式) =====
            if config.pipeline_mode != "full" and "tts" not in active_steps:
                exported_path = self._export_subtitles(
                    segments=timestamped_segments,
                    translations=translations,
                    output_dir=by_product_dir,
                    fmt=config.export_subtitle_format,
                    task_name=task_name,
                    subtitle_lang="ja",
                )
                if exported_path:
                    _report(f"[导出] 字幕文件: {exported_path.name}")
                    results["exported_subtitle"] = str(exported_path)

        results["translations"] = translations

        # ===== Step 4: TTS 合成 + 时间轴对齐 =====
        tts_aligned_path = by_product_dir / "tts_aligned.wav"
        # TTS 中间文件统一使用 .wav 格式，避免 mp3 残留问题

        if "tts" not in active_steps:
            results["tts_path"] = ""
            if timestamped_segments:
                # 有时间轴但不在 active_steps 中，说明是 tts_only 前的步骤
                pass
        elif config.use_tts and timestamped_segments:
            current_step += 1
            if config.skip_existing and tts_aligned_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] TTS 已存在: {tts_aligned_path.name}")
            else:
                _report("")
                _report(f"[{current_step}/{total_steps}] TTS 逐句合成 + 时间轴对齐...")
                t1 = time.time()

                try:
                    # 获取参考音频时长
                    ref_info = sf.info(str(results["vocal_path"]))
                    ref_duration = ref_info.duration
                    sample_rate = ref_info.samplerate

                    # 使用注入的 TTS 引擎或创建新实例
                    if self._injected_tts_engine is not None:
                        tts_engine = self._injected_tts_engine
                    else:
                        tts_engine = TTSEngine(
                            engine=config.tts_engine,
                            voice=config.tts_voice if config.tts_engine == "edge" else config.qwen3_voice,
                            speed=config.tts_speed,
                            voice_profile_id=config.voice_profile_id,
                        )

                    # 使用注入的混音器或创建新实例
                    if self._injected_mixer is not None:
                        mixer = self._injected_mixer
                    else:
                        mixer = Mixer(
                            original_volume=config.original_volume,
                            tts_volume_ratio=config.tts_volume_ratio,
                            tts_delay_ms=config.tts_delay_ms,
                        )

                    mixer.build_aligned_tts(
                        segments=timestamped_segments,
                        tts_engine=tts_engine.engine,  # 传入底层引擎
                        output_path=str(tts_aligned_path),
                        reference_duration=ref_duration,
                        sample_rate=sample_rate,
                        max_tts_ratio=config.max_tts_ratio,
                        compress_ratio=config.compress_ratio,
                    )

                    results["steps"]["tts"] = {
                        "duration": time.time() - t1,
                        "output": str(tts_aligned_path),
                        "aligned": True,
                        "segments": len(timestamped_segments),
                    }
                    results["tts_path"] = str(tts_aligned_path)
                except Exception as e:
                    _report(f"[WARN] TTS 合成失败: {e}")
                    results["steps"]["tts"] = {
                        "error": str(e),
                        "recoverable": True,
                    }
                    results["tts_path"] = ""
        else:
            results["tts_path"] = ""

        # ===== Step 5: 混音 =====
        # 成品命名: <name>_mix.<ext>（已经在 _resolve_output_dirs 中计算好）

        # 确定混音用的原音频（有 VTT 时用原音频，否则用人声分离的结果）
        use_vocal = results.get("steps", {}).get("vocal_separator", {}).get("source") != "original"
        original_for_mix = results["vocal_path"] if use_vocal else str(input_path)
        mix_source_note = "人声分离结果" if use_vocal else "原音频"

        if "mixer" not in active_steps:
            results["mix_path"] = ""
        elif config.use_mixer and results.get("tts_path"):
            current_step += 1
            if config.skip_existing and mix_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] 混音已存在: {mix_path.name}")
            else:
                _report("")
                _report(f"[{current_step}/{total_steps}] 混音 -> {mix_path.name}")
                _report(f"  (原音: {mix_source_note}, 中间文件: {by_product_dir.name}/)")
                t1 = time.time()

                try:
                    # 使用注入的混音器或创建新实例
                    if self._injected_mixer is not None:
                        mixer = self._injected_mixer
                    else:
                        mixer = Mixer(
                            original_volume=config.original_volume,
                            tts_volume_ratio=config.tts_volume_ratio,
                            tts_delay_ms=config.tts_delay_ms,
                        )
                    mixer.mix(
                        original_for_mix,
                        results["tts_path"],
                        str(mix_path),
                        adjust_tts_volume=True,
                    )

                    results["steps"]["mixer"] = {
                        "duration": time.time() - t1,
                        "output": str(mix_path),
                    }
                    results["mix_path"] = str(mix_path)
                except Exception as e:
                    _report(f"[WARN] 混音失败: {e}")
                    results["steps"]["mixer"] = {
                        "error": str(e),
                        "recoverable": True,
                    }
                    # 降级：使用 TTS 输出作为最终输出
                    results["mix_path"] = results.get("tts_path", "")
        else:
            results["mix_path"] = ""

        # ===== 总结 =====
        total_time = time.time() - t0
        _report("")
        _report("=" * 60)
        _report(f"流水线完成! 总耗时: {total_time:.1f}s")
        if has_subtitle:
            saved = 23 if is_chinese_subtitle else 0
            saved += 23 if (has_subtitle and not is_chinese_subtitle) else 0
            if saved > 0:
                _report(f"(相比无字幕流程节省约 {saved}s)")
        _report("=" * 60)

        for step, data in results["steps"].items():
            if data.get("skipped"):
                _report(f"  {step}: [跳过]")
            elif data.get("error"):
                _report(f"  {step}: [错误] {data['error']} (可恢复: {data.get('recoverable', False)})")
            else:
                _report(f"  {step}: {data.get('duration', 0):.1f}s")

        _report("")
        _report("输出文件:")
        if results.get("mix_path"):
            _report(f"  [成品] {mix_path}")
        if results.get("exported_subtitle"):
            _report(f"  [字幕] {results['exported_subtitle']}")
        _report(f"  [中间] {by_product_dir}/")
        # 显示关键中间文件
        if results.get("translations"):
            _report(f"          - 翻译: {translated_path.name}")
        if results.get("vocal_path") and "vocal_separator" in results.get("steps", {}):
            if results["steps"]["vocal_separator"].get("source") != "original":
                _report(f"          - 人声: {Path(results['vocal_path']).name}")

        return results


# 便捷函数
def run_preset(
    preset: str,
    input_path: str,
    output_dir: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """运行预设流水线"""
    config = PipelineConfig(input_path=input_path, output_dir=output_dir, **kwargs)
    pipeline = Pipeline(config)
    return pipeline.run(preset=preset)
