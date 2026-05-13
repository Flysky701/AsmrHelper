from click.testing import CliRunner


def test_subtitle_service_round_trip_preserves_timestamp_entries():
    from src.app.services.subtitle_service import SubtitleService

    entries = [
        {"start": 0.0, "end": 1.25, "text": "hello"},
        {"start": 1.25, "end": 2.5, "text": "world"},
    ]

    service = SubtitleService()
    document = service.from_timestamp_entries(entries)

    assert document.segments[0].text == "hello"
    assert document.segments[1].end == 2.5

    restored = service.to_timestamp_entries(document)
    assert restored == entries


def test_pipeline_service_maps_request_and_result(monkeypatch):
    from src.app.dto import PipelineRequest
    from src.app.services.pipeline_service import PipelineService

    captured = {}

    class DummyPipeline:
        def __init__(self, config):
            captured["config"] = config

        def run(self, preset=None, progress_callback=None):
            captured["preset"] = preset
            return {
                "input": "demo.wav",
                "mix_path": "out/demo_mix.wav",
                "exported_subtitle": "out/demo_subtitle.srt",
                "steps": {"asr": {"segments": 2}},
                "total_duration": 3.5,
            }

    monkeypatch.setattr("src.app.services.pipeline_service.Pipeline", DummyPipeline)

    request = PipelineRequest(
        input_path="demo.wav",
        output_dir="out",
        source_lang="ja",
        target_lang="zh",
        tts_engine="edge",
        tts_voice="zh-CN-XiaoxiaoNeural",
        vocal_model="htdemucs",
        asr_model="base",
        translate_provider="deepseek",
        tts_delay=0.0,
        skip_existing=False,
    )

    service = PipelineService()
    result = service.run_audio_pipeline(request)

    assert captured["config"].input_path == "demo.wav"
    assert captured["config"].translate_provider == "deepseek"
    assert captured["preset"] == "asmr_bilingual"
    assert result.success is True
    assert result.mix_path == "out/demo_mix.wav"
    assert result.exported_subtitle == "out/demo_subtitle.srt"


def test_pipeline_service_wraps_execution_errors(monkeypatch):
    import pytest

    from src.app.dto import PipelineRequest
    from src.app.errors import AppExecutionError
    from src.app.services.pipeline_service import PipelineService

    class DummyPipeline:
        def __init__(self, config):
            pass

        def run(self, preset=None, progress_callback=None):
            raise RuntimeError("boom")

    monkeypatch.setattr("src.app.services.pipeline_service.Pipeline", DummyPipeline)

    request = PipelineRequest(
        input_path="demo.wav",
        output_dir="out",
        source_lang="ja",
        target_lang="zh",
        tts_engine="edge",
        tts_voice="zh-CN-XiaoxiaoNeural",
        vocal_model="htdemucs",
        asr_model="base",
        translate_provider="deepseek",
        tts_delay=0.0,
        skip_existing=False,
    )

    service = PipelineService()

    with pytest.raises(AppExecutionError):
        service.run_audio_pipeline(request)


def test_cli_pipeline_run_uses_pipeline_service(monkeypatch):
    from src.app.dto import PipelineResult
    from src.cli import cli

    captured = {}

    class DummyPipelineService:
        def run_audio_pipeline(self, request):
            captured["request"] = request
            return PipelineResult(
                success=True,
                input_path=request.input_path,
                mix_path="out/final_mix.wav",
                exported_subtitle="out/final_subtitle.srt",
                steps={"asr": {"segments": 2}},
                total_duration=1.0,
                error_message=None,
            )

    monkeypatch.setattr("src.cli.get_pipeline_service", lambda: DummyPipelineService())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "pipeline",
            "run",
            "--input",
            "demo.wav",
            "--output",
            "out",
            "--source-lang",
            "ja",
            "--target-lang",
            "zh",
            "--tts-engine",
            "edge",
            "--tts-voice",
            "zh-CN-XiaoxiaoNeural",
            "--vocal-model",
            "htdemucs",
            "--asr-model",
            "base",
            "--translate-provider",
            "deepseek",
        ],
    )

    assert result.exit_code == 0
    assert captured["request"].input_path == "demo.wav"
    assert captured["request"].output_dir == "out"
    assert "out/final_mix.wav" in result.output


def test_cli_pipeline_presets_still_lists_available_presets():
    from src.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["pipeline", "presets"])

    assert result.exit_code == 0
    assert "asmr_bilingual" in result.output
