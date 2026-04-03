#!/usr/bin/env python3
"""
CUDA + flash-attn + Qwen3-TTS 全流程测试脚本

测试内容:
  Part 1: CUDA 基础能力测试
    - PyTorch CUDA 可用性
    - GPU 信息
    - flash-attn 功能验证（实际 CUDA kernel 调用）
    - GPU 矩阵运算基准
    - 显存管理

  Part 2: ASMR 全流程测试（Qwen3-TTS + 中文 VTT）
    - Step 1: 人声分离 (Demucs CUDA)
    - Step 2: 跳过（中文 VTT）
    - Step 3: 跳过（中文 VTT）
    - Step 4: Qwen3-TTS 逐句合成 + 时间轴对齐
    - Step 5: 混音

输出: tests/test_cuda_fullflow_report.txt
"""

import sys
import os
import time
import traceback
from pathlib import Path
from datetime import datetime

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 输出文件
REPORT_PATH = PROJECT_ROOT / "tests" / "test_cuda_fullflow_report.txt"
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

# 测试音频
TEST_AUDIO = PROJECT_ROOT / "ASMR_O" / "#2.千寻的治愈的放松手交.wav"
TEST_VTT = PROJECT_ROOT / "ASMR_O" / "#2.千寻的治愈的放松手交.wav.vtt"
OUTPUT_DIR = PROJECT_ROOT / "output" / "test_cuda_fullflow"

# 日志收集
log_lines = []

def log(msg):
    """同时打印和收集日志"""
    print(msg)
    log_lines.append(msg)

def log_section(title):
    """打印分隔线"""
    log("")
    log("=" * 70)
    log(f"  {title}")
    log("=" * 70)

def log_subsection(title):
    log("")
    log(f"--- {title} ---")


# ============================================================
# Part 1: CUDA 基础能力测试
# ============================================================

def test_pytorch_cuda():
    """测试 1: PyTorch CUDA 基础"""
    log_subsection("Test 1.1: PyTorch CUDA")
    import torch

    version = torch.__version__
    cuda_available = torch.cuda.is_available()
    cuda_version = torch.version.cuda
    cudnn_version = torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else "N/A"

    log(f"  PyTorch version: {version}")
    log(f"  CUDA available: {cuda_available}")
    log(f"  CUDA version: {cuda_version}")
    log(f"  cuDNN version: {cudnn_version}")

    if not cuda_available:
        log("  [FAIL] CUDA 不可用!")
        return False

    gpu_name = torch.cuda.get_device_name(0)
    gpu_cap = torch.cuda.get_device_capability(0)
    gpu_mem_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    log(f"  GPU: {gpu_name}")
    log(f"  Compute Capability: {gpu_cap}")
    log(f"  VRAM: {gpu_mem_total:.1f} GB")

    passed = "cu126" in version or "cu124" in version
    log(f"  [{'PASS' if passed else 'FAIL'}] PyTorch CUDA 版本正确")
    return passed


def test_gpu_compute():
    """测试 2: GPU 实际计算"""
    log_subsection("Test 1.2: GPU 矩阵运算")
    import torch

    try:
        # 小矩阵运算
        t0 = time.time()
        a = torch.randn(1000, 1000, device="cuda")
        b = torch.randn(1000, 1000, device="cuda")
        c = torch.mm(a, b)
        torch.cuda.synchronize()
        t_small = time.time() - t0

        # 大矩阵运算（测试 GPU 带宽）
        torch.cuda.empty_cache()
        t0 = time.time()
        a = torch.randn(4096, 4096, device="cuda")
        b = torch.randn(4096, 4096, device="cuda")
        c = torch.mm(a, b)
        torch.cuda.synchronize()
        t_large = time.time() - t0

        log(f"  1000x1000 matmul: {t_small*1000:.1f}ms")
        log(f"  4096x4096 matmul: {t_large*1000:.1f}ms")

        # 验证结果正确性
        assert c.shape == (4096, 4096), "矩阵维度错误"
        assert not torch.isnan(c).any(), "结果包含 NaN"
        log(f"  [PASS] GPU 矩阵运算正确")

        # 清理
        del a, b, c
        torch.cuda.empty_cache()
        return True
    except Exception as e:
        log(f"  [FAIL] GPU 计算异常: {e}")
        traceback.print_exc()
        return False


def test_flash_attn():
    """测试 3: flash-attn 功能验证（实际 CUDA kernel 调用）"""
    log_subsection("Test 1.3: flash-attn CUDA kernel")
    import torch

    try:
        import flash_attn
        log(f"  flash_attn version: {flash_attn.__version__}")

        from flash_attn import flash_attn_func

        # 实际调用 flash attention
        batch_size = 2
        num_heads = 8
        seq_len = 512
        head_dim = 64

        t0 = time.time()
        q = torch.randn(batch_size, num_heads, seq_len, head_dim, device="cuda", dtype=torch.float16)
        k = torch.randn(batch_size, num_heads, seq_len, head_dim, device="cuda", dtype=torch.float16)
        v = torch.randn(batch_size, num_heads, seq_len, head_dim, device="cuda", dtype=torch.float16)

        # 调用 flash attention
        output = flash_attn_func(q, k, v)
        torch.cuda.synchronize()
        t_fa = time.time() - t0

        assert output.shape == (batch_size, num_heads, seq_len, head_dim), "输出维度错误"
        assert not torch.isnan(output).any(), "输出包含 NaN"

        log(f"  Input shape: ({batch_size}, {num_heads}, {seq_len}, {head_dim})")
        log(f"  Output shape: {tuple(output.shape)}")
        log(f"  Flash attention time: {t_fa*1000:.1f}ms")
        log(f"  [PASS] flash-attn CUDA kernel 正常工作")

        del q, k, v, output
        torch.cuda.empty_cache()
        return True
    except Exception as e:
        log(f"  [FAIL] flash-attn 测试失败: {e}")
        traceback.print_exc()
        return False


def test_bfloat16():
    """测试 4: bfloat16 支持（Qwen3-TTS 需要）"""
    log_subsection("Test 1.4: bfloat16 支持")
    import torch

    try:
        # 检查 GPU 是否支持 bfloat16
        gpu_cap = torch.cuda.get_device_capability(0)
        bf16_supported = gpu_cap >= (8, 0)  # Ampere+
        log(f"  GPU Compute Capability: {gpu_cap}")
        log(f"  bfloat16 supported: {bf16_supported}")

        if not bf16_supported:
            log(f"  [FAIL] GPU 不支持 bfloat16 (需要 >= 8.0)")
            return False

        # 实际测试 bfloat16 运算
        a = torch.randn(1024, 1024, device="cuda", dtype=torch.bfloat16)
        b = torch.randn(1024, 1024, device="cuda", dtype=torch.bfloat16)
        c = torch.mm(a, b)
        torch.cuda.synchronize()
        assert c.dtype == torch.bfloat16
        assert not torch.isnan(c).any()

        log(f"  bfloat16 matmul: OK")
        log(f"  [PASS] bfloat16 运算正常")

        del a, b, c
        torch.cuda.empty_cache()
        return True
    except Exception as e:
        log(f"  [FAIL] bfloat16 测试失败: {e}")
        traceback.print_exc()
        return False


def test_vram_management():
    """测试 5: 显存管理"""
    log_subsection("Test 1.5: 显存管理")
    import torch

    try:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        before_alloc = torch.cuda.memory_allocated() / 1024**3
        before_reserved = torch.cuda.memory_reserved() / 1024**3

        # 分配大块显存
        big_tensor = torch.randn(8192, 8192, device="cuda", dtype=torch.float16)  # ~1GB
        during_alloc = torch.cuda.memory_allocated() / 1024**3
        during_reserved = torch.cuda.memory_reserved() / 1024**3

        # 释放
        del big_tensor
        torch.cuda.empty_cache()
        after_alloc = torch.cuda.memory_allocated() / 1024**3
        after_reserved = torch.cuda.memory_reserved() / 1024**3

        peak_mem = torch.cuda.max_memory_allocated() / 1024**3

        log(f"  Before:  alloc={before_alloc:.2f}GB, reserved={before_reserved:.2f}GB")
        log(f"  During: alloc={during_alloc:.2f}GB, reserved={during_reserved:.2f}GB")
        log(f"  After:   alloc={after_alloc:.2f}GB, reserved={after_reserved:.2f}GB")
        log(f"  Peak:    {peak_mem:.2f}GB")

        released = during_alloc - after_alloc
        log(f"  Released: {released:.2f}GB")

        passed = released > 0  # 释放了显存即可
        log(f"  [{'PASS' if passed else 'FAIL'}] 显存释放正常")
        return passed
    except Exception as e:
        log(f"  [FAIL] 显存管理测试失败: {e}")
        traceback.print_exc()
        return False


def run_cuda_tests():
    """运行所有 CUDA 基础测试"""
    log_section("Part 1: CUDA 基础能力测试")

    results = {}
    tests = [
        ("PyTorch CUDA", test_pytorch_cuda),
        ("GPU 计算", test_gpu_compute),
        ("flash-attn", test_flash_attn),
        ("bfloat16", test_bfloat16),
        ("显存管理", test_vram_management),
    ]

    for name, func in tests:
        t0 = time.time()
        try:
            passed = func()
        except Exception as e:
            log(f"  [FAIL] {name}: {e}")
            traceback.print_exc()
            passed = False
        elapsed = time.time() - t0
        results[name] = {"passed": passed, "time": elapsed}
        log(f"  Time: {elapsed:.1f}s")

    return results


# ============================================================
# Part 2: ASMR 全流程测试（Qwen3-TTS）
# ============================================================

def check_test_files():
    """检查测试文件是否存在"""
    log_subsection("Test 2.0: 测试文件检查")

    audio_exists = TEST_AUDIO.exists()
    vtt_exists = TEST_VTT.exists()

    log(f"  Audio: {TEST_AUDIO}")
    log(f"    exists: {audio_exists}")
    if audio_exists:
        log(f"    size: {TEST_AUDIO.stat().st_size / 1024 / 1024:.1f} MB")

    log(f"  VTT: {TEST_VTT}")
    log(f"    exists: {vtt_exists}")
    if vtt_exists:
        lines = TEST_VTT.read_text(encoding="utf-8").strip().split("\n")
        log(f"    lines: {len(lines)}")

    if not audio_exists:
        log("  [FAIL] 测试音频文件不存在!")
        return False
    if not vtt_exists:
        log("  [WARN] VTT 文件不存在，将使用完整 5 步流程")

    return True


def test_demucs_cuda():
    """测试: 人声分离 (Demucs CUDA)"""
    log_subsection("Step 1/5: 人声分离 (Demucs CUDA)")
    import torch

    try:
        from src.core.vocal_separator import VocalSeparator

        # 检查 Demucs 是否使用 CUDA
        log(f"  CUDA available: {torch.cuda.is_available()}")

        t0 = time.time()
        separator = VocalSeparator(model_name="htdemucs")
        sep_results = separator.separate(str(TEST_AUDIO), str(OUTPUT_DIR), stems=["vocals"])
        elapsed = time.time() - t0

        vocal_path = Path(sep_results.get("vocals", ""))
        if not vocal_path.exists():
            log(f"  [FAIL] 人声文件未生成")
            return False, 0

        vocal_size = vocal_path.stat().st_size / 1024 / 1024
        log(f"  Vocal: {vocal_path.name} ({vocal_size:.1f} MB)")
        log(f"  Time: {elapsed:.1f}s")

        # 释放显存
        del separator
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            mem_after = torch.cuda.memory_allocated() / 1024**3
            log(f"  VRAM after cleanup: {mem_after:.2f}GB")

        log(f"  [PASS] 人声分离完成")
        return True, elapsed

    except Exception as e:
        log(f"  [FAIL] 人声分离失败: {e}")
        traceback.print_exc()
        return False, 0


def test_vtt_load():
    """测试: VTT 加载和时间戳解析"""
    log_subsection("Step 2/5: VTT 加载（中文 VTT 跳过 ASR）")

    try:
        from src.core.translate import load_vtt_translations, load_vtt_with_timestamps, detect_vtt_language

        translations = load_vtt_translations(str(TEST_VTT))
        vtt_entries = load_vtt_with_timestamps(str(TEST_VTT))
        lang = detect_vtt_language(translations)

        log(f"  Language: {lang}")
        log(f"  Translations: {len(translations)}")
        log(f"  Timestamped entries: {len(vtt_entries)}")

        if vtt_entries:
            first = vtt_entries[0]
            last = vtt_entries[-1]
            log(f"  First: [{first['start']:.2f}s - {first['end']:.2f}s] {first['text'][:30]}")
            log(f"  Last:  [{last['start']:.2f}s - {last['end']:.2f}s] {last['text'][:30]}")

        passed = len(vtt_entries) > 0
        log(f"  [{'PASS' if passed else 'FAIL'}] VTT 加载成功")

        return passed, vtt_entries, translations, lang

    except Exception as e:
        log(f"  [FAIL] VTT 加载失败: {e}")
        traceback.print_exc()
        return False, [], [], None


def find_vocal_path():
    """在输出目录中查找人声文件（Demucs 输出格式为 {stem}_vocals.wav）"""
    for f in OUTPUT_DIR.glob("*vocals.wav"):
        return f
    # fallback: vocal.wav
    default = OUTPUT_DIR / "vocals.wav"
    if default.exists():
        return default
    return None


def test_qwen3_tts_aligned(vtt_entries, translations):
    """测试: Qwen3-TTS 逐句合成 + 时间轴对齐"""
    log_subsection("Step 4/5: Qwen3-TTS 逐句合成 + 时间轴对齐")
    import torch
    import soundfile as sf

    try:
        # 查找人声文件
        vocal_path = find_vocal_path()
        if not vocal_path:
            log(f"  [FAIL] 找不到人声文件 in {OUTPUT_DIR}")
            return False, 0
        log(f"  Vocal file: {vocal_path.name}")

        # 加载参考音频信息
        ref_info = sf.info(str(vocal_path))
        ref_duration = ref_info.duration
        sample_rate = ref_info.samplerate
        log(f"  Reference audio: {ref_duration:.1f}s, {sample_rate}Hz")

        # 构造 timestamped_segments
        timestamped_segments = []
        for entry, trans in zip(vtt_entries, translations):
            timestamped_segments.append({
                "start": entry["start"],
                "end": entry["end"],
                "text": entry["text"],
                "translation": trans,
            })

        log(f"  Segments to synthesize: {len(timestamped_segments)}")

        # 初始化 Qwen3-TTS 引擎
        t0 = time.time()
        from src.core.tts import TTSEngine
        tts_engine = TTSEngine(engine="qwen3", voice="Vivian", speed=1.0)
        t_init = time.time() - t0
        log(f"  Qwen3-TTS init time: {t_init:.1f}s")

        # 初始化 Mixer
        from src.mixer import Mixer
        mixer = Mixer(original_volume=0.85, tts_volume_ratio=0.5, tts_delay_ms=0)

        # 逐句合成 + 时间轴对齐
        tts_aligned_path = str(OUTPUT_DIR / "tts_aligned.wav")
        t0 = time.time()
        mixer.build_aligned_tts(
            segments=timestamped_segments,
            tts_engine=tts_engine.engine,
            output_path=tts_aligned_path,
            reference_duration=ref_duration,
            sample_rate=sample_rate,
        )
        t_tts = time.time() - t0

        # 验证输出
        tts_aligned = Path(tts_aligned_path)
        if not tts_aligned.exists():
            log(f"  [FAIL] TTS 对齐文件未生成")
            return False, 0

        tts_info = sf.info(tts_aligned_path)
        tts_size = tts_aligned.stat().st_size / 1024 / 1024

        log(f"  TTS aligned: {tts_aligned.name} ({tts_size:.1f} MB)")
        log(f"  TTS duration: {tts_info.duration:.1f}s (ref: {ref_duration:.1f}s)")
        log(f"  TTS total time: {t_tts:.1f}s")

        # 时长差异检查
        duration_diff = abs(tts_info.duration - ref_duration)
        log(f"  Duration diff: {duration_diff:.1f}s")

        # 释放 Qwen3 模型
        from src.core.tts import Qwen3TTSEngine
        Qwen3TTSEngine.unload_model()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            mem_after = torch.cuda.memory_allocated() / 1024**3
            log(f"  VRAM after Qwen3 unload: {mem_after:.2f}GB")

        passed = tts_aligned.exists() and tts_info.duration > 0
        log(f"  [{'PASS' if passed else 'FAIL'}] Qwen3-TTS 逐句合成完成")

        return passed, t_tts

    except Exception as e:
        log(f"  [FAIL] Qwen3-TTS 测试失败: {e}")
        traceback.print_exc()
        try:
            from src.core.tts import Qwen3TTSEngine
            Qwen3TTSEngine.unload_model()
        except:
            pass
        return False, 0


def test_mix():
    """测试: 混音"""
    log_subsection("Step 5/5: 混音")

    try:
        from src.mixer import Mixer
        import soundfile as sf

        vp = find_vocal_path()
        if not vp:
            log(f"  [FAIL] 找不到人声文件")
            return False, 0
        vocal_path = str(vp)
        tts_path = str(OUTPUT_DIR / "tts_aligned.wav")
        mix_path = str(OUTPUT_DIR / "final_mix.wav")

        t0 = time.time()
        mixer = Mixer(original_volume=0.85, tts_volume_ratio=0.5, tts_delay_ms=0)
        mixer.mix(vocal_path, tts_path, mix_path, adjust_tts_volume=True)
        elapsed = time.time() - t0

        mix_file = Path(mix_path)
        if not mix_file.exists():
            log(f"  [FAIL] 混音文件未生成")
            return False, 0

        mix_size = mix_file.stat().st_size / 1024 / 1024
        mix_info = sf.info(mix_path)

        log(f"  Mix: {mix_file.name} ({mix_size:.1f} MB)")
        log(f"  Duration: {mix_info.duration:.1f}s")
        log(f"  Time: {elapsed:.1f}s")
        log(f"  [PASS] 混音完成")

        return True, elapsed

    except Exception as e:
        log(f"  [FAIL] 混音失败: {e}")
        traceback.print_exc()
        return False, 0


def run_fullflow_tests():
    """运行全流程测试"""
    log_section("Part 2: ASMR 全流程测试 (Qwen3-TTS + 中文 VTT)")

    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = {}

    # 0. 文件检查
    files_ok = check_test_files()
    if not files_ok:
        log("测试文件缺失，无法继续全流程测试")
        return results

    # Step 1: 人声分离
    passed, elapsed = test_demucs_cuda()
    results["Step1_人声分离"] = {"passed": passed, "time": elapsed}

    if not passed:
        log("人声分离失败，无法继续后续测试")
        return results

    # Step 2: VTT 加载（中文 VTT 跳过 ASR 和翻译）
    passed, vtt_entries, translations, lang = test_vtt_load()
    results["Step2_VTT加载"] = {"passed": passed, "time": 0}
    results["Step3_翻译跳过"] = {"passed": True, "time": 0, "note": f"中文VTT, {len(translations)} 条"}

    if not passed or not vtt_entries:
        log("VTT 加载失败，无法继续 TTS 测试")
        return results

    # Step 4: Qwen3-TTS 逐句合成 + 时间轴对齐
    passed, elapsed = test_qwen3_tts_aligned(vtt_entries, translations)
    results["Step4_Qwen3_TTS"] = {"passed": passed, "time": elapsed}

    if not passed:
        log("Qwen3-TTS 失败，无法继续混音测试")
        return results

    # Step 5: 混音
    passed, elapsed = test_mix()
    results["Step5_混音"] = {"passed": passed, "time": elapsed}

    return results


# ============================================================
# Main
# ============================================================

def main():
    t_total_start = time.time()

    log("=" * 70)
    log("  CUDA + flash-attn + Qwen3-TTS 全流程测试")
    log(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 70)

    # Part 1: CUDA 基础测试
    cuda_results = run_cuda_tests()

    # Part 2: 全流程测试
    flow_results = run_fullflow_tests()

    # 汇总
    t_total = time.time() - t_total_start
    log_section("测试结果汇总")

    all_passed = True
    all_results = {**cuda_results, **flow_results}

    for name, result in all_results.items():
        status = "PASS" if result["passed"] else "FAIL"
        elapsed = result.get("time", 0)
        note = result.get("note", "")
        log(f"  [{status}] {name}: {elapsed:.1f}s  {note}")
        if not result["passed"]:
            all_passed = False

    log("")
    total_passed = sum(1 for r in all_results.values() if r["passed"])
    total_count = len(all_results)
    log(f"  Total: {total_passed}/{total_count} passed, {t_total:.1f}s")

    if all_passed:
        log("  ALL TESTS PASSED!")
    else:
        log(f"  {total_count - total_passed} test(s) FAILED!")

    log("")
    log("=" * 70)

    # 保存报告
    report_text = "\n".join(log_lines)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    log(f"Report saved to: {REPORT_PATH}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
