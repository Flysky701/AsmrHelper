"""Application-layer facade for voice profile and design operations."""

from __future__ import annotations

import logging
import threading

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

logger = logging.getLogger(__name__)


class VoiceService:
    """Stable application-facing facade for voice operations."""

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
        if not request.description:
            raise AppValidationError("description is required")
        if not request.name:
            raise AppValidationError("name is required")

        try:
            from src.core.tts.voice_designer import get_voice_designer

            designer = get_voice_designer()
            profile = designer.design_and_generate(
                description=request.description,
                name=request.name,
                ref_text=request.ref_text or None,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return VoiceDesignResult(
            profile_id=profile.id,
            name=profile.name,
            category=profile.category,
            ref_audio_path=profile.get_ref_audio_path(),
            prompt_cache_path=profile.get_prompt_cache_path(),
        )

    # --- Voice Clone ---

    def clone_voice(self, request: VoiceCloneRequest) -> VoiceCloneResult:
        if not request.audio_path:
            raise AppValidationError("audio_path is required")
        if not request.name:
            raise AppValidationError("name is required")

        try:
            from src.core.tts.voice_designer import get_voice_designer
            from pathlib import Path

            audio_path = Path(request.audio_path)
            if not audio_path.exists():
                raise AppValidationError(f"audio file does not exist: {request.audio_path}")

            designer = get_voice_designer()
            profile = designer.clone_from_audio(
                audio_path=str(audio_path),
                name=request.name,
                ref_text=request.ref_text or None,
            )
        except AppValidationError:
            raise
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return VoiceCloneResult(
            profile_id=profile.id,
            name=profile.name,
            category=profile.category,
            ref_audio_path=profile.get_ref_audio_path(),
            prompt_cache_path=profile.get_prompt_cache_path(),
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
        if not request.profile_id:
            raise AppValidationError("profile_id is required")

        profile = self._get_profile_or_raise(request.profile_id)

        try:
            from src.core.tts.voice_designer import get_voice_designer

            designer = get_voice_designer()
            audio_path = designer.preview_profile(
                profile=profile,
                text=request.text or None,
                speed=request.speed,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return VoicePreviewResult(
            profile_id=request.profile_id,
            audio_path=audio_path,
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
