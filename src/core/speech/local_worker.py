"""Private one-request worker for dependency-isolated speech providers."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def execute(payload):
    import soundfile as sf

    request = payload["request"]
    params = request["parameters"]
    options, variant = params["options"], params["variant"]
    output = payload["output_path"]
    if request["provider_id"] == "voxcpm2":
        from src.core.engines.tts.voxcpm2 import VoxCPM2Engine

        reference = payload["references"].get(variant["value"]) if variant["kind"] == "reference" else None
        engine = VoxCPM2Engine(model_dir=payload["model_path"], cfg_value=options["cfg_value"],
            inference_timesteps=options["inference_timesteps"], load_denoiser=False,
            device_map=options["device"], reference_wav_path=reference)
        instruction = "，".join(part for part in [variant["value"] if variant["kind"] == "design" else "", params["instruction"]] if part)
        text = f"({instruction}){request['text']}" if instruction else request["text"]
        engine.synthesize(text, output)
    elif request["provider_id"] == "qwen3":
        import torch
        from qwen_tts import Qwen3TTSModel
        from src.core.tts import normalize_qwen3_language

        device = options["device"]
        if device == "auto":
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        precision = payload.get("precision", "auto")
        dtype = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}.get(precision,
            torch.float32 if device == "cpu" else torch.bfloat16)
        model = Qwen3TTSModel.from_pretrained(payload["model_path"], device_map=device,
            dtype=dtype)
        arguments = {"text": request["text"], "language": normalize_qwen3_language(params["language"]),
            "temperature": options["temperature"], "top_p": options["top_p"]}
        if variant["kind"] == "reference":
            wavs, rate = model.generate_voice_clone(**arguments,
                ref_audio=payload["references"][variant["value"]], ref_text=params["reference_transcript"])
        elif variant["kind"] == "design":
            instruction = "，".join(x for x in [variant["value"], params["instruction"]] if x)
            wavs, rate = model.generate_voice_design(**arguments, instruct=instruction)
        else:
            wavs, rate = model.generate_custom_voice(**arguments, speaker=variant["value"], instruct=params["instruction"])
        sf.write(output, wavs[0], rate)
    else:
        raise ValueError("unsupported local provider")
    Path(payload["response_path"]).write_text(json.dumps({"output_path": output}), encoding="utf-8")


if __name__ == "__main__":
    execute(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
