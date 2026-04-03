"""验证所有 Qwen3-TTS 模型完整性"""
import os
from pathlib import Path

base = Path("models/qwen3tts")
models = {
    "CustomVoice": "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "VoiceDesign": "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "Base":        "models--Qwen--Qwen3-TTS-12Hz-1.7B-Base",
}

print("Qwen3-TTS Model Status")
print("=" * 65)
all_ok = True
for label, subdir in models.items():
    d = base / subdir
    has_safetensors = (d / "model.safetensors").exists()
    has_config = (d / "config.json").exists()
    has_tokenizer = (d / "vocab.json").exists()
    has_speech_tok = (d / "speech_tokenizer").exists()
    size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024 / 1024
    ok = has_safetensors and has_config and has_tokenizer and has_speech_tok
    status = "OK" if ok else "INCOMPLETE"
    if not ok:
        all_ok = False
    print(f"  [{label}] {status}")
    print(f"    Path: {d}")
    print(f"    Size: {size:.1f} MB")
    sep = " | "
    parts = []
    parts.append("model.safetensors: " + ("YES" if has_safetensors else "NO"))
    parts.append("config.json: " + ("YES" if has_config else "NO"))
    parts.append("vocab.json: " + ("YES" if has_tokenizer else "NO"))
    parts.append("speech_tokenizer: " + ("YES" if has_speech_tok else "NO"))
    print(f"    {sep.join(parts)}")
    print()

if all_ok:
    print("All 3 models verified successfully!")
else:
    print("WARNING: Some models are incomplete!")
