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
    raise ValueError(f"unsupported runtime worker operation: {operation}")


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
