from __future__ import annotations


import pytest


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("auto", "Auto"),
        ("zh-CN", "Chinese"),
        ("zh-TW", "Chinese"),
        ("ja", "Japanese"),
        ("English", "English"),
        ("pt_BR", "Portuguese"),
    ],
)
def test_qwen_language_mapping(language: str, expected: str) -> None:
    from src.core.tts import normalize_qwen3_language

    assert normalize_qwen3_language(language) == expected


def test_qwen_language_mapping_rejects_unsupported_language() -> None:
    from src.core.tts import normalize_qwen3_language

    with pytest.raises(ValueError, match="does not support language"):
        normalize_qwen3_language("th")


def test_qwen_voice_list_reports_native_languages() -> None:
    from src.core.speech.qwen_catalog import list_qwen_voices

    languages = {voice["id"]: voice["language"] for voice in list_qwen_voices()}

    assert languages["Ryan"] == "en"
    assert languages["Aiden"] == "en"
    assert languages["Ono_Anna"] == "ja"
    assert languages["Sohee"] == "ko"
    assert languages["Vivian"] == "zh"
