"""Dependency-only models stay installable without becoming standalone choices."""

from unittest.mock import MagicMock

from src.api.http.routes.models import list_models
from src.app.services.model_service import ModelService as AppModelService
from src.core.resources.model_catalog import ModelCatalog


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
