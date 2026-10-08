"""Named connections, with legacy migration and write-only credentials."""
from copy import deepcopy
import os
from uuid import uuid4
from urllib.parse import urlsplit


def profiles_for(settings, *, include_legacy_tts=False, include_removed=False):
    from src.core.engines.llm.registry import LLM_DEFAULT_MODELS

    if isinstance(settings.get("connection_profiles"), dict):
        result = deepcopy(settings["connection_profiles"])
        if not include_removed:
            result["llm"] = [p for p in result["llm"] if not p.get("removed")]
        return result
    api = settings.get("api", {})
    llm = []
    for provider in ("deepseek", "openai"):
        llm.append({"id": f"legacy-{provider}", "name": "DeepSeek" if provider == "deepseek" else "OpenAI 兼容",
                    "provider": provider, "base_url": api.get(f"{provider}_base_url", ""),
                    "model": api.get(f"{provider}_model") or LLM_DEFAULT_MODELS[provider], "api_key": api.get(f"{provider}_api_key", "")})
    result = {"llm": llm, "active_llm": f"legacy-{api.get('provider', 'deepseek')}"}
    if include_legacy_tts:
        raw = settings.get("external_tts")
        tts = deepcopy(raw) if isinstance(raw, dict) else {}
        tts.update(id="legacy-tts", name="外部语音", provider="openai_compatible")
        result.update(tts=[tts], active_tts="legacy-tts")
    return result


def project_profiles(settings, include_env=True):
    """Project selected named connections to the existing runtime contract."""
    if "connection_profiles" not in settings:
        return settings
    profiles = settings["connection_profiles"]
    for kind in ("llm",):
        selected = next((p for p in profiles[kind] if p["id"] == profiles[f"active_{kind}"] and not p.get("removed")), None)
        if selected is None:
            raise ValueError("所选连接配置不存在")
        if kind == "llm":
            provider = selected["provider"]
            api = settings.setdefault("api", {})
            api["provider"] = provider
            for field in ("base_url", "model", "api_key"):
                api[f"{provider}_{field}"] = selected.get(field, "")
            if include_env and selected["id"] == f"legacy-{provider}" and os.environ.get(f"{provider.upper()}_API_KEY"):
                api[f"{provider}_api_key"] = os.environ[f"{provider.upper()}_API_KEY"]
    return settings


def public_profiles(settings):
    profiles = profiles_for(settings, include_removed=True)
    result = []
    for profile in profiles["llm"]:
        item = {key: profile.get(key, "") for key in ("id", "name", "provider", "base_url", "model")}
        secret = profile.get("api_key")
        if profile["id"] == f"legacy-{profile['provider']}":
            secret = os.environ.get(f"{profile['provider'].upper()}_API_KEY") or secret
        item["credential_configured"] = bool(secret)
        item["removed"] = bool(profile.get("removed"))
        result.append(item)
    return {"llm": [p for p in result if not p["removed"]],
            "removed_llm": [p for p in result if p["removed"]], "active_llm": profiles["active_llm"]}


def update_profiles(base, request, legacy_updates):
    selection = request.get("active_connections", {})
    if not isinstance(selection, dict):
        raise ValueError("active_connections 必须是对象")
    if ("external_tts" in legacy_updates
            or "tts" in selection
            or isinstance(request.get("connection_profile"), dict)
            and request["connection_profile"].get("kind") == "tts"):
        raise ValueError("旧 TTS 配置只读，请使用 Speech 命名连接")
    profiles = profiles_for(base, include_removed=True)
    # Legacy clients edit the selected profile for the corresponding provider.
    api = legacy_updates.get("api", {})
    for provider in ("deepseek", "openai"):
        matching = [p for p in profiles["llm"] if p["provider"] == provider and not p.get("removed")]
        selected = next((p for p in matching if p["id"] == profiles["active_llm"]), None)
        selected = selected or next((p for p in matching if p["id"] == f"legacy-{provider}"), None)
        if selected:
            for field in ("base_url", "model", "api_key"):
                if f"{provider}_{field}" in api:
                    selected[field] = api[f"{provider}_{field}"]
            if api.get("provider") == provider:
                profiles["active_llm"] = selected["id"]
    selection = request.get("active_connections", {})
    if not isinstance(selection, dict):
        raise ValueError("active_connections 必须是对象")
    for kind in ("llm",):
        if kind in selection:
            if not any(p["id"] == selection[kind] and not p.get("removed") for p in profiles[kind]):
                raise ValueError("所选连接配置不存在")
            profiles[f"active_{kind}"] = selection[kind]
    if "connection_profile" in request:
        draft = request["connection_profile"]
        if not isinstance(draft, dict) or draft.get("kind") != "llm":
            raise ValueError("连接类型必须是 llm；TTS 请使用 Speech")
        kind = draft["kind"]
        existing = next((p for p in profiles[kind] if p["id"] == draft.get("id")), None)
        if existing and existing.get("removed"):
            raise ValueError("此连接已移除，请先恢复")
        if draft.get("id") and existing is None:
            raise ValueError("连接配置不存在")
        name = draft.get("name", existing.get("name") if existing else "")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError("配置名称须为 1–80 个字符")
        if any(p["name"].casefold() == name.strip().casefold() and p is not existing for p in profiles[kind]):
            raise ValueError("配置名称已存在")
        provider = draft.get("provider", existing.get("provider") if existing else "deepseek")
        if provider not in ("deepseek", "openai"):
            raise ValueError("不支持的服务提供商")
        if existing and provider != existing["provider"]:
            raise ValueError("更换提供商请新建配置")
        profile = existing if existing is not None else {"id": uuid4().hex, "api_key": ""}
        profile.update(name=name.strip(), provider=provider)
        for field in ("base_url", "model"):
            if field in draft:
                if not isinstance(draft[field], str):
                    raise ValueError(f"{field} 必须是字符串")
                profile[field] = draft[field].strip()
        if profile.get("base_url"):
            try:
                url = urlsplit(profile["base_url"])
                valid = url.scheme in ("http", "https") and url.hostname and not any((url.username, url.password, url.query, url.fragment))
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("连接地址必须是有效的 HTTP(S) 基础地址")
        credential = draft.get("credential")
        if credential is not None and not isinstance(credential, str):
            raise ValueError("API Key 必须是字符串")
        if credential and credential.strip() and credential != "***configured***":
            profile["api_key"] = credential.strip()
        if existing is None:
            profiles[kind].append(profile)
        profiles[f"active_{kind}"] = profile["id"]
    return profiles
