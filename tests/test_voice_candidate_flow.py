from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.dto.voice import (
    SegmentAnalyzeRequest,
    SegmentAnalyzeResult,
    SegmentInfo,
    VoiceCloneCandidate,
    VoiceCloneRequest,
)
from src.app.errors import AppExecutionError, AppValidationError
from src.app.services.voice_service import VoiceService


@pytest.fixture(autouse=True)
def _isolate_voice_analysis_sessions():
    import src.app.services.voice_service as service_module

    with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
        service_module._VOICE_ANALYSIS_SESSIONS.clear()
    with service_module._VOICE_CLONE_TASK_STAGING_LOCK:
        service_module._VOICE_CLONE_TASK_STAGING.clear()
    yield
    with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
        service_module._VOICE_ANALYSIS_SESSIONS.clear()
    with service_module._VOICE_CLONE_TASK_STAGING_LOCK:
        service_module._VOICE_CLONE_TASK_STAGING.clear()


def _service_without_runtime() -> VoiceService:
    return object.__new__(VoiceService)


def _install_fake_preprocessor(monkeypatch, captured: dict) -> None:
    import src.core.tts.audio_preprocessor as preprocessor_module

    class FakePreprocessor:
        def __init__(self, output_dir: str):
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            captured["output_dirs"] = [
                *captured.get("output_dirs", []),
                self.output_dir,
            ]

        def analyze_segments(self, **kwargs):
            captured["analyze_kwargs"] = kwargs
            segment_path = self.output_dir / "segment.wav"
            segment_path.write_bytes(b"candidate-audio")
            converted_path = self.output_dir / "converted.wav"
            converted_path.write_bytes(b"converted-audio")
            return {
                "mode": "asr",
                "segments": [
                    {
                        "index": 0,
                        "start": 1.0,
                        "end": 7.0,
                        "duration": 6.0,
                        "text": "候选文本",
                        "path": str(segment_path),
                        "rms": 0.12,
                        "quality_score": 88,
                        "quality_label": "良好",
                        "eligible": True,
                        "reasons": [],
                    }
                ],
                "recommended_indices": [0],
                "warnings": ["analysis warning"],
                "converted_audio_path": str(converted_path),
            }

        @staticmethod
        def evaluate_segment_quality(_segment):
            return {
                "score": 77,
                "label": "可用",
                "details": {
                    "duration_score": 90,
                    "rms_score": 80,
                    "text_score": 70,
                },
            }

    monkeypatch.setattr(preprocessor_module, "AudioPreprocessor", FakePreprocessor)


def _install_assessment_preprocessor(
    monkeypatch,
    segments: list[dict],
    recommended_indices: list[int],
) -> None:
    import src.core.tts.audio_preprocessor as preprocessor_module

    class AssessmentPreprocessor:
        def __init__(self, output_dir: str):
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)

        def analyze_segments(self, **_kwargs):
            materialized_segments = []
            for position, raw_segment in enumerate(segments):
                segment = dict(raw_segment)
                segment_path = self.output_dir / f"segment-{position}.wav"
                segment_path.write_bytes(f"candidate-{position}".encode())
                segment["path"] = str(segment_path)
                materialized_segments.append(segment)
            return {
                "mode": "asr",
                "segments": materialized_segments,
                "recommended_indices": list(recommended_indices),
            }

        @staticmethod
        def evaluate_segment_quality(_segment):
            return {}

    monkeypatch.setattr(
        preprocessor_module,
        "AudioPreprocessor",
        AssessmentPreprocessor,
    )


def _analyze(
    monkeypatch,
    tmp_path: Path,
    *,
    x_vector_only_mode: bool = False,
    separate_vocals: bool = False,
):
    import src.app.services.voice_service as service_module

    captured: dict = {}
    _install_fake_preprocessor(monkeypatch, captured)
    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(b"source-audio")

    service = _service_without_runtime()
    if separate_vocals:
        separated_path = tmp_path / "separated.wav"
        separated_path.write_bytes(b"separated-audio")

        def separate(_source_path, _analysis_dir):
            captured["separated"] = True
            return str(separated_path)

        service._separate_vocals_for_analysis = separate

    result = service.analyze_segments(
        SegmentAnalyzeRequest(
            audio_path=str(source_path),
            audio_language="ja",
            separate_vocals=separate_vocals,
            x_vector_only_mode=x_vector_only_mode,
        )
    )
    return service, source_path, result, captured


def test_analysis_creates_fingerprinted_clone_candidate(monkeypatch, tmp_path):
    _service, source_path, result, captured = _analyze(monkeypatch, tmp_path)

    assert result.analysis_id.startswith("voice-analysis-")
    assert result.source_fingerprint.startswith("sha256:")
    assert result.recommended_candidate_id == "candidate-0001"
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.source_variant == "original"
    assert candidate.text == "候选文本"
    assert candidate.score == 88
    assert candidate.label == "良好"
    assert candidate.eligible is True
    assert candidate.details["duration_score"] == 90
    assert candidate.reasons == ["自动推荐片段"]
    assert Path(candidate.preview_audio_path).read_bytes() == b"candidate-audio"

    assert result.segments[0].score == 88
    assert result.segments[0].label == "良好"
    assert result.segments[0].details["rms_score"] == 80
    assert captured["analyze_kwargs"]["audio_path"] == str(source_path)
    assert captured["analyze_kwargs"]["require_text"] is True
    assert captured["output_dirs"][0].name == result.analysis_id


def test_icl_candidate_clone_uses_preview_and_confirmed_text(monkeypatch, tmp_path):
    service, source_path, analysis, _captured = _analyze(monkeypatch, tmp_path)
    submitted: dict = {}

    def submit(operation: str, payload: dict):
        submitted["operation"] = operation
        submitted["payload"] = payload
        return SimpleNamespace(task_id="voice.clone-candidate")

    service._submit_voice_task = submit
    service.submit_clone_voice(
        VoiceCloneRequest(
            audio_path=str(source_path),
            name="Candidate Voice",
            ref_text="must not be used",
            analysis_id=analysis.analysis_id,
            candidate_id=analysis.recommended_candidate_id,
            confirmed_text="用户确认文本",
        )
    )

    assert submitted["operation"] == "clone"
    staged_path = Path(submitted["payload"]["audio_path"])
    assert staged_path != Path(analysis.candidates[0].preview_audio_path)
    assert staged_path.read_bytes() == b"candidate-audio"
    assert staged_path.parent == Path(submitted["payload"]["_clone_staging_dir"])
    assert submitted["payload"]["ref_text"] == "用户确认文本"
    assert submitted["payload"]["x_vector_only_mode"] is False
    manifest = submitted["payload"]["clone_manifest"]
    assert manifest["analysis_id"] == analysis.analysis_id
    assert manifest["candidate_id"] == analysis.recommended_candidate_id
    assert manifest["original_source_path"] == str(source_path.resolve())
    assert manifest["source_fingerprint"] == analysis.source_fingerprint
    assert manifest["candidate_fingerprint"].startswith("sha256:")
    assert manifest["source_variant"] == "original"
    assert manifest["start"] == 1.0
    assert manifest["end"] == 7.0
    assert manifest["original_text"] == "候选文本"
    assert manifest["confirmed_text"] == "用户确认文本"
    assert manifest["score"] == 88
    assert manifest["eligible"] is True
    assert manifest["reasons"] == ["自动推荐片段"]
    assert manifest["details"]["duration_score"] == 90
    service._remove_clone_staging_dir(submitted["payload"]["_clone_staging_dir"])


def test_icl_candidate_requires_confirmed_text(monkeypatch, tmp_path):
    service, source_path, analysis, _captured = _analyze(monkeypatch, tmp_path)

    with pytest.raises(AppValidationError, match="confirmed_text is required"):
        service.submit_clone_voice(
            VoiceCloneRequest(
                audio_path=str(source_path),
                name="Unconfirmed Voice",
                ref_text="legacy text must not be used",
                analysis_id=analysis.analysis_id,
                candidate_id=analysis.recommended_candidate_id,
            )
        )


def test_x_vector_candidate_does_not_require_confirmed_text(monkeypatch, tmp_path):
    service, source_path, analysis, captured = _analyze(
        monkeypatch,
        tmp_path,
        x_vector_only_mode=True,
    )
    submitted: dict = {}
    service._submit_voice_task = lambda operation, payload: (
        submitted.update({"operation": operation, "payload": payload})
        or SimpleNamespace(task_id="voice.clone-x-vector")
    )

    service.submit_clone_voice(
        VoiceCloneRequest(
            audio_path=str(source_path),
            name="X Vector Voice",
            x_vector_only_mode=True,
            analysis_id=analysis.analysis_id,
            candidate_id=analysis.recommended_candidate_id,
        )
    )

    assert submitted["payload"]["ref_text"] is None
    assert submitted["payload"]["x_vector_only_mode"] is True
    assert submitted["payload"]["clone_manifest"]["confirmed_text"] == ""
    assert captured["analyze_kwargs"]["require_text"] is False


def test_legacy_direct_clone_path_remains_supported(tmp_path):
    source_path = tmp_path / "direct.wav"
    source_path.write_bytes(b"direct-audio")
    submitted: dict = {}
    service = _service_without_runtime()
    service._submit_voice_task = lambda operation, payload: (
        submitted.update({"operation": operation, "payload": payload})
        or SimpleNamespace(task_id="voice.clone-direct")
    )

    service.submit_clone_voice(
        VoiceCloneRequest(
            audio_path=str(source_path),
            name="Direct Voice",
            ref_text="direct transcript",
        )
    )

    assert submitted["payload"]["audio_path"] == str(source_path)
    assert submitted["payload"]["ref_text"] == "direct transcript"


def test_candidate_clone_rejects_changed_source_fingerprint(monkeypatch, tmp_path):
    service, source_path, analysis, _captured = _analyze(monkeypatch, tmp_path)
    source_path.write_bytes(b"changed-source-audio")

    with pytest.raises(AppValidationError, match="fingerprint"):
        service.submit_clone_voice(
            VoiceCloneRequest(
                audio_path=str(source_path),
                name="Stale Candidate",
                analysis_id=analysis.analysis_id,
                candidate_id=analysis.recommended_candidate_id,
                confirmed_text="候选文本",
            )
        )


def test_analysis_can_bind_candidates_to_separated_vocals(monkeypatch, tmp_path):
    _service, _source_path, result, captured = _analyze(
        monkeypatch,
        tmp_path,
        separate_vocals=True,
    )

    assert captured["separated"] is True
    assert result.candidates[0].source_variant == "separated_vocals"
    assert "使用分离后的人声音轨" in result.candidates[0].reasons
    assert "候选片段来自分离后的人声音轨" in result.warnings


def test_ineligible_candidates_are_persisted_but_never_recommended_or_cloned(
    monkeypatch,
    tmp_path,
):
    import src.app.services.voice_service as service_module

    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(b"source-audio")
    _install_assessment_preprocessor(
        monkeypatch,
        segments=[
            {
                "index": 0,
                "start": 0.0,
                "end": 6.0,
                "duration": 6.0,
                "text": "削波候选",
                "score": 99,
                "label": "最优",
                "eligible": False,
                "reasons": ["削波比例过高"],
                "details": {"clipping_ratio": 0.4},
            },
            {
                "index": 1,
                "start": 6.0,
                "end": 12.0,
                "duration": 6.0,
                "text": "合格候选",
                "score": 70,
                "label": "可用",
                "eligible": True,
                "reasons": [],
                "details": {"clipping_ratio": 0.0},
            },
        ],
        # Simulate an old/malformed core recommendation that points at the
        # higher-scoring but ineligible segment.
        recommended_indices=[0],
    )
    service = _service_without_runtime()
    result = service.analyze_segments(SegmentAnalyzeRequest(audio_path=str(source_path)))

    assert result.segments[0].eligible is False
    assert result.segments[0].reasons == ["削波比例过高"]
    assert result.candidates[0].eligible is False
    assert "削波比例过高" in result.candidates[0].reasons
    assert result.recommended_candidate_id is None
    assert result.recommended_indices == []

    with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
        stored = service_module._VOICE_ANALYSIS_SESSIONS[result.analysis_id]["candidates"][
            "candidate-0001"
        ]
    assert stored["eligible"] is False
    assert "削波比例过高" in stored["reasons"]

    with pytest.raises(AppValidationError, match="not eligible.*削波"):
        service.submit_clone_voice(
            VoiceCloneRequest(
                audio_path=str(source_path),
                name="Rejected Candidate",
                analysis_id=result.analysis_id,
                candidate_id="candidate-0001",
                confirmed_text="削波候选",
            )
        )

    _install_assessment_preprocessor(
        monkeypatch,
        segments=[
            {
                "index": 0,
                "start": 0.0,
                "end": 6.0,
                "duration": 6.0,
                "text": "无效候选",
                "score": 100,
                "label": "最优",
                "eligible": False,
                "reasons": ["没有有效语音"],
                "details": {},
            }
        ],
        recommended_indices=[0],
    )
    all_ineligible = service.analyze_segments(SegmentAnalyzeRequest(audio_path=str(source_path)))
    assert all_ineligible.recommended_candidate_id is None
    assert all_ineligible.recommended_indices == []


def test_low_confidence_candidates_remain_manual_only(monkeypatch, tmp_path):
    import src.app.services.voice_service as service_module

    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(b"source-audio")
    _install_assessment_preprocessor(
        monkeypatch,
        segments=[
            {
                "index": 0,
                "start": 0.0,
                "end": 6.0,
                "duration": 6.0,
                "text": "低置信度候选",
                "score": 85,
                "label": "良好",
                "eligible": True,
                "reasons": ["ASR 置信度偏低，需人工确认"],
                "details": {"asr_confidence": 0.42},
            }
        ],
        recommended_indices=[],
    )
    service = _service_without_runtime()
    result = service.analyze_segments(SegmentAnalyzeRequest(audio_path=str(source_path)))

    assert result.candidates[0].eligible is True
    assert result.recommended_candidate_id is None
    assert result.recommended_indices == []

    submitted: dict = {}
    service._submit_voice_task = lambda _operation, payload: (
        submitted.update(payload) or SimpleNamespace(task_id="voice.clone-manual")
    )
    service.submit_clone_voice(
        VoiceCloneRequest(
            audio_path=str(source_path),
            name="Manual Candidate",
            analysis_id=result.analysis_id,
            candidate_id="candidate-0001",
            confirmed_text="人工确认文本",
        )
    )
    assert Path(submitted["audio_path"]).is_file()
    service._remove_clone_staging_dir(submitted["_clone_staging_dir"])


def test_concurrent_candidate_submissions_use_independent_task_staging(
    monkeypatch,
    tmp_path,
):
    service, source_path, analysis, _captured = _analyze(monkeypatch, tmp_path)
    submitted_payloads: list[dict] = []

    def submit(_operation: str, payload: dict):
        submitted_payloads.append(payload)
        return SimpleNamespace(task_id=f"voice.clone-{len(submitted_payloads)}")

    service._submit_voice_task = submit
    for name in ("Concurrent One", "Concurrent Two"):
        service.submit_clone_voice(
            VoiceCloneRequest(
                audio_path=str(source_path),
                name=name,
                analysis_id=analysis.analysis_id,
                candidate_id=analysis.recommended_candidate_id,
                confirmed_text="用户确认文本",
            )
        )

    first_payload, second_payload = submitted_payloads
    first_stage = Path(first_payload["audio_path"])
    second_stage = Path(second_payload["audio_path"])
    assert first_stage != second_stage
    assert first_stage.read_bytes() == b"candidate-audio"
    assert second_stage.read_bytes() == b"candidate-audio"

    service._claim_clone_task_staging(
        "voice.clone-1",
        Path(first_payload["_clone_staging_dir"]),
    )
    service._claim_clone_task_staging(
        "voice.clone-2",
        Path(second_payload["_clone_staging_dir"]),
    )
    runtime_inputs: list[bytes] = []

    def clone_runtime(profile: dict):
        runtime_inputs.append(Path(profile["audio_path"]).read_bytes())
        return {
            "profile_id": f"clone-{len(runtime_inputs)}",
            "name": "Clone",
            "category": "clone",
            "prompt_cache_path": "prompt.pt",
        }

    service._runtime_router = SimpleNamespace(clone_voice=clone_runtime)
    service._restore_profile = lambda _result: None
    service._register_voice_artifacts = lambda _task_id, _result: None
    analysis_dir = Path(analysis.candidates[0].preview_audio_path).parents[1]

    service._execute_serialized_voice_operation(
        operation="clone",
        profile=first_payload,
        task_id="voice.clone-1",
    )

    assert not analysis_dir.exists()
    assert not first_stage.exists()
    assert second_stage.is_file()

    service._execute_serialized_voice_operation(
        operation="clone",
        profile=second_payload,
        task_id="voice.clone-2",
    )

    assert runtime_inputs == [b"candidate-audio", b"candidate-audio"]
    assert not second_stage.exists()


def test_failed_clone_staging_transfers_to_retry_and_cleans_on_success(
    monkeypatch,
    tmp_path,
):
    import src.app.services.voice_service as service_module

    service, source_path, analysis, _captured = _analyze(monkeypatch, tmp_path)
    submitted: dict = {}
    service._submit_voice_task = lambda _operation, payload: (
        submitted.update(payload) or SimpleNamespace(task_id="voice.clone-failed")
    )
    service.submit_clone_voice(
        VoiceCloneRequest(
            audio_path=str(source_path),
            name="Retry Candidate",
            analysis_id=analysis.analysis_id,
            candidate_id=analysis.recommended_candidate_id,
            confirmed_text="用户确认文本",
        )
    )
    staging_dir = Path(submitted["_clone_staging_dir"])
    service._claim_clone_task_staging("voice.clone-failed", staging_dir)

    def fail_clone(_profile):
        raise RuntimeError("runtime failed")

    service._runtime_router = SimpleNamespace(clone_voice=fail_clone)
    with pytest.raises(RuntimeError, match="runtime failed"):
        service._execute_serialized_voice_operation(
            operation="clone",
            profile=submitted,
            task_id="voice.clone-failed",
        )

    assert staging_dir.is_dir()
    assert analysis.analysis_id in service_module._VOICE_ANALYSIS_SESSIONS
    assert service._owned_clone_staging_dir("voice.clone-failed") == str(staging_dir)

    service._adopt_retry_clone_staging(
        SimpleNamespace(
            task_id="voice.clone-retry",
            retry_of_task_id="voice.clone-failed",
        )
    )
    service._runtime_router = SimpleNamespace(
        clone_voice=lambda _profile: {
            "profile_id": "clone-retry",
            "name": "Clone",
            "category": "clone",
            "prompt_cache_path": "prompt.pt",
        }
    )
    service._restore_profile = lambda _result: None
    service._register_voice_artifacts = lambda _task_id, _result: None
    service._execute_serialized_voice_operation(
        operation="clone",
        profile=submitted,
        task_id="voice.clone-retry",
    )

    assert not staging_dir.exists()
    assert analysis.analysis_id not in service_module._VOICE_ANALYSIS_SESSIONS


def test_cancelled_or_failed_task_staging_expires_and_create_failure_cleans(
    monkeypatch,
    tmp_path,
):
    import src.app.services.voice_service as service_module

    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    source_path = tmp_path / "candidate.wav"
    source_path.write_bytes(b"candidate")
    service = _service_without_runtime()
    staged_path, staging_dir = service._stage_clone_reference(
        source_path,
        expected_fingerprint=service._fingerprint_file(source_path),
    )
    payload = {
        "operation": "clone",
        "audio_path": str(staged_path),
        "_clone_staging_dir": str(staging_dir),
        "_clone_staging_fingerprint": service._fingerprint_file(staged_path),
    }
    service._claim_clone_task_staging("voice.clone-cancelled", staging_dir)
    task_spec = SimpleNamespace(
        task_id="voice.clone-cancelled",
        task_type="voice.clone",
        retry_of_task_id=None,
        execution_profile=payload,
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        service._execute_voice_task(
            task_spec,
            SimpleNamespace(cancellation_requested=True),
        )
    assert staging_dir.is_dir()

    with service_module._VOICE_CLONE_TASK_STAGING_LOCK:
        service_module._VOICE_CLONE_TASK_STAGING["voice.clone-cancelled"]["created_at"] = (
            time.monotonic() - service_module._VOICE_ANALYSIS_TTL_SECONDS - 1
        )
    service._task_service = SimpleNamespace(
        get_task=lambda _task_id: SimpleNamespace(state="cancelled")
    )
    service._prune_expired_clone_task_staging()
    assert not staging_dir.exists()

    second_stage, second_dir = service._stage_clone_reference(
        source_path,
        expected_fingerprint=service._fingerprint_file(source_path),
    )

    def fail_create(**_kwargs):
        raise RuntimeError("task persistence failed")

    service._task_service = SimpleNamespace(create_task_spec=fail_create)
    with pytest.raises(RuntimeError, match="task persistence failed"):
        service._create_voice_task(
            "clone",
            {
                "audio_path": str(second_stage),
                "_clone_staging_dir": str(second_dir),
                "_clone_staging_fingerprint": service._fingerprint_file(second_stage),
            },
        )
    assert not second_dir.exists()


def test_pending_retry_prevents_expired_staging_prune(monkeypatch, tmp_path):
    import src.app.services.voice_service as service_module

    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    source_path = tmp_path / "candidate.wav"
    source_path.write_bytes(b"candidate")
    service = _service_without_runtime()
    _staged_path, staging_dir = service._stage_clone_reference(
        source_path,
        expected_fingerprint=service._fingerprint_file(source_path),
    )
    failed_task_id = "voice.clone-failed"
    retry_task_id = "voice.clone-pending-retry"
    service._claim_clone_task_staging(failed_task_id, staging_dir)
    with service_module._VOICE_CLONE_TASK_STAGING_LOCK:
        service_module._VOICE_CLONE_TASK_STAGING[failed_task_id]["created_at"] = (
            time.monotonic() - service_module._VOICE_ANALYSIS_TTL_SECONDS - 1
        )

    service._task_service = SimpleNamespace(
        get_task=lambda _task_id: SimpleNamespace(state="failed"),
        list_tasks=lambda: [
            SimpleNamespace(
                task_id=retry_task_id,
                state="pending",
                retry_of_task_id=failed_task_id,
            )
        ],
    )
    service._prune_expired_clone_task_staging()

    assert staging_dir.is_dir()
    assert service._owned_clone_staging_dir(failed_task_id) == str(staging_dir)
    service._adopt_retry_clone_staging(
        SimpleNamespace(
            task_id=retry_task_id,
            retry_of_task_id=failed_task_id,
        )
    )
    assert service._owned_clone_staging_dir(retry_task_id) == str(staging_dir)
    service._release_clone_task_staging(retry_task_id)
    assert not staging_dir.exists()


def test_retry_adopts_staging_from_ancestor_when_parent_never_executed(
    monkeypatch,
    tmp_path,
):
    import src.app.services.voice_service as service_module

    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    source_path = tmp_path / "candidate.wav"
    source_path.write_bytes(b"candidate")
    service = _service_without_runtime()
    _staged_path, staging_dir = service._stage_clone_reference(
        source_path,
        expected_fingerprint=service._fingerprint_file(source_path),
    )
    original_task_id = "voice.clone-original"
    cancelled_retry_id = "voice.clone-cancelled-retry"
    latest_retry_id = "voice.clone-latest-retry"
    service._claim_clone_task_staging(original_task_id, staging_dir)
    specs = {
        cancelled_retry_id: SimpleNamespace(
            task_id=cancelled_retry_id,
            retry_of_task_id=original_task_id,
        ),
        original_task_id: SimpleNamespace(
            task_id=original_task_id,
            retry_of_task_id=None,
        ),
    }
    service._task_service = SimpleNamespace(get_task_spec=specs.__getitem__)

    service._adopt_retry_clone_staging(
        SimpleNamespace(
            task_id=latest_retry_id,
            retry_of_task_id=cancelled_retry_id,
        )
    )

    assert service._owned_clone_staging_dir(original_task_id) == ""
    assert service._owned_clone_staging_dir(cancelled_retry_id) == ""
    assert service._owned_clone_staging_dir(latest_retry_id) == str(staging_dir)
    service._release_clone_task_staging(latest_retry_id)


def test_analysis_failure_removes_unique_analysis_directory(monkeypatch, tmp_path):
    import src.app.services.voice_service as service_module
    import src.core.tts.audio_preprocessor as preprocessor_module

    class BrokenCandidatePreprocessor:
        def __init__(self, output_dir: str):
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)

        def analyze_segments(self, **_kwargs):
            return {
                "mode": "asr",
                "segments": [
                    {
                        "index": 0,
                        "start": 0.0,
                        "end": 1.0,
                        "duration": 1.0,
                        "text": "text",
                    }
                ],
                "converted_audio_path": str(self.output_dir / "missing.wav"),
            }

    monkeypatch.setattr(
        preprocessor_module,
        "AudioPreprocessor",
        BrokenCandidatePreprocessor,
    )
    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    source_path = tmp_path / "source.wav"
    source_path.write_bytes(b"source-audio")

    with pytest.raises(AppExecutionError, match="candidate audio source"):
        _service_without_runtime().analyze_segments(
            SegmentAnalyzeRequest(audio_path=str(source_path))
        )

    analysis_root = tmp_path / ".tmp" / "voice-analysis"
    assert not list(analysis_root.glob("voice-analysis-*"))


def test_successful_clone_consumes_analysis_session_but_runtime_failure_keeps_it(
    monkeypatch,
    tmp_path,
):
    import src.app.services.voice_service as service_module

    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    analysis_root = tmp_path / ".tmp" / "voice-analysis"
    successful_dir = analysis_root / "voice-analysis-success"
    successful_dir.mkdir(parents=True)
    (successful_dir / "candidate.wav").write_bytes(b"candidate")
    with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
        service_module._VOICE_ANALYSIS_SESSIONS["voice-analysis-success"] = {
            "analysis_dir": str(successful_dir),
        }

    callbacks: list[str] = []
    service = _service_without_runtime()
    service._runtime_router = SimpleNamespace(
        clone_voice=lambda _profile: {
            "profile_id": "clone-1",
            "name": "Clone",
            "category": "clone",
            "prompt_cache_path": "prompt.pt",
            "clone_manifest_path": "clone-manifest.json",
        }
    )
    service._restore_profile = lambda _result: callbacks.append("restore")
    service._register_voice_artifacts = lambda _task_id, _result: callbacks.append("artifacts")

    result = service._execute_serialized_voice_operation(
        operation="clone",
        profile={
            "clone_manifest": {"analysis_id": "voice-analysis-success"},
        },
        task_id="voice.clone-success",
    )

    assert result["clone_manifest_path"] == "clone-manifest.json"
    assert callbacks == ["restore", "artifacts"]
    assert "voice-analysis-success" not in service_module._VOICE_ANALYSIS_SESSIONS
    assert not successful_dir.exists()

    failed_dir = analysis_root / "voice-analysis-failed"
    failed_dir.mkdir()
    with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
        service_module._VOICE_ANALYSIS_SESSIONS["voice-analysis-failed"] = {
            "analysis_dir": str(failed_dir),
        }

    def fail_clone(_profile):
        raise RuntimeError("clone runtime failed")

    service._runtime_router = SimpleNamespace(clone_voice=fail_clone)
    with pytest.raises(RuntimeError, match="clone runtime failed"):
        service._execute_serialized_voice_operation(
            operation="clone",
            profile={
                "clone_manifest": {"analysis_id": "voice-analysis-failed"},
            },
            task_id="voice.clone-failed",
        )

    assert "voice-analysis-failed" in service_module._VOICE_ANALYSIS_SESSIONS
    assert failed_dir.is_dir()


def test_clone_postprocess_failure_rolls_back_profile_and_keeps_retry_material(
    monkeypatch,
    tmp_path,
):
    import src.app.services.voice_service as service_module

    service, source_path, analysis, _captured = _analyze(monkeypatch, tmp_path)
    submitted: dict = {}
    failed_task_id = "voice.clone-postprocess-failed"
    retry_task_id = "voice.clone-postprocess-retry"
    service._submit_voice_task = lambda _operation, payload: (
        submitted.update(payload) or SimpleNamespace(task_id=failed_task_id)
    )
    service.submit_clone_voice(
        VoiceCloneRequest(
            audio_path=str(source_path),
            name="Postprocess Retry",
            analysis_id=analysis.analysis_id,
            candidate_id=analysis.recommended_candidate_id,
            confirmed_text="用户确认文本",
        )
    )
    staging_dir = Path(submitted["_clone_staging_dir"])
    service._claim_clone_task_staging(failed_task_id, staging_dir)

    runtime_calls: list[str] = []
    profiles: set[str] = set()

    def clone_runtime(_profile):
        profile_id = f"C{len(runtime_calls) + 1}"
        runtime_calls.append(profile_id)
        return {
            "profile_id": profile_id,
            "name": "Clone",
            "category": "clone",
            "prompt_cache_path": f"{profile_id}.pt",
        }

    service._runtime_router = SimpleNamespace(clone_voice=clone_runtime)
    service._restore_profile = lambda result: profiles.add(result["profile_id"])
    service._rollback_generated_profile = lambda result: profiles.discard(
        result["profile_id"]
    )

    def register_artifacts(task_id, _result):
        if task_id == failed_task_id:
            raise RuntimeError("artifact persistence failed")

    service._register_voice_artifacts = register_artifacts

    with pytest.raises(RuntimeError, match="artifact persistence failed"):
        service._execute_serialized_voice_operation(
            operation="clone",
            profile=submitted,
            task_id=failed_task_id,
        )

    assert profiles == set()
    assert staging_dir.is_dir()
    assert analysis.analysis_id in service_module._VOICE_ANALYSIS_SESSIONS
    assert service._owned_clone_staging_dir(failed_task_id) == str(staging_dir)

    service._adopt_retry_clone_staging(
        SimpleNamespace(task_id=retry_task_id, retry_of_task_id=failed_task_id)
    )
    service._execute_serialized_voice_operation(
        operation="clone",
        profile=submitted,
        task_id=retry_task_id,
    )

    assert runtime_calls == ["C1", "C2"]
    assert profiles == {"C2"}
    assert not staging_dir.exists()
    assert analysis.analysis_id not in service_module._VOICE_ANALYSIS_SESSIONS


def test_generated_profile_rollback_deletes_the_restored_profile(monkeypatch):
    import src.core.tts.voice_profile as profile_module

    deleted: list[str] = []
    monkeypatch.setattr(
        profile_module,
        "get_voice_manager",
        lambda: SimpleNamespace(
            delete_profile=lambda profile_id: deleted.append(profile_id) or True
        ),
    )

    VoiceService._rollback_generated_profile({"profile_id": "C1"})

    assert deleted == ["C1"]


def test_analysis_sessions_are_pruned_by_ttl_and_bounded_to_32(
    monkeypatch,
    tmp_path,
):
    import src.app.services.voice_service as service_module

    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    analysis_root = tmp_path / ".tmp" / "voice-analysis"
    now = time.monotonic()
    for index in range(34):
        analysis_id = f"voice-analysis-{index:02d}"
        analysis_dir = analysis_root / analysis_id
        analysis_dir.mkdir(parents=True)
        created_at = (
            now - service_module._VOICE_ANALYSIS_TTL_SECONDS - 1
            if index == 0
            else now - (34 - index)
        )
        with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
            service_module._VOICE_ANALYSIS_SESSIONS[analysis_id] = {
                "analysis_dir": str(analysis_dir),
                "created_at": created_at,
            }

    VoiceService._prune_analysis_sessions()

    with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
        remaining_ids = set(service_module._VOICE_ANALYSIS_SESSIONS)
    assert len(remaining_ids) == service_module._VOICE_ANALYSIS_MAX_SESSIONS
    assert "voice-analysis-00" not in remaining_ids
    assert "voice-analysis-01" not in remaining_ids
    assert not (analysis_root / "voice-analysis-00").exists()
    assert not (analysis_root / "voice-analysis-01").exists()
    assert (analysis_root / "voice-analysis-33").is_dir()


def test_service_startup_prunes_only_expired_safe_orphan_directories(
    monkeypatch,
    tmp_path,
):
    import src.app.services.voice_service as service_module

    monkeypatch.setattr(service_module, "PROJECT_ROOT", tmp_path)
    analysis_root = tmp_path / ".tmp" / "voice-analysis"
    stale_dir = analysis_root / "voice-analysis-stale"
    fresh_dir = analysis_root / "voice-analysis-fresh"
    active_dir = analysis_root / "voice-analysis-active"
    unrelated_dir = analysis_root / "keep-this-directory"
    outside_dir = tmp_path / "voice-analysis-outside"
    for path in (stale_dir, fresh_dir, active_dir, unrelated_dir, outside_dir):
        path.mkdir(parents=True)
        (path / "marker.txt").write_text("keep", encoding="utf-8")

    expired_time = time.time() - service_module._VOICE_ANALYSIS_TTL_SECONDS - 10
    for path in (stale_dir, active_dir, unrelated_dir, outside_dir):
        os.utime(path, (expired_time, expired_time))
    with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
        service_module._VOICE_ANALYSIS_SESSIONS["voice-analysis-active"] = {
            "analysis_dir": str(active_dir),
        }

    class Dispatcher:
        def register_executor(self, _task_type, _executor):
            return None

    service = VoiceService(
        task_service=SimpleNamespace(),
        dispatcher=Dispatcher(),
        artifact_service=SimpleNamespace(),
        runtime_router=SimpleNamespace(),
    )

    assert not stale_dir.exists()
    assert fresh_dir.is_dir()
    assert active_dir.is_dir()
    assert unrelated_dir.is_dir()
    assert outside_dir.is_dir()

    with service_module._VOICE_ANALYSIS_SESSIONS_LOCK:
        service_module._VOICE_ANALYSIS_SESSIONS["unsafe"] = {
            "analysis_dir": str(outside_dir),
        }
    service._discard_analysis_session("unsafe")
    assert outside_dir.is_dir()
    assert (outside_dir / "marker.txt").is_file()


def test_clone_manifest_path_is_restored_and_registered_as_an_artifact(
    monkeypatch,
):
    import src.core.tts.voice_profile as profile_module

    restored_profiles: list = []
    monkeypatch.setattr(
        profile_module,
        "get_voice_manager",
        lambda: SimpleNamespace(add_profile=restored_profiles.append),
    )
    result = {
        "profile_id": "clone-1",
        "name": "Clone",
        "category": "clone",
        "engine": "qwen3_clone",
        "ref_audio_path": "clone-ref.wav",
        "prompt_cache_path": "clone-prompt.pt",
        "clone_manifest_path": "clone-manifest.json",
    }

    VoiceService._restore_profile(result)

    assert len(restored_profiles) == 1
    assert restored_profiles[0].clone_manifest == "clone-manifest.json"

    artifact_calls: list[dict] = []
    service = _service_without_runtime()
    service._artifact_service = SimpleNamespace(
        register_artifact=lambda **kwargs: artifact_calls.append(kwargs)
    )
    service._register_voice_artifacts("voice.clone-1", result)

    manifest_artifact = next(
        call for call in artifact_calls if call["artifact_type"] == "voice.clone_manifest"
    )
    assert manifest_artifact["path"] == "clone-manifest.json"
    assert manifest_artifact["label"] == "Voice Clone Manifest"
    assert manifest_artifact["is_primary"] is False


def test_voice_routes_preserve_candidate_contract() -> None:
    from src.api.http.routes.voice import analyze_segments, clone_voice
    from src.api.http.schemas.voice import (
        SegmentAnalyzeRequest as SegmentAnalyzeBody,
        VoiceCloneRequest as VoiceCloneBody,
    )
    from src.core.tasks import TaskStatus

    captured: dict = {}

    class Service:
        def analyze_segments(self, request):
            captured["analysis_request"] = request
            return SegmentAnalyzeResult(
                audio_path="source.wav",
                mode="asr",
                analysis_id="analysis-1",
                source_fingerprint="sha256:source",
                segments=[
                    SegmentInfo(
                        index=0,
                        start=0.0,
                        end=4.0,
                        text="text",
                        duration=4.0,
                        score=91,
                        label="最优",
                        details={"rms_score": 90},
                    )
                ],
                candidates=[
                    VoiceCloneCandidate(
                        candidate_id="candidate-0001",
                        source_variant="separated_vocals",
                        start=0.0,
                        end=4.0,
                        text="text",
                        score=91,
                        label="最优",
                        details={"rms_score": 90},
                        reasons=["自动推荐片段"],
                        preview_audio_path="candidate.wav",
                    )
                ],
                recommended_indices=[0],
                recommended_candidate_id="candidate-0001",
            )

        def submit_clone_voice(self, request):
            captured["clone_request"] = request
            return TaskStatus(
                task_id="voice.clone-1",
                task_type="voice.clone",
                task_source="voice-lab",
                state="running",
                created_at="2026-08-30T00:00:00+00:00",
            )

    service = Service()
    response = analyze_segments(
        SegmentAnalyzeBody(
            audio_path="source.wav",
            separate_vocals=True,
            x_vector_only_mode=True,
        ),
        service,
    )
    clone_voice(
        VoiceCloneBody(
            audio_path="source.wav",
            name="Candidate Voice",
            x_vector_only_mode=True,
            analysis_id="analysis-1",
            candidate_id="candidate-0001",
            confirmed_text="confirmed",
        ),
        service,
    )

    assert response.analysis_id == "analysis-1"
    assert response.candidates[0].candidate_id == "candidate-0001"
    assert response.recommended_candidate_id == "candidate-0001"
    assert captured["analysis_request"].separate_vocals is True
    assert captured["analysis_request"].x_vector_only_mode is True
    assert captured["clone_request"].analysis_id == "analysis-1"
    assert captured["clone_request"].candidate_id == "candidate-0001"
    assert captured["clone_request"].confirmed_text == "confirmed"
