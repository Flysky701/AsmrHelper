"""
智能字幕生成器 - SubtitleGenerator

支持从 PDF 文档或纯文本提取台词，生成带时间轴的字幕文件 (SRT/VTT/LRC)
"""

import re
from typing import List, Optional
from pathlib import Path


class SubtitleGenerator:
    """智能字幕生成器 - 文本/PDF → 带时间轴字幕"""

    # 句子切分用的标点（中文 + 英文）
    SENTENCE_DELIMITERS = re.compile(
        r'[。！？.!?\n]+'
        r'|(?<=[」』》)])'  # 中文后引号也作为断句点
    )

    @staticmethod
    def generate_from_text(
        text: str,
        total_duration: float,
        fmt: str = "srt",
        lang: str = "zh"
    ) -> List[dict]:
        """
        从纯文本生成带时间轴的字幕条目

        Args:
            text: 输入文本
            total_duration: 总时长(秒)
            fmt: 输出格式 (srt/vtt/lrc)
            lang: 语言标识

        Returns:
            字幕条目列表 [{"start": s, "end": e, "text": t}, ...]
        """
        # 清理文本：去除多余空白
        text = re.sub(r'\r\n', '\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        # 按句切分
        raw_sentences = SubtitleGenerator.SENTENCE_DELIMITERS.split(text)
        sentences = [s.strip() for s in raw_sentences if s.strip()]

        if not sentences:
            return []

        # 计算每句时长比例（按字符数加权）
        char_counts = [len(s) for s in sentences]
        total_chars = sum(char_counts)

        entries = []
        current_time = 0.0

        for i, sentence in enumerate(sentences):
            # 按字数比例分配时长，每句最少 1 秒
            ratio = char_counts[i] / max(total_chars, 1)
            duration = max(ratio * total_duration, 1.0)
            start = current_time
            end = min(current_time + duration, total_duration)

            entries.append({
                "start": round(start, 3),
                "end": round(end, 3),
                "text": sentence,
            })
            current_time = end

        # 确保最后一条不超出总时长
        if entries:
            entries[-1]["end"] = min(entries[-1]["end"], total_duration)

        return entries

    @staticmethod
    def generate_from_pdf(
        pdf_path: str,
        total_duration: float,
        fmt: str = "srt",
        lang: str = "zh"
    ) -> List[dict]:
        """
        从 PDF 文档提取文本并生成带时间轴的字幕

        Args:
            pdf_path: PDF 文件路径
            total_duration: 总时长(秒)
            fmt: 输出格式
            lang: 语言标识

        Returns:
            字幕条目列表
        """
        text = SubtitleGenerator._extract_pdf_text(pdf_path)
        return SubtitleGenerator.generate_from_text(text, total_duration, fmt, lang)

    @staticmethod
    def _extract_pdf_text(pdf_path: str) -> str:
        """从 PDF 提取文本，优先使用 PyPDF2，回退到 pdfplumber"""
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        # 尝试 PyPDF2
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(path))
            pages_text = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages_text.append(page_text)
            result = "\n".join(pages_text)
            if result.strip():
                return result
        except ImportError:
            pass
        except Exception:
            pass

        # 回退到 pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(page_text)
                result = "\n".join(pages_text)
                if result.strip():
                    return result
        except ImportError:
            raise RuntimeError(
                "需要安装 PDF 处理库。请运行: uv add pypdf 或 uv add pdfplumber"
            )
        except Exception as e:
            raise RuntimeError(f"PDF 文本提取失败: {e}")

        raise RuntimeError(f"无法从 PDF 中提取文本: {pdf_path}")

    @staticmethod
    def save(entries: List[dict], output_path: str, fmt: str = "srt") -> None:
        """
        将字幕条目保存为文件

        Args:
            entries: 字幕条目列表 (由 generate_from_text/pdf 返回)
            output_path: 输出文件路径
            fmt: 输出格式 (srt/vtt/lrc)
        """
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "srt":
            lines = []
            for i, entry in enumerate(entries, 1):
                start = SubtitleGenerator._fmt_ts(entry["start"], "srt")
                end = SubtitleGenerator._fmt_ts(entry["end"], "srt")
                lines.append(f"{i}")
                lines.append(f"{start} --> {end}")
                lines.append(entry["text"])
                lines.append("")
            content = "\n".join(lines)

        elif fmt == "vtt":
            lines = ["WEBVTT", ""]
            for entry in entries:
                start = SubtitleGenerator._fmt_ts(entry["start"], "vtt")
                end = SubtitleGenerator._fmt_ts(entry["end"], "vtt")
                lines.append(f"{start} --> {end}")
                lines.append(entry["text"])
                lines.append("")
            content = "\n".join(lines)

        elif fmt == "lrc":
            lines = []
            for entry in entries:
                ms = int(entry["start"] * 1000)
                m = ms // 60000
                s = (ms % 60000) // 1000
                cs = ms % 1000
                ts = f"[{m:02d}:{s:02d}.{cs:02d}]"
                lines.append(f"{ts}{entry['text']}")
            content = "\n".join(lines)

        else:
            raise ValueError(f"不支持的格式: {fmt}，支持: srt, vtt, lrc")

        out_p.write_text(content, encoding="utf-8")

    @staticmethod
    def _fmt_ts(seconds: float, fmt: str = "srt") -> str:
        """格式化时间为 SRT 或 VTT 格式"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s_val = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        if fmt == "srt":
            return f"{h:02d}:{m:02d}:{s_val:02d},{ms:03d}"
        else:  # vtt
            return f"{h:02d}:{m:02d}:{s_val:02d}.{ms:03d}"
