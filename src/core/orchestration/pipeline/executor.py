"""Pipeline executor — runs stages via engine runtimes directly.

This module accepts a PipelineExecutionPlan and drives each enabled stage
through the corresponding EngineRuntime.
"""

from __future__ import annotations

import time
import json
import logging
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .models import PipelineExecutionPlan


class PipelineExecutor:
    """Execute pipeline stages via engine runtimes directly.

    This is the new primary execution path that replaces the legacy
    Pipeline class. Each stage is executed through its corresponding
    EngineRuntime (SeparatorEngineRuntime, AsrEngineRuntime,
    LlmOperationRuntime) plus SpeechService and the Mixer.
    """

    def __init__(
        self,
        *,
        separator=None,
        asr=None,
        aligner=None,
        llm=None,
        mixer_factory=None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Initialize with optional injected runtimes (for testing).

        Args:
            separator: SeparatorEngineRuntime instance or mock
            asr: AsrEngineRuntime instance or mock
            llm: LlmOperationRuntime instance or mock
            mixer_factory: Callable that creates a Mixer given (original_volume, tts_volume_ratio, tts_delay_ms)
            cancel_event: Optional threading.Event for cooperative cancellation
        """
        self._separator = separator
        self._asr = asr
        self._aligner = aligner
        self._llm = llm
        self._mixer_factory = mixer_factory
        self._cancel_event = cancel_event

    def execute_stage(
        self, stage, plan, *, directory, audio_path=None, speech_path=None,
        segments=None, cancel_event=None,
    ):
        """Run exactly one capability with isolated state and strict failures.

        The graph adapter supplies validated inputs and an instance-specific plan.
        This does not enter the legacy workflow, discover companions, or execute
        any other enabled binding carried by that plan.
        """
        from copy import deepcopy

        def check_cancel():
            event = cancel_event or self._cancel_event
            if event and event.is_set():
                raise InterruptedError("用户取消操作")

        check_cancel()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        plan = replace(
            plan, input_path=str(audio_path or plan.input_path), output_dir=str(directory),
            companion_subtitle_path=None, companion_subtitle_paths=[], skip_existing=False,
            workflow={"graph_node": True},
        )
        results = {"steps": {}, "step_errors": {}}
        cues = deepcopy(segments or [])
        if stage == "separate":
            if audio_path is None:
                raise ValueError("人声分离缺少明确音频输入")
            value = self._execute_separation(plan, directory, results)
        elif stage == "asr":
            if audio_path is None:
                raise ValueError("语音识别缺少明确音频输入")
            cues = self._execute_asr(plan, Path(audio_path), directory, results)
            value = results.get("transcript_path")
        elif stage == "align":
            if audio_path is None or not cues:
                raise ValueError("时间轴校准需要音频和字幕输入")
            cues = self._execute_alignment(plan, cues, directory, results)
            value = results.get("aligned_subtitle_path")
        elif stage == "translate":
            if not cues:
                raise ValueError("翻译缺少字幕输入")
            translations = self._execute_translation(plan, cues, directory, results)
            if not results["step_errors"]:
                cues = [{"start": cue["start"], "end": cue["end"], "text": text,
                         "original": cue["text"]}
                        for cue, text in zip(cues, translations, strict=True)]
            value = results.get("steps", {}).get("translate", {}).get("output")
        elif stage == "tts":
            if not cues:
                raise ValueError("语音合成缺少字幕输入")
            event = cancel_event or self._cancel_event
            value = self._execute_tts(
                plan, cues, directory, results,
                cancel_check=lambda: bool(event and event.is_set()),
            )
        elif stage == "mix":
            if audio_path is None or speech_path is None:
                raise ValueError("混音需要两个明确音频输入")
            if not Path(audio_path).is_file() or not Path(speech_path).is_file():
                raise ValueError("混音输入音频不存在，不能复制原音代替混音")
            value = directory / "mix.wav"
            self._execute_mix(plan, Path(audio_path), Path(speech_path), value, results)
        elif stage == "export":
            if not cues:
                raise ValueError("字幕导出缺少字幕输入")
            value = self._export_subtitles(plan, cues, [], directory)
        else:
            raise ValueError(f"不支持的执行能力: {stage}")
        check_cancel()
        if results["step_errors"]:
            raise RuntimeError(next(iter(results["step_errors"].values())))
        if not value or not Path(value).is_file() or Path(value).stat().st_size == 0:
            raise RuntimeError(f"{stage} 未产生有效文件")
        return {**results, "path": str(value), "segments": cues}

    def execute(
        self,
        plan: PipelineExecutionPlan,
        *,
        progress_callback: Callable[[str], None] | None = None,
        stage_callback: Callable[[str, float, str], None] | None = None,
        cancel_event: threading.Event | None = None,
        recovery=None,
    ) -> dict[str, Any]:
        """Run all enabled stages and return normalized results.

        Args:
            plan: The execution plan describing what stages to run
            progress_callback: Optional callback for progress messages

        Returns:
            Normalized result dictionary compatible with ArtifactResultMapper output
        """
        if recovery is not None:
            plan = replace(plan, skip_existing=False)
        results: dict[str, Any] = {
            "input": plan.input_path,
            "output_dir": plan.output_dir,
            "mix_path": None,
            "exported_subtitle": None,
            "primary_output": None,
            "vocal_path": None,
            "tts_audio_path": None,
            "transcript_path": None,
            "steps": {},
            "step_errors": {},
            "subtitle_lang": None,
            "subtitle_type": None,
            "total_steps": len(plan.active_stage_kinds),
            "total_duration": 0.0,
            "error": None,
        }

        t0 = time.perf_counter()
        current_step = 0
        total_steps = len(plan.active_stage_kinds) + int(plan.subtitle.enabled)

        def _report(stage: str, msg: str) -> None:
            if progress_callback:
                progress_callback(msg)
            if stage_callback:
                stage_callback(stage, current_step / max(total_steps, 1), msg)

        def _check_cancel() -> None:
            effective_cancel_event = cancel_event or self._cancel_event
            if effective_cancel_event and effective_cancel_event.is_set():
                raise RuntimeError("用户取消操作")

        timestamped_segments: list[dict[str, Any]] = []
        translations: list[str] = []
        vocal_path = Path(plan.input_path)
        mix_path, by_product_dir = self._resolve_output_paths(plan)
        tts_audio_path = by_product_dir / "tts_output.wav"
        results["output_dir"] = str(by_product_dir)

        flow = None
        if plan.workflow:
            from .workflow import WorkflowInputs
            flow = WorkflowInputs(plan)

        def _run(stage, operation):
            def execute_checked():
                value = operation()
                if flow and results["step_errors"]:
                    raise RuntimeError(f"{stage} 阶段失败: {next(iter(results['step_errors'].values()))}")
                results["last_stage"] = stage
                return value
            if recovery is None:
                return execute_checked()
            def checked_operation():
                value = execute_checked()
                _check_cancel()
                return value
            return recovery.run(stage, checked_operation, results, timestamped_segments,
                                translations, by_product_dir, mix_path)

        try:
            if not flow and plan.translation.common_options.get("direct_tts") is True:
                from src.core.subtitles.translation_reuse import direct_subtitle_input
                if any(stage.enabled for stage in (plan.separation, plan.asr, plan.alignment, plan.translation, plan.mix)):
                    raise ValueError("直接配音计划包含不需要的前置阶段，请重新提交任务")
                selected = direct_subtitle_input({
                    "source_lang": plan.source_lang, "target_lang": plan.target_lang,
                    "stages": {"translate": {"options": plan.translation.common_options}},
                }, plan.input_path, plan.companion_subtitle_paths)
                timestamped_segments = selected["segments"]
                translations = [segment["translation"] for segment in timestamped_segments]
                results["direct_subtitle_tts"] = True
                results["subtitle_lang"] = plan.target_lang
                results["subtitle_type"] = "target"
                results["subtitle_input"] = {"path": selected["path"], "segments": len(timestamped_segments)}
                _report("tts", "已验证目标字幕，按现有时间轴直接配音（不混音）")
            # === SEPARATION ===
            if plan.separation.enabled:
                _check_cancel()
                current_step += 1
                _report("separate", f"[{current_step}/{total_steps}] 人声分离...")
                stage_plan = replace(plan, input_path=str(flow.audio("separate"))) if flow else plan
                vocal_path = _run("separate", lambda: self._execute_separation(stage_plan, by_product_dir, results))
                if flow:
                    flow.outputs["separate"] = vocal_path

            # === ASR ===
            if plan.asr.enabled:
                _check_cancel()
                current_step += 1
                _report("asr", f"[{current_step}/{total_steps}] ASR 语音识别...")
                asr_audio = flow.audio("asr") if flow else vocal_path
                stage_plan = replace(plan, companion_subtitle_path=None, input_path=str(asr_audio)) if flow else plan
                timestamped_segments = _run("asr", lambda: self._execute_asr(stage_plan, asr_audio, by_product_dir, results))
                if flow:
                    if not timestamped_segments:
                        raise ValueError("语音识别没有产生有效字幕，不能跳过缺项继续执行")
                    flow.record_text("asr", timestamped_segments)

            # === ALIGNMENT ===
            if plan.alignment.enabled:
                _check_cancel()
                current_step += 1
                _report("align", f"[{current_step}/{total_steps}] 校准字幕时间轴...")
                if flow:
                    timestamped_segments = flow.text("align")
                stage_plan = replace(plan, input_path=str(flow.audio("align")), companion_subtitle_path=None) if flow else plan
                timestamped_segments = _run("align", lambda: self._execute_alignment(
                    stage_plan, timestamped_segments, by_product_dir, results
                ))
                if flow:
                    flow.record_text("align", timestamped_segments)
                _check_cancel()

            # === TRANSLATION ===
            if plan.translation.enabled or (not flow and plan.translation.common_options.get("reuse_only")):
                _check_cancel()
                current_step += 1
                _report("translate", f"[{current_step}/{total_steps}] 文本翻译...")
                if flow:
                    timestamped_segments = flow.text("translate")
                translations = _run("translate", lambda: self._execute_translation(
                    plan, timestamped_segments, by_product_dir, results
                ))
                if not results["step_errors"].get("translate"):
                    self._attach_translations(timestamped_segments, translations, plan.target_lang)
                if flow:
                    flow.record_text("translate", [{"start": s["start"], "end": s["end"], "text": t,
                        "original": s["text"]} for s, t in zip(timestamped_segments, translations, strict=True)])

            # === TTS ===
            if plan.tts.enabled:
                _check_cancel()
                if results["step_errors"].get("translate"):
                    raise RuntimeError(f"translate 阶段失败: {results['step_errors']['translate']}")
                current_step += 1
                _report("tts", f"[{current_step}/{total_steps}] TTS 语音合成...")
                stage_plan = plan
                if flow:
                    timestamped_segments = flow.text("tts")
                    stage_plan = replace(plan, tts=replace(plan.tts, common_options={
                        **plan.tts.common_options, "reference_duration": flow.duration("tts"),
                    }))
                tts_audio_path = _run("tts", lambda: self._execute_tts(
                    stage_plan, timestamped_segments, by_product_dir, results,
                    cancel_check=lambda: bool((cancel_event or self._cancel_event) and (cancel_event or self._cancel_event).is_set()),
                ))

                if flow:
                    flow.outputs["tts"] = tts_audio_path

            # === MIX ===
            if plan.mix.enabled:
                _check_cancel()
                current_step += 1
                _report("mix", f"[{current_step}/{total_steps}] 混合音频...")
                mix_audio = flow.audio("mix") if flow else vocal_path
                speech_audio = flow.audio("mix", "speech") if flow else tts_audio_path
                _run("mix", lambda: self._execute_mix(plan, mix_audio, speech_audio, mix_path, results))
                if flow:
                    flow.outputs["mix"] = mix_path

            # === SUBTITLE EXPORT ===
            if plan.subtitle.enabled:
                _check_cancel()
                current_step += 1
                _report("export", f"[{current_step}/{total_steps}] 导出字幕...")
                export_plan = plan
                if flow:
                    timestamped_segments = flow.text("export")
                    has_original = all(s.get("original") for s in timestamped_segments)
                    translations = [s["text"] for s in timestamped_segments] if has_original else []
                    if has_original:
                        timestamped_segments = [{**s, "text": s["original"]} for s in timestamped_segments]
                    export_plan = replace(plan, source_lang=plan.workflow["languages"]["export"])
                exported_subtitle = _run("export", lambda: self._export_subtitles(
                    export_plan, timestamped_segments, translations, by_product_dir
                ))
                if flow and not exported_subtitle:
                    raise ValueError("字幕导出未产生有效文件")
                if exported_subtitle:
                    results["exported_subtitle"] = exported_subtitle

        except Exception as e:
            results["error"] = str(e)
            if not isinstance(e, RuntimeError) or "取消" not in str(e):
                _report("error", f"[ERROR] 流水线异常: {e}")
            raise
        finally:
            results["total_duration"] = time.perf_counter() - t0
            results["mix_path"] = str(mix_path) if plan.mix.enabled and mix_path.exists() else None
            results["primary_output"] = (
                results["mix_path"]
                or (results.get("tts_audio_path") if results.get("direct_subtitle_tts") else None)
                or results.get("exported_subtitle")
            )

        if flow:
            self._select_workflow_outputs(plan, results)
        return results

    @staticmethod
    def _select_workflow_outputs(plan, results):
        definitions = {
            "separate": (results.get("vocal_path"), "audio.vocals", "audio", "分离人声"),
            "asr": (results.get("transcript_path"), "text.transcript", "text", "识别文本"),
            "align": (results.get("aligned_subtitle_path"), "subtitle.aligned", "subtitle", "校准字幕"),
            "translate": (results["steps"].get("translate", {}).get("output"), "text.translation", "text", "翻译文本"),
            "tts": (results.get("tts_audio_path"), "audio.tts", "audio", "配音音轨"),
            "mix": (results.get("mix_path"), "audio.mix", "audio", "混音音频"),
            "export": (results.get("exported_subtitle"), f"subtitle.{plan.subtitle.export_format}", "subtitle", "导出字幕"),
        }
        outputs = []
        for stage in plan.workflow["outputs"]:
            path, kind, preview, label = definitions[stage]
            if not path or not Path(path).is_file():
                raise ValueError(f"所选产出 {stage} 未生成，任务不能标记为完成")
            outputs.append({"stage": stage, "path": path, "type": kind, "preview": preview, "label": label})
        results["workflow_outputs"] = outputs
        results["primary_output"] = outputs[0]["path"]
        # Only selected deliverables are advertised; intermediates stay on disk for recovery.
        if "mix" not in plan.workflow["outputs"]:
            results["mix_path"] = None
        if "export" not in plan.workflow["outputs"]:
            results["exported_subtitle"] = None

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _execute_separation(
        self,
        plan: PipelineExecutionPlan,
        by_product_dir: Path,
        results: dict[str, Any],
    ) -> Path:
        """Run vocal separation stage."""
        from src.core.engines.separator import SeparatorEngineRuntime

        vocal_path = by_product_dir / "vocal.wav"

        if plan.skip_existing and vocal_path.exists():
            results["steps"]["vocal_separator"] = {
                "duration": 0, "skipped": True, "output": str(vocal_path)
            }
            results["vocal_path"] = str(vocal_path)
            return vocal_path

        t1 = time.time()
        try:
            separator = self._separator or SeparatorEngineRuntime()
            sep_results = separator.separate(
                input_path=plan.input_path,
                output_dir=str(by_product_dir),
                model=plan.separation.model,
                stems=["vocals"],
            )
            vocals = sep_results.get("vocals")
            if not vocals:
                raise ValueError("人声分离未返回 vocals 路径")
            vocal_path = Path(vocals)
            results["steps"]["vocal_separator"] = {
                "duration": time.time() - t1, "output": str(vocal_path)
            }
        except Exception as e:
            if plan.workflow.get("graph_node"):
                raise
            results["steps"]["vocal_separator"] = {"error": str(e), "recoverable": True}
            results["step_errors"]["vocal_separator"] = str(e)
            vocal_path = Path(plan.input_path)
        finally:
            self._try_clear_gpu()

        results["vocal_path"] = str(vocal_path)
        return vocal_path

    def _execute_asr(
        self,
        plan: PipelineExecutionPlan,
        vocal_path: Path,
        by_product_dir: Path,
        results: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run ASR transcription stage."""
        from src.core.engines.asr import AsrEngineRuntime

        asr_text_path = by_product_dir / "asr_result.txt"
        companion = self._load_source_companion(plan, results)
        if companion:
            asr_text_path.write_text("\n".join(entry["text"] for entry in companion), encoding="utf-8")
            results["transcript_path"] = str(asr_text_path)
            results["steps"]["asr"] = {"duration": 0.0, "segments": len(companion),
                                       "output": str(asr_text_path), "reused_subtitle": plan.companion_subtitle_path}
            return companion
        t1 = time.time()
        try:
            recognizer = self._asr or AsrEngineRuntime()
            document = recognizer.transcribe_file(
                input_path=str(vocal_path),
                output_path=str(asr_text_path),
                profile={
                    "provider": plan.asr.provider,
                    "model": plan.asr.model,
                    "common_options": plan.asr.common_options,
                    "provider_options": plan.asr.provider_options,
                },
            )
            segments = [
                {"start": seg.start, "end": seg.end, "text": seg.text}
                for seg in document.segments
            ]
            results["transcript_path"] = str(asr_text_path)
            results["steps"]["asr"] = {
                "duration": time.time() - t1,
                "segments": len(segments),
                "output": str(asr_text_path),
            }
        except Exception as e:
            if plan.workflow.get("graph_node"):
                raise
            results["steps"]["asr"] = {"error": str(e), "recoverable": True}
            results["step_errors"]["asr"] = str(e)
            segments = []
        finally:
            self._try_clear_gpu()

        return segments

    @staticmethod
    def _load_source_companion(plan, results):
        from src.core.subtitles.companions import inspect_subtitle, is_source_subtitle
        if not plan.companion_subtitle_path or Path(plan.companion_subtitle_path).suffix.lower() == ".txt":
            return []
        inspection = inspect_subtitle(plan.companion_subtitle_path)
        results["companion_subtitle"] = {key: value for key, value in inspection.items() if key != "segments"}
        if not is_source_subtitle(inspection, plan.source_lang):
            results["companion_subtitle"]["reason"] = inspection["reason"] or "字幕与原音频语言不一致，保留 ASR 原文识别"
            return []
        try:
            import soundfile as sf
            duration = sf.info(plan.input_path).duration
            if any(float(entry["end"]) > duration + 0.1 for entry in inspection["segments"]):
                raise ValueError("字幕时间轴超出音频范围")
        except (OSError, RuntimeError, ValueError) as exc:
            results["companion_subtitle"]["reason"] = f"无法验证字幕时间轴：{exc}"
            return []
        results["companion_subtitle"]["reused"] = True
        return inspection["segments"]

    def _execute_alignment(self, plan, segments, by_product_dir, results):
        from src.core.engines.alignment import AlignmentRuntime
        from src.core.subtitles import SubtitleExporter

        if plan.companion_subtitle_path:
            source = Path(plan.companion_subtitle_path)
            if source.suffix.lower() == ".txt":
                from src.core.subtitles.companions import conservative_text_language
                from src.core.subtitles.text_utils import normalize_language_code
                text = source.read_text(encoding="utf-8").strip()
                language = conservative_text_language([text])
                if language not in {"unknown", "mixed"} and language == normalize_language_code(plan.source_lang):
                    segments = [{"text": text}]
            else:
                segments = self._load_source_companion(plan, results) or segments
        original = by_product_dir / "alignment_original.json"
        original.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
        started = time.time()
        if self._asr is None and not plan.workflow:
            from src.core.engines.asr import get_asr_registry
            get_asr_registry().unload_all()
            self._try_clear_gpu()
        runtime = self._aligner or AlignmentRuntime()
        # Preserve the verified source cue identity while the aligner adjusts timing.
        segments = [{**segment, "translation_source_anchor": {
            "start": segment.get("start"), "end": segment.get("end"), "text": segment.get("text", ""),
        }} for segment in segments]
        aligned = runtime.align_file(input_path=plan.input_path, segments=segments, language=plan.source_lang)
        output = by_product_dir / "alignment_result.json"
        output.write_text(json.dumps(aligned, ensure_ascii=False, indent=2), encoding="utf-8")
        subtitle = by_product_dir / "aligned.vtt"
        SubtitleExporter().export_bilingual_subtitle(aligned["segments"], str(subtitle), bilingual=False)
        results["alignment_path"] = str(output)
        results["aligned_subtitle_path"] = str(subtitle)
        results["alignment_original_path"] = str(original)
        results["steps"]["align"] = {"duration": time.time() - started, "output": str(output),
            "segments": len(aligned["segments"]), "warnings": aligned.get("warnings", [])}
        return aligned["segments"]

    def _execute_translation(
        self,
        plan: PipelineExecutionPlan,
        timestamped_segments: list[dict[str, Any]],
        by_product_dir: Path,
        results: dict[str, Any],
    ) -> list[str]:
        """Reuse verified cues, translating only missing entries in original order."""
        from src.core.subtitles.translation_reuse import (
            cached_translations, reusable_translations, reuse_enabled, unused_output,
        )
        t1 = time.time()
        try:
            options = plan.translation.common_options
            translations = [""] * len(timestamped_segments)
            cache_path = by_product_dir / f"translations.{plan.target_lang}.json"
            if not plan.workflow and reuse_enabled(options):
                paths = list(getattr(plan, "companion_subtitle_paths", []))
                if plan.companion_subtitle_path and plan.companion_subtitle_path not in paths:
                    paths.append(plan.companion_subtitle_path)
                translations = reusable_translations(timestamped_segments, paths,
                    plan.source_lang, plan.target_lang, plan.input_path)
                cached = cached_translations(cache_path, timestamped_segments, plan.source_lang, plan.target_lang)
                translations = [text or cached[i] for i, text in enumerate(translations)]
            pending = [i for i, text in enumerate(translations) if not text
                       and str(timestamped_segments[i].get("text", "")).strip()]
            reused = sum(bool(text) for text in translations)
            if pending and options.get("reuse_only"):
                raise ValueError("已有译文无法完整匹配，缺失部分需要有效翻译连接；已停止配音，请检查字幕或配置翻译服务后重新提交")
            if pending:
                from src.core.engines.llm import LlmOperationRuntime
                translator = self._llm or LlmOperationRuntime()
                generated = translator.translate_texts(
                    texts=[timestamped_segments[i].get("text", "") for i in pending],
                    profile={
                        "provider": plan.translation.provider,
                        "model": plan.translation.model,
                        "common_options": options,
                        "provider_options": plan.translation.provider_options,
                    },
                    source_lang=plan.source_label,
                    target_lang=plan.target_label,
                )
                if len(generated) != len(pending) or any(not isinstance(t, str) or not t.strip() for t in generated):
                    raise ValueError("翻译结果缺少条目或包含空译文，已停止配音以避免漏句")
                for i, text in zip(pending, generated, strict=True):
                    translations[i] = text.strip()
            # Preserve old plaintext and structured outputs, including hand edits.
            translated_path = unused_output(by_product_dir, "translated.txt")
            records_path = unused_output(by_product_dir, cache_path.name)
            records = [{"start": s.get("start"), "end": s.get("end"),
                        "source_text": s.get("text", ""), "translation": text,
                        **({"previous_translation": s["translation"]} if s.get("translation") else {})}
                       for s, text in zip(timestamped_segments, translations, strict=True)]
            records_path.write_text(json.dumps({"version": 1, "source_lang": plan.source_lang,
                "target_lang": plan.target_lang, "segments": records}, ensure_ascii=False, indent=2), encoding="utf-8")
            translated_path.write_text("\n".join(translations), encoding="utf-8")
            self._attach_translations(timestamped_segments, translations, plan.target_lang)
            results["translation_records_path"] = str(records_path)
            results["steps"]["translate"] = {
                "duration": time.time() - t1,
                "segments": len(translations),
                "reused_segments": reused,
                "translated_segments": len(pending),
                "skipped": not pending,
                "output": str(translated_path),
                "records": str(records_path),
            }
        except Exception as e:
            if plan.workflow.get("graph_node"):
                raise
            results["steps"]["translate"] = {"error": str(e), "recoverable": True}
            results["step_errors"]["translate"] = str(e)
            translations = []

        return translations

    def _execute_tts(
        self,
        plan: PipelineExecutionPlan,
        timestamped_segments: list[dict[str, Any]],
        by_product_dir: Path,
        results: dict[str, Any],
        cancel_check=lambda: False,
    ) -> Path:
        """Run TTS synthesis stage."""
        from src.app.services.speech_service import get_speech_service

        tts_audio_path = by_product_dir / "tts_output.wav"

        # TTS reuse is owned by the fingerprinted recovery path. A filename alone
        # cannot attest to the current target language or the chosen translations.

        t1 = time.time()
        try:
            voice_segments = []
            for i, seg in enumerate(timestamped_segments, 1):
                translation_required = (plan.translation.enabled or plan.translation.common_options.get("reuse_only")
                                        or plan.translation.common_options.get("direct_tts"))
                if plan.workflow:
                    translation_required = False
                text = seg.get("translation") if translation_required else seg.get("text", "")
                if plan.workflow and not str(text or "").strip():
                    raise ValueError("所选配音文本含空条目，不能漏句继续合成")
                if translation_required and not str(text or "").strip():
                    raise ValueError("配音缺少有效目标译文，已停止以避免漏句")
                if translation_required and seg.get("translation_lang") != plan.target_lang:
                    raise ValueError("译文语言与目标语言不一致，已停止配音")
                if not text:
                    continue
                voice_segments.append({
                    "index": f"{i:04d}",
                    "text": text,
                    "original": seg.get("original", "") if plan.workflow else seg.get("text", ""),
                    "start_time": seg.get("start", 0),
                    "end_time": seg.get("end", seg.get("start", 0) + 5.0),
                })

            # Get reference duration from input
            if plan.workflow:
                reference_duration = float(plan.tts.common_options.get("reference_duration", 0))
            else:
                reference_duration = 0.0
                try:
                    import soundfile as sf
                    info = sf.info(plan.input_path)
                    reference_duration = info.duration
                except Exception:
                    pass
            snapshot = plan.tts.provider_options.get("speech_snapshot")
            if not snapshot:
                raise ValueError("缺少不可变配音配方快照，请从新工作台重新提交")
            assembly = get_speech_service().synthesize_timeline(
                snapshot, voice_segments, tts_audio_path, plan.task_id,
                cancel_check=cancel_check, reference_duration=reference_duration,
            )
            results["speech_experiment_id"] = assembly["experiment_id"]
            results["speech_assembly_id"] = assembly["id"]
            results["steps"]["tts"] = {
                "duration": time.time() - t1,
                "segments": len(voice_segments),
                "output": str(tts_audio_path),
                "engine": plan.tts.provider,
            }
        except Exception as e:
            if plan.workflow.get("graph_node"):
                raise
            results["steps"]["tts"] = {"error": str(e), "recoverable": True}
            results["step_errors"]["tts"] = str(e)
            if getattr(e, "task_error", None):
                raise
        finally:
            self._try_clear_gpu()

        results["tts_audio_path"] = str(tts_audio_path)
        return tts_audio_path

    def _execute_mix(
        self,
        plan: PipelineExecutionPlan,
        input_path: Path,
        tts_audio_path: Path,
        mix_path: Path,
        results: dict[str, Any],
    ) -> None:
        """Run audio mixing stage."""
        from src.mixer import Mixer

        t1 = time.time()
        try:
            if not tts_audio_path.exists():
                if plan.workflow.get("graph_node"):
                    raise ValueError("混音输入已消失，不能复制原音代替混音")
                import shutil
                shutil.copy2(str(input_path), str(mix_path))
                results["steps"]["mixer"] = {
                    "duration": time.time() - t1,
                    "output": str(mix_path),
                    "note": "TTS audio missing, copied original",
                }
                return

            mixer_factory = self._mixer_factory
            if mixer_factory:
                mixer = mixer_factory(
                    plan.mix.original_volume,
                    plan.mix.tts_volume_ratio,
                    plan.mix.tts_delay_ms,
                )
            else:
                mixer = Mixer(
                    original_volume=plan.mix.original_volume,
                    tts_volume_ratio=plan.mix.tts_volume_ratio,
                    tts_delay_ms=plan.mix.tts_delay_ms,
                )

            mixer.mix(
                original_path=str(input_path),
                tts_path=str(tts_audio_path),
                output_path=str(mix_path),
            )
            results["steps"]["mixer"] = {
                "duration": time.time() - t1, "output": str(mix_path)
            }
        except Exception as e:
            if plan.workflow.get("graph_node"):
                raise
            results["steps"]["mixer"] = {"error": str(e), "recoverable": False}
            results["step_errors"]["mixer"] = str(e)
            return

        # The audio is already complete. An ancillary history write cannot undo it.
        if results.get("speech_experiment_id"):
            try:
                from src.app.services.speech_service import get_speech_service
                get_speech_service().record_formal_mix(results["speech_experiment_id"], str(input_path), {
                    "original_volume": plan.mix.original_volume, "tts_volume_ratio": plan.mix.tts_volume_ratio,
                    "tts_delay_ms": plan.mix.tts_delay_ms,
                })
            except Exception as exc:
                warning = "混音音频已生成，但附加实验记录保存失败；音频结果仍可使用。"
                results["steps"]["mixer"]["warnings"] = [warning]
                logging.getLogger(__name__).warning("%s (%s)", warning, type(exc).__name__)

    def _export_subtitles(
        self,
        plan: PipelineExecutionPlan,
        timestamped_segments: list[dict[str, Any]],
        translations: list[str],
        by_product_dir: Path,
    ) -> str | None:
        """Export bilingual subtitles if we have segments."""
        if not timestamped_segments:
            return None

        try:
            from src.core.subtitles import SubtitleExporter

            export_format = plan.subtitle.export_format or "srt"
            task_name = Path(plan.input_path).stem
            target_only = (plan.translation.common_options.get("direct_tts") is True
                           and not all(str(seg.get("text", "")).strip() for seg in timestamped_segments))
            if plan.workflow:
                target_only = False
                suffix = "bilingual" if translations else plan.source_lang
            else:
                suffix = plan.target_lang if target_only else "bilingual"
            from src.core.subtitles.translation_reuse import unused_output
            output_path = unused_output(by_product_dir, f"{task_name}_{suffix}.{export_format}")

            exporter = SubtitleExporter()
            # Build segments with translations attached
            export_segments = []
            for i, seg in enumerate(timestamped_segments):
                entry = {
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "text": seg.get("text", ""),
                }
                if i < len(translations) and translations[i]:
                    entry["translation"] = translations[i]
                elif seg.get("translation"):
                    entry["translation"] = seg["translation"]
                if target_only:
                    entry["text"] = entry.pop("translation", "")
                export_segments.append(entry)

            result_path = exporter.export_bilingual_subtitle(
                export_segments, str(output_path), bilingual=bool(translations) and not target_only
            )
            return result_path
        except Exception:
            if plan.workflow.get("graph_node"):
                raise
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _attach_translations(
        segments: list[dict[str, Any]], translations: list[str], target_lang: str = ""
    ) -> None:
        """Attach translation texts to timestamped segments."""
        normalized = list(translations[: len(segments)])
        if len(normalized) < len(segments):
            normalized.extend([""] * (len(segments) - len(normalized)))
        for seg, trans in zip(segments, normalized, strict=True):
            if seg.get("translation") and seg["translation"] != trans:
                seg.setdefault("previous_translation", seg["translation"])
            seg["translation"] = trans
            seg["translation_lang"] = target_lang

    @staticmethod
    def _try_clear_gpu() -> None:
        """Attempt to clear GPU cache if torch is available."""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    @staticmethod
    def _resolve_output_paths(plan: PipelineExecutionPlan) -> tuple[Path, Path]:
        """Mirror legacy PathPlanner output semantics for new executor runs."""
        input_path = Path(plan.input_path)
        task_name = input_path.stem
        input_ext = ".wav" if plan.workflow else input_path.suffix or ".wav"

        if plan.output_mode == "batch" and plan.batch_root_dir:
            root_dir = Path(plan.batch_root_dir)
            main_product_dir = root_dir / "Main_Product"
            by_product_dir = root_dir / "BY_Product" / f"{task_name}_by"
        else:
            base_dir = Path(plan.output_dir) if plan.output_dir else input_path.parent / f"{task_name}_output"
            main_product_dir = base_dir
            by_product_dir = base_dir / "BY_Product"

        main_product_dir.mkdir(parents=True, exist_ok=True)
        by_product_dir.mkdir(parents=True, exist_ok=True)
        mix_path = main_product_dir / f"{task_name}_mix{input_ext}"
        return mix_path, by_product_dir
