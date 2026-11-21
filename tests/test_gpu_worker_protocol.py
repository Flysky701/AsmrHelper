"""Comprehensive tests for Milestone 1A: `packages/protocol`, `packages/gpu_worker`, and Colab notebook."""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path
import threading
import time
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
import numpy as np
from pydantic import ValidationError
import pytest
import soundfile as sf

from packages.gpu_worker import (
    ComputeClient,
    LocalSubprocessTransport,
    ModelLeaseManager,
    RemoteHttpTransport,
    WorkerHandlers,
    create_worker_app,
)
from packages.gpu_worker.cli import execute_once_job, run_once_file
from packages.protocol import (
    PROTOCOL_VERSION,
    AlignmentRequest,
    AlignmentResult,
    AsrRequest,
    AsrResult,
    AsrSegmentItem,
    ComputeErrorCode,
    ComputeErrorPayload,
    ComputeRemoteError,
    SeparationRequest,
    SeparationResult,
    TtsBatchRequest,
    TtsSynthesizeItem,
    WorkerCapabilities,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_sine_wav(
    path: Path,
    *,
    freq_hz: float = 440.0,
    duration_sec: float = 1.5,
    sample_rate: int = 44100,
    stereo: bool = True,
) -> np.ndarray:
    """Generate a deterministic PCM_16 WAV file suitable for FLAC compression tests."""
    frames = int(sample_rate * duration_sec)
    t = np.linspace(0.0, duration_sec, frames, endpoint=False, dtype=np.float32)
    mono = 0.35 * np.sin(2.0 * np.pi * freq_hz * t)
    samples = np.column_stack([mono, 0.25 * mono]) if stereo else mono
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), samples, sample_rate, format="WAV", subtype="PCM_16")
    return samples


def _extract_multipart_audio_bytes(req: httpx.Request) -> tuple[str | None, bytes]:
    """Extract the first uploaded audio file part from a raw `httpx.Request`."""
    from email.parser import BytesParser
    import email.policy

    ct = req.headers.get("content-type", "")
    raw = req.read()
    envelope = f"Content-Type: {ct}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1")
    msg = BytesParser(policy=email.policy.HTTP).parsebytes(envelope + raw)
    for part in msg.iter_parts():
        fname = part.get_filename()
        if fname is not None:
            return fname, part.get_payload(decode=True) or b""
    raise AssertionError("No file part found in multipart request")


def _build_mock_handlers() -> WorkerHandlers:
    """Build deterministic stateless `WorkerHandlers` with lightweight audio callbacks."""
    lease_mgr = ModelLeaseManager(vram_total_mb=15360)

    def fake_separate(
        *, input_path: str, output_dir: str, model: str, stems: list[str]
    ) -> dict[str, str]:
        data, sr = sf.read(input_path, dtype="float32", always_2d=True)
        out: dict[str, str] = {}
        for idx, stem in enumerate(stems):
            scale = 0.8 if stem == "vocals" else (0.2 + 0.05 * idx)
            stem_file = Path(output_dir) / f"mock_{stem}.wav"
            sf.write(str(stem_file), data * scale, sr, format="WAV", subtype="PCM_16")
            out[stem] = str(stem_file)
        return out

    def fake_asr(*, input_path: str, request: AsrRequest) -> list[dict[str, Any]]:
        info = sf.info(input_path)
        end_t = round(min(1.2, info.duration), 3)
        return [
            {
                "start": 0.0,
                "end": end_t,
                "text": "こんにちは、テストです。",
                "language": request.language,
                "confidence": 0.96,
            }
        ]

    def fake_align(*, input_path: str, request: AlignmentRequest) -> dict[str, Any]:
        info = sf.info(input_path)
        dur = max(0.2, float(info.duration))
        step = dur / max(1, len(request.segments))
        aligned_segs = []
        words = []
        for idx, seg in enumerate(request.segments):
            s_t = round(idx * step, 3)
            e_t = round((idx + 1) * step, 3)
            aligned_segs.append({**seg, "start": s_t, "end": e_t})
            words.append(
                {
                    "text": str(seg["text"]),
                    "start": s_t,
                    "end": e_t,
                    "segment_index": idx,
                }
            )
        return {
            "segments": aligned_segs,
            "words": words,
            "warnings": [],
            "model": request.model,
            "time_unit": "seconds",
        }

    def fake_tts(
        *,
        item: TtsSynthesizeItem,
        request: TtsBatchRequest,
        reference_path: str | None,
        output_path: str,
    ) -> str:
        if item.text == "__FAIL__":
            raise RuntimeError("Simulated synthesis failure for bad cue")
        sr = 24000
        if reference_path:
            ref_info = sf.info(reference_path)
            assert ref_info.frames > 0
        t = np.linspace(0.0, 0.4, int(sr * 0.4), endpoint=False, dtype=np.float32)
        wave = 0.3 * np.sin(2.0 * np.pi * 330.0 * t)
        sf.write(output_path, wave, sr, format="WAV", subtype="PCM_16")
        return output_path

    return WorkerHandlers(
        lease_manager=lease_mgr,
        separate_fn=fake_separate,
        asr_fn=fake_asr,
        align_fn=fake_align,
        tts_fn=fake_tts,
    )


# ---------------------------------------------------------------------------
# 1. Layer Boundaries & Pure Pydantic v2 Protocol Contracts
# ---------------------------------------------------------------------------


def test_namespace_package_and_anti_bloat_boundaries() -> None:
    assert not (REPO_ROOT / "packages" / "__init__.py").exists(), (
        "packages/ must remain a PEP 420 namespace package without __init__.py"
    )

    forbidden_protocol_roots = {
        "torch",
        "fastapi",
        "starlette",
        "sqlite3",
        "httpx",
        "soundfile",
        "numpy",
        "src",
    }
    protocol_dir = REPO_ROOT / "packages" / "protocol"
    for py_file in protocol_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden_protocol_roots, f"{py_file.name} imported {top}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                assert top not in forbidden_protocol_roots, f"{py_file.name} imported {top}"

    forbidden_worker_modules = {
        "sqlite3",
        "draft_store",
        "draft_session_service",
    }
    worker_dir = REPO_ROOT / "packages" / "gpu_worker"
    for py_file in worker_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_worker_modules
                    assert not alias.name.startswith(("src.app", "src.api"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_worker_modules
                assert not node.module.startswith(("src.app", "src.api"))


def test_protocol_models_and_error_contracts() -> None:
    caps = WorkerCapabilities(device="cuda:0", cuda_available=True, vram_total_mb=15360)
    assert caps.protocol_version == PROTOCOL_VERSION == "1.0"
    assert "asr" in caps.supported_tasks
    assert "separate" in caps.supported_tasks

    with pytest.raises(ValidationError):
        WorkerCapabilities(vram_total_mb=-1)

    with pytest.raises(ValidationError):
        SeparationRequest(stems=[])

    with pytest.raises(ValidationError):
        AsrSegmentItem(start=3.0, end=1.5, text="invalid span")

    asr_req = AsrRequest(
        input_path="sample.wav",
        profile={
            "provider": "anime_whisper",
            "model": "litagin/anime-whisper",
            "common_options": {"language": "ja", "timestamps": True},
            "provider_options": {"batch_size": 4},
        },
    )
    assert asr_req.provider == "anime_whisper"
    assert asr_req.model == "litagin/anime-whisper"
    prof = asr_req.to_profile()
    assert prof["provider"] == "anime_whisper"
    assert prof["provider_options"]["batch_size"] == 4

    asr_res = AsrResult(
        segments=[AsrSegmentItem(start=0.5, end=2.0, text="テスト")],
        language="ja",
        provider="anime_whisper",
    )
    doc = asr_res.to_worker_document()
    assert doc["document"]["segments"][0]["text"] == "テスト"

    with pytest.raises(ValidationError):
        AlignmentRequest(segments=[{"text": "   "}])

    align_res = AlignmentResult(
        segments=[{"text": "あ", "start": 0.1, "end": 0.4}],
        words=[{"text": "あ", "start": 0.1, "end": 0.4, "segment_index": 0}],
    )
    assert align_res.to_runtime_dict()["time_unit"] == "seconds"

    with pytest.raises(ValidationError):
        TtsBatchRequest(provider_id="qwen3", items=[])

    err_payload = ComputeErrorPayload(
        code=ComputeErrorCode.OOM_ERROR,
        message="CUDA out of memory",
        retryable=True,
        stage="separate",
    )
    err = ComputeRemoteError(err_payload, status_code=503)
    assert err.code == "OOM_ERROR"
    assert err.retryable is True
    assert err.stage == "separate"
    assert err.status_code == 503
    assert "[OOM_ERROR] (separate)" in str(err)


# ---------------------------------------------------------------------------
# 2. ModelLeaseManager LRU Eviction, Unload Cleanup & Thread Safety
# ---------------------------------------------------------------------------


def test_model_lease_manager_stage_switch_and_cleanup_order() -> None:
    events: list[str] = []

    class DummyModel:
        def __init__(self, tag: str) -> None:
            self.tag = tag
            events.append(f"load:{tag}")

        def unload(self) -> None:
            events.append(f"unload:{self.tag}")

    mgr = ModelLeaseManager(
        vram_total_mb=15360,  # Simulates Colab Tesla T4 (<=16GB)
        cuda_cleanup_fn=lambda: events.append("cuda_empty_cache"),
    )
    assert mgr.max_heavy_models == 1
    assert mgr.evict_on_stage_switch is True

    with patch("packages.gpu_worker.vram_lease.gc.collect", wraps=__import__("gc").collect) as mock_gc:
        with mgr.lease("separate:htdemucs", lambda: DummyModel("demucs"), family="separate") as m1:
            assert m1.tag == "demucs"
            assert mgr.loaded_models() == ["separate:htdemucs"]

        # Re-acquiring the exact same model reuses cached instance without unloading.
        with mgr.lease("separate:htdemucs", lambda: DummyModel("demucs_reload"), family="separate"):
            assert events == ["load:demucs"]

        # Switching to ASR on <=16GB T4 must unload Demucs + GC + empty CUDA cache BEFORE loading ASR.
        with mgr.lease("asr:large-v3", lambda: DummyModel("whisper"), family="asr") as m2:
            assert m2.tag == "whisper"
            assert mgr.loaded_models() == ["asr:large-v3"]

        assert mock_gc.call_count >= 1
        assert events == [
            "load:demucs",
            "unload:demucs",
            "cuda_empty_cache",
            "load:whisper",
        ]


def test_model_lease_manager_multi_slot_lru_and_thread_contention() -> None:
    unloaded: list[str] = []

    class SlotModel:
        def __init__(self, name: str) -> None:
            self.name = name

        def unload(self) -> None:
            unloaded.append(self.name)

    mgr = ModelLeaseManager(max_heavy_models=2, evict_on_stage_switch=False)
    with mgr.lease("m:a", lambda: SlotModel("a"), family="asr"):
        pass
    with mgr.lease("m:b", lambda: SlotModel("b"), family="asr"):
        pass
    # Touch 'm:a' so 'm:b' becomes the least-recently-used entry.
    with mgr.lease("m:a", lambda: SlotModel("a2"), family="asr"):
        pass
    assert mgr.loaded_models() == ["m:b", "m:a"]

    with mgr.lease("m:c", lambda: SlotModel("c"), family="asr"):
        pass
    assert unloaded == ["b"]
    assert mgr.loaded_models() == ["m:a", "m:c"]

    # Thread contention check: an active lease must never be evicted mid-flight.
    strict_mgr = ModelLeaseManager(max_heavy_models=1)
    timeline: list[str] = []
    entered_event = threading.Event()
    release_event = threading.Event()

    class GuardedModel:
        def __init__(self, label: str) -> None:
            self.label = label
            timeline.append(f"load:{label}")

        def unload(self) -> None:
            timeline.append(f"unload:{self.label}")

    def worker_one() -> None:
        with strict_mgr.lease("separate:m1", lambda: GuardedModel("m1"), family="separate"):
            entered_event.set()
            release_event.wait(timeout=5.0)
            timeline.append("finish_inference:m1")

    t1 = threading.Thread(target=worker_one)
    t1.start()
    assert entered_event.wait(timeout=5.0)

    def worker_two() -> None:
        with strict_mgr.lease("asr:m2", lambda: GuardedModel("m2"), family="asr"):
            timeline.append("finish_inference:m2")

    t2 = threading.Thread(target=worker_two)
    t2.start()
    time.sleep(0.08)
    # While t1 still holds m1, m1 must not have been unloaded yet!
    assert "unload:m1" not in timeline
    release_event.set()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert timeline.index("finish_inference:m1") < timeline.index("unload:m1")
    assert timeline.index("unload:m1") < timeline.index("load:m2")


def test_model_lease_conflict_timeout_and_torch_cuda_empty_cache() -> None:
    mgr = ModelLeaseManager(max_heavy_models=1)
    held = threading.Event()
    done = threading.Event()

    def hold_worker() -> None:
        with mgr.lease("separate:busy", lambda: object(), family="separate"):
            held.set()
            done.wait(timeout=5.0)

    holder = threading.Thread(target=hold_worker)
    holder.start()
    assert held.wait(timeout=5.0)
    try:
        with pytest.raises(ComputeRemoteError) as exc_info:
            with mgr.lease("asr:blocked", lambda: object(), family="asr", timeout=0.05):
                pass
        assert exc_info.value.code == ComputeErrorCode.LEASE_CONFLICT
        assert exc_info.value.retryable is True
    finally:
        done.set()
        holder.join(timeout=5.0)

    with (
        patch("torch.cuda.is_available", return_value=True),
        patch("torch.cuda.empty_cache") as mock_empty_cache,
    ):
        evicted = mgr.evict()
        assert evicted == ["separate:busy"]
        assert mock_empty_cache.call_count >= 1


# ---------------------------------------------------------------------------
# 3. FastAPI Server Auth, Lease Eviction, and Endpoints
# ---------------------------------------------------------------------------


def test_worker_server_auth_and_endpoints(tmp_path: Path) -> None:
    handlers = _build_mock_handlers()
    app = create_worker_app(token="secret-colab-token", handlers=handlers)
    client = TestClient(app)

    # Missing Bearer token -> 401 AUTH_REQUIRED
    r_unauth = client.get("/v1/capabilities")
    assert r_unauth.status_code == 401
    assert r_unauth.json()["code"] == ComputeErrorCode.AUTH_REQUIRED

    # Wrong Bearer token -> 401 AUTH_INVALID
    r_bad = client.get("/v1/capabilities", headers={"Authorization": "Bearer wrong-token"})
    assert r_bad.status_code == 401
    assert r_bad.json()["code"] == ComputeErrorCode.AUTH_INVALID

    auth_headers = {"Authorization": "Bearer secret-colab-token"}
    r_caps = client.get("/v1/capabilities", headers=auth_headers)
    assert r_caps.status_code == 200
    assert r_caps.json()["protocol_version"] == "1.0"

    # Corrupt audio bytes -> 422 AUDIO_DECODE_ERROR
    r_corrupt = client.post(
        "/v1/asr",
        headers=auth_headers,
        files={"audio": ("broken.flac", b"NOT_VALID_AUDIO_BYTES", "audio/flac")},
        data={"options": json.dumps({"language": "ja"})},
    )
    assert r_corrupt.status_code == 422
    assert r_corrupt.json()["code"] == ComputeErrorCode.AUDIO_DECODE_ERROR

    # Valid base64 JSON ASR call + capabilities + manual eviction
    wav_path = tmp_path / "clip.wav"
    _make_sine_wav(wav_path, duration_sec=0.6)
    b64_wav = base64.b64encode(wav_path.read_bytes()).decode("ascii")
    r_asr = client.post(
        "/v1/asr",
        headers=auth_headers,
        json={"audio_b64": b64_wav, "language": "ja", "provider": "faster_whisper"},
    )
    assert r_asr.status_code == 200
    assert len(r_asr.json()["segments"]) == 1
    assert handlers.lease_manager.loaded_models() == ["asr:faster_whisper:large-v3"]

    r_evict = client.post("/v1/lease/evict", headers=auth_headers, json={})
    assert r_evict.status_code == 200
    assert r_evict.json()["evicted"] == ["asr:faster_whisper:large-v3"]
    assert r_evict.json()["loaded_models"] == []

    # Open mode (token=None) + raw audio/flac binary body with X-Compute-Options header
    open_app = create_worker_app(token=None, handlers=handlers)
    open_client = TestClient(open_app)
    assert open_client.get("/v1/capabilities").status_code == 200
    r_raw = open_client.post(
        "/v1/asr",
        content=wav_path.read_bytes(),
        headers={
            "Content-Type": "audio/wav",
            "X-Compute-Options": json.dumps({"language": "ja", "provider": "faster_whisper"}),
        },
    )
    assert r_raw.status_code == 200
    assert len(r_raw.json()["segments"]) == 1


# ---------------------------------------------------------------------------
# 4. RemoteHttpTransport FLAC Roundtrip via httpx.MockTransport + LocalSubprocessTransport
# ---------------------------------------------------------------------------


def test_remote_http_transport_flac_roundtrip_via_mock_transport(tmp_path: Path) -> None:
    handlers = _build_mock_handlers()
    app = create_worker_app(token="tunnel-key-999", handlers=handlers)
    asgi_client = TestClient(app)
    captured_requests: list[httpx.Request] = []

    def mock_bridge(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        resp = asgi_client.request(
            method=request.method,
            url=str(request.url.raw_path.decode("ascii")),
            headers=dict(request.headers),
            content=request.read(),
        )
        return httpx.Response(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content=resp.content,
        )

    mock_transport = httpx.MockTransport(mock_bridge)

    src_wav = tmp_path / "asmr_track.wav"
    original_samples = _make_sine_wav(src_wav, duration_sec=1.5, sample_rate=44100, stereo=True)
    wav_size = src_wav.stat().st_size

    with ComputeClient.from_remote(
        "https://demo-worker.trycloudflare.com",
        api_key="tunnel-key-999",
        transport=mock_transport,
    ) as compute:
        # 1) Capabilities
        caps = compute.capabilities()
        assert caps.vram_total_mb == 15360

        # 2) ASR + local SRT output materialization + FLAC upload check
        srt_out = tmp_path / "out" / "recognized.srt"
        asr_res = compute.asr(
            AsrRequest(
                input_path=str(src_wav),
                output_path=str(srt_out),
                provider="anime_whisper",
                model="litagin/anime-whisper",
                language="ja",
            )
        )
        assert len(asr_res.segments) == 1
        assert srt_out.is_file()
        assert "こんにちは" in srt_out.read_text(encoding="utf-8")

        asr_http_req = captured_requests[-1]
        up_name, up_bytes = _extract_multipart_audio_bytes(asr_http_req)
        assert up_name == "asmr_track.flac"
        assert up_bytes.startswith(b"fLaC"), "WAV input must be transcoded to lossless FLAC"
        assert len(up_bytes) < wav_size * 0.65, (
            f"Expected FLAC ({len(up_bytes)}B) to be significantly smaller than WAV ({wav_size}B)"
        )

        # 3) Separation -> lossless FLAC over wire -> materialized WAV stems locally
        stems_dir = tmp_path / "stems_out"
        sep_res = compute.separate(
            SeparationRequest(
                input_path=str(src_wav),
                output_dir=str(stems_dir),
                stems=["vocals", "other"],
                output_format="wav",
            )
        )
        assert set(sep_res.stem_paths.keys()) == {"vocals", "other"}
        vocals_file = Path(sep_res.stem_paths["vocals"])
        assert vocals_file.is_file()
        assert vocals_file.read_bytes().startswith(b"RIFF")
        vocals_arr, vocals_sr = sf.read(str(vocals_file), dtype="float32")
        assert vocals_sr == 44100
        assert np.allclose(vocals_arr, original_samples * 0.8, atol=1e-3)

        # 4) Forced Alignment
        align_res = compute.align(
            AlignmentRequest(
                input_path=str(src_wav),
                segments=[{"text": "こんにちは", "start": 0.0, "end": 1.0}],
                language="ja",
            )
        )
        assert len(align_res.segments) == 1
        assert align_res.words[0].text == "こんにちは"

        # 5) Batch TTS with reference WAV transcoded to FLAC + mixed WAV/FLAC local outputs
        cue1_wav = tmp_path / "tts_out" / "cue_001.wav"
        cue2_flac = tmp_path / "tts_out" / "cue_002.flac"
        tts_res = compute.tts_batch(
            TtsBatchRequest(
                provider_id="qwen3",
                model="qwen3-tts-1.7b",
                reference_audio_path=str(src_wav),
                items=[
                    TtsSynthesizeItem(
                        item_id="c1",
                        text="第一句测试台词",
                        variant_kind="reference",
                        output_path=str(cue1_wav),
                    ),
                    TtsSynthesizeItem(
                        item_id="c2",
                        text="第二句测试台词",
                        variant_kind="reference",
                        output_path=str(cue2_flac),
                    ),
                    TtsSynthesizeItem(
                        item_id="c_bad",
                        text="__FAIL__",
                    ),
                ],
            )
        )
        tts_http_req = captured_requests[-1]
        ref_up_name, ref_up_bytes = _extract_multipart_audio_bytes(tts_http_req)
        assert ref_up_name == "asmr_track.flac"
        assert ref_up_bytes.startswith(b"fLaC")

        by_id = {item.item_id: item for item in tts_res.items}
        assert by_id["c1"].ok is True
        assert cue1_wav.is_file() and cue1_wav.read_bytes().startswith(b"RIFF")
        assert by_id["c2"].ok is True
        assert cue2_flac.is_file() and cue2_flac.read_bytes().startswith(b"fLaC")
        assert by_id["c_bad"].ok is False
        assert by_id["c_bad"].error is not None

    # Verify wrong token propagates as ComputeRemoteError
    with ComputeClient.from_remote(
        "https://demo-worker.trycloudflare.com",
        api_key="wrong-token",
        transport=mock_transport,
    ) as bad_client:
        with pytest.raises(ComputeRemoteError) as exc_info:
            bad_client.capabilities()
        assert exc_info.value.code == ComputeErrorCode.AUTH_INVALID
        assert exc_info.value.status_code == 401

    # Verify timeout and connection errors map to retryable ComputeRemoteError
    def timeout_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Colab tunnel read timed out", request=req)

    timeout_transport = RemoteHttpTransport(
        "https://slow-tunnel.trycloudflare.com",
        api_key="k",
        transport=httpx.MockTransport(timeout_handler),
    )
    try:
        with pytest.raises(ComputeRemoteError) as t_exc:
            timeout_transport.capabilities()
        assert t_exc.value.code == ComputeErrorCode.TIMEOUT
        assert t_exc.value.retryable is True
    finally:
        timeout_transport.close()

    with patch.dict(
        "os.environ",
        {
            "ASMR_HELPER_REMOTE_WORKER_URL": "https://env-worker.trycloudflare.com",
            "ASMR_HELPER_REMOTE_WORKER_TOKEN": "env-tok",
        },
        clear=False,
    ):
        env_client = ComputeClient.from_env()
        assert env_client is not None
        env_client.close()


def test_local_subprocess_transport_and_cli_once(tmp_path: Path) -> None:
    # Real subprocess execution via `python -m packages.gpu_worker.cli --once <job.json>`
    local_client = ComputeClient(LocalSubprocessTransport(cwd=REPO_ROOT))
    caps = local_client.capabilities()
    assert caps.protocol_version == "1.0"
    assert "asr" in caps.supported_tasks

    evict_res = local_client.evict()
    assert evict_res.loaded_models == []

    with pytest.raises(ComputeRemoteError) as exc_info:
        local_client.asr(AsrRequest(input_path=str(tmp_path / "missing_file.wav")))
    assert exc_info.value.code == ComputeErrorCode.INVALID_REQUEST

    # Also verify `run_once_file` & `execute_once_job` with mock handlers for full local audio roundtrip
    wav_in = tmp_path / "local_input.wav"
    _make_sine_wav(wav_in, duration_sec=0.5)
    sep_dir = tmp_path / "local_stems"
    job_file = tmp_path / "job.json"
    resp_file = tmp_path / "resp.json"
    job_file.write_text(
        json.dumps(
            {
                "task": "separate",
                "request": {
                    "input_path": str(wav_in),
                    "output_dir": str(sep_dir),
                    "stems": ["vocals"],
                    "output_format": "wav",
                },
                "response_path": str(resp_file),
            }
        ),
        encoding="utf-8",
    )
    handlers = _build_mock_handlers()
    rc = run_once_file(job_file, handlers=handlers)
    assert rc == 0
    envelope = json.loads(resp_file.read_text(encoding="utf-8"))
    assert envelope["ok"] is True
    sep_res = SeparationResult.model_validate(envelope["result"])
    assert Path(sep_res.stem_paths["vocals"]).is_file()
    assert sep_res.stem_audio_b64 == {}, "Local mode with output_dir avoids base64 overhead"

    direct_env = execute_once_job(
        {"task": "asr", "request": {"input_path": str(wav_in), "language": "ja"}},
        handlers=handlers,
    )
    assert direct_env["ok"] is True
    assert len(direct_env["result"]["segments"]) == 1


# ---------------------------------------------------------------------------
# 5. Colab Notebook Structure & Syntax Validation
# ---------------------------------------------------------------------------


def test_colab_gpu_worker_notebook_structure() -> None:
    nb_path = REPO_ROOT / "notebooks" / "colab_gpu_worker.ipynb"
    assert nb_path.is_file(), "notebooks/colab_gpu_worker.ipynb must exist"

    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    assert nb["nbformat_minor"] >= 4
    cells = {cell["id"]: "".join(cell["source"]) for cell in nb["cells"]}
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            ast.parse(cells[cell["id"]], filename=f"{cell['id']}.py")

    setup = cells["setup"]
    assert "drive.mount(" in setup and "ASMR_HELPER_MODEL_ROOT" in setup
    assert "ASMR_COLAB_REVISION" in setup and "faster-whisper" in setup
    assert "ASMR_COLAB_JOB_DIR" in cells["parameters"]
    assert "packages.gpu_worker.cli" in cells["asr"] and "--once" in cells["asr"]
    assert "result.srt" in cells["asr"] and "files.download" in cells["export"]

    models = cells["optional-worker-models"]
    assert "INSTALL_AUDIO_SEPARATOR = False" in models
    assert "audio-separator[gpu]" in models and "AUDIO_SEPARATOR_MODEL_DIR" in models
    server = cells["optional-worker-server"]
    assert "START_WORKER = False" in server
    assert "if START_WORKER and not cli_job_dir" in server
    assert "packages.gpu_worker.cli" in server and "--serve" in server
    assert "getpass(" in server and "ASMR_WORKER_TOKEN" in server
    assert "ASMR_HELPER_REMOTE_WORKER_URL" in cells["worker-connection"]
    assert "ASMR_HELPER_REMOTE_WORKER_TOKEN" in cells["worker-connection"]
