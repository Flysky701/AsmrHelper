"""Tests for the consolidated subtitle domain (core/subtitles/).

Verifies that migrated modules work correctly from their new canonical locations.
"""

from __future__ import annotations

import pytest


class TestSubtitleCleaner:
    """Test SubtitleCleaner from its canonical location."""

    def test_import_from_canonical_path(self):
        from src.core.subtitles.cleaner import SubtitleCleaner, CleanerConfig, clean_subtitle_text
        assert SubtitleCleaner is not None
        assert CleanerConfig is not None
        assert callable(clean_subtitle_text)

    def test_clean_sound_effects(self):
        from src.core.subtitles import clean_subtitle_text
        result = clean_subtitle_text("嘻嘻嘻 大家好呀")
        assert "嘻嘻嘻" not in result
        assert "大家好呀" in result

    def test_clean_speaker_names(self):
        from src.core.subtitles import clean_subtitle_text
        result = clean_subtitle_text("主播：大家好呀")
        assert "主播" not in result
        assert "大家好呀" in result

    def test_clean_action_onomatopoeia(self):
        from src.core.subtitles import SubtitleCleaner
        cleaner = SubtitleCleaner()
        result = cleaner.clean("撸啊撸啊撸啊撸")
        assert result == ""

    def test_clean_moaning(self):
        from src.core.subtitles import SubtitleCleaner
        cleaner = SubtitleCleaner()
        result = cleaner.clean("啊~...")
        assert result == ""

    def test_batch_clean(self):
        from src.core.subtitles import clean_subtitle_batch
        texts = ["嘻嘻嘻", "大家好", "哈哈哈哈"]
        results = clean_subtitle_batch(texts)
        assert results[0] == ""
        assert results[1] == "大家好"
        assert results[2] == ""


class TestSubtitleGenerator:
    """Test SubtitleGenerator from its canonical location."""

    def test_import_from_canonical_path(self):
        from src.core.subtitles.generator import SubtitleGenerator
        assert SubtitleGenerator is not None

    def test_import_from_package(self):
        from src.core.subtitles import SubtitleGenerator
        assert SubtitleGenerator is not None

    def test_generate_from_text(self):
        from src.core.subtitles import SubtitleGenerator
        entries = SubtitleGenerator.generate_from_text(
            text="你好世界。这是测试。",
            total_duration=10.0,
        )
        assert len(entries) >= 2
        assert entries[0]["start"] == 0.0
        assert entries[-1]["end"] <= 10.0
        assert all("text" in e for e in entries)

    def test_filter_stage_directions(self):
        from src.core.subtitles import SubtitleGenerator
        result = SubtitleGenerator.filter_stage_directions(
            "（轻声笑）你好呀", mode="remove"
        )
        assert "轻声笑" not in result
        assert "你好呀" in result

    def test_save_srt(self, tmp_path):
        from src.core.subtitles import SubtitleGenerator
        entries = [
            {"start": 0.0, "end": 1.5, "text": "hello"},
            {"start": 1.5, "end": 3.0, "text": "world"},
        ]
        output = tmp_path / "test.srt"
        SubtitleGenerator.save(entries, str(output), fmt="srt")
        content = output.read_text(encoding="utf-8")
        assert "hello" in content
        assert "-->" in content


class TestScriptProcessor:
    """Test ScriptProcessor from its canonical location."""

    def test_import_from_canonical_path(self):
        from src.core.subtitles.script_processor import ScriptProcessor
        assert ScriptProcessor is not None

    def test_import_from_package(self):
        from src.core.subtitles import ScriptProcessor
        assert ScriptProcessor is not None

    def test_detect_scripts_single(self):
        from src.core.subtitles import ScriptProcessor
        text = "角色A：你好\n角色B：世界"
        sections = ScriptProcessor.detect_scripts(text)
        assert len(sections) >= 1
        assert sections[0]["text"]

    def test_detect_scripts_multiple(self):
        from src.core.subtitles import ScriptProcessor
        text = "第1話\n台词1\n\n\n\n\n第2話\n台词2"
        sections = ScriptProcessor.detect_scripts(text)
        assert len(sections) == 2

    def test_filter_script_metadata(self):
        from src.core.subtitles import ScriptProcessor
        text = "登場人物\n・太郎\n・花子\n＝＝＝＝＝\n太郎：こんにちは"
        result = ScriptProcessor.filter_script_metadata(text)
        assert "登場人物" not in result
        assert "太郎：こんにちは" in result

    def test_detect_vertical_layout_horizontal(self):
        from src.core.subtitles import ScriptProcessor
        text = "これは普通の横書きテキストです。\n二行目もあります。\n三行目です。"
        assert ScriptProcessor.detect_vertical_layout(text) is False

    def test_extract_dialogue(self):
        from src.core.subtitles import ScriptProcessor
        text = "太郎：こんにちは\n花子：元気？"
        entries = ScriptProcessor.extract_dialogue(text)
        assert len(entries) >= 1


class TestSubtitleLoader:
    """Test subtitle loading functions from canonical location."""

    def test_load_srt_translations(self, tmp_path):
        from src.core.subtitles import load_srt_translations
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nworld\n",
            encoding="utf-8",
        )
        result = load_srt_translations(str(srt_file))
        assert result == ["hello", "world"]

    def test_load_vtt_translations(self, tmp_path):
        from src.core.subtitles import load_vtt_translations
        vtt_file = tmp_path / "test.vtt"
        vtt_file.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n\n"
            "00:00:01.000 --> 00:00:02.000\nworld\n",
            encoding="utf-8",
        )
        result = load_vtt_translations(str(vtt_file))
        assert result == ["hello", "world"]

    def test_load_subtitle_with_timestamps(self, tmp_path):
        from src.core.subtitles import load_subtitle_with_timestamps
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(
            "1\n00:00:00,000 --> 00:00:01,500\nhello\n\n"
            "2\n00:00:01,500 --> 00:00:03,000\nworld\n",
            encoding="utf-8",
        )
        entries = load_subtitle_with_timestamps(str(srt_file))
        assert len(entries) == 2
        assert entries[0]["start"] == 0.0
        assert entries[0]["end"] == 1.5
        assert entries[0]["text"] == "hello"


class TestSubtitleWorkspaceFormats:
    """The desktop-advertised subtitle formats must work end to end."""

    def test_domain_loads_vtt_and_lrc_assets(self, tmp_path):
        from src.core.subtitles.service import SubtitleDomainService

        vtt_file = tmp_path / "captions.vtt"
        vtt_file.write_text(
            "WEBVTT\n\nfirst-cue\n00:00.000 --> 00:01.250 align:start\nhello\n\n"
            "00:01.250 --> 00:02.500\nworld\n",
            encoding="utf-8",
        )
        lrc_file = tmp_path / "captions.lrc"
        lrc_file.write_text(
            "[ar:tester]\n[00:00.00]hello\n[00:01.25]world\n",
            encoding="utf-8",
        )
        service = SubtitleDomainService()

        vtt = service.load_asset(str(vtt_file))
        lrc = service.load_asset(str(lrc_file))

        assert [(segment.start, segment.end, segment.text) for segment in vtt.document.segments] == [
            (0.0, 1.25, "hello"),
            (1.25, 2.5, "world"),
        ]
        assert [(segment.start, segment.end, segment.text) for segment in lrc.document.segments] == [
            (0.0, 1.25, "hello"),
            (1.25, 4.25, "world"),
        ]

    def test_vtt_cue_identifier_may_begin_with_note(self, tmp_path):
        from src.core.subtitles.service import SubtitleDomainService

        vtt_file = tmp_path / "identifier.vtt"
        vtt_file.write_text(
            "WEBVTT\n\nNOTEWORTHY\n00:00.000 --> 00:01.000\nkept cue\n",
            encoding="utf-8",
        )

        document = SubtitleDomainService().load_asset(str(vtt_file)).document

        assert [segment.text for segment in document.segments] == ["kept cue"]

    def test_domain_exports_reloadable_vtt_and_lrc(self, tmp_path):
        from src.core.subtitles.models import SubtitleDocument, SubtitleSegment
        from src.core.subtitles.service import SubtitleDomainService

        document = SubtitleDocument(
            segments=[
                SubtitleSegment(start=0.0, end=1.25, text="hello"),
                SubtitleSegment(start=1.25, end=2.5, text="world"),
            ]
        )
        service = SubtitleDomainService()

        for extension in ("vtt", "lrc"):
            output = tmp_path / f"export.{extension}"
            service.export_document(document, output_path=str(output))
            reloaded = service.load_asset(str(output))
            assert [segment.text for segment in reloaded.document.segments] == ["hello", "world"]

        assert (tmp_path / "export.vtt").read_text(encoding="utf-8").startswith("WEBVTT")
        assert (tmp_path / "export.lrc").read_text(encoding="utf-8").startswith("[00:00.00]")

    def test_bilingual_export_rejects_unknown_extension(self, tmp_path):
        from src.core.subtitles.exporter import SubtitleExporter

        with pytest.raises(ValueError, match="unsupported subtitle format: ass"):
            SubtitleExporter().export_bilingual_subtitle(
                [{"start": 0.0, "end": 1.0, "text": "hello", "translation": "你好"}],
                str(tmp_path / "captions.ass"),
            )


class TestDeprecationWarnings:
    """Verify that legacy modules have been removed (Phase 2 cleanup complete)."""

    def test_legacy_subtitle_generator_removed(self):
        """Legacy src.core.subtitle_generator has been deleted."""
        from pathlib import Path
        assert not Path("src/core/subtitle_generator.py").exists()

    def test_legacy_script_processor_removed(self):
        """Legacy src.core.script_processor has been deleted."""
        from pathlib import Path
        assert not Path("src/core/script_processor.py").exists()

    def test_legacy_script_to_subtitle_removed(self):
        """Legacy src.core.script_to_subtitle/ has been deleted."""
        from pathlib import Path
        assert not Path("src/core/script_to_subtitle/__init__.py").exists()
