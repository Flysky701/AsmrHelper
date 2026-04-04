"""
翻译模块 - 支持 DeepSeek / OpenAI

功能：将日文等外语翻译为中文

升级功能（Report #13 Phase 1）：
1. 批量翻译（10句/批）
2. 重试机制（温度切换 + 指数退避）
3. 质量检测（残日检测等）
"""

import os
import time
import json
import re
from typing import List, Optional, Literal, Tuple

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

    # 批量翻译配置
    DEFAULT_BATCH_SIZE = 10  # 默认每批 10 句
    DEFAULT_MAX_RETRIES = 3  # 默认最大重试次数
    DEFAULT_TEMPERATURES = (0.1, 0.3, 0.5)  # 重试温度序列

    def __init__(
        self,
        provider: Literal["deepseek", "openai"] = "deepseek",
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        use_terminology: bool = True,
        use_batch: bool = True,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        use_quality_check: bool = True,
    ):
        """
        初始化翻译器

        Args:
            provider: API 提供商
            model: 模型名称
            api_key: API 密钥（默认从环境变量读取，支持热更新）
            base_url: 自定义 API 地址
            use_terminology: 是否启用 ASMR 术语库
            use_batch: 是否启用批量翻译（10句/批）
            batch_size: 批量大小
            max_retries: 最大重试次数
            use_quality_check: 是否启用质量检测
        """
        self.provider = provider
        self.model = model
        self._api_key_override = api_key  # 传入则优先使用，否则每次动态读取

        # 设置 base_url
        if base_url:
            self.base_url = base_url
        else:
            self.base_url = self.PROVIDERS.get(provider, "")

        # 批量翻译配置
        self.use_batch = use_batch
        self.batch_size = batch_size
        self.max_retries = max_retries

        # 质量检测
        self.use_quality_check = use_quality_check
        self._quality_checker = None

        # 术语库（延迟加载）
        self.term_db = None
        if use_terminology:
            try:
                from .terminology import TerminologyDB
                self.term_db = TerminologyDB()
            except Exception:
                pass  # 术语库不可用时静默降级

        print(f"[Translator] 提供商: {provider}, 模型: {model}, 术语库: {'ON' if self.term_db else 'OFF'}")
        print(f"[Translator] 批量翻译: {'ON' if use_batch else 'OFF'} (每批{batch_size}句), 重试: {max_retries}次, 质量检测: {'ON' if use_quality_check else 'OFF'}")

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

    def _get_quality_checker(self):
        """获取质量检测器（延迟加载）"""
        if self._quality_checker is None and self.use_quality_check:
            try:
                from .quality import QualityChecker
                self._quality_checker = QualityChecker()
            except Exception as e:
                print(f"[Translator] 质量检测器加载失败: {e}")
                self._quality_checker = None
        return self._quality_checker

    def _translate_single_with_retry(
        self,
        text: str,
        system_prompt: str,
        max_retries: int = None,
    ) -> Tuple[str, bool]:
        """
        带重试的单句翻译

        Args:
            text: 待翻译文本
            system_prompt: 系统提示词
            max_retries: 最大重试次数

        Returns:
            Tuple[str, bool]: (翻译结果, 是否成功)
        """
        if max_retries is None:
            max_retries = self.max_retries

        temperatures = self.DEFAULT_TEMPERATURES

        for attempt in range(max_retries):
            temperature = temperatures[attempt] if attempt < len(temperatures) else temperatures[-1]

            try:
                response = self._get_client().chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    max_tokens=500,
                    temperature=temperature,
                )

                translated = response.choices[0].message.content.strip()
                return translated, True

            except Exception as e:
                if attempt < max_retries - 1:
                    # 指数退避：1s, 2s, 4s...
                    wait_time = 2 ** attempt
                    print(f"  [WARN] 翻译失败 (尝试 {attempt+1}/{max_retries}): {e}, {wait_time}s 后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"  [ERROR] 翻译最终失败: {e}")
                    return text, False  # 降级：返回原文

        return text, False

    def _translate_batch_with_retry(
        self,
        batch: List[str],
        batch_indices: List[int],
        system_prompt: str,
        max_retries: int = None,
    ) -> List[Tuple[int, str, bool]]:
        """
        带重试的批量翻译

        Args:
            batch: 批次文本列表
            batch_indices: 原始文本索引
            system_prompt: 系统提示词
            max_retries: 最大重试次数

        Returns:
            List[Tuple[int, str, bool]]: [(索引, 翻译结果, 是否成功), ...]
        """
        if max_retries is None:
            max_retries = self.max_retries

        temperatures = self.DEFAULT_TEMPERATURES

        # 构建批量请求
        batch_data = [
            {"id": i, "idx": idx, "src": text}
            for i, (idx, text) in enumerate(zip(batch_indices, batch))
        ]

        for attempt in range(max_retries):
            temperature = temperatures[attempt] if attempt < len(temperatures) else temperatures[-1]

            try:
                # 批量请求
                response = self._get_client().chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(batch_data, ensure_ascii=False)},
                    ],
                    max_tokens=2000,
                    temperature=temperature,
                )

                # 解析 JSON 响应
                content = response.choices[0].message.content.strip()
                results = json.loads(content)

                # 确保返回的是列表
                if isinstance(results, list):
                    # 按 id 排序
                    results_dict = {r["id"]: r for r in results}
                    return [
                        (batch_indices[i], results_dict[i]["src"] if i in results_dict else batch[i - len(batch_indices)], True)
                        for i in range(len(batch))
                    ]
                else:
                    raise ValueError(f"Expected list, got {type(results)}")

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"  [WARN] 批量 JSON 解析失败 (尝试 {attempt+1}/{max_retries}): {e}, 降级为逐条翻译...")
                    # JSON 解析失败，降级为逐条翻译
                    if attempt == max_retries - 2:
                        # 最后一次机会，降级
                        return [
                            (idx, text, False)  # 标记为需要重试
                            for idx, text in zip(batch_indices, batch)
                        ]
                else:
                    print(f"  [ERROR] 批量翻译最终失败，降级为逐条翻译: {e}")
                    return [
                        (idx, text, False)
                        for idx, text in zip(batch_indices, batch)
                    ]

        return [
            (idx, text, False)
            for idx, text in zip(batch_indices, batch)
        ]

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str = "日文",
        target_lang: str = "中文",
        system_prompt: Optional[str] = None,
        delay: float = 0.1,
    ) -> List[str]:
        """
        批量翻译（支持批量请求 + 重试 + 质量检测）

        Args:
            texts: 文本列表
            source_lang: 源语言
            target_lang: 目标语言
            system_prompt: 自定义系统提示词
            delay: 请求间隔（秒）- 已废弃，保留兼容性

        Returns:
            List[str]: 翻译结果列表
        """
        if system_prompt is None:
            system_prompt = self._build_system_prompt(source_lang, target_lang)

        t0 = time.time()

        # 空文本预处理
        results = [""] * len(texts)
        need_translate = []  # [(index, text), ...]
        for i, text in enumerate(texts):
            if text.strip():
                need_translate.append((i, text))
            else:
                results[i] = ""

        total_need = len(need_translate)
        if total_need == 0:
            print(f"[Translator] 批量翻译完成，0 段有效文本")
            return results

        # 启用批量翻译模式
        if self.use_batch and total_need > 1:
            results = self._translate_batch_mode(
                need_translate, results, system_prompt, t0
            )
        else:
            results = self._translate_single_mode(
                need_translate, results, system_prompt, t0
            )

        # 质量检测
        if self.use_quality_check:
            results = self._run_quality_check(results, texts)

        print(f"[Translator] 批量翻译完成，{total_need} 段，耗时: {time.time()-t0:.1f}s")
        return results

    def _translate_batch_mode(
        self,
        need_translate: List[Tuple[int, str]],
        results: List[str],
        system_prompt: str,
        t0: float,
    ) -> List[str]:
        """批量翻译模式"""
        batch_size = self.batch_size
        total = len(need_translate)

        print(f"[Translator] 使用批量翻译模式 (每批 {batch_size} 句)...")

        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = need_translate[batch_start:batch_end]
            batch_indices = [idx for idx, _ in batch]
            batch_texts = [text for _, text in batch]

            print(f"  翻译批次 {batch_start//batch_size + 1}: 句 {batch_start+1}-{batch_end}/{total}")

            # 尝试批量翻译
            batch_results = self._translate_batch_with_retry(
                batch_texts, batch_indices, system_prompt
            )

            # 处理失败项（逐条重试）
            for idx, text, success in batch_results:
                if success:
                    results[idx] = text
                else:
                    # 批量失败，降级为逐条翻译
                    translated, ok = self._translate_single_with_retry(text, system_prompt)
                    results[idx] = translated

            # 进度显示
            elapsed = time.time() - t0
            print(f"    进度: {batch_end}/{total}, 耗时: {elapsed:.1f}s")

        return results

    def _translate_single_mode(
        self,
        need_translate: List[Tuple[int, str]],
        results: List[str],
        system_prompt: str,
        t0: float,
    ) -> List[str]:
        """逐条翻译模式（备用）"""
        total = len(need_translate)
        print(f"[Translator] 使用逐条翻译模式...")

        for i, (idx, text) in enumerate(need_translate):
            translated, success = self._translate_single_with_retry(text, system_prompt)
            results[idx] = translated

            # 进度显示
            if (i + 1) % 10 == 0 or (i + 1) == total:
                elapsed = time.time() - t0
                print(f"  翻译进度: {i+1}/{total}, 耗时: {elapsed:.1f}s")

        return results

    def _run_quality_check(
        self,
        results: List[str],
        originals: List[str],
    ) -> List[str]:
        """运行质量检测（只检测实际翻译的句子，跳过降级保留原文的情况）"""
        checker = self._get_quality_checker()
        if checker is None:
            return results

        print("[Translator] 运行质量检测...")

        qa_results = checker.check_batch(originals, results)
        issues_found = 0

        for result in qa_results:
            if result.has_issues:
                # 跳过原文本身（原文就是日文，会误判）
                # 只有当译文和原文不同且译文有残日问题时才处理
                if result.translation == result.original:
                    continue

                issues_found += 1
                # 残日问题：保留原文而非有问题的翻译
                if any(iss.value == "japanese_residue" for iss in result.issues):
                    print(f"  [QA] 第{result.index+1}句残留日文，保留原文: {result.translation[:30]}...")
                    results[result.index] = result.original

        if issues_found > 0:
            print(f"[Translator] 质量检测: 发现 {issues_found} 条问题（已自动处理）")
        else:
            print("[Translator] 质量检测: 全部通过")

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
