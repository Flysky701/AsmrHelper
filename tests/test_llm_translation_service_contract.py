"""Exercise application entry points against the real keyword-only runtime."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.app.errors import AppExecutionError
from src.app.services.llm_capability_service import LlmCapabilityService
from src.core.engines.llm.service import LlmOperationRuntime
from src.core.engines.llm.translator import TranslationError


@pytest.mark.parametrize("operation", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_translation_entrypoints_use_runtime_keyword_contract(tmp_path, operation, failure):
    translate = Mock(return_value=["translated one", "translated two"])
    if failure:
        translate.side_effect = TranslationError("translation failed")
    registry = SimpleNamespace(get=Mock(return_value=SimpleNamespace(translate_batch=translate)))
    profile = {"provider": "deepseek", "model": "chosen-model"}
    service = LlmCapabilityService(
        capability_service=Mock(), profile_builder=SimpleNamespace(build=Mock(return_value=profile)),
        runtime=LlmOperationRuntime(registry=registry),
    )
    output = tmp_path / "translated.txt"

    def run():
        common = dict(source_lang="ja", target_lang="en", output_path=str(output))
        if operation:
            return service.run_operation(operation="translate", content="one\n\ntwo", **common)
        return service.translate_texts(texts=["one", "two"], **common)

    if failure:
        with pytest.raises(AppExecutionError, match="translation failed"):
            run()
        assert not output.exists()
    else:
        run()
        assert output.read_text(encoding="utf-8") == "translated one\ntranslated two"
    translate.assert_called_once_with(["one", "two"], source_lang="ja", target_lang="en")
