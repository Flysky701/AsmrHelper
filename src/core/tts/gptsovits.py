"""
GPT-SoVITS 语音克隆引擎（HTTP API 调用）

功能：通过本地 GPT-SoVITS WebUI API 服务进行语音克隆合成
前置条件：启动 GPT-SoVITS WebUI（默认 localhost:9870）
"""

import requests
from pathlib import Path
from typing import Optional


class GPTSoVITSEngine:
    """GPT-SoVITS 语音克隆引擎（通过 HTTP API 调用本地服务）"""

    DEFAULT_API_URL = "http://localhost:9870"

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        ref_audio_path: str = "",
        ref_text: str = "",
        language: str = "zh",
    ):
        """
        初始化 GPT-SoVITS 引擎

        Args:
            api_url: GPT-SoVITS 服务地址
            ref_audio_path: 参考音频路径（克隆声线）
            ref_text: 参考音频对应的文本
            language: 合成语言（zh/ja/en）
        """
        self.api_url = api_url.rstrip("/")
        self.ref_audio_path = ref_audio_path
        self.ref_text = ref_text
        self.language = language

    def is_service_available(self) -> bool:
        """检查服务是否可用"""
        try:
            resp = requests.get(f"{self.api_url}/", timeout=3)
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def synthesize(self, text: str, output_path: str) -> str:
        """
        调用 GPT-SoVITS API 合成语音

        Args:
            text: 待合成文本
            output_path: 输出文件路径

        Returns:
            str: 输出文件路径

        Raises:
            ConnectionError: 服务不可用时抛出
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.ref_audio_path or not Path(self.ref_audio_path).exists():
            raise ValueError(
                f"GPT-SoVITS 需要参考音频文件，请先设置 ref_audio_path（文件不存在: {self.ref_audio_path}）"
            )

        # 构造 API 请求（GPT-SoVITS v2 API）
        payload = {
            "refer_wav_path": str(Path(self.ref_audio_path).resolve()),
            "prompt_text": self.ref_text,
            "prompt_language": "ja",
            "text": text,
            "text_language": self.language,
        }

        try:
            resp = requests.post(
                f"{self.api_url}/",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise ConnectionError(f"GPT-SoVITS 请求超时（120s），请检查服务状态: {self.api_url}")
        except Exception as e:
            raise ConnectionError(f"GPT-SoVITS 服务调用失败: {e}")

        # 写入音频文件（响应通常为音频二进制）
        output_path.write_bytes(resp.content)
        return str(output_path)
