"""Backend logging configured for both console and persistent diagnostics."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_MANAGED_HANDLER = "_asmr_helper_managed_handler"


def configure_backend_logging(
    log_dir: str | Path,
    *,
    level: str = "INFO",
) -> Path:
    """Configure root logging once and return the active backend log path."""
    resolved_dir = Path(log_dir).resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    log_path = resolved_dir / "backend.log"
    resolved_level = getattr(logging, str(level).upper(), logging.INFO)

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _MANAGED_HANDLER, False):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    setattr(console_handler, _MANAGED_HANDLER, True)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MANAGED_HANDLER, True)

    root.setLevel(resolved_level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)
    logging.captureWarnings(True)
    return log_path
