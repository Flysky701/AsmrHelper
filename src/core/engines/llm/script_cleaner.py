"""
LLM 辅助处理器

功能：
1. 台本精洗 — 从 regex 粗洗后的杂乱文本中提取纯净对话
2. ASR 对齐重排 — 将台本与 ASR 结果智能对齐，修正错字，处理顺序差异
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# ======================================================================
# Prompt 模板
# ======================================================================

CLEAN_SCRIPT_SYSTEM_PROMPT = """你是一个台本清洗专家。从 PDF 转换后的杂乱文本中提取纯净的角色对话台词。

规则：
1. 去除所有非对话内容：页码、版权信息、章节标题、旁白、动作描述（括号内容）、声效标记
2. 去除角色名前缀（如「太郎：」「[太郎]」），只保留台词本身
3. 每行一句台词，保持原文不修改，不翻译
4. 如果文本已经是干净的对话，直接返回原文
5. 输出格式：每行一句台词，用换行分隔，不要添加编号或其他标记"""

ALIGN_SYSTEM_PROMPT = """你是一个字幕对齐专家。将台本台词与 ASR 语音识别结果对齐。

输入：
- script: 台本台词列表（正确文本，无时间戳）
- asr: ASR 识别结果列表（有时间戳，但可能有错字、漏字、顺序偏差）

任务：
1. 将每条台本台词匹配到最合适的 ASR 片段
2. 用台本的正确文本替换 ASR 的错误文本
3. 保留 ASR 的时间戳（start, end）
4. 如果台本某行在 ASR 中找不到对应（被漏识别），对应字段设为 null
5. 处理可能的顺序差异（台本第3句可能对应 ASR 第5段）
6. 如果 ASR 有多余的片段（不在台本中的内容），忽略它们

输出格式：严格输出 JSON 数组，每个元素格式：
{"script_idx": 0, "asr_idx": 2, "text": "正确台词", "start": 1.23, "end": 3.45}

对于找不到 ASR 对应的台本行：
{"script_idx": 5, "asr_idx": null, "text": "台词内容", "start": null, "end": null}

不要输出任何其他内容，只输出 JSON 数组。"""


class LLMProcessor:
    """LLM 辅助处理器：台本精洗 + ASR 对齐重排"""

    # 每批发给 LLM 的最大 ASR 片段数（避免超 token 限制）
    BATCH_SIZE = 30

    def __init__(self, translator=None, debug_dir: Optional[Union[str, Path]] = None):
        """
        Args:
            translator: Translator 实例，为 None 时通过 LLM Registry 自动获取
            debug_dir: 调试输出目录（可选，设置后保存各阶段中间文件）
        """
        self._translator = translator
        self._debug_dir = Path(debug_dir) if debug_dir else None

    @property
    def translator(self):
        if self._translator is None:
            from src.config import config
            from src.core.engines.llm import get_llm_registry
            provider = config.get("api.provider") or "deepseek"
            self._translator = get_llm_registry().get(provider)
        return self._translator

    # ------------------------------------------------------------------
    # clean_script: LLM 精洗
    # ------------------------------------------------------------------

    def clean_script(self, text: str, debug_dir: Optional[Union[str, Path]] = None) -> str:
        """
        LLM 精洗：从 regex 粗洗后的文本中提取纯净对话。

        Args:
            text: regex 粗洗后的文本
            debug_dir: 调试输出目录（可选，覆盖 __init__ 中的设置）

        Returns:
            每行一句台词的纯净文本
        """
        if not text.strip():
            return ""

        dbg = Path(debug_dir) if debug_dir else self._debug_dir
        if dbg:
            dbg.mkdir(parents=True, exist_ok=True)

        try:
            # 文本较短时直接发给 LLM
            if len(text) < 4000:
                result = self._call_llm(CLEAN_SCRIPT_SYSTEM_PROMPT, text).strip()
                if dbg:
                    (dbg / "llm_clean_short_input.txt").write_text(text, encoding="utf-8")
                    (dbg / "llm_clean_short_output.txt").write_text(result, encoding="utf-8")
                return result

            # 文本较长时分段处理
            lines = text.split('\n')
            chunks = self._split_into_chunks(lines, max_chars=3000)
            results = []
            for i, chunk in enumerate(chunks):
                chunk_text = '\n'.join(chunk)
                cleaned = self._call_llm(CLEAN_SCRIPT_SYSTEM_PROMPT, chunk_text).strip()
                if dbg:
                    (dbg / f"llm_clean_chunk_{i:02d}_input.txt").write_text(chunk_text, encoding="utf-8")
                    (dbg / f"llm_clean_chunk_{i:02d}_output.txt").write_text(cleaned, encoding="utf-8")
                results.append(cleaned)
            return '\n'.join(results)
        except Exception as e:
            print(f"[LLMProcessor] LLM 清洗失败，回退到 regex 结果: {e}")
            return text

    # ------------------------------------------------------------------
    # llm_align: LLM 智能重排对齐
    # ------------------------------------------------------------------

    def align_and_reorder(
        self,
        script_lines: List[str],
        asr_segments: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        LLM 智能重排：将台本与 ASR 结果对齐，输出带时间轴的字幕。

        Args:
            script_lines: 清洗后的台本台词列表
            asr_segments: ASR 识别结果 [{"start": float, "end": float, "text": str}, ...]

        Returns:
            字幕条目 [{"start": float, "end": float, "text": str}, ...]
        """
        if not script_lines:
            return []
        if not asr_segments:
            # 无 ASR 结果，均匀分配时间轴
            return self._fallback_proportional(script_lines)

        # Step 1: 预匹配 — 用 SequenceMatcher 建立初步对应关系
        mapping = self._pre_match(script_lines, asr_segments)

        # Step 2: 分批发送给 LLM
        batches = self._prepare_batches(script_lines, asr_segments, mapping)
        all_entries = []

        for batch in batches:
            entries = self._align_batch(batch, script_lines, asr_segments)
            all_entries.extend(entries)

        # Step 3: 后处理 — 按 script_idx 排序，填充缺失的时间戳
        all_entries.sort(key=lambda e: e.get("script_idx", 0))
        all_entries = self._fill_missing_timestamps(all_entries, asr_segments)

        return all_entries

    # ------------------------------------------------------------------
    # 预匹配
    # ------------------------------------------------------------------

    def _pre_match(
        self,
        script_lines: List[str],
        asr_segments: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        用 SequenceMatcher 为每条台本行找到最相似的 ASR 片段。
        返回 mapping: [{"script_idx": i, "best_asr_idx": j, "score": float}, ...]
        """
        mapping = []
        for i, s_line in enumerate(script_lines):
            best_idx = -1
            best_score = 0.0
            s_clean = self._normalize_for_match(s_line)
            for j, asr in enumerate(asr_segments):
                a_clean = self._normalize_for_match(asr.get("text", ""))
                score = SequenceMatcher(None, s_clean, a_clean).ratio()
                if score > best_score:
                    best_score = score
                    best_idx = j
            mapping.append({
                "script_idx": i,
                "best_asr_idx": best_idx,
                "score": best_score,
            })
        return mapping

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        """归一化文本用于相似度比较"""
        text = text.strip()
        text = re.sub(r'\s+', '', text)
        text = text.lower()
        return text

    # ------------------------------------------------------------------
    # 分批策略
    # ------------------------------------------------------------------

    def _prepare_batches(
        self,
        script_lines: List[str],
        asr_segments: List[Dict[str, Any]],
        mapping: List[Dict[str, Any]],
    ) -> List[List[int]]:
        """
        将 script_lines 按 BATCH_SIZE 分批。
        返回每批包含的 script_idx 列表。
        """
        batches = []
        for start in range(0, len(script_lines), self.BATCH_SIZE):
            end = min(start + self.BATCH_SIZE, len(script_lines))
            batches.append(list(range(start, end)))
        return batches

    def _align_batch(
        self,
        batch_indices: List[int],
        script_lines: List[str],
        asr_segments: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """对一批台本行调用 LLM 对齐"""
        batch_id = batch_indices[0] // self.BATCH_SIZE

        # 构建该批的台本子集
        batch_script = [
            {"idx": i, "text": script_lines[i]}
            for i in batch_indices
        ]

        # 构建该批相关的 ASR 子集（取与这批台本最相关的 ASR 片段）
        relevant_asr_indices = self._find_relevant_asr(
            batch_indices, script_lines, asr_segments
        )
        batch_asr = [
            {"idx": j, "text": asr_segments[j]["text"],
             "start": asr_segments[j]["start"], "end": asr_segments[j]["end"]}
            for j in relevant_asr_indices
        ]

        user_content = json.dumps({
            "script": batch_script,
            "asr": batch_asr,
        }, ensure_ascii=False)

        if self._debug_dir:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
            (self._debug_dir / f"batch_{batch_id:02d}_request.json").write_text(
                user_content, encoding="utf-8"
            )

        raw = self._call_llm(ALIGN_SYSTEM_PROMPT, user_content)

        if self._debug_dir:
            (self._debug_dir / f"batch_{batch_id:02d}_response.txt").write_text(
                raw, encoding="utf-8"
            )

        return self._parse_align_response(raw, batch_indices, script_lines)

    def _find_relevant_asr(
        self,
        batch_indices: List[int],
        script_lines: List[str],
        asr_segments: List[Dict[str, Any]],
    ) -> List[int]:
        """找到与当前批次台本最相关的 ASR 片段索引"""
        # 简单策略：取与这批台本行相似度最高的 ASR 片段
        # 每条台本取 top-3 候选，去重后返回
        candidate_indices = set()
        for i in batch_indices:
            s_clean = self._normalize_for_match(script_lines[i])
            scores = []
            for j, asr in enumerate(asr_segments):
                a_clean = self._normalize_for_match(asr.get("text", ""))
                score = SequenceMatcher(None, s_clean, a_clean).ratio()
                scores.append((score, j))
            scores.sort(reverse=True)
            for _, j in scores[:3]:
                candidate_indices.add(j)

        return sorted(candidate_indices)

    # ------------------------------------------------------------------
    # 响应解析
    # ------------------------------------------------------------------

    def _parse_align_response(
        self,
        raw: str,
        batch_indices: List[int],
        script_lines: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """解析 LLM 的对齐响应 JSON"""
        # 提取 JSON 数组（LLM 可能会在 JSON 前后加多余文字）
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not json_match:
            print(f"[LLMProcessor] JSON 解析失败，回退到原始台词 (batch {batch_indices[:3]}...)")
            return self._fallback_from_indices(batch_indices, script_lines)

        try:
            items = json.loads(json_match.group())
        except json.JSONDecodeError:
            print(f"[LLMProcessor] JSON 解析失败，回退到原始台词 (batch {batch_indices[:3]}...)")
            return self._fallback_from_indices(batch_indices, script_lines)

        entries = []
        for item in items:
            text = item.get("text", "")
            start = item.get("start")
            end = item.get("end")
            if text:
                # 去除 LLM 返回的字符间多余空格（日文/中文不需要空格分隔）
                text = self._remove_char_spaces(text)
                entries.append({
                    "start": start,
                    "end": end,
                    "text": text,
                    "script_idx": item.get("script_idx"),
                    "asr_idx": item.get("asr_idx"),
                })
        return entries

    def _fallback_from_indices(
        self,
        batch_indices: List[int],
        script_lines: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """LLM 解析失败时的回退：返回无时间戳但保留原始台词的条目"""
        entries = []
        for i in batch_indices:
            text = script_lines[i] if script_lines and i < len(script_lines) else ""
            entries.append({
                "start": None, "end": None, "text": text,
                "script_idx": i, "asr_idx": None,
            })
        return entries

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------

    def _fill_missing_timestamps(
        self,
        entries: List[Dict[str, Any]],
        asr_segments: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """为缺失时间戳的条目填充估算值"""
        # 先清理内部字段，只保留 start/end/text
        result = []
        for e in entries:
            if not e.get("text"):
                continue
            result.append({
                "start": e.get("start"),
                "end": e.get("end"),
                "text": e["text"],
            })

        # 找到所有有时间戳的条目，用它们推断缺失的
        timed = [(i, e) for i, e in enumerate(result) if e["start"] is not None]
        if not timed:
            # 全部缺失，均匀分配
            return self._fallback_proportional([e["text"] for e in result])

        # 线性插值填充
        for i, e in enumerate(result):
            if e["start"] is not None:
                continue
            # 找前后最近的有时间戳的条目
            prev_timed = None
            next_timed = None
            for ti, te in timed:
                if ti < i:
                    prev_timed = (ti, te)
                elif ti > i and next_timed is None:
                    next_timed = (ti, te)
                    break

            if prev_timed and next_timed:
                # 线性插值
                pi, pt = prev_timed
                ni, nt = next_timed
                ratio = (i - pi) / (ni - pi)
                e["start"] = pt["end"] + ratio * (nt["start"] - pt["end"])
                e["end"] = e["start"] + (nt["start"] - pt["end"]) / (ni - pi)
            elif prev_timed:
                # 只有前一个，估算间隔
                pi, pt = prev_timed
                gap = 2.0  # 默认间隔
                e["start"] = pt["end"] + 0.1
                e["end"] = e["start"] + gap
            elif next_timed:
                # 只有后一个
                ni, nt = next_timed
                gap = 2.0
                e["end"] = nt["start"] - 0.1
                e["start"] = max(0, e["end"] - gap)

        return result

    def _fallback_proportional(
        self,
        lines: List[str],
        total_duration: float = 600.0,
    ) -> List[Dict[str, Any]]:
        """无 ASR 时按字符数均匀分配时间轴"""
        if not lines:
            return []
        total_chars = sum(len(line) for line in lines) or 1
        current = 0.0
        entries = []
        for line in lines:
            duration = (len(line) / total_chars) * total_duration
            entries.append({
                "start": round(current, 3),
                "end": round(current + duration, 3),
                "text": line,
            })
            current += duration
        return entries

    # ------------------------------------------------------------------
    # 文本清理
    # ------------------------------------------------------------------

    @staticmethod
    def _remove_char_spaces(text: str) -> str:
        """去除 LLM 返回的 CJK 字符间多余空格。

        LLM 对齐时有时会在每个字符之间插入空格，
        此方法去除非 ASCII 字符之间的空格，但保留拉丁文之间的空格。
        """
        if not text or ' ' not in text:
            return text

        # 非 ASCII 字符之间的空格视为多余（中日韩字符间不需要空格）
        pat = re.compile(r'([^\x00-\x7f]) +([^\x00-\x7f])')
        prev = None
        while prev != text:
            prev = text
            text = pat.sub(r'\1\2', text)
        return text

    # ------------------------------------------------------------------
    # 底层 LLM 调用
    # ------------------------------------------------------------------

    def _call_llm(self, system_prompt: str, user_content: str) -> str:
        """
        调用 LLM。

        Args:
            system_prompt: 系统提示词
            user_content: 用户输入内容

        Returns:
            LLM 响应文本
        """
        client = self.translator.get_client()
        response = client.chat.completions.create(
            model=self.translator.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=8192,
            temperature=0.1,
        )
        return response.choices[0].message.content.strip()

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _split_into_chunks(
        lines: List[str], max_chars: int = 3000, overlap_lines: int = 2
    ) -> List[List[str]]:
        """将行列表按最大字符数分块，相邻块之间有重叠行以保持上下文"""
        if not lines:
            return []

        chunks = []
        current = []
        current_len = 0
        for line in lines:
            if current_len + len(line) > max_chars and current:
                chunks.append(current)
                # 重叠：取上一块的最后 N 行作为下一块的开头
                overlap = current[-overlap_lines:] if overlap_lines > 0 else []
                current = list(overlap)
                current_len = sum(len(l) + 1 for l in current)
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append(current)
        return chunks
