"""Real durable checkpoint tests with deterministic, model-free stage doubles."""
from dataclasses import replace
from pathlib import Path
import threading

import pytest

from src.app.persistence.state_store import SqliteStateStore
from src.app.persistence.recovery_store import RecoveryStore
from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.models import PipelineExecutionPlan
from src.core.orchestration.pipeline.recovery import PipelineRecovery
from src.core.tasks import TaskSpec, TaskStatus


class StubExecutor(PipelineExecutor):
    def __init__(self, fail_tts=False):
        super().__init__()
        self.calls = []
        self.fail_tts = fail_tts

    def _execute_asr(self, plan, vocal_path, directory, results):
        self.calls.append("asr")
        output = directory / "asr.txt"
        output.write_text("spoken", encoding="utf-8")
        results["transcript_path"] = str(output)
        results["steps"]["asr"] = {"output": str(output)}
        return [{"text": "spoken", "start": 1.0, "end": 2.0}]

    def _execute_alignment(self, plan, segments, directory, results):
        self.calls.append("align")
        for key in ("alignment_path", "alignment_original_path", "aligned_subtitle_path"):
            output = directory / (key + ".json")
            output.write_text("alignment data", encoding="utf-8")
            results[key] = str(output)
        results["steps"]["align"] = {"output": results["alignment_path"]}
        return [{**segments[0], "start": 1.1, "words": [{"text": "spoken", "start": 1.1}]}]

    def _execute_translation(self, plan, segments, directory, results):
        self.calls.append("translate")
        segments[0]["translation"] = "translated"
        output = directory / "translated.txt"
        output.write_text("translated", encoding="utf-8")
        results["steps"]["translate"] = {"output": str(output)}
        return ["translated"]

    def _execute_tts(self, plan, segments, directory, results):
        self.calls.append("tts")
        assert segments[0]["translation"] == "translated"
        if plan.alignment.enabled:
            assert segments[0]["start"] == 1.1
            assert segments[0]["words"]
        assert not plan.skip_existing
        output = directory / "tts.wav"
        if self.fail_tts:
            output.write_text("partial", encoding="utf-8")
            results["step_errors"]["tts"] = "interrupted synthesis"
        else:
            output.write_text("complete audio", encoding="utf-8")
            results["tts_audio_path"] = str(output)
            results["steps"]["tts"] = {"output": str(output)}
        return output

    def _execute_mix(self, plan, vocal_path, tts_path, mix_path, results):
        self.calls.append("mix")
        mix_path.write_bytes(b"mixed audio")
        results["steps"]["mixer"] = {"output": str(mix_path)}


@pytest.fixture
def setup(tmp_path):
    state = SqliteStateStore(tmp_path / "state.sqlite3")
    for task_id in ("first", "second", "third"):
        state.save_task(TaskSpec(task_id, "pipeline", "test", "session"), TaskStatus(task_id, "pending"))
    store = RecoveryStore(state)
    input_file = tmp_path / "audio.wav"
    input_file.write_bytes(b"input audio")
    plan = PipelineExecutionPlan("first", str(input_file), str(tmp_path / "first"), skip_existing=True)
    plan.separation.enabled = False
    plan.mix.enabled = False
    plan.subtitle.enabled = False
    return store, plan


def run(store, plan, source=None, fail=False, connection="connection-a"):
    executor = StubExecutor(fail_tts=fail)
    recovery = PipelineRecovery(store, plan.task_id, source, plan, connection)
    if fail:
        with pytest.raises(RuntimeError, match="interrupted synthesis"):
            executor.execute(plan, recovery=recovery)
        return executor, None
    return executor, executor.execute(plan, recovery=recovery)


def next_plan(plan, task_id="second"):
    return replace(plan, task_id=task_id, output_dir=str(Path(plan.output_dir).parent / task_id))


def test_failed_stage_restarts_and_completed_stages_survive_restart_and_chain(setup):
    store, plan = setup
    plan.alignment.enabled = True
    run(store, plan, fail=True)
    assert store.checkpoint("first", "tts") is None
    store = RecoveryStore(SqliteStateStore(store.state_store.db_path))
    executor, result = run(store, next_plan(plan), "first")
    assert executor.calls == ["tts"]
    assert Path(result["transcript_path"]).is_relative_to(Path(plan.output_dir).parent / "second")
    for key in ("alignment_path", "alignment_original_path", "aligned_subtitle_path"):
        assert Path(result[key]).is_file()
        assert "second" in Path(result[key]).parts
    executor, _ = run(store, next_plan(plan, "third"), "second")
    assert executor.calls == []


@pytest.mark.parametrize("change,expected", [
    ("input", ["asr", "translate", "tts"]),
    ("model", ["asr", "translate", "tts"]),
    ("translation", ["translate", "tts"]),
    ("connection", ["translate", "tts"]),
    ("corrupt", ["asr", "translate", "tts"]),
    ("missing", ["translate", "tts"]),
])
def test_invalid_facts_invalidate_downstream(setup, change, expected):
    store, plan = setup
    run(store, plan)
    plan = next_plan(plan)
    connection = "connection-a"
    if change == "input":
        Path(plan.input_path).write_bytes(b"changed input")
    elif change == "model":
        plan.asr.model = "other-asr"
    elif change == "translation":
        plan.translation.common_options["prompt"] = "other prompt"
    elif change == "connection":
        connection = "connection-b"
    elif change == "corrupt":
        Path(store.checkpoint("first", "asr")["files"][0]["path"]).write_bytes(b"corruption")
    elif change == "missing":
        Path(store.checkpoint("first", "translate")["files"][0]["path"]).unlink()
    executor, _ = run(store, plan, "first", connection=connection)
    assert executor.calls == expected


def test_changed_local_model_contents_invalidate_checkpoint(setup, tmp_path):
    store, plan = setup
    model = tmp_path / "weights.bin"
    model.write_bytes(b"first weights")
    plan.asr.model = str(model)
    run(store, plan)
    model.write_bytes(b"other weights")
    executor, _ = run(store, next_plan(plan), "first")
    assert executor.calls == ["asr", "translate", "tts"]


def test_changed_companion_invalidates_checkpoint(setup, tmp_path):
    store, plan = setup
    companion = tmp_path / "script.txt"
    companion.write_text("one", encoding="utf-8")
    plan.companion_subtitle_path = str(companion)
    run(store, plan)
    companion.write_text("two", encoding="utf-8")
    executor, _ = run(store, next_plan(plan), "first")
    assert executor.calls == ["asr", "translate", "tts"]


def test_restored_final_outputs_belong_to_new_attempt(setup):
    store, plan = setup
    plan.mix.enabled = True
    plan.subtitle.enabled = True
    _, initial = run(store, plan)
    executor, restored = run(store, next_plan(plan), "first")
    assert executor.calls == []
    for key in ("mix_path", "exported_subtitle", "tts_audio_path", "transcript_path"):
        assert initial[key] != restored[key]
        assert Path(initial[key]).read_bytes() == Path(restored[key]).read_bytes()
        assert "second" in Path(restored[key]).parts


def test_cancelled_stage_is_not_committed(setup):
    store, plan = setup
    event = threading.Event()
    executor = StubExecutor()
    original = executor._execute_asr
    def cancelled_asr(*args):
        value = original(*args)
        event.set()
        return value
    executor._execute_asr = cancelled_asr
    with pytest.raises(RuntimeError, match="取消"):
        executor.execute(plan, cancel_event=event, recovery=PipelineRecovery(store, "first", None, plan))
    assert store.checkpoint("first", "asr") is None
    assert executor.calls == ["asr"]


def test_missing_declared_output_never_publishes_success(setup):
    store, plan = setup
    executor = StubExecutor()
    original = executor._execute_asr
    def missing_asr(*args):
        value = original(*args)
        Path(args[-1]["transcript_path"]).unlink()
        return value
    executor._execute_asr = missing_asr
    with pytest.raises(RuntimeError, match="产物缺失"):
        executor.execute(plan, recovery=PipelineRecovery(store, "first", None, plan))
    assert store.checkpoint("first", "asr") is None
    assert executor.calls == ["asr"]
