"""
ASMR 术语库 - 辅助翻译提示词构建

功能：
- 提供 ASMR 专用术语映射（日文→中文）
- 构建含术语约束的翻译系统提示词
- 支持用户自定义术语追加（写入 asmr_terms.json）
"""

import json
from pathlib import Path
from typing import Dict, Optional


TERM_DB_PATH = Path(__file__).parent.parent.parent.parent / "config" / "asmr_terms.json"


class TerminologyDB:
    """ASMR 专用术语库"""

    _default_terms: Dict[str, str] = {
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
    }

    _instance: Optional["TerminologyDB"] = None

    def __new__(cls) -> "TerminologyDB":
        """单例模式 - 全局共享一份术语数据"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._terms: Dict[str, str] = dict(self._default_terms)
        self._load_user_terms()
        self._initialized = True

    def _load_user_terms(self):
        """从 asmr_terms.json 加载用户自定义术语"""
        if TERM_DB_PATH.exists():
            try:
                data = json.loads(TERM_DB_PATH.read_text(encoding="utf-8"))
                user_terms = data.get("条目", {})
                if isinstance(user_terms, dict):
                    self._terms.update(user_terms)
                    print(f"[TermDB] 加载了 {len(user_terms)} 条用户术语")
            except Exception as e:
                print(f"[TermDB] 加载失败: {e}")

    def build_system_prompt(
        self,
        source_lang: str = "日文",
        target_lang: str = "中文",
        max_terms: int = 20,
    ) -> str:
        """
        构建含术语约束的翻译系统提示词

        Args:
            source_lang: 源语言
            target_lang: 目标语言
            max_terms: 最多注入的术语数量

        Returns:
            str: 包含术语约束的系统提示词
        """
        term_list = list(self._terms.items())
        if len(term_list) > max_terms:
            term_list = term_list[:max_terms]

        if not term_list:
            return f"你是一个专业的{source_lang}翻译。请将{source_lang}翻译成{target_lang}，保持自然流畅，口语化。"

        term_hints = "\n".join(
            f"  {k} → {v}" for k, v in term_list
        )

        return (
            f"你是一个专业的{source_lang}翻译，专注于 ASMR 音声内容。\n"
            f"请将{source_lang}翻译成{target_lang}，保持自然流畅、口语化，适合 ASMR 听感。\n"
            f"以下为优先术语表，翻译时请保持一致：\n{term_hints}"
        )

    def add_term(self, source: str, target: str, save: bool = True):
        """
        添加术语

        Args:
            source: 原文（如 日文）
            target: 译文（如 中文）
            save: 是否持久化到文件
        """
        self._terms[source] = target
        if save:
            self._save()

    def remove_term(self, source: str, save: bool = True):
        """移除术语"""
        self._terms.pop(source, None)
        if save:
            self._save()

    def _save(self):
        """保存术语到配置文件"""
        TERM_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "说明": "ASMR 术语库 - 日文原文: 中文翻译。用户自定义条目会追加到此文件。",
            "条目": self._terms,
        }
        TERM_DB_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[TermDB] 已保存 {len(self._terms)} 条术语")

    @property
    def all_terms(self) -> Dict[str, str]:
        """返回所有术语（只读副本）"""
        return dict(self._terms)

    @property
    def count(self) -> int:
        return len(self._terms)
