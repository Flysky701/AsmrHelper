"""Private, process-local connection snapshots for task execution.

Only connection sections are pinned; unrelated settings remain live. Secrets
never enter task specifications or the task state store. Snapshots deliberately
last only for this process, matching the current read-only restart history.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Iterator


_connections: ContextVar[dict | None] = ContextVar("task_connections", default=None)


def capture_connections(settings: dict) -> dict:
    """Copy complete sections, including absence, to avoid fallback leakage."""
    return {key: deepcopy(settings.get(key, {})) for key in ("api", "external_tts")}


@contextmanager
def connection_context(snapshot: dict | None) -> Iterator[None]:
    token = _connections.set(deepcopy(snapshot))
    try:
        yield
    finally:
        _connections.reset(token)


def overlay_connections(settings: dict) -> dict:
    """Return an independent settings view using the executing task's connections."""
    result = deepcopy(settings)
    snapshot = _connections.get()
    if snapshot is not None:
        result.update(deepcopy(snapshot))
    return result
