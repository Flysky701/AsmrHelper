"""Verify the minimum environment needed to start the ASMR Helper API."""

from __future__ import annotations

import importlib
import sys


REQUIRED_MODULES = ("fastapi", "uvicorn", "httpx", "yaml")
OPTIONAL_MODULES = (
    "torch",
    "demucs",
    "faster_whisper",
    "imageio_ffmpeg",
    "edge_tts",
    "soundfile",
)


def check_module(name: str) -> bool:
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        print(f"  [FAIL] {name}: {exc}")
        return False
    version = getattr(module, "__version__", "OK")
    print(f"  [OK] {name}: {version}")
    return True


def main() -> int:
    print("=" * 65)
    print("ASMR Helper startup environment")
    print("=" * 65)
    print(f"  Python: {sys.version}")

    if not (sys.version_info.major == 3 and sys.version_info.minor in (11, 12)):
        print("  [FAIL] Python 3.11 or 3.12 is required")
        return 1

    required_ok = all(check_module(name) for name in REQUIRED_MODULES)
    if required_ok:
        try:
            from src.api.http.app import create_app

            app = create_app()
            print(f"  [OK] API application: {len(app.routes)} routes registered")
        except Exception as exc:
            print(f"  [FAIL] API application: {exc}")
            required_ok = False

    print("  Optional engine modules:")
    for name in OPTIONAL_MODULES:
        check_module(name)

    print("=" * 65)
    print("Startup environment is ready." if required_ok else "Startup environment is incomplete.")
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
