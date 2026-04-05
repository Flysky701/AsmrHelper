"""验证所有 AI 模型完整性（Whisper + Qwen3-TTS）"""
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
all_ok = True

# ============================================================
# Qwen3-TTS 模型
# ============================================================
qwen3_base = project_root / "models" / "qwen3tts"
qwen3_models = {
    "CustomVoice": "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "VoiceDesign": "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "Base":        "models--Qwen--Qwen3-TTS-12Hz-1.7B-Base",
}

print("Qwen3-TTS Model Status")
print("=" * 65)

for label, subdir in qwen3_models.items():
    d = qwen3_base / subdir
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

# ============================================================
# Faster-Whisper 模型
# ============================================================
whisper_base = project_root / "models" / "whisper"
whisper_models = {
    "tiny":     "约 39 MB",
    "base":     "约 74 MB",
    "small":    "约 244 MB",
    "medium":   "约 769 MB",
    "large-v3": "约 1550 MB",
}

print("Faster-Whisper Model Status")
print("=" * 65)

for name, size_desc in whisper_models.items():
    # faster_whisper 下载到 models/whisper/<name>/ 或 models/whisper/models--guillaumeln--rft-<name>/
    model_dir = whisper_base / name
    alt_dir = whisper_base / f"models--guillaumeln--rft-{name}"

    found = False
    found_dir = None
    for d in [model_dir, alt_dir]:
        if d.exists() and d.is_dir():
            total_size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024 / 1024
            if total_size > 10:  # > 10MB 认为有效
                found = True
                found_dir = d
                break

    status = "OK" if found else "NOT FOUND"
    if not found:
        all_ok = False
    print(f"  [{name}] {status}")
    print(f"    Path: {found_dir or '(not downloaded)'}")
    if found:
        total_size = sum(f.stat().st_size for f in found_dir.rglob("*") if f.is_file()) / 1024 / 1024
        print(f"    Size: {total_size:.1f} MB ({size_desc})")
    else:
        print(f"    Size: {size_desc}")
    print()

# ============================================================
# 结果汇总
# ============================================================
print("=" * 65)
if all_ok:
    print("All models verified successfully!")
else:
    print("WARNING: Some models are missing or incomplete!")
    print("")
    print("To download models:")
    print("  uv run python scripts/install_models.py              # Whisper base")
    print("  uv run python scripts/install_models.py --all       # All models")
    print("  uv run python scripts/install_models.py --mirror    # Use mirror")
print("=" * 65)
