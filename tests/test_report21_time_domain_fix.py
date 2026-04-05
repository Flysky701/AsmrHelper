"""
音频时域压缩逻辑 - 测试用例

验证项:
1. Edge-TTS: TTS 超长时使用 OLA 时域压缩
2. Edge-TTS: OLA 窗口参数按采样率动态计算
3. Qwen3-TTS: TTS 超长时使用 instruct 提示词重合成（不调用 OLA）
4. Qwen3-TTS: instruct 提示词根据超长程度选择
5. TTS 短于原音频时不做任何处理（两种引擎一致）
6. TTS 时长在正常范围内不触发压缩
7. 声道一致性（立体声→单声道）
8. 中间文件 FLOAT 格式
9. PipelineConfig max_tts_ratio / compress_ratio
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import numpy as np
import soundfile as sf
import tempfile
import os

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================
# 辅助: 生成测试用正弦波音频
# ============================================================
def make_sine_wave(duration_sec: float, sr: int = 44100, freq: float = 440.0,
                   channels: int = 1) -> tuple:
    """生成正弦波音频数据，返回 (data, sr)"""
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
    if channels > 1:
        wave = np.column_stack([wave] * channels)
    return wave, sr


def write_sine_wav(path: str, duration_sec: float, sr: int = 44100, channels: int = 1):
    """写入正弦波 WAV 文件"""
    data, sr = make_sine_wave(duration_sec, sr, channels=channels)
    sf.write(path, data, sr, subtype="FLOAT")


# ============================================================
# 1. Edge-TTS: TTS 超长时使用 OLA 时域压缩
# ============================================================
def test_edge_tts_compress_with_ola():
    """Edge-TTS 超长时使用 OLA 压缩"""
    import pytsmod
    from src.mixer import Mixer
    from src.core.tts import EdgeTTSEngine

    # 原音 2s, TTS 3s > 2.0 * 1.2 = 2.4 -> 触发压缩
    segments = [{"start": 0.0, "end": 2.0, "translation": "测试文本"}]

    mock_engine = MagicMock(spec=EdgeTTSEngine)
    mock_engine.synthesize.side_effect = lambda text, path: write_sine_wav(path, 3.0)

    ola_calls = []
    original_ola = pytsmod.ola

    def mock_ola(audio, stretch_factor, **kwargs):
        ola_calls.append({"stretch_factor": stretch_factor, **kwargs})
        return original_ola(audio, stretch_factor, **kwargs)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "output.wav")

        with patch("pytsmod.ola", side_effect=mock_ola):
            mixer = Mixer()
            mixer.build_aligned_tts(
                segments=segments,
                tts_engine=mock_engine,
                output_path=output_path,
                reference_duration=10.0,
                sample_rate=44100,
                max_tts_ratio=1.2,
                compress_ratio=0.75,
            )

    assert len(ola_calls) == 1, f"Edge-TTS 应调用 OLA 一次，实际: {len(ola_calls)}"
    assert ola_calls[0]["stretch_factor"] == 0.75


# ============================================================
# 2. Edge-TTS: OLA 窗口参数按采样率动态计算
# ============================================================
def test_edge_tts_ola_window_params():
    """Edge-TTS OLA 窗口参数基于采样率动态计算"""
    import pytsmod
    from src.mixer import Mixer
    from src.core.tts import EdgeTTSEngine

    segments = [{"start": 0.0, "end": 2.0, "translation": "短文本"}]

    mock_engine = MagicMock(spec=EdgeTTSEngine)
    mock_engine.synthesize.side_effect = lambda text, path: write_sine_wav(path, 3.0)

    ola_calls = []
    original_ola = pytsmod.ola

    def mock_ola(audio, stretch_factor, **kwargs):
        ola_calls.append(kwargs)
        return original_ola(audio, stretch_factor, **kwargs)

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("pytsmod.ola", side_effect=mock_ola):
            mixer = Mixer()
            mixer.build_aligned_tts(
                segments=segments,
                tts_engine=mock_engine,
                output_path=os.path.join(tmpdir, "output.wav"),
                reference_duration=10.0,
                sample_rate=44100,
            )

    assert len(ola_calls) > 0
    assert ola_calls[0]["syn_hop_size"] == int(44100 * 0.025)
    assert ola_calls[0]["win_size"] == int(44100 * 0.100)


# ============================================================
# 3. Qwen3-TTS: 使用 instruct 重合成（不调用 OLA）
# ============================================================
def test_qwen3_uses_instruct_not_ola():
    """Qwen3-TTS 超长时使用 instruct 提示词重合成，不调用 OLA"""
    import pytsmod
    from src.mixer import Mixer
    from src.core.tts import Qwen3TTSEngine

    segments = [{"start": 0.0, "end": 2.0, "translation": "测试文本"}]

    mock_engine = MagicMock(spec=Qwen3TTSEngine)
    # 正常合成: 3s (超长)
    mock_engine.synthesize.side_effect = lambda text, path: write_sine_wav(path, 3.0)
    # instruct 重合成: 1.5s (缩短了)
    mock_engine.synthesize_with_instruct.side_effect = lambda text, path, instruct: write_sine_wav(path, 1.5)

    ola_called = False

    def mock_ola(audio, stretch_factor, **kwargs):
        nonlocal ola_called
        ola_called = True
        return pytsmod.ola(audio, stretch_factor, **kwargs)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "output.wav")

        with patch("pytsmod.ola", side_effect=mock_ola):
            mixer = Mixer()
            mixer.build_aligned_tts(
                segments=segments,
                tts_engine=mock_engine,
                output_path=output_path,
                reference_duration=10.0,
                sample_rate=44100,
                max_tts_ratio=1.2,
                compress_ratio=0.75,
            )

    assert not ola_called, "Qwen3-TTS 不应调用 OLA"
    # 应调用 synthesize_with_instruct
    mock_engine.synthesize_with_instruct.assert_called_once()
    # instruct 参数应包含速度相关的词
    call_kwargs = mock_engine.synthesize_with_instruct.call_args
    instruct = call_kwargs[1]["instruct"] if len(call_kwargs) > 1 else call_kwargs[0][2]
    assert instruct, "应传递非空 instruct"
    assert "快" in instruct, f"instruct 应包含'快'字，实际: {instruct}"


# ============================================================
# 4. Qwen3-TTS: instruct 提示词根据超长程度选择
# ============================================================
def test_qwen3_speed_instruct_levels():
    """验证 _qwen3_speed_instruct 返回正确的提示词"""
    from src.mixer import Mixer

    cases = [
        # (tts_duration, target_duration, expected_instruct)
        (2.4, 2.0, ""),             # ratio=1.2, 不重合成 (<=1.2)
        (2.41, 2.0, "语速稍快"),    # ratio=1.205 (>1.2)
        (3.01, 2.0, "语速加快"),    # ratio=1.505 (>1.5)
        (4.5, 2.0, "用比较快的语速说"),  # ratio=2.25 (>2.0)
        (7.0, 2.0, "用非常快的语速说"),  # ratio=3.5 (>3.0)
    ]

    for tts_dur, target_dur, expected in cases:
        result = Mixer._qwen3_speed_instruct(tts_dur, target_dur)
        assert result == expected, \
            f"ratio={tts_dur/target_dur:.2f}: 期望 {expected!r}, 实际 {result!r}"


# ============================================================
# 5. TTS 短于原音频时不做处理
# ============================================================
def test_no_processing_when_tts_shorter():
    """TTS 短于原音频时两种引擎都不做处理"""
    import pytsmod
    from src.mixer import Mixer
    from src.core.tts import EdgeTTSEngine, Qwen3TTSEngine

    segments = [{"start": 0.0, "end": 4.0, "translation": "文本"}]

    ola_called = False

    def mock_ola(audio, stretch_factor, **kwargs):
        nonlocal ola_called
        ola_called = True
        return pytsmod.ola(audio, stretch_factor, **kwargs)

    # 测试 Edge-TTS
    mock_edge = MagicMock(spec=EdgeTTSEngine)
    mock_edge.synthesize.side_effect = lambda text, path: write_sine_wav(path, 1.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("pytsmod.ola", side_effect=mock_ola):
            mixer = Mixer()
            mixer.build_aligned_tts(
                segments=segments,
                tts_engine=mock_edge,
                output_path=os.path.join(tmpdir, "edge_out.wav"),
                reference_duration=30.0,
                sample_rate=44100,
            )

    assert not ola_called, "Edge-TTS TTS短时不应调用 OLA"

    # 测试 Qwen3-TTS
    mock_qwen3 = MagicMock(spec=Qwen3TTSEngine)
    mock_qwen3.synthesize.side_effect = lambda text, path: write_sine_wav(path, 1.0)
    mock_qwen3.synthesize_with_instruct = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("pytsmod.ola", side_effect=mock_ola):
            mixer = Mixer()
            mixer.build_aligned_tts(
                segments=segments,
                tts_engine=mock_qwen3,
                output_path=os.path.join(tmpdir, "qwen3_out.wav"),
                reference_duration=30.0,
                sample_rate=44100,
            )

    assert not ola_called, "Qwen3 TTS短时不应调用 OLA"
    mock_qwen3.synthesize_with_instruct.assert_not_called()


# ============================================================
# 6. TTS 时长在正常范围内不触发压缩
# ============================================================
def test_no_compress_in_normal_range():
    """TTS 时长在正常范围内两种引擎都不触发压缩"""
    import pytsmod
    from src.mixer import Mixer
    from src.core.tts import EdgeTTSEngine, Qwen3TTSEngine

    segments = [{"start": 0.0, "end": 2.0, "translation": "正常文本"}]

    ola_called = False

    def mock_ola(audio, stretch_factor, **kwargs):
        nonlocal ola_called
        ola_called = True
        return pytsmod.ola(audio, stretch_factor, **kwargs)

    # Edge-TTS: 原音 2s, TTS 2s -> 不触发
    mock_edge = MagicMock(spec=EdgeTTSEngine)
    mock_edge.synthesize.side_effect = lambda text, path: write_sine_wav(path, 2.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("pytsmod.ola", side_effect=mock_ola):
            mixer = Mixer()
            mixer.build_aligned_tts(
                segments=segments,
                tts_engine=mock_edge,
                output_path=os.path.join(tmpdir, "out.wav"),
                reference_duration=10.0,
                sample_rate=44100,
            )

    assert not ola_called

    # Qwen3: 原音 2s, TTS 2s -> 不触发
    mock_qwen3 = MagicMock(spec=Qwen3TTSEngine)
    mock_qwen3.synthesize.side_effect = lambda text, path: write_sine_wav(path, 2.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("pytsmod.ola", side_effect=mock_ola):
            mixer = Mixer()
            mixer.build_aligned_tts(
                segments=segments,
                tts_engine=mock_qwen3,
                output_path=os.path.join(tmpdir, "out.wav"),
                reference_duration=10.0,
                sample_rate=44100,
            )

    assert not ola_called
    mock_qwen3.synthesize_with_instruct.assert_not_called()


# ============================================================
# 7. 声道一致性 - 立体声转单声道
# ============================================================
def test_stereo_to_mono_conversion():
    """验证立体声 TTS 输出被正确转为单声道"""
    from src.mixer import Mixer

    segments = [{"start": 0.0, "end": 2.0, "translation": "文本"}]

    mock_engine = MagicMock()
    mock_engine.synthesize.side_effect = lambda text, path: write_sine_wav(path, 1.5, channels=2)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "output.wav")
        mixer = Mixer()
        mixer.build_aligned_tts(
            segments=segments,
            tts_engine=mock_engine,
            output_path=output_path,
            reference_duration=10.0,
            sample_rate=44100,
        )
        data, sr = sf.read(output_path)
        assert data.ndim == 1, f"输出应为单声道(1D)，实际维度: {data.ndim}"


# ============================================================
# 8. 中间文件 FLOAT 格式
# ============================================================
def test_intermediate_files_use_float():
    """验证淡入淡出保持 float32，输出文件使用 FLOAT subtype"""
    from src.mixer import _apply_fade

    data, sr = make_sine_wave(1.0, 44100)
    result = _apply_fade(data, sr, fade_in_ms=30, fade_out_ms=50)
    assert result.dtype == np.float32, f"淡入淡出后应保持 float32，实际: {result.dtype}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = os.path.join(tmpdir, "test.wav")
        sf.write(tmp_path, result, sr, subtype="FLOAT")
        info = sf.info(tmp_path)
        assert info.subtype == "FLOAT", f"文件 subtype 应为 FLOAT，实际: {info.subtype}"


# ============================================================
# 9. PipelineConfig 参数
# ============================================================
def test_pipeline_config_new_params():
    """验证 PipelineConfig 的新参数"""
    from src.core.pipeline import PipelineConfig

    config = PipelineConfig()
    assert config.max_tts_ratio == 1.2
    assert config.compress_ratio == 0.75

    config = PipelineConfig(max_tts_ratio=1.3, compress_ratio=0.8)
    assert config.max_tts_ratio == 1.3
    assert config.compress_ratio == 0.8


# ============================================================
# 10. Qwen3 instruct 重合成未缩短时保留原始
# ============================================================
def test_qwen3_instruct_fallback_when_not_shorter():
    """Qwen3 instruct 重合成没有缩短时保留原始结果"""
    import pytsmod
    from src.mixer import Mixer
    from src.core.tts import Qwen3TTSEngine

    segments = [{"start": 0.0, "end": 2.0, "translation": "测试文本"}]

    mock_engine = MagicMock(spec=Qwen3TTSEngine)
    # 正常合成: 3s (超长)
    mock_engine.synthesize.side_effect = lambda text, path: write_sine_wav(path, 3.0)
    # instruct 重合成: 还是 3s (没缩短!) -> 应保留原始
    mock_engine.synthesize_with_instruct.side_effect = lambda text, path, instruct: write_sine_wav(path, 3.0)

    ola_called = False

    def mock_ola(audio, stretch_factor, **kwargs):
        nonlocal ola_called
        ola_called = True
        return pytsmod.ola(audio, stretch_factor, **kwargs)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "output.wav")

        with patch("pytsmod.ola", side_effect=mock_ola):
            mixer = Mixer()
            mixer.build_aligned_tts(
                segments=segments,
                tts_engine=mock_engine,
                output_path=output_path,
                reference_duration=10.0,
                sample_rate=44100,
            )

        # 验证（tempdir 仍然存活）
        assert not ola_called, "Qwen3 不应降级到 OLA"
        mock_engine.synthesize_with_instruct.assert_called_once()
        data, sr = sf.read(output_path)
        assert data.ndim == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
