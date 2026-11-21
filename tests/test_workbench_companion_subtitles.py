"""Workbench discovery and execution must distinguish source subtitles from translations."""

import pytest

from src.app.services.batch_run_service import BatchRunService
from src.core.sessions.catalog import InputCatalog
from src.core.subtitles.companions import discover_subtitles, inspect_subtitle, is_source_subtitle


def subtitle(path, text, end="00:00:01.000"):
    path.write_text(f"WEBVTT\n\n00:00:00.000 --> {end}\n{text}\n", encoding="utf-8")
    return path


def test_discovery_full_audio_name_and_alternate_candidate(tmp_path):
    audio = tmp_path / "录音.mp3"
    audio.write_bytes(b"audio")
    translated = subtitle(tmp_path / "录音.mp3.VTT", "这是翻译字幕")
    original = subtitle(tmp_path / "录音.vtt", "こんにちは、お元気ですか")
    assert discover_subtitles(audio) == [translated, original]
    catalog = InputCatalog()
    asset = catalog.inspect_paths([str(audio)])[0]
    assert len(catalog.discover_companions(asset.asset_id)) == 2
    assert BatchRunService._discover_companions(audio) == [str(translated), str(original)]
    assert [item["language"] for item in BatchRunService._subtitle_summaries(audio)] == ["zh", "ja"]


@pytest.mark.parametrize("text,expected", [
    ("こんにちは、お元気ですか", True),
    ("这是中文翻译，不是日语原文", False),
    ("こんにちは\n你好，这是一段翻译", False),
    ("に这是一段包含日语字符的中文翻译台词", False),
    ("12345", False),
])
def test_only_unambiguous_original_language_can_be_reused(tmp_path, text, expected):
    inspection = inspect_subtitle(subtitle(tmp_path / "audio.vtt", text))
    assert bool(is_source_subtitle(inspection, "ja")) is expected
    assert not is_source_subtitle(inspection, "auto")
