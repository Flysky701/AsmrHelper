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


# 步骤名称常量
STEP_NAMES = ["separation", "asr", "translate", "tts", "mix"]

# 步骤显示名称
STEP_DISPLAY_NAMES = {
    "separation": "人声分离",
    "asr": "ASR识别",
    "translate": "翻译",
    "tts": "TTS合成",
    "mix": "智能混音",
}

# 步骤依赖关系：哪些步骤必须在某步骤之前完成
STEP_DEPENDENCIES = {
    "separation": [],  # 无依赖
    "asr": ["separation"],  # 需要人声
    "translate": ["asr"],  # 需要ASR结果
    "tts": ["translate"],  # 需要翻译
    "mix": ["tts"],  # 需要TTS
}


@dataclass
class PipelineState:
    """
    流水线状态数据类 - 用于步骤间传递数据

    Attributes:
        input_path: 输入音频路径
        by_product_dir: 中间文件目录
        mix_path: 最终成品路径
        vocal_path: 人声文件路径
        asr_results: ASR识别结果列表 [{start, end, text}, ...]
        translations: 翻译结果列表
        timestamped_segments: 带时间轴的字幕数据 [{start, end, text, translation}, ...]
        tts_path: TTS合成结果路径
        mix_output_path: 混音输出路径
        subtitle_path: 字幕文件路径
        subtitle_lang: 字幕语言
        cloned_profile_id: 克隆音色ID
    """
    # 输入输出路径
    input_path: str = ""
    by_product_dir: str = ""
    mix_path: str = ""

    # 步骤输出
    vocal_path: str = ""
    asr_results: List[Dict[str, Any]] = field(default_factory=list)
    translations: List[str] = field(default_factory=list)
    timestamped_segments: List[Dict[str, Any]] = field(default_factory=list)
    tts_path: str = ""
    mix_output_path: str = ""

    # 元数据
    subtitle_path: Optional[str] = None
    subtitle_lang: Optional[str] = None
    cloned_profile_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 checkpoint 序列化）"""
        return {
            "input_path": self.input_path,
            "by_product_dir": self.by_product_dir,
            "mix_path": self.mix_path,
            "vocal_path": self.vocal_path,
            "asr_results": self.asr_results,
            "translations": self.translations,
            "timestamped_segments": self.timestamped_segments,
            "tts_path": self.tts_path,
            "mix_output_path": self.mix_output_path,
            "subtitle_path": self.subtitle_path,
            "subtitle_lang": self.subtitle_lang,
            "cloned_profile_id": self.cloned_profile_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineState":
        """从字典恢复（用于 checkpoint 反序列化）"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class StepDependencyError(Exception):
    """步骤依赖错误"""
    pass

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

    # 音色克隆 (report_17)
    clone_voice_after_separation: bool = False  # 人声分离后自动克隆音色
    clone_voice_name: str = ""  # 克隆音色名称（留空则自动生成）

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

    def _check_step_dependencies(
        self,
        step_name: str,
        state: PipelineState,
    ) -> None:
        """
        检查步骤依赖是否满足

        Args:
            step_name: 步骤名称
            state: 当前流水线状态

        Raises:
            StepDependencyError: 依赖不满足时抛出
        """
        required_deps = STEP_DEPENDENCIES.get(step_name, [])

        for dep in required_deps:
            if dep == "separation" and not state.vocal_path:
                raise StepDependencyError(
                    f"步骤 '{step_name}' 需要先完成 'separation' 步骤"
                )
            elif dep == "asr" and not state.asr_results:
                raise StepDependencyError(
                    f"步骤 '{step_name}' 需要先完成 'asr' 步骤"
                )
            elif dep == "translate" and not state.translations:
                raise StepDependencyError(
                    f"步骤 '{step_name}' 需要先完成 'translate' 步骤"
                )
            elif dep == "tts" and not state.tts_path:
                raise StepDependencyError(
                    f"步骤 '{step_name}' 需要先完成 'tts' 步骤"
                )

    def _get_existing_intermediates(self, by_product_dir: Path) -> Dict[str, Any]:
        """
        检测已存在的中间文件

        Args:
            by_product_dir: 中间文件目录

        Returns:
            包含已存在文件信息的字典
        """
        intermediates = {}

        vocal_path = by_product_dir / "vocal.wav"
        if vocal_path.exists():
            intermediates["vocal_path"] = str(vocal_path)

        asr_path = by_product_dir / "asr_result.txt"
        if asr_path.exists():
            intermediates["asr_path"] = str(asr_path)
            # 读取 ASR 结果
            asr_results = []
            for line in asr_path.read_text(encoding="utf-8").split("\n"):
                if line.strip() and not line.startswith("["):
                    asr_results.append({"text": line.strip()})
            intermediates["asr_results"] = asr_results

        trans_path = by_product_dir / "translated.txt"
        if trans_path.exists():
            intermediates["translations"] = [
                line for line in trans_path.read_text(encoding="utf-8").split("\n")
                if line.strip()
            ]

        tts_path = by_product_dir / "tts_aligned.wav"
        if tts_path.exists():
            intermediates["tts_path"] = str(tts_path)

        return intermediates

    def run_steps(
        self,
        selected_steps: List[str],
        progress_callback: Optional[Callable[[str], None]] = None,
        initial_state: Optional[PipelineState] = None,
        checkpoint_manager=None,
    ) -> Dict[str, Any]:
        """
        按选中的步骤执行流水线（支持选择性/单步执行）

        Args:
            selected_steps: 要执行的步骤列表，如 ["separation", "asr", "translate"]
            progress_callback: 进度回调函数
            initial_state: 初始状态（用于断点恢复）
            checkpoint_manager: CheckpointManager 实例（用于保存断点）

        Returns:
            处理结果字典

        Raises:
            StepDependencyError: 依赖不满足时抛出
        """
        import torch

        from ..translate import (
            load_subtitle_translations,
            load_subtitle_with_timestamps,
            detect_subtitle_language,
            load_and_clean_subtitle,
        )

        config = self.config
        input_path = Path(config.input_path)

        def _report(msg: str):
            """内部进度报告"""
            print(msg)
            if progress_callback:
                progress_callback(msg)

        # 解析输出目录
        mix_path, by_product_dir, task_name = self._resolve_output_dirs()

        # 初始化或恢复状态
        if initial_state:
            state = initial_state
        else:
            state = PipelineState(
                input_path=str(input_path),
                by_product_dir=str(by_product_dir),
                mix_path=str(mix_path),
            )

        # 检测已存在的中间文件
        existing = self._get_existing_intermediates(by_product_dir)
        if existing.get("vocal_path"):
            state.vocal_path = existing["vocal_path"]
        if existing.get("asr_results"):
            state.asr_results = existing["asr_results"]
        if existing.get("translations"):
            state.translations = existing["translations"]
        if existing.get("tts_path"):
            state.tts_path = existing["tts_path"]

        # 字幕检测
        subtitle_path = config.vtt_path
        if subtitle_path and Path(subtitle_path).exists():
            state.subtitle_path = subtitle_path
            subtitle_translations = load_subtitle_translations(subtitle_path)
            if subtitle_translations:
                if config.clean_subtitle:
                    from ..translate import clean_subtitle_batch
                    subtitle_translations = clean_subtitle_batch(
                        subtitle_translations,
                        clean_sound_effects=config.clean_sound_effects,
                        clean_speaker_names=config.clean_speaker_names,
                    )
                state.subtitle_lang = detect_subtitle_language(subtitle_translations)

        _report("=" * 60)
        _report(f"ASMR Helper 流水线 (步骤模式)")
        _report(f"输入: {input_path}")
        _report(f"选中步骤: {', '.join(selected_steps)}")
        _report(f"中间: {by_product_dir}/")
        _report("=" * 60)

        results = {
            "input": str(input_path),
            "output_dir": str(by_product_dir),
            "mix_path": str(mix_path),
            "steps": {},
            "selected_steps": selected_steps,
        }

        t0 = time.time()

        # 按顺序执行选中的步骤
        step_methods = {
            "separation": self._execute_separation,
            "asr": self._execute_asr,
            "translate": self._execute_translate,
            "tts": self._execute_tts,
            "mix": self._execute_mix,
        }

        for step_name in selected_steps:
            if step_name not in step_methods:
                _report(f"[警告] 未知步骤: {step_name}")
                continue

            # 检查依赖
            try:
                self._check_step_dependencies(step_name, state)
            except StepDependencyError as e:
                _report(f"[警告] {e}，跳过此步骤")
                continue

            # 执行步骤
            _report("")
            method = step_methods[step_name]
            step_result = method(state, _report, config)

            # 更新状态
            if step_result:
                results["steps"][step_name] = step_result
                # 更新 state 中的对应字段
                if "vocal_path" in step_result:
                    state.vocal_path = step_result["vocal_path"]
                if "asr_results" in step_result:
                    state.asr_results = step_result["asr_results"]
                if "translations" in step_result:
                    state.translations = step_result["translations"]
                if "timestamped_segments" in step_result:
                    state.timestamped_segments = step_result["timestamped_segments"]
                if "tts_path" in step_result:
                    state.tts_path = step_result["tts_path"]
                if "mix_path" in step_result:
                    state.mix_output_path = step_result["mix_path"]

            # 保存 checkpoint
            if checkpoint_manager:
                checkpoint_manager.save(
                    by_product_dir=str(by_product_dir),
                    step_name=step_name,
                    state=state,
                )

        # 汇总结果
        results["vocal_path"] = state.vocal_path
        results["asr_results"] = state.asr_results
        results["translations"] = state.translations
        results["timestamped_segments"] = state.timestamped_segments
        results["tts_path"] = state.tts_path
        results["mix_path"] = state.mix_output_path or str(mix_path)
        results["cloned_profile_id"] = state.cloned_profile_id

        total_time = time.time() - t0
        _report("")
        _report("=" * 60)
        _report(f"流水线完成! 总耗时: {total_time:.1f}s")
        _report("=" * 60)

        for step, data in results["steps"].items():
            if data.get("skipped"):
                _report(f"  {step}: [跳过]")
            elif data.get("error"):
                _report(f"  {step}: [错误] {data['error']}")
            else:
                _report(f"  {step}: {data.get('duration', 0):.1f}s")

        return results

    def _execute_separation(
        self,
        state: PipelineState,
        report_fn: Callable[[str], None],
        config: PipelineConfig,
    ) -> Dict[str, Any]:
        """
        执行人声分离步骤

        Returns:
            包含 vocal_path 的结果字典
        """
        import torch

        input_path = Path(config.input_path)
        by_product_dir = Path(state.by_product_dir)

        # 如果已有 vocal_path 且 skip_existing，跳过
        if state.vocal_path and config.skip_existing:
            report_fn(f"[跳过] 人声分离已存在")
            return {"skipped": True, "vocal_path": state.vocal_path}

        report_fn(f"人声分离 (Demucs)...")
        t1 = time.time()

        try:
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

            result = {
                "duration": time.time() - t1,
                "vocal_path": str(vocal_path),
                "output": str(vocal_path),
            }

            # 释放显存
            if self._injected_separator is None and 'separator' in locals():
                del separator
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            return result

        except Exception as e:
            report_fn(f"[WARN] 人声分离失败，使用原音: {e}")
            return {
                "error": str(e),
                "recoverable": True,
                "vocal_path": str(input_path),
            }

    def _execute_asr(
        self,
        state: PipelineState,
        report_fn: Callable[[str], None],
        config: PipelineConfig,
    ) -> Dict[str, Any]:
        """
        执行 ASR 识别步骤

        Returns:
            包含 asr_results 和 timestamped_segments 的结果字典
        """
        import torch

        by_product_dir = Path(state.by_product_dir)
        vocal_path = state.vocal_path or config.input_path
        asr_text_path = by_product_dir / "asr_result.txt"

        # 如果已有 ASR 结果且 skip_existing，跳过
        if state.asr_results and config.skip_existing:
            report_fn(f"[跳过] ASR 已存在")
            return {"skipped": True, "asr_results": state.asr_results}

        report_fn(f"ASR 语音识别 (Whisper)...")
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
                vocal_path,
                str(asr_text_path),
            )
            timestamped_segments = asr_results.copy()

            result = {
                "duration": time.time() - t1,
                "asr_results": asr_results,
                "timestamped_segments": timestamped_segments,
                "segments": len(asr_results),
                "output": str(asr_text_path),
            }

            # 释放显存
            if self._injected_recognizer is None and 'recognizer' in locals():
                del recognizer
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            return result

        except Exception as e:
            report_fn(f"[WARN] ASR 识别失败: {e}")
            return {
                "error": str(e),
                "recoverable": True,
                "asr_results": [],
                "timestamped_segments": [],
            }

    def _execute_translate(
        self,
        state: PipelineState,
        report_fn: Callable[[str], None],
        config: PipelineConfig,
    ) -> Dict[str, Any]:
        """
        执行翻译步骤

        Returns:
            包含 translations 和 timestamped_segments 的结果字典
        """
        from ..translate import Translator

        by_product_dir = Path(state.by_product_dir)
        translated_path = by_product_dir / "translated.txt"

        # 如果已有翻译且 skip_existing，跳过
        if state.translations and config.skip_existing:
            report_fn(f"[跳过] 翻译已存在")
            return {"skipped": True, "translations": state.translations}

        # 如果没有 ASR 结果，无法翻译
        if not state.asr_results:
            report_fn(f"[跳过] 无 ASR 结果，无法翻译")
            return {"skipped": True}

        report_fn(f"翻译 (DeepSeek)...")
        t1 = time.time()

        try:
            if self._injected_translator is not None:
                translator = self._injected_translator
            else:
                translator = Translator(
                    provider=config.translate_provider,
                    model=config.translate_model,
                )

            texts = [r["text"] for r in state.asr_results]
            translations = translator.translate_batch(
                texts,
                source_lang=config.source_lang,
                target_lang=config.target_lang,
            )
            translated_path.write_text("\n".join(translations), encoding="utf-8")

            # 更新 timestamped_segments
            timestamped_segments = []
            for seg, trans in zip(state.asr_results, translations):
                seg_copy = dict(seg)
                seg_copy["translation"] = trans
                timestamped_segments.append(seg_copy)

            return {
                "duration": time.time() - t1,
                "translations": translations,
                "timestamped_segments": timestamped_segments,
                "segments": len(translations),
                "output": str(translated_path),
            }

        except Exception as e:
            report_fn(f"[WARN] 翻译失败: {e}")
            # 降级：使用原文
            translations = [r["text"] for r in state.asr_results]
            return {
                "error": str(e),
                "recoverable": True,
                "translations": translations,
                "timestamped_segments": [
                    {**seg, "translation": seg["text"]}
                    for seg in state.asr_results
                ],
            }

    def _execute_tts(
        self,
        state: PipelineState,
        report_fn: Callable[[str], None],
        config: PipelineConfig,
    ) -> Dict[str, Any]:
        """
        执行 TTS 合成步骤

        Returns:
            包含 tts_path 的结果字典
        """
        by_product_dir = Path(state.by_product_dir)
        tts_aligned_path = by_product_dir / "tts_aligned.wav"

        # 如果已有 TTS 且 skip_existing，跳过
        if state.tts_path and config.skip_existing:
            report_fn(f"[跳过] TTS 已存在")
            return {"skipped": True, "tts_path": state.tts_path}

        # 如果没有 timestamped_segments，无法 TTS
        if not state.timestamped_segments:
            report_fn(f"[跳过] 无字幕数据，无法 TTS")
            return {"skipped": True}

        report_fn(f"TTS 逐句合成 + 时间轴对齐...")
        t1 = time.time()

        try:
            # 获取参考音频时长
            ref_path = state.vocal_path or config.input_path
            ref_info = sf.info(str(ref_path))
            ref_duration = ref_info.duration
            sample_rate = ref_info.samplerate

            # 获取 TTS 引擎
            if self._injected_tts_engine is not None:
                tts_engine = self._injected_tts_engine
            else:
                tts_engine = TTSEngine(
                    engine=config.tts_engine,
                    voice=config.tts_voice if config.tts_engine == "edge" else config.qwen3_voice,
                    speed=config.tts_speed,
                    voice_profile_id=config.voice_profile_id,
                )

            # 获取混音器
            if self._injected_mixer is not None:
                mixer = self._injected_mixer
            else:
                mixer = Mixer(
                    original_volume=config.original_volume,
                    tts_volume_ratio=config.tts_volume_ratio,
                    tts_delay_ms=config.tts_delay_ms,
                )

            mixer.build_aligned_tts(
                segments=state.timestamped_segments,
                tts_engine=tts_engine.engine,
                output_path=str(tts_aligned_path),
                reference_duration=ref_duration,
                sample_rate=sample_rate,
                max_tts_ratio=config.max_tts_ratio,
                compress_ratio=config.compress_ratio,
            )

            return {
                "duration": time.time() - t1,
                "tts_path": str(tts_aligned_path),
                "output": str(tts_aligned_path),
                "aligned": True,
                "segments": len(state.timestamped_segments),
            }

        except Exception as e:
            report_fn(f"[WARN] TTS 合成失败: {e}")
            return {
                "error": str(e),
                "recoverable": True,
                "tts_path": "",
            }

    def _execute_mix(
        self,
        state: PipelineState,
        report_fn: Callable[[str], None],
        config: PipelineConfig,
    ) -> Dict[str, Any]:
        """
        执行混音步骤

        Returns:
            包含 mix_path 的结果字典
        """
        input_path = Path(config.input_path)
        by_product_dir = Path(state.by_product_dir)
        mix_path = Path(state.mix_path)

        # 如果已有混音且 skip_existing，跳过
        if mix_path.exists() and config.skip_existing:
            report_fn(f"[跳过] 混音已存在")
            return {"skipped": True, "mix_path": str(mix_path)}

        # 如果没有 TTS，无法混音
        if not state.tts_path:
            report_fn(f"[跳过] 无 TTS 结果，无法混音")
            return {"skipped": True}

        # 确定原音频
        original_for_mix = state.vocal_path or str(input_path)
        use_vocal = Path(state.vocal_path).exists() if state.vocal_path else False
        mix_source_note = "人声分离结果" if use_vocal else "原音频"

        report_fn(f"混音 -> {mix_path.name}")
        report_fn(f"  (原音: {mix_source_note}, 中间文件: {by_product_dir.name}/)")
        t1 = time.time()

        try:
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
                state.tts_path,
                str(mix_path),
                adjust_tts_volume=True,
            )

            return {
                "duration": time.time() - t1,
                "mix_path": str(mix_path),
                "output": str(mix_path),
            }

        except Exception as e:
            report_fn(f"[WARN] 混音失败: {e}")
            # 降级：使用 TTS 输出
            return {
                "error": str(e),
                "recoverable": True,
                "mix_path": state.tts_path,
            }

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

        # 确定实际步骤数（固定 5 步，跳过的步骤显示为 [跳过]）
        # Step1: 分离 (始终)
        # Step2: ASR (无字幕时执行)
        # Step3: 翻译 (中文字幕跳过)
        # Step4: TTS + 时间轴对齐 (始终)
        # Step5: 混音 (始终)
        total_steps = 5
        current_step = 0

        # 获取字幕格式描述
        subtitle_ext = Path(subtitle_path).suffix.upper() if subtitle_path else ""
        subtitle_type = subtitle_ext.lstrip(".") or "VTT"

        _report("=" * 60)
        _report(f"ASMR Helper 流水线")
        _report(f"预设: {preset or 'custom'}")
        _report(f"输入: {input_path}")
        _report(f"成品: {mix_path.parent}/{mix_path.name}")
        _report(f"中间: {by_product_dir}/")
        if has_subtitle:
            _report(f"字幕: {Path(subtitle_path).name} ({subtitle_type}格式, 语言: {subtitle_lang})")
        _report(f"流程: {total_steps} 步" + (" (智能跳过优化)" if has_subtitle else ""))
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

        # ===== Step 1: 人声分离 (有字幕时跳过，直接使用原音频) =====
        if has_subtitle:
            # 有字幕，跳过人声分离，直接使用原音频
            current_step += 1
            results["vocal_path"] = str(input_path)
            _report(f"[{current_step}/{total_steps}] [跳过] 人声分离 (有{subtitle_type}字幕，直接使用原音频)")
            results["steps"]["vocal_separator"] = {"duration": 0, "skipped": True, "source": "original"}
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
            current_step += 1
            results["vocal_path"] = str(input_path)
            _report(f"[{current_step}/{total_steps}] [跳过] 人声分离 (直接使用输入文件)")

        # ===== Step 2: 时间戳获取 (ASR 或字幕) - 音色克隆需要 ASR 结果 =====
        asr_text_path = by_product_dir / "asr_result.txt"
        asr_results = []
        timestamped_segments = []  # [{start, end, text, translation}, ...] 贯穿整个流程

        if has_subtitle:
            # 使用字幕时间戳
            current_step += 1  # 递增步骤计数
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

            # 如果启用了音色克隆但字幕语言与音频语言不匹配，需要先做 ASR 获取音频语言的文本
            audio_lang = config.asr_language  # 音频语言（如 "ja"）
            if config.clone_voice_after_separation and subtitle_lang not in (audio_lang, "mixed"):
                _report(f"[音色克隆] 字幕语言({subtitle_lang}) != 音频语言({audio_lang})，先做 ASR 获取日语文本...")
                asr_done = False
            else:
                asr_done = True
        else:
            asr_done = True  # 没有字幕，正常进入 ASR 流程

        # 如果还没做 ASR 且需要做
        if not asr_done or (config.use_asr and not has_subtitle):
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

        results["asr_results"] = asr_results
        results["timestamped_segments"] = timestamped_segments

        # ===== 音色克隆 (report_18: AudioPreprocessor) - 使用 ASR 结果 =====
        results["cloned_profile_id"] = None
        if config.clone_voice_after_separation:
            _report("")
            _report(f"[音色克隆] 准备参考音频...")
            t_clone = time.time()

            try:
                from ..tts.voice_designer import VoiceDesigner
                from ..tts.voice_profile import get_voice_manager
                from ..tts.audio_preprocessor import AudioPreprocessor

                # 使用 AudioPreprocessor 准备合规的克隆音频
                # 传入 ASR 结果（包含日语文本和时间轴）
                preprocessor = AudioPreprocessor()
                clone_result = preprocessor.prepare_clone_audio(
                    audio_path=results["vocal_path"],
                    subtitle_path=subtitle_path if has_subtitle else None,
                    audio_language=config.asr_language,
                    asr_segments=timestamped_segments,  # 传入 ASR 结果！
                    progress_callback=lambda msg, p=0: _report(f"  {msg}"),
                )

                # 显示模式信息
                if clone_result.mode == "matched":
                    _report(f"[音色克隆] 匹配模式: ref_text 与音频内容完全匹配")
                else:
                    _report(f"[音色克隆] 基础模式: ref_text 使用默认文本")

                if clone_result.warnings:
                    for warn in clone_result.warnings:
                        _report(f"  [警告] {warn}")

                _report(f"[音色克隆] 片段: {clone_result.segments_used}, "
                       f"总时长: {clone_result.total_duration:.1f}s")

                # 调用克隆
                designer = VoiceDesigner()

                # 自动生成音色名称
                clone_name = config.clone_voice_name
                if not clone_name:
                    import datetime
                    clone_name = f"Clone_{datetime.datetime.now().strftime('%m%d%H%M')}"

                # 使用处理后的音频和真实匹配的 ref_text
                profile = designer.clone_from_audio(
                    audio_path=clone_result.ref_audio_path,
                    name=clone_name,
                    ref_text=clone_result.ref_text,  # 真实匹配的文本！
                    progress_callback=lambda msg, p=0: _report(f"  {msg}"),
                )

                results["cloned_profile_id"] = profile.id
                results["steps"]["voice_clone"] = {
                    "duration": time.time() - t_clone,
                    "profile_id": profile.id,
                    "profile_name": profile.name,
                    "audio_source": results["vocal_path"],
                    "mode": clone_result.mode,
                    "segments_used": clone_result.segments_used,
                    "total_duration": clone_result.total_duration,
                }
                _report(f"[音色克隆] 完成: {profile.name} ({profile.id})")

            except Exception as e:
                _report(f"[WARN] 音色克隆失败（不影响主流程）: {e}")
                import traceback
                traceback.print_exc()
                results["steps"]["voice_clone"] = {
                    "error": str(e),
                    "recoverable": True,
                }

        # ===== Step 3: 翻译 (保留时间戳) =====
        translated_path = by_product_dir / "translated.txt"
        translations = []

        if is_chinese_subtitle:
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
                "skipped": True,  # 跳过了翻译 API 调用
                "output": str(translated_path),
            }
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

        results["translations"] = translations

        # ===== Step 4: TTS 合成 + 时间轴对齐 (带错误处理) =====
        current_step += 1
        tts_aligned_path = by_product_dir / "tts_aligned.wav"
        # TTS 中间文件统一使用 .wav 格式，避免 mp3 残留问题

        if config.use_tts and timestamped_segments:
            _report("")
            if config.skip_existing and tts_aligned_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] TTS 已存在: {tts_aligned_path.name}")
            else:
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

        # ===== Step 5: 混音 (带错误处理) =====
        current_step += 1
        # 成品命名: <name>_mix.<ext>（已经在 _resolve_output_dirs 中计算好）

        # 确定混音用的原音频（有 VTT 时用原音频，否则用人声分离的结果）
        use_vocal = results.get("steps", {}).get("vocal_separator", {}).get("source") != "original"
        original_for_mix = results["vocal_path"] if use_vocal else str(input_path)
        mix_source_note = "人声分离结果" if use_vocal else "原音频"

        if config.use_mixer and results.get("tts_path"):
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
        _report(f"  [成品] {mix_path}")
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
