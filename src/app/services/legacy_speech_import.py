"""One-way, additive import of legacy connection data. Never a runtime fallback.

Original configuration remains the rollback source. Unsupported synthesis
fields stay there; importing a connection does not invent a generation rule.
"""
from copy import deepcopy
from hashlib import sha256
from urllib.parse import urlsplit


PROTOCOLS = {"speech": "openai_compatible", "fish": "fish_audio", "mimo_chat": "mimo_audio"}


def _sources(settings):
    result = []
    profiles = settings.get("connection_profiles", {})
    for index, item in enumerate(profiles.get("tts", [])):
        if isinstance(item, dict):
            result.append(("profile:" + str(item.get("id") or index), item))
    external = settings.get("external_tts")
    if isinstance(external, dict) and any(external.values()):
        result.append(("external_tts", external))
    return result


def inspect_legacy(settings, service):
    imports = {item.get("source"): item for item in service.store.list("imports")
               if item.get("kind") == "legacy_tts_connection"}
    result = []
    for source, raw in _sources(settings):
        provider = PROTOCOLS.get(raw.get("api_format") or "speech")
        url = raw.get("base_url", "")
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and not any(
                (parsed.username, parsed.password, parsed.query, parsed.fragment))
        except (ValueError, TypeError):
            valid = False
        reason = None if provider and valid else "协议或地址无法可靠转换，原配置保留"
        old = imports.get(source)
        result.append({"source": source, "provider_id": provider,
                       "name": str(raw.get("name") or "旧外部语音"),
                       "status": "imported" if old else "retained" if reason else "ready",
                       "connection_id": old.get("connection_id") if old else None,
                       "credential_configured": bool(raw.get("api_key")),
                       "reason": reason,
                       "retained_fields": sorted(k for k in raw if k not in {
                           "id", "name", "provider", "api_format", "base_url", "api_key"})})
    return {"entries": result, "legacy_local_settings_retained": bool(settings.get("tts")),
            "note": "仅导入服务连接；模型、音色、指令及本地旧设置保留在原配置，不自动创建规则或设置默认服务"}


def import_legacy(settings, service):
    # Serialize same-process import requests; each store write also takes its
    # file lock. An interrupted import is reported, never overwritten on retry.
    with service.store._thread_lock:
        sources = dict(_sources(settings))
        report = inspect_legacy(settings, service)
        for item in report["entries"]:
            if item["status"] != "ready":
                continue
            source = item["source"]
            raw = sources[source]
            marker = sha256(source.encode()).hexdigest()[:16]
            name = f"旧配置导入 · {item['name']} · {marker}"
            existing = [c for c in service.store.list("connections") if c.get("name") == name]
            if existing:
                # Never replace an existing named service, including edits to an
                # earlier partial import. Record it for manual reconciliation.
                item.update(status="retained", reason="同名连接已存在，保留原数据并跳过，避免覆盖")
                continue
            body = {"name": name, "provider_id": item["provider_id"], "deployment": "cloud",
                    "base_url": raw["base_url"]}
            if raw.get("api_key"):
                body["api_key"] = raw["api_key"]
            try:
                connection = service.save_connection(body)
                service.store.create("imports", {"kind": "legacy_tts_connection", "source": source,
                    "connection_id": connection["id"], "retained_fields": item["retained_fields"]})
            except (ValueError, TypeError):
                item.update(status="retained", reason="连接未通过当前校验，原配置保留")
                continue
            item.update(status="imported", connection_id=connection["id"])
        return deepcopy(report)
