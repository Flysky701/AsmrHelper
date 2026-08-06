"""Entry point for running the HTTP API server.

Usage:
    python -m src.api.http [--host HOST] [--port PORT] [--reload]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def _write_pid_file(pid_file: str | None) -> Path | None:
    if not pid_file:
        return None
    path = Path(pid_file).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="ascii")
    return path


def _remove_pid_file(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="ASMR Helper HTTP API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument(
        "--log-dir",
        default=str(project_root / "logs"),
        help="Persistent backend log directory",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("ASMR_HELPER_LOG_LEVEL", "INFO"),
        help="Backend logging level",
    )
    parser.add_argument(
        "--pid-file",
        default=None,
        help="Write the actual backend process ID to this file",
    )
    args = parser.parse_args()

    from .logging_config import configure_backend_logging

    log_path = configure_backend_logging(args.log_dir, level=args.log_level)
    logging.getLogger(__name__).info(
        "starting ASMR Helper backend host=%s port=%s log=%s",
        args.host,
        args.port,
        log_path,
    )

    import uvicorn

    pid_file = _write_pid_file(args.pid_file)
    try:
        uvicorn.run(
            "src.api.http.app:create_app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            factory=True,
            log_config=None,
        )
    finally:
        _remove_pid_file(pid_file)


if __name__ == "__main__":
    main()
