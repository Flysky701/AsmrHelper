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

        # ===== Step 1: 加载并转换音频 ======
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

                # 判断模式
                audio_lang_normalized = "ja" if audio_language.lower().startswith("j") else audio_language.lower()

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
        self._report(progress_callback, f"ASR 识别中 (语言: {language})...", 32)

        try:
            from src.core.asr import ASRRecognizer

            # 创建 ASR 识别器
            asr = ASRRecognizer(model_size="large-v3", language=language)

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

        # 准备切割参数（添加安全区）
        cut_entries = []
        for entry in entries:
            # 添加安全区，但不超过音频边界
            start = max(0, entry["start"] - SAFE_MARGIN)
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

            # 拼接
            merged_data = np.concatenate(all_data)
            ensure_dir(str(merged_path.parent))
            sf.write(str(merged_path), merged_data, sample_rate, subtype="FLOAT")

            # 计算 RMS
            if len(merged_data.shape) > 1:
                merged_data = merged_data[:, 0]
            rms = float(np.sqrt(np.mean(merged_data ** 2)))

            return {
                "path": str(merged_path),
                "start": start,
                "end": end,
                "text": " ".join(merged_texts),  # 合并文本
                "duration": duration,
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
        智能选择最佳片段用于克隆

        优先级:
        1. 时长 5-10s 的片段（效果最稳定）
        2. 时长 3-5s 的片段（勉强可用）
        3. 时长 10-30s 的片段（过长，已截断）

        总时长控制:
        - 最少: 5s
        - 推荐: 10-20s
        - 最多: 60s

        Args:
            segments: 有效片段列表

        Returns:
            List[dict]: 选中的片段列表
        """
        if not segments:
            return []

        # 按优先级分类
        optimal = []  # 5-10s
        acceptable = []  # 3-5s
        long = []  # >10s (已截断的)

        for seg in segments:
            duration = seg.get("duration", 0)
            if CLONE_OPTIMAL_MIN <= duration <= CLONE_OPTIMAL_MAX:
                optimal.append(seg)
            elif CLONE_MIN_DURATION <= duration < CLONE_OPTIMAL_MIN:
                acceptable.append(seg)
            else:
                long.append(seg)

        selected = []
        total_duration = 0.0

        # 优先选择 5-10s 的片段
        for seg in sorted(optimal, key=lambda x: -x["duration"]):
            if total_duration + seg["duration"] > CLONE_TOTAL_MAX:
                break
            selected.append(seg)
            total_duration += seg["duration"]

        # 补充 3-5s 的片段
        if total_duration < CLONE_TOTAL_MIN:
            for seg in sorted(acceptable, key=lambda x: -x["duration"]):
                if total_duration + seg["duration"] > CLONE_TOTAL_MAX:
                    break
                selected.append(seg)
                total_duration += seg["duration"]

        # 按时间顺序排序
        selected.sort(key=lambda x: x["start"])

        return selected

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

                # 淡出曲线
                fade_out_weight = np.linspace(1.0, 0.5, len(fade_out))
                fade_in_weight = np.linspace(0.5, 1.0, len(fade_in))

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


def get_audio_preprocessor() -> AudioPreprocessor:
    """获取 AudioPreprocessor 单例"""
    if not hasattr(get_audio_preprocessor, "_instance"):
        get_audio_preprocessor._instance = AudioPreprocessor()
    return get_audio_preprocessor._instance
