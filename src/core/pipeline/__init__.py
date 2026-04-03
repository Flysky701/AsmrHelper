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
    tts_speed: float = 1.0  # Qwen3 语速

    # 混音
    use_mixer: bool = True
    original_volume: float = 0.85
    tts_volume_ratio: float = 0.5
    tts_delay_ms: float = 0

    # 高级
    skip_existing: bool = False


class Pipeline:
    """处理流水线"""

    PRESETS = {
        "asmr_bilingual": "ASMR 双语双轨（人声分离 + ASR + 翻译 + TTS + 混音）",
        "asr_only": "仅 ASR 识别",
        "translate_only": "仅翻译文本",
        "tts_only": "仅 TTS 合成",
        "auto_subtitle": "自动字幕（ASR + 翻译）",
    }

    def __init__(self, config: PipelineConfig):
        """
        初始化流水线

        Args:
            config: 流水线配置
        """
        self.config = config
        self.steps = []
        self.results = {}

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

        from ..translate import load_vtt_translations, load_vtt_with_timestamps, detect_vtt_language

        config = self.config
        input_path = Path(config.input_path)
        output_dir = Path(config.output_dir or input_path.parent / "output")
        ensure_dir(output_dir)

        # 创建任务名
        task_name = input_path.stem
        task_dir = output_dir / task_name
        ensure_dir(task_dir)

        def _report(msg: str):
            """内部进度报告（打印 + 回调）"""
            print(msg)
            if progress_callback:
                progress_callback(msg)

        # ===== VTT 预检测 =====
        vtt_path = config.vtt_path
        vtt_translations = None
        vtt_lang = None
        has_vtt = False
        is_chinese_vtt = False

        if vtt_path and Path(vtt_path).exists():
            vtt_translations = load_vtt_translations(vtt_path)
            if vtt_translations:
                vtt_lang = detect_vtt_language(vtt_translations)
                has_vtt = True
                is_chinese_vtt = vtt_lang == "zh"

        # 确定实际步骤数（固定 5 步，跳过的步骤显示为 [跳过]）
        # Step1: 分离 (始终)
        # Step2: ASR (无 VTT 时执行)
        # Step3: 翻译 (中文 VTT 跳过)
        # Step4: TTS + 时间轴对齐 (始终)
        # Step5: 混音 (始终)
        total_steps = 5
        current_step = 0

        _report("=" * 60)
        _report(f"ASMR Helper 流水线")
        _report(f"预设: {preset or 'custom'}")
        _report(f"输入: {input_path}")
        _report(f"输出: {task_dir}")
        if has_vtt:
            _report(f"VTT字幕: {Path(vtt_path).name} (语言: {vtt_lang})")
        _report(f"流程: {total_steps} 步" + (" (智能跳过优化)" if has_vtt else ""))
        _report("=" * 60)

        results = {
            "input": str(input_path),
            "output_dir": str(task_dir),
            "steps": {},
            "vtt_lang": vtt_lang,
            "total_steps": total_steps,
        }

        t0 = time.time()

        # ===== Step 1: 人声分离 (始终执行) =====
        if config.use_vocal_separator:
            vocal_path = task_dir / "vocal.wav"
            current_step += 1
            if config.skip_existing and vocal_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] 人声分离已存在: {vocal_path.name}")
            else:
                _report("")
                _report(f"[{current_step}/{total_steps}] 人声分离 (Demucs)...")
                t1 = time.time()

                separator = VocalSeparator(model_name=config.vocal_model)
                sep_results = separator.separate(
                    str(input_path),
                    str(task_dir),
                    stems=["vocals"],
                )
                vocal_path = Path(sep_results.get("vocals", ""))

                # 释放 Demucs 模型显存
                del separator
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                results["steps"]["vocal_separator"] = {
                    "duration": time.time() - t1,
                    "output": str(vocal_path),
                }
            results["vocal_path"] = str(vocal_path)
        else:
            current_step += 1
            results["vocal_path"] = str(input_path)
            _report(f"[{current_step}/{total_steps}] [跳过] 人声分离 (直接使用输入文件)")

        # ===== Step 2: 时间戳获取 (ASR 或 VTT) =====
        asr_text_path = task_dir / "asr_result.txt"
        asr_results = []
        timestamped_segments = []  # [{start, end, text, translation}, ...] 贯穿整个流程

        if has_vtt:
            # 使用 VTT 时间戳
            _report(f"[{current_step}/{total_steps}] [跳过] ASR (使用 VTT 字幕时间戳)")
            vtt_entries = load_vtt_with_timestamps(vtt_path)
            timestamped_segments = [
                {"start": e["start"], "end": e["end"], "text": e["text"]}
                for e in vtt_entries
            ]
            results["steps"]["asr"] = {"duration": 0, "skipped": True, "source": "vtt", "segments": len(timestamped_segments)}
        elif config.use_asr:
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

                # 释放 Whisper 模型显存
                del recognizer
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                results["steps"]["asr"] = {
                    "duration": time.time() - t1,
                    "segments": len(asr_results),
                    "output": str(asr_text_path),
                }
        else:
            if asr_text_path.exists():
                text = asr_text_path.read_text(encoding="utf-8")
                asr_results = [{"text": line} for line in text.split("\n") if line.strip()]
        results["asr_results"] = asr_results
        results["timestamped_segments"] = timestamped_segments

        # ===== Step 3: 翻译 (保留时间戳) =====
        translated_path = task_dir / "translated.txt"
        translations = []

        if is_chinese_vtt:
            # 中文 VTT：已是翻译结果，直接使用
            current_step += 1
            translations = vtt_translations
            translated_path.write_text("\n".join(translations), encoding="utf-8")
            _report(f"[{current_step}/{total_steps}] [跳过] 翻译 (VTT 字幕已是中文，{len(translations)} 条)")

            # 为 timestamped_segments 填充 translation 字段
            for seg, trans in zip(timestamped_segments, translations):
                seg["translation"] = trans

            results["steps"]["translate"] = {
                "duration": 0.0,
                "segments": len(translations),
                "source": "vtt_zh",
                "skipped": False,
                "output": str(translated_path),
            }
        elif has_vtt and vtt_lang in ("ja", "mixed"):
            # 日文/混合 VTT：需要翻译
            current_step += 1
            _report("")
            _report(f"[{current_step}/{total_steps}] 翻译 (VTT {vtt_lang} -> 中文)...")
            t1 = time.time()

            translator = Translator(provider=config.translate_provider, model=config.translate_model)
            translations = translator.translate_batch(
                vtt_translations,
                source_lang="日文",
                target_lang="中文",
            )
            translated_path.write_text("\n".join(translations), encoding="utf-8")

            # 为 timestamped_segments 填充 translation 字段
            for seg, trans in zip(timestamped_segments, translations):
                seg["translation"] = trans

            results["steps"]["translate"] = {
                "duration": time.time() - t1,
                "segments": len(translations),
                "source": "vtt_ja",
                "output": str(translated_path),
            }
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

            # 为 timestamped_segments 填充 translation 字段
            for seg, trans in zip(timestamped_segments, translations):
                seg["translation"] = trans

        results["translations"] = translations

        # ===== Step 4: TTS 合成 + 时间轴对齐 =====
        current_step += 1
        tts_ext = "wav" if config.tts_engine == "qwen3" else "mp3"
        tts_aligned_path = task_dir / "tts_aligned.wav"
        tts_path = task_dir / f"tts_output.{tts_ext}"

        if config.use_tts and timestamped_segments:
            _report("")
            if config.skip_existing and tts_aligned_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] TTS 已存在: {tts_aligned_path.name}")
            else:
                _report(f"[{current_step}/{total_steps}] TTS 逐句合成 + 时间轴对齐...")
                t1 = time.time()

                # 获取参考音频时长
                ref_info = sf.info(str(results["vocal_path"]))
                ref_duration = ref_info.duration
                sample_rate = ref_info.samplerate

                # 初始化 TTS 引擎
                tts_engine = TTSEngine(
                    engine=config.tts_engine,
                    voice=config.tts_voice if config.tts_engine == "edge" else config.qwen3_voice,
                    speed=config.tts_speed,
                    voice_profile_id=config.voice_profile_id,
                )

                # 使用时间轴对齐方法
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
                )

                results["steps"]["tts"] = {
                    "duration": time.time() - t1,
                    "output": str(tts_aligned_path),
                    "aligned": True,
                    "segments": len(timestamped_segments),
                }
            results["tts_path"] = str(tts_aligned_path)
        else:
            results["tts_path"] = ""

        # ===== Step 5: 混音 (始终执行) =====
        current_step += 1
        mix_path = task_dir / "final_mix.wav"

        if config.use_mixer and results.get("tts_path"):
            if config.skip_existing and mix_path.exists():
                _report(f"[{current_step}/{total_steps}] [跳过] 混音已存在: {mix_path.name}")
            else:
                _report("")
                _report(f"[{current_step}/{total_steps}] 混音...")
                t1 = time.time()

                mixer = Mixer(
                    original_volume=config.original_volume,
                    tts_volume_ratio=config.tts_volume_ratio,
                    tts_delay_ms=config.tts_delay_ms,
                )
                mixer.mix(
                    results["vocal_path"],
                    results["tts_path"],
                    str(mix_path),
                    adjust_tts_volume=True,
                )

                results["steps"]["mixer"] = {
                    "duration": time.time() - t1,
                    "output": str(mix_path),
                }
            results["mix_path"] = str(mix_path)
        else:
            results["mix_path"] = ""

        # ===== 总结 =====
        total_time = time.time() - t0
        _report("")
        _report("=" * 60)
        _report(f"流水线完成! 总耗时: {total_time:.1f}s")
        if has_vtt:
            saved = 23 if is_chinese_vtt else 0
            saved += 23 if (has_vtt and not is_chinese_vtt) else 0
            if saved > 0:
                _report(f"(相比无 VTT 流程节省约 {saved}s)")
        _report("=" * 60)

        for step, data in results["steps"].items():
            if data.get("skipped"):
                _report(f"  {step}: [跳过]")
            else:
                _report(f"  {step}: {data.get('duration', 0):.1f}s")

        _report("")
        _report("输出文件:")
        for key in ["vocal_path", "translations", "tts_path", "mix_path"]:
            val = results.get(key)
            if val:
                if key == "translations":
                    _report(f"  - 翻译: {translated_path}")
                else:
                    _report(f"  - {key}: {val}")

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
