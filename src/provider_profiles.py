"""Named connections, with legacy migration and write-only credentials."""
from copy import deepcopy
import os
from uuid import uuid4
from urllib.parse import urlsplit


def profiles_for(settings):
    from src.core.engines.llm.registry import LLM_DEFAULT_MODELS

    if isinstance(settings.get("connection_profiles"), dict):
        return deepcopy(settings["connection_profiles"])
    api = settings.get("api", {})
    llm = []
    for provider in ("deepseek", "openai"):
        llm.append({"id": f"legacy-{provider}", "name": "DeepSeek" if provider == "deepseek" else "OpenAI 兼容",
                    "provider": provider, "base_url": api.get(f"{provider}_base_url", ""),
                    "model": api.get(f"{provider}_model") or LLM_DEFAULT_MODELS[provider], "api_key": api.get(f"{provider}_api_key", "")})
    tts = deepcopy(settings.get("external_tts", {}))
    tts.update(id="legacy-tts", name="外部语音", provider="openai_compatible")
    return {"llm": llm, "tts": [tts], "active_llm": f"legacy-{api.get('provider', 'deepseek')}", "active_tts": "legacy-tts"}


def project_profiles(settings, include_env=True):
    """Project selected named connections to the existing runtime contract."""
    if "connection_profiles" not in settings:
        return settings
    profiles = settings["connection_profiles"]
    for kind in ("llm", "tts"):
        selected = next((p for p in profiles[kind] if p["id"] == profiles[f"active_{kind}"]), None)
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
        else:
            settings["external_tts"] = {k: deepcopy(v) for k, v in selected.items() if k not in ("id", "name", "provider")}
    return settings


def public_profiles(settings):
    profiles = profiles_for(settings)
    for kind in ("llm", "tts"):
        allowed = ("id", "name", "provider", "base_url", "model") if kind == "llm" else (
            "id", "name", "provider", "base_url", "model", "voice", "api_format", "instructions"
        )
        result = []
        for profile in profiles[kind]:
            item = {key: profile.get(key, "") for key in allowed}
            if kind == "tts":
                item["api_format"] = profile.get("api_format") or "speech"
            secret = profile.get("api_key")
            if kind == "llm" and profile["id"] == f"legacy-{profile['provider']}":
                secret = os.environ.get(f"{profile['provider'].upper()}_API_KEY") or secret
            item["credential_configured"] = bool(secret)
            result.append(item)
        profiles[kind] = result
    return profiles


def update_profiles(base, request, legacy_updates):
    profiles = profiles_for(base)
    # Legacy clients edit the selected profile for the corresponding provider.
    api = legacy_updates.get("api", {})
    for provider in ("deepseek", "openai"):
        matching = [p for p in profiles["llm"] if p["provider"] == provider]
        selected = next((p for p in matching if p["id"] == profiles["active_llm"]), None)
        selected = selected or next((p for p in matching if p["id"] == f"legacy-{provider}"), None)
        if selected:
            for field in ("base_url", "model", "api_key"):
                if f"{provider}_{field}" in api:
                    selected[field] = api[f"{provider}_{field}"]
            if api.get("provider") == provider:
                profiles["active_llm"] = selected["id"]
    if "external_tts" in legacy_updates:
        next(p for p in profiles["tts"] if p["id"] == profiles["active_tts"]).update(legacy_updates["external_tts"])
    selection = request.get("active_connections", {})
    if not isinstance(selection, dict):
        raise ValueError("active_connections 必须是对象")
    for kind in ("llm", "tts"):
        if kind in selection:
            if not any(p["id"] == selection[kind] for p in profiles[kind]):
                raise ValueError("所选连接配置不存在")
            profiles[f"active_{kind}"] = selection[kind]
    if "connection_profile" in request:
        draft = request["connection_profile"]
        if not isinstance(draft, dict) or draft.get("kind") not in ("llm", "tts"):
            raise ValueError("连接类型必须是 llm 或 tts")
        kind = draft["kind"]
        existing = next((p for p in profiles[kind] if p["id"] == draft.get("id")), None)
        if draft.get("id") and existing is None:
            raise ValueError("连接配置不存在")
        name = draft.get("name", existing.get("name") if existing else "")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError("配置名称须为 1–80 个字符")
        if any(p["name"].casefold() == name.strip().casefold() and p is not existing for p in profiles[kind]):
            raise ValueError("配置名称已存在")
        provider = draft.get("provider", existing.get("provider") if existing else ("deepseek" if kind == "llm" else "openai_compatible"))
        if provider not in (("deepseek", "openai") if kind == "llm" else ("openai_compatible",)):
            raise ValueError("不支持的服务提供商")
        if existing and provider != existing["provider"]:
            raise ValueError("更换提供商请新建配置")
        previous = deepcopy(existing) if existing else {}
        profile = existing if existing is not None else {"id": uuid4().hex, "api_key": ""}
        profile.update(name=name.strip(), provider=provider)
        for field in (("base_url", "model") if kind == "llm" else (
            "base_url", "model", "voice", "api_format", "instructions"
        )):
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
        if kind == "tts":
            api_format = profile.get("api_format") or "speech"
            if api_format not in ("speech", "mimo_chat", "fish"):
                raise ValueError("不支持的 TTS 接口格式")
            profile["api_format"] = api_format
            if api_format == "fish":
                if not all(profile.get(key) for key in ("base_url", "model", "voice")):
                    raise ValueError("Fish Audio 配置需要 API 地址、模型和音色 ID")
                if profile.get("instructions"):
                    raise ValueError("Fish Audio 不支持独立语音指令字段，请在合成文本中使用官方支持的标签")
            before_url = urlsplit(previous.get("base_url", ""))
            after_url = urlsplit(profile.get("base_url", ""))
            changed_service = (
                (before_url.scheme, before_url.netloc) != (after_url.scheme, after_url.netloc)
                or (previous.get("api_format") or "speech") != api_format
            )
            if previous.get("api_key") and changed_service and (
                not credential or not credential.strip() or credential == "***configured***"
            ):
                raise ValueError("更换 TTS 服务地址或协议后，请重新填写对应服务的 API Key")
        if credential and credential.strip() and credential != "***configured***":
            profile["api_key"] = credential.strip()
        if existing is None:
            profiles[kind].append(profile)
        profiles[f"active_{kind}"] = profile["id"]
    return profiles
