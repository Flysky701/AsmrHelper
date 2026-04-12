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
from src.utils import format_timestamp
import soundfile as sf

from .path_planner import PathPlanner
from .step_resolver import StepResolver
from .subtitle_strategy import SubtitleStrategy
from .step_executor import StepExecutor
from .artifact_collector import ArtifactCollector


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
    # "asr_only"      -> 仅 ASR + 可选人声分离
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
        "tts_only": "仅 TTS 合成",
        "auto_subtitle": "自动字幕（ASR + 翻译）",
    }

    def __init__(self, config: PipelineConfig,
                 separator=None, recognizer=None,
                 translator=None, tts_engine=None, mixer=None,
                 cancel_event=None):
        """
        初始化流水线（支持依赖注入）

        Args:
            config: 流水线配置
            separator: 人声分离器实例（可选，默认自动创建）
            recognizer: ASR 识别器实例（可选，默认自动创建）
            translator: 翻译器实例（可选，默认自动创建）
            tts_engine: TTS 引擎实例（可选，默认自动创建）
            mixer: 混音器实例（可选，默认自动创建）
            cancel_event: 取消事件（threading.Event，协作式取消）
        """
        self.config = config
        self.steps = []
        self.results = {}
        self._cancel_event = cancel_event

        # 依赖注入的组件（支持外部传入，便于测试和复用）
        self._injected_separator = separator
        self._injected_recognizer = recognizer
        self._injected_translator = translator
        self._injected_tts_engine = tts_engine
        self._injected_mixer = mixer

        # 解耦辅助组件
        self._path_planner = PathPlanner(config)
        self._step_resolver = StepResolver(config)
        self._subtitle_strategy = SubtitleStrategy(config)
        self._step_executor = StepExecutor(config, self._path_planner, self._subtitle_strategy)
        self._step_executor.inject(
            separator=self._injected_separator,
            recognizer=self._injected_recognizer,
            translator=self._injected_translator,
            tts_engine=self._injected_tts_engine,
            mixer=self._injected_mixer
        )
        # 传递 cancel_event 给 executor
        if cancel_event:
            self._step_executor.set_cancel_event(cancel_event)
        self._artifact_collector = ArtifactCollector(config)

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
        return self._path_planner.resolve_output_dirs()

    def _resolve_active_steps(self, has_subtitle: bool, is_chinese_subtitle: bool) -> List[str]:
        """
        根据配置和输入条件确定实际执行的步骤列表

        Args:
            has_subtitle: 是否有字幕文件
            is_chinese_subtitle: 字幕是否为中文

        Returns:
            如 ["vocal_separator", "asr", "translate"]
        """
        return self._step_resolver.resolve_active_steps(has_subtitle, is_chinese_subtitle)

    def run(
        self,
        preset: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        运行流水线（支持 VTT 智能跳过）

        Args:
            preset: 预设流程名称
            progress_callback: 进度回调函数（接收消息字符串），供 GUI 实时显示

        Returns:
            Dict: 处理结果
        """
        config = self.config
        input_path = Path(config.input_path)

        # 统一解析输出目录
        mix_path, by_product_dir, task_name = self._resolve_output_dirs()

        # 初始化 Executor
        executor = self._step_executor
        executor.progress_callback = progress_callback
        executor._report("=" * 60)
        executor._report(f"ASMR Helper 流水线")
        executor._report(f"预设: {preset or 'custom'}")
        executor._report(f"输入: {input_path}")
        executor._report(f"成品: {mix_path.parent}/{mix_path.name}")
        executor._report(f"中间: {by_product_dir}/")

        # 字幕预检测
        subtitle_ctx = self._subtitle_strategy.preload()
        if subtitle_ctx.has_subtitle:
            executor._report(f"字幕: {Path(subtitle_ctx.subtitle_path).name} ({subtitle_ctx.subtitle_type}格式, 语言: {subtitle_ctx.subtitle_lang})")

        # 解析执行步骤
        active_steps = self._resolve_active_steps(subtitle_ctx.has_subtitle, subtitle_ctx.is_chinese_subtitle)
        
        # 进度统计与真实执行步骤保持一致
        executor.total_steps = len(active_steps)

        executor._report(f"流程: {executor.total_steps} 步 [{config.pipeline_mode}]")
        executor._report("=" * 60)

        executor.results = {
            "input": str(input_path),
            "output_dir": str(by_product_dir),
            "mix_path": str(mix_path),
            "steps": {},
            "subtitle_lang": subtitle_ctx.subtitle_lang,
            "subtitle_type": subtitle_ctx.subtitle_type,
            "total_steps": executor.total_steps,
        }

        # 执行流水线步骤
        t0 = time.time()
        
        def _check_cancel():
            """检查取消状态，若已取消则抛出异常中断流水线"""
            if self._cancel_event and self._cancel_event.is_set():
                raise RuntimeError("用户取消操作")
        
        _check_cancel()
        vocal_path = executor.execute_separation(active_steps, subtitle_ctx, task_name, input_path, by_product_dir)
        
        _check_cancel()
        timestamped_segments = executor.execute_asr(active_steps, subtitle_ctx, vocal_path, by_product_dir)
        
        # asr_only 模式导出字幕
        if config.pipeline_mode != "full" and "translate" not in active_steps:
            sub_path = self._artifact_collector.write_subtitles(
                ["translate"], timestamped_segments, [], by_product_dir, task_name, "ja"
            )
            if sub_path:
                executor.results["exported_subtitle"] = sub_path

        _check_cancel()
        translations = executor.execute_translate(active_steps, subtitle_ctx, timestamped_segments, by_product_dir)
        
        _check_cancel()
        tts_audio_path = executor.execute_tts(active_steps, timestamped_segments, by_product_dir)

        _check_cancel()
        executor.execute_mix(
            active_steps,
            input_path,
            tts_audio_path,
            mix_path,
            timestamped_segments=timestamped_segments,
            tts_engine=executor.results.get("tts_engine"),
        )
        
        # Artifact 收集 (写回多语言字幕)
        self._artifact_collector.progress_callback = progress_callback
        sub_path = self._artifact_collector.write_subtitles(
            active_steps, timestamped_segments, translations, by_product_dir, task_name, subtitle_ctx.subtitle_lang
        )
        if sub_path:
            executor.results["exported_subtitle"] = sub_path

        executor.results["total_duration"] = time.time() - t0
        executor._report(f"\n[完成] 总耗时: {executor.results['total_duration']:.1f}s")
        executor._report("=" * 60)

        return executor.results
