"""Run with .runtimes/qwen_tts/Scripts/python.exe; uses local models offline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/whisper-exploration")
    parser.add_argument("--text", default="今天辛苦了。放松下来，慢慢呼吸，我会在这里陪着你。")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import numpy as np
    import soundfile as sf
    import torch
    from src.core.engines.tts.service import TtsEngineRuntime

    args.output.mkdir(parents=True, exist_ok=True)
    runtime = TtsEngineRuntime(enable_runtime_routing=False)
    results = []
    for style in ("normal", "soft", "whisper"):
        torch.manual_seed(42)
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        target = args.output / f"{style}.wav"
        started = time.perf_counter()
        runtime.synthesize_text(
            text=args.text, output_path=str(target),
            profile={"provider": "qwen3", "model": "qwen3-custom-voice",
                     "common_options": {"voice": "Vivian", "language": "zh"},
                     "provider_options": {"speaking_style": style}},
        )
        elapsed = time.perf_counter() - started
        audio, sr = sf.read(target, always_2d=True)
        if not audio.size or not np.isfinite(audio).all() or not np.any(audio):
            raise RuntimeError(f"Invalid or silent output: {target}")
        results.append({"style": style, "path": str(target.resolve()),
                        "seconds": len(audio) / sr, "sample_rate": sr,
                        "channels": audio.shape[1], "elapsed_seconds": elapsed,
                        "rms": float(np.sqrt(np.mean(audio ** 2))),
                        "peak": float(np.max(np.abs(audio))),
                        "peak_cuda_gib": torch.cuda.max_memory_allocated() / 1024**3
                        if torch.cuda.is_available() else None})
        (args.output / "results.json").write_text(
            json.dumps({"text": args.text, "seed": 42, "results": results},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
