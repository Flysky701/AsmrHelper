"""Unit tests for PipelineExecutor — the new pipeline execution path.

Tests each stage with mocked engine runtimes to verify:
- Stage dispatch logic
- Per-stage error handling
- Progress callback invocation
- Result normalization
- Skip-existing logic
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.models import (
    MixConfig,
    PipelineExecutionPlan,
    PipelineMode,
    StageBinding,
    StageKind,
    SubtitleConfig,
)


def _make_plan(
    tmp_path: Path,
    *,
    separation: bool = True,
    asr: bool = True,
    translation: bool = True,
    tts: bool = True,
    mix: bool = True,
) -> PipelineExecutionPlan:
    """Create a minimal execution plan for testing."""
    return PipelineExecutionPlan(
        task_id="test-task-1",
        input_path=str(tmp_path / "input.wav"),
        output_dir=str(tmp_path / "output"),
        source_lang="ja",
        target_lang="zh",
        source_label="日文",
        target_label="中文",
        mode=PipelineMode.FULL,
        separation=StageBinding(kind=StageKind.SEPARATION, provider="builtin", model="htdemucs", enabled=separation),
        asr=StageBinding(kind=StageKind.ASR, provider="faster_whisper", model="base", enabled=asr),
        translation=StageBinding(kind=StageKind.TRANSLATION, provider="deepseek", model="default", enabled=translation),
        tts=StageBinding(kind=StageKind.TTS, provider="edge", model="default", enabled=tts,
                         common_options={"voice": "zh-CN-XiaoxiaoNeural", "speed": 1.0},
                         provider_options={}),
        mix=MixConfig(enabled=mix, original_volume=0.85, tts_volume_ratio=0.5, tts_delay_ms=0),
        subtitle=SubtitleConfig(export_format="srt"),
    )


@pytest.fixture
def mock_separator():
    mock = MagicMock()
    mock.separate.return_value = {"vocals": "/tmp/vocal.wav"}
    return mock


@pytest.fixture
def mock_asr():
    mock = MagicMock()
    doc = MagicMock()
    doc.segments = [
        MagicMock(start=0.0, end=1.5, text="こんにちは"),
        MagicMock(start=1.5, end=3.0, text="世界"),
    ]
    mock.transcribe_file.return_value = doc
    return mock


@pytest.fixture
def mock_llm():
    mock = MagicMock()
    mock.translate_texts.return_value = ["你好", "世界"]
    return mock


@pytest.fixture
def mock_tts():
    mock = MagicMock()
    mock.synthesize_segments.return_value = ("/tmp/tts_output.wav", MagicMock())
    return mock


@pytest.fixture
def mock_mixer_factory():
    def factory(original_volume, tts_volume_ratio, tts_delay_ms):
        mixer = MagicMock()
        mixer.mix.return_value = "/tmp/mix.wav"
        return mixer
    return factory


class TestPipelineExecutorStages:
    """Test individual stage execution."""

    def test_separation_stage_calls_runtime(self, tmp_path, mock_separator):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, asr=False, translation=False, tts=False, mix=False)

        executor = PipelineExecutor(separator=mock_separator)
        results = executor.execute(plan)

        mock_separator.separate.assert_called_once()
        call_kwargs = mock_separator.separate.call_args.kwargs
        assert call_kwargs["model"] == "htdemucs"
        assert call_kwargs["stems"] == ["vocals"]
        assert "vocal_separator" in results["steps"]

    def test_stage_callback_uses_contract_stage_names(self, tmp_path, mock_separator):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, asr=False, translation=False, tts=False, mix=False)
        events: list[tuple[str, float, str]] = []

        PipelineExecutor(separator=mock_separator).execute(
            plan,
            stage_callback=lambda stage, progress, message: events.append(
                (stage, progress, message)
            ),
        )

        assert [stage for stage, _, _ in events] == ["separate", "export"]
        assert events[-1][1] == 1.0

    def test_asr_stage_calls_runtime(self, tmp_path, mock_asr):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, separation=False, translation=False, tts=False, mix=False)

        executor = PipelineExecutor(asr=mock_asr)
        results = executor.execute(plan)

        mock_asr.transcribe_file.assert_called_once()
        assert results["steps"]["asr"]["segments"] == 2

    def test_translation_stage_calls_runtime(self, tmp_path, mock_asr, mock_llm):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, separation=False, tts=False, mix=False)

        executor = PipelineExecutor(asr=mock_asr, llm=mock_llm)
        results = executor.execute(plan)

        mock_llm.translate_texts.assert_called_once()
        assert results["steps"]["translate"]["segments"] == 2

    def test_tts_stage_calls_runtime(self, tmp_path, mock_asr, mock_llm, mock_tts):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, separation=False, mix=False)

        executor = PipelineExecutor(asr=mock_asr, llm=mock_llm, tts=mock_tts)
        results = executor.execute(plan)

        mock_tts.synthesize_segments.assert_called_once()
        assert "tts" in results["steps"]

    def test_mix_stage_calls_mixer(self, tmp_path, mock_asr, mock_llm, mock_tts, mock_mixer_factory):
        (tmp_path / "input.wav").write_bytes(b"audio")
        # Create fake TTS output so mixer doesn't skip
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "tts_output.wav").write_bytes(b"tts_audio")

        plan = _make_plan(tmp_path, separation=False)
        executor = PipelineExecutor(
            asr=mock_asr, llm=mock_llm, tts=mock_tts, mixer_factory=mock_mixer_factory
        )
        results = executor.execute(plan)

        assert "mixer" in results["steps"]


class TestPipelineExecutorErrorHandling:
    """Test per-stage error isolation."""

    def test_separation_error_captured_in_step_errors(self, tmp_path):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, asr=False, translation=False, tts=False, mix=False)

        mock_sep = MagicMock()
        mock_sep.separate.side_effect = RuntimeError("GPU OOM")

        executor = PipelineExecutor(separator=mock_sep)
        results = executor.execute(plan)

        assert "vocal_separator" in results["step_errors"]
        assert "GPU OOM" in results["step_errors"]["vocal_separator"]

    def test_asr_error_does_not_prevent_subsequent_stages(self, tmp_path, mock_llm):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, separation=False, tts=False, mix=False)

        mock_asr = MagicMock()
        mock_asr.transcribe_file.side_effect = RuntimeError("model not found")

        executor = PipelineExecutor(asr=mock_asr, llm=mock_llm)
        results = executor.execute(plan)

        assert "asr" in results["step_errors"]
        # Translation still attempted (with empty segments)
        mock_llm.translate_texts.assert_called_once()

    def test_translation_error_captured(self, tmp_path, mock_asr):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, separation=False, tts=False, mix=False)

        mock_llm = MagicMock()
        mock_llm.translate_texts.side_effect = RuntimeError("API timeout")

        executor = PipelineExecutor(asr=mock_asr, llm=mock_llm)
        results = executor.execute(plan)

        assert "translate" in results["step_errors"]
        assert "API timeout" in results["step_errors"]["translate"]


class TestPipelineExecutorProgressCallback:
    """Test progress callback invocation."""

    def test_progress_callback_called_for_each_stage(self, tmp_path, mock_separator, mock_asr, mock_llm, mock_tts, mock_mixer_factory):
        (tmp_path / "input.wav").write_bytes(b"audio")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "tts_output.wav").write_bytes(b"tts")

        plan = _make_plan(tmp_path)
        messages = []

        executor = PipelineExecutor(
            separator=mock_separator, asr=mock_asr, llm=mock_llm,
            tts=mock_tts, mixer_factory=mock_mixer_factory,
        )
        executor.execute(plan, progress_callback=lambda msg: messages.append(msg))

        assert len(messages) == 6  # five pipeline stages plus export
        assert "人声分离" in messages[0]
        assert "ASR" in messages[1]
        assert "翻译" in messages[2]
        assert "TTS" in messages[3]
        assert "混合" in messages[4]


class TestPipelineExecutorResultShape:
    """Test result dictionary shape matches ArtifactResultMapper output."""

    def test_result_has_required_keys(self, tmp_path, mock_asr, mock_llm):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, separation=False, tts=False, mix=False)

        executor = PipelineExecutor(asr=mock_asr, llm=mock_llm)
        results = executor.execute(plan)

        required_keys = {
            "input", "output_dir", "mix_path", "exported_subtitle",
            "primary_output", "vocal_path", "tts_audio_path",
            "transcript_path", "steps", "step_errors",
            "total_steps", "total_duration", "error",
        }
        assert required_keys.issubset(set(results.keys()))
        assert results["error"] is None
        assert isinstance(results["total_duration"], float)
        assert results["total_duration"] > 0


class TestPipelineExecutorOutputPaths:
    """Test output path layout matches legacy planner semantics."""

    def test_single_mode_uses_main_dir_plus_by_product_subdir(self, tmp_path, mock_asr):
        (tmp_path / "input.wav").write_bytes(b"audio")
        plan = _make_plan(tmp_path, separation=False, translation=False, tts=False, mix=False)

        executor = PipelineExecutor(asr=mock_asr)
        results = executor.execute(plan)

        assert results["output_dir"].endswith(str(Path("output") / "BY_Product"))
        assert results["transcript_path"].endswith(str(Path("output") / "BY_Product" / "asr_result.txt"))

    def test_batch_mode_uses_main_product_and_task_scoped_by_product_dir(self, tmp_path, mock_asr):
        (tmp_path / "input.wav").write_bytes(b"audio")
        batch_root = tmp_path / "batch-output"
        plan = _make_plan(tmp_path, separation=False, translation=False, tts=False, mix=False)
        plan.output_mode = "batch"
        plan.batch_root_dir = str(batch_root)

        executor = PipelineExecutor(asr=mock_asr)
        results = executor.execute(plan)

        assert results["output_dir"].endswith(str(Path("BY_Product") / "input_by"))
        assert results["transcript_path"].endswith(
            str(Path("batch-output") / "BY_Product" / "input_by" / "asr_result.txt")
        )


class TestPipelineExecutorSkipExisting:
    """Test skip_existing logic."""

    def test_skip_existing_separation(self, tmp_path):
        (tmp_path / "input.wav").write_bytes(b"audio")
        output_dir = tmp_path / "output"
        by_product_dir = output_dir / "BY_Product"
        by_product_dir.mkdir(parents=True)
        (by_product_dir / "vocal.wav").write_bytes(b"existing_vocal")

        plan = _make_plan(tmp_path, asr=False, translation=False, tts=False, mix=False)
        plan.skip_existing = True

        mock_sep = MagicMock()
        executor = PipelineExecutor(separator=mock_sep)
        results = executor.execute(plan)

        # Separator should NOT be called since file exists
        mock_sep.separate.assert_not_called()
        assert results["steps"]["vocal_separator"]["skipped"] is True
