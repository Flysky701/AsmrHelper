from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.api.http import dependencies
from src.api.http.app import create_app


def _mock_dep(mock_obj):
    return lambda: mock_obj


def test_list_asr_engines_exposes_fun_asr_descriptor():
    app = create_app()
    client = TestClient(app)

    mock_svc = MagicMock()
    mock_svc.list_engines.return_value = [
        {
            "category": "asr",
            "provider": "fun_asr",
            "display_name": "Fun-ASR",
            "kind": "local",
            "supported_models": ["FunAudioLLM/Fun-ASR-Nano-2512"],
            "default_model": "FunAudioLLM/Fun-ASR-Nano-2512",
            "common_option_schema": [],
            "provider_option_schema": [],
            "supports": {"sentence_timestamps": True},
        }
    ]
    app.dependency_overrides[dependencies.asr_engine_service] = _mock_dep(mock_svc)

    try:
        response = client.get("/api/v1/asr/engines")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["engines"][0]["provider"] == "fun_asr"
    assert payload["engines"][0]["supported_models"] == ["FunAudioLLM/Fun-ASR-Nano-2512"]


def test_transcribe_route_forwards_fun_asr_provider_options():
    app = create_app()
    client = TestClient(app)

    mock_svc = MagicMock()
    result_mock = MagicMock()
    result_mock.segments = [MagicMock(start=0.0, end=1.0, text="hello")]
    result_mock.output_path = None
    result_mock.text = "hello"
    mock_svc.transcribe_file.return_value = result_mock
    app.dependency_overrides[dependencies.asr_engine_service] = _mock_dep(mock_svc)

    try:
        response = client.post(
            "/api/v1/asr/transcribe",
            json={
                "input_path": "/test/audio.wav",
                "provider": "fun_asr",
                "model": "FunAudioLLM/Fun-ASR-Nano-2512",
                "language": "ja",
                "provider_options": {
                    "device": "cpu",
                    "sentence_timestamp": True,
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_svc.transcribe_file.assert_called_once_with(
        input_path="/test/audio.wav",
        output_path=None,
        provider="fun_asr",
        model="FunAudioLLM/Fun-ASR-Nano-2512",
        language="ja",
        common_options={"language": "ja"},
        provider_options={"device": "cpu", "sentence_timestamp": True},
    )
