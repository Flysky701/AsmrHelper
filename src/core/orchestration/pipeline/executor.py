"""Pipeline executor — runs stages via engine runtimes directly.

This module accepts a PipelineExecutionPlan and drives each enabled stage
through the corresponding EngineRuntime.
"""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Any, Callable

from .models import PipelineExecutionPlan


class PipelineExecutor:
    """Execute pipeline stages via engine runtimes directly.

    This is the new primary execution path that replaces the legacy
    Pipeline class. Each stage is executed through its corresponding
    EngineRuntime (SeparatorEngineRuntime, AsrEngineRuntime,
    LlmOperationRuntime, TtsEngineRuntime) plus the Mixer.
    """

    def __init__(
        self,
        *,
        separator=None,
        asr=None,
        llm=None,
        tts=None,
        mixer_factory=None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Initialize with optional injected runtimes (for testing).

        Args:
            separator: SeparatorEngineRuntime instance or mock
            asr: AsrEngineRuntime instance or mock
            llm: LlmOperationRuntime instance or mock
            tts: TtsEngineRuntime instance or mock
            mixer_factory: Callable that creates a Mixer given (original_volume, tts_volume_ratio, tts_delay_ms)
            cancel_event: Optional threading.Event for cooperative cancellation
        """
        self._separator = separator
        self._asr = asr
        self._llm = llm
        self._tts = tts
        self._mixer_factory = mixer_factory
        self._cancel_event = cancel_event

    def execute(
        self,
        plan: PipelineExecutionPlan,
        *,
        progress_callback: Callable[[str], None] | None = None,
        stage_callback: Callable[[str, float, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Run all enabled stages and return normalized results.

        Args:
            plan: The execution plan describing what stages to run
            progress_callback: Optional callback for progress messages

        Returns:
            Normalized result dictionary compatible with ArtifactResultMapper output
        """
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

        t0 = time.time()
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

        try:
            # === SEPARATION ===
            if plan.separation.enabled:
                _check_cancel()
                current_step += 1
                _report("separate", f"[{current_step}/{total_steps}] 人声分离...")
                vocal_path = self._execute_separation(plan, by_product_dir, results)

            # === ASR ===
            if plan.asr.enabled:
                _check_cancel()
                current_step += 1
                _report("asr", f"[{current_step}/{total_steps}] ASR 语音识别...")
                timestamped_segments = self._execute_asr(plan, vocal_path, by_product_dir, results)

            # === TRANSLATION ===
            if plan.translation.enabled:
                _check_cancel()
                current_step += 1
                _report("translate", f"[{current_step}/{total_steps}] 文本翻译...")
                translations = self._execute_translation(
                    plan, timestamped_segments, by_product_dir, results
                )

            # === TTS ===
            if plan.tts.enabled:
                _check_cancel()
                current_step += 1
                _report("tts", f"[{current_step}/{total_steps}] TTS 语音合成...")
                tts_audio_path = self._execute_tts(
                    plan, timestamped_segments, by_product_dir, results
                )

            # === MIX ===
            if plan.mix.enabled:
                _check_cancel()
                current_step += 1
                _report("mix", f"[{current_step}/{total_steps}] 混合音频...")
                self._execute_mix(plan, vocal_path, tts_audio_path, mix_path, results)

            # === SUBTITLE EXPORT ===
            if plan.subtitle.enabled:
                current_step += 1
                _report("export", f"[{current_step}/{total_steps}] 导出字幕...")
                exported_subtitle = self._export_subtitles(
                    plan, timestamped_segments, translations, by_product_dir
                )
                if exported_subtitle:
                    results["exported_subtitle"] = exported_subtitle

        except Exception as e:
            results["error"] = str(e)
            if not isinstance(e, RuntimeError) or "取消" not in str(e):
                _report("error", f"[ERROR] 流水线异常: {e}")
            raise
        finally:
            results["total_duration"] = time.time() - t0
            results["mix_path"] = str(mix_path) if mix_path.exists() else None
            results["primary_output"] = (
                results["mix_path"] or results.get("exported_subtitle")
            )

        return results

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
            results["steps"]["asr"] = {"error": str(e), "recoverable": True}
            results["step_errors"]["asr"] = str(e)
            segments = []
        finally:
            self._try_clear_gpu()

        return segments

    def _execute_translation(
        self,
        plan: PipelineExecutionPlan,
        timestamped_segments: list[dict[str, Any]],
        by_product_dir: Path,
        results: dict[str, Any],
    ) -> list[str]:
        """Run LLM translation stage."""
        from src.core.engines.llm import LlmOperationRuntime

        translated_path = by_product_dir / "translated.txt"

        if plan.skip_existing and translated_path.exists():
            translations = [
                line.strip()
                for line in translated_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self._attach_translations(timestamped_segments, translations)
            results["steps"]["translate"] = {
                "duration": 0.0, "segments": len(translations),
                "skipped": True, "output": str(translated_path),
            }
            return translations

        t1 = time.time()
        try:
            source_texts = [seg.get("text", "") for seg in timestamped_segments]
            translator = self._llm or LlmOperationRuntime()
            translations = translator.translate_texts(
                texts=source_texts,
                profile={
                    "provider": plan.translation.provider,
                    "model": plan.translation.model,
                    "common_options": plan.translation.common_options,
                    "provider_options": plan.translation.provider_options,
                },
                source_lang=plan.source_label,
                target_lang=plan.target_label,
            )
            translated_path.write_text("\n".join(translations), encoding="utf-8")
            self._attach_translations(timestamped_segments, translations)
            results["steps"]["translate"] = {
                "duration": time.time() - t1,
                "segments": len(translations),
                "output": str(translated_path),
            }
        except Exception as e:
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
    ) -> Path:
        """Run TTS synthesis stage."""
        from src.core.engines.tts import TtsEngineRuntime

        tts_audio_path = by_product_dir / "tts_output.wav"

        if plan.skip_existing and tts_audio_path.exists():
            results["steps"]["tts"] = {
                "duration": 0.0, "skipped": True, "output": str(tts_audio_path),
                "engine": plan.tts.provider,
            }
            results["tts_audio_path"] = str(tts_audio_path)
            return tts_audio_path

        t1 = time.time()
        try:
            voice_segments = []
            for i, seg in enumerate(timestamped_segments, 1):
                text = seg.get("translation", seg.get("text", ""))
                if not text:
                    continue
                voice_segments.append({
                    "index": f"{i:04d}",
                    "text": text,
                    "original": seg.get("text", ""),
                    "start_time": seg.get("start", 0),
                    "end_time": seg.get("end", seg.get("start", 0) + 5.0),
                })

            # Get reference duration from input
            reference_duration = 0.0
            sample_rate = 44100
            try:
                import soundfile as sf
                info = sf.info(plan.input_path)
                reference_duration = info.duration
                sample_rate = info.samplerate
            except Exception:
                pass

            runtime = self._tts or TtsEngineRuntime()
            runtime.synthesize_segments(
                segments=voice_segments,
                output_dir=str(by_product_dir),
                output_path=str(tts_audio_path),
                profile={
                    "provider": plan.tts.provider,
                    "model": plan.tts.model,
                    "common_options": plan.tts.common_options,
                    "provider_options": plan.tts.provider_options,
                },
                reference_duration=reference_duration,
                sample_rate=sample_rate,
            )
            results["steps"]["tts"] = {
                "duration": time.time() - t1,
                "segments": len(voice_segments),
                "output": str(tts_audio_path),
                "engine": plan.tts.provider,
            }
        except Exception as e:
            results["steps"]["tts"] = {"error": str(e), "recoverable": True}
            results["step_errors"]["tts"] = str(e)
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
            results["steps"]["mixer"] = {"error": str(e), "recoverable": False}
            results["step_errors"]["mixer"] = str(e)

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
            output_path = by_product_dir / f"{task_name}_bilingual.{export_format}"

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
                export_segments.append(entry)

            result_path = exporter.export_bilingual_subtitle(
                export_segments, str(output_path), bilingual=bool(translations)
            )
            return result_path
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _attach_translations(
        segments: list[dict[str, Any]], translations: list[str]
    ) -> None:
        """Attach translation texts to timestamped segments."""
        normalized = list(translations[: len(segments)])
        if len(normalized) < len(segments):
            normalized.extend([""] * (len(segments) - len(normalized)))
        for seg, trans in zip(segments, normalized):
            seg["translation"] = trans

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
        input_ext = input_path.suffix or ".wav"

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
