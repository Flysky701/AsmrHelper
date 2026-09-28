"""
音色克隆音频预处理器 (Report #18 + 修正)

功能：
1. 音频兼容转换 (保留源采样率 / 16-bit PCM / Mono)
2. 双模式支持:
   - 匹配模式: 字幕语言 == 音频语言，使用字幕切割 + 字幕文本作为 ref_text
   - ASR模式: 字幕语言 != 音频语言 OR 无字幕，按音频语言识别文本和时间轴
3. 智能片段选择 (3-30s 范围，优先 5-10s)
4. 音频拼接 (交叉淡入淡出避免 pop/click)

关键原则：
- ref_text 必须是音频内容的真实转录，绝不能预设！
- 如果没有匹配的字幕，必须用 ASR 生成指定语言的文本

依赖:
- ffmpeg: 音频规格转换
- Faster-Whisper: ASR 识别
- 已有基础设施: cut_audio_by_subtitle, detect_subtitle_language
"""

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, List

import numpy as np
import soundfile as sf

from src.core.subtitles.text_utils import normalize_language_code
from src.utils import get_ffmpeg, get_audio_info, cut_audio_by_subtitle, ensure_dir


# ===== 常量定义 =====

# 保留该常量以兼容旧调用方。Qwen3-TTS 会在模型输入层处理采样率，
# 预处理不应将 16kHz 当作强制规格。
CLONE_SAMPLE_RATE = 16000  # legacy preference; preprocessing preserves source rate
CLONE_CHANNELS = 1  # Mono
CLONE_SAMPLE_FORMAT = "s16"  # 16-bit PCM
CLONE_MIN_DURATION = 3.0  # 秒
CLONE_MAX_DURATION = 30.0  # 秒
CLONE_OPTIMAL_MIN = 5.0  # 秒
CLONE_OPTIMAL_MAX = 10.0  # 秒
CLONE_TOTAL_MIN = 5.0  # 最少总时长
CLONE_TOTAL_MAX = 60.0  # 最多总时长（避免过长影响克隆速度）

# RMS 阈值（过滤静音段）
RMS_THRESHOLD = 0.01  # 静音阈值

# 以下阈值只用于候选片段的轻量启发式评分，不是语音识别模型。
# 数值刻意较保守：只硬性淘汰明显削波、近乎无活动音频和越界片段。
QUALITY_CLIP_LEVEL = 0.995
QUALITY_MAX_CLIPPING_RATIO = 0.01
QUALITY_MIN_ACTIVE_RATIO = 0.05
QUALITY_BOUNDARY_WINDOW_SECONDS = 0.05
QUALITY_MIN_ASR_RECOMMEND_CONFIDENCE = 0.55

# 交叉淡入淡出时长
CROSSFADE_DURATION = 0.01  # 10ms

# 安全区（切割前后保留）
SAFE_MARGIN = 0.05  # 50ms


@dataclass
class CloneAudioResult:
    """
    克隆音频准备结果

    Attributes:
        ref_audio_path: 最终的参考音频路径 (Mono/16-bit WAV，保留源采样率)
        ref_text: 与音频完全匹配的参考文本（必须来自字幕或ASR，不能预设！）
        mode: "matched" | "asr"
        segments_used: 使用的片段数
        total_duration: 总时长
        segments_info: 每段信息 [{path, start, end, text, duration, rms}]
        warnings: 警告信息
    """
    ref_audio_path: str
    ref_text: str
    mode: str  # "matched" | "asr"
    segments_used: int
    total_duration: float
    segments_info: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class AudioPreprocessor:
    """
    音色克隆音频预处理器

    使用方式:
        preprocessor = AudioPreprocessor()
        result = preprocessor.prepare_clone_audio(
            audio_path="path/to/vocal.wav",
            subtitle_path="path/to/subtitle.vtt",
            audio_language="ja",
            progress_callback=lambda msg, pct: print(f"{pct}%: {msg}")
        )
    """

    def __init__(self, output_dir: str = None):
        """
        初始化音频预处理器

        Args:
            output_dir: 输出目录，默认使用系统临时目录
        """
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path(tempfile.gettempdir()) / "asmr_clone_preprocess"
        ensure_dir(str(self.output_dir))

    def _report(self, callback: Optional[Callable], msg: str, percent: int = 0):
        """报告进度"""
        if callback:
            callback(msg, percent)
        print(f"[AudioPreprocessor] {msg}")

    def prepare_clone_audio(
        self,
        audio_path: str,
        subtitle_path: str = None,
        audio_language: str = "ja",
        progress_callback: Optional[Callable[[str, int], None]] = None,
        asr_segments: list = None,
    ) -> CloneAudioResult:
        """
        核心方法：为音色克隆准备合规的参考音频

        正确流程：
        1. 加载音频，检查格式
        2. 转换为兼容的 16-bit PCM / Mono WAV（保留源采样率）
        3. 判断输入来源:
           a. 字幕（语言匹配音频）→ 匹配模式：字幕时间轴 + 字幕文本
           b. 字幕（语言不匹配）OR 无字幕 → ASR模式：ASR时间轴 + ASR文本
        4. 切割音频
        5. 筛选合规片段 (3-30s)
        6. 拼接为完整参考音频 + 提取 ref_text
        7. 返回 CloneAudioResult

        重要：ref_text 必须是音频内容的真实转录，绝不能预设！

        Args:
            audio_path: 输入音频路径（人声分离后的）
            subtitle_path: 字幕文件路径（可选）
            audio_language: 音频语言 ("ja" | "zh" | "en")，日语音色克隆时为 "ja"
            progress_callback: 进度回调 (msg, progress_percent)
            asr_segments: 已有的 ASR 结果 [{start, end, text}, ...]（可选，避免重复 ASR）

        Returns:
            CloneAudioResult: 包含参考音频路径、ref_text 和模式信息
        """
        warnings = []

        # ===== Step 1: 加载并转换音频 =====
        self._report(progress_callback, "检查音频规格...", 5)

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        # 获取原始音频信息
        original_info = get_audio_info(str(audio_path))
        self._report(progress_callback,
            f"原始音频: {original_info['sample_rate']}Hz, "
            f"{original_info['channels']}ch, "
            f"{original_info['duration']:.1f}s", 10)

        # ===== Step 2: 音频规格转换 ======
        self._report(progress_callback, "转换音频规格 (Mono/16-bit，保留采样率)...", 15)

        converted_path = self._convert_to_clone_spec(
            str(audio_path),
            str(self.output_dir / f"{audio_path.stem}_clone.wav")
        )

        # 获取转换后的音频信息
        converted_info = get_audio_info(converted_path)

        # 检查是否需要转换
        needs_conversion = (
            original_info['channels'] != CLONE_CHANNELS or
            audio_path.suffix.lower() != ".wav"
        )
        if needs_conversion:
            self._report(progress_callback,
                f"已转换: {converted_info['sample_rate']}Hz, "
                f"{converted_info['channels']}ch", 20)
        else:
            self._report(progress_callback,
                "音频已是目标规格", 20)

        # ===== Step 3: 确定处理模式 =====
        subtitle_entries = []
        mode = "asr"  # 默认 ASR 模式
        audio_lang_normalized = normalize_language_code(audio_language)

        # 加载字幕（如果有）
        subtitle_lang = None
        if subtitle_path and Path(subtitle_path).exists():
            self._report(progress_callback, f"加载字幕: {Path(subtitle_path).name}", 22)

            from src.core.subtitles import (
                detect_subtitle_language,
                load_subtitle_with_timestamps,
            )
            subtitle_entries = load_subtitle_with_timestamps(subtitle_path)

            if subtitle_entries:
                # 检测字幕语言
                texts = [e.get("text", "") for e in subtitle_entries]
                subtitle_lang = detect_subtitle_language(texts)

                # 判断模式 - 统一 zh/zh_CN/zh_TW/en/ja 等代码
                subtitle_lang_normalized = normalize_language_code(subtitle_lang)

                if subtitle_lang_normalized == audio_lang_normalized:
                    # 字幕语言匹配音频语言 → 使用字幕（匹配模式）
                    mode = "matched"
                    self._report(progress_callback,
                        f"匹配模式: 字幕语言({subtitle_lang}) == 音频语言({audio_lang_normalized})", 25)
                else:
                    # 字幕语言不匹配 → 使用 ASR
                    self._report(progress_callback,
                        f"字幕语言({subtitle_lang}) != 音频语言({audio_lang_normalized})，将使用 ASR", 25)
                    warnings.append(f"字幕语言({subtitle_lang})与音频语言({audio_lang_normalized})不匹配，使用 ASR 识别")
                    subtitle_entries = []  # 不使用字幕
            else:
                warnings.append("字幕文件为空或无法解析")
                subtitle_entries = []
        else:
            warnings.append("未提供字幕文件")
            self._report(progress_callback, "无字幕文件，将使用 ASR 识别", 25)

        # ===== Step 3.5: ASR 识别（如果需要）=====
        if mode == "asr" or not subtitle_entries:
            # 如果已有 ASR 结果，直接复用，避免重复识别（节省时间和 GPU 资源）
            if asr_segments and len(asr_segments) > 0:
                self._report(progress_callback,
                    f"复用已有 ASR 结果: {len(asr_segments)} 条", 30)
                subtitle_entries = []
                for segment in asr_segments:
                    entry = {
                        "start": segment.get("start", 0),
                        "end": segment.get("end", 0),
                        "text": segment.get("text", ""),
                    }
                    if segment.get("asr_confidence") is not None:
                        entry["asr_confidence"] = segment["asr_confidence"]
                    subtitle_entries.append(entry)
                mode = "asr"
            else:
                self._report(progress_callback, "执行 ASR 识别（获取文本和时间轴）...", 30)

                try:
                    asr_segments = self._run_asr(
                        converted_path,
                        language=audio_lang_normalized,
                        progress_callback=progress_callback,
                    )

                    if asr_segments and len(asr_segments) > 0:
                        self._report(progress_callback,
                            f"ASR 识别完成: {len(asr_segments)} 条", 40)
                        mode = "asr"
                        subtitle_entries = asr_segments
                    else:
                        raise ValueError("ASR 识别结果为空")

                except Exception as asr_err:
                    self._report(progress_callback, f"ASR 识别失败: {asr_err}", 30)
                    warnings.append(f"ASR 识别失败: {asr_err}")
                    raise RuntimeError(f"无法获取音频文本内容: {asr_err}") from asr_err

        # ===== Step 4: 切割音频 =====
        self._report(progress_callback, "切割音频为片段...", 45)

        segments = self._cut_with_entries(
            converted_path, subtitle_entries, progress_callback
        )

        if not segments:
            raise ValueError("音频切割失败，无法获取有效片段")

        # ===== Step 5: 筛选合规片段 =====
        self._report(progress_callback, "筛选合规片段 (3-30s, RMS > 阈值)...", 65)

        valid_segments = self._filter_valid_segments(
            segments, progress_callback
        )

        if not valid_segments:
            raise ValueError("没有找到符合时长要求的音频片段 (3-30s)")

        self._report(progress_callback,
            f"有效片段: {len(valid_segments)}/{len(segments)}", 72)

        # ===== Step 6: 智能选择最佳片段 =====
        self._report(progress_callback, "智能选择最佳片段...", 75)

        selected = self._select_best_segments(valid_segments)

        if not selected:
            raise ValueError("没有通过质量校验的音色克隆候选片段")

        self._report(progress_callback,
            f"选用片段: {len(selected)}, 总时长: {sum(s['duration'] for s in selected):.1f}s", 80)

        # ===== Step 7: 拼接音频 =====
        self._report(progress_callback, "拼接音频片段...", 85)

        ref_audio_path = self._concatenate_audio_segments(
            selected,
            str(self.output_dir / f"ref_audio_{Path(audio_path).stem}.wav")
        )

        # ===== Step 8: 生成 ref_text（从选中片段中提取）=====
        ref_text = self._build_ref_text(selected)

        self._report(progress_callback,
            f"ref_text 生成完成: {len(ref_text)} 字符", 92)

        # ===== Step 9: 最终验证 =====
        final_info = get_audio_info(ref_audio_path)

        if final_info['duration'] < CLONE_TOTAL_MIN:
            warnings.append(f"总时长 ({final_info['duration']:.1f}s) 低于推荐值 ({CLONE_TOTAL_MIN}s)")

        if final_info['duration'] > CLONE_TOTAL_MAX:
            warnings.append(f"总时长 ({final_info['duration']:.1f}s) 超过建议最大值 ({CLONE_TOTAL_MAX}s)")

        self._report(progress_callback, "音频预处理完成!", 100)

        return CloneAudioResult(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            mode=mode,
            segments_used=len(selected),
            total_duration=final_info['duration'],
            segments_info=selected,
            warnings=warnings,
        )

    def _run_asr(
        self,
        audio_path: str,
        language: str = "ja",
        progress_callback: Optional[Callable] = None,
    ) -> List[dict]:
        """
        运行 ASR 识别

        Args:
            audio_path: 音频路径（Mono/PCM16 WAV）
            language: ASR 语言 ("ja" | "zh" | "en")
            progress_callback: 进度回调

        Returns:
            List[dict]: ASR 结果 [{start, end, text}, ...]
        """
        # 从配置读取 ASR 模型，默认 large-v3（最佳质量）
        try:
            from src.config import config
            model_size = config.get("processing.asr_model", "large-v3")
        except Exception:
            model_size = "large-v3"

        self._report(progress_callback, f"ASR 识别中 (模型: {model_size}, 语言: {language})...", 32)

        try:
            from src.core.engines.asr.service import AsrEngineRuntime

            # Voice analysis is a real ASR consumer. Route it through the
            # current engine runtime so catalog model IDs are normalized in
            # exactly the same way as direct ASR and Pipeline execution.
            runtime = AsrEngineRuntime()

            def transcribe(*, vad_filter: bool):
                return runtime.transcribe_file(
                    input_path=str(audio_path),
                    output_path=None,
                    profile={
                        "provider": "faster_whisper",
                        "model": str(model_size),
                        "common_options": {"language": language},
                        # Voice-analysis input often contains long silent gaps.
                        # Faster-Whisper keeps timestamps on the source timeline
                        # while VAD reduces silence hallucinations.
                        "provider_options": {"vad_filter": vad_filter},
                    },
                )

            document = transcribe(vad_filter=True)
            if not document.segments:
                # Silero VAD can miss extremely quiet whispers. Retry only
                # the zero-result case without VAD; normal calls still keep
                # VAD protection against long-silence hallucinations.
                self._report(
                    progress_callback,
                    "VAD 未检测到语音，关闭 VAD 重试极轻耳语识别...",
                    34,
                )
                document = transcribe(vad_filter=False)

            if not document.segments:
                raise ValueError("ASR 识别结果为空")

            # 转换为标准格式
            result = []
            for seg in document.segments:
                item = {
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "text": str(seg.text).strip(),
                }
                confidence = getattr(seg, "confidence", None)
                if confidence is not None:
                    try:
                        confidence_value = float(confidence)
                    except (TypeError, ValueError):
                        confidence_value = None
                    if confidence_value is not None and np.isfinite(confidence_value):
                        item["asr_confidence"] = float(
                            np.clip(confidence_value, 0.0, 1.0)
                        )
                result.append(item)

            return result

        except ImportError as exc:
            raise RuntimeError("ASR 模块不可用，请确保 Faster-Whisper 已安装") from exc
        except Exception as e:
            raise RuntimeError(f"ASR 识别失败: {e}") from e

    def _convert_to_clone_spec(self, audio_path: str, output_path: str) -> str:
        """
        转换音频为通用克隆输入格式:
        - 采样率: 保留源采样率
        - 位深: 16-bit PCM (PCM_S16LE)
        - 声道: Mono
        - 格式: WAV

        Args:
            audio_path: 输入音频路径
            output_path: 输出音频路径

        Returns:
            str: 转换后的音频路径
        """
        output_path = Path(output_path)
        ensure_dir(str(output_path.parent))

        cmd = [
            get_ffmpeg(),
            "-i", str(audio_path),
            "-ac", str(CLONE_CHANNELS),       # Mono
            "-sample_fmt", CLONE_SAMPLE_FORMAT,  # 16-bit PCM
            "-c:a", "pcm_s16le",
            str(output_path),
            "-y",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 转换失败: {result.stderr}")

        return str(output_path)

    def _cut_with_entries(
        self,
        audio_path: str,
        entries: List[dict],
        progress_callback: Optional[Callable] = None,
    ) -> List[dict]:
        """
        使用时间轴条目切割音频

        Args:
            audio_path: 音频路径
            entries: 时间轴条目 [{start, end, text}, ...]
            progress_callback: 进度回调

        Returns:
            List[dict]: 片段信息 [{path, start, end, text, duration, rms}, ...]
        """
        self._report(progress_callback, "使用时间轴切割音频...", 48)

        # 获取音频实际时长，所有时间轴都必须被限制在该范围内。
        audio_info = get_audio_info(audio_path)
        audio_duration = max(0.0, float(audio_info["duration"]))

        # 安全区只做小幅度扩展，不能让末句吞掉整段尾音频。
        cut_entries = []
        for entry in entries:
            try:
                raw_start = float(entry["start"])
                raw_end = float(entry["end"])
            except (KeyError, TypeError, ValueError):
                continue

            start = max(0.0, raw_start - SAFE_MARGIN)
            end = min(audio_duration, raw_end + SAFE_MARGIN)
            if start >= audio_duration or end <= start:
                continue

            cut_entry = {
                "start": start,
                "end": end,
                "text": entry.get("text", ""),
            }
            if entry.get("asr_confidence") is not None:
                cut_entry["asr_confidence"] = entry.get("asr_confidence")
            cut_entries.append(cut_entry)

        # 使用已有的 cut_audio_by_subtitle 函数
        segments = cut_audio_by_subtitle(
            audio_path,
            cut_entries,
            str(self.output_dir / "segments"),
            prefix="seg",
        )

        # 合并 segments 和已验证条目文本。不能使用原 entries 的
        # 索引，因为上面可能已跳过了非法时间轴。
        for i, seg in enumerate(segments):
            if i < len(cut_entries):
                seg["text"] = cut_entries[i].get("text", "")
                if cut_entries[i].get("asr_confidence") is not None:
                    seg["asr_confidence"] = cut_entries[i]["asr_confidence"]

        return segments

    def _filter_valid_segments(
        self,
        segments: List[dict],
        progress_callback: Optional[Callable] = None,
    ) -> List[dict]:
        """
        筛选合规片段

        合规条件:
        - 时长 >= 3s 且 <= 30s
        - RMS > 阈值（非静音）

        对于时长 < 3s 的短片段，尝试合并相邻片段。

        Args:
            segments: 原始片段列表
            progress_callback: 进度回调

        Returns:
            List[dict]: 有效片段列表
        """
        valid = []
        short_segments = []  # 仅收集可读且非静音的短片段

        for original_segment in segments:
            seg = dict(original_segment)
            path = str(seg.get("path") or "")
            if not path or not Path(path).is_file():
                continue

            # 先从最终候选文件计算时长和 RMS。不允许从裁剪前
            # 或已失效的路径借用质量数据。
            try:
                data, sr = sf.read(path)
                if sr <= 0 or data.size == 0 or not np.isfinite(data).all():
                    continue
                if len(data.shape) > 1:
                    data = np.mean(data, axis=1)
                actual_duration = len(data) / sr
                rms = float(np.sqrt(np.mean(data ** 2)))
            except Exception:
                continue

            if not np.isfinite(rms) or rms < RMS_THRESHOLD:
                continue

            seg["duration"] = actual_duration
            seg["rms"] = rms

            if actual_duration > CLONE_MAX_DURATION:
                # 没有词级时间戳时，任意截取长片段会使完整文本与
                # 音频错位。宁可淘汰，不构造错误的 ICL 引用。
                continue
            if actual_duration < CLONE_MIN_DURATION:
                short_segments.append(seg)
                continue

            valid.append(seg)

        # 如果合规片段数量不足，只合并已通过可读性和 RMS 检查
        # 的短片段。静音、损坏文件和过长片段不得回流。
        if short_segments and len(valid) < 3:
            self._report(progress_callback,
                f"发现 {len(short_segments)} 个短片段，尝试合并... (目标: 3-30s)", 68)
            merged = self._merge_short_segments(short_segments)
            if merged:
                valid.extend(merged)

        return valid

    def _merge_short_segments(self, segments: List[dict]) -> List[dict]:
        """
        合并短片段以满足最低时长要求

        Args:
            segments: 原始片段列表

        Returns:
            List[dict]: 合并后的片段列表
        """
        if not segments:
            return []

        # 按开始时间排序
        sorted_segs = sorted(segments, key=lambda x: x.get("start", 0))

        merged = []
        current_group = []

        for seg in sorted_segs:
            if not current_group:
                current_group.append(seg)
            else:
                # 检查是否可以合并（相邻片段）
                last_end = current_group[-1].get("end", 0)
                curr_start = seg.get("start", 0)
                gap = curr_start - last_end

                if gap < 1.0:  # 间隔小于1秒，可以合并
                    current_group.append(seg)
                else:
                    # 处理当前组
                    if len(current_group) >= 2:
                        merged_result = self._do_merge(current_group)
                        if merged_result:
                            merged.append(merged_result)
                    current_group = [seg]

        # 处理最后一组
        if len(current_group) >= 2:
            merged_result = self._do_merge(current_group)
            if merged_result:
                merged.append(merged_result)

        return merged

    def _do_merge(self, segments: List[dict]) -> Optional[dict]:
        """执行片段合并"""
        if len(segments) < 2:
            return None

        # 合并路径
        merged_path = self.output_dir / "segments" / f"merged_{segments[0].get('index', 0)}.wav"

        # 计算新的时间范围
        start = segments[0].get("start", 0)
        end = segments[-1].get("end", 0)

        # 时间轴跨度过长时无论实际怎样拼接都不应作为一个引用。
        if end - start > CLONE_MAX_DURATION:
            return None

        # 读取并合并音频
        try:
            all_data = []
            sample_rate = None
            merged_texts = []
            asr_confidences = []
            for seg in segments:
                path = str(seg.get("path") or "")
                text = str(seg.get("text") or "").strip()
                if not path or not Path(path).is_file():
                    return None

                data, sr = sf.read(path)
                if sr <= 0 or data.size == 0 or not np.isfinite(data).all():
                    return None
                if len(data.shape) > 1:
                    data = np.mean(data, axis=1)
                if sample_rate is None:
                    sample_rate = sr
                elif sr != sample_rate:
                    return None
                all_data.append(data)
                if text:
                    merged_texts.append(text)
                if seg.get("asr_confidence") is not None:
                    try:
                        confidence = float(seg["asr_confidence"])
                    except (TypeError, ValueError):
                        pass
                    else:
                        if np.isfinite(confidence):
                            asr_confidences.append(
                                float(np.clip(confidence, 0.0, 1.0))
                            )

            # 拼接（带交叉淡入淡出）
            if len(all_data) == 1:
                merged_data = all_data[0]
            else:
                merged_data = all_data[0]
                for i in range(1, len(all_data)):
                    crossfade_samples = int(CROSSFADE_DURATION * sample_rate)
                    if crossfade_samples <= 0:
                        merged_data = np.concatenate([merged_data, all_data[i]])
                        continue
                    fade_out = merged_data[-crossfade_samples:] if len(merged_data) >= crossfade_samples else merged_data
                    fade_in = all_data[i][:crossfade_samples] if len(all_data[i]) >= crossfade_samples else all_data[i]
                    if len(fade_out) == len(fade_in):
                        fade_out_weight = np.linspace(1.0, 0.0, len(fade_out))
                        fade_in_weight = np.linspace(0.0, 1.0, len(fade_in))
                        crossfade = fade_out * fade_out_weight + fade_in * fade_in_weight
                        merged_data = np.concatenate([merged_data[:-crossfade_samples], crossfade, all_data[i][crossfade_samples:]])
                    else:
                        merged_data = np.concatenate([merged_data, all_data[i]])
            # 必须根据拼接后的实际数据重新验证。时间轴中的 gap
            # 不会自动变成输出音频，因此不能用 end-start 代替实际时长。
            actual_duration = len(merged_data) / sample_rate
            rms = float(np.sqrt(np.mean(merged_data ** 2)))
            if (
                actual_duration < CLONE_MIN_DURATION
                or actual_duration > CLONE_MAX_DURATION
                or not np.isfinite(rms)
                or rms < RMS_THRESHOLD
            ):
                return None

            ensure_dir(str(merged_path.parent))
            sf.write(str(merged_path), merged_data, sample_rate, subtype="PCM_16")

            result = {
                "path": str(merged_path),
                "start": start,
                "end": end,
                "text": " ".join(merged_texts),  # 合并文本
                "duration": actual_duration,
                "rms": rms,
            }
            if asr_confidences:
                # Conservative aggregation: one weak sub-segment should keep
                # a merged reference out of automatic recommendation.
                result["asr_confidence"] = min(asr_confidences)
            return result
        except Exception:
            return None

    def _trim_segment(self, segment: dict) -> dict:
        """
        长片段不再进行无文本对齐的中间截取。

        Args:
            segment: 片段信息

        Returns:
            dict: 未超限时原样返回
        """
        duration = segment.get("duration", 0)
        if duration <= CLONE_MAX_DURATION:
            return segment
        raise ValueError("长片段需要词级时间戳才能在保持音文对齐的前提下裁剪")

    def _select_best_segments(self, segments: List[dict]) -> List[dict]:
        """
        智能选择最佳片段用于克隆 - 改进版：单段最优选策略

        关键改进：
        - 优先选择单个最佳片段（5-10s），避免多段拼接导致的音文对齐问题
        - 只有当单片段时长不足时，才考虑多段拼接

        优先级:
        1. 时长 5-10s 的单个片段（效果最稳定，优先单段）
        2. 时长 3-5s 的单个片段（次优单段）
        3. 多段拼接（仅当单段不足时使用）

        总时长控制:
        - 最少: 5s
        - 推荐: 5-10s（单段最优）
        - 最多: 30s

        Args:
            segments: 有效片段列表

        Returns:
            List[dict]: 选中的片段列表（优先返回单段）
        """
        if not segments:
            return []

        def ensure_quality(segment: dict) -> None:
            score = segment.get("quality_score", segment.get("score"))
            if "eligible" in segment and score is not None:
                segment.setdefault("quality_score", int(score))
                segment.setdefault("score", int(score))
                return

            quality = self.evaluate_segment_quality(segment, require_text=True)
            segment["quality_score"] = quality["score"]
            segment["quality_label"] = quality["label"]
            segment["score"] = quality["score"]
            segment["label"] = quality["label"]
            segment["details"] = quality["details"]
            segment["eligible"] = quality["eligible"]
            segment["reasons"] = quality["reasons"]

        def ranking_key(segment: dict) -> tuple[int, float]:
            score = segment.get("quality_score", segment.get("score", 0))
            details = segment.get("details") or {}
            rms = segment.get("rms", details.get("rms", 0.0))
            return int(score), float(rms)

        # 推荐必须只从通过硬性校验的候选中产生。
        # analyze_segments 已按 ICL/x-vector 模式评分的片段
        # 会保留其 eligible，不会被默认的 ICL 文本规则重新评估。
        eligible_segments = []
        for segment in segments:
            ensure_quality(segment)
            if segment.get("eligible") is True:
                details = segment.get("details") or {}
                asr_confidence = details.get("asr_confidence")
                try:
                    low_asr_confidence = (
                        asr_confidence is not None
                        and float(asr_confidence)
                        < QUALITY_MIN_ASR_RECOMMEND_CONFIDENCE
                    )
                except (TypeError, ValueError):
                    low_asr_confidence = False
                if low_asr_confidence:
                    continue
                eligible_segments.append(segment)

        if not eligible_segments:
            return []

        # 按优先级分类
        optimal = []  # 5-10s（最优单段范围）
        acceptable = []  # 3-5s（次优单段范围）
        long_segments = []  # >10s

        for seg in eligible_segments:
            duration = seg.get("duration", 0)
            if CLONE_OPTIMAL_MIN <= duration <= CLONE_OPTIMAL_MAX:
                optimal.append(seg)
            elif CLONE_MIN_DURATION <= duration < CLONE_OPTIMAL_MIN:
                acceptable.append(seg)
            else:
                long_segments.append(seg)

        # ===== 策略1: 优先选择单个最佳片段 =====
        # 优先使用综合质量分，RMS 只用作同分时的次级排序。
        if optimal:
            best_seg = max(optimal, key=ranking_key)
            return [best_seg]

        # 策略2: 选择综合质量最高的 3-5s 片段
        if acceptable:
            best_seg = max(acceptable, key=ranking_key)
            return [best_seg]

        # 策略3: 选择综合质量最高的 10-30s 长片段
        if long_segments:
            best_seg = max(long_segments, key=ranking_key)
            return [best_seg]

        return []

    def _concatenate_audio_segments(
        self,
        segments: List[dict],
        output_path: str,
    ) -> str:
        """
        拼接音频片段（带交叉淡入淡出）

        Args:
            segments: 选中的片段列表
            output_path: 输出路径

        Returns:
            str: 拼接后的音频路径
        """
        if not segments:
            raise ValueError("没有片段可拼接")

        output_path = Path(output_path)
        ensure_dir(str(output_path.parent))

        # 统一读写所有片段（包括单片段），保证输出总是
        # Mono PCM16 WAV，而不是意外保留源文件的 FLOAT 子类型。
        all_data = None
        sample_rate = None

        for i, seg in enumerate(segments):
            data, sr = sf.read(seg["path"])
            if data.size == 0 or not np.isfinite(data).all():
                raise ValueError(f"片段音频无效: {seg['path']}")
            if len(data.shape) > 1:
                data = np.mean(data, axis=1)

            if sample_rate is None:
                sample_rate = sr
            elif sr != sample_rate:
                raise ValueError("选中片段的采样率不一致")

            if i > 0 and all_data is not None and len(all_data) > 0:
                # 添加交叉淡入淡出
                crossfade_samples = int(CROSSFADE_DURATION * sample_rate)
                if crossfade_samples <= 0:
                    all_data = np.concatenate([all_data, data])
                    continue
                fade_out = all_data[-crossfade_samples:] if len(all_data) >= crossfade_samples else all_data
                fade_in = data[:crossfade_samples] if len(data) >= crossfade_samples else data

                # 淡出曲线 (标准交叉淡入淡出: 1.0→0.0, 0.0→1.0)
                fade_out_weight = np.linspace(1.0, 0.0, len(fade_out))
                fade_in_weight = np.linspace(0.0, 1.0, len(fade_in))

                # 交叉淡入淡出
                if len(fade_out) == len(fade_in):
                    crossfade = fade_out * fade_out_weight + fade_in * fade_in_weight
                    all_data = np.concatenate([all_data[:-crossfade_samples], crossfade, data[crossfade_samples:]])
                else:
                    all_data = np.concatenate([all_data, data])
            else:
                all_data = data

        # 保存
        sf.write(str(output_path), all_data, sample_rate, subtype="PCM_16")
        return str(output_path)

    def _build_ref_text(self, segments: List[dict]) -> str:
        """
        生成 ref_text（从选中片段中提取文本）

        重要：ref_text 必须是音频内容的真实转录，绝不能预设！

        Args:
            segments: 选中的片段 [{path, start, end, text, duration, rms}, ...]

        Returns:
            str: 参考文本（来自片段的真实文本）
        """
        texts = []
        for seg in segments:
            text = seg.get("text", "").strip()
            if text:
                texts.append(text)

        if not texts:
            raise ValueError("没有找到任何文本内容！ASR 识别可能失败。")

        return " ".join(texts)


    # ===== 交互式预览模式方法 =====

    def _detect_energy_entries(self, audio_path: str) -> List[dict]:
        """使用轻量能量 VAD 生成无文本候选时间段。"""
        data, sample_rate = sf.read(audio_path)
        if sample_rate <= 0 or data.size == 0 or not np.isfinite(data).all():
            return []
        if len(data.shape) > 1:
            data = np.mean(data, axis=1)

        frame_samples = max(1, int(sample_rate * 0.03))
        hop_samples = max(1, int(sample_rate * 0.01))
        max_silence_seconds = 0.30
        audio_duration = len(data) / sample_rate

        frame_positions = list(range(0, len(data), hop_samples))
        frame_rms = [
            float(np.sqrt(np.mean(data[start:start + frame_samples] ** 2)))
            for start in frame_positions
            if len(data[start:start + frame_samples]) > 0
        ]

        regions: List[tuple[float, float]] = []
        region_start: float | None = None
        last_voice_end = 0.0
        for start_sample, rms in zip(frame_positions, frame_rms, strict=True):
            frame_start = start_sample / sample_rate
            frame_end = min(audio_duration, (start_sample + frame_samples) / sample_rate)
            if np.isfinite(rms) and rms >= RMS_THRESHOLD:
                if region_start is None:
                    region_start = frame_start
                last_voice_end = frame_end
            elif (
                region_start is not None
                and frame_start - last_voice_end >= max_silence_seconds
            ):
                regions.append((region_start, last_voice_end))
                region_start = None

        if region_start is not None:
            regions.append((region_start, last_voice_end))

        entries: List[dict] = []
        for region_start, region_end in regions:
            start = max(0.0, region_start - SAFE_MARGIN)
            end = min(audio_duration, region_end + SAFE_MARGIN)
            # 连续语音可能超过 30s，按最佳上限分成独立候选，
            # 避免后续为了时长而任意截文本。x-vector 模式无文本。
            cursor = start
            while cursor < end:
                chunk_end = min(end, cursor + CLONE_OPTIMAL_MAX)
                entries.append({"start": cursor, "end": chunk_end, "text": ""})
                cursor = chunk_end

        return entries

    def analyze_segments(
        self,
        audio_path: str,
        subtitle_path: str = None,
        audio_language: str = "ja",
        progress_callback: Optional[Callable] = None,
        require_text: bool = True,
    ) -> dict:
        """
        分析音频片段（不自动选择，用于 GUI 预览模式）

        与 prepare_clone_audio 的区别：
        - 不自动选择最佳片段
        - 返回所有有效片段及其质量评分
        - 用于 GUI 展示和用户手动选择
        - require_text=False 时使用轻量能量 VAD，不启动 ASR

        Returns:
            dict: {
                "segments": List[dict],
                "mode": str,
                "total_raw": int,
                "valid_count": int,
                "recommended_indices": List[int],
                "audio_info": dict,
                "warnings": List[str],
                "converted_audio_path": str,
            }
        """
        warnings = []

        # Step 1: 加载并转换音频
        self._report(progress_callback, "检查音频规格...", 5)
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        original_info = get_audio_info(str(audio_path))
        self._report(progress_callback,
            f"原始音频: {original_info['sample_rate']}Hz, "
            f"{original_info['channels']}ch, "
            f"{original_info['duration']:.1f}s", 10)

        # Step 2: 转换音频规格
        self._report(progress_callback, "转换音频规格 (Mono/16-bit，保留采样率)...", 15)
        converted_path = self._convert_to_clone_spec(
            str(audio_path),
            str(self.output_dir / f"{audio_path.stem}_clone.wav")
        )

        # Step 3: 确定模式
        subtitle_entries = []
        mode = "asr"
        audio_lang_normalized = normalize_language_code(audio_language)
        if not require_text:
            self._report(progress_callback, "使用轻量能量 VAD 生成 x-vector 候选片段...", 30)
            subtitle_entries = self._detect_energy_entries(converted_path)
            mode = "energy"
            if not subtitle_entries:
                raise ValueError("未检测到可用的非静音音频片段")
        elif subtitle_path and Path(subtitle_path).exists():
            self._report(progress_callback, f"加载字幕: {Path(subtitle_path).name}", 20)
            from src.core.subtitles import (
                detect_subtitle_language,
                load_subtitle_with_timestamps,
            )
            subtitle_entries = load_subtitle_with_timestamps(subtitle_path)
            if subtitle_entries:
                texts = [e.get("text", "") for e in subtitle_entries]
                subtitle_lang = detect_subtitle_language(texts)
                if normalize_language_code(subtitle_lang) == audio_lang_normalized:
                    mode = "matched"
                    self._report(progress_callback,
                        f"匹配模式: 字幕语言({subtitle_lang}) == 音频语言({audio_lang_normalized})", 25)
                else:
                    self._report(progress_callback,
                        f"字幕语言({subtitle_lang}) != 音频语言({audio_lang_normalized})，将使用 ASR", 25)
                    warnings.append(f"字幕语言({subtitle_lang})与音频语言({audio_lang_normalized})不匹配")
                    subtitle_entries = []
            else:
                warnings.append("字幕文件为空")
                subtitle_entries = []
        elif require_text:
            self._report(progress_callback, "无字幕文件，将使用 ASR 识别", 25)

        # Step 3.5: ASR
        if require_text and (mode == "asr" or not subtitle_entries):
            self._report(progress_callback, "执行 ASR 识别...", 30)
            try:
                asr_segments = self._run_asr(
                    converted_path,
                    language=audio_lang_normalized,
                    progress_callback=progress_callback,
                )
                if asr_segments:
                    mode = "asr"
                    subtitle_entries = asr_segments
                    self._report(progress_callback, f"ASR 识别完成: {len(asr_segments)} 条", 50)
                else:
                    raise ValueError("ASR 识别结果为空")
            except Exception as asr_err:
                self._report(progress_callback, f"ASR 识别失败: {asr_err}", 30)
                warnings.append(f"ASR 识别失败: {asr_err}")
                raise RuntimeError(f"无法获取音频文本内容: {asr_err}") from asr_err

        # Step 4: 切割音频
        self._report(progress_callback, "切割音频为片段...", 55)
        segments = self._cut_with_entries(converted_path, subtitle_entries, progress_callback)
        if not segments:
            raise ValueError("音频切割失败，无法获取有效片段")

        # Step 5: 筛选合规片段
        self._report(progress_callback, "筛选合规片段...", 70)
        valid_segments = self._filter_valid_segments(segments, progress_callback)
        if not valid_segments:
            raise ValueError("没有找到符合时长要求的音频片段 (3-30s)")

        # Step 6: 评估质量
        self._report(progress_callback, "评估片段质量...", 85)
        for i, seg in enumerate(valid_segments):
            quality = self.evaluate_segment_quality(seg, require_text=require_text)
            # 保留旧 GUI 字段，同时输出应用层约定的标准字段。
            seg["quality_score"] = quality["score"]
            seg["quality_label"] = quality["label"]
            seg["score"] = quality["score"]
            seg["label"] = quality["label"]
            seg["details"] = quality["details"]
            seg["eligible"] = quality["eligible"]
            seg["reasons"] = quality["reasons"]
            seg["index"] = i

        # Step 7: 自动推荐
        recommended = self._select_best_segments(valid_segments)
        recommended_indices = []
        for rec in recommended:
            for i, seg in enumerate(valid_segments):
                if seg is rec:
                    recommended_indices.append(i)
                    seg["selected"] = True
                    break

        self._report(progress_callback,
            f"分析完成: {len(valid_segments)} 个有效片段, 推荐 {len(recommended_indices)} 个", 100)

        return {
            "segments": valid_segments,
            "mode": mode,
            "total_raw": len(segments),
            "valid_count": len(valid_segments),
            "recommended_indices": recommended_indices,
            "audio_info": {
                "original_sample_rate": original_info["sample_rate"],
                "original_channels": original_info["channels"],
                "original_duration": original_info["duration"],
            },
            "warnings": warnings,
            "converted_audio_path": converted_path,
        }

    def evaluate_segment_quality(
        self,
        segment: dict,
        *,
        require_text: bool = True,
    ) -> dict:
        """用轻量启发式指标评估候选片段质量 (0-100)。

        这里的 active ratio 和 SNR 是基于短时 RMS 的近似值，不能代替
        VAD/噪声分类模型。它们只用于排序和拒绝明显无效的候选，
        避免为这一步引入额外模型或重依赖。

        Args:
            segment: 包含 path/start/end/duration/text 的候选片段。
            require_text: ICL 模式为 True；x-vector 模式为 False。

        Returns:
            包含 score/label/eligible/reasons/details 的可解释评分。
        """
        reasons: list[str] = []
        hard_reasons: list[str] = []

        def add_reason(reason: str, *, hard: bool = False) -> None:
            if reason not in reasons:
                reasons.append(reason)
            if hard and reason not in hard_reasons:
                hard_reasons.append(reason)

        def finite_float(value) -> float | None:
            try:
                result = float(value)
            except (TypeError, ValueError):
                return None
            return result if np.isfinite(result) else None

        reported_duration = finite_float(segment.get("duration"))
        duration = reported_duration or 0.0
        rms = finite_float(segment.get("rms")) or 0.0
        peak = 0.0
        clipping_ratio = 0.0
        active_ratio = 0.0
        active_threshold = RMS_THRESHOLD
        boundary_start_rms = 0.0
        boundary_end_rms = 0.0
        boundary_energy_ratio = 0.0
        noise_rms = 0.0
        signal_rms = 0.0
        snr_db = 0.0
        audio_readable = False

        path = str(segment.get("path") or "")
        if not path or not Path(path).is_file():
            add_reason("音频文件不存在或不可读", hard=True)
        else:
            try:
                data, sample_rate = sf.read(path)
                data = np.asarray(data, dtype=np.float64)
                if data.ndim > 1:
                    data = np.mean(data, axis=1)
                data = np.ravel(data)

                if (
                    sample_rate <= 0
                    or data.size == 0
                    or not np.isfinite(data).all()
                ):
                    add_reason("音频数据为空或包含非有限值", hard=True)
                else:
                    audio_readable = True
                    duration = data.size / sample_rate
                    absolute = np.abs(data)
                    rms = float(np.sqrt(np.mean(data ** 2)))
                    peak = float(np.max(absolute))
                    clipping_ratio = float(
                        np.mean(absolute >= QUALITY_CLIP_LEVEL)
                    )

                    # 30ms 帧 / 10ms hop，仅基于能量估计活动比例。
                    frame_samples = max(1, int(sample_rate * 0.03))
                    hop_samples = max(1, int(sample_rate * 0.01))
                    frame_rms = np.asarray(
                        [
                            np.sqrt(np.mean(data[start:start + frame_samples] ** 2))
                            for start in range(0, data.size, hop_samples)
                            if data[start:start + frame_samples].size > 0
                        ],
                        dtype=np.float64,
                    )
                    noise_rms = float(np.percentile(frame_rms, 20))
                    upper_rms = float(np.percentile(frame_rms, 90))
                    dynamic_threshold = noise_rms + max(
                        0.003,
                        0.2 * max(0.0, upper_rms - noise_rms),
                    )
                    threshold_cap = max(RMS_THRESHOLD, upper_rms * 0.8)
                    active_threshold = max(
                        RMS_THRESHOLD,
                        min(dynamic_threshold, threshold_cap),
                    )
                    active_frames = frame_rms >= active_threshold
                    active_ratio = float(np.mean(active_frames))
                    if np.any(active_frames):
                        signal_rms = float(np.percentile(frame_rms[active_frames], 75))
                        snr_db = float(
                            np.clip(
                                20.0 * np.log10(
                                    (signal_rms + 1e-8) / (noise_rms + 1e-8)
                                ),
                                0.0,
                                60.0,
                            )
                        )

                    boundary_samples = min(
                        data.size,
                        max(1, int(sample_rate * QUALITY_BOUNDARY_WINDOW_SECONDS)),
                    )
                    boundary_start_rms = float(
                        np.sqrt(np.mean(data[:boundary_samples] ** 2))
                    )
                    boundary_end_rms = float(
                        np.sqrt(np.mean(data[-boundary_samples:] ** 2))
                    )
                    boundary_energy_ratio = max(
                        boundary_start_rms,
                        boundary_end_rms,
                    ) / max(rms, 1e-8)
            except (OSError, RuntimeError, ValueError):
                add_reason("音频文件不存在或不可读", hard=True)

        # 时长和时间轴越界是硬失败；未提供时间轴时不做猜测。
        if reported_duration is None and segment.get("duration") is not None:
            add_reason("片段时长无效或越界", hard=True)
        elif reported_duration is not None and not (
            CLONE_MIN_DURATION <= reported_duration <= CLONE_MAX_DURATION
        ):
            add_reason("片段时长无效或越界", hard=True)

        if not CLONE_MIN_DURATION <= duration <= CLONE_MAX_DURATION:
            add_reason("片段实际时长超出 3-30 秒范围", hard=True)

        start_value = segment.get("start")
        end_value = segment.get("end")
        start = finite_float(start_value) if start_value is not None else None
        end = finite_float(end_value) if end_value is not None else None
        if start_value is not None and (start is None or start < 0.0):
            add_reason("片段时间轴越界", hard=True)
        if end_value is not None and (end is None or end < 0.0):
            add_reason("片段时间轴越界", hard=True)
        if start is not None and end is not None:
            if end <= start or end - start > CLONE_MAX_DURATION + 0.1:
                add_reason("片段时间轴越界", hard=True)

        source_duration_value = segment.get(
            "source_duration",
            segment.get("audio_duration"),
        )
        source_duration = finite_float(source_duration_value)
        if (
            source_duration_value is not None
            and (
                source_duration is None
                or source_duration < 0.0
                or (end is not None and end > source_duration + SAFE_MARGIN)
            )
        ):
            add_reason("片段时间轴越界", hard=True)

        text = str(segment.get("text") or "").strip()
        text_length = len("".join(text.split()))
        asr_confidence_value = finite_float(segment.get("asr_confidence"))
        asr_confidence = (
            float(np.clip(asr_confidence_value, 0.0, 1.0))
            if asr_confidence_value is not None
            else None
        )
        if require_text and not text:
            add_reason("ICL 模式缺少与音频对齐的参考文本", hard=True)
        if (
            require_text
            and asr_confidence is not None
            and asr_confidence < QUALITY_MIN_ASR_RECOMMEND_CONFIDENCE
        ):
            add_reason("ASR 置信度偏低，请试听并逐字核对参考文本")

        if audio_readable and (
            rms < RMS_THRESHOLD or active_ratio < QUALITY_MIN_ACTIVE_RATIO
        ):
            add_reason("未检测到有效语音或活动音频", hard=True)

        if clipping_ratio >= QUALITY_MAX_CLIPPING_RATIO:
            add_reason(
                f"明显削波（样本占比 {clipping_ratio:.2%}）",
                hard=True,
            )
        elif clipping_ratio >= 0.002:
            add_reason(f"存在少量削波样本（{clipping_ratio:.2%}）")

        if peak >= 0.98:
            add_reason("峰值接近满幅，动态余量偏小")
        if audio_readable and boundary_energy_ratio > 0.8:
            add_reason("边界能量偏高，切点可能位于发声中")
        if audio_readable and active_ratio >= QUALITY_MIN_ACTIVE_RATIO and snr_db < 8.0:
            add_reason("启发式估算信噪比偏低")

        # 子分数据各指标的原始值独立计算，便于 UI 解释和调参。
        if CLONE_OPTIMAL_MIN <= duration <= CLONE_OPTIMAL_MAX:
            duration_score = 100.0
        elif CLONE_MIN_DURATION <= duration < CLONE_OPTIMAL_MIN:
            duration_score = 60.0 + 40.0 * (
                (duration - CLONE_MIN_DURATION)
                / (CLONE_OPTIMAL_MIN - CLONE_MIN_DURATION)
            )
        elif CLONE_OPTIMAL_MAX < duration <= CLONE_MAX_DURATION:
            duration_score = 60.0 + 40.0 * (
                (CLONE_MAX_DURATION - duration)
                / (CLONE_MAX_DURATION - CLONE_OPTIMAL_MAX)
            )
        else:
            duration_score = 0.0

        if rms < 0.005:
            rms_score = 0.0
        elif rms < 0.01:
            rms_score = 20.0 + 30.0 * (rms - 0.005) / 0.005
        elif rms < 0.03:
            rms_score = 50.0 + 50.0 * (rms - 0.01) / 0.02
        elif rms <= 0.25:
            rms_score = 100.0
        elif rms <= 0.50:
            rms_score = 100.0 - 70.0 * (rms - 0.25) / 0.25
        else:
            rms_score = max(0.0, 30.0 - 60.0 * (rms - 0.50))

        if not require_text:
            # x-vector 不使用参考文本，因此该维度按满分中性处理。
            text_score = 100.0
        elif text_length >= 10:
            text_score = 100.0
        elif text_length >= 5:
            text_score = 70.0 + 30.0 * (text_length - 5) / 5.0
        elif text_length >= 1:
            text_score = 40.0 + 30.0 * (text_length - 1) / 4.0
        else:
            text_score = 0.0
        if require_text and asr_confidence is not None:
            # Confidence is a soft quality signal only. A user may correct
            # confirmed_text and still use the candidate manually.
            text_score *= 0.5 + 0.5 * asr_confidence

        if clipping_ratio <= 0.0001:
            clipping_score = 100.0
        elif clipping_ratio <= 0.001:
            clipping_score = 100.0 - 15.0 * (clipping_ratio - 0.0001) / 0.0009
        elif clipping_ratio <= 0.005:
            clipping_score = 85.0 - 45.0 * (clipping_ratio - 0.001) / 0.004
        elif clipping_ratio < QUALITY_MAX_CLIPPING_RATIO:
            clipping_score = 40.0 * (
                QUALITY_MAX_CLIPPING_RATIO - clipping_ratio
            ) / 0.005
        else:
            clipping_score = 0.0

        if peak <= 0.90:
            peak_score = 100.0 if peak > 0.0 else 0.0
        elif peak <= 0.98:
            peak_score = 100.0 - 30.0 * (peak - 0.90) / 0.08
        elif peak <= QUALITY_CLIP_LEVEL:
            peak_score = 70.0 - 30.0 * (peak - 0.98) / 0.015
        else:
            peak_score = max(0.0, 40.0 - 40.0 * (peak - 0.995) / 0.005)

        if active_ratio < QUALITY_MIN_ACTIVE_RATIO:
            active_score = 0.0
        elif active_ratio < 0.20:
            active_score = 40.0 + 60.0 * (
                active_ratio - QUALITY_MIN_ACTIVE_RATIO
            ) / (0.20 - QUALITY_MIN_ACTIVE_RATIO)
        elif active_ratio <= 0.90:
            active_score = 100.0
        else:
            active_score = 100.0 - 15.0 * (active_ratio - 0.90) / 0.10

        if boundary_energy_ratio <= 0.25:
            boundary_score = 100.0
        elif boundary_energy_ratio <= 0.60:
            boundary_score = 100.0 - 20.0 * (boundary_energy_ratio - 0.25) / 0.35
        elif boundary_energy_ratio <= 1.0:
            boundary_score = 80.0 - 40.0 * (boundary_energy_ratio - 0.60) / 0.40
        elif boundary_energy_ratio <= 1.5:
            boundary_score = 40.0 - 40.0 * (boundary_energy_ratio - 1.0) / 0.5
        else:
            boundary_score = 0.0

        if snr_db >= 20.0:
            snr_score = 100.0
        elif snr_db >= 12.0:
            snr_score = 70.0 + 30.0 * (snr_db - 12.0) / 8.0
        elif snr_db >= 6.0:
            snr_score = 40.0 + 30.0 * (snr_db - 6.0) / 6.0
        else:
            snr_score = 10.0 + 30.0 * max(0.0, snr_db) / 6.0

        weighted_total = (
            duration_score * 0.20
            + rms_score * 0.10
            + text_score * 0.15
            + clipping_score * 0.15
            + peak_score * 0.05
            + active_score * 0.15
            + boundary_score * 0.10
            + snr_score * 0.10
        )
        total = int(round(np.clip(weighted_total, 0.0, 100.0)))
        eligible = not hard_reasons
        if not eligible:
            total = min(total, 49)
            label = "不合格"
        elif total >= 90:
            label = "最优"
        elif total >= 75:
            label = "良好"
        elif total >= 60:
            label = "可用"
        else:
            label = "较差"

        return {
            "score": total,
            "label": label,
            "eligible": eligible,
            "reasons": reasons,
            "details": {
                "duration": round(float(duration), 6),
                "reported_duration": round(float(reported_duration or 0.0), 6),
                "rms": round(float(rms), 8),
                "peak": round(float(peak), 8),
                "clipping_ratio": round(float(clipping_ratio), 8),
                "speech_or_active_ratio": round(float(active_ratio), 6),
                "active_threshold": round(float(active_threshold), 8),
                "boundary_start_rms": round(float(boundary_start_rms), 8),
                "boundary_end_rms": round(float(boundary_end_rms), 8),
                "boundary_energy_ratio": round(float(boundary_energy_ratio), 6),
                "noise_rms": round(float(noise_rms), 8),
                "signal_rms": round(float(signal_rms), 8),
                "snr_db": round(float(snr_db), 3),
                "text_length": text_length,
                "text_required": require_text,
                "asr_confidence": (
                    round(asr_confidence, 4)
                    if asr_confidence is not None
                    else None
                ),
                "duration_score": int(round(duration_score)),
                "rms_score": int(round(rms_score)),
                "text_score": int(round(text_score)),
                "clipping_score": int(round(clipping_score)),
                "peak_score": int(round(peak_score)),
                "active_score": int(round(active_score)),
                "boundary_score": int(round(boundary_score)),
                "snr_score": int(round(snr_score)),
            },
        }


def get_audio_preprocessor() -> AudioPreprocessor:
    """获取 AudioPreprocessor 单例"""
    if not hasattr(get_audio_preprocessor, "_instance"):
        get_audio_preprocessor._instance = AudioPreprocessor()
    return get_audio_preprocessor._instance
