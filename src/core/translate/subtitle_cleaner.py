"""
字幕清理模块 - 预处理字幕文本

功能：
1. 删除拟声词（笑声、语气词等）
2. 删除人物名字标识
3. 格式验证与统一

使用方法：
    from src.core.translate.subtitle_cleaner import SubtitleCleaner, clean_subtitle_text
    
    # 单条清理
    text = "主播：大家好呀～嘻嘻"
    cleaned = clean_subtitle_text(text)
    
    # 批量清理
    cleaner = SubtitleCleaner()
    cleaned_list = cleaner.clean_batch(texts)
"""

import re
from typing import List, Set, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class CleanerConfig:
    """清理配置"""
    remove_sound_effects: bool = True       # 删除拟声词
    remove_speaker_names: bool = True       # 删除说话人名字
    remove_punctuation_only: bool = True    # 删除纯标点片段
    remove_action_onomatopoeia: bool = True  # 删除动作拟声词（撸啊撸、搓啊搓等）
    remove_moaning: bool = True              # 删除纯喘息/呻吟（啊~...、嗯...等）
    remove_chapter_titles: bool = True       # 删除章节标题行
    min_text_length: int = 1                 # 最小文本长度
    custom_sound_words: Set[str] = field(default_factory=set)  # 自定义拟声词


class SoundEffectPatterns:
    """拟声词/音效模式库"""

    # 常见笑声拟声词（中文）
    CHINESE_LAUGHTER: Set[str] = {
        "嘻嘻", "哈哈", "呵呵", "嘿嘿", "咯咯", "嘎嘎", "哼哼", "嘿嘿嘿",
        "哈哈哈", "呵呵呵", "嘻嘻嘻", "咯咯咯", "嘎嘎嘎", "哼哼哼",
        "笑",  # 单字"笑"常作为拟声词
    }

    # 常见笑声拟声词（日文罗马音/日文）
    JAPANESE_LAUGHTER: Set[str] = {
        "waha", "wahaha", "wahahaha", "wwww", "wwwww",  # 日语笑声罗马音
        "あはは", "あははは", "あはははは",  # 日语笑声
        "うふふ", "うふふふ", "うはは",  # 女生笑
        "おほほ", "おほほほ",  # 优雅笑
        "くすくす", "くく",  # 偷笑
        "げらげら",  # 大笑
    }

    # 语气词/感叹词（中文）
    CHINESE_INTERJECTIONS: Set[str] = {
        "嗯", "啊", "哦", "噢", "呀", "嘛", "呢", "吧", "啦", "哈",
        "嘿", "哼", "唉", "哎", "咦", "哟", "哇", "呀", "呐",
        "嗯嗯", "啊啊啊", "哦哦", "噢噢", "呀呀", "嘿嘿", "哼哼",
        "啊啊", "哇哇", "诶", "诶诶", "哎哎", "呃", "呃呃",
        "呀~", "呀～", "哈~", "哈～",  # 带波浪号
    }

    # 语气词（英文）
    ENGLISH_INTERJECTIONS: Set[str] = {
        "uh", "um", "ah", "oh", "er", "mm", "hmm", "mmm",
        "yeah", "ya", "yep", "nope", "wow", "yay", "boo",
        "oops", "ouch", "ew", "ugh",
    }

    # 常见ASMR/音效词
    ASMR_EFFECTS: Set[str] = {
        # 中文ASMR常见词
        "呼", "呼～", "呼呼", "呼噜", "嘶", "嘶～",
        "啾", "啾啾", "木", "嘛", "呐呐",
        # 英文ASMR词
        "shh", "shhh", "hiss", "whisper", "murmur",
    }

    # ASMR 动作拟声词（XX啊XX 格式的重复动作声）
    # 例: 撸啊撸, 搓啊搓, 摸啊摸, 揉啊揉, 吞啊吞, 咕啊咕
    # 支持加长版: 撸啊撸啊撸啊撸啊
    # 支持后缀说话人: 撸啊撸 / 爱理：哦— (全角冒号 U+FF1A)
    ACTION_ONOMATOPOEIA_PATTERN = re.compile(
        r"^([\u4e00-\u9fff]{1,3}啊[\u4e00-\u9fff]{1,3})+(?:\s*/\s*[\u4e00-\u9fff\w]+[：:\s].*)?$"
    )

    # ASMR 喘息/呻吟模式（纯开口元音/鼻音 + 省略号）
    # 例: 啊~..., 嗯...嗯, 呃——, 啊、啊、
    # 不匹配: 唉…… (有语义的叹词), 嘿嘿 (笑声已有专门处理)
    MOANING_PATTERN = re.compile(
        r"^[啊嗯哈呃呜哼][…～~\-，。、\.~]+[啊嗯哈呃呜哼]{0,2}[…～~\-，。、\.~]*$"
    )

    # 组合正则模式
    # 笑声重复模式: 嘻嘻嘻, 哈哈哈, wwwww
    LAUGHTER_REPEAT_PATTERN = re.compile(
        r"^(嘻嘻+|哈哈+|呵呵+|嘿嘿+|咯咯+|嘎嘎+|哼哼+|うふ+|あは+|くす+|www+)+$"
    )

    # 纯拟声词片段: 只包含拟声词的文本
    SOUND_WORD_ONLY_PATTERN = re.compile(
        r"^[\s\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff～~wW]*$"  # 只含日文假名、中文、波浪号、w
    )

    # 括号内的音效标签: [笑声], [音乐], (鼓掌) 等
    SOUND_TAG_PATTERN = re.compile(
        r"[\（\(【\[].*?[\)）\】\]]",
        re.IGNORECASE
    )

    # 说话人名字模式
    SPEAKER_PATTERNS: List[Tuple[str, re.Pattern]] = [
        # 常见格式: 主播：, 主播:, 主播 -
        (r"说话人", re.compile(r"^(说话人|主播|主持人|嘉宾|听众|观众)[：:\-\s]+", re.IGNORECASE)),
        # 日语: 話者, 声優
        (r"日语说话人", re.compile(r"^(話者|声優|ナレーター)[：:\-\s]*", re.IGNORECASE)),
        # 括号内名字: [小明], (小红)
        (r"括号名字", re.compile(r"^[\（\(【\[].*?[\)）\】\]]\s*", re.IGNORECASE)),
        # 角色名 + 冒号: 张三: 李四: 佐藤: 丽花： 爱理：
        (r"角色名", re.compile(r"^[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{2,4}[：:]\s*", re.IGNORECASE)),
        # 英文名字: John: Mary:
        (r"英文名", re.compile(r"^[A-Za-z]{2,20}[：:]\s*")),
        # LRC格式时间标签后紧跟的说话人
        (r"LRC说话人", re.compile(r"^\d{2}:\d{2}[.:]\d{2}\][\s\-:]+([^\[\]]+):")),
    ]

    # 章节标题模式（LRC 首行或 VTT 纯标题）
    # 例: "5 舔耳手交", "10 双重舔耳手交", "03 洗澡"
    # 特征: 数字开头 + 短标题（通常不含标点或只有句号/空格）
    CHAPTER_TITLE_PATTERN = re.compile(
        r"^\d{1,3}\s+[\u4e00-\u9fff\w][\u4e00-\u9fff\w\s/～~\-]+$"
    )

    # 倒计时模式（不应被当作章节标题）
    COUNTDOWN_PATTERN = re.compile(
        r"^[一二三四五六七八九十百千万零\d]+[…～~\-。.]+$"
    )


class SubtitleCleaner:
    """
    字幕清理器

    功能：
    1. 删除拟声词（笑声、语气词等）
    2. 删除人物名字标识
    3. 清理空白片段
    4. 格式验证
    """

    # 默认保留的语气词（可能是实际对话内容）
    KEEP_INTERJECTIONS: Set[str] = {
        # 这些语气词可能是有意义的对话内容，不轻易删除
        "嗯", "啊", "哦", "好的", "好吧", "这样", "那个",
        "这个", "什么", "怎么", "为什么",
    }

    def __init__(self, config: Optional[CleanerConfig] = None):
        """
        初始化清理器

        Args:
            config: 清理配置，默认使用默认配置
        """
        self.config = config or CleanerConfig()

        # 合并所有拟声词
        self._all_sound_words: Set[str] = set()
        self._init_sound_words()

    def _init_sound_words(self):
        """初始化拟声词集合"""
        patterns = SoundEffectPatterns()

        if self.config.remove_sound_effects:
            # 笑声
            self._all_sound_words.update(patterns.CHINESE_LAUGHTER)
            self._all_sound_words.update(patterns.JAPANESE_LAUGHTER)

            # 语气词（保留部分）
            for word in patterns.CHINESE_INTERJECTIONS:
                if word not in self.KEEP_INTERJECTIONS:
                    self._all_sound_words.add(word)

            self._all_sound_words.update(patterns.ENGLISH_INTERJECTIONS)
            self._all_sound_words.update(patterns.ASMR_EFFECTS)

            # 添加自定义
            self._all_sound_words.update(self.config.custom_sound_words)

    def clean(self, text: str) -> str:
        """
        清理单条字幕文本

        Args:
            text: 原始字幕文本

        Returns:
            str: 清理后的文本
        """
        if not text or not text.strip():
            return ""

        original = text
        changed = True
        iteration = 0
        max_iterations = 5  # 防止无限循环

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1
            text = text.strip()

            # Step 1: 删除音效标签 [笑声], (音乐) 等
            if self.config.remove_sound_effects:
                new_text = self._remove_sound_tags(text)
                if new_text != text:
                    text = new_text
                    changed = True

            # Step 2: 删除说话人名字
            if self.config.remove_speaker_names:
                new_text = self._remove_speaker_names(text)
                if new_text != text:
                    text = new_text
                    changed = True

            # Step 3: 删除拟声词
            if self.config.remove_sound_effects:
                new_text = self._remove_sound_effects(text)
                if new_text != text:
                    text = new_text
                    changed = True

            # Step 4: 删除动作拟声词（撸啊撸、搓啊搓等）
            if self.config.remove_action_onomatopoeia:
                new_text = self._remove_action_onomatopoeia(text)
                if new_text != text:
                    text = new_text
                    changed = True

            # Step 5: 删除纯喘息/呻吟（啊~...、嗯...等）
            if self.config.remove_moaning:
                new_text = self._remove_moaning(text)
                if new_text != text:
                    text = new_text
                    changed = True

            # Step 6: 规范化空白
            new_text = self._normalize_whitespace(text)
            if new_text != text:
                text = new_text
                changed = True

        # Step 7: 删除纯标点或过短文本
        if self.config.remove_punctuation_only:
            text = self._remove_punctuation_only(text)

        # Step 8: 删除章节标题行
        if self.config.remove_chapter_titles:
            text = self._remove_chapter_titles(text)

        return text.strip()

    def clean_batch(self, texts: List[str]) -> List[str]:
        """
        批量清理字幕

        Args:
            texts: 原始字幕列表

        Returns:
            List[str]: 清理后的字幕列表
        """
        return [self.clean(text) for text in texts]

    def _remove_sound_tags(self, text: str) -> str:
        """删除音效标签 [笑声], (音乐) 等"""
        patterns = SoundEffectPatterns()

        # 匹配括号内常见音效词
        new_text = patterns.SOUND_TAG_PATTERN.sub("", text)

        # 匹配特殊音效符号
        new_text = re.sub(r"♪+", "", new_text)  # 音乐符号
        new_text = re.sub(r"♫+", "", new_text)
        new_text = re.sub(r"🎵+", "", new_text)
        new_text = re.sub(r"🎶+", "", new_text)
        new_text = re.sub(r"\~+", "~", new_text)  # 保留波浪号但合并

        return new_text

    def _remove_speaker_names(self, text: str) -> str:
        """删除说话人名字"""
        patterns = SoundEffectPatterns()

        for name, pattern in patterns.SPEAKER_PATTERNS:
            text = pattern.sub("", text)

        return text

    def _remove_sound_effects(self, text: str) -> str:
        """删除拟声词"""
        # 检查是否是纯拟声词
        patterns = SoundEffectPatterns()

        # 笑声重复模式（如 嘻嘻嘻、哈哈哈、嘻嘻、呵呵）— 不跳过短文本
        if patterns.LAUGHTER_REPEAT_PATTERN.match(text):
            return ""

        # 检查是否整体是拟声词
        if patterns.SOUND_WORD_ONLY_PATTERN.match(text):
            # 进一步检查：只有当文本只由拟声词组成时才删除
            # 使用单词边界匹配，确保拟声词是完整词语
            all_sound = True
            remaining = text
            for word in sorted(self._all_sound_words, key=len, reverse=True):
                if len(word) <= 1:
                    continue  # 跳过单字
                escaped = re.escape(word)
                # 移除这个拟声词
                remaining = re.sub(r'(?<![a-zA-Z0-9\u4e00-\u9fff])' + escaped + r'(?![a-zA-Z0-9\u4e00-\u9fff])', '', remaining, flags=re.IGNORECASE)
            
            # 清理残留的 w 序列
            remaining = re.sub(r'(?<![a-zA-Z])[wW]{3,}(?![a-zA-Z])', '', remaining)
            # 去掉标点和空白
            remaining = re.sub(r'[\s～~]+', '', remaining)
            
            # 如果清理后什么都没有，说明整个文本都是拟声词
            if not remaining.strip():
                return ""

        # 逐个移除拟声词
        result = text
        for word in sorted(self._all_sound_words, key=len, reverse=True):
            if len(word) <= 1:
                continue  # 跳过单字，避免误删
            
            # 使用单词边界匹配，避免误删正常词汇
            escaped = re.escape(word)
            
            # 中文/日文词语：检查是否是纯CJK字符组成
            has_cjk = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', word))
            
            if has_cjk:
                # CJK词语：使用更精确的边界匹配
                # 匹配完整的中文词语（前后不是字母数字或中文）
                # 使用零宽断言确保只匹配完整词语
                pattern = r'(?<![a-zA-Z0-9\u4e00-\u9fff])' + escaped + r'(?![a-zA-Z0-9\u4e00-\u9fff])'
            else:
                # 英文词语：使用单词边界
                pattern = r'\b' + escaped + r'\b'
            
            result = re.sub(pattern, "", result, flags=re.IGNORECASE)

        # 清理残留的特殊字符（只处理连续的w笑声）
        # 匹配独立的 w 序列（不是单词的一部分）
        # 使用负向先行/后行断言确保不是正常单词
        result = re.sub(r'(?<![a-zA-Z])[wW]{3,}(?![a-zA-Z])', '', result)

        return result

    def _normalize_whitespace(self, text: str) -> str:
        """规范化空白字符"""
        # 合并多个空格
        text = re.sub(r"\s+", " ", text)
        
        # 只清理首部残留的标点符号（删除拟声词后可能残留在开头）
        # 不清理尾部标点，因为ASMR文本的尾部标点是有意义的
        text = re.sub(r'^[\s\,\.\;\:\'\"\[\]\(\)\-—\uff0c\uff0e\u3001]+', '', text)  # 清理开头，\u3001是日文中点
        text = re.sub(r'^[\uff01\uff1f\uff08\uff09\uff3b\uff3d\u3000]+', '', text)  # 清理开头中文标点
        
        # 去除首尾空白
        text = text.strip()
        return text

    def _remove_punctuation_only(self, text: str) -> str:
        """删除纯标点符号的文本"""
        if not text:
            return ""

        # 移除后检查
        stripped = re.sub(r"[\s\.\,\!\?\~\-\:\;\"\'\[\]\(\)]+", "", text)

        # 如果只剩空白或标点，删除
        if len(stripped) < self.config.min_text_length:
            return ""

        return text

    def _remove_action_onomatopoeia(self, text: str) -> str:
        """
        删除动作拟声词（ASMR 特有）

        匹配模式: 单字重复 + 啊 + 单字重复，如:
        - 撸啊撸、搓啊搓、摸啊摸、揉啊揉
        - 撸啊撸啊撸啊撸啊（加长版）
        - 撸啊撸 / 爱理：哦—（带说话人的复合行）
        """
        patterns = SoundEffectPatterns()
        if patterns.ACTION_ONOMATOPOEIA_PATTERN.match(text.strip()):
            return ""
        return text

    def _remove_moaning(self, text: str) -> str:
        """
        删除纯喘息/呻吟行（非人声语义内容）

        匹配模式: 单个汉字 + 标点/省略号重复，如:
        - 啊~...
        - 嗯...嗯
        - 呃——
        - 啊、啊、
        - 啊……啊……
        但不匹配: "啊…真的吗"（有实际语言内容）
        """
        patterns = SoundEffectPatterns()
        if patterns.MOANING_PATTERN.match(text.strip()):
            return ""
        return text

    def _remove_chapter_titles(self, text: str) -> str:
        """
        删除章节标题行（LRC/VTT 中常见）

        匹配模式:
        - 纯数字 + 标题: "5 舔耳手交", "10 双重舔耳手交", "03 洗澡"
        - 但排除倒计时: "五……", "一……"
        - 但排除正常对话: 不以数字开头的句子
        """
        patterns = SoundEffectPatterns()
        stripped = text.strip()

        if not stripped:
            return text

        # 先检查是否是倒计时（不应删除）
        if patterns.COUNTDOWN_PATTERN.match(stripped):
            return text

        # 纯数字 + 标题格式
        if patterns.CHAPTER_TITLE_PATTERN.match(stripped):
            return ""

        return text

    def analyze(self, text: str) -> dict:
        """
        分析文本，返回清理信息

        Returns:
            dict: {
                "original": 原始文本,
                "cleaned": 清理后文本,
                "removed_sound_tags": 被删除的音效标签,
                "removed_speakers": 被删除的说话人,
                "removed_sound_words": 被删除的拟声词,
                "was_modified": 是否被修改,
            }
        """
        original = text
        removed_sound_tags = []
        removed_speakers = []
        removed_sound_words = []

        patterns = SoundEffectPatterns()

        # 记录被删除的音效标签
        for match in patterns.SOUND_TAG_PATTERN.finditer(text):
            removed_sound_tags.append(match.group())

        # 记录被删除的说话人
        for name, pattern in patterns.SPEAKER_PATTERNS:
            for match in pattern.finditer(text):
                removed_speakers.append(match.group())

        # 记录被删除的拟声词
        for word in self._all_sound_words:
            if word in text:
                removed_sound_words.append(word)

        cleaned = self.clean(text)

        return {
            "original": original,
            "cleaned": cleaned,
            "removed_sound_tags": list(set(removed_sound_tags)),
            "removed_speakers": list(set(removed_speakers)),
            "removed_sound_words": list(set(removed_sound_words)),
            "was_modified": original.strip() != cleaned,
        }


def clean_subtitle_text(
    text: str,
    remove_sound_effects: bool = True,
    remove_speaker_names: bool = True,
) -> str:
    """
    快速清理单条字幕文本

    Args:
        text: 原始文本
        remove_sound_effects: 是否删除拟声词
        remove_speaker_names: 是否删除说话人名字

    Returns:
        str: 清理后的文本
    """
    config = CleanerConfig(
        remove_sound_effects=remove_sound_effects,
        remove_speaker_names=remove_speaker_names,
    )
    cleaner = SubtitleCleaner(config)
    return cleaner.clean(text)


def clean_subtitle_batch(
    texts: List[str],
    remove_sound_effects: bool = True,
    remove_speaker_names: bool = True,
) -> List[str]:
    """
    快速批量清理字幕文本

    Args:
        texts: 原始文本列表
        remove_sound_effects: 是否删除拟声词
        remove_speaker_names: 是否删除说话人名字

    Returns:
        List[str]: 清理后的文本列表
    """
    config = CleanerConfig(
        remove_sound_effects=remove_sound_effects,
        remove_speaker_names=remove_speaker_names,
    )
    cleaner = SubtitleCleaner(config)
    return cleaner.clean_batch(texts)


# ===== 字幕格式验证 =====

class SubtitleFormatValidator:
    """
    字幕格式验证器

    功能：
    1. 验证字幕文件格式是否符合标准
    2. 检查必要字段
    3. 生成格式报告
    """

    VTT_REQUIRED = ["WEBVTT"]
    SRT_REQUIRED = ["-->"]
    LRC_REQUIRED = ["[00:"]  # LRC格式需要时间标签

    @classmethod
    def validate_file(cls, file_path: str) -> Tuple[bool, List[str], dict]:
        """
        验证字幕文件格式

        Args:
            file_path: 字幕文件路径

        Returns:
            Tuple[bool, List[str], dict]:
            - is_valid: 是否有效
            - errors: 错误列表
            - info: 文件信息
        """
        from pathlib import Path

        path = Path(file_path)
        ext = path.suffix.lower()
        errors = []
        info = {
            "format": ext.lstrip("."),
            "path": str(path),
            "exists": path.exists(),
            "size": 0,
            "line_count": 0,
        }

        if not path.exists():
            errors.append(f"文件不存在: {file_path}")
            return False, errors, info

        try:
            content = path.read_text(encoding="utf-8")
            lines = content.split("\n")
            info["line_count"] = len(lines)
            info["size"] = len(content)

            if ext == ".vtt":
                valid, errs = cls._validate_vtt(lines)
                errors.extend(errs)
            elif ext == ".srt":
                valid, errs = cls._validate_srt(lines)
                errors.extend(errs)
            elif ext == ".lrc":
                valid, errs = cls._validate_lrc(lines)
                errors.extend(errs)
            else:
                errors.append(f"不支持的格式: {ext}")

        except Exception as e:
            errors.append(f"读取文件失败: {e}")

        return len(errors) == 0, errors, info

    @classmethod
    def _validate_vtt(cls, lines: List[str]) -> Tuple[bool, List[str]]:
        """验证VTT格式"""
        errors = []

        if not any("WEBVTT" in line for line in lines[:10]):
            errors.append("缺少 WEBVTT 头部")

        timestamp_count = sum(1 for line in lines if "-->" in line)
        if timestamp_count == 0:
            errors.append("未找到时间戳")

        return len(errors) == 0, errors

    @classmethod
    def _validate_srt(cls, lines: List[str]) -> Tuple[bool, List[str]]:
        """验证SRT格式"""
        errors = []

        # 检查序号行
        has_sequence = False
        has_timestamps = False

        for line in lines:
            if re.match(r"^\d+$", line.strip()):
                has_sequence = True
            if "-->" in line:
                has_timestamps = True

        if not has_sequence:
            errors.append("未找到字幕序号（应为纯数字行）")

        if not has_timestamps:
            errors.append("未找到时间戳 (--> )")

        return len(errors) == 0, errors

    @classmethod
    def _validate_lrc(cls, lines: List[str]) -> Tuple[bool, List[str]]:
        """验证LRC格式"""
        errors = []

        # LRC格式通常有时间标签
        has_time_tags = any(re.match(r"\[\d{2}:\d{2}", line) for line in lines)

        if not has_time_tags:
            errors.append("未找到 LRC 时间标签 [mm:ss]")

        return len(errors) == 0, errors


def validate_subtitle_format(file_path: str) -> dict:
    """
    快速验证字幕格式

    Args:
        file_path: 字幕文件路径

    Returns:
        dict: {
            "valid": bool,
            "errors": [错误列表],
            "info": {文件信息},
        }
    """
    is_valid, errors, info = SubtitleFormatValidator.validate_file(file_path)
    return {
        "valid": is_valid,
        "errors": errors,
        "info": info,
    }


# ===== 导出便捷函数 =====

__all__ = [
    "SubtitleCleaner",
    "CleanerConfig",
    "SoundEffectPatterns",
    "SubtitleFormatValidator",
    "clean_subtitle_text",
    "clean_subtitle_batch",
    "validate_subtitle_format",
]
