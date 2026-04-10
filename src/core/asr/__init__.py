"""
ASR 语音识别模块 - 使用 Faster-Whisper

功能：将语音转换为文字，支持日语等多种语言

后处理（Report #14）：
- 文本规范化：去除重复标点、全角半角混用、空格、幻觉标记
- 片段合并：合并间隔<0.3s 且单段<1s 的极短片段
- 置信度过滤：利用 log_prob 过滤低质量片段

增强功能（Report #14 P2/P3）：
- word_timestamps：逐词时间戳用于 TTS 对齐优化
- 毫秒级时间精度：3位小数（毫秒）
- 流式进度显示：实时显示识别进度
- SRT/LRC 输出格式支持
"""

import math
import time
import sys
from pathlib import Path
from typing import Optional, List, Literal, Callable

import numpy as np
from faster_whisper import WhisperModel

from .postprocess import ASRPostProcessor, PostProcessConfig
from src.config import PROJECT_ROOT  # 统一使用项目根目录
from src.utils import format_timestamp


class ASRRecognizer:
    """语音识别器（基于 Faster-Whisper）"""

    # 支持的模型大小
    MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3"]

    # 语言代码映射
    LANG_CODES = {
        "ja": "ja",  # 日语
        "zh": "zh",  # 中文
        "en": "en",  # 英语
        "ko": "ko",  # 韩语
        "auto": None,  # 自动检测
    }

    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "auto",
        language: Optional[str] = None,
        compute_type: str = "float16",
        disable_vad: bool = True,
        postprocess_config: Optional[PostProcessConfig] = None,
    ):
        """
        初始化 ASR 识别器

        Args:
            model_size: 模型大小 (tiny/base/small/medium/large-v3)
            device: 计算设备 (cuda/cpu/auto)
            language: 语言代码 (ja/zh/en/auto)
            compute_type: 计算精度
            disable_vad: 是否禁用 VAD（ASMR 需要保留轻声）
            postprocess_config: 后处理配置，为 None 时使用默认配置
        """
        self.model_size = model_size
        # 自动检测 CUDA 支持
        if device == "auto":
            try:
                import onnxruntime as ort
                if "CUDAExecutionProvider" in ort.get_available_providers():
                    self.device = "cuda"
                else:
                    self.device = "cpu"
            except ImportError:
                self.device = "cpu"
        else:
            self.device = device if device == "cuda" else "cpu"

        self.language = self.LANG_CODES.get(language, language)
        self.disable_vad = disable_vad
        # CPU 使用 int8 加速
        self.compute_type = compute_type if self.device == "cuda" else "int8"

        # 后处理器
        self.postprocessor = ASRPostProcessor(postprocess_config or PostProcessConfig())

        # 加载模型，优先使用本地 models 目录
        t0 = time.time()
        # 统一使用 PROJECT_ROOT
        models_dir = PROJECT_ROOT / "models" / "whisper"
        download_root = str(models_dir) if models_dir.exists() else None
        self.model = WhisperModel(
            model_size,
            device=self.device,
            compute_type=self.compute_type,
            download_root=download_root,
        )
        print(f"[ASRRecognizer] 模型加载完成: {model_size}, 耗时: {time.time()-t0:.1f}s")

    def recognize(
        self,
        audio_path: str,
        output_path: Optional[str] = None,
        segment_threshold: float = 0.5,
        min_segment_duration: float = 0.5,
        progress_callback: Optional[Callable[[float, float, int], None]] = None,
        show_progress: bool = True,
    ) -> List[dict]:
        """
        识别音频

        Args:
            audio_path: 音频文件路径
            output_path: 输出文本文件路径（可选）
            segment_threshold: 片段阈值
            min_segment_duration: 最小片段时长（秒）
            progress_callback: 进度回调函数 callback(current_time, duration, segments_count)
            show_progress: 是否显示进度条

        Returns:
            List[dict]: 识别结果 [{start, end, text, words?, log_prob?}, ...]
        """
        audio_path = Path(audio_path)

        print(f"[ASRRecognizer] 识别音频: {audio_path.name}")
        t0 = time.time()

        # 运行识别
        segments, info = self.model.transcribe(
            str(audio_path),
            language=self.language,
            vad_filter=not self.disable_vad,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ) if not self.disable_vad else None,
            word_timestamps=True,  # 开启逐词时间戳（用于 TTS 对齐优化）
            beam_size=5,
            best_of=5,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # 多温度重试，提高轻声识别率
            condition_on_previous_text=True,   # 利用上下文
            initial_prompt="これはASMR音声です。ゆっくりとした静かな音声です。",  # 引导模型识别轻声
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.9,  # 高阈值保留 ASMR 轻声，让模型更难将轻声判断为无语音
        )

        # 获取音频时长
        duration = info.duration or 0.0
        last_progress_update = 0.0  # 上次更新进度的时间

        # 收集结果（保留 log_prob 用于置信度过滤）
        results = []
        word_count = 0
        for seg in segments:
            if seg.end - seg.start < min_segment_duration:
                continue

            # 收集单词时间戳
            words = []
            if seg.words:
                for w in seg.words:
                    words.append({
                        "word": w.word.strip(),
                        "start": round(w.start, 3),  # 毫秒级精度
                        "end": round(w.end, 3),
                        "probability": w.probability,
                    })
                    word_count += 1

            # 计算置信度：基于 words 的平均概率
            if words:
                avg_prob = sum(w["probability"] for w in words) / len(words)
                # 转换为 log_prob 格式（兼容后处理），取自然对数
                log_prob = -math.log(1.0 / (avg_prob + 1e-10) - 1.0 + 1e-10)
            else:
                # 如果没有 words，使用 no_speech_prob 的补数
                # no_speech_prob 越高越可能是静音，取补数作为语音置信度
                log_prob = -math.log(1.0 / (seg.no_speech_prob + 1e-10) - 1.0 + 1e-10) if seg.no_speech_prob < 0.99 else -1.0

            result = {
                "start": round(seg.start, 3),  # 毫秒级精度 (3位小数)
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "log_prob": log_prob,  # 保留置信度（用于后处理过滤）
                "words": words,
            }
            results.append(result)

            # 流式进度显示（每5%更新一次）
            current_time = seg.end
            if show_progress and duration > 0:
                progress = current_time / duration
                if progress - last_progress_update >= 0.05:  # 每5%更新
                    self._print_progress(current_time, duration, len(results))
                    last_progress_update = progress

            # 调用进度回调
            if progress_callback:
                progress_callback(current_time, duration, len(results))

        total_words = sum(len(r.get("words", [])) for r in results)

        # 后处理：文本规范化 + 片段合并 + 置信度过滤
        results = self.postprocessor.process(results)

        # 保存结果
        if output_path:
            self._save_results(results, output_path)

        print(f"[ASRRecognizer] 识别完成，{len(results)} 段 / {total_words} 词，耗时: {time.time()-t0:.1f}s")

        return results

    def _print_progress(self, current: float, total: float, segments: int):
        """打印进度条"""
        pct = min(100.0, current / total * 100) if total > 0 else 0
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "=" * filled + "-" * (bar_len - filled)
        mins, secs = divmod(int(current), 60)
        mins_t, secs_t = divmod(int(total), 60)
        sys.stdout.write(f"\r[ASR] [{bar}] {pct:5.1f}% ({mins}:{secs:02d}/{mins_t}:{secs_t:02d}) {segments}段")
        sys.stdout.flush()

    def _save_results(self, results: List[dict], output_path: str):
        """保存识别结果到文件（默认格式）"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for i, r in enumerate(results, 1):
                f.write(f"[{i}] {r['start']:.3f}s - {r['end']:.3f}s\n")
                f.write(f"{r['text']}\n")
                f.write("\n")

    def save_as_srt(self, results: List[dict], output_path: str):
        """
        保存为 SRT 格式（SubRip 字幕）

        Args:
            results: 识别结果
            output_path: 输出文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for i, r in enumerate(results, 1):
                # SRT 时间格式: HH:MM:SS,mmm
                start = self._format_srt_time(r["start"])
                end = self._format_srt_time(r["end"])

                f.write(f"{i}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{r['text']}\n")
                f.write("\n")

        print(f"[ASRRecognizer] 已保存 SRT: {output_path}")

    def save_as_lrc(
        self,
        results: List[dict],
        output_path: str,
        offset_ms: int = 0,
        include_metadata: bool = True,
    ):
        """
        保存为 LRC 格式（歌词时间戳）

        Args:
            results: 识别结果
            output_path: 输出文件路径
            offset_ms: 整体时间偏移（毫秒）
            include_metadata: 是否包含元数据行
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            # 元数据
            if include_metadata:
                f.write("[ti:ASMR Transcription]\n")
                f.write("[by:AsmrHelper]\n")
                f.write(f"[offset:{offset_ms}]\n")

            # 歌词行
            for r in results:
                # LRC 时间格式: [MM:SS.xx]
                start = self._format_lrc_time(r["start"] + offset_ms / 1000.0)
                f.write(f"{start}{r['text']}\n")

        print(f"[ASRRecognizer] 已保存 LRC: {output_path}")

    def _format_srt_time(self, seconds: float) -> str:
        """将秒数格式化为 SRT 时间 (HH:MM:SS,mmm)"""
        return format_timestamp(seconds, fmt="srt")

    def _format_lrc_time(self, seconds: float) -> str:
        """将秒数格式化为 LRC 时间 [MM:SS.xx]"""
        return format_timestamp(seconds, fmt="lrc")

    def recognize_to_text(self, audio_path: str, output_path: str) -> str:
        """
        识别音频并保存为纯文本

        Args:
            audio_path: 音频文件路径
            output_path: 输出文本文件路径

        Returns:
            str: 识别的文本
        """
        results = self.recognize(audio_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        text = "\n".join(r["text"] for r in results)
        output_path.write_text(text, encoding="utf-8")

        return text

    def unload(self):
        """
        释放模型占用的内存（Phase 3）

        在批量处理完成后调用以释放显存/CPU内存。
        """
        if hasattr(self, "model") and self.model is not None:
            del self.model
            self.model = None
            if self.device == "cuda":
                import torch
                torch.cuda.empty_cache()
            print(f"[ASRRecognizer] 模型已卸载，设备: {self.device}")


# 便捷函数
def recognize_speech(
    audio_path: str,
    output_path: Optional[str] = None,
    language: str = "ja",
    model_size: str = "base",
) -> List[dict]:
    """快速识别语音"""
    recognizer = ASRRecognizer(model_size=model_size, language=language)
    return recognizer.recognize(audio_path, output_path)
