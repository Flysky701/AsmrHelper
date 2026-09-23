"""Dependency-only models stay installable without becoming standalone choices."""

from unittest.mock import MagicMock

from src.api.http.routes.models import list_models
from src.app.services.model_service import ModelService as AppModelService
from src.core.resources.model_catalog import ModelCatalog
from src.core.resources.model_service import ModelService


def test_auxiliary_metadata_reaches_http_without_hiding_standalone_aligner():
    catalog = ModelCatalog()
    core = MagicMock()
    core.list_models.return_value = catalog.list()
    service = AppModelService(
        core_service=core,
        dispatcher=MagicMock(),
        settings_service=MagicMock(),
    )
    responses = {item.model_id: item for item in list_models(svc=service)}
    assert responses["fun-asr-fsmn-vad"].is_auxiliary is True
    assert responses["qwen3-forced-aligner-0.6b"].is_auxiliary is False
    assert responses["fun-asr-nano-2512"].is_auxiliary is False
    assert "fun-asr-fsmn-vad" in responses["fun-asr-nano-2512"].required_assets


def test_main_model_install_still_includes_hidden_dependency():
    service = ModelService(runtime_resolver=MagicMock())
    for model_id in ("fun-asr-nano-2512", "fun-asr-mlt-nano-2512"):
        plan = service._resolve_install_plan(
            service.get_model(model_id),
            install_mode="single",
            install_recommended_assets=False,
        )
        assert [entry.id for entry in plan] == [model_id, "fun-asr-fsmn-vad"]
