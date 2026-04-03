"""
ASMR Helper 核心模块测试
"""

import pytest
from pathlib import Path


class TestVocalSeparator:
    """人声分离测试"""

    def test_initialization(self):
        """测试初始化"""
        from src.core import VocalSeparator

        sep = VocalSeparator(model_name="htdemucs")
        assert sep.model_name == "htdemucs"
        assert sep.device in ["cuda", "cpu"]


class TestASRRecognizer:
    """ASR 识别测试"""

    def test_initialization(self):
        """测试初始化"""
        from src.core import ASRRecognizer

        recognizer = ASRRecognizer(model_size="tiny", language="ja")
        assert recognizer.model_size == "tiny"
        assert recognizer.language == "ja"


class TestTranslator:
    """翻译测试"""

    def test_initialization(self):
        """测试初始化"""
        import os
        from src.core import Translator

        # 跳过如果没配置 API key
        if not os.environ.get("DEEPSEEK_API_KEY"):
            pytest.skip("需要配置 DEEPSEEK_API_KEY")

        translator = Translator(provider="deepseek")
        assert translator.provider == "deepseek"

    def test_translate(self):
        """测试翻译"""
        import os
        from src.core import Translator

        if not os.environ.get("DEEPSEEK_API_KEY"):
            pytest.skip("需要配置 DEEPSEEK_API_KEY")

        translator = Translator(provider="deepseek")
        result = translator.translate("こんにちは", source_lang="日文", target_lang="中文")
        assert len(result) > 0


class TestTTSEngine:
    """TTS 测试"""

    def test_edge_tts_initialization(self):
        """测试 Edge-TTS 初始化"""
        from src.core import TTSEngine

        tts = TTSEngine(engine="edge", voice="zh-CN-XiaoxiaoNeural")
        assert tts.engine_type == "edge"


class TestMixer:
    """混音测试"""

    def test_initialization(self):
        """测试初始化"""
        from src.core import Mixer

        mixer = Mixer(
            original_volume=0.85,
            tts_volume_ratio=0.5,
            tts_delay_ms=0,
        )
        assert mixer.original_volume == 0.85
        assert mixer.tts_volume_ratio == 0.5
        assert mixer.tts_delay_ms == 0

    def test_detect_volume(self, tmp_path):
        """测试音量检测"""
        import numpy as np
        import soundfile as sf
        from src.core import Mixer

        # 创建测试音频
        audio_path = tmp_path / "test.wav"
        data = np.random.randn(44100) * 0.5  # 0.5 峰值
        sf.write(str(audio_path), data, 44100)

        mixer = Mixer()
        volume = mixer.detect_volume(str(audio_path))
        assert 0.4 < volume < 0.6


class TestPipeline:
    """流水线测试"""

    def test_config_initialization(self):
        """测试配置初始化"""
        from src.core import PipelineConfig

        config = PipelineConfig(
            input_path="test.wav",
            output_dir="output",
            use_vocal_separator=True,
        )
        assert config.input_path == "test.wav"
        assert config.output_dir == "output"
        assert config.use_vocal_separator is True

    def test_presets(self):
        """测试预设"""
        from src.core import Pipeline

        assert "asmr_bilingual" in Pipeline.PRESETS
        assert "asr_only" in Pipeline.PRESETS
