"""
ASMR Helper - ASMR 音频汉化工具核心模块

核心流程:
1. VocalSeparator - Demucs 人声分离
2. ASRRecognizer - Faster-Whisper 语音识别
3. Translator - DeepSeek/OpenAI 翻译
4. TTSEngine - Edge-TTS / Qwen3-TTS 合成
5. Mixer - 智能混音
"""

__version__ = "0.2.0"

from .core.vocal_separator import VocalSeparator
from .core.asr import ASRRecognizer
from .core.translate import Translator
from .core.tts import TTSEngine
from .mixer import Mixer
from .core.pipeline import Pipeline, PipelineConfig

__all__ = [
    "VocalSeparator",
    "ASRRecognizer",
    "Translator",
    "TTSEngine",
    "Mixer",
    "Pipeline",
    "PipelineConfig",
]
