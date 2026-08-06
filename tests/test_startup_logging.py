"""Startup diagnostics must remain available when the GUI launcher closes."""

from __future__ import annotations

import logging
import os

from src.api.http.__main__ import _remove_pid_file, _write_pid_file
from src.api.http.logging_config import configure_backend_logging


def test_backend_logging_writes_utf8_and_replaces_managed_handlers(tmp_path):
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    message = "backend startup 可诊断"

    try:
        log_path = configure_backend_logging(tmp_path, level="INFO")
        configure_backend_logging(tmp_path, level="INFO")
        logging.getLogger("asmr-helper-test").info(message)
        managed = [
            handler
            for handler in root.handlers
            if getattr(handler, "_asmr_helper_managed_handler", False)
        ]
        for handler in managed:
            handler.flush()

        assert len(managed) == 2
        assert message in log_path.read_text(encoding="utf-8")
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_asmr_helper_managed_handler", False):
                root.removeHandler(handler)
                handler.close()
        root.setLevel(original_level)
        for handler in original_handlers:
            if handler not in root.handlers:
                root.addHandler(handler)


def test_backend_pid_file_uses_actual_process_and_is_removed(tmp_path):
    pid_path = tmp_path / "backend.pid"

    written = _write_pid_file(str(pid_path))

    assert written == pid_path.resolve()
    assert pid_path.read_text(encoding="ascii") == str(os.getpid())

    _remove_pid_file(written)
    assert not pid_path.exists()
