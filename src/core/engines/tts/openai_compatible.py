"""Remote speech endpoints, including MiMo's chat audio response format."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import httpx
import soundfile as sf


class OpenAICompatibleTtsEngine:
    def __init__(
        self,
        *,
        base_url=None,
        api_key=None,
        model=None,
        voice=None,
        api_format="speech",
        speed=1.0,
        instructions="",
    ):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        self.voice = str(voice or "").strip()
        self.api_format = api_format or "speech"
        self.speed = float(speed)
        self.instructions = str(instructions or "").strip()

    def synthesize(self, text: str, output_path: str) -> str:
        if not all((self.base_url, self.api_key, self.model, self.voice)):
            raise ValueError("请在设置中填写外部 TTS 的地址、API Key、模型和音色")
        if not text.strip():
            raise ValueError("合成文本不能为空")
        if self.api_format not in ("speech", "mimo_chat"):
            raise ValueError("不支持的 TTS 接口格式")
        if not 0.25 <= self.speed <= 4.0:
            raise ValueError("语速必须在 0.25–4.0 之间")
        if self.api_format == "mimo_chat" and self.speed != 1.0:
            raise ValueError("MiMo 接口不支持数值语速；请使用语音指令设置语速")
        if self.api_format == "speech":
            endpoint = "/audio/speech"
            payload = {
                "model": self.model,
                "input": text,
                "voice": self.voice,
                "response_format": "wav",
            }
            if self.speed != 1.0:
                payload["speed"] = self.speed
            if self.instructions:
                payload["instructions"] = self.instructions
        else:
            endpoint = "/chat/completions"
            messages = []
            if self.instructions:
                messages.append({"role": "user", "content": self.instructions})
            messages.append({"role": "assistant", "content": text})
            payload = {
                "model": self.model,
                "messages": messages,
                "audio": {"format": "wav", "voice": self.voice},
            }
        try:
            with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
                response = client.post(
                    self.base_url + endpoint,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if not response.is_success:
                    # Remote bodies may echo credentials or submitted text.
                    raise RuntimeError(
                        f"外部 TTS 请求失败（HTTP {response.status_code}），请检查地址、凭据和模型"
                    )
                if self.api_format == "speech":
                    content = response.content
                else:
                    content = base64.b64decode(
                        response.json()["choices"][0]["message"]["audio"]["data"],
                        validate=True,
                    )
            audio, sample_rate = sf.read(BytesIO(content), dtype="float32")
            if len(audio) == 0:
                raise ValueError("empty audio")
        except httpx.TimeoutException:
            raise RuntimeError("外部 TTS 请求超时") from None
        except httpx.RequestError:
            raise RuntimeError("无法连接外部 TTS 服务，请检查 API 地址和网络") from None
        except (ValueError, KeyError, IndexError, TypeError, sf.LibsndfileError):
            raise RuntimeError("外部 TTS 未返回有效音频，请检查接口格式") from None
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(target), audio, sample_rate)
        return str(target)
