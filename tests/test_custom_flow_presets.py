"""Local-only contract checks for one shared, revisioned workflow preset catalog."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.api.http import dependencies
from src.api.http.routes.pipeline import router
from src.api.http.schemas.pipeline import GraphPresetItem
from src.app.services.preset_catalog_service import PresetCatalogService, PresetConflictError


BUILTINS = Path(__file__).resolve().parents[1] / "config" / "presets.yaml"
DRAFT = {"label": "My flow", "description": "Only target subtitle speech",
         "stages": ["tts"], "outputs": ["tts"]}


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "flow_presets.json"
    svc = PresetCatalogService(BUILTINS, path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[dependencies.preset_catalog_service] = lambda: svc
    with TestClient(app) as client:
        yield client, svc, path


def test_shared_graph_catalog_copies_builtin_without_changing_outputs(catalog, monkeypatch):
    client, _, path = catalog
    monkeypatch.setattr(dependencies, "get_pipeline_service", lambda: pytest.fail("No execution"))
    initial = client.get("/api/v1/pipeline/presets?include_graph=true").json()["presets"]
    assert len(initial) == 2 and not path.exists()
    source = initial[0]
    assert all(item["version"] == 2 and item["builtin"] for item in initial)
    created = client.post(f"/api/v1/pipeline/presets/{source['id']}/copy",
                          json={"label": "My graph copy"})
    assert created.status_code == 201
    saved = created.json()
    assert saved["id"].startswith("custom_") and not saved["builtin"]
    assert saved["graph"] == source["graph"]
    reloaded = PresetCatalogService(BUILTINS, path).list_presets()
    assert [GraphPresetItem.model_validate(item).model_dump() for item in reloaded] == initial + [saved]
    assert client.get("/api/v1/pipeline/presets?include_graph=true").json()["presets"] == initial + [saved]
    forbidden = client.put(f"/api/v1/pipeline/presets/{source['id']}",
                           json={**DRAFT, "revision": source["revision"]})
    assert forbidden.status_code == 403
    assert client.post("/api/v1/pipeline/presets/absent/copy",
                       json={"label": "Unknown"}).status_code == 404


def test_custom_edits_check_revision_and_only_write_chosen_steps_outputs(catalog):
    client, _, path = catalog
    created = client.post("/api/v1/pipeline/presets", json=DRAFT)
    assert created.status_code == 201
    saved = created.json()
    edit = {**DRAFT, "stages": ["translation", "export"], "outputs": ["export"], "revision": 1}
    url = f"/api/v1/pipeline/presets/{saved['id']}"
    updated = client.put(url, json=edit)
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["stages"] == ["translate", "export"]
    assert updated.json()["outputs"] == ["export"]
    content = path.read_bytes()
    assert client.put(url, json=edit).status_code == 409
    assert path.read_bytes() == content
    assert json.loads(content)["presets"] == [updated.json()]


def test_invalid_or_unrelated_fields_are_rejected_without_saving(catalog):
    client, _, path = catalog
    invalid = [
        {**DRAFT, "stages": []}, {**DRAFT, "outputs": []},
        {**DRAFT, "stages": ["not-a-stage"]}, {**DRAFT, "outputs": ["asr"]},
        {**DRAFT, "stages": ["translate", "translation"]}, {**DRAFT, "label": "   "},
        {**DRAFT, "bindings": {}}, {**DRAFT, "api_key": "not-a-real-key"},
        {**DRAFT, "language": "en"}, {**DRAFT, "params": {"speed": 1}},
    ]
    for body in invalid:
        assert client.post("/api/v1/pipeline/presets", json=body).status_code == 422
    assert not path.exists()
    saved = client.post("/api/v1/pipeline/presets", json=DRAFT).json()
    assert client.put(f"/api/v1/pipeline/presets/{saved['id']}",
                      json={**DRAFT, "revision": True}).status_code == 422


def test_legacy_aliases_normalize_and_malformed_catalogs_never_get_overwritten(catalog, tmp_path):
    client, _, path = catalog
    legacy = tmp_path / "legacy.yaml"
    legacy.write_text("presets:\n  - id: old\n    label: Old\n"
                      "    stages: [separation, asr, translation, export]\n", encoding="utf-8")
    item = PresetCatalogService(legacy, path).list_presets()[0]
    assert item["stages"] == item["outputs"] == ["separate", "asr", "translate", "export"]
    legacy.write_text("typo_presets: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid format"):
        PresetCatalogService(legacy, path).list_presets()
    for version in (1, 2):
        valid = json.dumps({"version": version, "presets": []}).encode()
        path.write_bytes(valid)
        assert client.get("/api/v1/pipeline/presets?include_graph=true").status_code == 200
        assert path.read_bytes() == valid
    for corrupt in [b"{partial", b'{"version": 4, "presets": []}',
                    b'{"version": 1, "preset_typo": []}',
                    b'{"version": 1, "presets": [{"id":"bad", "api_key":"placeholder"}]}']:
        path.write_bytes(corrupt)
        assert client.get("/api/v1/pipeline/presets").status_code == 422
        assert client.post("/api/v1/pipeline/presets", json=DRAFT).status_code == 422
        assert path.read_bytes() == corrupt


def test_atomic_replace_failure_keeps_last_catalog(catalog, monkeypatch):
    client, svc, path = catalog
    saved = svc.create_preset(DRAFT)
    content = path.read_bytes()

    def reject_replace(*_args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("src.app.services.preset_catalog_service.os.replace", reject_replace)
    response = client.put(f"/api/v1/pipeline/presets/{saved['id']}",
                          json={**DRAFT, "label": "Unsaved", "revision": 1})
    assert response.status_code == 503
    assert path.read_bytes() == content
    assert not list(path.parent.glob("*.tmp"))


def test_concurrent_editors_cannot_overwrite_same_revision(catalog):
    _, svc, path = catalog
    saved = svc.create_preset(DRAFT)
    barrier = Barrier(2)

    def edit(label):
        other = PresetCatalogService(BUILTINS, path)
        barrier.wait(timeout=5)
        try:
            return other.update_preset(saved["id"], {**DRAFT, "label": label}, 1)
        except PresetConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["Editor one", "Editor two"]))
    assert results.count("conflict") == 1
    winner = next(result for result in results if isinstance(result, dict))
    assert winner["revision"] == 2
    assert svc.list_presets()[-1] == winner


def test_builtin_delete_stays_deleted_and_template_add_creates_new_identity(catalog):
    client, svc, path = catalog
    original = svc.list_presets()[0]
    url = f"/api/v1/pipeline/presets/{original['id']}"
    assert client.delete(url, params={"revision": original["revision"]}).status_code == 204
    for _ in range(2):
        reopened = PresetCatalogService(BUILTINS, path)
        assert original["id"] not in {item["id"] for item in reopened.list_presets()}
    assert client.post(url + "/restore", json={"revision": original["revision"] + 1}).status_code == 404
    templates = client.get("/api/v1/pipeline/templates").json()["presets"]
    assert original in templates
    added = client.post(f"/api/v1/pipeline/templates/{original['id']}/add", json={"revision": original["revision"]})
    assert added.status_code == 201
    item = added.json()
    assert item["id"] != original["id"] and not item["builtin"] and item["revision"] == 1
    assert item["graph"] == original["graph"]
    assert original["id"] not in {row["id"] for row in svc.list_presets()}
    assert client.delete(f"/api/v1/pipeline/presets/{item['id']}/permanent", params={"revision": 1}).status_code == 200
    assert item["id"] not in {row["id"] for row in PresetCatalogService(BUILTINS, path).list_presets()}


@pytest.mark.parametrize("version", [1, 2, 3])
def test_both_delete_routes_remove_custom_data_without_new_backup(catalog, version):
    client, svc, path = catalog
    raw = {"id": "custom_remove", **DRAFT, "revision": 1, "builtin": False}
    data = {"version": version, "presets": [raw]}
    if version == 3:
        data["index"] = {raw["id"]: {"active": True, "revision": 1}}
    path.write_text(json.dumps(data), encoding="utf-8")
    old_backup = path.with_suffix('.old.bak')
    old_backup.write_bytes(b'previous user backup')
    endpoint = '/permanent' if version == 2 else ''
    assert client.delete(f"/api/v1/pipeline/presets/{raw['id']}{endpoint}", params={"revision": 1}).status_code in (200, 204)
    state = json.loads(path.read_text(encoding="utf-8"))
    assert not state["presets"] and raw["id"] not in state["index"]
    assert not svc.list_archived_presets()
    assert list(path.parent.glob('*.bak')) == [old_backup]
    assert old_backup.read_bytes() == b'previous user backup'


def test_legacy_removed_custom_is_read_only_and_never_exposed_as_template(catalog):
    client, svc, path = catalog
    legacy = {"id": "custom_legacy", **DRAFT, "revision": 1, "builtin": False}
    data = {"version": 3, "presets": [legacy], "index": {legacy["id"]: {"active": False, "revision": 2}}}
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    assert legacy["id"] not in {item["id"] for item in svc.list_presets()}
    assert client.get('/api/v1/pipeline/presets/archived').status_code in (404, 405)
    assert client.post(f"/api/v1/pipeline/presets/{legacy['id']}/restore", json={"revision": 2}).status_code == 404
    assert client.post(f"/api/v1/pipeline/templates/{legacy['id']}/add", json={"revision": 2}).status_code == 404
    assert all(item["builtin"] for item in client.get('/api/v1/pipeline/templates').json()["presets"])
    assert path.read_bytes() == before
    svc.create_preset({**DRAFT, "label": "Unrelated new preset"})
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["presets"][0] == legacy and after["index"][legacy["id"]] == data["index"][legacy["id"]]
    assert svc.list_archived_presets()[0]["id"] == legacy["id"]


def test_template_conflict_and_stale_revision_do_not_modify_catalog(catalog):
    client, svc, path = catalog
    template = svc.list_builtin_templates()[0]
    url = f"/api/v1/pipeline/templates/{template['id']}/add"
    assert client.post(url, json={"revision": template["revision"]}).status_code == 409
    assert client.post(url, json={"revision": template["revision"] + 1, "label": "New"}).status_code == 409
    assert not path.exists()
