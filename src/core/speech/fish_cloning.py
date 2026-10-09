"""Fish persistent private voice models, separate from per-request TTS references."""
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx

from .providers import ProviderError


def model_endpoint(connection):
    parsed = urlsplit(str(connection.get("base_url", "")))
    if (connection.get("provider_id") != "fish_audio" or parsed.scheme != "https"
            or parsed.hostname != "api.fish.audio" or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") not in {"", "/v1", "/tts", "/v1/tts"}):
        raise ValueError("远程克隆目前仅支持 Fish 官方 HTTPS 地址，请在连接设置中配置")
    return "https://api.fish.audio/model"


def _request(connection, method, *, voice_id=None, **kwargs):
    url = model_endpoint(connection)
    if voice_id is not None:
        if not isinstance(voice_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", voice_id):
            raise ValueError("无效的 Fish 音色 ID")
        url += "/" + voice_id
    key = connection.get("api_key")
    if not key:
        raise ValueError("请先在现有服务连接入口配置 Fish 凭据")
    creating = method == "POST"
    try:
        with httpx.Client(timeout=httpx.Timeout(float(connection.get("timeout", 120)), connect=15),
                          follow_redirects=False) as client:
            response = client.request(method, url, headers={"Authorization": f"Bearer {key}"}, **kwargs)
    except httpx.RequestError:
        raise ProviderError("fish_clone_network", "Fish 请求中断；创建结果可能未知，请先到 Fish 核查，勿重复上传",
                            result_unknown=creating) from None
    if response.status_code not in ({200, 201} if creating else {200}):
        messages = {401: "Fish 认证失败，请检查安全连接配置", 403: "Fish 账户无此权限",
                    402: "Fish 要求付费或余额不足；不会切换模型或充值",
                    404: "Fish 音色或接口不存在", 422: "Fish 拒绝了素材或参数",
                    429: "Fish 请求限流，请稍后检查"}
        raise ProviderError("fish_clone_http", messages.get(response.status_code,
                            f"Fish 请求失败（HTTP {response.status_code}），请核查远程结果"),
                            result_unknown=creating and (response.status_code >= 500 or response.is_redirect))
    try:
        data = response.json()
    except ValueError:
        data = None
    if (not isinstance(data, dict) or not isinstance(data.get("_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", data["_id"])
            or data.get("state") not in {"created", "training", "trained", "failed"}
            or voice_id is not None and data["_id"] != voice_id):
        raise ProviderError("fish_clone_response", "Fish 返回格式不兼容，请到 Fish 核查音色；不要重复上传",
                            result_unknown=creating)
    # Whitelist fields: never persist upstream bodies, samples, URLs or credentials.
    return {"remote_voice_id": data["_id"], "state": data["state"]}


def create_voice(connection, *, title, path, transcript):
    # Explicit transcripts avoid implicit ASR; no enhancement or generated sample.
    with Path(path).open("rb") as audio:
        return _request(connection, "POST", data={"type": "tts", "title": title,
                        "train_mode": "fast", "visibility": "private", "texts": transcript,
                        "enhance_audio_quality": "false", "generate_sample": "false"},
                        files=[("voices", ("reference.wav", audio, "audio/wav"))])


def get_voice(connection, voice_id):
    return _request(connection, "GET", voice_id=voice_id)
