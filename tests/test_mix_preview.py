"""Preview must sound like the corresponding window of production mixing."""
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from src.app.errors import AppValidationError
from src.app.services.mix_preview import render_mix_preview, resolve_mix_sources
from src.mixer import Mixer


@pytest.mark.parametrize("delay,start,speech_duration", [(0, 4, 24), (1.5, 4, 24), (-1.5, 4, 24),
                                                       (0, 12, 5), (1.5, 6, 5), (-1.5, 12, 5)])
def test_preview_matches_production_window(tmp_path, delay, start, speech_duration):
    sr = 44100
    original = tmp_path / "original.wav"
    speech = tmp_path / "speech.wav"
    mixed = tmp_path / "production.wav"
    t = np.arange(25 * sr) / sr
    sf.write(original, 0.2 * np.sin(2 * np.pi * 220 * t), sr, subtype="FLOAT")
    speech_t = np.arange(speech_duration * sr) / sr
    sf.write(speech, 0.1 * np.sin(2 * np.pi * 330 * speech_t), sr, subtype="FLOAT")
    Mixer(0.7, 0.35, delay * 1000).mix(str(original), str(speech), str(mixed))
    full, rate = sf.read(mixed, always_2d=True)
    audio = render_mix_preview(str(original), str(speech), original_volume=0.7,
                               tts_volume_ratio=0.35, tts_delay=delay, start_seconds=start)
    actual, _ = sf.read(BytesIO(audio), always_2d=True)
    expected = full[int(start * rate):int(start * rate) + len(actual)]
    assert len(actual) <= 15 * rate
    # WAV preview uses PCM16; allow one quantization step and FFmpeg rounding.
    assert np.max(np.abs(actual - expected)) < 0.0001


def test_missing_speech_rejected(tmp_path):
    original = tmp_path / "original.wav"
    original.touch()
    tasks = SimpleNamespace(get_task=lambda _: SimpleNamespace(task_type="pipeline", state="completed", input_asset_id="a"),
                            recovery_store=None)
    artifacts = SimpleNamespace(get_task_artifacts=lambda _: SimpleNamespace(entries=[]))
    inputs = SimpleNamespace(get_asset=lambda _: SimpleNamespace(absolute_path=str(original)))
    with pytest.raises(AppValidationError, match="缺少原音"):
        resolve_mix_sources("task", tasks, artifacts, inputs)


def test_http_missing_artifact_and_invalid_parameters(tmp_path):
    from fastapi.testclient import TestClient
    from src.api.http.app import create_app
    from src.api.http.dependencies import task_service, artifact_service, input_catalog_service

    original = tmp_path / "original.wav"
    original.touch()
    tasks = SimpleNamespace(get_task=lambda _: SimpleNamespace(task_type="pipeline", state="completed", input_asset_id="a"),
                            recovery_store=None)
    app = create_app()
    app.dependency_overrides[task_service] = lambda: tasks
    app.dependency_overrides[artifact_service] = lambda: SimpleNamespace(get_task_artifacts=lambda _: SimpleNamespace(entries=[]))
    app.dependency_overrides[input_catalog_service] = lambda: SimpleNamespace(get_asset=lambda _: SimpleNamespace(absolute_path=str(original)))
    client = TestClient(app)
    response = client.post("/api/v1/tasks/known/mix-preview", json={})
    assert response.status_code == 400
    assert "缺少原音" in response.text
    assert client.post("/api/v1/tasks/known/mix-preview", json={"tts_delay": 3}).status_code == 422


def test_resolves_separated_source(tmp_path):
    paths = [tmp_path / name for name in ("original.wav", "vocals.wav", "tts.wav")]
    for path in paths:
        path.touch()
    task = SimpleNamespace(task_type="pipeline", state="completed", input_asset_id="a")
    tasks = SimpleNamespace(get_task=lambda _: task, recovery_store=None)
    entries = [SimpleNamespace(artifact_type=kind, path=str(path))
               for kind, path in zip(("audio.vocals", "audio.tts"), paths[1:])]
    artifacts = SimpleNamespace(get_task_artifacts=lambda _: SimpleNamespace(entries=entries))
    inputs = SimpleNamespace(get_asset=lambda _: SimpleNamespace(absolute_path=str(paths[0])))
    assert resolve_mix_sources("task", tasks, artifacts, inputs) == tuple(map(str, paths))
