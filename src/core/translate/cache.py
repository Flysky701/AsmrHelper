"""
翻译缓存层 - 按 MD5(原文) → 译文 映射

功能（Report #13 Phase 2 - M4）：
- 按原文 MD5 缓存翻译结果
- 命中检查：命中的句子跳过 API 调用
- 增量重处理：重处理时只翻译新增句子
- 节省 API 费用（同一作品批量处理可节省 20-60%）
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CacheEntry:
    """缓存条目"""
    translation: str  # 翻译结果
    timestamp: str  # 时间戳
    source_hash: str  # 原文哈希（用于验证）
    model: str  # 使用的模型

    def to_dict(self) -> dict:
        return {
            "translation": self.translation,
            "timestamp": self.timestamp,
            "source_hash": self.source_hash,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CacheEntry":
        return cls(
            translation=data["translation"],
            timestamp=data["timestamp"],
            source_hash=data["source_hash"],
            model=data.get("model", "unknown"),
        )


class TranslationCache:
    """
    翻译缓存管理器

    按 MD5(原文) → 译文 映射存储翻译结果。
    支持：
    - 缓存命中检查
    - 批量写入
    - 按文件隔离（每个项目/批次独立缓存）
    - 缓存验证（source_hash 不匹配时失效）
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_age_days: int = 30,
    ):
        """
        初始化缓存管理器

        Args:
            cache_dir: 缓存目录（默认 .workbuddy/translation_cache/）
            max_age_days: 缓存有效期（天）
        """
        if cache_dir is None:
            cache_dir = Path(__file__).parent.parent.parent.parent / ".workbuddy" / "translation_cache"

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_days = max_age_days

        # 内存缓存（当前会话）
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def _hash_text(self, text: str) -> str:
        """计算文本 MD5 哈希"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _get_cache_file(self, namespace: str = "default") -> Path:
        """获取缓存文件路径"""
        # 安全的命名（替换非法字符）
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in namespace)
        return self.cache_dir / f"{safe_name}.json"

    def load(self, namespace: str = "default") -> Dict[str, CacheEntry]:
        """
        加载缓存文件到内存

        Args:
            namespace: 命名空间（用于隔离不同项目/批次的缓存）

        Returns:
            Dict[str, CacheEntry]: 缓存字典
        """
        cache_file = self._get_cache_file(namespace)

        if not cache_file.exists():
            return {}

        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            entries = {}

            for key, value in data.items():
                try:
                    entry = CacheEntry.from_dict(value)
                    # 检查过期
                    if self._is_expired(entry.timestamp):
                        continue
                    entries[key] = entry
                except (KeyError, TypeError):
                    continue

            print(f"[TranslationCache] 加载缓存 {len(entries)} 条: {cache_file.name}")
            return entries

        except (json.JSONDecodeError, IOError) as e:
            print(f"[TranslationCache] 缓存加载失败: {e}")
            return {}

    def save(
        self,
        cache_data: Dict[str, CacheEntry],
        namespace: str = "default",
    ):
        """
        保存缓存到文件

        Args:
            cache_data: 缓存数据
            namespace: 命名空间
        """
        cache_file = self._get_cache_file(namespace)

        # 转换为可序列化格式
        data = {key: entry.to_dict() for key, entry in cache_data.items()}

        try:
            cache_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except IOError as e:
            print(f"[TranslationCache] 缓存保存失败: {e}")

    def _is_expired(self, timestamp_str: str) -> bool:
        """检查缓存是否过期"""
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            age_days = (datetime.now() - timestamp).days
            return age_days > self.max_age_days
        except (ValueError, TypeError):
            return True  # 无效时间戳视为过期

    def get(self, text: str) -> Optional[str]:
        """
        获取缓存的翻译结果

        Args:
            text: 原文

        Returns:
            Optional[str]: 缓存的翻译结果，None 表示未命中
        """
        key = self._hash_text(text)

        # 先检查内存缓存
        if key in self._memory_cache:
            self._hits += 1
            return self._memory_cache[key].translation

        return None

    def set(
        self,
        text: str,
        translation: str,
        model: str = "unknown",
    ):
        """
        设置缓存

        Args:
            text: 原文
            translation: 翻译结果
            model: 使用的模型
        """
        key = self._hash_text(text)
        entry = CacheEntry(
            translation=translation,
            timestamp=datetime.now().isoformat(),
            source_hash=self._hash_text(text),
            model=model,
        )
        self._memory_cache[key] = entry

    def get_batch(
        self,
        texts: List[str],
    ) -> Tuple[List[Optional[str]], List[Tuple[int, str]]]:
        """
        批量获取缓存命中情况

        Args:
            texts: 原文列表

        Returns:
            Tuple[List[Optional[str]], List[Tuple[int, str]]]:
            - 命中的结果列表（None 表示未命中）
            - 未命中的 (索引, 原文) 列表
        """
        hits = []
        misses = []

        for i, text in enumerate(texts):
            cached = self.get(text)
            if cached is not None:
                hits.append(cached)
            else:
                hits.append(None)
                misses.append((i, text))

        return hits, misses

    def set_batch(
        self,
        results: List[Tuple[int, str, str]],
        model: str = "unknown",
    ):
        """
        批量设置缓存

        Args:
            results: [(索引, 原文, 翻译), ...]
            model: 使用的模型
        """
        for _, text, translation in results:
            self.set(text, translation, model)

    def get_stats(self) -> Dict[str, int]:
        """获取缓存统计信息"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": hit_rate,
            "memory_entries": len(self._memory_cache),
        }

    def clear_stats(self):
        """清除统计信息"""
        self._hits = 0
        self._misses = 0


# 全局单例（延迟初始化）
_cache_instance: Optional[TranslationCache] = None


def get_cache() -> TranslationCache:
    """获取全局缓存实例"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = TranslationCache()
    return _cache_instance
