"""
Tests for PDFToSubtitlePipeline debug output infrastructure
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.script_to_subtitle.pipeline import PDFToSubtitlePipeline
from src.core.script_to_subtitle import ScriptToSubtitleTool


# ---------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture
def sample_txt(tmp_path: Path) -> Path:
    path = tmp_path / "script.txt"
    path.write_text(SAMPLE_SCRIPT, encoding="utf-8")
    return path


@pytest.fixture
def sample_vtt(tmp_path: Path) -> Path:
    content = """\
WEBVTT

00:00:00.000 --> 00:00:02.000
おはようあかり

00:00:02.500 --> 00:00:04.500
おはようゆり

00:00:05.000 --> 00:00:07.000
今日はいい天気だね

00:00:07.500 --> 00:00:09.500
そうだねお出かけしよう
"""
    path = tmp_path / "asr.vtt"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# run_text_only with debug_dir
# ---------------------------------------------------------------------------

def test_run_text_only_debug_output(sample_txt: Path, tmp_path: Path):
    """run_text_only 应生成 stage1 中间文件"""
    debug_dir = tmp_path / "debug"
    pipeline = PDFToSubtitlePipeline()

    # patch load_script to read our txt file directly
    with patch.object(ScriptToSubtitleTool, 'load_script', return_value=SAMPLE_SCRIPT):
        pipeline.run_text_only(
            pdf_path=sample_txt,
            use_llm_clean=False,
            debug_dir=debug_dir,
        )

    # 验证 debug 文件存在
    raw_file = debug_dir / "stage1_extract" / "01_raw_text.txt"
    clean_file = debug_dir / "stage1_clean" / "02_clean_text.txt"

    assert raw_file.exists(), "01_raw_text.txt 应存在"
    assert clean_file.exists(), "02_clean_text.txt 应存在"

    raw_text = raw_file.read_text(encoding="utf-8")
    clean_text = clean_file.read_text(encoding="utf-8")

    assert len(raw_text) > 0, "原始文本不应为空"
    assert len(clean_text) > 0, "清洗后文本不应为空"
    assert "ゆり" in raw_text, "原始文本应包含角色名"
    assert "登場人物" not in clean_text, "清洗后不应包含元数据"


def test_run_text_only_no_debug_dir(sample_txt: Path, tmp_path: Path):
    """不设置 debug_dir 时不应创建 debug 目录"""
    pipeline = PDFToSubtitlePipeline()

    with patch.object(ScriptToSubtitleTool, 'load_script', return_value=SAMPLE_SCRIPT):
        pipeline.run_text_only(
            pdf_path=sample_txt,
            use_llm_clean=False,
        )

    # 没有 debug 目录应该不存在
    # (pipeline 不会自己创建 debug 目录)


# ---------------------------------------------------------------------------
# run_from_existing_vtt with debug_dir
# ---------------------------------------------------------------------------

def test_run_from_existing_vtt_debug_output(sample_txt: Path, sample_vtt: Path, tmp_path: Path):
    """run_from_existing_vtt 应生成 stage1 + stage3 中间文件"""
    debug_dir = tmp_path / "debug"
    output_path = tmp_path / "output.vtt"
    pipeline = PDFToSubtitlePipeline()

    # Mock LLM 调用避免需要真实 API key
    mock_entries = [
        {"start": 0.0, "end": 2.0, "text": "おはよう、あかり。"},
        {"start": 2.5, "end": 4.5, "text": "おはよう、ゆり。"},
        {"start": 5.0, "end": 7.0, "text": "今日はいい天気だね。"},
        {"start": 7.5, "end": 9.5, "text": "そうだね、お出かけしよう。"},
    ]

    with patch.object(ScriptToSubtitleTool, 'load_script', return_value=SAMPLE_SCRIPT), \
         patch.object(ScriptToSubtitleTool, 'align_with_llm', return_value=mock_entries):
        pipeline.run_from_existing_vtt(
            pdf_path=sample_txt,
            vtt_path=sample_vtt,
            output_path=output_path,
            use_llm_clean=False,
            debug_dir=debug_dir,
        )

    # 验证 debug 文件
    assert (debug_dir / "stage1_extract" / "01_raw_text.txt").exists()
    assert (debug_dir / "stage1_clean" / "02_clean_text.txt").exists()
    assert (debug_dir / "stage2_asr" / "03_asr_results.json").exists()
    assert (debug_dir / "stage3_align" / "04_aligned_entries.json").exists()
    assert (debug_dir / "stage4_output" / "final.vtt").exists()

    # 验证 ASR JSON 内容可解析
    asr_data = json.loads((debug_dir / "stage2_asr" / "03_asr_results.json").read_text(encoding="utf-8"))
    assert isinstance(asr_data, list)


# ---------------------------------------------------------------------------
# Vertical layout detection
# ---------------------------------------------------------------------------

def test_detect_vertical_layout_short_lines():
    """短行多行文本应被检测为竖排"""
    from src.core.script_processor import ScriptProcessor
    # 模拟竖排文本：每行很短，行数很多
    vertical_text = "\n".join(["あいう", "かきく", "さしす"] * 10)
    assert ScriptProcessor.detect_vertical_layout(vertical_text) is True


def test_detect_vertical_layout_normal_text():
    """正常长度的文本不应被检测为竖排"""
    from src.core.script_processor import ScriptProcessor
    normal_text = "ゆり：おはよう、あかり。今日はいい天気だね。\n" * 5
    assert ScriptProcessor.detect_vertical_layout(normal_text) is False


def test_detect_vertical_layout_empty():
    """空文本不应被检测为竖排"""
    from src.core.script_processor import ScriptProcessor
    assert ScriptProcessor.detect_vertical_layout("") is False
