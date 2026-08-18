"""Application-layer facade for voice profile and design operations."""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from ..dto import (
    SegmentAnalyzeRequest,
    SegmentAnalyzeResult,
    SegmentInfo,
    VoiceCloneRequest,
    VoiceCloneResult,
    VoiceDesignRequest,
    VoiceDesignResult,
    VoiceProfileSummary,
    VoiceProfileView,
    VoicePreviewRequest,
    VoicePreviewResult,
)
from ..errors import AppExecutionError, AppValidationError
from src.config import PROJECT_ROOT
from src.core.runtime import RuntimeRouter, get_runtime_router
from src.core.tasks import TaskDispatcher

from .artifact_service import ArtifactService, get_artifact_service
from .task_service import TaskService, get_task_dispatcher, get_task_service

logger = logging.getLogger(__name__)

_VOICE_TASK_LOCK = threading.Lock()
_VOICE_TASK_LOCK_POLL_SECONDS = 0.1


class VoiceService:
    """Stable application-facing facade for voice operations."""

    def __init__(
        self,
        task_service: TaskService | None = None,
        dispatcher: TaskDispatcher | None = None,
        artifact_service: ArtifactService | None = None,
        runtime_router: RuntimeRouter | None = None,
    ) -> None:
        self._task_service = task_service or get_task_service()
        self._dispatcher = dispatcher or (
            get_task_dispatcher()
            if task_service is None
            else TaskDispatcher(
                self._task_service.registry,
                task_service=self._task_service,
            )
        )
        self._artifact_service = artifact_service or get_artifact_service()
        self._runtime_router = runtime_router or get_runtime_router()
        for task_type in ("voice.design", "voice.clone", "voice.preview"):
            self._dispatcher.register_executor(task_type, self._execute_voice_task)

    # --- Profile CRUD ---

    def list_profiles(self, kind: str | None = None) -> list[VoiceProfileSummary]:
        try:
            from src.core.tts.voice_profile import get_voice_manager

            manager = get_voice_manager()
            if kind == "preset":
                profiles = manager.get_presets()
            elif kind == "custom":
                profiles = manager.get_customs()
            elif kind == "clone":
                profiles = manager.get_clones()
            else:
                profiles = manager.get_all()
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return [
            VoiceProfileSummary(
                id=p.id,
                name=p.name,
                category=p.category,
                engine=p.engine,
                description=p.description,
                available=p.is_available(),
            )
            for p in profiles
        ]

    def get_profile(self, profile_id: str) -> VoiceProfileView:
        profile = self._get_profile_or_raise(profile_id)
        return VoiceProfileView(
            id=profile.id,
            name=profile.name,
            category=profile.category,
            engine=profile.engine,
            description=profile.description,
            speaker=profile.speaker,
            instruct=profile.instruct,
            design_instruct=profile.design_instruct,
            ref_audio=profile.ref_audio,
            generated=profile.generated,
            available=profile.is_available(),
        )

    def delete_profile(self, profile_id: str) -> bool:
        try:
            from src.core.tts.voice_profile import get_voice_manager

            manager = get_voice_manager()
            result = manager.delete_profile(profile_id)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        if not result:
            raise AppValidationError(f"cannot delete profile: {profile_id}")
        return result

    # --- Voice Design ---

    def design_voice(self, request: VoiceDesignRequest) -> VoiceDesignResult:
        description = request.description.strip()
        name = request.name.strip()
        if not description:
            raise AppValidationError("description is required")
        if not name:
            raise AppValidationError("name is required")

        try:
            result = self._run_voice_task(
                "design",
                {
                    "description": description,
                    "name": name,
                    "ref_text": request.ref_text.strip() or None,
                },
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except AppValidationError:
            raise
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return VoiceDesignResult(
            task_id=result["task_id"],
            profile_id=result["profile_id"],
            name=result["name"],
            category=result["category"],
            ref_audio_path=result.get("ref_audio_path", ""),
            prompt_cache_path=result.get("prompt_cache_path", ""),
        )

    def submit_design_voice(self, request: VoiceDesignRequest):
        description = request.description.strip()
        name = request.name.strip()
        if not description:
            raise AppValidationError("description is required")
        if not name:
            raise AppValidationError("name is required")
        return self._submit_voice_task(
            "design",
            {
                "description": description,
                "name": name,
                "ref_text": request.ref_text.strip() or None,
            },
        )

    # --- Voice Clone ---

    def clone_voice(self, request: VoiceCloneRequest) -> VoiceCloneResult:
        if not request.audio_path:
            raise AppValidationError("audio_path is required")
        name = request.name.strip()
        if not name:
            raise AppValidationError("name is required")

        audio_path = Path(request.audio_path)
        if not audio_path.is_file():
            raise AppValidationError(f"audio file does not exist: {request.audio_path}")
        ref_text = "" if request.x_vector_only_mode else (request.ref_text or "").strip()
        if not request.x_vector_only_mode and not ref_text:
            raise AppValidationError(
                "ref_text is required for ICL voice cloning; provide the exact "
                "reference transcript or enable x_vector_only_mode"
            )
        try:
            result = self._run_voice_task(
                "clone",
                {
                    "audio_path": str(audio_path),
                    "name": name,
                    "ref_text": ref_text or None,
                    "x_vector_only_mode": request.x_vector_only_mode,
                },
            )
        except AppValidationError:
            raise
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return VoiceCloneResult(
            task_id=result["task_id"],
            profile_id=result["profile_id"],
            name=result["name"],
            category=result["category"],
            ref_audio_path=result.get("ref_audio_path", ""),
            prompt_cache_path=result.get("prompt_cache_path", ""),
        )

    def submit_clone_voice(self, request: VoiceCloneRequest):
        if not request.audio_path:
            raise AppValidationError("audio_path is required")
        name = request.name.strip()
        if not name:
            raise AppValidationError("name is required")
        audio_path = Path(request.audio_path)
        if not audio_path.is_file():
            raise AppValidationError(f"audio file does not exist: {request.audio_path}")
        ref_text = "" if request.x_vector_only_mode else (request.ref_text or "").strip()
        if not request.x_vector_only_mode and not ref_text:
            raise AppValidationError(
                "ref_text is required for ICL voice cloning; provide the exact "
                "reference transcript or enable x_vector_only_mode"
            )
        return self._submit_voice_task(
            "clone",
            {
                "audio_path": str(audio_path),
                "name": name,
                "ref_text": ref_text or None,
                "x_vector_only_mode": request.x_vector_only_mode,
            },
        )

    # --- Segment Analysis ---

    def analyze_segments(self, request: SegmentAnalyzeRequest) -> SegmentAnalyzeResult:
        if not request.audio_path:
            raise AppValidationError("audio_path is required")

        try:
            from src.core.tts.audio_preprocessor import get_audio_preprocessor

            preprocessor = get_audio_preprocessor()
            result = preprocessor.analyze_segments(
                audio_path=request.audio_path,
                subtitle_path=request.subtitle_path,
                audio_language=request.audio_language,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        segments = [
            SegmentInfo(
                index=seg.get("index", i),
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
                text=str(seg.get("text", "")),
                duration=float(seg.get("duration", 0.0)),
                score=int(seg.get("score", 0)),
                label=str(seg.get("label", "")),
                details=seg.get("details", {}),
            )
            for i, seg in enumerate(result.get("segments", []))
        ]

        return SegmentAnalyzeResult(
            audio_path=request.audio_path,
            mode=result.get("mode", ""),
            segments=segments,
            recommended_indices=result.get("recommended_indices", []),
            warnings=result.get("warnings", []),
        )

    # --- Voice Preview ---

    def preview_voice(self, request: VoicePreviewRequest) -> VoicePreviewResult:
        profile_id = request.profile_id.strip()
        text = request.text.strip()
        if not profile_id:
            raise AppValidationError("profile_id is required")
        if not text:
            raise AppValidationError("text is required")
        language = self._normalize_preview_language(request.language)

        self._get_profile_or_raise(profile_id)

        try:
            result = self._run_voice_task(
                "preview",
                {
                    "profile_id": profile_id,
                    "text": text,
                    "speed": request.speed,
                    "language": language,
                    "output_path": str(
                        PROJECT_ROOT / ".tmp" / f"voice-preview-{profile_id}.wav"
                    ),
                },
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return VoicePreviewResult(
            task_id=result["task_id"],
            profile_id=profile_id,
            audio_path=result["audio_path"],
        )

    def submit_preview_voice(self, request: VoicePreviewRequest):
        profile_id = request.profile_id.strip()
        text = request.text.strip()
        if not profile_id:
            raise AppValidationError("profile_id is required")
        if not text:
            raise AppValidationError("text is required")
        language = self._normalize_preview_language(request.language)
        self._get_profile_or_raise(profile_id)
        return self._submit_voice_task(
            "preview",
            {
                "profile_id": profile_id,
                "text": text,
                "speed": request.speed,
                "language": language,
            },
        )

    def _run_voice_task(self, operation: str, payload: dict) -> dict:
        task = self._create_voice_task(operation, payload)
        result = self._dispatcher.run(task.task_id)
        if not isinstance(result, dict):
            raise AppExecutionError(f"voice task returned no result: {task.task_id}")
        result["task_id"] = task.task_id
        return result

    def _submit_voice_task(self, operation: str, payload: dict):
        task = self._create_voice_task(operation, payload)
        return self._dispatcher.submit(task.task_id)

    def _create_voice_task(self, operation: str, payload: dict):
        if operation == "preview":
            payload = {
                **payload,
                "output_path": str(
                    PROJECT_ROOT / ".tmp" / f"voice-preview-{uuid.uuid4().hex}.wav"
                ),
            }
        task, _ = self._task_service.create_task_spec(
            task_type=f"voice.{operation}",
            task_source="voice-lab",
            session_id="",
            input_asset_id=str(
                payload.get("audio_path") or payload.get("profile_id") or ""
            ),
            execution_profile={"operation": operation, **payload},
        )
        return task

    def _execute_voice_task(self, task_spec, context):
        profile = dict(task_spec.execution_profile)
        operation = str(profile.get("operation") or task_spec.task_type.split(".")[-1])
        if operation not in {"design", "clone", "preview"}:
            raise AppValidationError(f"unsupported voice task operation: {operation}")
        if context.cancellation_requested:
            raise RuntimeError("cancelled by user")
        context.update_progress(
            0.0,
            message=f"waiting for voice {operation} runtime",
            stage=operation,
        )

        while not _VOICE_TASK_LOCK.acquire(timeout=_VOICE_TASK_LOCK_POLL_SECONDS):
            if context.cancellation_requested:
                raise RuntimeError("cancelled by user")

        try:
            if context.cancellation_requested:
                raise RuntimeError("cancelled by user")
            context.update_progress(
                0.0,
                message=f"running voice {operation}",
                stage=operation,
            )
            return self._execute_serialized_voice_operation(
                operation=operation,
                profile=profile,
                task_id=task_spec.task_id,
            )
        finally:
            _VOICE_TASK_LOCK.release()

    def _execute_serialized_voice_operation(
        self,
        *,
        operation: str,
        profile: dict,
        task_id: str,
    ) -> dict:
        if operation == "design":
            result = self._runtime_router.design_voice(profile)
            self._restore_profile(result)
            self._register_voice_artifacts(task_id, result)
            return {
                **result,
                "primary_output": result.get("ref_audio_path", ""),
                "artifact_set_id": task_id,
            }
        if operation == "clone":
            result = self._runtime_router.clone_voice(profile)
            self._restore_profile(result)
            self._register_voice_artifacts(task_id, result)
            return {
                **result,
                "primary_output": result.get("prompt_cache_path", ""),
                "artifact_set_id": task_id,
            }
        if operation == "preview":
            audio_path = self._runtime_router.preview_voice(profile)
            self._artifact_service.register_artifact(
                task_id=task_id,
                artifact_type="audio.voice_preview",
                path=str(audio_path),
                label="Voice Preview",
                preview_kind="audio",
                stage="preview",
                is_primary=True,
            )
            return {
                "profile_id": profile.get("profile_id", ""),
                "audio_path": str(audio_path),
                "primary_output": str(audio_path),
                "artifact_set_id": task_id,
            }
        raise AppValidationError(f"unsupported voice task operation: {operation}")

    @staticmethod
    def _normalize_preview_language(language: str) -> str:
        from src.core.tts import normalize_qwen3_language

        try:
            normalized = normalize_qwen3_language(language)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        return {
            "Auto": "auto",
            "Chinese": "zh",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "German": "de",
            "French": "fr",
            "Russian": "ru",
            "Portuguese": "pt",
            "Spanish": "es",
            "Italian": "it",
        }[normalized]

    @staticmethod
    def _restore_profile(result: dict) -> None:
        from src.core.tts.voice_profile import VoiceProfile, get_voice_manager

        profile = VoiceProfile(
            id=str(result["profile_id"]),
            name=str(result["name"]),
            category=str(result["category"]),
            engine=str(result.get("engine", "qwen3_clone")),
            description=str(result.get("description", "")),
            design_instruct=str(result.get("design_instruct", "")),
            ref_audio=str(result.get("ref_audio_path", "")),
            prompt_cache=str(result.get("prompt_cache_path", "")),
            generated=True,
        )
        get_voice_manager().add_profile(profile)

    def _register_voice_artifacts(self, task_id: str, result: dict) -> None:
        for artifact_type, path, label in (
            ("audio.voice_reference", result.get("ref_audio_path"), "Voice Reference"),
            ("voice.prompt_cache", result.get("prompt_cache_path"), "Voice Prompt Cache"),
        ):
            if path:
                self._artifact_service.register_artifact(
                    task_id=task_id,
                    artifact_type=artifact_type,
                    path=str(path),
                    label=label,
                    stage="voice",
                    is_primary=artifact_type.startswith("audio."),
                )

    # --- Internal helpers ---

    def _get_profile_or_raise(self, profile_id: str):
        try:
            from src.core.tts.voice_profile import get_voice_manager

            manager = get_voice_manager()
            profile = manager.get_by_id(profile_id)
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        if profile is None:
            raise AppValidationError(f"voice profile not found: {profile_id}")
        return profile


_service: VoiceService | None = None
_lock = threading.Lock()


def get_voice_service() -> VoiceService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = VoiceService()
    return _service
