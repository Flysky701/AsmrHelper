"""Offline short VoxCPM2 voice-design probe; does not modify provider code."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from src.core.engines.tts.voxcpm2 import VoxCPM2Engine

    output = ROOT / "output/voxcpm-whisper-exploration"
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    engine = VoxCPM2Engine(model_dir=str(ROOT / "models/voxcpm2"),
                          load_denoiser=False, device_map="cuda",
                          inference_timesteps=10)
    load_seconds = time.perf_counter() - started
    text = "今天辛苦了。放松下来，慢慢呼吸，我会在这里陪着你。"
    results = []
    for name, description in [
        ("normal", "年轻女性，普通话，自然平静地说话"),
        ("whisper", "年轻女性，普通话，贴近耳边的气声耳语，轻声低语，吐字清晰"),
    ]:
        torch.manual_seed(42)
        np.random.seed(42)
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        path = output / f"{name}.wav"
        engine.synthesize(f"({description}){text}", str(path))
        elapsed = time.perf_counter() - started
        audio, sr = sf.read(path, always_2d=True)
        if not audio.size or not np.isfinite(audio).all() or not np.any(audio):
            raise RuntimeError("Invalid or silent audio")
        results.append(dict(style=name, description=description, seconds=len(audio)/sr,
                            elapsed_seconds=elapsed, sample_rate=sr, channels=audio.shape[1],
                            rms=float(np.sqrt(np.mean(audio**2))), peak=float(np.max(np.abs(audio))),
                            peak_cuda_gib=torch.cuda.max_memory_allocated()/1024**3))
        (output / "results.json").write_text(json.dumps(dict(
            text=text, load_seconds=load_seconds, mode="voice_design_without_reference",
            results=results), ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
