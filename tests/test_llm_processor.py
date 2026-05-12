"""
Tests for LLMProcessor with mocked LLM calls
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.script_to_subtitle.llm_processor import LLMProcessor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_translator():
    """创建 mock Translator"""
    translator = MagicMock()
    translator.model = "test-model"
    client = MagicMock()
    translator._get_client.return_value = client
    return translator, client


@pytest.fixture
def processor(mock_translator):
    """创建使用 mock translator 的 LLMProcessor"""
    translator, _ = mock_translator
    return LLMProcessor(translator=translator)


# ---------------------------------------------------------------------------
# clean_script
# ---------------------------------------------------------------------------

def test_clean_script_short_text(processor, mock_translator):
    """短文本应直接发送给 LLM"""
    _, client = mock_translator
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "おはよう、あかり。\nおはよう、ゆり。"
    client.chat.completions.create.return_value = mock_response

    result = processor.clean_script("ゆり：おはよう、あかり。\nあかり：おはよう、ゆり。")
    assert "おはよう、あかり。" in result
    assert "おはよう、ゆり。" in result


def test_clean_script_empty_text(processor):
    """空文本应直接返回空字符串"""
    assert processor.clean_script("") == ""
    assert processor.clean_script("   ") == ""


def test_clean_script_llm_failure_fallback(processor, mock_translator):
    """LLM 调用失败时应回退到原始文本"""
    _, client = mock_translator
    client.chat.completions.create.side_effect = Exception("API Error")

    original = "ゆり：おはよう、あかり。"
    result = processor.clean_script(original)
    assert result == original


def test_clean_script_with_debug_dir(processor, mock_translator, tmp_path):
    """debug_dir 应保存中间文件"""
    _, client = mock_translator
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = " cleaned output "
    client.chat.completions.create.return_value = mock_response

    debug_dir = tmp_path / "debug"
    processor.clean_script("test input text", debug_dir=debug_dir)

    assert (debug_dir / "llm_clean_short_input.txt").exists()
    assert (debug_dir / "llm_clean_short_output.txt").exists()
    assert "test input text" in (debug_dir / "llm_clean_short_input.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# _split_into_chunks
# ---------------------------------------------------------------------------

def test_split_into_chunks_short_list():
    """短列表不应被分割"""
    lines = ["line1", "line2", "line3"]
    chunks = LLMProcessor._split_into_chunks(lines, max_chars=1000)
    assert len(chunks) == 1
    assert chunks[0] == lines


def test_split_into_chunks_long_list():
    """长列表应被正确分割"""
    lines = [f"line{i}" * 10 for i in range(100)]
    chunks = LLMProcessor._split_into_chunks(lines, max_chars=200)
    assert len(chunks) > 1
    # 所有行都应被包含（考虑重叠）
    all_lines = []
    for chunk in chunks:
        all_lines.extend(chunk)
    # 原始行应该全部出现在 chunks 中
    for line in lines:
        assert line in all_lines


def test_split_into_chunks_overlap():
    """相邻块应有重叠行"""
    lines = [f"line{i}" for i in range(20)]
    chunks = LLMProcessor._split_into_chunks(lines, max_chars=100, overlap_lines=2)
    if len(chunks) > 1:
        # 第二块的开头应包含第一块的最后 2 行
        first_end = chunks[0][-2:]
        second_start = chunks[1][:2]
        assert first_end == second_start


def test_split_into_chunks_empty():
    """空列表应返回空"""
    assert LLMProcessor._split_into_chunks([]) == []


# ---------------------------------------------------------------------------
# _fallback_from_indices
# ---------------------------------------------------------------------------

def test_fallback_from_indices_with_script_lines(processor):
    """回退应返回实际台词文本"""
    script_lines = ["おはよう", "こんにちは", "さようなら"]
    entries = processor._fallback_from_indices([0, 2], script_lines)
    assert len(entries) == 2
    assert entries[0]["text"] == "おはよう"
    assert entries[1]["text"] == "さようなら"
    assert entries[0]["start"] is None
    assert entries[0]["end"] is None


def test_fallback_from_indices_without_script_lines(processor):
    """无 script_lines 时应返回空文本"""
    entries = processor._fallback_from_indices([0, 1])
    assert len(entries) == 2
    assert entries[0]["text"] == ""
    assert entries[1]["text"] == ""


# ---------------------------------------------------------------------------
# align_and_reorder
# ---------------------------------------------------------------------------

def test_align_and_reorder_no_asr(processor):
    """无 ASR 结果时应均匀分配时间轴"""
    script_lines = ["おはよう", "こんにちは"]
    entries = processor.align_and_reorder(script_lines, [])
    assert len(entries) == 2
    assert entries[0]["start"] == 0.0
    assert entries[-1]["end"] > 0


def test_align_and_reorder_empty_script(processor):
    """空台本应返回空列表"""
    entries = processor.align_and_reorder([], [{"start": 0, "end": 1, "text": "test"}])
    assert entries == []


def test_align_and_reorder_with_mock_llm(processor, mock_translator):
    """正常 LLM 响应应返回正确条目"""
    _, client = mock_translator

    # Mock LLM 返回对齐结果
    llm_response = json.dumps([
        {"script_idx": 0, "asr_idx": 0, "text": "おはよう、あかり。", "start": 0.0, "end": 2.0},
        {"script_idx": 1, "asr_idx": 1, "text": "おはよう、ゆり。", "start": 2.5, "end": 4.5},
    ], ensure_ascii=False)

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = llm_response
    client.chat.completions.create.return_value = mock_response

    script_lines = ["おはよう、あかり。", "おはよう、ゆり。"]
    asr_segments = [
        {"start": 0.0, "end": 2.0, "text": "おはようあかり"},
        {"start": 2.5, "end": 4.5, "text": "おはようゆり"},
    ]

    entries = processor.align_and_reorder(script_lines, asr_segments)
    assert len(entries) == 2
    assert entries[0]["text"] == "おはよう、あかり。"
    assert entries[0]["start"] == 0.0


def test_align_and_reorder_llm_invalid_json(processor, mock_translator):
    """LLM 返回无效 JSON 时应回退到原始台词"""
    _, client = mock_translator

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This is not JSON"
    client.chat.completions.create.return_value = mock_response

    script_lines = ["おはよう", "こんにちは"]
    asr_segments = [
        {"start": 0.0, "end": 2.0, "text": "おはよう"},
    ]

    entries = processor.align_and_reorder(script_lines, asr_segments)
    # 应该有条目（回退到原始台词 + 时间戳填充）
    assert len(entries) >= 2
    texts = [e["text"] for e in entries]
    assert "おはよう" in texts
    assert "こんにちは" in texts


# ---------------------------------------------------------------------------
# _fill_missing_timestamps
# ---------------------------------------------------------------------------

def test_fill_missing_timestamps_interpolation(processor):
    """缺失时间戳应通过线性插值填充"""
    entries = [
        {"start": 0.0, "end": 2.0, "text": "line1"},
        {"start": None, "end": None, "text": "line2"},
        {"start": 6.0, "end": 8.0, "text": "line3"},
    ]
    asr_segments = []
    result = processor._fill_missing_timestamps(entries, asr_segments)
    assert len(result) == 3
    assert result[1]["start"] is not None
    assert 2.0 < result[1]["start"] < 6.0


def test_fill_missing_timestamps_all_missing(processor):
    """全部缺失时应均匀分配"""
    entries = [
        {"start": None, "end": None, "text": "line1"},
        {"start": None, "end": None, "text": "line2"},
    ]
    result = processor._fill_missing_timestamps(entries, [])
    assert len(result) == 2
    assert result[0]["start"] == 0.0
    assert result[-1]["end"] > 0


def test_fill_missing_timestamps_preserves_text(processor):
    """填充后应保留原始文本"""
    entries = [
        {"start": None, "end": None, "text": "テスト"},
    ]
    result = processor._fill_missing_timestamps(entries, [])
    assert result[0]["text"] == "テスト"


# ---------------------------------------------------------------------------
# _parse_align_response
# ---------------------------------------------------------------------------

def test_parse_align_response_valid_json(processor):
    """有效 JSON 应正确解析"""
    raw = json.dumps([
        {"script_idx": 0, "asr_idx": 0, "text": "hello", "start": 1.0, "end": 2.0},
    ])
    entries = processor._parse_align_response(raw, [0], ["hello"])
    assert len(entries) == 1
    assert entries[0]["text"] == "hello"
    assert entries[0]["start"] == 1.0


def test_parse_align_response_json_with_extra_text(processor):
    """JSON 前后有额外文字时应能提取"""
    raw = 'Here is the result: [{"script_idx": 0, "asr_idx": 0, "text": "hello", "start": 1.0, "end": 2.0}] Done.'
    entries = processor._parse_align_response(raw, [0], ["hello"])
    assert len(entries) == 1
    assert entries[0]["text"] == "hello"


def test_parse_align_response_invalid_json(processor):
    """无效 JSON 应回退到原始台词"""
    raw = "This is not JSON at all"
    script_lines = ["おはよう", "こんにちは"]
    entries = processor._parse_align_response(raw, [0, 1], script_lines)
    assert len(entries) == 2
    assert entries[0]["text"] == "おはよう"
    assert entries[1]["text"] == "こんにちは"
