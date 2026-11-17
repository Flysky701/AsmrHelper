"""Small shared transport for explicit cloud speech contracts; never retries POSTs."""
from __future__ import annotations

import base64
from io import BytesIO
from urllib.parse import urlsplit

import httpx
import numpy as np
import soundfile as sf

from .providers import ProviderError


def join_endpoint(base, endpoint):
    base = str(base).rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ProviderError("connection_missing", "外部连接地址无效，请检查 API 基础地址")
    if parsed.path.endswith(endpoint):
        return base
    # Accept either an origin or a versioned API base without duplicating /v1.
    # Only collapse matching boundary segments; keep custom proxy prefixes.
    base_parts = parsed.path.strip("/").split("/") if parsed.path.strip("/") else []
    endpoint_parts = endpoint.strip("/").split("/")
    for overlap in range(min(len(base_parts), len(endpoint_parts)), 0, -1):
        if base_parts[-overlap:] == endpoint_parts[:overlap]:
            return base + "/" + "/".join(endpoint_parts[overlap:])
    return base + endpoint


def decode_base64(value):
    if not isinstance(value, str) or not value:
        raise ProviderError("invalid_audio", "远端未返回有效音频数据")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise ProviderError("invalid_audio", "远端音频编码无效") from None


def post_audio(url, headers, body, output_path, connection, *, decoder=None):
    """Decode only a successful response; redact upstream errors and credentials.

    A decoder returns (bytes, 'audio' | 'pcm_s16le', sample_rate | None).
    Cancellation is checked by the common runner before/after this bounded POST;
    it cannot undo remote generation or charges already accepted by a provider.
    """
    parsed = urlsplit(url)
    # A provider may append its documented query parameters (e.g. output_format).
    # User-supplied base URLs still reject queries in join_endpoint.
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment):
        raise ProviderError("connection_missing", "外部连接地址无效，请检查 API 基础地址")
    try:
        with httpx.Client(timeout=httpx.Timeout(float(connection.get("timeout", 120)), connect=15),
                          follow_redirects=False) as client:
            response = client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        raise ProviderError("result_unknown", "远端响应超时，请确认计费与结果后再生成", result_unknown=True) from None
    except httpx.RequestError:
        raise ProviderError("connection_failed", "外部语音服务连接失败", result_unknown=True) from None
    if response.status_code in {401, 403}:
        raise ProviderError("authentication_failed", "外部语音服务认证失败")
    if response.status_code == 402:
        raise ProviderError("payment_required", "外部语音服务余额不足或需要付费，请检查账户计费状态后再试")
    if response.status_code == 429:
        raise ProviderError("rate_limited", "外部语音服务请求限流")
    if response.status_code == 404:
        raise ProviderError("model_unavailable", "服务端点、模型或音色不可用")
    if response.status_code in {400, 422}:
        raise ProviderError("request_rejected", "服务拒绝语音请求，请检查模型、音色与参数")
    if not response.is_success:
        raise ProviderError("remote_failed", f"外部语音服务失败（HTTP {response.status_code}）",
                            result_unknown=response.status_code >= 500)
    try:
        content, encoding, rate = decoder(response) if decoder else (response.content, "audio", None)
        if not isinstance(content, bytes) or not content:
            raise ValueError("empty audio")
        if encoding == "pcm_s16le":
            if type(rate) is not int or not 8000 <= rate <= 192000 or len(content) % 2:
                raise ValueError("invalid PCM format")
            audio = np.frombuffer(content, dtype="<i2").astype(np.float32) / 32768.0
        elif encoding == "audio":
            audio, rate = sf.read(BytesIO(content), dtype="float32")
        else:
            raise ValueError("unsupported audio encoding")
        if len(audio) == 0 or not np.isfinite(audio).all():
            raise ValueError("invalid samples")
        sf.write(output_path, audio, rate, format="WAV", subtype="PCM_16")
    except ProviderError:
        raise
    except Exception:
        raise ProviderError("invalid_audio", "远端没有返回可解码音频") from None
    return response.headers.get("x-request-id") or response.headers.get("request-id")
