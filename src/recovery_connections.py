"""Secret-free connection references for explicitly resumed pipeline attempts.

Records are JSON serializable. Credentials stay in configuration/environment;
salted digests detect changes without copying them into task persistence.
"""
from copy import deepcopy
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import urlsplit

from src.provider_profiles import profiles_for


def _digest(value, salt):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256((salt + "\0" + data).encode("utf-8")).hexdigest()


def _effective_profile(profile, kind):
    result = {k: deepcopy(v) for k, v in profile.items() if k not in ("id", "name")}
    provider = result.get("provider", "")
    if kind == "llm" and profile["id"] == f"legacy-{provider}":
        result["api_key"] = os.environ.get(f"{provider.upper()}_API_KEY") or result.get("api_key", "")
    return result


def _safe_field(key, value):
    # Unknown structures are opaque: nested headers, auth, options, etc. may
    # contain credentials under arbitrary names.
    if key in ("provider", "model", "deepseek_model", "openai_model", "voice", "speed", "response_format", "enabled"):
        return isinstance(value, (str, int, float, bool)) or value is None
    if key in ("base_url", "deepseek_base_url", "openai_base_url") and isinstance(value, str):
        try:
            url = urlsplit(value)
            return not (url.username or url.password or url.query or url.fragment)
        except ValueError:
            return False
    return False


def _project(settings, references):
    result = {key: deepcopy(settings.get(key, {})) for key in ("api", "external_tts")}
    for reference in references:
        kind, profile = reference["kind"], reference["profile"]
        if kind == "tts":
            result["external_tts"] = {k: deepcopy(v) for k, v in profile.items() if k != "provider"}
        else:
            provider = profile["provider"]
            for field in ("base_url", "model", "api_key"):
                result["api"][f"{provider}_{field}"] = deepcopy(profile.get(field, ""))
            if reference.get("selected"):
                result["api"]["provider"] = provider
    return result


def capture_recovery_connections(settings: dict, snapshot: dict, *, include_tts: bool = False) -> dict:
    """Capture references; never write credentials or arbitrary nested values.

    ``settings`` must include connection_profiles when named profiles are used;
    ``snapshot`` is the private api/external_tts snapshot captured for the task.
    Call at task creation, before users can change connection definitions.
    """
    profiles = profiles_for(settings, include_legacy_tts=include_tts)
    salt = secrets.token_hex(32)
    references = []
    kinds = ("llm", "tts") if include_tts else ("llm",)
    selected = {kind: profiles[f"active_{kind}"] for kind in kinds}
    for kind in kinds:
        profile = next((p for p in profiles[kind] if p["id"] == selected[kind]), None)
        if profile is None:
            raise ValueError("无法保存恢复配置：所选连接配置不存在")
        references.append({"kind": kind, "id": profile["id"], "selected": True,
                           "fingerprint": _digest(_effective_profile(profile, kind), salt)})
    # Preserve inactive provider fields too: the runtime snapshot contains the
    # complete API section, and changing active selection may project over it.
    active_provider = next(p for p in profiles["llm"] if p["id"] == selected["llm"])["provider"]
    for provider in ("deepseek", "openai"):
        if provider == active_provider:
            continue
        for profile in profiles["llm"]:
            effective = _effective_profile(profile, "llm")
            if effective.get("provider") == provider and all(
                snapshot.get("api", {}).get(f"{provider}_{field}", "") == effective.get(field, "")
                for field in ("base_url", "api_key")
            ):
                references.append({"kind": "llm", "id": profile["id"], "selected": False,
                                   "fingerprint": _digest(effective, salt)})
                break
    template = {}
    for section in (("api", "external_tts") if include_tts else ("api",)):
        template[section] = {
            key: ({"value": deepcopy(value)} if _safe_field(key, value) else {"digest": _digest(value, salt)})
            for key, value in snapshot.get(section, {}).items()
        }
    record = {"schema_version": 1 if include_tts else 2, "salt": salt, "selected": selected,
              "references": references, "template": template}
    # Reject mismatched capture inputs immediately, rather than persisting an
    # attempt that can never be resumed with its original settings.
    restore_recovery_connections(record, settings)
    return record


def restore_recovery_connections(record: dict, settings: dict) -> dict:
    """Resolve original IDs and verify every pinned value before execution.

    Active selection and display names may change. Missing/edited definitions
    or credentials fail closed; callers should offer starting a new task.
    Errors intentionally exclude actual values and secrets.
    """
    try:
        if record["schema_version"] not in (1, 2):
            raise ValueError("unsupported schema")
        salt = record["salt"]
        if not isinstance(salt, str) or len(salt) != 64:
            raise ValueError("invalid salt")
        expected_sections = {"api", "external_tts"} if record["schema_version"] == 1 else {"api"}
        if set(record["template"]) != expected_sections:
            raise ValueError("invalid template")
        if set(record["selected"]) not in ({"llm", "tts"}, {"llm"}):
            raise ValueError("invalid selected kinds")
        for kind in record["selected"]:
            selected_refs = [ref for ref in record["references"] if ref["kind"] == kind and ref.get("selected")]
            if len(selected_refs) != 1 or selected_refs[0]["id"] != record["selected"][kind]:
                raise ValueError("invalid selected reference")
        profiles = profiles_for(settings, include_legacy_tts="tts" in record["selected"])
        resolved = []
        for ref in record["references"]:
            profile = next((p for p in profiles[ref["kind"]] if p["id"] == ref["id"]), None)
            if profile is None:
                raise ValueError("missing connection")
            effective = _effective_profile(profile, ref["kind"])
            if not hmac.compare_digest(_digest(effective, salt), ref["fingerprint"]):
                raise ValueError("changed connection")
            resolved.append({**ref, "profile": effective})
        candidate = _project(settings, resolved)
        result = {}
        for section, fields in record["template"].items():
            result[section] = {}
            for key, expected in fields.items():
                if key not in candidate[section]:
                    raise ValueError("missing field")
                value = candidate[section][key]
                if "value" in expected:
                    matches = _digest(value, salt) == _digest(expected["value"], salt)
                else:
                    matches = hmac.compare_digest(_digest(value, salt), expected["digest"])
                if not matches:
                    raise ValueError("changed field")
                result[section][key] = deepcopy(value)
        return result
    except (AttributeError, KeyError, TypeError, ValueError, StopIteration) as exc:
        raise ValueError("无法继续任务：原连接配置或凭据已删除、改变或恢复记录无效，请使用当前配置新建任务") from exc
