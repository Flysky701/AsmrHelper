from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from src.core.engines.alignment import AlignmentRuntime, alignment_windows
from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.models import PipelineExecutionPlan, StageKind
from src.api.http.schemas.pipeline_runs import PipelineStagesRequest


def test_defaults_are_opt_in():
    plan = PipelineExecutionPlan(task_id="test", input_path="a", output_dir="b")
    assert StageKind.ALIGN not in plan.active_stage_kinds
    assert not PipelineStagesRequest().align.enabled
    plan.alignment.enabled = True
    assert plan.active_stage_kinds.index(StageKind.ALIGN) == plan.active_stage_kinds.index(StageKind.ASR) + 1


def test_long_script_requires_real_anchors():
    with pytest.raises(ValueError, match="时间锚点"):
        alignment_windows([{"text": "long script"}], 301)
    with pytest.raises(ValueError, match="5 分钟"):
        alignment_windows([{"text": "long script", "start": 0, "end": 301}], 302)


@pytest.mark.parametrize("start,end", [(float("nan"), 2), (2, 1), (-1, 2), (1, 15)])
def test_invalid_anchors(start, end):
    with pytest.raises(ValueError, match="无效"):
        alignment_windows([dict(text="hello", start=start, end=end)], 10)


def test_offsets_and_integer_seconds(tmp_path):
    source = tmp_path / "audio.wav"
    sf.write(source, np.zeros(12 * 16000), 16000)
    model = Mock()
    model.align.return_value = [SimpleNamespace(items=[SimpleNamespace(text="hello", start_time=1, end_time=2)])]
    result = AlignmentRuntime(local=True, model=model).align_file(input_path=str(source),
        segments=[dict(text="hello", start=8, end=10)], language="en")
    assert result["segments"][0]["start"] == 8.25
    assert result["segments"][0]["end"] == 9.25
    assert result["words"][0]["start"] == 8.25
    assert model.align.call_args.kwargs["language"] == "English"


def test_missing_model_never_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr("src.core.engines.alignment.resolve_model_reference", lambda _: str(tmp_path / "absent"))
    with pytest.raises(RuntimeError, match="安装"):
        AlignmentRuntime._load_model()


def test_pipeline_alignment_preserves_original_and_exports(tmp_path):
    plan = PipelineExecutionPlan(task_id="test", input_path=str(tmp_path / "input.wav"), output_dir=str(tmp_path / "out"))
    plan.separation.enabled = plan.translation.enabled = plan.tts.enabled = plan.mix.enabled = False
    plan.alignment.enabled = True
    asr, aligner = Mock(), Mock()
    asr.transcribe_file.return_value = SimpleNamespace(segments=[SimpleNamespace(start=0, end=2, text="hello")])
    aligner.align_file.return_value = dict(segments=[dict(start=.5, end=1.5, text="hello")], words=[], warnings=[])
    stages = []
    result = PipelineExecutor(asr=asr, aligner=aligner).execute(plan, stage_callback=lambda stage, *_: stages.append(stage))
    assert stages == ["asr", "align", "export"]
    from pathlib import Path
    import json
    assert json.loads(Path(result["alignment_original_path"]).read_text())[0]["start"] == 0
    assert "00:00:00.500" in Path(result["aligned_subtitle_path"]).read_text()
    assert aligner.align_file.call_args.kwargs["input_path"] == plan.input_path


def test_alignment_failure_stops_downstream(tmp_path):
    plan = PipelineExecutionPlan(task_id="test", input_path="input.wav", output_dir=str(tmp_path))
    plan.separation.enabled = plan.asr.enabled = False
    plan.alignment.enabled = True
    aligner, llm = Mock(), Mock()
    aligner.align_file.side_effect = RuntimeError("missing model")
    with pytest.raises(RuntimeError, match="missing model"):
        PipelineExecutor(aligner=aligner, llm=llm).execute(plan)
    llm.translate_texts.assert_not_called()


@pytest.mark.parametrize("start,end", [(float("nan"), 2), (2, 1), (-1, 2), (1, 5)])
def test_model_invalid_timestamps_are_rejected(tmp_path, start, end):
    source = tmp_path / "audio.wav"
    sf.write(source, np.zeros(3 * 16000), 16000)
    model = Mock()
    model.align.return_value = [SimpleNamespace(items=[SimpleNamespace(text="hello", start_time=start, end_time=end)])]
    with pytest.raises(ValueError, match="无效时间戳"):
        AlignmentRuntime(local=True, model=model).align_file(input_path=str(source), segments=[dict(text="hello")], language="en")


def test_readiness_reports_alignment_resource(tmp_path):
    from src.app.services.resource_service import ResourceService
    models = Mock()
    models.list_models.return_value = []
    models.get_model_status.return_value = SimpleNamespace(executable=False, detail="aligner missing")
    service = ResourceService(tmp_path, model_service=models, descriptor_service=Mock())
    issues = service._check_pipeline_profile({"stages": {"align": {
        "enabled": True, "provider": "qwen3_forced_aligner", "model": "qwen3-forced-aligner-0.6b"}}})
    assert any(issue["stage"] == "align" and issue["requirement"] == "qwen3-forced-aligner-0.6b" for issue in issues)


def test_worker_routes_alignment_without_loading_asr(monkeypatch):
    from src.core.runtime.stage_worker import _execute
    runtime = Mock()
    runtime.align_file.return_value = {"segments": []}
    factory = Mock(return_value=runtime)
    monkeypatch.setattr("src.core.engines.alignment.AlignmentRuntime", factory)
    assert _execute({"operation": "alignment.align_file", "payload": {"language": "ja"}}) == {"segments": []}
    factory.assert_called_once_with(local=True)
