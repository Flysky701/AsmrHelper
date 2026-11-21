from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
from pathlib import Path
import subprocess

import numpy as np
import pytest
import soundfile as sf

from scripts.import_voice_library import import_library
from src.core.speech.store import SpeechStore, validate_plan


def _voice(name="Voice"):
    return {"name": name, "bindings": [{"provider_id": "qwen3", "variants": [
        {"kind": "builtin", "value": "Vivian", "style": "normal"}
    ]}], "default_binding": "qwen3"}


def _recipe():
    return {"name": "Recipe", "voice_id": "v", "provider_id": "qwen3", "model": "m",
            "variant": {"kind": "builtin", "value": "Vivian", "style": "normal"},
            "provider_options": {"schema_version": 1}}


def test_reference_preview_save_match_without_transcript_and_preserve_source(tmp_path):
    original = tmp_path / "source.wav"
    sf.write(original, np.full(1000, .2, dtype=np.float32), 1000, subtype="FLOAT")
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    store = SpeechStore(tmp_path / "library")
    options = dict(name="素材", notes="未转录", gain_db=6, fade_in=.1, fade_out=.1)
    preview = store.import_reference(original, .1, .9, "", "ja", False, preview=True, **options)
    assert store.list("assets") == []
    assert store.get_inspection(preview["id"])["staged"]
    saved = store.import_reference(original, .1, .9, "", "ja", False, **options)
    assert saved["sha256"] == preview["sha256"]
    assert saved["confirmed"] is False
    samples, _ = sf.read(saved["path"])
    assert samples[0] == samples[-1] == 0
    assert samples[200] == pytest.approx(.2 * 10**(.3), rel=1e-6)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    store.create("recipes", {**_recipe(), "variant": {"kind": "reference", "value": saved["id"], "style": "normal"}})
    changed = store.reference_metadata(saved["id"], {"name": "新名称"})
    assert changed["id"] == saved["id"] and changed["sha256"] == saved["sha256"]
    assert store.reference_audio_path(saved["id"]).is_file()
    with pytest.raises(ValueError):
        store.reference_metadata(saved["id"], {"path": "other.wav"})
    crop = store.import_reference(saved["path"], .1, .4, "", "ja", False)
    assert crop["parent_asset_id"] == saved["id"]
    inspected = store.inspect_reference(saved["path"])
    staged_crop = store.import_reference(inspected["path"], .1, .4, "", "ja", False)
    assert staged_crop["parent_asset_id"] == saved["id"]
    assert staged_crop["source_processing"]["parent_asset_id"] == saved["id"]


def test_multiple_store_instances_do_not_lose_concurrent_writes(tmp_path):
    def save(index):
        return SpeechStore(tmp_path).create("voices", _voice(str(index)))
    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(save, range(24)))
    assert len(SpeechStore(tmp_path).list("voices")) == 24


def test_atomic_write_failure_keeps_previous_store(tmp_path, monkeypatch):
    import src.core.speech.store as module
    store = SpeechStore(tmp_path)
    voice = store.create("voices", _voice())
    old = store.path.read_bytes()
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError):
        store.update("voices", voice["id"], {"name": "lost"})
    assert store.path.read_bytes() == old
    assert not list(tmp_path.glob(".write-*"))


def test_secret_material_is_rejected_recursively(tmp_path):
    store = SpeechStore(tmp_path)
    with pytest.raises(ValueError, match="secrets"):
        store.create("takes", {"request": {"api_key": "private"}})
    assert store.list("takes") == []


@pytest.mark.parametrize("proposed", [
    {"segments": [{"start": 0, "end": 2}]},
    {"segments": [{"start": 0, "end": 2}, {"start": 1, "end": 3}]},
    {"segments": [{"start": 0, "end": 3, "text": "new words"}]},
])
def test_llm_plan_cannot_rewrite_drop_duplicate_or_add_text(proposed):
    with pytest.raises(ValueError):
        validate_plan("abc", proposed)


def _audio(tmp_path):
    original = tmp_path / "original.wav"
    samples = np.stack([np.linspace(-0.5, 0.5, 8000), np.linspace(0.4, -0.4, 8000)], axis=1)
    sf.write(original, samples, 8000, subtype="FLOAT")
    return original


def test_reference_inspection_crop_and_original_are_persistent(tmp_path):
    original = _audio(tmp_path)
    original_bytes = original.read_bytes()
    store = SpeechStore(tmp_path / "library")
    inspection = store.inspect_reference(original)
    assert inspection["duration"] == 1
    assert inspection["peaks"]
    assert store.list("assets") == []
    assert store.get_inspection(inspection["id"]) == inspection
    asset = store.import_reference(inspection["path"], 0.25, 0.75, "真实转录", "zh", True)
    assert asset["original_path"] == str(original)
    assert asset["inspection_id"] == inspection["id"]
    assert original.read_bytes() == original_bytes
    assert asset["duration"] == 0.5
    assert asset["channels"] == 2
    assert sf.info(asset["path"]).frames == 4000
    original.write_bytes(b"user may replace original later")
    reopened = SpeechStore(store.root)
    assert reopened.reference_audio_path(asset["id"]).is_file()
    assert reopened.reference_audio_path(asset["id"], source=True).read_bytes() == original_bytes
    assert reopened.get("assets", asset["id"])["transcript"] == "真实转录"


def test_reference_tampering_is_detected(tmp_path):
    original = _audio(tmp_path)
    store = SpeechStore(tmp_path / "library")
    asset = store.import_reference(original, 0, 1, "spoken words", "en")
    Path(asset["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        store.reference_audio_path(asset["id"])


@pytest.mark.parametrize("inspect_first", [False, True])
def test_real_m4a_reference_decodes_without_changing_original(tmp_path, inspect_first):
    from src.utils import get_ffmpeg
    wav = _audio(tmp_path)
    compressed = tmp_path / "reference.m4a"
    subprocess.run([get_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", str(wav),
                    "-c:a", "aac", str(compressed)], check=True, capture_output=True, timeout=30)
    original = compressed.read_bytes()
    source_hash = hashlib.sha256(original).hexdigest()
    store = SpeechStore(tmp_path / "library")
    source = compressed
    if inspect_first:
        inspection = store.inspect_reference(compressed)
        assert inspection["peaks"] and inspection["duration"] >= 1
        assert Path(inspection["path"]).suffix == ".wav"
        assert sf.info(inspection["path"]).channels == 2
        assert inspection["source_sha256"] == source_hash
        assert Path(inspection["source_path"]).read_bytes() == original
        assert store.get_inspection(inspection["id"]) == inspection
        source = Path(inspection["path"])
    asset = store.import_reference(source, .25, .75, "真实参考文本", "zh")
    assert asset["original_path"] == str(compressed)
    assert asset["source_sha256"] == source_hash
    assert Path(asset["source_path"]).read_bytes() == original
    assert sf.info(asset["path"]).frames == 4000
    assert sf.info(asset["source_playback_path"]).duration >= 1
    assert compressed.read_bytes() == original
    if inspect_first:
        Path(inspection["source_path"]).write_bytes(b"changed compressed source")
        with pytest.raises(ValueError, match="changed"):
            store.get_inspection(inspection["id"])


def test_explicit_import_backs_up_and_does_not_guess_connection_provider(tmp_path):
    voices = tmp_path / "old-voices.json"
    voices.write_text(json.dumps({"profiles": [
        {"id": "A1", "name": "Known", "category": "preset", "engine": "qwen3_custom", "speaker": "Vivian"},
        {"id": "B1", "name": "Unmapped", "category": "clone", "engine": "qwen3_clone"},
    ]}), encoding="utf-8")
    connections = tmp_path / "connections.json"
    connections.write_text(json.dumps({"tts": [{"id": "cloud", "name": "Service", "base_url": "https://example.invalid", "api_key": "secret"}]}))
    before = voices.read_bytes()
    store = SpeechStore(tmp_path / "library")
    report = import_library(store, voices_path=voices, connections_path=connections)
    assert Path(report["backup"], "manifest.json").is_file()
    assert len(report["voices"]) == 1
    assert len(report["unmapped"]) == 2
    assert store.list("connections") == []
    assert voices.read_bytes() == before
    assert "secret" not in store.path.read_text()


def test_explicit_connection_mapping_keeps_credentials_out_of_public_store(tmp_path):
    source = tmp_path / "connections.json"
    source.write_text(json.dumps({"tts": [{"id": "old", "api_key": "private-key", "base_url": "https://example.invalid"}]}))
    store = SpeechStore(tmp_path / "library")
    report = import_library(store, connections_path=source, connection_map={"old": {"provider_id": "fish_audio"}})
    assert len(report["connections"]) == 1
    connection = store.list("connections")[0]
    assert connection["provider_id"] == "fish_audio"
    assert "private-key" not in store.path.read_text()
    assert json.loads((store.root / "credentials" / f"{connection['credential_ref']}.json").read_text())["api_key"] == "private-key"


def test_import_aborts_before_mutations_when_backup_fails(tmp_path, monkeypatch):
    voices = tmp_path / "voices.json"
    voices.write_text(json.dumps({"profiles": [{"id": "A1", "name": "V", "category": "preset", "speaker": "Vivian"}]}))
    store = SpeechStore(tmp_path / "library")
    def fail(*args):
        raise OSError("backup unavailable")
    monkeypatch.setattr(store, "backup_for_import", fail)
    with pytest.raises(OSError):
        import_library(store, voices_path=voices)
    assert not store.path.exists()
