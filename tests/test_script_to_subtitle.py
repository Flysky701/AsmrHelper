"""
Tests for ScriptToSubtitleTool
"""

import pytest
from pathlib import Path

from src.core.script_to_subtitle import ScriptToSubtitleTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_SCRIPT = """\
・タイトル（決定稿）
まっしろの部屋で

登場人物
・ゆり
・あかり

あらすじ
二人が部屋で話している。

（以下、台本）
＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝

ゆり：おはよう、あかり。
あかり：おはよう、ゆり。
（ドアが開く音）
ゆり：今日はいい天気だね。
あかり：そうだね、お出かけしよう。

（第一話　終わり）
"""

SAMPLE_SCRIPT_WITH_ACTIONS = """\
ゆり：（小声で）おはよう、あかり。
あかり：【伸びをしながら】おはよう、ゆり。
"""


@pytest.fixture
def tmp_txt_file(tmp_path: Path):
    path = tmp_path / "script.txt"
    path.write_text(SAMPLE_SCRIPT, encoding="utf-8")
    return path


@pytest.fixture
def tmp_output_path(tmp_path: Path):
    return tmp_path / "output.srt"


# ---------------------------------------------------------------------------
# load_script
# ---------------------------------------------------------------------------

def test_load_script_txt(tmp_txt_file: Path):
    text = ScriptToSubtitleTool.load_script(tmp_txt_file)
    assert "ゆり：おはよう、あかり。" in text
    assert "あかり：おはよう、ゆり。" in text


def test_load_script_file_not_found():
    with pytest.raises(FileNotFoundError):
        ScriptToSubtitleTool.load_script("/nonexistent/path/script.txt")


def test_load_script_unsupported_format(tmp_path: Path):
    path = tmp_path / "script.docx"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的文件格式"):
        ScriptToSubtitleTool.load_script(path)


# ---------------------------------------------------------------------------
# clean_script
# ---------------------------------------------------------------------------

def test_clean_script_removes_metadata():
    cleaned = ScriptToSubtitleTool.clean_script(SAMPLE_SCRIPT)
    assert "登場人物" not in cleaned
    assert "あらすじ" not in cleaned
    assert "・タイトル" not in cleaned
    assert "（以下、台本）" not in cleaned
    assert "まっしろの部屋で" not in cleaned


def test_clean_script_keeps_dialogue():
    cleaned = ScriptToSubtitleTool.clean_script(SAMPLE_SCRIPT)
    assert "おはよう、あかり。" in cleaned
    assert "おはよう、ゆり。" in cleaned
    assert "今日はいい天気だね。" in cleaned
    assert "そうだね、お出かけしよう。" in cleaned


def test_clean_script_removes_actions_by_default():
    cleaned = ScriptToSubtitleTool.clean_script(SAMPLE_SCRIPT)
    assert "（ドアが開く音）" not in cleaned


def test_clean_script_include_character():
    cleaned = ScriptToSubtitleTool.clean_script(
        SAMPLE_SCRIPT, options={"include_character": True}
    )
    assert "ゆり：" in cleaned
    assert "あかり：" in cleaned


def test_clean_script_keep_actions():
    cleaned = ScriptToSubtitleTool.clean_script(
        SAMPLE_SCRIPT_WITH_ACTIONS, options={"filter_actions": False}
    )
    assert "小声で" in cleaned or "伸びをしながら" in cleaned


# ---------------------------------------------------------------------------
# align_with_asr
# ---------------------------------------------------------------------------

def test_align_with_asr_fallback_when_empty():
    clean_text = "今日はいい天気だね。そうだね。"
    entries = ScriptToSubtitleTool.align_with_asr(
        clean_text, [], total_duration=10.0
    )
    assert len(entries) == 2
    assert entries[0]["text"] == "今日はいい天気だね"
    assert entries[1]["text"] == "そうだね"
    assert entries[-1]["end"] <= 10.0


def test_align_with_asr_with_results():
    clean_text = "おはよう。こんにちは。"
    asr_results = [
        {"start": 0.0, "end": 2.0, "text": "おはよう"},
        {"start": 2.5, "end": 4.5, "text": "こんにちは"},
    ]
    entries = ScriptToSubtitleTool.align_with_asr(
        clean_text, asr_results, total_duration=5.0
    )
    assert len(entries) == 2
    assert entries[0]["start"] == 0.0
    assert entries[1]["start"] == 2.5


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

def test_save_srt(tmp_path: Path):
    entries = [
        {"start": 1.0, "end": 3.5, "text": "Hello world"},
        {"start": 4.0, "end": 6.0, "text": "Second line"},
    ]
    output = tmp_path / "test.srt"
    ScriptToSubtitleTool.save(entries, output, fmt="srt")
    content = output.read_text(encoding="utf-8")
    assert "1" in content
    assert "00:00:01,000 --> 00:00:03,500" in content
    assert "Hello world" in content
    assert "Second line" in content


def test_save_vtt(tmp_path: Path):
    entries = [
        {"start": 0.5, "end": 2.0, "text": "VTT test"},
    ]
    output = tmp_path / "test.vtt"
    ScriptToSubtitleTool.save(entries, output, fmt="vtt")
    content = output.read_text(encoding="utf-8")
    assert "WEBVTT" in content
    assert "00:00:00.500 --> 00:00:02.000" in content
    assert "VTT test" in content


def test_save_lrc(tmp_path: Path):
    entries = [
        {"start": 65.432, "end": 70.0, "text": "LRC test"},
    ]
    output = tmp_path / "test.lrc"
    ScriptToSubtitleTool.save(entries, output, fmt="lrc")
    content = output.read_text(encoding="utf-8")
    assert "[01:05.432]LRC test" in content


# ---------------------------------------------------------------------------
# process (one-shot)
# ---------------------------------------------------------------------------

def test_process_without_asr(tmp_txt_file: Path, tmp_output_path: Path):
    entries = ScriptToSubtitleTool.process(
        source=tmp_txt_file,
        asr_results=[],
        total_duration=20.0,
        output_path=tmp_output_path,
        fmt="srt",
    )
    assert len(entries) > 0
    assert tmp_output_path.exists()
    content = tmp_output_path.read_text(encoding="utf-8")
    assert "-->" in content


def test_process_with_asr(tmp_txt_file: Path, tmp_output_path: Path):
    asr_results = [
        {"start": 0.0, "end": 2.0, "text": "おはようあかり"},
        {"start": 2.0, "end": 4.0, "text": "おはようゆり"},
        {"start": 5.0, "end": 7.0, "text": "今日はいい天気だね"},
        {"start": 7.0, "end": 9.0, "text": "そうだねお出かけしよう"},
    ]
    entries = ScriptToSubtitleTool.process(
        source=tmp_txt_file,
        asr_results=asr_results,
        total_duration=10.0,
        output_path=tmp_output_path,
        fmt="srt",
    )
    assert len(entries) >= 4
    assert tmp_output_path.exists()


def test_process_no_output_path(tmp_txt_file: Path):
    entries = ScriptToSubtitleTool.process(
        source=tmp_txt_file,
        asr_results=[],
        total_duration=10.0,
    )
    assert isinstance(entries, list)
    assert len(entries) > 0
