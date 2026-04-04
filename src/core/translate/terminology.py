"""
ASMR 术语库 - 三层字典系统

功能（Report #13 Phase 2 - M5）：
- pre_terms: ASR 纠错字典（在送入 LLM 前替换）
- gpt_terms: GPT 字典（注入提示词引导 LLM 使用指定翻译）
- post_terms: 后处理字典（修正 LLM 顽固错误）

三层字典的实际价值：
- pre_jp: 修正 ASR/OCR 错误（如「はか」→「墓」）
- gpt_dict: 引导 LLM 使用指定翻译
- post_zh: 修正 LLM 顽固的错误翻译
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional, List

from src.config import PROJECT_ROOT  # 统一使用项目根目录


TERM_DB_PATH = PROJECT_ROOT / "config" / "asmr_terms.json"


class ThreeLayerTerminologyDB:
    """
    三层术语库

    - pre_terms: 预处理字典（ASR纠错）
    - gpt_terms: GPT注入字典（引导翻译）
    - post_terms: 后处理字典（修正顽固错误）
    """

    # 默认预处理字典（ASR纠错）
    DEFAULT_PRE_TERMS: Dict[str, str] = {
        # ASR 常见错误
        "はか": "墓",
        "はみが": "墓",
        "ばか": "馬鹿",
        "死に": "知り",
        "しりに": "尻に",
        "おしり": "お尻",
        "いっち": "一回",
        "いっかい": "一回",
        "ぼくに": "僕に",
        "ぼくの": "僕の",
        "あたしに": "私に",
        "あたしの": "私の",
        "ご主人": "ご主人様",
    }

    # 默认 GPT 字典（引导翻译）
    DEFAULT_GPT_TERMS: Dict[str, str] = {
        # ASMR 场景专用术语
        "ご主人様": "主人",
        "お兄ちゃん": "哥哥",
        "お姉ちゃん": "姐姐",
        "はい": "嗯",
        "いいえ": "不",
        "ふふ": "呵呵",
        "えへへ": "嘿嘿",
        "もふもふ": "毛茸茸的",
        "心配": "担心",
        "仕事": "工作",
        "一緒に": "一起",
        "い나요": "呢",
        "ご褒美": "奖励",
        "敏感": "敏感",
        "恥ずかしい": "害羞的",
        "舐めて": "舔",
        "吐息": "呼吸",
        "囁き": "低语",
        "艶声": "娇媚的声音",
        "为您服务": "为您服务",
        # ASMR 语气词
        "んふ": "嗯",
        "んん": "嗯",
        "あは": "啊",
        "ひゃん": "呢",
    }

    # 默认后处理字典（修正顽固错误）
    DEFAULT_POST_TERMS: Dict[str, str] = {
        # LLM 常见的顽固错误翻译
        "奴隶": "主人",
        "仆从": "主人",
        "下仆": "主人",
        "ごしょうぬし": "主人",
        "御主人": "主人",
    }

    _instance: Optional["ThreeLayerTerminologyDB"] = None

    def __new__(cls) -> "ThreeLayerTerminologyDB":
        """单例模式 - 全局共享一份术语数据"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._pre_terms: Dict[str, str] = dict(self.DEFAULT_PRE_TERMS)
        self._gpt_terms: Dict[str, str] = dict(self.DEFAULT_GPT_TERMS)
        self._post_terms: Dict[str, str] = dict(self.DEFAULT_POST_TERMS)

        self._load_user_terms()
        self._initialized = True

        print(f"[TermDB] 三层术语库加载完成: pre={len(self._pre_terms)}, gpt={len(self._gpt_terms)}, post={len(self._post_terms)}")

    def _load_user_terms(self):
        """从 asmr_terms.json 加载用户自定义术语"""
        if TERM_DB_PATH.exists():
            try:
                data = json.loads(TERM_DB_PATH.read_text(encoding="utf-8"))

                # 加载预处理字典
                user_pre = data.get("pre_terms", {})
                if isinstance(user_pre, dict):
                    self._pre_terms.update(user_pre)
                    print(f"[TermDB] 加载用户预处理术语: {len(user_pre)} 条")

                # 加载 GPT 字典
                user_gpt = data.get("gpt_terms", {})
                if isinstance(user_gpt, dict):
                    self._gpt_terms.update(user_gpt)
                    print(f"[TermDB] 加载用户 GPT 术语: {len(user_gpt)} 条")

                # 加载后处理字典
                user_post = data.get("post_terms", {})
                if isinstance(user_post, dict):
                    self._post_terms.update(user_post)
                    print(f"[TermDB] 加载用户后处理术语: {len(user_post)} 条")

                # 兼容旧格式（全放在 terms 字段）
                legacy_terms = data.get("条目", {})
                if isinstance(legacy_terms, dict):
                    # 旧格式全部当作 GPT 术语
                    self._gpt_terms.update(legacy_terms)
                    print(f"[TermDB] 兼容旧格式术语: {len(legacy_terms)} 条")

            except Exception as e:
                print(f"[TermDB] 术语加载失败: {e}")

    def save(self):
        """保存术语到配置文件"""
        TERM_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "说明": "ASMR 术语库 - 三层结构",
            "pre_terms": self._pre_terms,
            "gpt_terms": self._gpt_terms,
            "post_terms": self._post_terms,
            "legacy_note": "旧格式 '条目' 字段已废弃，请使用 pre_terms/gpt_terms/post_terms",
        }
        TERM_DB_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[TermDB] 已保存术语: pre={len(self._pre_terms)}, gpt={len(self._gpt_terms)}, post={len(self._post_terms)}")

    # ========== 核心功能 ==========

    def preprocess(self, text: str) -> str:
        """
        预处理：ASR 纠错字典

        在文本送入 LLM 前替换 ASR 常见的识别错误。

        Args:
            text: 原始文本

        Returns:
            str: 纠错后的文本
        """
        for src, dst in self._pre_terms.items():
            text = text.replace(src, dst)
        return text

    def preprocess_batch(self, texts: List[str]) -> List[str]:
        """批量预处理"""
        return [self.preprocess(t) for t in texts]

    def build_gpt_dict_prompt(
        self,
        texts: Optional[List[str]] = None,
        max_terms: int = 20,
    ) -> str:
        """
        构建 GPT 字典提示词

        只注入与当前批次相关的术语，减少 token 消耗。

        Args:
            texts: 当前批次的文本列表（用于筛选相关术语）
            max_terms: 最多注入的术语数量

        Returns:
            str: 术语约束提示词
        """
        terms_to_use = self._gpt_terms

        # 如果提供了文本，只选择包含在文本中的术语
        if texts is not None:
            combined = " ".join(texts)
            terms_to_use = {
                k: v for k, v in self._gpt_terms.items()
                if k in combined
            }

        if not terms_to_use:
            return ""

        # 限制数量
        term_list = list(terms_to_use.items())
        if len(term_list) > max_terms:
            term_list = term_list[:max_terms]

        term_lines = "\n".join(f"  {k} -> {v}" for k, v in term_list)
        return f"术语约束（请保持一致）:\n{term_lines}"

    def postprocess(self, text: str) -> str:
        """
        后处理：修正 LLM 顽固的错误翻译

        Args:
            text: LLM 翻译后的文本

        Returns:
            str: 修正后的文本
        """
        for src, dst in self._post_terms.items():
            text = text.replace(src, dst)
        return text

    def postprocess_batch(self, texts: List[str]) -> List[str]:
        """批量后处理"""
        return [self.postprocess(t) for t in texts]

    # ========== 兼容接口 ==========

    def build_system_prompt(
        self,
        source_lang: str = "日文",
        target_lang: str = "中文",
        max_terms: int = 20,
    ) -> str:
        """
        构建系统提示词（兼容旧接口）

        Args:
            source_lang: 源语言
            target_lang: 目标语言
            max_terms: 最多注入的术语数量

        Returns:
            str: 包含术语约束的系统提示词
        """
        gpt_dict_hint = self.build_gpt_dict_prompt(max_terms=max_terms)

        if not gpt_dict_hint:
            return f"你是一个专业的{source_lang}翻译。请将{source_lang}翻译成{target_lang}，保持自然流畅，口语化。"

        return (
            f"你是一个专业的{source_lang}翻译，专注于 ASMR 音声内容。\n"
            f"请将{source_lang}翻译成{target_lang}，保持自然流畅、口语化，适合 ASMR 听感。\n"
            f"\n{gpt_dict_hint}"
        )

    def add_term(
        self,
        source: str,
        target: str,
        layer: str = "gpt",
        save: bool = True,
    ):
        """
        添加术语

        Args:
            source: 原文
            target: 译文
            layer: 术语层 (pre/gpt/post)
            save: 是否持久化
        """
        if layer == "pre":
            self._pre_terms[source] = target
        elif layer == "post":
            self._post_terms[source] = target
        else:
            self._gpt_terms[source] = target

        if save:
            self.save()

    def remove_term(self, source: str, layer: str = "gpt", save: bool = True):
        """移除术语"""
        if layer == "pre":
            self._pre_terms.pop(source, None)
        elif layer == "post":
            self._post_terms.pop(source, None)
        else:
            self._gpt_terms.pop(source, None)

        if save:
            self.save()

    # ========== 属性 ==========

    @property
    def pre_terms(self) -> Dict[str, str]:
        """预处理字典（只读）"""
        return dict(self._pre_terms)

    @property
    def gpt_terms(self) -> Dict[str, str]:
        """GPT 字典（只读）"""
        return dict(self._gpt_terms)

    @property
    def post_terms(self) -> Dict[str, str]:
        """后处理字典（只读）"""
        return dict(self._post_terms)

    @property
    def pre_count(self) -> int:
        return len(self._pre_terms)

    @property
    def gpt_count(self) -> int:
        return len(self._gpt_terms)

    @property
    def post_count(self) -> int:
        return len(self._post_terms)

    @property
    def total_count(self) -> int:
        return self.pre_count + self.gpt_count + self.post_count


# ========== 兼容旧接口 ==========

# 为了向后兼容，保留 TerminologyDB 作为别名
TerminologyDB = ThreeLayerTerminologyDB
