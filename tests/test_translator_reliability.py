"""No-network regressions for cache identity and explicit translation failures."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.core.engines.llm.cache import TranslationCache
from src.core.engines.llm.translator import Translator, TranslationError


def response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def translator(tmp_path, **options):
    instance = Translator(api_key="test-secret", use_terminology=False,
                          use_quality_check=False, max_retries=1, **options)
    instance._cache = TranslationCache(tmp_path)
    create = Mock(return_value=response("translated"))
    instance._get_client = Mock(return_value=SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))))
    return instance, create


def test_identical_request_hits_cache_and_legacy_text_key_is_ignored(tmp_path):
    instance, create = translator(tmp_path)
    instance._cache.set("hello", "unsafe legacy value", "old-model")
    assert instance.translate_batch(["hello"]) == ["translated"]
    assert instance.translate_batch(["hello"]) == ["translated"]
    assert create.call_count == 1
    serialized = next(tmp_path.glob("translation-v2-*.json")).read_text(encoding="utf-8")
    assert "test-secret" not in serialized


@pytest.mark.parametrize("change", [
    "target",
    "endpoint",
    "credential",
    "namespace",
])
def test_changed_translation_context_misses_cache(tmp_path, change):
    instance, create = translator(tmp_path)
    request = dict(source_lang="Japanese", target_lang="Chinese", system_prompt="first prompt")
    instance.translate_batch(["hello"], **request)
    if change == "target":
        request["target_lang"] = "English"
    elif change == "endpoint":
        instance.base_url = "https://other.invalid/v1"
    elif change == "credential":
        instance._api_key_override = "other-secret"
    else:
        instance.cache_namespace = "other-project"
    instance.translate_batch(["hello"], **request)
    assert create.call_count == 2


def test_batch_neighbours_change_cache_identity(tmp_path):
    instance, create = translator(tmp_path)
    create.return_value = response(json.dumps([{"id": 0, "dst": "one"}, {"id": 1, "dst": "two"}]))
    instance.translate_batch(["hello", "first neighbour"])
    instance.translate_batch(["hello", "other neighbour"])
    assert create.call_count == 2


def test_cache_initialization_failure_still_translates(tmp_path, monkeypatch):
    import src.core.engines.llm.cache as cache_module
    instance, create = translator(tmp_path)
    instance._cache = None
    monkeypatch.setattr(cache_module, "TranslationCache", Mock(side_effect=OSError("unavailable cache directory")))
    assert instance.translate_batch(["hello"]) == ["translated"]
    assert create.call_count == 1


def test_valid_scoped_disk_cache_reloads_without_using_old_namespace(tmp_path, monkeypatch):
    import src.core.engines.llm.cache as cache_module
    TranslationCache(tmp_path).save({}, "default")
    monkeypatch.setattr(cache_module, "TranslationCache", lambda: TranslationCache(tmp_path))
    first, create = translator(tmp_path)
    first._cache = None
    first.translate_batch(["hello"])
    second, next_create = translator(tmp_path)
    second._cache = None
    assert second.translate_batch(["hello"]) == ["translated"]
    next_create.assert_not_called()
    assert first._cache is not second._cache


def test_retry_exhaustion_raises_and_does_not_cache_partial_success(tmp_path):
    instance, create = translator(tmp_path, use_batch=False)
    create.side_effect = [response("good translation"), RuntimeError("fake upstream secret")]
    with pytest.raises(TranslationError, match="第 2") as error:
        instance.translate_batch(["first text", "second text"])
    assert "fake upstream" not in str(error.value)
    assert not instance._cache._memory_cache
    assert not list(tmp_path.glob("*.json"))


@pytest.mark.parametrize("batch", [
    [{"id": 0, "dst": "one"}, {"id": 0, "dst": "two"}],
    [{"id": 0, "dst": "one"}, {"id": 1, "dst": ""}],
])
def test_malformed_batch_retries_individually_without_claiming_original_is_success(tmp_path, batch):
    instance, create = translator(tmp_path)
    create.side_effect = [response(json.dumps(batch)), response("single one"), response("single two")]
    assert instance.translate_batch(["hello", "world"]) == ["single one", "single two"]
    assert create.call_count == 3


def test_quality_rejection_never_returns_original_or_caches_rejected_result(tmp_path):
    instance, _ = translator(tmp_path)
    instance.use_quality_check = True
    instance._get_quality_checker = lambda: SimpleNamespace(check_batch=lambda *args: [
        SimpleNamespace(has_issues=True, translation="translated", original="hello", index=0,
                        issues=[SimpleNamespace(value="japanese_residue")])])
    with pytest.raises(TranslationError, match="质量检查"):
        instance.translate_batch(["hello"])
    assert not instance._cache._memory_cache
