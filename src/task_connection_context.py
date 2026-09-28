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


def resolve_task_settings(settings: dict, execution_profile: dict | None) -> dict:
    """Project a task's explicit LLM reference without changing global selection."""
    from src.provider_profiles import profiles_for
    from urllib.parse import urlsplit
    import os

    result = deepcopy(settings)
    stage = (execution_profile or {}).get("stages", {}).get("translate", {})
    options = stage.get("options", {})
    reference = options.get("connection_ref")
    if not stage.get("enabled", True) or "connection_ref" not in options:
        return result
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("请选择本次翻译使用的 LLM 连接")
    profiles = profiles_for(result)
    selected = next((p for p in profiles["llm"] if p["id"] == reference), None)
    if selected is None:
        raise ValueError("本次翻译选择的 LLM 连接已不存在，请重新选择")
    provider = selected["provider"]
    if stage.get("provider") != provider:
        raise ValueError("本次翻译连接与所选提供方不一致")
    key = selected.get("api_key", "")
    if reference == f"legacy-{provider}":
        key = os.environ.get(f"{provider.upper()}_API_KEY") or key
    if not isinstance(key, str) or not key.strip():
        raise ValueError("本次翻译连接缺少 API Key")
    url = urlsplit(selected.get("base_url", ""))
    if url.scheme not in {"http", "https"} or not url.hostname or any((url.username, url.password, url.query, url.fragment)):
        raise ValueError("本次翻译连接的 API 地址无效")
    model = stage.get("model")
    if model in (None, "", "default"):
        model = selected.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("请为本次翻译选择模型")
    profiles["active_llm"] = reference
    result["connection_profiles"] = profiles
    api = result.setdefault("api", {})
    api["provider"] = provider
    for field in ("base_url", "model"):
        api[f"{provider}_{field}"] = selected.get(field, "")
    api[f"{provider}_api_key"] = key
    return result


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
