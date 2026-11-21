"""Read-only, cursor-paginated voice catalogs for native Gemini and ElevenLabs APIs."""
import httpx

from .cloud_http import join_endpoint
from .providers import ProviderError


def list_account_voices(connection, *, title, page_size, page_token):
    provider = connection["provider_id"]
    key = connection.get("api_key")
    if not key:
        raise ProviderError("connection_missing", "请先配置服务商密钥")
    base = str(connection.get("base_url") or "").rstrip("/")
    params = {"page_size": page_size}
    if title.strip():
        params["search"] = title.strip()
    if provider == "gemini":
        url = join_endpoint(base.removesuffix("/interactions"), "/voices")
        headers = {"x-goog-api-key": key}
        cursor_field, id_field, name_field = "page_token", "id", "display_name"
    elif provider == "elevenlabs":
        url = join_endpoint(base.removesuffix("/v1"), "/v2/voices")
        headers = {"xi-api-key": key}
        cursor_field, id_field, name_field = "next_page_token", "voice_id", "name"
    else:
        raise ProviderError("voice_catalog_unsupported", "此服务未提供音色目录")
    if page_token:
        params[cursor_field] = page_token
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ProviderError("voice_catalog_failed", f"读取音色失败（HTTP {exc.response.status_code}）") from None
    except httpx.RequestError:
        raise ProviderError("voice_catalog_network", "无法连接音色目录") from None
    try:
        data = response.json()
        if not isinstance(data["voices"], list):
            raise ValueError
        items = []
        for voice in data["voices"]:
            voice_id = voice[id_field]
            if not isinstance(voice_id, str) or not voice_id.strip():
                raise ValueError
            items.append({"id": voice_id, "name": voice.get(name_field) or voice_id})
        token = data.get("next_page_token") or ""
        if not isinstance(token, str):
            raise ValueError
        more = bool(token) and (provider == "gemini" or data.get("has_more") is True)
    except (KeyError, TypeError, ValueError):
        raise ProviderError("voice_catalog_invalid", "服务返回的音色目录格式有误") from None
    return {"items": items, "has_more": more, "next_page_token": token if more else None, "notice": ""}
