"""Optional script cleaning and checked matching against real transcript anchors."""

from __future__ import annotations
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from src.core.subtitles.script_review import (
    ScriptReviewRequired,
    validate_timed_entries,
)

CLEAN_SCRIPT_SYSTEM_PROMPT = (
    "提取纯台词，每行一句。保持原文字词标点，不翻译，不改写，不添加或遗漏。只返回台词。"
)
ALIGN_SYSTEM_PROMPT = """将同语言原文台词与录音识别片段匹配。每条script恰好返回一项。
只返回JSON数组：{"script_idx":0,"asr_idx":2}。横跨相邻片段可用{"script_idx":0,"asr_indices":[2,3]}。
找不到或重复句无法确定时asr_idx为null。不要返回文本或时间，不翻译不编造。
不要让两句占用同一片段。台本可能漏读或顺序不同，录音可能有额外内容。索引用输入idx。"""


class LLMProcessor:
    BATCH_SIZE = 30

    def __init__(
        self, translator=None, debug_dir=None, progress_callback=None, allow_llm=True
    ):
        self._translator = translator
        self._debug_dir = Path(debug_dir) if debug_dir else None
        self.progress_callback = progress_callback
        self.allow_llm = allow_llm

    @property
    def translator(self):
        if self._translator is None:
            from src.config import config
            from src.core.engines.llm import get_llm_registry

            provider = config.get("api.provider") or "deepseek"
            self._translator = get_llm_registry().get(
                provider, model=config.get(f"api.{provider}_model") or "default"
            )
        return self._translator

    def clean_script(self, text, debug_dir=None):
        if not text.strip():
            return ""
        try:
            chunks = (
                self._split_into_chunks(text.split("\n"))
                if len(text) >= 4000
                else [text.split("\n")]
            )
            cleaned = []
            for chunk in chunks:
                original = "\n".join(chunk)
                result = self._call_llm(CLEAN_SCRIPT_SYSTEM_PROMPT, original).strip()
                if re.sub(r"\s+", " ", result).strip() != re.sub(r"\s+", " ", original).strip():
                    raise ValueError("清洗改变了原文")
                cleaned.append(result)
            return "\n".join(cleaned)
        except Exception:
            return (
                text  # Explicit preview confirmation precedes use of the rule result.
            )

    def align_and_reorder(self, script_lines, asr_segments):
        validate_timed_entries(asr_segments)
        if not script_lines or any(
            not isinstance(s, str) or not s.strip() for s in script_lines
        ):
            raise ValueError("确认后的台词为空")
        review = {
            "version": 1,
            "script_lines": script_lines,
            "asr_segments": asr_segments,
            "entries": [],
            "unmatched": [],
            "conflicts": [],
            "extra_asr": [],
            "timestamp_source": "transcript_segments",
            "complete": False,
        }
        items = []
        batches = self._prepare_batches(script_lines, asr_segments)
        for n, batch in enumerate(batches):
            if self.progress_callback:
                self.progress_callback(n, len(batches))
            try:
                items.extend(self._align_batch(batch, script_lines, asr_segments))
            except (ValueError, TypeError, KeyError) as exc:
                review["conflicts"].append(f"匹配批次 {n + 1}：{exc}")
                break
        seen, used = set(), set()
        for item in items:
            i = item["script_idx"]
            if i in seen:
                review["conflicts"].append(f"第 {i + 1} 句重复返回")
                continue
            seen.add(i)
            indices = item.get("asr_indices")
            if indices is None:
                indices = [] if item.get("asr_idx") is None else [item["asr_idx"]]
            if not indices:
                review["unmatched"].append({"script_idx": i, "text": script_lines[i]})
                continue
            if (
                not isinstance(indices, list)
                or any(
                    type(j) is not int or not 0 <= j < len(asr_segments)
                    for j in indices
                )
                or indices != list(range(indices[0], indices[-1] + 1))
                or used.intersection(indices)
            ):
                review["conflicts"].append(f"第 {i + 1} 句引用无效或重复的录音片段")
                continue
            a, b = asr_segments[indices[0]]["start"], asr_segments[indices[-1]]["end"]
            if any(
                item.get(key) is not None and item[key] != value
                for key, value in [("start", a), ("end", b)]
            ):
                review["conflicts"].append(f"第 {i + 1} 句返回了与录音锚点不同的时间")
                continue
            used.update(indices)
            review["entries"].append(
                {
                    "script_idx": i,
                    "asr_indices": indices,
                    "text": script_lines[i],
                    "start": a,
                    "end": b,
                    "timestamp_source": "transcript_segments",
                }
            )
        review["unmatched"].extend(
            {"script_idx": i, "text": text}
            for i, text in enumerate(script_lines)
            if i not in seen
        )
        review["extra_asr"] = [
            {"asr_idx": j, **e} for j, e in enumerate(asr_segments) if j not in used
        ]
        review["entries"].sort(key=lambda e: e["start"])
        if review["entries"]:
            try:
                validate_timed_entries(review["entries"])
            except ValueError as exc:
                review["conflicts"].append(str(exc))
        if review["unmatched"] or review["conflicts"] or review["extra_asr"]:
            raise ScriptReviewRequired(review)
        review["complete"] = True
        self.review = review
        return review["entries"]

    def _prepare_batches(self, script_lines, asr_segments, mapping=None):
        batches, current, size = [], [], 0
        for i, line in enumerate(script_lines):
            if len(line) > 3000:
                raise ValueError(f"第 {i + 1} 行过长，请在确认稿中分句")
            if current and (len(current) >= self.BATCH_SIZE or size + len(line) > 3000):
                batches.append(current)
                current, size = [], 0
            current.append(i)
            size += len(line)
        if current:
            batches.append(current)
        return batches

    def _align_batch(self, batch_indices, script_lines, asr_segments):
        if not self.allow_llm:

            def normalize(value):
                return re.sub(r"[^\w]", "", value).lower()

            parallel = len(script_lines) == len(asr_segments) and all(
                normalize(line) == normalize(asr_segments[i]["text"])
                for i, line in enumerate(script_lines)
            )
            items = []
            for i in batch_indices:
                if parallel:
                    items.append({"script_idx": i, "asr_idx": i})
                    continue
                candidates = []
                for j in range(len(asr_segments)):
                    for end in range(j + 1, min(j + 3, len(asr_segments)) + 1):
                        if normalize(script_lines[i]) == normalize(
                            "".join(e["text"] for e in asr_segments[j:end])
                        ):
                            candidates.append(list(range(j, end)))
                items.append(
                    {"script_idx": i, "asr_indices": candidates[0]}
                    if len(candidates) == 1
                    else {"script_idx": i, "asr_idx": None}
                )
            return items
        candidates = self._find_relevant_asr(batch_indices, script_lines, asr_segments)
        content = json.dumps(
            {
                "script": [{"idx": i, "text": script_lines[i]} for i in batch_indices],
                "asr": [
                    {"idx": j, "text": asr_segments[j]["text"]} for j in candidates
                ],
            },
            ensure_ascii=False,
        )
        if len(content) > 20000:
            raise ValueError("匹配上下文过长，请缩小台本章节或先分句")
        items = self._parse_align_response(
            self._call_llm(ALIGN_SYSTEM_PROMPT, content), batch_indices, script_lines
        )
        for item in items:
            indices = item.get("asr_indices")
            if indices is None:
                indices = [] if item.get("asr_idx") is None else [item["asr_idx"]]
            if not isinstance(indices, list) or any(
                type(j) is not int or j not in candidates for j in indices
            ):
                raise ValueError("响应引用了未提供的录音片段")
        return items

    def _find_relevant_asr(self, batch_indices, script_lines, asr_segments):
        candidates = set()
        for i in batch_indices:
            source = self._normalize_for_match(script_lines[i])
            scored = [
                (
                    SequenceMatcher(
                        None, source, self._normalize_for_match(e["text"])
                    ).ratio(),
                    j,
                )
                for j, e in enumerate(asr_segments)
            ]
            for _, j in sorted(scored, reverse=True)[:3]:
                candidates.update(range(max(0, j - 1), min(len(asr_segments), j + 2)))
        return sorted(candidates)

    def _parse_align_response(self, raw, batch_indices, script_lines=None):
        try:
            match = re.fullmatch(
                r"\s*(?:```(?:json)?\s*)?(\[.*\])\s*(?:```)?\s*", raw, re.DOTALL
            )
            if not match:
                raise ValueError("响应不是JSON数组")
            items = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("响应JSON无法解析") from exc
        seen = set()
        for item in items:
            if (
                not isinstance(item, dict)
                or type(item.get("script_idx")) is not int
                or item["script_idx"] not in batch_indices
            ):
                raise ValueError("响应台词索引无效")
            i = item["script_idx"]
            if i in seen:
                raise ValueError("响应重复了台词索引")
            seen.add(i)
            if "text" in item and item["text"] != script_lines[i]:
                raise ValueError(f"第 {i + 1} 句响应改写或翻译了确认原文")
            if "asr_idx" not in item and "asr_indices" not in item:
                raise ValueError("响应缺少匹配状态")
        if seen != set(batch_indices):
            raise ValueError("响应遗漏了台词，覆盖率不足")
        return items

    @staticmethod
    def _normalize_for_match(text):
        return re.sub(r"\s+", "", text.strip()).lower()

    @staticmethod
    def _remove_char_spaces(text):
        return re.sub(r"([^\x00-\x7f]) +(?=[^\x00-\x7f])", r"\1", text)

    def _call_llm(self, system_prompt, user_content):
        response = self.translator.get_client().chat.completions.create(
            model=self.translator.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=8192,
            temperature=0.1,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str):
            raise ValueError("LLM未返回文本")
        return content.strip()

    @staticmethod
    def _split_into_chunks(lines, max_chars=3000, overlap_lines=0):
        chunks, current, size = [], [], 0
        for line in lines:
            for part in [
                line[i : i + max_chars] for i in range(0, len(line), max_chars)
            ] or [""]:
                if current and size + len(part) + 1 > max_chars:
                    chunks.append(current)
                    current, size = [], 0
                current.append(part)
                size += len(part) + 1
        if current:
            chunks.append(current)
        return chunks
