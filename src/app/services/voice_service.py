"""Application-layer facade for voice profile and design operations."""

from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

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
from ..dto.voice import VoiceCloneCandidate
from ..errors import AppExecutionError, AppValidationError
from src.config import PROJECT_ROOT
from src.core.runtime import RuntimeRouter, get_runtime_router
from src.core.tasks import TaskDispatcher

from .artifact_service import ArtifactService, get_artifact_service
from .task_service import TaskService, get_task_dispatcher, get_task_service

logger = logging.getLogger(__name__)

_VOICE_TASK_LOCK = threading.Lock()
_VOICE_TASK_LOCK_POLL_SECONDS = 0.1
_VOICE_ANALYSIS_SESSIONS: dict[str, dict[str, Any]] = {}
_VOICE_ANALYSIS_SESSIONS_LOCK = threading.Lock()
_VOICE_ANALYSIS_TTL_SECONDS = 2 * 60 * 60
_VOICE_ANALYSIS_MAX_SESSIONS = 32
_VOICE_CLONE_TASK_STAGING: dict[str, dict[str, Any]] = {}
_VOICE_CLONE_TASK_STAGING_LOCK = threading.Lock()


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
        self._prune_orphan_analysis_dirs()
        self._prune_orphan_clone_staging_dirs()

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
        name = request.name.strip()
        if not name:
            raise AppValidationError("name is required")
        self._prune_expired_clone_task_staging()
        self._prune_orphan_clone_staging_dirs()
        audio_path, ref_text, clone_manifest, staging_dir = self._resolve_clone_reference(request)
        payload = {
            "audio_path": str(audio_path),
            "name": name,
            "ref_text": ref_text or None,
            "x_vector_only_mode": request.x_vector_only_mode,
        }
        if clone_manifest is not None:
            payload["clone_manifest"] = clone_manifest
        if staging_dir is not None:
            payload["_clone_staging_dir"] = str(staging_dir)
            payload["_clone_staging_fingerprint"] = self._fingerprint_file(audio_path)
        try:
            result = self._run_voice_task(
                "clone",
                payload,
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
        name = request.name.strip()
        if not name:
            raise AppValidationError("name is required")
        self._prune_expired_clone_task_staging()
        self._prune_orphan_clone_staging_dirs()
        audio_path, ref_text, clone_manifest, staging_dir = self._resolve_clone_reference(request)
        payload = {
            "audio_path": str(audio_path),
            "name": name,
            "ref_text": ref_text or None,
            "x_vector_only_mode": request.x_vector_only_mode,
        }
        if clone_manifest is not None:
            payload["clone_manifest"] = clone_manifest
        if staging_dir is not None:
            payload["_clone_staging_dir"] = str(staging_dir)
            payload["_clone_staging_fingerprint"] = self._fingerprint_file(audio_path)
        return self._submit_voice_task(
            "clone",
            payload,
        )

    def _resolve_clone_reference(
        self,
        request: VoiceCloneRequest,
    ) -> tuple[Path, str, dict[str, Any] | None, Path | None]:
        analysis_id = (request.analysis_id or "").strip()
        candidate_id = (request.candidate_id or "").strip()
        if bool(analysis_id) != bool(candidate_id):
            raise AppValidationError("analysis_id and candidate_id must be provided together")

        if not analysis_id:
            if not request.audio_path:
                raise AppValidationError("audio_path is required")
            audio_path = Path(request.audio_path)
            if not audio_path.is_file():
                raise AppValidationError(f"audio file does not exist: {request.audio_path}")
            ref_text = "" if request.x_vector_only_mode else (request.ref_text or "").strip()
            if not request.x_vector_only_mode and not ref_text:
                raise AppValidationError(
                    "ref_text is required for ICL voice cloning; provide the exact "
                    "reference transcript or enable x_vector_only_mode"
                )
            return audio_path, ref_text, None, None

        self._prune_analysis_sessions()
        with _VOICE_ANALYSIS_SESSIONS_LOCK:
            session = _VOICE_ANALYSIS_SESSIONS.get(analysis_id)
            if session is None:
                raise AppValidationError(f"voice analysis session not found: {analysis_id}")

            candidate = session["candidates"].get(candidate_id)
            if candidate is None:
                raise AppValidationError(f"voice analysis candidate not found: {candidate_id}")
            if candidate.get("eligible") is not True:
                reasons = [str(reason) for reason in candidate.get("reasons", [])]
                detail = "；".join(reasons) or "未通过克隆候选硬性校验"
                raise AppValidationError(f"voice analysis candidate is not eligible: {detail}")
            if bool(session["x_vector_only_mode"]) != bool(request.x_vector_only_mode):
                raise AppValidationError("clone mode does not match the voice analysis session")

            if not request.audio_path:
                raise AppValidationError("audio_path is required")
            requested_source = Path(request.audio_path)
            if not requested_source.is_file():
                raise AppValidationError(f"audio file does not exist: {request.audio_path}")

            requested_fingerprint = self._fingerprint_file(requested_source)
            expected_fingerprint = str(session["source_fingerprint"])
            if requested_fingerprint != expected_fingerprint:
                raise AppValidationError(
                    "audio fingerprint does not match the voice analysis session"
                )

            session_source = Path(str(session["source_path"]))
            if not session_source.is_file():
                raise AppValidationError("voice analysis source audio is no longer available")
            if session_source.resolve() == requested_source.resolve():
                current_source_fingerprint = requested_fingerprint
            else:
                current_source_fingerprint = self._fingerprint_file(session_source)
            if current_source_fingerprint != expected_fingerprint:
                raise AppValidationError("voice analysis source audio changed after analysis")
            if str(candidate["source_fingerprint"]) != expected_fingerprint:
                raise AppValidationError(
                    "voice analysis candidate is not bound to the source audio"
                )

            candidate_path = Path(str(candidate["preview_audio_path"]))
            if not candidate_path.is_file():
                raise AppValidationError("voice analysis candidate audio is no longer available")
            candidate_fingerprint = str(candidate["preview_fingerprint"])
            if self._fingerprint_file(candidate_path) != candidate_fingerprint:
                raise AppValidationError("voice analysis candidate audio changed after analysis")

            confirmed_text = (request.confirmed_text or "").strip()
            if not request.x_vector_only_mode and not confirmed_text:
                raise AppValidationError(
                    "confirmed_text is required for an ICL voice analysis candidate"
                )
            staged_path, staging_dir = self._stage_clone_reference(
                candidate_path,
                expected_fingerprint=candidate_fingerprint,
            )
            session["created_at"] = time.monotonic()
            clone_manifest = {
                "analysis_id": analysis_id,
                "candidate_id": candidate_id,
                "original_source_path": str(session_source.resolve()),
                "source_fingerprint": expected_fingerprint,
                "candidate_fingerprint": candidate_fingerprint,
                "source_variant": str(candidate["source_variant"]),
                "start": float(candidate["start"]),
                "end": float(candidate["end"]),
                "original_text": str(candidate["text"]),
                "confirmed_text": ("" if request.x_vector_only_mode else confirmed_text),
                "score": int(candidate["score"]),
                "eligible": True,
                "reasons": list(candidate["reasons"]),
                "details": dict(candidate["details"]),
            }
            return (
                staged_path,
                "" if request.x_vector_only_mode else confirmed_text,
                clone_manifest,
                staging_dir,
            )

    # --- Segment Analysis ---

    def analyze_segments(self, request: SegmentAnalyzeRequest) -> SegmentAnalyzeResult:
        if not request.audio_path:
            raise AppValidationError("audio_path is required")

        source_path = Path(request.audio_path)
        if not source_path.is_file():
            raise AppValidationError(f"audio file does not exist: {request.audio_path}")

        self._prune_analysis_sessions(reserve=1)
        self._prune_orphan_analysis_dirs()
        analysis_id = f"voice-analysis-{uuid.uuid4().hex}"
        analysis_dir = PROJECT_ROOT / ".tmp" / "voice-analysis" / analysis_id
        analysis_dir.mkdir(parents=True, exist_ok=False)
        analysis_succeeded = False

        try:
            source_fingerprint = self._fingerprint_file(source_path)
            analyzed_audio_path = source_path
            source_variant = "original"
            if request.separate_vocals:
                analyzed_audio_path = Path(
                    self._separate_vocals_for_analysis(source_path, analysis_dir)
                )
                if not analyzed_audio_path.is_file():
                    raise AppExecutionError("vocal separation did not produce an audio file")
                source_variant = "separated_vocals"

            from src.core.tts.audio_preprocessor import AudioPreprocessor

            preprocessor = AudioPreprocessor(output_dir=str(analysis_dir))
            result = preprocessor.analyze_segments(
                audio_path=str(analyzed_audio_path),
                subtitle_path=request.subtitle_path,
                audio_language=request.audio_language,
                require_text=not request.x_vector_only_mode,
            )

            raw_segments = list(result.get("segments", []))
            requested_recommended_indices = {
                int(index) for index in result.get("recommended_indices", [])
            }
            recommended_indices: list[int] = []
            candidate_dir = analysis_dir / "candidates"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            segments: list[SegmentInfo] = []
            candidates: list[VoiceCloneCandidate] = []
            session_candidates: dict[str, dict[str, Any]] = {}
            recommended_candidate_id: str | None = None

            for position, raw_segment in enumerate(raw_segments):
                segment = dict(raw_segment)
                index = int(segment.get("index", position))
                start = float(segment.get("start", 0.0))
                end = float(segment.get("end", 0.0))
                duration = float(segment.get("duration", max(0.0, end - start)))
                text = str(segment.get("text", ""))
                score, label, eligible, quality_reasons, details = self._resolve_segment_quality(
                    preprocessor,
                    segment,
                )
                segment_info = SegmentInfo(
                    index=index,
                    start=start,
                    end=end,
                    text=text,
                    duration=duration,
                    score=score,
                    label=label,
                    eligible=eligible,
                    reasons=quality_reasons,
                    details=details,
                )
                segments.append(segment_info)

                candidate_id = f"candidate-{position + 1:04d}"
                preview_path = candidate_dir / f"{candidate_id}.wav"
                self._materialize_candidate_audio(
                    segment=segment,
                    fallback_audio_path=Path(
                        str(result.get("converted_audio_path") or analyzed_audio_path)
                    ),
                    output_path=preview_path,
                    start=start,
                    end=end,
                )
                is_recommended = eligible and index in requested_recommended_indices
                reasons = self._candidate_reasons(
                    quality_reasons,
                    eligible=eligible,
                    label=label,
                    score=score,
                    is_recommended=is_recommended,
                    source_variant=source_variant,
                )
                candidate = VoiceCloneCandidate(
                    candidate_id=candidate_id,
                    source_variant=source_variant,
                    start=start,
                    end=end,
                    text=text,
                    score=score,
                    label=label,
                    eligible=eligible,
                    details=details,
                    reasons=reasons,
                    preview_audio_path=str(preview_path),
                )
                candidates.append(candidate)
                session_candidates[candidate_id] = {
                    "preview_audio_path": str(preview_path),
                    "preview_fingerprint": self._fingerprint_file(preview_path),
                    "source_fingerprint": source_fingerprint,
                    "source_variant": source_variant,
                    "start": start,
                    "end": end,
                    "text": text,
                    "score": score,
                    "eligible": eligible,
                    "reasons": list(reasons),
                    "details": dict(details),
                }
                if is_recommended:
                    recommended_indices.append(index)
                    if not recommended_candidate_id:
                        recommended_candidate_id = candidate_id

            warnings = list(result.get("warnings", []))
            if request.separate_vocals:
                warnings.append("候选片段来自分离后的人声音轨")

            response = SegmentAnalyzeResult(
                audio_path=request.audio_path,
                mode=result.get("mode", ""),
                segments=segments,
                recommended_indices=recommended_indices,
                warnings=warnings,
                analysis_id=analysis_id,
                source_fingerprint=source_fingerprint,
                candidates=candidates,
                recommended_candidate_id=recommended_candidate_id,
            )
            with _VOICE_ANALYSIS_SESSIONS_LOCK:
                _VOICE_ANALYSIS_SESSIONS[analysis_id] = {
                    "analysis_id": analysis_id,
                    "source_path": str(source_path.resolve()),
                    "source_fingerprint": source_fingerprint,
                    "x_vector_only_mode": bool(request.x_vector_only_mode),
                    "analysis_dir": str(analysis_dir),
                    "created_at": time.monotonic(),
                    "candidates": session_candidates,
                }
            self._prune_analysis_sessions()
            analysis_succeeded = True
            return response
        except AppValidationError:
            raise
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except AppExecutionError:
            raise
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc
        finally:
            if not analysis_succeeded:
                with _VOICE_ANALYSIS_SESSIONS_LOCK:
                    _VOICE_ANALYSIS_SESSIONS.pop(analysis_id, None)
                self._remove_analysis_dir(analysis_dir)

    @staticmethod
    def _resolve_segment_quality(
        preprocessor: Any,
        segment: dict[str, Any],
    ) -> tuple[int, str, bool, list[str], dict[str, Any]]:
        evaluated: dict[str, Any] = {}
        evaluator = getattr(preprocessor, "evaluate_segment_quality", None)
        if callable(evaluator):
            try:
                evaluated = dict(evaluator(segment) or {})
            except Exception:
                evaluated = {}

        raw_score = segment.get("score")
        if raw_score is None:
            raw_score = segment.get("quality_score")
        if raw_score is None:
            raw_score = evaluated.get("score", 0)

        raw_label = segment.get("label")
        if raw_label is None or raw_label == "":
            raw_label = segment.get("quality_label")
        if raw_label is None or raw_label == "":
            raw_label = evaluated.get("label", "")

        raw_details = segment.get("details")
        if not isinstance(raw_details, dict) or not raw_details:
            raw_details = evaluated.get("details", {})
        details = dict(raw_details) if isinstance(raw_details, dict) else {}
        details.setdefault("duration", float(segment.get("duration", 0.0)))
        if "rms" in segment:
            details.setdefault("rms", float(segment["rms"]))
        raw_eligible = segment.get("eligible")
        if raw_eligible is None:
            raw_eligible = evaluated.get("eligible", False)
        eligible = raw_eligible is True

        raw_reasons = segment.get("reasons")
        if raw_reasons is None:
            raw_reasons = evaluated.get("reasons", [])
        if isinstance(raw_reasons, str):
            reasons = [raw_reasons] if raw_reasons.strip() else []
        elif isinstance(raw_reasons, list):
            reasons = [str(reason) for reason in raw_reasons if str(reason).strip()]
        else:
            reasons = []
        if not eligible and not reasons:
            reasons.append("未通过克隆候选硬性校验")
        return int(raw_score), str(raw_label or ""), eligible, reasons, details

    @staticmethod
    def _candidate_reasons(
        quality_reasons: list[str],
        *,
        eligible: bool,
        label: str,
        score: int,
        is_recommended: bool,
        source_variant: str,
    ) -> list[str]:
        reasons = list(quality_reasons)
        if is_recommended:
            reasons.append("自动推荐片段")
        elif not eligible and not reasons:
            reasons.append("未通过克隆候选硬性校验")
        elif label:
            reasons.append(f"质量评级：{label}")
        elif score < 60:
            reasons.append("综合质量评分较低")
        if source_variant == "separated_vocals":
            reasons.append("使用分离后的人声音轨")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _materialize_candidate_audio(
        *,
        segment: dict[str, Any],
        fallback_audio_path: Path,
        output_path: Path,
        start: float,
        end: float,
    ) -> None:
        segment_path = Path(str(segment.get("path") or ""))
        if segment_path.is_file():
            shutil.copy2(segment_path, output_path)
            return
        if not fallback_audio_path.is_file():
            raise AppExecutionError("candidate audio source is not available")

        import soundfile as sf

        audio, sample_rate = sf.read(str(fallback_audio_path))
        start_sample = max(0, int(start * sample_rate))
        end_sample = min(len(audio), int(end * sample_rate))
        if end_sample <= start_sample:
            raise AppExecutionError("candidate audio range is empty")
        sf.write(str(output_path), audio[start_sample:end_sample], sample_rate)

    @staticmethod
    def _separate_vocals_for_analysis(
        source_path: Path,
        analysis_dir: Path,
    ) -> str:
        from src.config import config
        from src.core.engines import SeparatorEngineRuntime

        outputs = SeparatorEngineRuntime().separate(
            input_path=str(source_path),
            output_dir=str(analysis_dir / "separated"),
            model=str(config.get("processing.vocal_model", "htdemucs")),
            stems=["vocals"],
        )
        return str(outputs.get("vocals") or "")

    @staticmethod
    def _fingerprint_file(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise AppValidationError(f"cannot read audio file: {path}") from exc
        return f"sha256:{digest.hexdigest()}"

    def _stage_clone_reference(
        self,
        source_path: Path,
        *,
        expected_fingerprint: str,
    ) -> tuple[Path, Path]:
        staging_dir = (
            PROJECT_ROOT / ".tmp" / "voice-clone-tasks" / f"voice-clone-stage-{uuid.uuid4().hex}"
        )
        suffix = source_path.suffix.lower() or ".wav"
        staged_path = staging_dir / f"reference{suffix}"
        try:
            staging_dir.mkdir(parents=True, exist_ok=False)
            shutil.copy2(source_path, staged_path)
            if self._fingerprint_file(staged_path) != expected_fingerprint:
                raise AppValidationError(
                    "staged voice clone reference fingerprint does not match candidate"
                )
        except Exception:
            self._remove_clone_staging_dir(staging_dir)
            raise
        return staged_path, staging_dir

    @staticmethod
    def _remove_clone_staging_dir(path: str | Path) -> None:
        """Remove only one service-created task staging directory."""
        if not path:
            return
        try:
            project_root = PROJECT_ROOT.resolve()
            staging_root = (PROJECT_ROOT / ".tmp" / "voice-clone-tasks").resolve()
            target = Path(path).resolve()
        except (OSError, RuntimeError) as exc:
            logger.warning("cannot resolve voice clone staging path %s: %s", path, exc)
            return
        if not staging_root.is_relative_to(project_root):
            logger.warning(
                "refusing voice clone staging cleanup outside project root: %s",
                staging_root,
            )
            return
        if target.parent != staging_root or not target.name.startswith("voice-clone-stage-"):
            logger.warning("refusing to remove unexpected clone staging path: %s", target)
            return
        shutil.rmtree(target, ignore_errors=True)

    @classmethod
    def _claim_clone_task_staging(cls, task_id: str, staging_dir: Path) -> None:
        with _VOICE_CLONE_TASK_STAGING_LOCK:
            if task_id in _VOICE_CLONE_TASK_STAGING:
                raise AppExecutionError(f"voice clone task staging is already claimed: {task_id}")
            _VOICE_CLONE_TASK_STAGING[task_id] = {
                "staging_dir": str(staging_dir),
                "created_at": time.monotonic(),
            }

    def _adopt_retry_clone_staging(self, task_spec: Any) -> None:
        retry_of_task_id = str(getattr(task_spec, "retry_of_task_id", "") or "")
        if not retry_of_task_id:
            return

        ancestor_ids: list[str] = []
        visited: set[str] = set()
        current_id = retry_of_task_id
        while current_id and current_id not in visited:
            visited.add(current_id)
            ancestor_ids.append(current_id)
            try:
                parent_spec = self._task_service.get_task_spec(current_id)
            except Exception:
                break
            current_id = str(getattr(parent_spec, "retry_of_task_id", "") or "")

        with _VOICE_CLONE_TASK_STAGING_LOCK:
            if task_spec.task_id in _VOICE_CLONE_TASK_STAGING:
                return
            for ancestor_id in ancestor_ids:
                staging = _VOICE_CLONE_TASK_STAGING.pop(ancestor_id, None)
                if staging:
                    staging["created_at"] = time.monotonic()
                    _VOICE_CLONE_TASK_STAGING[task_spec.task_id] = staging
                    break

    @classmethod
    def _owned_clone_staging_dir(cls, task_id: str) -> str:
        with _VOICE_CLONE_TASK_STAGING_LOCK:
            staging = _VOICE_CLONE_TASK_STAGING.get(task_id) or {}
            return str(staging.get("staging_dir") or "")

    @classmethod
    def _release_clone_task_staging(cls, task_id: str) -> None:
        with _VOICE_CLONE_TASK_STAGING_LOCK:
            staging = _VOICE_CLONE_TASK_STAGING.pop(task_id, None)
        if staging:
            cls._remove_clone_staging_dir(str(staging.get("staging_dir") or ""))

    def _prune_expired_clone_task_staging(self) -> None:
        """Expire failed/cancelled task staging while preserving queued work."""
        now = time.monotonic()
        with _VOICE_CLONE_TASK_STAGING_LOCK:
            candidates = [
                (task_id, dict(staging))
                for task_id, staging in _VOICE_CLONE_TASK_STAGING.items()
                if now - float(staging.get("created_at", now)) > _VOICE_ANALYSIS_TTL_SECONDS
            ]

        expired_ids: list[str] = []
        for task_id, _staging in candidates:
            try:
                state = str(self._task_service.get_task(task_id).state)
            except Exception:
                state = "missing"
            if state not in {"pending", "running"} and not (
                self._has_live_retry_descendant(task_id)
            ):
                expired_ids.append(task_id)

        for task_id in expired_ids:
            self._release_clone_task_staging(task_id)

    def _has_live_retry_descendant(self, task_id: str) -> bool:
        """Keep an old owner's staging while a queued retry still depends on it."""
        try:
            statuses = list(self._task_service.list_tasks())
        except Exception:
            return False

        children: dict[str, list[Any]] = {}
        for status in statuses:
            parent_id = str(getattr(status, "retry_of_task_id", "") or "")
            if parent_id:
                children.setdefault(parent_id, []).append(status)

        pending_parents = [task_id]
        visited = {task_id}
        while pending_parents:
            parent_id = pending_parents.pop()
            for child in children.get(parent_id, []):
                child_id = str(getattr(child, "task_id", "") or "")
                if not child_id or child_id in visited:
                    continue
                if str(getattr(child, "state", "")) in {"pending", "running"}:
                    return True
                visited.add(child_id)
                pending_parents.append(child_id)
        return False

    @classmethod
    def _prune_orphan_clone_staging_dirs(cls) -> None:
        """Remove expired staging directories with no live in-process owner."""
        staging_root = PROJECT_ROOT / ".tmp" / "voice-clone-tasks"
        if not staging_root.is_dir():
            return
        with _VOICE_CLONE_TASK_STAGING_LOCK:
            active_dirs = {
                str(Path(str(staging.get("staging_dir") or "")).resolve())
                for staging in _VOICE_CLONE_TASK_STAGING.values()
                if staging.get("staging_dir")
            }
        cutoff = time.time() - _VOICE_ANALYSIS_TTL_SECONDS
        try:
            children = list(staging_root.iterdir())
        except OSError:
            return
        for child in children:
            try:
                should_remove = (
                    child.is_dir()
                    and child.name.startswith("voice-clone-stage-")
                    and str(child.resolve()) not in active_dirs
                    and child.stat().st_mtime < cutoff
                )
            except OSError:
                continue
            if should_remove:
                cls._remove_clone_staging_dir(child)

    def _validate_clone_task_staging(self, task_id: str, profile: dict) -> None:
        staging_dir = str(profile.get("_clone_staging_dir") or "")
        expected_fingerprint = str(profile.get("_clone_staging_fingerprint") or "")
        if not staging_dir and not expected_fingerprint:
            return
        owned_staging_dir = self._owned_clone_staging_dir(task_id)
        if not owned_staging_dir:
            raise AppValidationError("voice clone task does not own its staged reference")
        if Path(owned_staging_dir).resolve() != Path(staging_dir).resolve():
            raise AppValidationError("voice clone task staging ownership mismatch")
        staged_path = Path(str(profile.get("audio_path") or ""))
        if (
            not staged_path.is_file()
            or staged_path.resolve().parent != Path(owned_staging_dir).resolve()
        ):
            raise AppValidationError("voice clone staged reference is no longer available")
        if not expected_fingerprint:
            raise AppValidationError("voice clone staged reference fingerprint is missing")
        if self._fingerprint_file(staged_path) != expected_fingerprint:
            raise AppValidationError("voice clone staged reference fingerprint changed")

    @staticmethod
    def _remove_analysis_dir(path: str | Path) -> None:
        """Remove only a request directory created under the analysis root."""
        if not path:
            return
        try:
            project_root = PROJECT_ROOT.resolve()
            analysis_root = (PROJECT_ROOT / ".tmp" / "voice-analysis").resolve()
            target = Path(path).resolve()
        except (OSError, RuntimeError) as exc:
            logger.warning("cannot resolve voice analysis cleanup path %s: %s", path, exc)
            return
        if not analysis_root.is_relative_to(project_root):
            logger.warning(
                "refusing voice analysis cleanup outside project root: %s",
                analysis_root,
            )
            return
        if target.parent != analysis_root or not target.name.startswith("voice-analysis-"):
            logger.warning("refusing to remove unexpected voice analysis path: %s", target)
            return
        shutil.rmtree(target, ignore_errors=True)

    @classmethod
    def _discard_analysis_session(cls, analysis_id: str) -> None:
        if not analysis_id:
            return
        with _VOICE_ANALYSIS_SESSIONS_LOCK:
            session = _VOICE_ANALYSIS_SESSIONS.pop(analysis_id, None)
        if session:
            cls._remove_analysis_dir(str(session.get("analysis_dir") or ""))

    @classmethod
    def _prune_analysis_sessions(cls, *, reserve: int = 0) -> None:
        """Bound temporary candidate sessions by age and count."""
        now = time.monotonic()
        stale: list[dict[str, Any]] = []
        with _VOICE_ANALYSIS_SESSIONS_LOCK:
            expired_ids = [
                analysis_id
                for analysis_id, session in _VOICE_ANALYSIS_SESSIONS.items()
                if now - float(session.get("created_at", now)) > _VOICE_ANALYSIS_TTL_SECONDS
            ]
            for analysis_id in expired_ids:
                stale.append(_VOICE_ANALYSIS_SESSIONS.pop(analysis_id))

            keep_count = max(0, _VOICE_ANALYSIS_MAX_SESSIONS - max(0, reserve))
            overflow = max(0, len(_VOICE_ANALYSIS_SESSIONS) - keep_count)
            if overflow:
                oldest_ids = sorted(
                    _VOICE_ANALYSIS_SESSIONS,
                    key=lambda analysis_id: float(
                        _VOICE_ANALYSIS_SESSIONS[analysis_id].get("created_at", now)
                    ),
                )[:overflow]
                for analysis_id in oldest_ids:
                    stale.append(_VOICE_ANALYSIS_SESSIONS.pop(analysis_id))

        for session in stale:
            cls._remove_analysis_dir(str(session.get("analysis_dir") or ""))

    @classmethod
    def _prune_orphan_analysis_dirs(cls) -> None:
        """Remove expired request directories left by an earlier process."""
        analysis_root = PROJECT_ROOT / ".tmp" / "voice-analysis"
        if not analysis_root.is_dir():
            return
        with _VOICE_ANALYSIS_SESSIONS_LOCK:
            active_dirs = {
                str(Path(str(session.get("analysis_dir") or "")).resolve())
                for session in _VOICE_ANALYSIS_SESSIONS.values()
                if session.get("analysis_dir")
            }
        cutoff = time.time() - _VOICE_ANALYSIS_TTL_SECONDS
        try:
            children = list(analysis_root.iterdir())
        except OSError:
            return
        for child in children:
            if (
                not child.is_dir()
                or not child.name.startswith("voice-analysis-")
                or str(child.resolve()) in active_dirs
            ):
                continue
            try:
                is_expired = child.stat().st_mtime < cutoff
            except OSError:
                continue
            if is_expired:
                cls._remove_analysis_dir(child)

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
                    "output_path": str(PROJECT_ROOT / ".tmp" / f"voice-preview-{profile_id}.wav"),
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
                "output_path": str(PROJECT_ROOT / ".tmp" / f"voice-preview-{uuid.uuid4().hex}.wav"),
            }
        staging_dir = str(payload.get("_clone_staging_dir") or "")
        try:
            task, _ = self._task_service.create_task_spec(
                task_type=f"voice.{operation}",
                task_source="voice-lab",
                session_id="",
                input_asset_id=str(payload.get("audio_path") or payload.get("profile_id") or ""),
                execution_profile={"operation": operation, **payload},
            )
        except Exception:
            if staging_dir:
                self._remove_clone_staging_dir(staging_dir)
            raise
        if staging_dir:
            try:
                self._claim_clone_task_staging(task.task_id, Path(staging_dir))
            except Exception:
                self._remove_clone_staging_dir(staging_dir)
                raise
        return task

    def _execute_voice_task(self, task_spec, context):
        profile = dict(task_spec.execution_profile)
        operation = str(profile.get("operation") or task_spec.task_type.split(".")[-1])
        if operation not in {"design", "clone", "preview"}:
            raise AppValidationError(f"unsupported voice task operation: {operation}")
        if operation == "clone":
            self._adopt_retry_clone_staging(task_spec)
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
            analysis_id = str(
                (profile.get("clone_manifest") or {}).get("analysis_id")
                if isinstance(profile.get("clone_manifest"), dict)
                else ""
            )
            clone_completed = False
            result: dict | None = None
            try:
                self._validate_clone_task_staging(task_id, profile)
                result = self._runtime_router.clone_voice(profile)
                try:
                    self._restore_profile(result)
                    self._register_voice_artifacts(task_id, result)
                except Exception:
                    self._rollback_generated_profile(result)
                    raise
                clone_completed = True
                return {
                    **result,
                    "primary_output": result.get("prompt_cache_path", ""),
                    "artifact_set_id": task_id,
                }
            finally:
                if clone_completed:
                    self._discard_analysis_session(analysis_id)
                    self._release_clone_task_staging(task_id)
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
            clone_manifest=str(result.get("clone_manifest_path", "")),
            generated=True,
        )
        get_voice_manager().add_profile(profile)

    @staticmethod
    def _rollback_generated_profile(result: dict) -> None:
        """Remove a generated profile when clone post-processing cannot commit."""
        from src.core.tts.voice_profile import get_voice_manager

        profile_id = str(result.get("profile_id") or "")
        if not profile_id:
            return
        try:
            if not get_voice_manager().delete_profile(profile_id):
                logger.warning(
                    "cannot roll back generated voice profile because it is not loaded: %s",
                    profile_id,
                )
        except Exception:
            logger.exception("failed to roll back generated voice profile: %s", profile_id)

    def _register_voice_artifacts(self, task_id: str, result: dict) -> None:
        for artifact_type, path, label in (
            ("audio.voice_reference", result.get("ref_audio_path"), "Voice Reference"),
            ("voice.prompt_cache", result.get("prompt_cache_path"), "Voice Prompt Cache"),
            (
                "voice.clone_manifest",
                result.get("clone_manifest_path"),
                "Voice Clone Manifest",
            ),
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
