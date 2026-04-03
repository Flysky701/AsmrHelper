"""Environment verification script - checks all critical packages after CUDA migration."""
import sys

def check(label, func):
    try:
        result = func()
        status = "OK"
        detail = str(result)
    except Exception as e:
        status = "FAIL"
        detail = str(e)
    print(f"  [{status}] {label}")
    if detail:
        print(f"         {detail}")
    return status == "OK"

print("=" * 65)
print("Environment Verification Report")
print("=" * 65)

results = []

# 1. Python
results.append(check(
    "Python",
    lambda: f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
))

# 2. PyTorch
results.append(check("PyTorch CUDA", lambda: (
    __import__("torch"),
    f"torch={__import__('torch').__version__}, cuda={__import__('torch').cuda.is_available()}"
)[-1]))

# 3. GPU
results.append(check("GPU", lambda: (
    __import__("torch"),
    f"{__import__('torch').cuda.get_device_name(0)} ({__import__('torch').cuda.get_device_capability(0)})"
)[-1]))

# 4. Flash Attention
results.append(check("flash-attn", lambda: (
    __import__("flash_attn"),
    f"flash_attn {__import__('flash_attn').__version__}"
)[-1]))

# 5. flash_attn_func
results.append(check("flash_attn_func", lambda: (
    __import__("flash_attn", fromlist=["flash_attn_func"]).flash_attn_func,
    "imported"
)[-1]))

# 6. Demucs
results.append(check("demucs", lambda: (
    __import__("demucs"),
    f"demucs {__import__('demucs').__version__}"
)[-1]))

# 7. Faster-Whisper
results.append(check("faster-whisper", lambda: (
    __import__("faster_whisper"),
    f"faster_whisper {__import__('faster_whisper').__version__}"
)[-1]))

# 8. Edge-TTS
results.append(check("edge-tts", lambda: (
    __import__("edge_tts"),
    f"edge_tts OK"
)[-1]))

# 9. Qwen-TTS
results.append(check("qwen-tts", lambda: (
    __import__("qwen_tts"),
    f"qwen_tts {__import__('qwen_tts').__version__}"
)[-1]))

# 10. Transformers
results.append(check("transformers", lambda: (
    __import__("transformers"),
    f"transformers {__import__('transformers').__version__}"
)[-1]))

# 11. PySide6
results.append(check("PySide6", lambda: (
    __import__("PySide6"),
    f"PySide6 {__import__('PySide6').__version__}"
)[-1]))

# 12. NumPy
results.append(check("numpy", lambda: (
    __import__("numpy"),
    f"numpy {__import__('numpy').__version__}"
)[-1]))

# 13. torchaudio
results.append(check("torchaudio", lambda: (
    __import__("torchaudio"),
    f"torchaudio {__import__('torchaudio').__version__}"
)[-1]))

# 14. huggingface_hub
results.append(check("huggingface_hub", lambda: (
    __import__("huggingface_hub"),
    f"huggingface_hub {__import__('huggingface_hub').__version__}"
)[-1]))

print("=" * 65)
passed = sum(results)
total = len(results)
print(f"Result: {passed}/{total} passed")
if passed == total:
    print("All checks passed!")
else:
    failed = total - passed
    print(f"WARNING: {failed} check(s) failed!")
print("=" * 65)
