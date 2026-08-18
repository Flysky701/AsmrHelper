from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path
from typing import Any


def _execute(request: dict[str, Any]) -> dict[str, Any]:
    operation = str(request.get("operation") or "")
    payload = dict(request.get("payload") or {})
    if operation == "tts.synthesize_text":
        from src.core.engines.tts.service import TtsEngineRuntime

        runtime = TtsEngineRuntime(enable_runtime_routing=False)
        output_path = runtime.synthesize_text(**payload)
        return {"output_path": str(output_path)}
    elif operation == "tts.synthesize_segments":
        from src.core.engines.tts.service import TtsEngineRuntime

        runtime = TtsEngineRuntime(enable_runtime_routing=False)
        output_path, _engine = runtime.synthesize_segments(**payload)
        return {"output_path": str(output_path)}
    elif operation == "asr.transcribe_file":
        from src.core.engines.asr.service import AsrEngineRuntime

        runtime = AsrEngineRuntime(enable_runtime_routing=False)
        document = runtime.transcribe_file(**payload)
        return {
            "document": {
                "segments": [
                    {
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text,
                        "language": segment.language,
                        "confidence": segment.confidence,
                    }
                    for segment in document.segments
                ],
                "language": document.language,
                "format": document.format,
                "source_path": document.source_path,
                "warnings": list(document.warnings),
            }
        }
    elif operation == "voice.design":
        from src.core.tts.voice_designer import VoiceDesigner

        designer = VoiceDesigner(output_dir=payload.get("output_dir"))
        profile = designer.design_and_generate(
            description=str(payload.get("description") or ""),
            name=str(payload.get("name") or ""),
            ref_text=str(payload.get("ref_text") or "你好，今天辛苦了，让我来帮助你放松一下吧。"),
        )
        return _serialize_voice_profile(profile)
    elif operation == "voice.clone":
        from src.core.tts.voice_designer import VoiceDesigner

        designer = VoiceDesigner(output_dir=payload.get("output_dir"))
        profile = designer.clone_from_audio(
            audio_path=str(payload.get("audio_path") or ""),
            name=str(payload.get("name") or ""),
            ref_text=str(payload.get("ref_text") or ""),
            x_vector_only_mode=bool(payload.get("x_vector_only_mode", False)),
        )
        return _serialize_voice_profile(profile)
    elif operation == "voice.preview":
        from src.core.tts.voice_designer import get_voice_designer
        from src.core.tts.voice_profile import get_voice_manager

        profile = get_voice_manager().get_by_id(str(payload.get("profile_id") or ""))
        if profile is None:
            raise ValueError(f"voice profile not found: {payload.get('profile_id')}")
        output_path = get_voice_designer().preview_profile(
            profile=profile,
            text=str(payload.get("text") or ""),
            output_path=str(payload.get("output_path")) if payload.get("output_path") else None,
            speed=float(payload.get("speed", 1.0)),
            language=str(payload.get("language") or "auto"),
        )
        return {"output_path": str(output_path)}
    raise ValueError(f"unsupported runtime worker operation: {operation}")


def _serialize_voice_profile(profile: Any) -> dict[str, Any]:
    return {
        "profile_id": profile.id,
        "name": profile.name,
        "category": profile.category,
        "engine": profile.engine,
        "description": profile.description,
        "design_instruct": profile.design_instruct,
        "ref_audio_path": profile.get_ref_audio_path(),
        "prompt_cache_path": profile.get_prompt_cache_path(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args()

    response_path = Path(args.response)
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        response = {"success": True, "result": _execute(request)}
        exit_code = 0
    except Exception as exc:
        response = {
            "success": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }
        exit_code = 1
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
