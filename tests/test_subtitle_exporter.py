"""
SubtitleExporter 单元测试
"""
import pytest
import tempfile
import os
from pathlib import Path

from src.core.subtitle_exporter import SubtitleExporter


class TestSubtitleExporter:
    """SubtitleExporter 测试"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        # 清理
        for f in Path(tmpdir).glob("*"):
            f.unlink()
        os.rmdir(tmpdir)

    @pytest.fixture
    def sample_segments(self):
        """创建示例字幕段落"""
        return [
            {"start": 0.0, "end": 1.5, "text": "こんにちは", "translation": "你好"},
            {"start": 1.5, "end": 3.0, "text": "今日はいい天気ですね", "translation": "今天天气真好"},
            {"start": 3.0, "end": 5.0, "text": "一緒に勉強しましょう", "translation": "一起学习吧"},
        ]

    @pytest.fixture
    def exporter(self):
        """创建 SubtitleExporter 实例"""
        return SubtitleExporter()

    def test_export_srt(self, temp_dir, exporter, sample_segments):
        """测试 SRT 格式导出"""
        output_path = temp_dir / "test.srt"

        result = exporter.export_srt(sample_segments, str(output_path))
        assert result is True
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8")
        # 验证格式
        assert "1" in content  # 序号
        assert "00:00:00,000 --> 00:00:01,500" in content  # 时间轴
        assert "你好" in content  # 翻译文本
        assert "00:00:03,000 --> 00:00:05,000" in content

    def test_export_srt_bilingual(self, temp_dir, exporter, sample_segments):
        """测试 SRT 双语模式导出"""
        output_path = temp_dir / "test_bilingual.srt"

        result = exporter.export_srt(sample_segments, str(output_path), bilingual=True)
        assert result is True
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8")
        # 双语模式下应同时包含原文和译文
        assert "こんにちは" in content
        assert "你好" in content

    def test_export_vtt(self, temp_dir, exporter, sample_segments):
        """测试 VTT 格式导出"""
        output_path = temp_dir / "test.vtt"

        result = exporter.export_vtt(sample_segments, str(output_path))
        assert result is True
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8-sig")
        # 验证格式
        assert "WEBVTT" in content  # VTT 头部
        assert "00:00:00.000 --> 00:00:01.500" in content  # VTT 时间轴

    def test_export_lrc(self, temp_dir, exporter, sample_segments):
        """测试 LRC 格式导出"""
        output_path = temp_dir / "test.lrc"

        result = exporter.export_lrc(sample_segments, str(output_path))
        assert result is True
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8")
        # 验证格式
        assert "[00:00.00]" in content  # LRC 时间标签
        assert "00:00]" in content  # 后续时间标签

    def test_export_lrc_bilingual(self, temp_dir, exporter, sample_segments):
        """测试 LRC 双语模式导出"""
        output_path = temp_dir / "test_bilingual.lrc"

        result = exporter.export_lrc(sample_segments, str(output_path), bilingual=True)
        assert result is True
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8")
        # 双语模式下应有原文和译文行
        lines = content.split("\n")
        text_lines = [l for l in lines if l.strip() and not l.startswith("[")]
        assert len(text_lines) >= 2  # 至少有两行文本

    def test_export_auto_srt(self, temp_dir, exporter, sample_segments):
        """测试自动格式选择 - SRT"""
        output_path = temp_dir / "test_auto.srt"

        result = exporter.export_auto(sample_segments, str(output_path), fmt="auto")
        assert result is True
        assert output_path.exists()

    def test_export_auto_vtt(self, temp_dir, exporter, sample_segments):
        """测试自动格式选择 - VTT"""
        output_path = temp_dir / "test_auto.vtt"

        result = exporter.export_auto(sample_segments, str(output_path), fmt="auto")
        assert result is True
        assert output_path.exists()

    def test_export_auto_lrc(self, temp_dir, exporter, sample_segments):
        """测试自动格式选择 - LRC"""
        output_path = temp_dir / "test_auto.lrc"

        result = exporter.export_auto(sample_segments, str(output_path), fmt="auto")
        assert result is True
        assert output_path.exists()

    def test_export_auto_by_extension(self, temp_dir, exporter, sample_segments):
        """测试根据扩展名自动选择格式"""
        # .vtt 扩展名
        output_path_vtt = temp_dir / "test.vtt"
        result = exporter.export_auto(sample_segments, str(output_path_vtt), fmt="srt")
        assert result is True

        # .lrc 扩展名
        output_path_lrc = temp_dir / "test.lrc"
        result = exporter.export_auto(sample_segments, str(output_path_lrc), fmt="auto")
        assert result is True

    def test_format_timestamp_srt(self, exporter):
        """测试 SRT 时间戳格式化"""
        assert exporter.format_timestamp_srt(0.0) == "00:00:00,000"
        assert exporter.format_timestamp_srt(61.5) == "00:01:01,500"
        assert exporter.format_timestamp_srt(3661.123) == "01:01:01,123"
        assert exporter.format_timestamp_srt(7323.456) == "02:02:03,456"

    def test_format_timestamp_vtt(self, exporter):
        """测试 VTT 时间戳格式化"""
        assert exporter.format_timestamp_vtt(0.0) == "00:00:00.000"
        assert exporter.format_timestamp_vtt(61.5) == "00:01:01.500"
        assert exporter.format_timestamp_vtt(3661.123) == "01:01:01.123"

    def test_format_timestamp_lrc(self, exporter):
        """测试 LRC 时间戳格式化"""
        assert exporter.format_timestamp_lrc(0.0) == "00:00.00"
        assert exporter.format_timestamp_lrc(61.5) == "01:01.50"
        assert exporter.format_timestamp_lrc(125.67) == "02:05.67"

    def test_validate_segments(self, exporter):
        """测试字幕段落验证"""
        valid_segments = [
            {"start": 0.0, "end": 1.0, "text": "测试"},
            {"start": 1.0, "end": 2.0, "text": "", "translation": "有译文"},
            {"start": 2.0, "end": 3.0, "text": "有文本", "translation": "有译文"},
        ]

        invalid_segments = [
            {"start": -1.0, "end": 1.0, "text": "负数时间"},
            {"start": 2.0, "end": 1.0, "text": "结束早于开始"},
            {"start": 3.0, "end": 4.0},  # 缺少必需字段
            {"start": 4.0, "end": 5.0, "text": "", "translation": ""},  # 空文本
        ]

        all_segments = valid_segments + invalid_segments
        result = exporter.validate_segments(all_segments)

        # 应该只保留有效的段落
        assert len(result) == 3

    def test_empty_segments(self, temp_dir, exporter):
        """测试空段落列表"""
        output_path = temp_dir / "empty.srt"

        result = exporter.export_srt([], str(output_path))
        assert result is True
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == ""

    def test_segment_without_translation(self, temp_dir, exporter):
        """测试只有原文没有译文的情况"""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "のみ原文"},
        ]
        output_path = temp_dir / "no_translation.srt"

        result = exporter.export_srt(segments, str(output_path), bilingual=False)
        assert result is True

        content = output_path.read_text(encoding="utf-8")
        assert "のみ原文" in content
        assert "translation" not in content

    def test_overwrite_existing_file(self, temp_dir, exporter, sample_segments):
        """测试覆盖已存在的文件"""
        output_path = temp_dir / "overwrite.srt"

        # 第一次写入
        exporter.export_srt(sample_segments[:1], str(output_path))
        content1 = output_path.read_text(encoding="utf-8")

        # 第二次写入（覆盖）
        exporter.export_srt(sample_segments, str(output_path))
        content2 = output_path.read_text(encoding="utf-8")

        # 应该被覆盖
        assert content1 != content2
        assert len(content2) > len(content1)
