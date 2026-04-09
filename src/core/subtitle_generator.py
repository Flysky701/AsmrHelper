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

    @staticmethod
    def align_text_with_asr(
        user_text: str,
        asr_results: list,
        total_duration: float,
        fmt: str = "srt",
        lang: str = "zh",
    ) -> list:
        """
        ASR 对齐模式：将用户文本与 ASR 结果进行模糊匹配，生成带真实时间轴的字幕

        Args:
            user_text: 用户提供的台词文本（按行分隔）
            asr_results: ASR 识别结果列表 [{"start": s, "end": e, "text": t}, ...]
            total_duration: 总时长(秒) - 用于尾部填充
            fmt: 输出格式
            lang: 语言标识

        Returns:
            字幕条目列表
        """
        import difflib

        # 将用户文本切分为句子列表
        user_sentences = SubtitleGenerator.SENTENCE_DELIMITERS.split(user_text)
        user_sentences = [s.strip() for s in user_sentences if s.strip()]

        if not user_sentences or not asr_results:
            # 回退到均分模式
            return SubtitleGenerator.generate_from_text(
                user_text, total_duration, fmt, lang
            )

        # 提取ASR文本用于匹配
        asr_texts = [r.get("text", "").strip() for r in asr_results]

        aligned_entries = []
        used_asr_indices = set()

        for i, sentence in enumerate(user_sentences):
            # 模糊匹配：找到最相似的ASR片段
            best_match_idx = -1
            best_ratio = 0.0

            for j, asr_text in enumerate(asr_texts):
                if j in used_asr_indices:
                    continue

                ratio = difflib.SequenceMatcher(None, sentence.lower(), asr_text.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match_idx = j

            if best_match_idx >= 0 and best_ratio >= 0.3:
                # 找到匹配的ASR片段，使用其时间戳
                asr_entry = asr_results[best_match_idx]
                start = asr_entry["start"]
                end = max(asr_entry["end"], start + 0.5)
                aligned_entries.append({
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": sentence,
                })
                used_asr_indices.add(best_match_idx)
            else:
                # 未找到匹配，使用前一条结束时间作为起点估算
                prev_end = aligned_entries[-1]["end"] if aligned_entries else 0
                char_count = len(sentence)
                est_dur = max(char_count * 0.15, 0.8)
                aligned_entries.append({
                    "start": round(prev_end, 3),
                    "end": round(prev_end + est_dur, 3),
                    "text": sentence,
                })

        # 确保不超出总时长
        if aligned_entries and aligned_entries[-1]["end"] > total_duration:
            aligned_entries[-1]["end"] = total_duration

        return aligned_entries
