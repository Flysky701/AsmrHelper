"""
音色克隆音频预处理器 (Report #18 + 修正)

功能：
1. 音频规格转换 (16kHz / 16-bit PCM / Mono) - 满足 Qwen3-TTS 克隆要求
2. 双模式支持:
   - 匹配模式: 字幕语言 == 音频语言，使用字幕切割 + 字幕文本作为 ref_text
   - ASR模式: 字幕语言 != 音频语言 OR 无字幕，使用 ASR 识别日语文本 + ASR 时间轴切割
3. 智能片段选择 (3-30s 范围，优先 5-10s)
4. 音频拼接 (交叉淡入淡出避免 pop/click)

关键原则：
- ref_text 必须是音频内容的真实转录，绝不能预设！
- 如果没有匹配的字幕，必须用 ASR 生成日语文本

依赖:
- ffmpeg: 音频规格转换
- Faster-Whisper: ASR 识别
- 已有基础设施: cut_audio_by_subtitle, detect_subtitle_language
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, List, Tuple

import numpy as np
import soundfile as sf

from src.utils import get_ffmpeg, get_audio_info, cut_audio_by_subtitle, ensure_dir


# ===== 常量定义 =====

# Qwen3-TTS 克隆音频规格要求
CLONE_SAMPLE_RATE = 16000  # Hz
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

# 交叉淡入淡出时长
CROSSFADE_DURATION = 0.01  # 10ms

# 安全区（切割前后保留）
SAFE_MARGIN = 0.05  # 50ms


@dataclass
class CloneAudioResult:
    """
    克隆音频准备结果

    Attributes:
        ref_audio_path: 最终的参考音频路径 (16kHz/Mono/16-bit WAV)
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
        2. 转换为 16kHz / 16-bit / Mono（满足 Qwen3-TTS 要求）
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
        self._report(progress_callback, "转换音频规格 (16kHz/Mono/16-bit)...", 15)

        converted_path = self._convert_to_clone_spec(
            str(audio_path),
            str(self.output_dir / f"{audio_path.stem}_16k.wav")
        )

        # 获取转换后的音频信息
        converted_info = get_audio_info(converted_path)

        # 检查是否需要转换
        needs_conversion = (
            original_info['sample_rate'] != CLONE_SAMPLE_RATE or
            original_info['channels'] != CLONE_CHANNELS
        )
        if needs_conversion:
            self._report(progress_callback,
                f"已转换: {converted_info['sample_rate']}Hz, "
                f"{converted_info['channels']}ch", 20)
        else:
            self._report(progress_callback,
                f"音频已是目标规格", 20)

        # ===== Step 3: 确定处理模式 =====
        subtitle_entries = []
        mode = "asr"  # 默认 ASR 模式
        asr_segments = None  # ASR 结果

        # 加载字幕（如果有）
        subtitle_lang = None
        if subtitle_path and Path(subtitle_path).exists():
            self._report(progress_callback, f"加载字幕: {Path(subtitle_path).name}", 22)

            from src.core.translate import load_subtitle_with_timestamps, detect_subtitle_language
            subtitle_entries = load_subtitle_with_timestamps(subtitle_path)

            if subtitle_entries:
                # 检测字幕语言
                texts = [e.get("text", "") for e in subtitle_entries]
                subtitle_lang = detect_subtitle_language(texts)

                # 判断模式 - 标准化语言代码
                lang_map = {"j": "ja", "z": "zh", "e": "en"}
                first_char = audio_language.lower()[0] if audio_language else ""
                audio_lang_normalized = lang_map.get(first_char, audio_language.lower())

                if subtitle_lang == audio_lang_normalized:
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
                subtitle_entries = [
                    {"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")}
                    for s in asr_segments
                ]
                mode = "asr"
            else:
                self._report(progress_callback, "执行 ASR 识别（获取日语文本和时间轴）...", 30)

                try:
                    asr_segments = self._run_asr(
                        converted_path,
                        language="ja",  # 强制识别日语（用于日语音色克隆）
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
                    raise RuntimeError(f"无法获取音频文本内容: {asr_err}")

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
            warnings.append(f"总时长 ({final_info['duration']:.1f}s) 超过最大值 ({CLONE_TOTAL_MAX}s)，已截断")

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
            audio_path: 音频路径（16kHz/Mono）
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
            from src.core.asr import ASRRecognizer

            # 创建 ASR 识别器（使用配置中的模型）
            asr = ASRRecognizer(model_size=model_size, language=language)

            # ASR 识别
            segments = asr.recognize(
                audio_path=audio_path,
                progress_callback=lambda cur, dur, cnt: self._report(
                    progress_callback,
                    f"ASR: {cur:.1f}s / {dur:.1f}s",
                    32 + int((cur / dur * 100) * 0.08) if dur > 0 else 32
                ),
                show_progress=False,
            )

            # 卸载模型释放内存
            asr.unload()

            if not segments:
                raise ValueError("ASR 识别结果为空")

            # 转换为标准格式
            result = []
            for seg in segments:
                result.append({
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "text": seg.get("text", "").strip(),
                })

            return result

        except ImportError:
            raise RuntimeError("ASR 模块不可用，请确保 Faster-Whisper 已安装")
        except Exception as e:
            raise RuntimeError(f"ASR 识别失败: {e}")

    def _convert_to_clone_spec(self, audio_path: str, output_path: str) -> str:
        """
        转换音频为 Qwen3-TTS 克隆规格:
        - 采样率: 16000 Hz
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
            "-ar", str(CLONE_SAMPLE_RATE),  # 16kHz
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

        # 获取音频实际时长，防止末尾截断
        audio_info = get_audio_info(audio_path)
        audio_duration = audio_info["duration"]
        total = len(entries)

        # 准备切割参数（添加安全区，首尾特殊处理）
        cut_entries = []
        for i, entry in enumerate(entries):
            # 首个片段：不减安全区，避免丢失开头内容
            if i == 0:
                start = entry["start"]
            else:
                start = max(0, entry["start"] - SAFE_MARGIN)

            # 末尾片段：使用实际音频长度，防止提前截断
            if i == total - 1:
                end = max(entry["end"], audio_duration)
            else:
                end = entry["end"] + SAFE_MARGIN

            cut_entries.append({
                "start": start,
                "end": end,
                "text": entry.get("text", ""),
            })

        # 使用已有的 cut_audio_by_subtitle 函数
        segments = cut_audio_by_subtitle(
            audio_path,
            cut_entries,
            str(self.output_dir / "segments"),
            prefix="seg",
        )

        # 合并 segments 和原始文本
        for i, seg in enumerate(segments):
            if i < len(entries):
                seg["text"] = entries[i].get("text", "")

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
        short_segments = []  # 收集过短的片段用于合并

        for seg in segments:
            duration = seg.get("duration", 0)
            path = seg.get("path", "")

            # 时长检查
            if duration < CLONE_MIN_DURATION:
                short_segments.append(seg)
                continue
            if duration > CLONE_MAX_DURATION:
                # 超过30秒的截取中间部分
                seg = self._trim_segment(seg)
                duration = seg.get("duration", 0)
                if duration < CLONE_MIN_DURATION:
                    short_segments.append(seg)
                    continue

            # RMS 检查（语音质量）
            if path:
                try:
                    data, sr = sf.read(path)
                    if len(data.shape) > 1:
                        data = data[:, 0]  # 取单声道
                    rms = float(np.sqrt(np.mean(data ** 2)))
                    seg["rms"] = rms

                    if rms < RMS_THRESHOLD:
                        short_segments.append(seg)
                        continue
                except Exception:
                    short_segments.append(seg)
                    continue
            else:
                seg["rms"] = 0.0

            valid.append(seg)

        # 如果有合规片段但数量不足，尝试合并短片段
        if short_segments and len(valid) < 3:
            self._report(progress_callback,
                f"发现 {len(short_segments)} 个短片段，尝试合并... (目标: 3-30s)", 68)
            merged = self._merge_short_segments(short_segments + valid)
            if merged:
                valid.extend(merged)
                # 去重
                seen = set()
                unique_valid = []
                for seg in valid:
                    seg_id = seg.get("path", "")
                    if seg_id not in seen:
                        seen.add(seg_id)
                        unique_valid.append(seg)
                valid = unique_valid

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
        if not segments:
            return None

        # 合并路径
        merged_path = self.output_dir / "segments" / f"merged_{segments[0].get('index', 0)}.wav"

        # 计算新的时间范围
        start = segments[0].get("start", 0)
        end = segments[-1].get("end", 0)

        # 跳过时长不满足要求的
        duration = end - start
        if duration < CLONE_MIN_DURATION or duration > CLONE_MAX_DURATION:
            return None

        # 读取并合并音频
        try:
            all_data = []
            sample_rate = None
            merged_texts = []
            for seg in segments:
                path = seg.get("path", "")
                if path and Path(path).exists():
                    data, sr = sf.read(path)
                    if sample_rate is None:
                        sample_rate = sr
                    all_data.append(data)
                # 收集文本
                text = seg.get("text", "")
                if text:
                    merged_texts.append(text)

            if not all_data:
                return None

            # 拼接（带交叉淡入淡出）
            if len(all_data) == 1:
                merged_data = all_data[0]
            else:
                merged_data = all_data[0]
                for i in range(1, len(all_data)):
                    crossfade_samples = int(CROSSFADE_DURATION * sample_rate)
                    fade_out = merged_data[-crossfade_samples:] if len(merged_data) >= crossfade_samples else merged_data
                    fade_in = all_data[i][:crossfade_samples] if len(all_data[i]) >= crossfade_samples else all_data[i]
                    if len(fade_out) == len(fade_in):
                        fade_out_weight = np.linspace(1.0, 0.0, len(fade_out))
                        fade_in_weight = np.linspace(0.0, 1.0, len(fade_in))
                        crossfade = fade_out * fade_out_weight + fade_in * fade_in_weight
                        merged_data = np.concatenate([merged_data[:-crossfade_samples], crossfade, all_data[i][crossfade_samples:]])
                    else:
                        merged_data = np.concatenate([merged_data, all_data[i]])
            ensure_dir(str(merged_path.parent))
            sf.write(str(merged_path), merged_data, sample_rate, subtype="FLOAT")

            # 计算 RMS
            if len(merged_data.shape) > 1:
                merged_data = merged_data[:, 0]
            rms = float(np.sqrt(np.mean(merged_data ** 2)))

            # 基于实际音频数据计算时长
            actual_duration = len(merged_data) / sample_rate

            return {
                "path": str(merged_path),
                "start": start,
                "end": end,
                "text": " ".join(merged_texts),  # 合并文本
                "duration": actual_duration,
                "rms": rms,
            }
        except Exception:
            return None

    def _trim_segment(self, segment: dict) -> dict:
        """
        截取片段中间部分（处理超过30秒的长片段）

        Args:
            segment: 片段信息

        Returns:
            dict: 截取后的片段信息
        """
        duration = segment.get("duration", 0)
        if duration <= CLONE_MAX_DURATION:
            return segment

        # 截取中间 25 秒
        trim_start = (duration - 25.0) / 2.0
        trim_end = trim_start + 25.0

        # 读取并截取
        path = segment["path"]
        data, sr = sf.read(path)
        if len(data.shape) > 1:
            data = data[:, 0]

        start_sample = int(trim_start * sr)
        end_sample = int(trim_end * sr)
        trimmed_data = data[start_sample:end_sample]

        # 保存
        trimmed_path = str(Path(path).with_suffix(".trimmed.wav"))
        sf.write(trimmed_path, trimmed_data, sr, subtype="FLOAT")

        return {
            **segment,
            "path": trimmed_path,
            "start": segment["start"] + trim_start,
            "end": segment["start"] + trim_end,
            "duration": 25.0,
        }

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

        # 按优先级分类
        optimal = []  # 5-10s（最优单段范围）
        acceptable = []  # 3-5s（次优单段范围）
        long_segments = []  # >10s

        for seg in segments:
            duration = seg.get("duration", 0)
            if CLONE_OPTIMAL_MIN <= duration <= CLONE_OPTIMAL_MAX:
                optimal.append(seg)
            elif CLONE_MIN_DURATION <= duration < CLONE_OPTIMAL_MIN:
                acceptable.append(seg)
            else:
                long_segments.append(seg)

        # ===== 策略1: 优先选择单个最佳片段 =====
        # 选择 RMS 最高的 5-10s 片段（音质最好）
        if optimal:
            best_seg = max(optimal, key=lambda x: x.get("rms", 0))
            return [best_seg]

        # 策略2: 选择 RMS 最高的 3-5s 片段
        if acceptable:
            best_seg = max(acceptable, key=lambda x: x.get("rms", 0))
            return [best_seg]

        # 策略3: 选择时长最接近 10s 的长片段（截断后使用）
        if long_segments:
            # 按接近 10s 的程度排序
            best_seg = min(long_segments, key=lambda x: abs(x.get("duration", 0) - CLONE_OPTIMAL_MAX))
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

        if len(segments) == 1:
            # 单片段直接复制
            import shutil
            shutil.copy(segments[0]["path"], str(output_path))
            return str(output_path)

        # 多片段拼接（带交叉淡入淡出）
        all_data = []
        sample_rate = None

        for i, seg in enumerate(segments):
            data, sr = sf.read(seg["path"])
            if len(data.shape) > 1:
                data = data[:, 0]

            if sample_rate is None:
                sample_rate = sr

            if i > 0 and len(all_data) > 0:
                # 添加交叉淡入淡出
                crossfade_samples = int(CROSSFADE_DURATION * sample_rate)
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
        sf.write(str(output_path), all_data, sample_rate, subtype="FLOAT")
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

    def get_audio_preview(
        self,
        audio_path: str,
        subtitle_path: str = None,
        audio_language: str = "ja",
    ) -> dict:
        """
        预检音频，返回预览信息（不实际处理）

        Args:
            audio_path: 音频路径
            subtitle_path: 字幕路径（可选）
            audio_language: 音频语言

        Returns:
            dict: 预览信息
        """
        info = get_audio_info(audio_path)

        preview = {
            "original_sample_rate": info["sample_rate"],
            "original_channels": info["channels"],
            "original_duration": info["duration"],
            "needs_conversion": (
                info["sample_rate"] != CLONE_SAMPLE_RATE or
                info["channels"] != CLONE_CHANNELS
            ),
            "target_sample_rate": CLONE_SAMPLE_RATE,
            "target_channels": CLONE_CHANNELS,
            "mode": "unknown",
            "subtitle_info": None,
            "segment_preview": None,
            "warnings": [],
        }

        # 检查字幕
        if subtitle_path and Path(subtitle_path).exists():
            try:
                from src.core.translate import (
                    load_subtitle_with_timestamps,
                    detect_subtitle_language,
                )

                entries = load_subtitle_with_timestamps(subtitle_path)
                texts = [e.get("text", "") for e in entries]
                sub_lang = detect_subtitle_language(texts)

                # 统计时长分布
                duration_ranges = {"<3s": 0, "3-5s": 0, "5-10s": 0, ">10s": 0}
                for entry in entries:
                    duration = entry["end"] - entry["start"]
                    if duration < 3:
                        duration_ranges["<3s"] += 1
                    elif duration < 5:
                        duration_ranges["3-5s"] += 1
                    elif duration < 10:
                        duration_ranges["5-10s"] += 1
                    else:
                        duration_ranges[">10s"] += 1

                audio_lang_norm = "ja" if audio_language.lower().startswith("j") else audio_language.lower()
                mode = "matched" if sub_lang == audio_lang_norm else "asr"

                preview["subtitle_info"] = {
                    "path": subtitle_path,
                    "entries": len(entries),
                    "language": sub_lang,
                    "mode": mode,
                    "duration_ranges": duration_ranges,
                }
                preview["mode"] = mode

                if mode == "asr":
                    preview["warnings"].append(
                        f"字幕语言({sub_lang})与音频语言({audio_lang_norm})不匹配，将使用 ASR"
                    )

            except Exception as e:
                preview["warnings"].append(f"字幕解析失败: {e}")

        else:
            preview["warnings"].append("未提供字幕文件，将使用 ASR")
            preview["mode"] = "asr"

        # 时长警告
        if info["duration"] < CLONE_TOTAL_MIN:
            preview["warnings"].append(
                f"音频时长({info['duration']:.1f}s)低于推荐值({CLONE_TOTAL_MIN}s)"
            )

        return preview


    # ===== 交互式预览模式方法 =====

    def analyze_segments(
        self,
        audio_path: str,
        subtitle_path: str = None,
        audio_language: str = "ja",
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """
        分析音频片段（不自动选择，用于 GUI 预览模式）

        与 prepare_clone_audio 的区别：
        - 不自动选择最佳片段
        - 返回所有有效片段及其质量评分
        - 用于 GUI 展示和用户手动选择

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
        self._report(progress_callback, "转换音频规格 (16kHz/Mono/16-bit)...", 15)
        converted_path = self._convert_to_clone_spec(
            str(audio_path),
            str(self.output_dir / f"{audio_path.stem}_16k.wav")
        )

        # Step 3: 确定模式
        subtitle_entries = []
        mode = "asr"
        if subtitle_path and Path(subtitle_path).exists():
            self._report(progress_callback, f"加载字幕: {Path(subtitle_path).name}", 20)
            from src.core.translate import load_subtitle_with_timestamps, detect_subtitle_language
            subtitle_entries = load_subtitle_with_timestamps(subtitle_path)
            if subtitle_entries:
                texts = [e.get("text", "") for e in subtitle_entries]
                subtitle_lang = detect_subtitle_language(texts)
                lang_map = {"j": "ja", "z": "zh", "e": "en"}
                first_char = audio_language.lower()[0] if audio_language else ""
                audio_lang_normalized = lang_map.get(first_char, audio_language.lower())
                if subtitle_lang == audio_lang_normalized:
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
        else:
            self._report(progress_callback, "无字幕文件，将使用 ASR 识别", 25)

        # Step 3.5: ASR
        if mode == "asr" or not subtitle_entries:
            self._report(progress_callback, "执行 ASR 识别...", 30)
            try:
                asr_segments = self._run_asr(converted_path, language="ja", progress_callback=progress_callback)
                if asr_segments:
                    mode = "asr"
                    subtitle_entries = asr_segments
                    self._report(progress_callback, f"ASR 识别完成: {len(asr_segments)} 条", 50)
                else:
                    raise ValueError("ASR 识别结果为空")
            except Exception as asr_err:
                self._report(progress_callback, f"ASR 识别失败: {asr_err}", 30)
                warnings.append(f"ASR 识别失败: {asr_err}")
                raise RuntimeError(f"无法获取音频文本内容: {asr_err}")

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
            quality = self.evaluate_segment_quality(seg)
            seg["quality_score"] = quality["score"]
            seg["quality_label"] = quality["label"]
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

    def evaluate_segment_quality(self, segment: dict) -> dict:
        """
        评估片段质量 (0-100)

        评分维度:
        - 时长 (40%): 5-10s 最优
        - 音量 (30%): RMS 0.03-0.30 最佳
        - 文本 (30%): 有文本且长度合适

        Returns:
            dict: {"score": int, "label": str, "details": dict}
        """
        duration = segment.get("duration", 0)
        rms = segment.get("rms", 0)
        text = segment.get("text", "").strip()

        # 时长得分 (40%)
        if CLONE_OPTIMAL_MIN <= duration <= CLONE_OPTIMAL_MAX:
            duration_score = 100.0
        elif CLONE_MIN_DURATION <= duration < CLONE_OPTIMAL_MIN:
            duration_score = 60.0 + 40.0 * (duration - CLONE_MIN_DURATION) / (CLONE_OPTIMAL_MIN - CLONE_MIN_DURATION)
        elif CLONE_OPTIMAL_MAX < duration <= CLONE_MAX_DURATION:
            duration_score = 60.0 + 40.0 * (CLONE_MAX_DURATION - duration) / (CLONE_MAX_DURATION - CLONE_OPTIMAL_MAX)
        else:
            duration_score = 0.0

        # 音量得分 (30%)
        if 0.03 <= rms <= 0.30:
            rms_score = 100.0
        elif 0.01 <= rms < 0.03:
            rms_score = 50.0 + 50.0 * (rms - 0.01) / 0.02
        elif 0.30 < rms <= 0.50:
            rms_score = 100.0 - 50.0 * (rms - 0.30) / 0.20
        else:
            rms_score = max(0.0, 30.0)

        # 文本得分 (30%)
        text_len = len(text)
        if text_len >= 10:
            text_score = 100.0
        elif text_len >= 5:
            text_score = 70.0 + 30.0 * (text_len - 5) / 5.0
        elif text_len >= 1:
            text_score = 40.0 + 30.0 * (text_len - 1) / 4.0
        else:
            text_score = 0.0

        total = int(duration_score * 0.4 + rms_score * 0.3 + text_score * 0.3)

        if total >= 90:
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
            "details": {
                "duration_score": int(duration_score),
                "rms_score": int(rms_score),
                "text_score": int(text_score),
            },
        }

    def build_from_segments(
        self,
        segments: List[dict],
        output_path: str = None,
    ) -> CloneAudioResult:
        """
        从用户选中的片段构建最终克隆音频

        Args:
            segments: 用户选中的片段列表 (必须有 path 和 text)
            output_path: 输出路径 (可选)

        Returns:
            CloneAudioResult
        """
        if not segments:
            raise ValueError("没有选中的片段")

        if output_path is None:
            output_path = str(self.output_dir / "ref_audio_manual.wav")

        # 拼接音频
        ref_audio_path = self._concatenate_audio_segments(segments, output_path)

        # 生成 ref_text
        ref_text = self._build_ref_text(segments)

        # 验证
        final_info = get_audio_info(ref_audio_path)
        warnings = []
        if final_info['duration'] < CLONE_TOTAL_MIN:
            warnings.append(f"总时长 ({final_info['duration']:.1f}s) 低于推荐值 ({CLONE_TOTAL_MIN}s)")
        if final_info['duration'] > CLONE_TOTAL_MAX:
            warnings.append(f"总时长 ({final_info['duration']:.1f}s) 超过最大值 ({CLONE_TOTAL_MAX}s)")

        return CloneAudioResult(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            mode="manual",
            segments_used=len(segments),
            total_duration=final_info['duration'],
            segments_info=segments,
            warnings=warnings,
        )


def get_audio_preprocessor() -> AudioPreprocessor:
    """获取 AudioPreprocessor 单例"""
    if not hasattr(get_audio_preprocessor, "_instance"):
        get_audio_preprocessor._instance = AudioPreprocessor()
    return get_audio_preprocessor._instance
