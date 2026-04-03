#!/usr/bin/env python3
"""
Qwen3-TTS 最小用例测试 - 使用 qwen_tts 0.1.1 新 API
"""
import sys
import os
import time
import traceback

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1, encoding='utf-8', errors='replace')
sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', buffering=1, encoding='utf-8', errors='replace')

def log(msg):
    print(msg, flush=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

log("=" * 50)
log("Qwen3-TTS 最小用例测试 (qwen_tts 0.1.1)")
log("=" * 50)

import torch
log(f"PyTorch: {torch.__version__}, CUDA: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    log(f"GPU: {torch.cuda.get_device_name(0)}, VRAM: {torch.cuda.memory_allocated()/1024**3:.2f}GB")

# Step 1: Import
log("\nStep 1: import qwen_tts")
try:
    import qwen_tts
    from qwen_tts import Qwen3TTSModel
    log(f"[PASS] qwen_tts {getattr(qwen_tts, '__version__', '?')}")
except Exception as e:
    log(f"[FAIL] {e}")
    traceback.print_exc()
    sys.exit(1)

# Step 2: Load model
log("\nStep 2: 加载 CustomVoice 模型")
model_dir = os.path.join(PROJECT_ROOT, "models", "qwen3tts", "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice")
log(f"Model dir: {model_dir}")

t0 = time.time()
try:
    model = Qwen3TTSModel.from_pretrained(model_dir, device_map="cuda:0", torch_dtype=torch.bfloat16)
    log(f"[PASS] 加载成功, {time.time()-t0:.1f}s, VRAM: {torch.cuda.memory_allocated()/1024**3:.2f}GB")
except Exception as e:
    log(f"[FAIL] {e}")
    traceback.print_exc()
    sys.exit(1)

# Step 3: Synthesize 1 sentence
log("\nStep 3: 合成第 1 句 (Vivian, zh)")
output_dir = os.path.join(PROJECT_ROOT, "output", "test_qwen3_minimal")
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, "test_01.wav")
text1 = "你好"

log(f"Text: '{text1}'")
t0 = time.time()
try:
    wavs, sr = model.generate_custom_voice(text1, speaker="Vivian", language="chinese")
    t_gen = time.time() - t0
    import soundfile as sf
    import numpy as np
    audio = wavs[0].astype(np.float32)
    sf.write(output_path, audio, sr)
    info = sf.info(output_path)
    log(f"[PASS] 合成成功, {t_gen:.1f}s, Duration: {info.duration:.2f}s, SR: {info.samplerate}, Size: {os.path.getsize(output_path)/1024/1024:.2f}MB")
except Exception as e:
    log(f"[FAIL] {e}")
    traceback.print_exc()

# Step 4: Synthesize 2nd sentence
log("\nStep 4: 合成第 2 句 (Vivian, zh, instruct)")
output_path2 = os.path.join(output_dir, "test_02.wav")
text2 = "辛苦了"
log(f"Text: '{text2}', Instruct: '温柔的'")
t0 = time.time()
try:
    wavs, sr = model.generate_custom_voice(text2, speaker="Vivian", language="chinese", instruct="温柔的")
    t_gen = time.time() - t0
    audio = wavs[0].astype(np.float32)
    sf.write(output_path2, audio, sr)
    info = sf.info(output_path2)
    log(f"[PASS] 合成成功, {t_gen:.1f}s, Duration: {info.duration:.2f}s, SR: {info.samplerate}, Size: {os.path.getsize(output_path2)/1024/1024:.2f}MB")
except Exception as e:
    log(f"[FAIL] {e}")
    traceback.print_exc()

# Step 5: Longer text
log("\nStep 5: 合成较长文本 (Serena, zh, instruct)")
output_path3 = os.path.join(output_dir, "test_03.wav")
text3 = "已经工作了一整天了吧？来，闭上眼睛，让我帮你放松一下。"
log(f"Text: '{text3}', Instruct: '轻声细语的，温柔的'")
t0 = time.time()
try:
    wavs, sr = model.generate_custom_voice(text3, speaker="Serena", language="chinese", instruct="轻声细语的，温柔的")
    t_gen = time.time() - t0
    audio = wavs[0].astype(np.float32)
    sf.write(output_path3, audio, sr)
    info = sf.info(output_path3)
    log(f"[PASS] 合成成功, {t_gen:.1f}s, Duration: {info.duration:.2f}s, SR: {info.samplerate}, Size: {os.path.getsize(output_path3)/1024/1024:.2f}MB")
except Exception as e:
    log(f"[FAIL] {e}")
    traceback.print_exc()

# Step 6: Test via project engine (Qwen3TTSEngine)
log("\nStep 6: 通过项目 TTSEngine 测试 (Qwen3TTSEngine)")
output_path4 = os.path.join(output_dir, "test_04_engine.wav")
try:
    from src.core.tts import TTSEngine
    tts = TTSEngine(engine="qwen3", voice="Vivian", speed=1.0)
    t0 = time.time()
    result = tts.synthesize("测试项目引擎", str(output_path4))
    t_gen = time.time() - t0
    import soundfile as sf
    info = sf.info(result)
    log(f"[PASS] 项目引擎合成成功, {t_gen:.1f}s, Duration: {info.duration:.2f}s, Size: {os.path.getsize(result)/1024/1024:.2f}MB")
except Exception as e:
    log(f"[FAIL] {e}")
    traceback.print_exc()

# Cleanup
log("\nCleanup")
del model
torch.cuda.empty_cache()
log(f"VRAM: {torch.cuda.memory_allocated()/1024**3:.2f}GB")
log("\n[DONE]")
