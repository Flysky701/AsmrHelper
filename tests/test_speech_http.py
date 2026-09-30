"""VoiceLab HTTP → dispatcher → native protocol → durable take integration."""
from io import BytesIO
import json
import time

from fastapi.testclient import TestClient
import httpx
import numpy as np
import pytest
import soundfile as sf

from src.api.http.app import create_app
from src.api.http import dependencies
from src.app.services.speech_service import SpeechService, get_speech_service
from src.app.services.task_service import TaskService
from src.app.services.artifact_service import ArtifactService
from src.core.speech.store import SpeechStore


@pytest.fixture
def speech_http(tmp_path):
    service = SpeechService(store=SpeechStore(tmp_path / "speech"), tasks=TaskService(), artifacts=ArtifactService())
    app = create_app()
    app.dependency_overrides[get_speech_service] = lambda: service
    app.dependency_overrides[dependencies.task_service] = lambda: service.tasks
    app.dependency_overrides[dependencies.task_dispatcher] = lambda: service.dispatcher
    app.dependency_overrides[dependencies.artifact_service] = lambda: service.artifacts
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, service
    app.dependency_overrides.clear()


def post(client, path, body, status=200):
    response = client.post("/api/v1/speech" + path, json=body)
    assert response.status_code == status, response.text
    return response.json()


def test_experiment_cannot_override_task_media_root(speech_http, tmp_path):
    client, service = speech_http
    plan = post(client, "/plans", {"text": "测试。"})
    post(client, "/experiments", {"name": "Test", "plan_id": plan["id"],
        "kind": "formal", "media_root": str(tmp_path / "unexpected")}, status=422)
    assert service.store.list("experiments") == []
    assert not (tmp_path / "unexpected").exists()


def setup_fish(client):
    connection = post(client, "/connections", {"name": "Fish test", "provider_id": "fish_audio", "deployment": "cloud",
        "base_url": "https://fish.invalid/v1", "api_key": "never-expose-this-key"})
    voice = post(client, "/voices", {"name": "测试声音", "bindings": []})
    recipe = post(client, "/recipes", {"name": "测试配方", "voice_id": voice["id"], "provider_id": "fish_audio",
        "model": "s2-pro", "mode": "hosted", "connection_ref": connection["id"],
        "variant": {"kind": "hosted", "value": "voice-native-id", "style": "normal"},
        "language": "zh", "provider_options": {"schema_version": 1}})
    plan = post(client, "/plans", {"text": "第一句。第二句。"})
    experiment = post(client, "/experiments", {"name": "真实任务测试", "plan_id": plan["id"]})
    return connection, voice, recipe, plan, experiment


def wait_task(client, task_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get("/api/v1/tasks/" + task_id)
        assert response.status_code == 200, response.text
        state = response.json()
        if state["state"] in {"completed", "failed", "cancelled"}:
            return state
        time.sleep(.02)
    pytest.fail("speech dispatcher did not finish")


def wav():
    buffer = BytesIO()
    sf.write(buffer, np.sin(np.arange(2400) / 20).astype("float32") * .1, 24000, format="WAV")
    return buffer.getvalue()


def test_reference_analysis_task_returns_progress_and_durable_result(speech_http, monkeypatch, tmp_path):
    import threading
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    client, service = speech_http
    source = tmp_path / "reference.wav"
    source.write_bytes(wav())
    entered, release = threading.Event(), threading.Event()

    def analyze(_self, **kwargs):
        assert kwargs["require_text"] is True
        kwargs["progress_callback"]("识别并整理台词", 30)
        entered.set()
        assert release.wait(5)
        return {"segments": [{"start": 0, "end": .1, "text": ""}], "mode": "asr"}

    monkeypatch.setattr(AudioPreprocessor, "analyze_segments", analyze)
    task = post(client, "/references/analyze-tasks", {"path": str(source)}, status=202)
    try:
        assert entered.wait(5)
        running = client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()
        assert running["status"]["state"] == "running"
        assert running["status"]["progress"] == .3
        assert running["status"]["message"] == "识别并整理台词"
        assert running["result"] is None
    finally:
        release.set()
    assert wait_task(client, task["task_id"])["state"] == "completed"
    result = client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()["result"]
    assert result["mode"] == "asr"
    assert len(result["segments"]) == 1
    assert (service.store.root / "_analyses" / (task["task_id"] + ".json")).exists()


def test_reference_analysis_failure_is_visible_and_asr_is_opt_in(speech_http, monkeypatch, tmp_path):
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    client, _service = speech_http
    source = tmp_path / "reference.wav"
    source.write_bytes(wav())

    def analyze(_self, **kwargs):
        assert kwargs["require_text"] is True
        raise RuntimeError("识别模型尚未安装")

    monkeypatch.setattr(AudioPreprocessor, "analyze_segments", analyze)
    task = post(client, "/references/analyze-tasks", {"path": str(source), "require_text": True}, status=202)
    assert wait_task(client, task["task_id"])["state"] == "failed"
    result = client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()
    assert "识别模型尚未安装" in str(result["status"]["error"])
    assert result["result"] is None


def test_reference_analysis_can_cancel_without_publishing_result(speech_http, monkeypatch, tmp_path):
    import threading
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    client, _service = speech_http
    source = tmp_path / "reference.wav"
    source.write_bytes(wav())
    entered, release = threading.Event(), threading.Event()

    def analyze(_self, **kwargs):
        entered.set()
        assert release.wait(5)
        kwargs["progress_callback"]("候选已生成", 100)
        return {"segments": []}

    monkeypatch.setattr(AudioPreprocessor, "analyze_segments", analyze)
    task = post(client, "/references/analyze-tasks", {"path": str(source)}, status=202)
    try:
        assert entered.wait(5)
        response = client.post("/api/v1/tasks/" + task["task_id"] + "/cancel")
        assert response.status_code == 200, response.text
    finally:
        release.set()
    assert wait_task(client, task["task_id"])["state"] == "cancelled"
    assert client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()["result"] is None


def test_reference_analysis_rejects_missing_input(speech_http, tmp_path):
    client, _service = speech_http
    post(client, "/references/analyze-tasks", {"path": str(tmp_path / "missing.wav")}, status=422)


def test_reference_analysis_silence_reports_no_candidates_without_loading_asr(speech_http, monkeypatch, tmp_path):
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    client, _service = speech_http
    source = tmp_path / "silence.wav"
    sf.write(source, np.zeros(64000, dtype="float32"), 16000)

    def forbidden_asr(*args, **kwargs):
        pytest.fail("关闭 ASR 时不应加载模型")

    monkeypatch.setattr(AudioPreprocessor, "_run_asr", forbidden_asr)
    task = post(client, "/references/analyze-tasks", {"path": str(source), "require_text": False}, status=202)
    status = wait_task(client, task["task_id"])
    assert status["state"] == "completed"
    result = client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()["result"]
    assert result["segments"] == []
    assert result["mode"] == "manual"
    assert result["transcript_source"] == "none"


@pytest.mark.parametrize("sidecar_suffix", [".vtt", ".wav.vtt", ".srt", ".wav.srt"])
@pytest.mark.parametrize("language,text,end,expected_source,verified", [
    ("en", "Hello this is the original recording.", "00:00:03.500", "subtitle", True),
    ("ja", "これは録音の原文です。よろしくお願いします。", "00:00:03.500", "subtitle", True),
    ("auto", "Hello this is the original recording.", "00:00:03.500", "asr", None),
    ("ja", "这是翻译后的中文字幕。", "00:00:03.500", "asr", None),
    ("en", "Hello this is the original recording.", "00:00:09.000", "asr", None),
])
def test_reference_analysis_reuses_valid_sidecar_from_staged_audio(
    speech_http, monkeypatch, tmp_path, language, text, end, expected_source, verified, sidecar_suffix,
):
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    client, _service = speech_http
    source = tmp_path / "recording.wav"
    sf.write(source, np.zeros(64000, dtype="float32"), 16000)
    content = f"WEBVTT\n\n00:00:00.100 --> {end}\n{text}\n" if sidecar_suffix.endswith(".vtt") else f"1\n00:00:00,100 --> {end.replace('.', ',')}\n{text}\n"
    source.with_suffix(sidecar_suffix).write_text(content, encoding="utf-8")
    staged = post(client, "/references/inspect", {"path": str(source)})
    assert staged["companion_subtitles"] == [{"name": "recording" + sidecar_suffix, "format": sidecar_suffix.rsplit(".", 1)[1]}]

    def analyze(_self, **kwargs):
        assert bool(kwargs["subtitle_path"]) == (expected_source == "subtitle")
        assert kwargs["require_text"] is True
        return {"segments": [], "mode": "matched" if kwargs["subtitle_path"] else "asr"}

    monkeypatch.setattr(AudioPreprocessor, "analyze_segments", analyze)
    task = post(client, "/references/analyze-tasks", {"path": staged["path"], "language": language}, status=202)
    assert wait_task(client, task["task_id"])["state"] == "completed"
    result = client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()["result"]
    assert result["transcript_source"] == expected_source
    assert result["warnings"]
    if verified is not None:
        assert result["subtitle"]["language_verified"] is verified


def test_processed_reference_does_not_reuse_parent_subtitle_timeline(speech_http, tmp_path):
    client, _service = speech_http
    source = tmp_path / "recording.wav"
    sf.write(source, np.zeros(64000, dtype="float32"), 16000)
    source.with_suffix(".srt").write_text("1\n00:00:00,000 --> 00:00:03,500\nHello original recording.\n", encoding="utf-8")
    staged = post(client, "/references/inspect", {"path": str(source)})
    cropped = post(client, "/references/preview", {"path": staged["path"], "start": 1, "end": 2})
    again = post(client, "/references/inspect", {"path": cropped["path"]})
    assert again["companion_subtitles"] == []
    assert again["companion_source_path"] is None


@pytest.mark.parametrize("language,text", [
    ("ja", "これは原文です。\n这是中文字幕翻译。"),
    ("ja", "这是中文字幕翻译，只有一个の字。\n另外一句也是中文字幕。"),
    ("ja", "这是中文字幕翻译，只有一个の字。"),
    ("auto", "Hello from this recording."),
    ("ja", "This is an English translation."),
])
def test_uncertain_or_translated_subtitles_do_not_block_requested_asr(speech_http, monkeypatch, tmp_path, language, text):
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    client, _service = speech_http
    source = tmp_path / "recording.wav"
    sf.write(source, np.zeros(64000, dtype="float32"), 16000)
    source.with_suffix(".vtt").write_text(f"WEBVTT\n\n00:00:00.000 --> 00:00:03.500\n{text}\n", encoding="utf-8")

    def analyze(_self, **kwargs):
        assert kwargs["subtitle_path"] is None
        assert kwargs["require_text"] is True
        assert kwargs["audio_language"] == language
        return {"segments": [{"start": 0, "end": 3, "text": "ASR original"}], "mode": "asr"}

    monkeypatch.setattr(AudioPreprocessor, "analyze_segments", analyze)
    task = post(client, "/references/analyze-tasks", {"path": str(source), "language": language, "require_text": True}, status=202)
    assert wait_task(client, task["task_id"])["state"] == "completed"
    result = client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()["result"]
    assert result["transcript_source"] == "asr"
    assert result["subtitle"] is None
    assert result["warnings"]


def test_selection_asr_only_reads_crop_ignores_subtitles_and_requires_confirmation(speech_http, monkeypatch, tmp_path):
    from src.core.engines.asr.service import AsrEngineRuntime
    from types import SimpleNamespace
    client, service = speech_http
    source = tmp_path / "recording.wav"
    samples = np.concatenate([np.zeros(16000), np.full(16000, .25), np.zeros(16000)]).astype("float32")
    sf.write(source, samples, 16000)
    source.with_suffix(".vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nwrong translation\n", encoding="utf-8")
    calls = []

    def transcribe(_self, **kwargs):
        crop, rate = sf.read(kwargs["input_path"])
        assert rate == 16000 and len(crop) == 16000
        assert np.allclose(crop, .25)
        assert kwargs["profile"]["common_options"]["language"] == "ja"
        calls.append(kwargs["input_path"])
        return SimpleNamespace(segments=[SimpleNamespace(start=0, end=1, text="本当の原文です。")])

    monkeypatch.setattr(AsrEngineRuntime, "transcribe_file", transcribe)
    task = post(client, "/references/transcribe-tasks", {"path": str(source), "start": 1, "end": 2, "language": "ja"}, status=202)
    assert wait_task(client, task["task_id"])["state"] == "completed"
    result = client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()["result"]
    assert result["transcript"] == "本当の原文です。"
    assert result["confirmed"] is False
    assert result["start"] == 1 and result["end"] == 2
    assert result["segments"][0]["start"] == 1 and result["segments"][0]["end"] == 2
    assert len(calls) == 1
    assert service.store.list("assets") == []


@pytest.mark.parametrize("start,end", [(1, 1), (-1, 1), (2, 1)])
def test_selection_asr_rejects_invalid_interval(speech_http, tmp_path, start, end):
    client, _service = speech_http
    source = tmp_path / "recording.wav"
    source.write_bytes(wav())
    post(client, "/references/transcribe-tasks", {"path": str(source), "start": start, "end": end}, status=422)


def test_selection_asr_cancellation_discards_late_result(speech_http, monkeypatch, tmp_path):
    import threading
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    client, service = speech_http
    source = tmp_path / "recording.wav"
    source.write_bytes(wav())
    entered, release = threading.Event(), threading.Event()

    def transcribe(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return [{"start": 0, "end": .1, "text": "late"}]

    monkeypatch.setattr(AudioPreprocessor, "_run_asr", transcribe)
    task = post(client, "/references/transcribe-tasks", {"path": str(source), "start": 0, "end": .1}, status=202)
    try:
        assert entered.wait(5)
        assert client.post("/api/v1/tasks/" + task["task_id"] + "/cancel").status_code == 200
    finally:
        release.set()
    assert wait_task(client, task["task_id"])["state"] == "cancelled"
    assert not (service.store.root / "_analyses" / (task["task_id"] + ".json")).exists()


def test_selection_asr_bounds_and_engine_failure_are_visible(speech_http, monkeypatch, tmp_path):
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    client, _service = speech_http
    source = tmp_path / "recording.wav"
    source.write_bytes(wav())
    calls = []

    def transcribe(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("ASR 模型未安装")

    monkeypatch.setattr(AudioPreprocessor, "_run_asr", transcribe)
    task = post(client, "/references/transcribe-tasks", {"path": str(source), "start": 0, "end": 1}, status=202)
    assert wait_task(client, task["task_id"])["state"] == "failed"
    assert not calls
    task = post(client, "/references/transcribe-tasks", {"path": str(source), "start": 0, "end": .1}, status=202)
    status = wait_task(client, task["task_id"])
    assert status["state"] == "failed" and "ASR 模型未安装" in str(status["error"])
    assert len(calls) == 1
    assert client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()["result"] is None


@pytest.mark.parametrize("text,format,expected", [
    ("WEBVTT\n\n00:00:00.000 --> 00:00:03.500\nHello from the recording.\n", "vtt", "subtitle"),
    ("1\n00:00:00,000 --> 00:00:03,500\nHello from the recording.\n", "srt", "subtitle"),
    ("WEBVTT\n\n00:00:00.000 --> 00:00:09.000\nOut of bounds.\n", "vtt", "asr"),
    ("not a subtitle", "srt", "asr"),
])
def test_manual_subtitle_is_snapshotted_and_reused_without_asr(speech_http, monkeypatch, tmp_path, text, format, expected):
    from src.core.tts.audio_preprocessor import AudioPreprocessor
    from pathlib import Path
    client, service = speech_http
    source = tmp_path / "browser.wav"
    sf.write(source, np.zeros(64000, dtype="float32"), 16000)

    def analyze(_self, **kwargs):
        if expected == "subtitle":
            assert Path(kwargs["subtitle_path"]).read_text(encoding="utf-8") == text
        else:
            assert kwargs["subtitle_path"] is None
            assert kwargs["require_text"] is True
        return {"segments": [], "mode": "matched" if expected == "subtitle" else "asr"}

    monkeypatch.setattr(AudioPreprocessor, "analyze_segments", analyze)
    task = post(client, "/references/analyze-tasks", {
        "path": str(source), "subtitle_text": text, "subtitle_format": format, "language": "en",
    }, status=202)
    assert wait_task(client, task["task_id"])["state"] == "completed"
    spec = service.tasks.get_task_spec(task["task_id"])
    assert spec.execution_profile["reference_analysis"]["subtitle_text"] == text
    result = client.get("/api/v1/speech/references/analyze-tasks/" + task["task_id"]).json()["result"]
    assert result["transcript_source"] == expected
    assert result["warnings"]
    if expected == "subtitle":
        assert result["subtitle"]["name"] == "手动加载字幕"


@pytest.mark.parametrize("extra", [
    {"subtitle_text": []}, {"subtitle_format": "../vtt"}, {"subtitle_text": "x" * (5 * 1024 * 1024 + 1)},
])
def test_manual_subtitle_rejects_invalid_transport(speech_http, tmp_path, extra):
    client, _service = speech_http
    source = tmp_path / "browser.wav"
    source.write_bytes(wav())
    post(client, "/references/analyze-tasks", {"path": str(source), **extra}, status=422)


def test_browser_reference_upload_can_be_cropped_and_played(speech_http):
    client, service = speech_http
    response = client.post("/api/v1/speech/references/upload", params={"filename": "参考.wav"},
        content=wav(), headers={"content-type": "application/octet-stream"})
    assert response.status_code == 200, response.text
    inspection = response.json()
    assert inspection["duration"] == pytest.approx(.1)
    assert not list((service.store.root / "_uploads").iterdir())
    asset = post(client, "/references", {"path": inspection["path"], "start": 0, "end": .08,
        "transcript": "测试", "language": "zh", "confirmed": True})
    audio = client.get(f'/api/v1/speech/references/{asset["id"]}/audio')
    samples, rate = sf.read(BytesIO(audio.content))
    assert len(samples) == int(rate * .08)


def test_browser_reference_upload_rejects_empty_and_oversize(speech_http, monkeypatch):
    client, service = speech_http
    assert client.post("/api/v1/speech/references/upload?filename=empty.wav", content=b"").status_code == 422
    assert client.post("/api/v1/speech/references/upload?filename=bad.exe", content=b"bad").status_code == 422
    monkeypatch.setattr("src.api.http.routes.speech.MAX_REFERENCE_UPLOAD", 3)
    assert client.post("/api/v1/speech/references/upload?filename=large.wav", content=b"1234").status_code == 413
    # Missing Content-Length: enforce the limit while streaming too.
    assert client.post("/api/v1/speech/references/upload?filename=large.wav", content=iter([b"12", b"34"])).status_code == 413
    assert not list((service.store.root / "_uploads").iterdir())


def test_reference_metadata_patch_is_allowed_from_desktop_origin(speech_http):
    client, _ = speech_http
    response = client.options("/api/v1/speech/references/test", headers={
        "origin": "http://tauri.localhost", "access-control-request-method": "PATCH",
        "access-control-request-headers": "content-type",
    })
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_reference_library_preview_search_archive_and_subtitles(speech_http):
    client, service = speech_http
    uploaded = client.post("/api/v1/speech/references/upload?filename=sample.wav", content=wav()).json()
    body = {"path": uploaded["path"], "start": 0, "end": .08, "name": "雨声", "notes": "素材备注", "gain_db": -3, "fade_in": .01, "fade_out": .01}
    preview = post(client, "/references/preview", body)
    assert service.store.list("assets") == []
    saved = post(client, "/references", body)
    assert saved["sha256"] == preview["sha256"] and saved["confirmed"] is False
    assert client.get(f'/api/v1/speech/references/{preview["id"]}/audio').status_code == 200
    assert client.get("/api/v1/speech/references?query=备注").json()["assets"][0]["id"] == saved["id"]
    changed = client.patch(f'/api/v1/speech/references/{saved["id"]}', json={"name": "新名"})
    assert changed.status_code == 200 and changed.json()["sha256"] == saved["sha256"]
    assert client.delete(f'/api/v1/speech/references/{saved["id"]}').status_code == 200
    assert client.get("/api/v1/speech/references").json()["assets"] == []
    assert client.get(f'/api/v1/speech/references/{saved["id"]}/audio').status_code == 200
    cues = post(client, "/references/subtitles", {"format": "vtt", "text": "WEBVTT\n\n00:00.100 --> 00:00.800\n测试\n"})
    assert cues["segments"] == [{"start": .1, "end": .8, "text": "测试"}]


def test_rule_archive_restore_http_preserves_original_records(speech_http):
    client, service = speech_http
    _, _, first, _, _ = setup_fish(client)
    second = service.store.update("recipes", first["id"], {"name": "最新版本"})
    base = "/api/v1/speech/rules"
    assert client.delete(f'{base}/{second["id"]}').status_code == 200
    assert client.get(base).json()["recipes"] == []
    assert client.get(base + "?include_archived=true").json()["recipes"] == [{**second, "archived": True}]
    assert client.patch(f'{base}/{first["id"]}', json={"archived": "false"}).status_code == 422
    response = client.patch(f'{base}/{first["id"]}', json={"archived": False})
    assert response.status_code == 200 and response.json()["archived"] is False
    assert client.get(base).json()["recipes"] == [second]
    assert service.store.get("recipes", first["id"]) == first
    assert service.store.get("recipes", second["id"]) == second


def fake_remote(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))


def test_fish_http_task_candidates_selection_and_partial_regeneration(speech_http, monkeypatch):
    client, service = speech_http
    calls = []
    def handler(request):
        assert str(request.url) == "https://fish.invalid/v1/tts"
        assert request.headers["model"] == "s2-pro"
        assert request.headers["authorization"] == "Bearer never-expose-this-key"
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=wav(), headers={"x-request-id": "fake-result"})
    fake_remote(monkeypatch, handler)
    _, _, recipe, plan, experiment = setup_fish(client)
    task = post(client, f"/experiments/{experiment['id']}/generate", {"recipe_id": recipe["id"]}, status=202)
    result = wait_task(client, task["task_id"])
    assert result["state"] == "completed", result
    takes = client.get(f"/api/v1/speech/experiments/{experiment['id']}").json()["takes"]
    assert len(takes) == 2 and len(calls) == 2
    assert [call["text"] for call in calls] == ["第一句。", "第二句。"]
    for take in takes:
        audio = client.get(f"/api/v1/speech/takes/{take['id']}/audio")
        assert audio.status_code == 200 and sf.info(BytesIO(audio.content)).samplerate == 24000
        post(client, "/selections", {"experiment_id": experiment["id"], "segment_id": take["segment_id"], "take_id": take["id"]})
    first = post(client, "/assemblies", {"experiment_id": experiment["id"]})
    rendered = client.get(f"/api/v1/speech/assemblies/{first['id']}/audio")
    assert rendered.status_code == 200 and sf.info(BytesIO(rendered.content)).frames > 0
    task2 = post(client, f"/experiments/{experiment['id']}/generate", {"recipe_id": recipe["id"], "segment_id": takes[0]["segment_id"]}, status=202)
    assert wait_task(client, task2["task_id"])["state"] == "completed"
    new_takes = service.experiment(experiment["id"])["takes"]
    replacement = next(t for t in new_takes if t["task_id"] == task2["task_id"])
    post(client, "/selections", {"experiment_id": experiment["id"], "segment_id": replacement["segment_id"], "take_id": replacement["id"]})
    second = post(client, "/assemblies", {"experiment_id": experiment["id"]})
    assert first["processing"][1]["take_id"] == second["processing"][1]["take_id"]
    assert first["processing"][0]["take_id"] != second["processing"][0]["take_id"]
    assert len(calls) == 3 and len(new_takes) == 3
    assert "never-expose-this-key" not in client.get("/api/v1/speech/library").text
    assert "never-expose-this-key" not in json.dumps(service.tasks.get_task_spec(task["task_id"]).execution_profile)


def test_remote_result_unknown_is_structured_and_generic_retry_blocked(speech_http, monkeypatch):
    client, service = speech_http
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("never-expose-this-key")
    fake_remote(monkeypatch, handler)
    _, _, recipe, _, experiment = setup_fish(client)
    task = post(client, f"/experiments/{experiment['id']}/generate", {"recipe_id": recipe["id"]}, status=202)
    result = wait_task(client, task["task_id"])
    assert result["state"] == "failed" and result["error"]["result_unknown"] is True
    assert result["error"]["retryable"] is False
    assert "never-expose-this-key" not in json.dumps(result)
    retry = client.post(f"/api/v1/tasks/{task['task_id']}/retry")
    assert retry.status_code in {400, 409, 422}, retry.text
    assert len(calls) == 1 and service.store.list("takes") == []


@pytest.mark.parametrize("path", ["/compile", "/plan-performance", "/references", "/references/inspect", "/experiments", "/workbench-draft"])
def test_missing_http_fields_are_validation_errors(speech_http, path):
    client, _ = speech_http
    response = client.post("/api/v1/speech" + path, json={})
    assert response.status_code == 422, response.text


def test_recipe_requires_existing_voice(speech_http):
    client, _ = speech_http
    _, _, recipe, _, _ = setup_fish(client)
    recipe.pop("id")
    recipe["voice_id"] = "nonexistent-voice"
    response = client.post("/api/v1/speech/recipes", json=recipe)
    assert response.status_code == 422, response.text


def test_formal_fish_single_sentence_regeneration_preserves_other_audio(speech_http, monkeypatch, tmp_path):
    client, service = speech_http
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=wav())
    fake_remote(monkeypatch, handler)
    _, _, recipe, _, _ = setup_fish(client)
    first = service.synthesize_timeline(service.snapshot(recipe["id"]), [
        {"text": "第一句。", "start_time": .2, "end_time": .5},
        {"text": "第二句。", "start_time": .8, "end_time": 1.1},
    ], tmp_path / "formal.wav", "formal-parent", reference_duration=1.5)
    experiment = next(e for e in service.store.list("experiments") if e.get("kind") == "formal")
    task = post(client, f"/experiments/{experiment['id']}/generate", {"recipe_id": recipe["id"], "segment_id": "sentence-1"}, status=202)
    assert wait_task(client, task["task_id"])["state"] == "completed"
    take = next(t for t in service.experiment(experiment["id"])["takes"] if t["task_id"] == task["task_id"])
    post(client, "/selections", {"experiment_id": experiment["id"], "segment_id": "sentence-1", "take_id": take["id"]})
    second = post(client, "/assemblies", {"experiment_id": experiment["id"]})
    assert len(calls) == 3
    assert first["processing"][1]["take_id"] == second["processing"][1]["take_id"]
    assert first["processing"][0]["take_id"] != second["processing"][0]["take_id"]
    assert second["duration"] == 1.5


def test_recipe_rejects_binding_provider_mismatch(speech_http):
    client, _ = speech_http
    _, _, recipe, _, _ = setup_fish(client)
    voice = post(client, "/voices", {"name": "Edge only", "bindings": [{"id": "edge", "provider_id": "edge", "variants": []}]})
    recipe.pop("id")
    recipe["voice_id"] = voice["id"]
    response = client.post("/api/v1/speech/recipes", json=recipe)
    assert response.status_code == 422, response.text
