"""
ASR 语音识别模块 - 使用 Faster-Whisper

功能：将语音转换为文字，支持日语等多种语言
"""

import time
from pathlib import Path
from typing import Optional, List, Literal

import numpy as np
from faster_whisper import WhisperModel


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
    ):
        """
        初始化 ASR 识别器

        Args:
            model_size: 模型大小 (tiny/base/small/medium/large-v3)
            device: 计算设备 (cuda/cpu/auto)
            language: 语言代码 (ja/zh/en/auto)
            compute_type: 计算精度
            disable_vad: 是否禁用 VAD（ASMR 需要保留轻声）
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

        # 加载模型，优先使用本地 models 目录
        t0 = time.time()
        # 查找本地缓存目录
        models_dir = Path(__file__).parent.parent.parent.parent / "models" / "whisper"
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
    ) -> List[dict]:
        """
        识别音频

        Args:
            audio_path: 音频文件路径
            output_path: 输出文本文件路径（可选）
            segment_threshold: 片段阈值
            min_segment_duration: 最小片段时长（秒）

        Returns:
            List[dict]: 识别结果 [{start, end, text}, ...]
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
            word_timestamps=False,
            beam_size=5,
            best_of=5,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # 多温度重试，提高轻声识别率
            condition_on_previous_text=True,   # 利用上下文
            initial_prompt="これはASMR音声です。ゆっくりとした静かな音声です。",  # 引导模型识别轻声
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.9,  # 高阈值保留 ASMR 轻声，让模型更难将轻声判断为无语音
        )

        # 收集结果
        results = []
        for seg in segments:
            if seg.end - seg.start < min_segment_duration:
                continue

            result = {
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            }
            results.append(result)

        # 保存结果
        if output_path:
            self._save_results(results, output_path)

        print(f"[ASRRecognizer] 识别完成，{len(results)} 段，耗时: {time.time()-t0:.1f}s")

        return results

    def _save_results(self, results: List[dict], output_path: str):
        """保存识别结果到文件"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for i, r in enumerate(results, 1):
                f.write(f"[{i}] {r['start']:.2f}s - {r['end']:.2f}s\n")
                f.write(f"{r['text']}\n")
                f.write("\n")

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
