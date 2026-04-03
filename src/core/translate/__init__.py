"""
翻译模块 - 支持 DeepSeek / OpenAI

功能：将日文等外语翻译为中文
"""

import os
import time
from typing import List, Optional, Literal

from openai import OpenAI

# 优先从配置文件读取 API Key
from src.config import config


class Translator:
    """翻译器（支持 DeepSeek / OpenAI，支持 Config 热更新 + ASMR 术语库）"""

    # 支持的提供商
    PROVIDERS = {
        "deepseek": "https://api.deepseek.com",
        "openai": "https://api.openai.com/v1",
    }

    # 支持的模型
    MODELS = {
        "deepseek": ["deepseek-chat"],
        "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
    }

    def __init__(
        self,
        provider: Literal["deepseek", "openai"] = "deepseek",
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        use_terminology: bool = True,
    ):
        """
        初始化翻译器

        Args:
            provider: API 提供商
            model: 模型名称
            api_key: API 密钥（默认从环境变量读取，支持热更新）
            base_url: 自定义 API 地址
            use_terminology: 是否启用 ASMR 术语库
        """
        self.provider = provider
        self.model = model
        self._api_key_override = api_key  # 传入则优先使用，否则每次动态读取

        # 设置 base_url
        if base_url:
            self.base_url = base_url
        else:
            self.base_url = self.PROVIDERS.get(provider, "")

        # 术语库（延迟加载）
        self.term_db = None
        if use_terminology:
            try:
                from .terminology import TerminologyDB
                self.term_db = TerminologyDB()
            except Exception:
                pass  # 术语库不可用时静默降级

        print(f"[Translator] 提供商: {provider}, 模型: {model}, 术语库: {'ON' if self.term_db else 'OFF'}")

    @property
    def api_key(self) -> str:
        """每次读取最新配置（支持 GUI 热更新）"""
        if self._api_key_override:
            return self._api_key_override
        if self.provider == "deepseek":
            return config.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        elif self.provider == "openai":
            return config.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        return ""

    def _get_client(self) -> OpenAI:
        """每次调用都重新构建客户端（保证 api_key 始终是最新的）"""
        key = self.api_key
        if not key:
            raise ValueError(f"未设置 {self.provider} API 密钥，请在设置中配置")
        return OpenAI(api_key=key, base_url=self.base_url)

    def translate(
        self,
        text: str,
        source_lang: str = "日文",
        target_lang: str = "中文",
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        翻译单段文本

        Args:
            text: 待翻译文本
            source_lang: 源语言
            target_lang: 目标语言
            system_prompt: 自定义系统提示词

        Returns:
            str: 翻译结果
        """
        if system_prompt is None:
            system_prompt = self._build_system_prompt(source_lang, target_lang)

        response = self._get_client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=500,
            temperature=0.3,
        )

        return response.choices[0].message.content.strip()

    def _build_system_prompt(self, source_lang: str, target_lang: str) -> str:
        """构建系统提示词（可选接入术语库）"""
        if self.term_db:
            return self.term_db.build_system_prompt(source_lang, target_lang)
        return f"你是一个专业的{source_lang}翻译。请将{source_lang}翻译成{target_lang}，保持自然流畅，口语化。"

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str = "日文",
        target_lang: str = "中文",
        system_prompt: Optional[str] = None,
        delay: float = 0.1,
    ) -> List[str]:
        """
        批量翻译

        Args:
            texts: 文本列表
            source_lang: 源语言
            target_lang: 目标语言
            system_prompt: 自定义系统提示词
            delay: 请求间隔（秒）

        Returns:
            List[str]: 翻译结果列表
        """
        if system_prompt is None:
            system_prompt = self._build_system_prompt(source_lang, target_lang)

        results = []
        t0 = time.time()

        for i, text in enumerate(texts):
            if not text.strip():
                results.append("")
                continue

            try:
                # 每次动态获取客户端（保证 api_key 最新）
                response = self._get_client().chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    max_tokens=500,
                    temperature=0.3,
                )

                translated = response.choices[0].message.content.strip()
                results.append(translated)

                # 进度显示
                if (i + 1) % 10 == 0:
                    elapsed = time.time() - t0
                    print(f"  翻译进度: {i+1}/{len(texts)}, 耗时: {elapsed:.1f}s")

            except Exception as e:
                print(f"  翻译失败 [{i+1}]: {e}")
                results.append("")

            # 请求间隔
            if delay > 0:
                time.sleep(delay)

        print(f"[Translator] 批量翻译完成，{len(results)} 段，耗时: {time.time()-t0:.1f}s")

        return results

    def translate_segments(
        self,
        segments: List[dict],
        source_lang: str = "日文",
        target_lang: str = "中文",
    ) -> List[dict]:
        """
        翻译 ASR 识别结果段落

        Args:
            segments: ASR 识别结果 [{start, end, text}, ...]
            source_lang: 源语言
            target_lang: 目标语言

        Returns:
            List[dict]: 带翻译结果的段落 [{start, end, text, translation}, ...]
        """
        texts = [seg["text"] for seg in segments]
        translations = self.translate_batch(texts, source_lang, target_lang)

        # 合并结果
        results = []
        for seg, trans in zip(segments, translations):
            seg = seg.copy()
            seg["translation"] = trans
            results.append(seg)

        return results


# 便捷函数
def translate_text(
    text: str,
    source_lang: str = "日文",
    target_lang: str = "中文",
    provider: str = "deepseek",
) -> str:
    """快速翻译文本"""
    translator = Translator(provider=provider)
    return translator.translate(text, source_lang, target_lang)


def translate_batch(
    texts: List[str],
    source_lang: str = "日文",
    target_lang: str = "中文",
    provider: str = "deepseek",
) -> List[str]:
    """快速批量翻译"""
    translator = Translator(provider=provider)
    return translator.translate_batch(texts, source_lang, target_lang)


def load_vtt_translations(vtt_path: str) -> List[str]:
    """
    从 VTT 文件加载翻译文本

    VTT 格式:
    WEBVTT

    1
    00:00:24.140 --> 00:00:29.741
    主人，您露出了放松的表情呢

    Args:
        vtt_path: VTT 文件路径

    Returns:
        List[str]: 翻译文本列表（按时间顺序）
    """
    translations = []

    try:
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        i = 0

        # 跳过 WEBVTT 头
        while i < len(lines) and "WEBVTT" not in lines[i]:
            i += 1
        i += 1  # 跳过 WEBVTT 行

        # 解析每个字幕块
        while i < len(lines):
            line = lines[i].strip()

            # 跳过空行和序号行
            if not line or line.isdigit():
                i += 1
                continue

            # 时间戳行: 00:00:24.140 --> 00:00:29.741
            if "-->" in line:
                i += 1
                # 收集时间戳后的所有文本行（支持多行字幕），直到遇到空行
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1
                if text_lines:
                    translations.append(" ".join(text_lines))
                continue

            i += 1

        print(f"[VTT Loader] 加载了 {len(translations)} 条翻译: {vtt_path}")

    except FileNotFoundError:
        print(f"[VTT Loader] 文件不存在: {vtt_path}")
    except Exception as e:
        print(f"[VTT Loader] 解析失败: {e}")

    return translations


def detect_vtt_language(translations: List[str]) -> str:
    """
    检测 VTT 字幕的主语言（智能跳过 ASR/翻译的关键）

    判断逻辑：
    - 纯中文：没有假名且汉字占比 > 30%
    - 纯日文：有假名但没有中文（汉字可能是日文汉字）
    - 混合：两者都有
    - 未知：无法判断

    Args:
        translations: VTT 解析出的文本列表

    Returns:
        "zh" | "ja" | "mixed" | "unknown"
    """
    import re

    zh_chars = 0
    ja_kana = 0  # 仅统计假名（排除汉字重叠区）
    total = 0

    for text in translations:
        if not text.strip():
            continue
        # 中文字符（Unicode 范围 4E00-9FFF）
        zh_chars += len(re.findall(r"[\u4e00-\u9fff]", text))
        # 日文假名（平假名 + 片假名）
        ja_kana += len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", text))
        total += len(text.strip())

    if total == 0:
        return "unknown"

    # 纯中文：没有假名且汉字占比 > 30%
    if ja_kana == 0 and zh_chars / total > 0.3:
        return "zh"
    # 纯日文：有假名但没有中文（汉字可能是日文汉字）
    if ja_kana > 0 and zh_chars == 0:
        return "ja"
    # 混合：两者都有
    if ja_kana > 0 and zh_chars > 0:
        return "mixed"

    return "unknown"


def load_vtt_with_timestamps(vtt_path: str) -> List[dict]:
    """
    从 VTT 文件加载翻译文本（带时间戳，为后续时间轴对齐 TTS 铺路）

    Returns:
        List[dict]: [{start_sec, end_sec, text}, ...]
    """
    entries = []

    try:
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        i = 0

        # 跳过 WEBVTT 头
        while i < len(lines) and "WEBVTT" not in lines[i]:
            i += 1
        i += 1

        while i < len(lines):
            line = lines[i].strip()

            if not line or line.isdigit():
                i += 1
                continue

            if "-->" in line:
                # 解析时间戳
                parts = line.split("-->")
                start_str = parts[0].strip()
                end_str = parts[1].strip().split()[0]  # 去掉可能的样式标签
                start_sec = _parse_vtt_time(start_str)
                end_sec = _parse_vtt_time(end_str)

                # 收集文本行
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1

                if text_lines:
                    entries.append(
                        {
                            "start": start_sec,
                            "end": end_sec,
                            "text": " ".join(text_lines),
                        }
                    )
                continue

            i += 1

        print(f"[VTT Loader] 加载了 {len(entries)} 条带时间戳翻译: {vtt_path}")

    except Exception as e:
        print(f"[VTT Loader] 解析失败: {e}")

    return entries


def _parse_vtt_time(time_str: str) -> float:
    """
    将 VTT 时间格式 '00:00:24.140' 或 '00:24.140' 转换为秒数
    """
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")

    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)

    return 0.0
