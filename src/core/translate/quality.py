"""
翻译质量检测模块 - 检测翻译结果中的常见问题

功能：
1. 残日检测：检测译文中残留的日文假名
2. 标点一致性：检测中日标点混用
3. 长度异常检测：检测译文长度异常（过短/过长）
4. 空白检测：检测译文是否为空或仅含空白
"""

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


class QualityIssue(Enum):
    """质量问题类型"""
    JAPANESE_RESIDUE = "japanese_residue"       # 残日
    PUNCTUATION_MIX = "punctuation_mix"          # 标点混用
    LENGTH_TOO_SHORT = "length_too_short"        # 译文过短
    LENGTH_TOO_LONG = "length_too_long"          # 译文过长
    EMPTY_TRANSLATION = "empty_translation"      # 空翻译
    UNKNOWN = "unknown"                          # 未知问题


@dataclass
class QualityCheckResult:
    """质量检测结果"""
    original: str                    # 原文
    translation: str                 # 译文
    index: int                       # 句子的序号
    issues: List[QualityIssue] = field(default_factory=list)  # 发现的问题
    is_valid: bool = True            # 是否有效
    fix_suggestion: Optional[str] = None  # 修复建议

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0


class QualityChecker:
    """
    翻译质量检测器

    检测翻译结果中的常见问题，并提供修复建议。
    主要针对 ASMR 场景定制（单说话人、口语化）。
    """

    # 日文假名正则
    HIRAGANA = re.compile(r'[\u3040-\u309f]')      # 平假名
    KATAKANA = re.compile(r'[\u30a0-\u30ff]')       # 片假名
    KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')  # 所有假名

    # 日文字符（包含汉字）
    JAPANESE = re.compile(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]')

    # 中文标点 vs 日文/英文标点
    CHINESE_PUNCT = re.compile(r'[，。！？；：、""''（）【】《》]')
    WESTERN_PUNCT = re.compile(r'[,.!?;:"\'()\[\]<>]')

    # 允许残留的短假名（如 ASMR 音效词）
    ALLOWED_SHORT_KANA = {"あ", "ん", "っ", "ー", "〜"}

    def __init__(
        self,
        max_retries: int = 3,
        allow_short_kana: bool = True,
        short_kana_threshold: int = 2,
        length_ratio_min: float = 0.2,
        length_ratio_max: float = 3.0,
    ):
        """
        初始化质量检测器

        Args:
            max_retries: 最大重试检测次数
            allow_short_kana: 是否允许短假名残留（如 ASMR 音效词）
            short_kana_threshold: 短假名的阈值（少于等于此数量的假名允许保留）
            length_ratio_min: 译文/原文长度比的最小值（低于此认为过短）
            length_ratio_max: 译文/原文长度比的最大值（高于此认为过长）
        """
        self.max_retries = max_retries
        self.allow_short_kana = allow_short_kana
        self.short_kana_threshold = short_kana_threshold
        self.length_ratio_min = length_ratio_min
        self.length_ratio_max = length_ratio_max

    def check(self, original: str, translation: str, index: int = 0) -> QualityCheckResult:
        """
        检测单条翻译的质量

        Args:
            original: 原文
            translation: 译文
            index: 句子序号

        Returns:
            QualityCheckResult: 检测结果
        """
        result = QualityCheckResult(
            original=original,
            translation=translation,
            index=index,
        )

        # 1. 空翻译检测
        if self._is_empty(translation):
            result.issues.append(QualityIssue.EMPTY_TRANSLATION)
            result.is_valid = False
            result.fix_suggestion = "翻译结果为空，请检查 API 响应或重试"
            return result

        # 2. 残日检测
        jp_issue = self._check_japanese_residue(original, translation)
        if jp_issue:
            result.issues.append(QualityIssue.JAPANESE_RESIDUE)
            result.fix_suggestion = "译文中残留日文，请检查是否需要重新翻译"

        # 3. 长度异常检测
        length_issue = self._check_length_ratio(original, translation)
        if length_issue:
            result.issues.append(length_issue)
            result.fix_suggestion = f"译文长度异常（{length_issue.value}），请检查翻译质量"

        # 4. 标点混用检测（警告，不影响有效性）
        if self._has_punctuation_mix(translation):
            # 标点混用只是警告，不标记为无效
            pass

        # 如果有严重问题（残日），标记为无效
        if QualityIssue.JAPANESE_RESIDUE in result.issues:
            result.is_valid = False

        return result

    def check_batch(
        self,
        originals: List[str],
        translations: List[str],
    ) -> List[QualityCheckResult]:
        """
        批量检测翻译质量

        Args:
            originals: 原文列表
            translations: 译文列表

        Returns:
            List[QualityCheckResult]: 检测结果列表
        """
        results = []
        for i, (orig, trans) in enumerate(zip(originals, translations)):
            results.append(self.check(orig, trans, i))
        return results

    def filter(
        self,
        translations: List[str],
        originals: List[str],
    ) -> List[Tuple[str, QualityCheckResult]]:
        """
        过滤有问题的翻译，返回需要检查的列表

        Args:
            translations: 译文列表
            originals: 原文列表

        Returns:
            List[Tuple[str, QualityCheckResult]]: 有问题的翻译及检测结果
        """
        results = []
        for i, (orig, trans) in enumerate(zip(originals, translations)):
            result = self.check(orig, trans, i)
            if result.has_issues:
                results.append((trans, result))
        return results

    def _is_empty(self, text: str) -> bool:
        """检测文本是否为空"""
        return not text or not text.strip()

    def _check_japanese_residue(self, original: str, translation: str) -> bool:
        """
        检测译文中是否残留日文假名

        允许情况：
        - 短假名（如 ASMR 音效词）：あ、ん、っ、ー、〜 等
        - 少量假名（不超过阈值）
        """
        # 找出所有假名
        kana_matches = self.KANA.findall(translation)

        if not kana_matches:
            return False  # 没有假名，没问题

        # 计算非允许的假名数量
        non_allowed = [k for k in kana_matches if k not in self.ALLOWED_SHORT_KANA]

        # 如果允许短假名，减去它们
        if self.allow_short_kana:
            short_kana = [k for k in kana_matches if k in self.ALLOWED_SHORT_KANA]
            non_allowed = [k for k in kana_matches if k not in self.ALLOWED_SHORT_KANA]
            # 如果总假名数 <= 阈值，允许
            if len(kana_matches) <= self.short_kana_threshold:
                return False

        # 有超过阈值的非允许假名，认为是残日
        return len(non_allowed) > self.short_kana_threshold

    def _check_length_ratio(self, original: str, translation: str) -> Optional[QualityIssue]:
        """
        检测译文长度是否异常

        Returns:
            QualityIssue: 问题类型，或 None 表示正常
        """
        if not original or not translation:
            return None

        orig_len = len(original)
        trans_len = len(translation)

        # 避免除以零
        if orig_len == 0:
            return None

        ratio = trans_len / orig_len

        if ratio < self.length_ratio_min:
            return QualityIssue.LENGTH_TOO_SHORT
        if ratio > self.length_ratio_max:
            return QualityIssue.LENGTH_TOO_LONG

        return None

    def _has_punctuation_mix(self, text: str) -> bool:
        """
        检测标点符号是否混用（中/日/英标点混在一起）

        这是一个宽松的检测，主要用于警告而不是判定为错误
        """
        has_chinese = bool(self.CHINESE_PUNCT.search(text))
        has_western = bool(self.WESTERN_PUNCT.search(text))

        # 两者都有，标记为混用
        return has_chinese and has_western

    def get_summary(self, results: List[QualityCheckResult]) -> str:
        """
        获取质量检测摘要

        Args:
            results: 检测结果列表

        Returns:
            str: 摘要信息
        """
        total = len(results)
        valid = sum(1 for r in results if r.is_valid)
        invalid = total - valid

        # 统计各类问题
        issue_counts = {}
        for result in results:
            for issue in result.issues:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1

        summary_parts = [
            f"质量检测完成: {total} 条",
            f"  有效: {valid}, 有问题: {invalid}",
        ]

        if issue_counts:
            summary_parts.append("  问题分布:")
            for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
                summary_parts.append(f"    - {issue.value}: {count}")

        return "\n".join(summary_parts)


# 便捷函数
def check_translation_quality(
    original: str,
    translation: str,
    index: int = 0,
) -> QualityCheckResult:
    """
    快速检测单条翻译质量

    Args:
        original: 原文
        translation: 译文
        index: 句子序号

    Returns:
        QualityCheckResult: 检测结果
    """
    checker = QualityChecker()
    return checker.check(original, translation, index)


def has_japanese_residue(text: str) -> bool:
    """
    快速检测译文中是否残留日文假名

    Args:
        text: 待检测文本

    Returns:
        bool: True 表示有残留
    """
    checker = QualityChecker()
    # 空文本或纯中文检测
    if not text or not text.strip():
        return False

    # 简单检测：超过 2 个假名认为有问题
    kana_matches = checker.KANA.findall(text)
    return len(kana_matches) > 2
