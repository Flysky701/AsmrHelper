from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path
from typing import Any


def _execute(request: dict[str, Any]) -> dict[str, Any]:
    from src.core.engines.tts.service import TtsEngineRuntime

    operation = str(request.get("operation") or "")
    payload = dict(request.get("payload") or {})
    runtime = TtsEngineRuntime(enable_runtime_routing=False)
    if operation == "tts.synthesize_text":
        output_path = runtime.synthesize_text(**payload)
    elif operation == "tts.synthesize_segments":
        output_path, _engine = runtime.synthesize_segments(**payload)
    else:
        raise ValueError(f"unsupported runtime worker operation: {operation}")
    return {"output_path": str(output_path)}


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
