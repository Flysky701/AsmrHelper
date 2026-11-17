"""Private isolated worker for dependency-isolated speech providers (single-shot & batch session)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


def _atomic_write_json(path: Path, data: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=".resp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _build_runner(payload: dict):
    import soundfile as sf

    first_request = payload["request"]
    provider_id = first_request["provider_id"]
    params = first_request["parameters"]
    options, variant = params["options"], params["variant"]

    if provider_id == "voxcpm2":
        from src.core.engines.tts.voxcpm2 import VoxCPM2Engine

        reference = payload["references"].get(variant["value"]) if variant["kind"] == "reference" else None
        engine = VoxCPM2Engine(
            model_dir=payload["model_path"],
            cfg_value=options["cfg_value"],
            inference_timesteps=options["inference_timesteps"],
            load_denoiser=False,
            device_map=payload.get("device", options.get("device", "auto")),
            reference_wav_path=reference,
        )

        def run_voxcpm2(request: dict, references: dict, output: str) -> None:
            req_params = request["parameters"]
            req_opts, req_var = req_params["options"], req_params["variant"]
            engine.cfg_value = float(req_opts["cfg_value"])
            engine.inference_timesteps = int(req_opts["inference_timesteps"])
            engine.default_reference_wav = (
                references.get(req_var["value"]) if req_var["kind"] == "reference" else None
            )
            instruction = "，".join(
                part
                for part in [
                    req_var["value"] if req_var["kind"] == "design" else "",
                    req_params["instruction"],
                ]
                if part
            )
            text = f"({instruction}){request['text']}" if instruction else request["text"]
            engine.synthesize(text, output)

        return run_voxcpm2

    if provider_id == "qwen3":
        import torch
        from qwen_tts import Qwen3TTSModel
        from src.core.tts import normalize_qwen3_language

        device = payload.get("device", options.get("device", "cuda:0"))
        if device == "auto":
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        precision = payload.get("precision", "auto")
        dtype = {
            "float32": torch.float32,
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
        }.get(precision, torch.float32 if device == "cpu" else torch.bfloat16)
        model = Qwen3TTSModel.from_pretrained(payload["model_path"], device_map=device, dtype=dtype)

        def run_qwen3(request: dict, references: dict, output: str) -> None:
            req_params = request["parameters"]
            req_opts, req_var = req_params["options"], req_params["variant"]
            arguments = {
                "text": request["text"],
                "language": normalize_qwen3_language(req_params["language"]),
                "temperature": req_opts["temperature"],
                "top_p": req_opts["top_p"],
            }
            for key in ("do_sample", "top_k", "repetition_penalty", "max_new_tokens"):
                if key in req_opts:
                    arguments[key] = req_opts[key]
            if req_var["kind"] == "reference":
                wavs, rate = model.generate_voice_clone(
                    **arguments,
                    ref_audio=references[req_var["value"]],
                    ref_text=None if req_opts.get("x_vector_only_mode", False) else req_params["reference_transcript"],
                    x_vector_only_mode=req_opts.get("x_vector_only_mode", False),
                )
            elif req_var["kind"] == "design":
                instruction = "，".join(x for x in [req_var["value"], req_params["instruction"]] if x)
                wavs, rate = model.generate_voice_design(**arguments, instruct=instruction)
            else:
                wavs, rate = model.generate_custom_voice(
                    **arguments, speaker=req_var["value"], instruct=req_params["instruction"]
                )
            sf.write(output, wavs[0], rate)

        return run_qwen3

    raise ValueError("unsupported local provider")


def execute(payload: dict) -> None:
    runner = _build_runner(payload)
    output = payload["output_path"]
    runner(payload["request"], payload.get("references", {}), output)
    Path(payload["response_path"]).write_text(
        json.dumps({"output_path": output}), encoding="utf-8"
    )


def serve_session(session_path: Path) -> None:
    session = json.loads(session_path.read_text(encoding="utf-8"))
    runner = _build_runner(session)
    _atomic_write_json(Path(session["ready_path"]), {"status": "ready"})

    for raw_line in sys.stdin:
        command = raw_line.strip()
        if not command or command == "STOP":
            break
        job = json.loads(Path(command).read_text(encoding="utf-8"))
        response_path = Path(job["response_path"])
        try:
            output = job["output_path"]
            runner(job["request"], job.get("references", {}), output)
            _atomic_write_json(response_path, {"ok": True, "output_path": output})
        except Exception as exc:
            _atomic_write_json(response_path, {"ok": False, "error": type(exc).__name__})


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--session":
        serve_session(Path(sys.argv[2]))
    else:
        execute(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
