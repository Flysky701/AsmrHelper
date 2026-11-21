"""End-to-end V2 modular architecture vertical-slice integration tests.

Covers the complete cross-module workflow without manual PYTHONPATH hacks:
- MCP JSON-RPC 2.0 `tools/call` (`asmr_inspect_work` -> `asmr_prepare_draft` ->
  `asmr_get_draft_audit` -> `asmr_patch_draft` -> `asmr_commit_draft`)
- Remote Colab GPU worker delegation via `RuntimeRouter` -> `ComputeClient(RemoteHttpTransport)`
  -> `packages.gpu_worker.server.create_worker_app` (lossless FLAC upload + Bearer auth)
- Pre-ASR acoustic VAD slicing (`slice_speech_regions`) across >29s ASMR silence valleys
- Deterministic `QualityAuditReport` backed by `src.mixer.binaural.plan_cue_slots`
- Phase-2 `commit_draft` binaural Left/Right/Center stereo panning follower, inter-cue
  silence-slack borrowing (`atempo == 1.0x`), and bilingual `.srt` / `.lrc` export
- Local vs remote `RuntimeRouter` preservation for both ASR and forced alignment
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import httpx
import numpy as np
import pytest
import soundfile as sf

from packages.gpu_worker.handlers import WorkerHandlers
from packages.gpu_worker.server import create_worker_app
from packages.mcp_server import McpStdioServer, McpToolRegistry
from packages.protocol.compute import (
    AlignmentRequest,
    AlignmentResult,
    AlignmentWordItem,
    AsrRequest,
    AsrResult,
    AsrSegmentItem,
)
from src.app.dto import TranslationResult
from src.app.persistence.draft_store import DraftStore
from src.app.persistence.state_store import SqliteStateStore
from src.app.services.artifact_service import ArtifactService
from src.app.services.asr_engine_service import AsrEngineService
from src.app.services.capability_descriptor_service import CapabilityDescriptorService
from src.app.services.draft_session_service import DraftSessionService
from src.app.services.execution_profile_builder import ExecutionProfileBuilder
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.core.engines.alignment import AlignmentRuntime
from src.core.engines.asr.service import AsrEngineRuntime
from src.core.engines.asr.vad_slicer import slice_speech_regions
from src.core.runtime.profiles import RuntimeProfileResolver
from src.core.runtime.router import RuntimeRouter, RuntimeWorkerError
from src.core.speech.providers import get_provider
from src.core.speech.store import SpeechStore
from src.core.subtitles.parser import SubtitleParser


def _build_binaural_work_directory(work_dir: Path, *, sample_rate: int = 48000) -> dict[str, Path]:
    """Create a 38s 48kHz stereo ASMR work with Left/Right/Center vocal cues and a 30s silence gap."""
    work_dir.mkdir(parents=True, exist_ok=True)
    duration_sec = 38.0
    total_frames = int(round(duration_sec * sample_rate))
    t = np.arange(total_frames, dtype=np.float32) / sample_rate

    # Subtle stereo ambient bed for SE-only stem
    se_left = (0.004 * np.sin(2.0 * np.pi * 140.0 * t)).astype(np.float32)
    se_right = (0.004 * np.cos(2.0 * np.pi * 145.0 * t)).astype(np.float32)
    se_stereo = np.stack([se_left, se_right], axis=1)

    # Clean stereo vocals with distinct Left / Right / Center ear positioning:
    # - Cue 0 [1.0s, 2.2s]: Hard Left ear (L=0.35, R=0.01)
    # - Cue 1 [2.4s, 4.0s]: Hard Right ear (L=0.01, R=0.35), followed by a 30.2s silence gap!
    # - Cue 2 [34.2s, 36.2s]: Center whisper (L=0.26, R=0.26)
    voc_left = np.zeros(total_frames, dtype=np.float32)
    voc_right = np.zeros(total_frames, dtype=np.float32)

    def _add_burst(start_s: float, end_s: float, amp_l: float, amp_r: float, freq: float) -> None:
        i0 = int(round(start_s * sample_rate))
        i1 = int(round(end_s * sample_rate))
        burst = np.sin(2.0 * np.pi * freq * t[i0:i1]).astype(np.float32)
        voc_left[i0:i1] += amp_l * burst
        voc_right[i0:i1] += amp_r * burst

    _add_burst(1.0, 2.2, 0.35, 0.01, 240.0)
    _add_burst(2.4, 4.0, 0.01, 0.35, 280.0)
    _add_burst(34.2, 36.2, 0.26, 0.26, 220.0)

    vocals_stereo = np.stack([voc_left, voc_right], axis=1)
    main_stereo = np.clip(vocals_stereo + se_stereo, -0.98, 0.98)

    main_path = work_dir / "01_ear_care.wav"
    vocals_path = work_dir / "01_ear_care_vocals.wav"
    se_path = work_dir / "01_ear_care_se_only.wav"
    script_path = work_dir / "01_ear_care_script.txt"

    sf.write(str(main_path), main_stereo, sample_rate, subtype="PCM_16")
    sf.write(str(vocals_path), vocals_stereo, sample_rate, subtype="PCM_16")
    sf.write(str(se_path), se_stereo, sample_rate, subtype="PCM_16")
    script_path.write_text(
        "左耳でささやきますね\n今度は右耳でゆっくり話します\nおやすみなさい\n",
        encoding="utf-8",
    )
    return {
        "main": main_path,
        "vocals": vocals_path,
        "se_only": se_path,
        "script": script_path,
    }


def _bridge_worker_app_to_mock_transport(worker_app: Any) -> tuple[httpx.MockTransport, list[dict[str, Any]]]:
    """Bridge `httpx.MockTransport` directly into a FastAPI `create_worker_app` TestClient."""
    client = TestClient(worker_app, raise_server_exceptions=False)
    wire_log: list[dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        wire_log.append(
            {
                "method": request.method,
                "path": request.url.raw_path.decode("ascii"),
                "auth": request.headers.get("authorization"),
                "content_type": request.headers.get("content-type"),
                "body_len": len(body),
                "has_flac_magic": b"fLaC" in body,
            }
        )
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "content-length"}
        }
        resp = client.request(
            request.method,
            request.url.raw_path.decode("ascii"),
            content=body,
            headers=headers,
        )
        return httpx.Response(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content=resp.content,
            request=request,
        )

    return httpx.MockTransport(_handler), wire_log


def _run_mcp_session(registry: McpToolRegistry, requests: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Execute a batch of JSON-RPC 2.0 requests through `McpStdioServer` and index responses by id."""
    stdin_buf = io.StringIO("\n".join(json.dumps(req, ensure_ascii=False) for req in requests) + "\n")
    stdout_buf = io.StringIO()
    server = McpStdioServer(registry=registry)
    assert server.serve_stdio(stdin=stdin_buf, stdout=stdout_buf, stderr=io.StringIO()) == 0
    responses: dict[int, dict[str, Any]] = {}
    for line in stdout_buf.getvalue().splitlines():
        if line.strip():
            msg = json.loads(line)
            if "id" in msg:
                responses[int(msg["id"])] = msg
    return responses


def test_v2_vertical_slice_mcp_remote_colab_vad_audit_binaural_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full V2 slice: MCP stdio -> Remote Colab Worker (FLAC + VAD) -> Gate Audit -> Patch -> Binaural Commit."""
    data_dir = tmp_path / "isolated_data"
    db_path = data_dir / "state.sqlite3"
    voice_lab_dir = data_dir / "voice_lab"
    monkeypatch.setenv("ASMR_HELPER_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ASMR_HELPER_STATE_DB", str(db_path))
    monkeypatch.setenv("ASMR_HELPER_VOICE_LAB_DIR", str(voice_lab_dir))
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_URL", raising=False)

    work_dir = tmp_path / "RJ999888_BinauralWhisper"
    _build_binaural_work_directory(work_dir, sample_rate=48000)

    # 1. Build real stateless GPU worker app simulating a Colab T4 tunnel endpoint
    worker_received: dict[str, Any] = {}

    def _colab_asr_handler(*, input_path: str, request: AsrRequest) -> AsrResult:
        staged = Path(input_path)
        assert staged.is_file()
        assert staged.suffix.lower() == ".flac"

        # Run real acoustic pre-ASR VAD slicer on mono 16kHz downmix to verify >30s silence split
        samples, sr = sf.read(str(staged), dtype="float32", always_2d=True)
        mono = samples.mean(axis=1)
        step = max(1, round(sr / 16000))
        mono_16k = mono[::step].astype(np.float32)
        vad_regions = slice_speech_regions(mono_16k, sample_rate=16000)

        worker_received["provider"] = request.provider
        worker_received["model"] = request.model
        worker_received["vad_slicing"] = request.provider_options.get("vad_slicing")
        worker_received["vad_regions"] = vad_regions

        # Acoustic VAD must split across the 30-second silence valley ([4.0s .. 34.2s])
        assert len(vad_regions) == 2
        assert vad_regions[0][1] < 6.0
        assert vad_regions[1][0] > 32.0

        return AsrResult(
            provider=request.provider,
            model=request.model,
            language="ja",
            segments=[
                AsrSegmentItem(start=1.0, end=2.2, text="左耳でささやきますね", language="ja"),
                AsrSegmentItem(start=2.4, end=4.0, text="今度は右耳でゆっくり話します", language="ja"),
                AsrSegmentItem(start=34.2, end=36.2, text="おやすみなさい", language="ja"),
            ],
        )

    colab_app = create_worker_app(
        token="colab-tunnel-token-xyz",
        handlers=WorkerHandlers(asr_fn=_colab_asr_handler),
    )
    mock_transport, wire_log = _bridge_worker_app_to_mock_transport(colab_app)

    # 2. Wire real AsrEngineService -> AsrEngineRuntime -> RuntimeRouter(remote_transport=...)
    class _StubSettings:
        def get_settings(self, masked: bool = False) -> dict[str, Any]:
            return {"processing": {"asr_model": "faster-whisper-base"}}

    router = RuntimeRouter(
        resolver=RuntimeProfileResolver(project_root=tmp_path),
        project_root=tmp_path,
        remote_transport=mock_transport,
    )
    asr_service = AsrEngineService(
        capability_service=CapabilityDescriptorService(),
        profile_builder=ExecutionProfileBuilder(_StubSettings(), CapabilityDescriptorService()),  # type: ignore[arg-type]
        runtime=AsrEngineRuntime(runtime_router=router),
    )

    class _StubLlmService:
        def translate_texts(self, *, texts: list[str], **kwargs: Any) -> TranslationResult:
            assert len(texts) == 3
            return TranslationResult(
                items=[
                    # Cue 0 [1.0, 2.2], next at 2.4 -> max slot 1.34s; 27 chars -> ~6.43s -> OVER SPEED!
                    "现在让我贴在你的左耳边轻声细语地一直温柔陪伴着你入睡吧",
                    # Cue 1 [2.4, 4.0], next at 34.2 -> 30s silence slack; 18 chars -> ~4.29s -> borrows slack, NOT over-speed!
                    "接下来换到你的右耳边慢慢地轻声对你说",
                    # Cue 2 [34.2, 36.2] -> contains Japanese kana residue ("ですね")!
                    "晚安好梦ですね",
                ],
                provider="deepseek",
                source_lang="ja",
                target_lang="zh",
            )

    state_store = SqliteStateStore(db_path)
    draft_store = DraftStore(state_store=state_store)
    tasks = TaskService(state_store=state_store)
    artifacts = ArtifactService(state_store=state_store)
    speech_svc = SpeechService(
        store=SpeechStore(voice_lab_dir),
        tasks=tasks,
        artifacts=artifacts,
    )

    tts_calls: list[str] = []

    def _offline_edge_tts(request: dict[str, Any], output_path: Path, context: Any, cancel_check: Any) -> dict[str, Any]:
        text = str(request.get("input", {}).get("text") or request.get("text") or "")
        tts_calls.append(text)
        sr = 24000
        # Make Cue 1 ("接下来换到...") 3.2s long (> 1.6s natural slot!) to exercise silence-slack borrowing!
        dur_sec = 3.2 if "右耳" in text else 0.9
        frames = int(round(dur_sec * sr))
        t = np.arange(frames, dtype=np.float32) / sr
        mono_wave = (0.18 * np.sin(2.0 * np.pi * 310.0 * t)).astype(np.float32)
        sf.write(str(output_path), mono_wave, sr, subtype="PCM_16")
        return {"model": request["model"], "sample_rate": sr}

    monkeypatch.setattr(get_provider("edge"), "synthesize", _offline_edge_tts)

    draft_service = DraftSessionService(
        store=draft_store,
        asr_service=asr_service,
        llm_service=_StubLlmService(),
        speech_service=speech_svc,
        artifact_service=artifacts,
    )
    registry = McpToolRegistry(draft_service=draft_service, speech_service=speech_svc)

    # 3. Step A & B via MCP stdio: initialize -> tools/list -> asmr_inspect_work -> asmr_prepare_draft
    phase1_responses = _run_mcp_session(
        registry,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "producer-agent"}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "asmr_inspect_work", "arguments": {"path_or_dir": str(work_dir)}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "asmr_prepare_draft",
                    "arguments": {
                        "path_or_dir": str(work_dir),
                        "asr_provider": "anime_whisper",
                        "extract_voice_reference": True,
                        "remote_worker_url": "https://colab-t4.trycloudflare.com",
                        "remote_worker_token": "colab-tunnel-token-xyz",
                    },
                },
            },
        ],
    )

    tool_names = [t["name"] for t in phase1_responses[2]["result"]["tools"]]
    assert set(tool_names) == {
        "asmr_inspect_work",
        "asmr_prepare_draft",
        "asmr_get_draft_audit",
        "asmr_patch_draft",
        "asmr_commit_draft",
        "asmr_list_voices_and_presets",
    }

    inspect_res = phase1_responses[3]["result"]["structuredContent"]
    assert inspect_res["readiness"]["recommended_mode"] == "asr_and_translate"
    assert inspect_res["readiness"]["has_clean_vocal_or_no_se_stem"] is True
    assert inspect_res["tracks"][0]["sample_rate"] == 48000
    assert inspect_res["tracks"][0]["channels"] == 2
    assert Path(inspect_res["tracks"][0]["paired_stems"]["vocals"]).name == "01_ear_care_vocals.wav"
    assert Path(inspect_res["tracks"][0]["paired_stems"]["se_only"]).name == "01_ear_care_se_only.wav"

    prep_res = phase1_responses[4]["result"]["structuredContent"]
    assert phase1_responses[4]["result"]["isError"] is False, prep_res
    draft_id = prep_res["draft_id"]
    assert prep_res["state"] == "awaiting_review"
    assert prep_res["revision"] == 1
    assert len(tts_calls) == 0  # Phase-1 gate MUST NOT run full-track TTS

    # Verify Colab RemoteHttpTransport uploaded lossless FLAC with Bearer token & VAD slicing enabled
    assert len(wire_log) == 1
    assert wire_log[0]["path"] == "/v1/asr"
    assert wire_log[0]["auth"] == "Bearer colab-tunnel-token-xyz"
    assert wire_log[0]["has_flac_magic"] is True
    assert worker_received["provider"] == "anime_whisper"
    assert worker_received["vad_slicing"] is True

    # Verify slack-aware QualityAuditReport (`plan_cue_slots`)
    audit = prep_res["audit_report"]
    assert audit["gate_passed"] is False
    assert [c["index"] for c in audit["over_speed_cues"]] == [0]  # Cue 1 NOT flagged thanks to 30s post-cue slack!
    assert audit["japanese_residue_indices"] == [2]
    assert audit["untranslated_indices"] == []

    # 4. Step C, D, E via MCP stdio: asmr_get_draft_audit -> asmr_patch_draft -> asmr_commit_draft
    output_dir = tmp_path / "final_delivery"
    phase2_responses = _run_mcp_session(
        registry,
        [
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "asmr_get_draft_audit",
                    "arguments": {"draft_id": draft_id, "include_segments": True},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "asmr_patch_draft",
                    "arguments": {
                        "draft_id": draft_id,
                        "expected_revision": 1,
                        "edits": [
                            {"index": 0, "translation": "在左耳陪你"},
                            {"index": 2, "translation": "晚安好梦"},
                        ],
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "asmr_commit_draft",
                    "arguments": {
                        "draft_id": draft_id,
                        "expected_revision": 2,
                        "output_dir": str(output_dir),
                        "export_formats": ["srt", "lrc"],
                        "enable_dubbing": True,
                    },
                },
            },
        ],
    )

    audit_call = phase2_responses[10]["result"]["structuredContent"]
    assert len(audit_call["segments"]) == 3

    patched_res = phase2_responses[11]["result"]["structuredContent"]
    assert patched_res["state"] == "awaiting_review"
    assert patched_res["revision"] == 2
    assert patched_res["audit_report"]["over_speed_cues"] == []
    assert patched_res["audit_report"]["japanese_residue_indices"] == []
    assert patched_res["audit_report"]["gate_passed"] is True

    commit_res = phase2_responses[12]["result"]["structuredContent"]
    assert phase2_responses[12]["result"]["isError"] is False, commit_res
    assert commit_res["state"] == "completed"
    assert len(tts_calls) == 3

    # 5. Verify exported bilingual SRT & LRC subtitles
    srt_path = Path(commit_res["artifacts"]["subtitles"]["srt"])
    lrc_path = Path(commit_res["artifacts"]["subtitles"]["lrc"])
    assert srt_path.is_file()
    assert lrc_path.is_file()

    lrc_content = lrc_path.read_text(encoding="utf-8")
    assert "[00:01.00]左耳でささやきますね / 在左耳陪你" in lrc_content
    assert "[00:02.40]今度は右耳でゆっくり話します / 接下来换到你的右耳边慢慢地轻声对你说" in lrc_content
    assert "[00:34.20]おやすみなさい / 晚安好梦" in lrc_content

    srt_doc = SubtitleParser().parse_text(srt_path.read_text(encoding="utf-8"), "srt")
    assert len(srt_doc.segments) == 3

    # 6. Verify 48kHz stereo binaural panning + inter-cue silence-slack borrowing on assembled & mixed audio
    dubbing_meta = commit_res["artifacts"]["dubbing"]
    assert dubbing_meta["borrow_silence_slack"] is True
    assert dubbing_meta["channels"] == 2
    proc = dubbing_meta["processing"]
    assert len(proc) == 3

    # Cue 0: Hard Left ear (`pan < -0.7`)
    assert proc[0]["pan"] < -0.7
    # Cue 1: Hard Right ear (`pan > 0.7`) + borrowed ~1.6s silence slack so `time_stretch == 1.0`!
    assert proc[1]["pan"] > 0.7
    assert proc[1]["borrowed_seconds"] == pytest.approx(1.6, abs=0.05)
    assert proc[1]["time_stretch"] == pytest.approx(1.0, abs=1e-6)
    assert proc[1]["over_speed"] is False
    # Cue 2: Center whisper (`|pan| < 0.1`)
    assert abs(proc[2]["pan"]) < 0.1

    tts_wav = Path(dubbing_meta["tts_track_path"])
    mixed_wav = Path(dubbing_meta["mixed_audio_path"])
    tts_info = sf.info(str(tts_wav))
    mixed_info = sf.info(str(mixed_wav))
    assert tts_info.channels == 2
    assert tts_info.samplerate == 48000
    assert mixed_info.channels == 2
    assert mixed_info.samplerate == 48000

    tts_samples, sr = sf.read(str(tts_wav), dtype="float32", always_2d=True)
    # Check actual Left vs Right RMS energy in the assembled stereo TTS track
    c0_slice = tts_samples[int(1.05 * sr) : int(1.85 * sr)]
    c1_slice = tts_samples[int(2.45 * sr) : int(5.40 * sr)]
    c2_slice = tts_samples[int(34.25 * sr) : int(35.05 * sr)]

    assert np.sqrt(np.mean(c0_slice[:, 0] ** 2)) > 8.0 * np.sqrt(np.mean(c0_slice[:, 1] ** 2))
    assert np.sqrt(np.mean(c1_slice[:, 1] ** 2)) > 8.0 * np.sqrt(np.mean(c1_slice[:, 0] ** 2))
    assert np.sqrt(np.mean(c2_slice[:, 0] ** 2)) == pytest.approx(
        np.sqrt(np.mean(c2_slice[:, 1] ** 2)),
        rel=0.08,
    )


def test_runtime_router_env_remote_alignment_and_local_preservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify `ASMR_HELPER_REMOTE_WORKER_URL` delegates `align_file` & `transcribe_file`, and unset keeps local behavior."""
    audio_path = tmp_path / "line.wav"
    sr = 16000
    tone = (0.2 * np.sin(2.0 * np.pi * 220.0 * (np.arange(sr * 2, dtype=np.float32) / sr))).astype(np.float32)
    sf.write(str(audio_path), tone, sr, subtype="PCM_16")

    def _align_handler(*, input_path: str, request: AlignmentRequest) -> AlignmentResult:
        assert Path(input_path).suffix.lower() == ".flac"
        return AlignmentResult(
            segments=[{"start": 0.12, "end": 1.68, "text": request.segments[0]["text"]}],
            words=[AlignmentWordItem(text="おは", start=0.12, end=0.80, segment_index=0)],
            warnings=[],
            model=request.model,
        )

    worker_app = create_worker_app(
        token="env-token-777",
        handlers=WorkerHandlers(align_fn=_align_handler),
    )
    mock_transport, wire_log = _bridge_worker_app_to_mock_transport(worker_app)

    # 1. With ASMR_HELPER_REMOTE_WORKER_URL set -> AlignmentRuntime delegates over RemoteHttpTransport
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_URL", "https://remote-align.trycloudflare.com")
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", "env-token-777")
    remote_router = RuntimeRouter(
        resolver=RuntimeProfileResolver(project_root=tmp_path),
        project_root=tmp_path,
        remote_transport=mock_transport,
    )
    monkeypatch.setattr("src.core.runtime.get_runtime_router", lambda: remote_router)

    aligned = AlignmentRuntime(local=False).align_file(
        input_path=str(audio_path),
        segments=[{"start": 0.0, "end": 1.9, "text": "おはよう"}],
        language="ja",
    )
    assert aligned["segments"] == [{"start": 0.12, "end": 1.68, "text": "おはよう"}]
    assert aligned["words"][0]["text"] == "おは"
    assert wire_log[-1]["path"] == "/v1/align"
    assert wire_log[-1]["has_flac_magic"] is True

    # Invalid token raises RuntimeWorkerError wrapping ComputeRemoteError
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", "wrong-token")
    with pytest.raises(RuntimeWorkerError, match="AUTH_INVALID"):
        AlignmentRuntime(local=False).align_file(
            input_path=str(audio_path),
            segments=[{"start": 0.0, "end": 1.9, "text": "おはよう"}],
            language="ja",
        )

    # 2. With ASMR_HELPER_REMOTE_WORKER_URL unset -> 100% local subprocess behavior preserved
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_URL", raising=False)
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", raising=False)
    local_router = RuntimeRouter(
        resolver=RuntimeProfileResolver(project_root=tmp_path),
        project_root=tmp_path,
        remote_transport=mock_transport,
    )
    assert local_router.has_remote_worker() is False
    with pytest.raises(RuntimeWorkerError, match="runtime environment is not installed: qwen_asr"):
        local_router.align_file(
            {
                "input_path": str(audio_path),
                "segments": [{"start": 0.0, "end": 1.9, "text": "おはよう"}],
                "language": "ja",
            }
        )
