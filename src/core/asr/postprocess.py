"""
ASR 后处理模块 - 文本规范化与片段合并

基于 Report #14 的 ASMR ASR 后处理规范

功能：
1. 文本规范化：去除 Whisper 输出的常见问题
2. 片段合并：合并间隔<0.3s 且单段<1s 的极短片段
3. 置信度过滤：利用 log_prob 过滤低质量片段
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Segment:
    """带置信度的片段"""
    start: float
    end: float
    text: str
    log_prob: float = 0.0  # log 概率，越高越好

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),  # 毫秒级精度
            "end": round(self.end, 3),
            "text": self.text,
            "log_prob": self.log_prob,
        }


class NormalizeRules:
    """文本规范化规则"""

    # 重复标点规则 [(模式, 替换), ...]
    # 注意：这些规则在半角转半角之后执行，所以使用半角字符
    PUNCTUATION_RULES: List[Tuple[str, str]] = [
        (r'\.{2,}', '...'), # 多个点合并为省略号
        (r'\.{3,}', '...'), # 4个及以上点也合并为省略号
        (r'!+', '!'),        # 多个感叹号合并为一个
        (r'\?+', '?'),       # 多个问号合并为一个
        (r',+', ','),        # 多个逗号合并为一个
    ]

    # 全角转半角映射（包含日文标点）
    # 注意：不转换中文/日文括号（），保留原样
    FULLWIDTH_MAP = {
        '！': '!',   # U+FF01
        '？': '?',   # U+FF1F
        # '（': '(',   # 不转换中文括号
        # '）': ')',   # 不转换中文括号
        '【': '[',   # U+FF3B
        '】': ']',   # U+FF3D
        '「': '"',   # U+300C
        '」': '"',   # U+300D
        '『': "'",   # U+300E
        '』': "'",   # U+300F
        '，': ',',   # U+FF0C 全角逗号（中文/日文）
        '．': '.',   # U+FF0E 全角点
        '。': '.',   # U+3002 日文句号
    }

    # 空格规则
    SPACE_RULES = [
        (r'\s+', ''),         # 多个空格合并为一个
        (r'\n\s*\n', '\n'),   # 多余换行
    ]

    # Whisper 幻觉标记（只移除英文括号内的内容，保留中文/日文括号）
    HALLUCINATION_PATTERNS = [
        r'\[.*?\]',           # [音楽] [掌声] [笑声] 等
        r'＜.*?＞',           # <...>
        r'\(.*?\)',           # 英文括号内的非日文内容
        # 不移除中文括号（），保留其内容
    ]

    # Whisper 误识别标记（ASMR 音频中常见的误识别前缀）
    # 如 "2.全て元通り" 中的 "2." 是把语气/标点误识别为数字序号
    MISRECOGNITION_PATTERNS = [
        (r'^\d+\.\s*', ''),   # 行首数字序号: "2.文本" → "文本"
        (r'^\d+\s+', ''),     # 行首纯数字: "3 文本" → "文本"
    ]


@dataclass
class MergeConfig:
    """片段合并配置"""
    min_gap: float = 0.3       # 最小间隔（秒），小于此值考虑合并
    max_merge_duration: float = 1.0  # 合并后最大时长（秒）
    merge_threshold: float = 0.5   # 间隔超过此值不合并


@dataclass
class PostProcessConfig:
    """后处理配置"""
    enable_normalize: bool = True      # 启用文本规范化
    enable_merge: bool = True         # 启用片段合并
    enable_confidence_filter: bool = True  # 启用置信度过滤

    normalize_rules: NormalizeRules = field(default_factory=NormalizeRules)
    merge_config: MergeConfig = field(default_factory=MergeConfig)

    # 置信度过滤
    min_log_prob: float = -1.0        # log_prob 阈值，低于此值过滤


class ASRPostProcessor:
    """ASR 后处理器"""

    # 直接引用类属性，避免实例化问题
    _rules = NormalizeRules()

    def __init__(self, config: Optional[PostProcessConfig] = None):
        self.config = config or PostProcessConfig()

    def process(self, segments: List[dict]) -> List[dict]:
        """
        执行完整的后处理流程

        Args:
            segments: Whisper 输出片段 [{start, end, text, log_prob?}, ...]

        Returns:
            List[dict]: 处理后的片段
        """
        if not segments:
            return []

        # Step 1: 转换为 Segment 对象
        segs = [self._to_segment(s) for s in segments]

        # Step 2: 文本规范化
        if self.config.enable_normalize:
            segs = [self._normalize_segment(s) for s in segs]

        # Step 3: 置信度过滤
        if self.config.enable_confidence_filter:
            segs = self._filter_by_confidence(segs)

        # Step 4: 片段合并
        if self.config.enable_merge:
            segs = self._merge_segments(segs)

        # Step 5: 过滤空片段
        segs = [s for s in segs if s.text.strip()]

        # Step 6: 转换回 dict
        return [s.to_dict() for s in segs]

    def _to_segment(self, s: dict) -> Segment:
        """转换为 Segment 对象"""
        return Segment(
            start=float(s.get("start", 0)),
            end=float(s.get("end", 0)),
            text=str(s.get("text", "")),
            log_prob=float(s.get("log_prob", 0)),
        )

    def _normalize_segment(self, seg: Segment) -> Segment:
        """对单个片段进行文本规范化"""
        text = seg.text

        # Step 1: 全角转半角（优先处理，因为后续规则使用半角模式）
        for full, half in self._rules.FULLWIDTH_MAP.items():
            text = text.replace(full, half)

        # Step 2: 去除幻觉标记
        for pattern in self._rules.HALLUCINATION_PATTERNS:
            text = re.sub(pattern, '', text)

        # Step 2.5: 去除误识别标记（如行首数字序号 "2.文本" → "文本"）
        for pattern, replacement in self._rules.MISRECOGNITION_PATTERNS:
            text = re.sub(pattern, replacement, text)

        # Step 3: 重复标点
        for pattern, replacement in self._rules.PUNCTUATION_RULES:
            text = re.sub(pattern, replacement, text)

        # Step 4: 空格处理
        for pattern, replacement in self._rules.SPACE_RULES:
            text = re.sub(pattern, replacement, text)

        # Step 5: 去除首尾空白
        text = text.strip()

        return Segment(
            start=seg.start,
            end=seg.end,
            text=text,
            log_prob=seg.log_prob,
        )

    def _filter_by_confidence(self, segments: List[Segment]) -> List[Segment]:
        """根据置信度过滤低质量片段"""
        min_prob = self.config.min_log_prob
        filtered = []
        dropped = 0

        for seg in segments:
            if seg.log_prob >= min_prob:
                filtered.append(seg)
            else:
                dropped += 1

        if dropped > 0:
            print(f"[ASRPostProcessor] 置信度过低过滤: {dropped} 个片段")

        return filtered

    def _merge_segments(self, segments: List[Segment]) -> List[Segment]:
        """合并相邻的短片段"""
        if len(segments) <= 1:
            return segments

        cfg = self.config.merge_config
        merged = []
        buffer = segments[0]
        merged_count = 0

        for i in range(1, len(segments)):
            seg = segments[i]
            gap = seg.start - buffer.end

            # 如果间隔足够小且合并后时长在阈值内，则合并
            if gap < cfg.min_gap and (seg.end - buffer.start) < cfg.max_merge_duration:
                # 合并到 buffer
                buffer = Segment(
                    start=buffer.start,
                    end=seg.end,
                    text=buffer.text + seg.text,
                    log_prob=max(buffer.log_prob, seg.log_prob),  # 取较高置信度
                )
                merged_count += 1
            else:
                # 保存 buffer，开始新的
                merged.append(buffer)
                buffer = seg

        # 保存最后一个 buffer
        merged.append(buffer)

        if merged_count > 0:
            print(f"[ASRPostProcessor] 合并短片段: {merged_count} 次")

        return merged

    def normalize_text_only(self, text: str) -> str:
        """仅规范化文本（不涉及时间戳）"""
        seg = Segment(start=0, end=0, text=text)
        result = self._normalize_segment(seg)
        return result.text


# 全角转半角（独立函数）
def fullwidth_to_halfwidth(text: str) -> str:
    """将全角字符转换为半角"""
    result = []
    for char in text:
        if '\uff01' <= char <= '\uff5e':  # 全角 ASCII 范围
            result.append(chr(ord(char) - 0xfee0))
        else:
            result.append(char)
    return ''.join(result)


# 便捷函数
def postprocess_segments(
    segments: List[dict],
    normalize: bool = True,
    merge: bool = True,
    min_log_prob: float = -1.0,
) -> List[dict]:
    """
    快速后处理函数

    Args:
        segments: Whisper 输出片段
        normalize: 启用文本规范化
        merge: 启用片段合并
        min_log_prob: 最小 log 概率阈值

    Returns:
        处理后的片段
    """
    config = PostProcessConfig(
        enable_normalize=normalize,
        enable_merge=merge,
        enable_confidence_filter=min_log_prob > -2.0,
        min_log_prob=min_log_prob,
    )
    processor = ASRPostProcessor(config)
    return processor.process(segments)
