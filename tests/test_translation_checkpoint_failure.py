"""Real Translator failures must never become durable successful stages."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import OpenAI

from src.app.persistence.recovery_store import RecoveryStore
from src.app.persistence.state_store import SqliteStateStore
from src.core.engines.llm.service import LlmOperationRuntime
from src.core.engines.llm.translator import Translator
from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.models import PipelineExecutionPlan
from src.core.orchestration.pipeline.recovery import PipelineRecovery
from src.core.tasks import TaskSpec, TaskStatus


@pytest.mark.parametrize("use_batch", [True, False])
@pytest.mark.parametrize("failure", ["api_exhausted", "invalid_response"])
def test_translation_failure_preserves_asr_without_success_checkpoint(tmp_path, monkeypatch, use_batch, failure):
    state = SqliteStateStore(tmp_path / "state.sqlite3")
    task_id = "translation-failure"
    state.save_task(TaskSpec(task_id, "pipeline", "test", "session"), TaskStatus(task_id, "pending"))
    store = RecoveryStore(state)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"stub audio")
    plan = PipelineExecutionPlan(task_id, str(audio), str(tmp_path / "output"))
    plan.separation.enabled = plan.mix.enabled = plan.subtitle.enabled = False
    plan.tts.enabled = False

    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if failure == "api_exhausted":
            return httpx.Response(503, json={"error": {"message": "test unavailable", "type": "server_error"}})
        # Invalid batch schema forces single-item fallback; an empty response to
        # that fallback must fail, rather than publish the original ASR text.
        content = '[{"id": 0, "src": "spoken"}]' if body["max_tokens"] == 2000 else ""
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "test-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        })

    translator = Translator(api_key="test-only", use_terminology=False,
                            use_batch=use_batch, max_retries=1,
                            use_quality_check=False, use_cache=False)
    with OpenAI(api_key="test-only", base_url="https://test.invalid/v1", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
        monkeypatch.setattr(translator, "_get_client", lambda: client)
        registry = SimpleNamespace(get=Mock(return_value=translator))

        class AsrStubExecutor(PipelineExecutor):
            def _execute_asr(self, plan, vocal_path, directory, results):
                output = directory / "asr.txt"
                output.write_text("spoken", encoding="utf-8")
                results["transcript_path"] = str(output)
                results["steps"]["asr"] = {"output": str(output)}
                return [{"text": "spoken", "start": 0.0, "end": 1.0},
                        {"text": "another phrase", "start": 1.0, "end": 2.0}]

        executor = AsrStubExecutor(llm=LlmOperationRuntime(registry=registry))
        with pytest.raises(RuntimeError, match="translate 阶段失败"):
            executor.execute(plan, recovery=PipelineRecovery(store, task_id, None, plan))

    assert len(requests) == (2 if use_batch else 1)
    registry.get.assert_called_once()
    # Reopen the database: these assertions verify persisted checkpoints, not
    # merely an executor's in-memory error bookkeeping.
    reopened = RecoveryStore(SqliteStateStore(state.db_path))
    assert reopened.checkpoint(task_id, "asr") is not None
    assert reopened.checkpoint(task_id, "translate") is None
    assert not list(tmp_path.rglob("translated.txt"))
