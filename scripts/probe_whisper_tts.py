"""Run with the project Python; Speech uses the isolated Qwen worker offline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

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
    from src.app.services.speech_service import get_speech_service
    from src.core.speech.compiler import compile_recipe
    from src.core.speech.store import build_plan

    args.output.mkdir(parents=True, exist_ok=True)
    service = get_speech_service()
    snapshot = service.pipeline_snapshot({"provider": "qwen3", "model": "qwen3-custom-voice",
                                          "options": {"voice": "Vivian", "language": "zh"}})
    results = []
    for style in ("normal", "soft", "whisper"):
        target = args.output / f"{style}.wav"
        started = time.perf_counter()
        plan = build_plan(args.text)
        for segment in plan["segments"]:
            segment["delivery"] = style
        plan = service.store.create("plans", plan)
        experiment_id = uuid4().hex
        task_id = "speech-probe-" + experiment_id
        media_root = args.output.resolve() / "speech" / experiment_id
        service.store.create("experiments", {"id": experiment_id, "name": f"Qwen {style} probe",
            "kind": "formal", "task_id": task_id, "media_root": str(media_root),
            "plan_id": plan["id"], "snapshot": snapshot})
        requests = compile_recipe(snapshot["recipe"], plan, snapshot["assets"])
        takes = service.run_requests(requests, snapshot, task_id=task_id,
            experiment_id=experiment_id, plan_id=plan["id"], media_root=media_root)
        for take in takes:
            service.select({"experiment_id": experiment_id, "segment_id": take["segment_id"], "take_id": take["id"]})
        assembly = service.assemble(experiment_id)
        samples, rate = sf.read(assembly["audio_path"])
        sf.write(target, samples, rate)
        elapsed = time.perf_counter() - started
        audio, sr = sf.read(target, always_2d=True)
        if not audio.size or not np.isfinite(audio).all() or not np.any(audio):
            raise RuntimeError(f"Invalid or silent output: {target}")
        results.append({"style": style, "path": str(target.resolve()),
                        "seconds": len(audio) / sr, "sample_rate": sr,
                        "channels": audio.shape[1], "elapsed_seconds": elapsed,
                        "rms": float(np.sqrt(np.mean(audio ** 2))),
                        "peak": float(np.max(np.abs(audio)))})
        (args.output / "results.json").write_text(
            json.dumps({"text": args.text, "execution": "Speech isolated worker", "results": results},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
