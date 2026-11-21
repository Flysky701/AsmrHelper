"""V2 translation tasks pin node connections privately."""

from dataclasses import asdict
import json
import sqlite3

from src.app.dto import PipelineRequest
from src.app.persistence import SqliteStateStore
from src.app.services.artifact_service import ArtifactService
from src.app.services.input_catalog_service import InputCatalogService
from src.app.services.pipeline_service import PipelineService
from src.app.services.session_service import SessionService
from src.app.services.task_service import TaskService
from src.config import config
from src.provider_profiles import project_profiles


def test_queued_translation_uses_frozen_credentials_without_persisting_them(monkeypatch, tmp_path):
    settings = project_profiles({
        "api": {},
        "connection_profiles": {
            "active_llm": "initial",
            "llm": [{"id": "initial", "name": "Test", "provider": "deepseek",
                     "base_url": "https://test-provider.invalid", "model": "deepseek-chat",
                     "api_key": "original-node-secret"}],
        },
        "paths": {"output_dir": str(tmp_path / "config-out")},
    })
    monkeypatch.setattr(config, "_config", settings)
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    tasks = TaskService(state_store=store)
    catalog = InputCatalogService()
    pipeline = PipelineService(
        task_service=tasks,
        input_catalog_service=catalog,
        session_service=SessionService(input_catalog_service=catalog),
        artifact_service=ArtifactService(state_store=store),
    )
    subtitle = tmp_path / "source.vtt"
    subtitle.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHello, world!\n", encoding="utf-8")
    status, spec = pipeline.create_pipeline_task(PipelineRequest(
        input_path=str(subtitle), output_dir=str(tmp_path / "out"),
        execution_profile={
            "version": 2,
            "graph": {
                "version": 2,
                "nodes": [{"id": "translate", "kind": "translate", "provider": "deepseek",
                           "source_lang": "en", "target_lang": "zh",
                           "options": {"connection_ref": "initial"}}],
                "input_slots": [{"id": "source", "type": "subtitle", "label": "Source", "language": "en"}],
                "edges": [{"source": {"kind": "slot", "slot_id": "source"},
                           "target": {"node_id": "translate", "port": "subtitle"}}],
                "outputs": [{"node_id": "translate", "port": "subtitle"}],
            },
            "bindings": {"source": {"path": str(subtitle), "language": "en", "language_confirmed": True}},
        },
    ))
    assert status.state == "pending"
    settings["connection_profiles"]["llm"][0]["api_key"] = "rotated-node-secret"
    settings["paths"]["output_dir"] = str(tmp_path / "new-output")
    project_profiles(settings)

    with tasks.graph_node_connection_context(spec.task_id, "translate"):
        assert config.get("api.deepseek_api_key") == "original-node-secret"
        assert config.get("api.deepseek_model") == "deepseek-chat"
        assert config.get("paths.output_dir") == str(tmp_path / "new-output")
    assert config.get("api.deepseek_api_key") == "rotated-node-secret"

    public = json.dumps([asdict(spec), asdict(status)])
    with sqlite3.connect(store.db_path) as connection:
        persisted = "\n".join(connection.iterdump())
    for secret in ("original-node-secret", "rotated-node-secret", "https://test-provider.invalid"):
        assert secret not in public
        assert secret not in persisted
