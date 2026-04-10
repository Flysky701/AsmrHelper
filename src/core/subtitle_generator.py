"""
智能字幕生成器 - SubtitleGenerator

支持从 PDF 文档或纯文本提取台词，生成带时间轴的字幕文件 (SRT/VTT/LRC)

功能增强：
- Q1: PDF 多脚本自动检测与切分
- Q2: 台词中动作描述（舞台指示）的过滤/保留
- Q3: ASR 与台词的精确对齐算法 + 对齐结果预览数据
"""

import re
from typing import List, Optional, Tuple, Dict
from pathlib import Path


class SubtitleGenerator:
    """智能字幕生成器 - 文本/PDF → 带时间轴字幕"""

    # 句子切分用的标点（中文 + 英文）
    SENTENCE_DELIMITERS = re.compile(
        r'[。！？.!?\n]+'
        r'|(?<=[」』》)])'  # 中文后引号也作为断句点
    )

    # ===== Q2: 动作描述 / 舞台指示 模式 =====
    # 匹配括号内动作描述，如：（轻声笑）、【叹气】、*靠近麦克风* 等
    ACTION_PATTERNS = {
        # 圆括号动作 (...)
        "paren": re.compile(r'[（(][^)）]*[)）]'),
        # 方括号动作 [...]
        "bracket": re.compile(r'[［\[][^］\]]*[］\]]'),
        # 星号包围 *...*
        "star": re.compile(r'\*{1,3}[^*]+\*{1,3}'),
        # 日文常见的ルビ/注釈风格 〈...〉
        "angle": re.compile(r'[〈<][^〉>]*[〉>]'),
    }

    # PDF 多脚本检测用的章节标题模式
    SECTION_PATTERNS = [
        re.compile(r'^[第\s]*(\d+)\s*[話话章幕回]', re.MULTILINE),      # 第X話/章/幕/回
        re.compile(r'^(?:Chapter|SCENE|Part)\s*[\.\s]*(\d+)', re.IGNORECASE | re.MULTILINE),
        re.compile(r'^#{1,3}\s*(.+)$', re.MULTILINE),                    # Markdown 标题
        re.compile(r'^(?:【|「)([^】」]+)(?:】|」)', re.MULTILINE),       # 【标题】或 「标题」
        re.compile(r'^[^\n]{0,30}$', re.MULTILINE),                      # 短行（可能是标题）
    ]

    @staticmethod
    def filter_stage_directions(
        text: str,
        mode: str = "remove",
        keep_as_comment: bool = False,
    ) -> str:
        """
        过滤文本中的舞台指示/动作描述 (Q2)

        Args:
            text: 原始台词文本
            mode: 处理方式
                - "remove": 直接删除动作描述
                - "bracket_keep": 保留括号但清空内容，如 () → ()
                - "keep": 不做任何处理
            keep_as_comment: 是否将过滤掉的动作用注释保留（用于人工审核）

        Returns:
            清理后的文本
        """
        if mode == "keep":
            return text

        removed_parts = []

        result = text
        for pattern_name, pattern in SubtitleGenerator.ACTION_PATTERNS.items():
            matches = pattern.findall(result)
            if matches:
                removed_parts.extend(matches)
            if mode == "remove":
                result = pattern.sub('', result)
            elif mode == "bracket_keep":
                # 只保留外层括号，清空内容
                result = pattern.sub(
                    lambda m: m.group()[0] + m.group()[-1]
                    if len(m.group()) >= 2 else ''
                    , result
                )

        # 清理多余空白：连续空格合并、去除首尾空格
        result = re.sub(r'[ \t]{2,}', ' ', result)
        result = re.sub(r'\n[ \t]*\n+', '\n\n', result)

        return result

    @staticmethod
    def extract_action_descriptions(text: str) -> List[Dict]:
        """
        提取所有动作描述及其位置信息 (Q2 辅助方法)

        Returns:
            [{"type": "paren", "text": "(轻声)", "start": pos, "end": pos}, ...]
        """
        actions = []
        for name, pattern in SubtitleGenerator.ACTION_PATTERNS.items():
            for m in pattern.finditer(text):
                actions.append({
                    "type": name,
                    "text": m.group(),
                    "start": m.start(),
                    "end": m.end(),
                })
        # 按出现位置排序
        actions.sort(key=lambda x: x["start"])
        return actions

    # ==================== Q1: PDF 多脚本处理 ====================

    @staticmethod
    def extract_pdf_scripts(pdf_path: str) -> List[Dict]:
        """
        从 PDF 中提取并检测多个脚本章节 (Q1)

        自动识别同一 PDF 中的多个独立脚本（如不同章节/角色/场景），
        返回每个脚本的元信息供用户选择。

        Args:
            pdf_path: PDF 文件路径

        Returns:
            脚本列表: [{"index": i, "title": "第1話", "text": "...", "page_start": n}, ...]
        """
        raw_text, page_texts = SubtitleGenerator._extract_pdf_text_with_pages(pdf_path)

        # 策略1: 检测明显的章节标题分隔
        sections = SubtitleGenerator._detect_sections_from_text(raw_text, page_texts)

        if len(sections) <= 1:
            # 只有一个脚本或无法分割
            return [{
                "index": 0,
                "title": Path(pdf_path).stem,
                "text": raw_text,
                "page_start": 0,
                "page_end": len(page_texts),
            }]

        return sections

    @staticmethod
    def _detect_sections_from_text(
        full_text: str,
        page_texts: List[str],
    ) -> List[Dict]:
        """
        从完整文本中检测多个脚本章节

        检测策略（按优先级）：
        1. 明确的章节标记：第X話/Chapter X/# 标题等
        2. 长空行间隔（>2个空行可能表示章节分隔）
        3. 页面级分割（用户可手动选择页面范围）
        """
        sections = []

        # --- 策略1: 正则匹配章节标题 ---
        # 收集所有可能的章节边界位置
        boundaries = []  # [(position, title)]

        # 第X話/章/幕
        for m in re.finditer(r'^[第\s]*(\d+)[\s\-\.]*[話话章幕回][\s:：]*(.*)$', full_text, re.MULTILINE):
            title = (m.group(1) + m.group(2)).strip()
            if not title:
                title = f"第{m.group(1)}話"
            boundaries.append((m.start(), title))

        # Chapter/Scene
        for m in re.finditer(r'^(Chapter|SCENE|Part)\s*[\.\s]*(\d+)[:\s]*(.*)$', full_text, re.IGNORECASE | re.MULTILINE):
            title = f"{m.group(1)} {m.group(2)}".strip()
            rest = m.group(3).strip()
            if rest:
                title += f" - {rest}"
            boundaries.append((m.start(), title))

        # 【标题】格式
        for m in re.finditer(r'^【([^】]+)】', full_text, re.MULTILINE):
            boundaries.append((m.start(), m.group(1)))

        # Markdown 标题 ## xxx
        for m in re.finditer(r'^#{1,3}\s+(.+)$', full_text, re.MULTILINE):
            boundaries.append((m.start(), m.group(1).strip()))

        # 去重排序
        boundaries.sort(key=lambda x: x[0])

        if not boundaries:
            # --- 策略2: 按长空行/页面分割 ---
            # 检测是否有超过 3 个连续空行的段落
            long_gap_pattern = re.compile(r'\n{4,}')
            gap_matches = list(long_gap_pattern.finditer(full_text))

            if len(gap_matches) >= 1:
                # 用长空行作为分隔符
                positions = [0] + [m.end() for m in gap_matches] + [len(full_text)]
                titles = [f"脚本 {i+1}" for i in range(len(positions) - 1)]
                boundaries = list(zip(positions[:-1], titles))
            elif len(page_texts) > 5:
                # 多页 PDF 但无明确章节 -> 每几页一个脚本
                pages_per_section = max(3, len(page_texts) // 3)
                for start_idx in range(0, len(page_texts), pages_per_section):
                    end_idx = min(start_idx + pages_per_section, len(page_texts))
                    sections.append({
                        "index": len(sections),
                        "title": f"P.{start_idx+1}-{end_idx}",
                        # 合并该范围内的页面文本
                        "text": "\n".join(page_texts[start_idx:end_idx]),
                        "page_start": start_idx,
                        "page_end": end_idx - 1,
                    })
                return sections
            else:
                # 无法分割
                return [{"index": 0, "title": "全文", "text": full_text, "page_start": 0, "page_end": len(page_texts) - 1}]

        # 构建章节列表
        for idx, (pos, title) in enumerate(boundaries):
            end_pos = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(full_text)
            section_text = full_text[pos:end_pos].strip()

            # 计算对应页码范围
            char_count_before = sum(len(page_texts[j]) for j in range(min(pos // 100, len(page_texts))))
            page_start = min(char_count_before // 200, len(page_texts) - 1)
            page_end = min(end_pos // 200, len(page_texts) - 1)

            if section_text:  # 排除空章节
                sections.append({
                    "index": len(sections),
                    "title": title,
                    "text": section_text,
                    "page_start": page_start,
                    "page_end": page_end,
                })

        return sections

    @staticmethod
    def _extract_pdf_text_with_pages(pdf_path: str) -> Tuple[str, List[str]]:
        """从 PDF 提取文本，返回 (全部文本, [每页文本列表])"""
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(path))
            pages_text = []
            for page in reader.pages:
                pt = page.extract_text()
                pages_text.append(pt if pt else "")
            result = "\n\n".join(pt for pt in pages_text if pt.strip())
            if result.strip():
                return result, pages_text
        except ImportError:
            pass
        except Exception:
            pass

        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    pt = page.extract_text()
                    pages_text.append(pt if pt else "")
                result = "\n\n".join(pt for pt in pages_text if pt.strip())
                if result.strip():
                    return result, pages_text
        except ImportError:
            raise RuntimeError("需要安装 PDF 处理库。请运行: uv add pypdf 或 uv add pdfplumber")
        except Exception as e:
            raise RuntimeError(f"PDF 文本提取失败: {e}")

        raise RuntimeError(f"无法从 PDF 中提取文本: {pdf_path}")

    # ==================== 字幕生成核心 ====================

    @staticmethod
    def generate_from_text(
        text: str,
        total_duration: float,
        fmt: str = "srt",
        lang: str = "zh",
        filter_actions: bool = True,
        action_mode: str = "remove",
    ) -> List[dict]:
        """
        从纯文本生成带时间轴的字幕条目

        Args:
            text: 输入文本
            total_duration: 总时长(秒)
            fmt: 输出格式 (srt/vtt/lrc)
            lang: 语言标识
            filter_actions: 是否过滤动作描述 (Q2)
            action_mode: 动作描述处理方式 ("remove"|"bracket_keep"|"keep")

        Returns:
            字幕条目列表 [{"start": s, "end": e, "text": t}, ...]
        """
        # Q2: 过滤动作描述
        if filter_actions and action_mode != "keep":
            text = SubtitleGenerator.filter_stage_directions(text, mode=action_mode)

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

        if entries:
            entries[-1]["end"] = min(entries[-1]["end"], total_duration)

        return entries

    @staticmethod
    def generate_from_pdf(
        pdf_path: str,
        total_duration: float,
        fmt: str = "srt",
        lang: str = "zh",
        script_index: int = 0,
        filter_actions: bool = True,
        action_mode: str = "remove",
    ) -> List[dict]:
        """
        从 PDF 文档提取文本并生成带时间轴的字幕 (Q1 增强)

        Args:
            pdf_path: PDF 文件路径
            total_duration: 总时长(秒)
            fmt: 输出格式
            lang: 语言标识
            script_index: 选择哪个脚本（Q1 多脚本时）
            filter_actions: 是否过滤动作描述
            action_mode: 动作描述处理方式
        """
        scripts = SubtitleGenerator.extract_pdf_scripts(pdf_path)
        if not scripts:
            raise RuntimeError(f"PDF 中未能提取到任何脚本内容")

        if script_index >= len(scripts):
            script_index = 0

        selected_script = scripts[script_index]
        text = selected_script["text"]

        return SubtitleGenerator.generate_from_text(
            text=text,
            total_duration=total_duration,
            fmt=fmt,
            lang=lang,
            filter_actions=filter_actions,
            action_mode=action_mode,
        )

    @staticmethod
    def _extract_pdf_text(pdf_path: str) -> str:
        """从 PDF 提取纯文本 (兼容旧接口)"""
        text, _ = SubtitleGenerator._extract_pdf_text_with_pages(pdf_path)
        return text

    # ==================== Q3: ASR 精确对齐 ====================

    @staticmethod
    def _normalize_for_match(text: str, lang: str = "ja") -> str:
        """
        文本归一化预处理 (Q3 对齐优化)
        
        统一字符宽度、大小写、标点符号，提升匹配精度
        """
        import unicodedata
        # NFC 规范化
        text = unicodedata.normalize('NFC', text)
        # 全角→半角（仅 ASCII 范围）
        text = text.translate(str.maketrans(
            ''.join(chr(i) for i in range(0xFF01, 0xFF5F)),
            ''.join(chr(i) for i in range(0x21, 0x7F)),
        ))
        # 统一空格
        text = re.sub(r'\s+', ' ', text)
        # 去除首尾空格
        text = text.strip().lower()
        return text

    @staticmethod
    def _compute_ngram_similarity(s1: str, s2: str, n: int = 2) -> float:
        """
        N-Gram 相似度计算 (Q3 对齐优化)
        
        比 SequenceMatcher 更适合短文本和含噪声的ASR结果
        """
        if not s1 or not s2:
            return 0.0

        def _ngrams(text, n):
            return set(text[i:i+n] for i in range(len(text) - n + 1)) if len(text) >= n else {text}

        ng1 = _ngrams(s1, n)
        ng2 = _ngrams(s2, n)
        if not ng1 or not ng2:
            return 0.0
        intersection = ng1 & ng2
        union = ng1 | ng2
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def align_text_with_asr(
        user_text: str,
        asr_results: list,
        total_duration: float,
        fmt: str = "srt",
        lang: str = "zh",
        filter_actions: bool = True,
        action_mode: str = "remove",
        return_alignment_info: bool = False,
    ) -> list:
        """
        ASR 对齐模式：将用户文本与 ASR 结果进行精确匹配 (Q3 重构)

        改进点：
        - 双重匹配策略: SequenceMatcher + N-Gram
        - 位置一致性约束：优先匹配相邻位置的 ASR 片段
        - 归一化预处理消除噪音差异
        - 可选返回对齐详情供 GUI 展示预览表

        Args:
            user_text: 用户提供的台词文本
            asr_results: ASR 识别结果 [{"start": s, "end": e, "text": t}, ...]
            total_duration: 总时长(秒)
            fmt: 输出格式
            lang: 语言标识
            filter_actions: 是否过滤动作描述
            action_mode: 动作描述处理方式
            return_alignment_info: 是否在 entry 中附加 _align 元数据

        Returns:
            字幕条目列表 (可选带 _align 字段)
        """
        import difflib

        # Q2: 过滤动作描述后再切分
        if filter_actions and action_mode != "keep":
            user_text = SubtitleGenerator.filter_stage_directions(user_text, mode=action_mode)

        user_sentences = SubtitleGenerator.SENTENCE_DELIMITERS.split(user_text)
        user_sentences = [s.strip() for s in user_sentences if s.strip()]

        if not user_sentences or not asr_results:
            return SubtitleGenerator.generate_from_text(
                user_text, total_duration, fmt, lang
            )

        # 归一化所有文本用于匹配
        norm_user = [SubtitleGenerator._normalize_for_match(s, lang) for s in user_sentences]
        norm_asr_raw = [r.get("text", "").strip() for r in asr_results]
        norm_asr = [SubtitleGenerator._normalize_for_match(t, lang) for t in norm_asr_raw]

        aligned_entries = []
        used_asr_indices = set()

        # 窗口大小：限制每个句子最多向前看 N 个 ASR 片段
        window_size = max(5, len(norm_asr) // len(user_sentences) + 2)

        for i, (sentence, norm_sent) in enumerate(zip(user_sentences, norm_user)):
            best_match_idx = -1
            best_score = 0.0
            best_method = ""

            # 确定搜索范围（基于位置一致性）
            last_used = max(used_asr_indices) if used_asr_indices else -1
            search_start = max(0, last_used - 1)  # 允许少量回溯
            search_end = min(len(norm_asr), search_start + window_size + 3)

            for j in range(search_start, search_end):
                if j in used_asr_indices:
                    continue

                asr_norm = norm_asr[j]

                # 策略1: N-Gram相似度（对短文本更稳定）
                ngram_sim = SubtitleGenerator._compute_ngram_similarity(norm_sent, asr_norm, n=2)

                # 策略2: SequenceMatcher（长文本更准确）
                seq_ratio = difflib.SequenceMatcher(None, norm_sent, asr_norm).ratio()

                # 加权综合得分（N-Gram 权重更高因为ASR常有噪音）
                combined = ngram_sim * 0.6 + seq_ratio * 0.4

                # 位置奖励：距离上次匹配越近越加分
                dist_penalty = 1.0
                if used_asr_indices:
                    last_pos = max(used_asr_indices)
                    dist = abs(j - last_pos)
                    if dist <= 2:
                        dist_penalty = 1.0          # 紧邻不惩罚
                    elif dist <= 5:
                        dist_penalty = 0.95         # 近邻微调
                    else:
                        dist_penalty = max(0.7, 1.0 - dist * 0.02)  # 远距离衰减

                final_score = combined * dist_penalty

                if final_score > best_score:
                    best_score = final_score
                    best_match_idx = j
                    best_method = f"ngram={ngram_sim:.2f}/seq={seq_ratio:.2f}"

            # 阈值判断（比原来 0.3 更严格）
            MIN_MATCH_THRESHOLD = 0.25

            if best_match_idx >= 0 and best_score >= MIN_MATCH_THRESHOLD:
                asr_entry = asr_results[best_match_idx]
                start = asr_entry["start"]
                end = max(asr_entry["end"], start + 0.5)

                entry = {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": sentence,
                }

                if return_alignment_info:
                    entry["_align"] = {
                        "asr_index": best_match_idx,
                        "asr_text": norm_asr_raw[best_match_idx],
                        "score": round(best_score, 3),
                        "method": best_method,
                        "confidence": "high" if best_score > 0.6 else "medium" if best_score > 0.4 else "low",
                    }

                aligned_entries.append(entry)
                used_asr_indices.add(best_match_idx)
            else:
                # 未找到匹配，使用前一条结束时间估算
                prev_end = aligned_entries[-1]["end"] if aligned_entries else 0
                char_count = len(sentence)
                est_dur = max(char_count * 0.15, 0.8)

                entry = {
                    "start": round(prev_end, 3),
                    "end": round(prev_end + est_dur, 3),
                    "text": sentence,
                }
                if return_alignment_info:
                    entry["_align"] = {
                        "asr_index": -1,
                        "asr_text": "",
                        "score": 0.0,
                        "method": "estimated",
                        "confidence": "none",
                    }
                aligned_entries.append(entry)

        if aligned_entries and aligned_entries[-1]["end"] > total_duration:
            aligned_entries[-1]["end"] = total_duration

        return aligned_entries

    # ==================== 文件保存 ====================

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
