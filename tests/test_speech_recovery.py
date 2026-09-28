"""New speech snapshots opt into safe stage reuse without legacy settings."""
from copy import deepcopy
from pathlib import Path

import pytest

import test_pipeline_stage_recovery as stage_recovery
from test_pipeline_stage_recovery import run, next_plan
from src.app.persistence.recovery_store import file_identity
from src.core.speech.compiler import COMPILER_VERSION
from src.core.speech.providers import get_provider
from src.core.orchestration.pipeline.recovery import PipelineRecovery
from src.core.orchestration.pipeline.models import PipelineExecutionContext
from src.core.orchestration.pipeline.planner import build_execution_plan


recovery_setup = stage_recovery.setup


@pytest.fixture(params=["speech", "concrete"])
def setup(recovery_setup, request):
    recovery_setup[1].tts.provider = request.param
    return recovery_setup


def speech_plan(plan, *, provider="fish_audio", model="s2-pro", mode="hosted", kind="hosted", value="voice-id", assets=None, model_path=None):
    connection = {"id": "pinned-connection", "revision": 2, "provider_id": provider, "deployment": "cloud",
        "base_url": "https://speech.invalid/v1", "credential_ref": "opaque-ref"}
    if model_path:
        connection.update(model_path=str(model_path), deployment="local", runtime="qwen_tts", device="cuda:0", precision="auto")
    snapshot = {"compiler_version": COMPILER_VERSION, "provider_version": get_provider(provider).version,
        "recipe": {"id": "recipe", "revision": 1, "provider_id": provider, "model": model, "mode": mode,
            "connection_ref": connection["id"], "variant": {"kind": kind, "value": value, "style": "normal"},
            "language": "zh", "provider_options": {"schema_version": 1}},
        "connection": connection, "assets": assets or {}}
    plan.tts.provider = "speech" if plan.tts.provider == "speech" else provider
    plan.tts.model = model
    plan.tts.provider_options = {"speech_snapshot": snapshot}
    return snapshot


def test_completed_speech_tts_reused_despite_unrelated_global_tts_settings(setup):
    store, plan = setup
    speech_plan(plan)
    run(store, plan, connection={"llm": "same", "tts": "global-before"})
    executor, result = run(store, next_plan(plan), "first", connection={"llm": "same", "tts": "global-after"})
    assert executor.calls == []
    assert Path(result["tts_audio_path"]).read_bytes() == b"complete audio"
    audit = store.checkpoint("second", "tts")["payload"]["speech_identity"]
    assert audit["provider_id"] == "fish_audio"
    assert audit["compiler_version"] == COMPILER_VERSION
    assert "opaque-ref" not in str(audit)


@pytest.mark.parametrize("change", ["compiler", "provider", "connection", "corrupt_output", "missing_output", "missing_audit"])
def test_changed_or_unverifiable_completed_cloud_speech_never_recharged(setup, monkeypatch, change):
    store, plan = setup
    snapshot = speech_plan(plan)
    run(store, plan)
    if change == "compiler":
        snapshot["compiler_version"] = "old-version"
    elif change == "provider":
        monkeypatch.setattr(get_provider("fish_audio"), "version", "changed")
    elif change == "connection":
        snapshot["connection"]["base_url"] = "https://different.invalid/v1"
    elif change in {"corrupt_output", "missing_output"}:
        output = Path(store.checkpoint("first", "tts")["files"][0]["path"])
        if change == "corrupt_output":
            output.write_bytes(b"corrupt")
        else:
            output.unlink()
    else:
        checkpoint = store.checkpoint("first", "tts")
        payload = deepcopy(checkpoint["payload"])
        payload.pop("speech_identity")
        store.commit("first", "tts", checkpoint["fingerprint"], payload, [checkpoint["files"][0]["original"]])
    with pytest.raises(ValueError, match="新任务"):
        run(store, next_plan(plan), "first")
    assert store.checkpoint("second", "tts") is None


def test_local_snapshot_model_and_reference_hashes_allow_safe_reuse(setup, tmp_path):
    store, plan = setup
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"tts_model_type":"base"}')
    (model / "model.safetensors").write_bytes(b"test-weights")
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"test-reference")
    assets = {"asset": {"path": str(reference), "sha256": file_identity(reference)["sha256"], "transcript": "你好"}}
    speech_plan(plan, provider="qwen3", model="qwen3-base", mode="reference", kind="reference", value="asset", assets=assets, model_path=model)
    run(store, plan)
    executor, _ = run(store, next_plan(plan), "first")
    assert executor.calls == []
    audit = store.checkpoint("first", "tts")["payload"]["speech_identity"]
    assert audit["reference_files"]["asset"]["sha256"] == assets["asset"]["sha256"]
    assert len(audit["model"]["files"]) == 2
    (model / "model.safetensors").write_bytes(b"different-weights")
    with pytest.raises(ValueError, match="模型已改变"):
        run(store, next_plan(plan, "third"), "second")


@pytest.mark.parametrize("change", ["asset_changed", "asset_missing", "model_missing", "config_changed"])
def test_reference_or_local_model_drift_blocks_resume(setup, tmp_path, change):
    store, plan = setup
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"tts_model_type":"base"}')
    (model / "model.safetensors").write_bytes(b"weights")
    ref = tmp_path / "reference.wav"
    ref.write_bytes(b"reference")
    speech_plan(plan, provider="qwen3", model="qwen3-base", mode="reference", kind="reference", value="asset",
        assets={"asset": {"path": str(ref), "sha256": file_identity(ref)["sha256"], "transcript": "text"}}, model_path=model)
    run(store, plan)
    if change == "asset_changed":
        ref.write_bytes(b"different")
    elif change == "asset_missing":
        ref.unlink()
    elif change == "model_missing":
        (model / "model.safetensors").unlink()
    else:
        (model / "config.json").write_text('{"tts_model_type":"voice_design"}')
    with pytest.raises(ValueError, match="新任务"):
        run(store, next_plan(plan), "first")


def test_unaudited_speech_provider_and_secret_values_are_rejected(setup):
    store, plan = setup
    snapshot = speech_plan(plan)
    snapshot["connection"]["api_key"] = "must-not-persist"
    with pytest.raises(ValueError, match="凭据引用"):
        run(store, plan)
    snapshot["connection"].pop("api_key")
    snapshot["recipe"]["provider_id"] = "future-provider"
    with pytest.raises(ValueError, match="恢复审计"):
        run(store, plan)


def test_model_changes_during_inference_cannot_publish_reusable_fact(setup, tmp_path):
    store, plan = setup
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"tts_model_type":"custom_voice"}')
    weights = model / "model.safetensors"
    weights.write_bytes(b"original")
    speech_plan(plan, provider="qwen3", model="qwen3-custom-voice", mode="builtin", kind="builtin", value="Vivian", model_path=model)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output = output_dir / "tts.wav"
    results = {"steps": {}, "step_errors": {}}
    def operation():
        output.write_bytes(b"audio")
        weights.write_bytes(b"changed during inference")
        results["steps"]["tts"] = {"output": str(output)}
        return output
    recovery = PipelineRecovery(store, "first", None, plan)
    with pytest.raises(ValueError, match="生成期间"):
        recovery.run("tts", operation, results, [], [], output_dir, tmp_path / "mix.wav")
    assert store.checkpoint("first", "tts") is None


@pytest.mark.parametrize("provider,model,mode,value", [
    ("fish_audio", "s2-pro", "hosted", "voice-id"),
    ("openai_compatible", "tts-1", "hosted", "alloy"),
    ("mimo_audio", "mimo-v2.5-tts", "hosted", "mimo_default"),
    ("edge", "edge-tts", "builtin", "zh-CN-XiaoxiaoNeural"),
    ("qwen3", "qwen3-custom-voice", "builtin", "Vivian"),
    ("voxcpm2", "voxcpm2", "default", "default"),
])
def test_real_planner_resumes_after_mix_failure_without_resynthesis(
        recovery_setup, tmp_path, provider, model, mode, value):
    store, original = recovery_setup
    model_dir = None
    if provider in {"qwen3", "voxcpm2"}:
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "weights.safetensors").write_bytes(b"weights")
    snapshot = speech_plan(original, provider=provider, model=model, mode=mode,
                           kind=mode, value=value, model_path=model_dir)
    profile = {"version": 1, "stages": {
        "separate": {"enabled": False}, "export": {"enabled": False},
        "tts": {"enabled": True, "provider": provider, "model": model,
                "provider_options": {"speech_snapshot": snapshot}},
    }}
    plan = build_execution_plan(PipelineExecutionContext(
        "first", original.input_path, original.output_dir, execution_profile=profile))
    assert plan.tts.provider == provider

    class FailMix(stage_recovery.StubExecutor):
        def _execute_mix(self, *args):
            self.calls.append("mix")
            raise RuntimeError("mix interrupted")

    first = FailMix()
    with pytest.raises(RuntimeError, match="mix interrupted"):
        first.execute(plan, recovery=PipelineRecovery(store, "first", None, plan))
    assert first.calls == ["asr", "translate", "tts", "mix"]
    assert store.checkpoint("first", "tts")["payload"]["speech_identity"]["provider_id"] == provider
    resumed, result = run(store, next_plan(plan), "first", connection="")
    assert resumed.calls == ["mix"]
    assert Path(result["tts_audio_path"]).read_bytes() == b"complete audio"
    assert "second" in Path(result["tts_audio_path"]).parts


@pytest.mark.parametrize("change", ["empty", "missing", "provider_mismatch", "upstream"])
def test_invalid_concrete_snapshot_never_regenerates_completed_audio(recovery_setup, change):
    store, plan = recovery_setup
    speech_plan(plan)
    run(store, plan)
    if change == "empty":
        plan.tts.provider_options["speech_snapshot"] = {}
    elif change == "missing":
        plan.tts.provider_options["speech_snapshot"] = None
    elif change == "provider_mismatch":
        plan.tts.provider = "edge"
    else:
        Path(plan.input_path).write_bytes(b"changed input")
    with pytest.raises(ValueError, match="新任务"):
        run(store, next_plan(plan), "first")
    assert store.checkpoint("second", "tts") is None
