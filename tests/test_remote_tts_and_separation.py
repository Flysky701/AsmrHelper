"""Offline integration tests for Wave 2A: Remote GPU delegation for `qwen3` & `voxcpm2` TTS and Demucs separation."""

from __future__ import annotations

from email.parser import BytesParser
import email.policy
import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import httpx
import numpy as np
import pytest
import soundfile as sf

from packages.gpu_worker import ModelLeaseManager, WorkerHandlers, create_worker_app
from packages.protocol import TtsBatchRequest, TtsSynthesizeItem
from src.app.services.artifact_service import ArtifactService
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.core.engines.separator.service import SeparatorEngineRuntime, SeparatorEngineService
from src.core.speech.providers import ProviderError, get_provider
from src.core.speech.store import SpeechStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_sine_wav(
    path: Path,
    *,
    freq_hz: float = 440.0,
    duration_sec: float = 1.2,
    sample_rate: int = 24000,
    stereo: bool = False,
) -> np.ndarray:
    frames = int(sample_rate * duration_sec)
    t = np.linspace(0.0, duration_sec, frames, endpoint=False, dtype=np.float32)
    mono = 0.35 * np.sin(2.0 * np.pi * freq_hz * t)
    samples = np.column_stack([mono, 0.5 * mono]) if stereo else mono
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), samples, sample_rate, format="WAV", subtype="PCM_16")
    return samples


def _extract_multipart_parts(req: httpx.Request) -> tuple[dict[str, Any], dict[str, tuple[str | None, bytes]]]:
    ct = req.headers.get("content-type", "")
    raw = req.read()
    envelope = f"Content-Type: {ct}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1")
    msg = BytesParser(policy=email.policy.HTTP).parsebytes(envelope + raw)
    fields: dict[str, Any] = {}
    files: dict[str, tuple[str | None, bytes]] = {}
    for part in msg.iter_parts():
        name = str(part.get_param("name", header="content-disposition") or "")
        fname = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if fname is not None:
            files[name] = (fname, payload)
        else:
            text = payload.decode("utf-8", errors="replace")
            try:
                fields[name] = json.loads(text)
            except Exception:
                fields[name] = text
    return fields, files


def _build_worker_harness(token: str | None = "colab-secret-token"):
    """Build an in-memory `create_worker_app` bridged via `httpx.MockTransport`."""
    lease_mgr = ModelLeaseManager(vram_total_mb=15360)
    tts_invocations: list[dict[str, Any]] = []
    sep_invocations: list[dict[str, Any]] = []
    http_requests: list[httpx.Request] = []

    def fake_tts(
        *,
        item: TtsSynthesizeItem,
        request: TtsBatchRequest,
        reference_path: str | None,
        output_path: str,
    ) -> str:
        if item.text == "__REMOTE_ERROR__":
            raise RuntimeError("Simulated GPU TTS failure")
        ref_frames = None
        if reference_path is not None:
            ref_info = sf.info(reference_path)
            ref_frames = ref_info.frames
            assert ref_frames > 0
        tts_invocations.append(
            {
                "provider_id": request.provider_id,
                "model": request.model,
                "item": item.model_dump(),
                "has_reference": reference_path is not None,
                "reference_frames": ref_frames,
            }
        )
        sr = 48000 if request.provider_id == "voxcpm2" else 24000
        dur = 0.35
        t = np.linspace(0.0, dur, int(sr * dur), endpoint=False, dtype=np.float32)
        freq = 330.0 if request.provider_id == "qwen3" else 520.0
        wave = 0.25 * np.sin(2.0 * np.pi * freq * t)
        sf.write(output_path, wave, sr, format="WAV", subtype="PCM_16")
        return output_path

    def fake_separate(
        *,
        input_path: str,
        output_dir: str,
        model: str,
        stems: list[str],
    ) -> dict[str, str]:
        data, sr = sf.read(input_path, dtype="float32", always_2d=True)
        sep_invocations.append(
            {
                "model": model,
                "stems": list(stems),
                "sample_rate": sr,
                "frames": len(data),
            }
        )
        out: dict[str, str] = {}
        for stem in stems:
            scale = 0.75 if stem == "vocals" else (0.25 if stem == "no_vocals" else 0.15)
            stem_file = Path(output_dir) / f"worker_{stem}.wav"
            sf.write(str(stem_file), data * scale, sr, format="WAV", subtype="PCM_16")
            out[stem] = str(stem_file)
        return out

    handlers = WorkerHandlers(
        lease_manager=lease_mgr,
        tts_fn=fake_tts,
        separate_fn=fake_separate,
    )
    app = create_worker_app(token=token, handlers=handlers)
    asgi_client = TestClient(app)

    def bridge(request: httpx.Request) -> httpx.Response:
        http_requests.append(request)
        resp = asgi_client.request(
            method=request.method,
            url=request.url.raw_path.decode("ascii"),
            headers=dict(request.headers),
            content=request.read(),
        )
        return httpx.Response(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content=resp.content,
        )

    transport = httpx.MockTransport(bridge)
    return transport, http_requests, tts_invocations, sep_invocations


def _install_mock_httpx_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.BaseTransport) -> None:
    original_client = httpx.Client

    def patched_client(**kwargs: Any) -> httpx.Client:
        kwargs.setdefault("transport", transport)
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)


# ---------------------------------------------------------------------------
# 1. Remote Worker `probe()` Without Local `.runtimes` or Model Weights
# ---------------------------------------------------------------------------


def test_probe_remote_worker_without_local_weights(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_URL", raising=False)
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", raising=False)

    transport, http_requests, _, _ = _build_worker_harness(token="probe-secret-123")

    # Without remote worker URL and with missing local model_path, probe fails as before.
    local_missing = get_provider("qwen3").probe(
        {
            "model": "qwen3-base",
            "mode": "reference",
            "model_path": str(tmp_path / "nonexistent_weights"),
        }
    )
    assert local_missing["ready"] is False

    # With deployment="remote_gpu" + base_url on connection, probe queries /v1/capabilities.
    remote_ctx = {
        "model": "qwen3-base",
        "mode": "reference",
        "connection": {
            "deployment": "remote_gpu",
            "base_url": "https://colab-t4.trycloudflare.com",
            "api_key": "probe-secret-123",
            "remote_transport": transport,
        },
    }
    qwen_ready = get_provider("qwen3").probe(remote_ctx)
    assert qwen_ready["ready"] is True
    assert qwen_ready["reachable"] is True
    assert qwen_ready["verified"] is True
    assert qwen_ready["vram_total_mb"] == 15360
    assert http_requests[-1].url.path == "/v1/capabilities"

    # Mode/model mismatch is still caught deterministically before/without false readiness.
    mismatch_ctx = {**remote_ctx, "mode": "design"}
    mismatch_res = get_provider("qwen3").probe(mismatch_ctx)
    assert mismatch_res["ready"] is False
    assert mismatch_res["code"] == "model_mismatch"

    # Wrong token fails closed without leaking the secret token.
    bad_auth_ctx = {
        "model": "voxcpm2",
        "mode": "default",
        "connection": {
            "deployment": "remote_gpu",
            "base_url": "https://colab-t4.trycloudflare.com",
            "api_key": "wrong-secret-xyz",
            "remote_transport": transport,
        },
    }
    bad_res = get_provider("voxcpm2").probe(bad_auth_ctx)
    assert bad_res["ready"] is False
    assert bad_res["reachable"] is True
    assert bad_res["code"] == "authentication_failed"
    assert "wrong-secret-xyz" not in bad_res["detail"]

    # Environment variable configuration (`ASMR_HELPER_REMOTE_WORKER_URL` + TOKEN) works with empty context!
    _install_mock_httpx_transport(monkeypatch, transport)
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_URL", "https://env-colab.trycloudflare.com")
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", "probe-secret-123")
    vox_env_ready = get_provider("voxcpm2").probe({"model": "voxcpm2", "mode": "design"})
    assert vox_env_ready["ready"] is True
    assert vox_env_ready["remote_worker_url"] == "https://env-colab.trycloudflare.com"


# ---------------------------------------------------------------------------
# 2. End-to-End `qwen3` Remote Reference Clone & Batch Synthesis via `SpeechService.run_requests`
# ---------------------------------------------------------------------------


def test_qwen3_remote_reference_clone_and_builtin_via_speech_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_URL", raising=False)
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", raising=False)

    transport, http_requests, tts_invocations, _ = _build_worker_harness(token="qwen-tunnel-tok")
    _install_mock_httpx_transport(monkeypatch, transport)

    # Create a real reference WAV file for voice cloning and compute its SHA256.
    ref_wav = tmp_path / "voice_ref.wav"
    _make_sine_wav(ref_wav, freq_hz=280.0, duration_sec=1.6, sample_rate=24000)
    ref_wav_size = ref_wav.stat().st_size
    ref_sha256 = hashlib.sha256(ref_wav.read_bytes()).hexdigest()

    service = SpeechService(
        store=SpeechStore(tmp_path / "speech_lab"),
        tasks=TaskService(),
        artifacts=ArtifactService(),
    )
    asset = service.store.create(
        "assets",
        {
            "name": "Clean Whisper Reference",
            "path": str(ref_wav),
            "sha256": ref_sha256,
            "transcript": "こんばんは、ゆっくり休んでくださいね。",
            "confirmed": True,
        },
    )
    conn = service.save_connection(
        {
            "name": "Qwen3 Colab Worker",
            "provider_id": "qwen3",
            "deployment": "local",
            "base_url": "https://qwen-colab.trycloudflare.com",
            "api_key": "qwen-tunnel-tok",
        }
    )
    voice = service.store.create("voices", {"name": "ASMR Whisper Clone", "bindings": []})
    clone_recipe = service.save_recipe(
        {
            "name": "Qwen3 Clone Rule",
            "voice_id": voice["id"],
            "provider_id": "qwen3",
            "model": "qwen3-base",
            "mode": "reference",
            "connection_ref": conn["id"],
            "variant": {"kind": "reference", "value": asset["id"], "style": "whisper"},
            "language": "zh",
            "default_delivery": "whisper",
            "provider_options": {"schema_version": 1, "temperature": 0.75, "top_p": 0.9},
        }
    )

    plan = service.create_plan({"text": "第一句耳语克隆测试。第二句温柔晚安问候。"})
    experiment = service.store.create("experiments", {"name": "Remote Clone Batch", "plan_id": plan["id"]})

    # `snapshot()` probes `/v1/capabilities` without any local `.runtimes` or weights installed!
    snapshot = service.snapshot(clone_recipe["id"])
    requests = service.compile(clone_recipe["id"], plan["id"])
    assert len(requests) == 2

    takes = service.run_requests(
        requests,
        snapshot,
        task_id="task-qwen3-remote",
        experiment_id=experiment["id"],
        plan_id=plan["id"],
    )
    assert len(takes) == 2

    # Both sentences in the batch must have been dispatched in ONE `/v1/tts/batch` HTTP call!
    tts_http_calls = [r for r in http_requests if r.url.path == "/v1/tts/batch"]
    assert len(tts_http_calls) == 1

    fields, files = _extract_multipart_parts(tts_http_calls[0])
    assert "reference_audio" in files
    up_filename, up_bytes = files["reference_audio"]
    assert up_filename == "voice_ref.flac"
    assert up_bytes.startswith(b"fLaC"), "Reference WAV must be transcoded to lossless FLAC before upload"
    assert len(up_bytes) < ref_wav_size * 0.75

    wire_req = fields["request"]
    assert wire_req["provider_id"] == "qwen3"
    assert wire_req["model"] == "qwen3-base"
    assert len(wire_req["items"]) == 2
    assert wire_req["items"][0]["variant_kind"] == "reference"
    assert wire_req["items"][0]["reference_transcript"] == "こんばんは、ゆっくり休んでくださいね。"

    # Verify worker saw decoded reference audio and SpeechService wrote float32 WAV outputs.
    assert len(tts_invocations) == 2
    assert all(inv["has_reference"] is True for inv in tts_invocations)
    for take in takes:
        take_path = Path(take["audio_path"])
        assert take_path.is_file()
        info = sf.info(str(take_path))
        assert info.format == "WAV"
        assert info.subtype == "FLOAT"
        assert info.samplerate == 24000
        samples, _ = sf.read(str(take_path), dtype="float32")
        assert len(samples) > 0 and np.isfinite(samples).all()

    # Local SHA256 tamper check MUST fail BEFORE making any remote HTTP call!
    http_count_before_tamper = len(http_requests)
    ref_wav.write_bytes(b"tampered-audio-bytes")
    with pytest.raises(ProviderError) as tamper_exc:
        service.run_requests(
            requests[:1],
            snapshot,
            task_id="task-tampered",
            experiment_id=experiment["id"],
            plan_id=plan["id"],
        )
    assert tamper_exc.value.code == "asset_changed"
    assert len(http_requests) == http_count_before_tamper

    # Also verify single-cue `qwen3` builtin speaker mode (`Vivian` -> protocol `preset`).
    builtin_recipe = service.save_recipe(
        {
            "name": "Qwen3 Builtin Vivian",
            "voice_id": voice["id"],
            "provider_id": "qwen3",
            "model": "qwen3-custom-voice",
            "mode": "builtin",
            "connection_ref": conn["id"],
            "variant": {"kind": "builtin", "value": "Vivian", "style": "normal"},
            "language": "zh",
            "provider_options": {"schema_version": 1},
        }
    )
    single_plan = service.create_plan({"text": "单句预设音色测试。"})
    single_takes = service.run_requests(
        service.compile(builtin_recipe["id"], single_plan["id"]),
        service.snapshot(builtin_recipe["id"]),
        task_id="task-qwen3-builtin",
        experiment_id=experiment["id"],
        plan_id=single_plan["id"],
    )
    assert len(single_takes) == 1
    assert sf.info(single_takes[0]["audio_path"]).subtype == "FLOAT"
    assert tts_invocations[-1]["item"]["variant_kind"] == "preset"
    assert tts_invocations[-1]["item"]["speaker"] == "Vivian"


# ---------------------------------------------------------------------------
# 3. End-to-End `voxcpm2` Remote Synthesis via `ASMR_HELPER_REMOTE_WORKER_URL`
# ---------------------------------------------------------------------------


def test_voxcpm2_remote_synthesis_via_env_and_speech_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport, http_requests, tts_invocations, _ = _build_worker_harness(token="vox-env-token")
    _install_mock_httpx_transport(monkeypatch, transport)
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_URL", "https://vox-colab.trycloudflare.com")
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", "vox-env-token")

    service = SpeechService(
        store=SpeechStore(tmp_path / "vox_lab"),
        tasks=TaskService(),
        artifacts=ArtifactService(),
    )

    # Build a `voxcpm2` pipeline snapshot without any explicit connection `base_url` or local weights.
    snapshot = service.pipeline_snapshot(
        {
            "provider": "voxcpm2",
            "model": "voxcpm2",
            "options": {
                "language": "zh",
                "speech_source": {
                    "mode": "design",
                    "variant": {"kind": "design", "value": "温柔耳语少女声线", "style": "whisper"},
                    "default_delivery": "whisper",
                    "provider_options": {
                        "schema_version": 1,
                        "cfg_value": 2.4,
                        "inference_timesteps": 12,
                    },
                },
            },
        }
    )

    plan = service.create_plan({"text": "欢迎来到耳语空间。请闭上眼睛放松。"})
    experiment = service.store.create("experiments", {"name": "VoxCPM2 Remote", "plan_id": plan["id"]})
    from src.core.speech.compiler import compile_recipe

    requests = compile_recipe(snapshot["recipe"], plan, snapshot["assets"])
    takes = service.run_requests(
        requests,
        snapshot,
        task_id="task-voxcpm2-remote",
        experiment_id=experiment["id"],
        plan_id=plan["id"],
    )
    assert len(takes) == 2

    tts_http_calls = [r for r in http_requests if r.url.path == "/v1/tts/batch"]
    assert len(tts_http_calls) == 1
    assert len(tts_invocations) == 2
    assert tts_invocations[0]["provider_id"] == "voxcpm2"
    assert tts_invocations[0]["item"]["variant_kind"] == "design"
    assert tts_invocations[0]["item"]["variant_value"] == "温柔耳语少女声线"
    assert tts_invocations[0]["item"]["options"]["cfg_value"] == 2.4
    assert tts_invocations[0]["item"]["options"]["inference_timesteps"] == 12

    for take in takes:
        info = sf.info(take["audio_path"])
        assert info.format == "WAV"
        assert info.subtype == "FLOAT"
        assert info.samplerate == 48000


# ---------------------------------------------------------------------------
# 4. Remote Demucs Separation via `SeparatorEngineService` & Local Fallback Preservation
# ---------------------------------------------------------------------------


def test_remote_demucs_separation_and_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_URL", raising=False)
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", raising=False)

    transport, http_requests, _, sep_invocations = _build_worker_harness(token="sep-token-777")
    _install_mock_httpx_transport(monkeypatch, transport)

    src_wav = tmp_path / "binaural_mix.wav"
    original_stereo = _make_sine_wav(
        src_wav, freq_hz=440.0, duration_sec=1.2, sample_rate=44100, stereo=True
    )
    src_wav_size = src_wav.stat().st_size

    assert SeparatorEngineService is SeparatorEngineRuntime

    # 1) Explicit `provider_options["remote_worker_url"]` delegation (without touching local Demucs!)
    failing_local_registry = MagicMock()
    failing_local_registry.get.side_effect = AssertionError(
        "Local Demucs registry must NOT be invoked when remote_worker_url is set"
    )
    sep_service = SeparatorEngineService(registry=failing_local_registry)

    out_dir_explicit = tmp_path / "stems_explicit"
    stems_map = sep_service.separate(
        input_path=str(src_wav),
        output_dir=str(out_dir_explicit),
        model="htdemucs",
        stems=["vocals", "no_vocals", "other"],
        provider_options={
            "remote_worker_url": "https://sep-colab.trycloudflare.com",
            "remote_worker_token": "sep-token-777",
        },
    )
    assert set(stems_map.keys()) == {"vocals", "no_vocals", "other"}
    for stem_name, scale in (("vocals", 0.75), ("no_vocals", 0.25), ("other", 0.15)):
        stem_path = Path(stems_map[stem_name])
        assert stem_path.is_file()
        assert stem_path.parent == out_dir_explicit
        assert stem_path.suffix == ".wav"
        arr, sr = sf.read(str(stem_path), dtype="float32")
        assert sr == 44100
        assert np.allclose(arr, original_stereo * scale, atol=1e-3)

    # Verify lossless FLAC upload over HTTP
    sep_http_req = http_requests[-1]
    assert sep_http_req.url.path == "/v1/separate"
    _fields, files = _extract_multipart_parts(sep_http_req)
    up_name, up_bytes = files["audio"]
    assert up_name == "binaural_mix.flac"
    assert up_bytes.startswith(b"fLaC")
    assert len(up_bytes) < src_wav_size * 0.70
    assert sep_invocations[-1]["stems"] == ["vocals", "no_vocals", "other"]

    # 2) Environment variable `ASMR_HELPER_REMOTE_WORKER_URL` delegation with default `stems=None` -> `["vocals"]`
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_URL", "https://sep-colab.trycloudflare.com")
    monkeypatch.setenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", "sep-token-777")
    out_dir_env = tmp_path / "stems_env"
    env_stems = sep_service.separate(
        input_path=str(src_wav),
        output_dir=str(out_dir_env),
        model="htdemucs_ft",
    )
    assert list(env_stems.keys()) == ["vocals"]
    assert Path(env_stems["vocals"]).is_file()
    assert sep_invocations[-1]["model"] == "htdemucs_ft"

    # 3) Local Demucs behavior preserved 100% when no remote worker URL is configured
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_URL", raising=False)
    monkeypatch.delenv("ASMR_HELPER_REMOTE_WORKER_TOKEN", raising=False)
    mock_demucs = MagicMock()
    mock_demucs.separate.return_value = {"vocals": str(tmp_path / "local_vocals.wav")}
    local_registry = MagicMock()
    local_registry.get.return_value = mock_demucs

    local_service = SeparatorEngineService(registry=local_registry)
    local_res = local_service.separate(
        input_path=str(src_wav),
        output_dir=str(tmp_path / "local_out"),
        model="htdemucs",
        stems=["vocals"],
    )
    assert local_res == {"vocals": str(tmp_path / "local_vocals.wav")}
    local_registry.get.assert_called_once_with("demucs", model_name="htdemucs")
    mock_demucs.separate.assert_called_once_with(
        str(src_wav), str(tmp_path / "local_out"), stems=["vocals"]
    )
