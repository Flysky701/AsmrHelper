"""Generation rules are single-engine recipes; performances never mutate voices."""
from copy import deepcopy

import pytest

from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.app.services.artifact_service import ArtifactService
from src.core.speech.store import SpeechStore


@pytest.fixture
def rules(tmp_path):
    service = SpeechService(store=SpeechStore(tmp_path / "rules"), tasks=TaskService(), artifacts=ArtifactService())
    connection = service.save_connection({"name": "Qwen", "provider_id": "qwen3", "deployment": "local"})
    body = {"name": "旁白", "description": "自然清晰", "provider_id": "qwen3", "model": "qwen3-voice-design",
        "mode": "design", "connection_ref": connection["id"], "variant": {"kind": "design", "value": "自然清晰的成年女声"},
        "language": "zh", "provider_options": {"schema_version": 1}}
    return service, body


def test_rule_creates_voice_and_preserves_immutable_revisions(rules):
    service, body = rules
    original = deepcopy(body)
    rule = service.save_rule(body)
    assert body == original
    assert rule["description"] == "自然清晰"
    assert rule["variant"]["style"] == "normal"
    voice = service.store.get("voices", rule["voice_id"])
    assert voice["bindings"] == []
    updated = service.save_rule({**rule, "name": "新版旁白", "description": "第二版"})
    assert updated["voice_id"] == rule["voice_id"]
    assert updated["id"] != rule["id"]
    assert updated["revision"] == 2
    assert service.store.get("recipes", rule["id"]) == rule
    assert len(service.store.list("voices")) == 1
    assert [r["id"] for r in service.active_recipes()] == [updated["id"]]
    service.archive_rule(updated["id"])
    assert service.active_recipes() == []
    assert service.store.get("recipes", rule["id"]) == rule


@pytest.mark.parametrize("change", [
    {"mode": "builtin"}, {"model": "qwen3-base"}, {"name": " "}, {"description": {}},
    {"default_delivery": "invented"}, {"default_emotion": "invented"},
    {"variant": {"kind": "design", "value": "清晰女声", "style": "invented"}},
    {"provider_options": {"schema_version": 1, "invented": True}},
])
def test_invalid_rule_does_not_leave_orphan_voice(rules, change):
    service, body = rules
    with pytest.raises(ValueError):
        service.save_rule({**body, **change})
    assert service.store.list("voices") == []
    assert service.store.list("recipes") == []


def test_provider_reference_constraints_remain_authoritative(rules):
    service, body = rules
    asset = service.store.create("assets", {"sha256": "a" * 64, "transcript": ""})
    with pytest.raises(ValueError, match="转录"):
        service.save_rule({**body, "mode": "reference", "model": "qwen3-base",
            "variant": {"kind": "reference", "value": asset["id"]}})
    assert service.store.list("voices") == []


def test_performance_plan_does_not_change_rule_or_voice(rules):
    service, body = rules
    rule = service.save_rule(body)
    voice = service.store.get("voices", rule["voice_id"])
    plan = service.create_plan({"text": "你好。"})
    plan["segments"][0]["delivery"] = "whisper"
    modified = service.create_plan({"text": plan["text"], "segments": plan["segments"]})
    requests = service.compile(rule["id"], modified["id"])
    assert requests
    assert service.store.get("recipes", rule["id"]) == rule
    assert service.store.get("voices", rule["voice_id"]) == voice


def test_rule_rejects_unsupported_provider_mode(rules):
    service, body = rules
    edge = service.save_connection({"name": "Edge", "provider_id": "edge", "deployment": "cloud"})
    with pytest.raises(ValueError):
        service.save_rule({**body, "connection_ref": edge["id"], "provider_id": "edge", "model": "edge-tts"})
    assert service.store.list("voices") == []


@pytest.mark.parametrize("confirmed", [False, None, "true", 1])
def test_reference_rule_requires_explicit_transcript_confirmation(rules, confirmed):
    service, body = rules
    asset = service.store.create("assets", {"sha256": "a" * 64, "transcript": "你好。", "confirmed": confirmed})
    with pytest.raises(ValueError, match="核对"):
        service.save_rule({**body, "mode": "reference", "model": "qwen3-base",
            "variant": {"kind": "reference", "value": asset["id"]}})
    assert service.store.list("voices") == []
    assert service.store.list("recipes") == []


def test_archived_reference_blocks_new_rules_but_not_historical_compile(rules):
    service, body = rules
    asset = service.store.create("assets", {"sha256": "a" * 64, "transcript": "你好。", "confirmed": True})
    request = {**body, "mode": "reference", "model": "qwen3-base",
        "variant": {"kind": "reference", "value": asset["id"]}}
    rule = service.save_rule(request)
    plan = service.create_plan({"text": "你好。"})
    before = service.compile(rule["id"], plan["id"])
    service.store.reference_metadata(asset["id"], {"archived": True})
    with pytest.raises(ValueError, match="归档"):
        service.save_rule(request)
    assert service.compile(rule["id"], plan["id"]) == before
    assert len(service.store.list("voices")) == 1


def test_provider_without_transcript_requirement_accepts_unconfirmed_reference(rules):
    service, body = rules
    connection = service.save_connection({"name": "Vox", "provider_id": "voxcpm2", "deployment": "local"})
    asset = service.store.create("assets", {"sha256": "a" * 64, "transcript": "", "confirmed": False})
    rule = service.save_rule({**body, "provider_id": "voxcpm2", "connection_ref": connection["id"],
        "mode": "reference", "model": "voxcpm2", "variant": {"kind": "reference", "value": asset["id"]}})
    assert rule["variant"]["value"] == asset["id"]
