#!/usr/bin/env python3
"""
Step 4 only: Qwen3-TTS 逐句合成 + 时间轴对齐测试
利用已存在的人声文件和 VTT 字幕
"""
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output" / "test_cuda_fullflow"
TEST_VTT = PROJECT_ROOT / "ASMR_O" / "#2.千寻的治愈的放松手交.wav.vtt"

def find_vocal_path():
    for f in OUTPUT_DIR.glob("*vocals.wav"):
        return f
    default = OUTPUT_DIR / "vocals.wav"
    if default.exists():
        return default
    return None

def main():
    import torch
    import soundfile as sf

    print("=" * 60)
    print("Step 4: Qwen3-TTS 逐句合成 + 时间轴对齐")
    print("=" * 60)

    # 查找人声文件
    vocal_path = find_vocal_path()
    if not vocal_path:
        print(f"[FAIL] 找不到人声文件 in {OUTPUT_DIR}")
        return 1
    print(f"Vocal: {vocal_path.name}")

    # 加载 VTT
    from src.core.translate import load_vtt_translations, load_vtt_with_timestamps
    translations = load_vtt_translations(str(TEST_VTT))
    vtt_entries = load_vtt_with_timestamps(str(TEST_VTT))
    print(f"VTT: {len(translations)} translations, {len(vtt_entries)} timestamped entries")

    # 参考音频信息
    ref_info = sf.info(str(vocal_path))
    ref_duration = ref_info.duration
    sample_rate = ref_info.samplerate
    print(f"Reference: {ref_duration:.1f}s, {sample_rate}Hz")

    # 构造 timestamped_segments
    timestamped_segments = []
    for entry, trans in zip(vtt_entries, translations):
        timestamped_segments.append({
            "start": entry["start"],
            "end": entry["end"],
            "text": entry["text"],
            "translation": trans,
        })

    # 初始化 Qwen3-TTS
    print("\n[Qwen3-TTS] 初始化...")
    t0 = time.time()
    from src.core.tts import TTSEngine
    tts_engine = TTSEngine(engine="qwen3", voice="Vivian", speed=1.0)
    print(f"[Qwen3-TTS] 初始化完成: {time.time()-t0:.1f}s")

    # 初始化 Mixer
    from src.mixer import Mixer
    mixer = Mixer(original_volume=0.85, tts_volume_ratio=0.5, tts_delay_ms=0)

    # 逐句合成 + 时间轴对齐
    tts_aligned_path = str(OUTPUT_DIR / "tts_aligned.wav")
    print(f"\n[Qwen3-TTS] 开始逐句合成 {len(timestamped_segments)} 段...")
    print(f"[Qwen3-TTS] 这可能需要 20-40 分钟，请耐心等待...")

    t0 = time.time()
    try:
        mixer.build_aligned_tts(
            segments=timestamped_segments,
            tts_engine=tts_engine.engine,
            output_path=tts_aligned_path,
            reference_duration=ref_duration,
            sample_rate=sample_rate,
        )
    except Exception as e:
        print(f"[FAIL] build_aligned_tts 失败: {e}")
        traceback.print_exc()
        from src.core.tts import Qwen3TTSEngine
        Qwen3TTSEngine.unload_model()
        return 1

    t_tts = time.time() - t0

    # 验证输出
    from pathlib import Path
    tts_aligned = Path(tts_aligned_path)
    if not tts_aligned.exists():
        print(f"[FAIL] TTS 对齐文件未生成: {tts_aligned_path}")
        from src.core.tts import Qwen3TTSEngine
        Qwen3TTSEngine.unload_model()
        return 1

    tts_info = sf.info(tts_aligned_path)
    tts_size = tts_aligned.stat().st_size / 1024 / 1024

    print(f"\n[PASS] Qwen3-TTS 合成完成!")
    print(f"  Output: {tts_aligned.name} ({tts_size:.1f} MB)")
    print(f"  Duration: {tts_info.duration:.1f}s (ref: {ref_duration:.1f}s)")
    print(f"  Time: {t_tts:.1f}s")

    # 释放模型
    from src.core.tts import Qwen3TTSEngine
    Qwen3TTSEngine.unload_model()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        print(f"  VRAM after unload: {torch.cuda.memory_allocated()/1024**3:.2f}GB")

    return 0

if __name__ == "__main__":
    sys.exit(main())
