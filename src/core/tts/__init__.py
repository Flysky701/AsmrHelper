"""
Speech 共用的 Edge 底层适配与 Qwen 语言归一

功能：将文本转换为语音
"""

import asyncio
import re

import subprocess
from pathlib import Path
from typing import Optional, List

import edge_tts
from edge_tts.exceptions import NoAudioReceived
from aiohttp import ClientError

from src.utils import get_ffmpeg


_QWEN3_LANGUAGE_ALIASES = {
    "": "Auto",
    "auto": "Auto",
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "chinese": "Chinese",
    "en": "English",
    "en-us": "English",
    "english": "English",
    "ja": "Japanese",
    "ja-jp": "Japanese",
    "jp": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "ko-kr": "Korean",
    "korean": "Korean",
    "de": "German",
    "de-de": "German",
    "german": "German",
    "fr": "French",
    "fr-fr": "French",
    "french": "French",
    "ru": "Russian",
    "ru-ru": "Russian",
    "russian": "Russian",
    "pt": "Portuguese",
    "pt-pt": "Portuguese",
    "pt-br": "Portuguese",
    "portuguese": "Portuguese",
    "es": "Spanish",
    "es-es": "Spanish",
    "spanish": "Spanish",
    "it": "Italian",
    "it-it": "Italian",
    "italian": "Italian",
}


def normalize_qwen3_language(language: Optional[str]) -> str:
    """Map project language codes to Qwen3-TTS's supported language names."""
    key = str(language or "auto").strip().lower().replace("_", "-")
    normalized = _QWEN3_LANGUAGE_ALIASES.get(key)
    if normalized is None and "-" in key:
        normalized = _QWEN3_LANGUAGE_ALIASES.get(key.split("-", 1)[0])
    if normalized is None:
        supported = ", ".join(
            ("auto", "zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it")
        )
        raise ValueError(
            f"Qwen3-TTS does not support language {language!r}; supported: {supported}"
        )
    return normalized


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)


class EdgeTTSEngine:
    """Edge-TTS 引擎"""

    MAX_CONCURRENT_REQUESTS = 4
    MAX_NETWORK_ATTEMPTS = 3
    CONNECT_TIMEOUT_SECONDS = 15
    RECEIVE_TIMEOUT_SECONDS = 60

    # 预设音色
    VOICES = {
        "zh-CN-XiaoxiaoNeural": "晓晓（女）",
        "zh-CN-YunxiNeural": "云希（男）",
        "zh-CN-YunyangNeural": "云扬（男）",
        "zh-CN-XiaoyiNeural": "小艺（女）",
        "ja-JP-NanamiNeural": "七海（日语女）",
        "ja-JP-KeitaNeural": "惠太（日语男）",
        "en-US-JennyNeural": "Jenny（英语女）",
    }

    @classmethod
    def list_voices(cls) -> list[dict]:
        return [
            {"id": vid, "name": desc, "language": vid.split("-")[0] + "-" + vid.split("-")[1] if "-" in vid else ""}
            for vid, desc in cls.VOICES.items()
        ]

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
        proxy: Optional[str] = None,
    ):
        """
        初始化 Edge-TTS 引擎

        Args:
            voice: 音色名称
            rate: 语速 (+/-%)
            volume: 音量 (+/-%)
            pitch: 音调 (+/-Hz)
            proxy: 可选 HTTP 代理
        """
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch
        self.proxy = proxy.strip() if proxy else None

        print(f"[EdgeTTS] 音色: {voice} ({self.VOICES.get(voice, 'unknown')})")

    async def synthesize_async(self, text: str, output_path: str) -> str:
        """
        异步合成语音

        Args:
            text: 待合成文本
            output_path: 输出文件路径（支持 .wav 或 .mp3）

        Returns:
            str: 输出文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        suffix = output_path.suffix.lower()
        if suffix not in {".wav", ".mp3"}:
            raise ValueError("Edge TTS output_path must use .wav or .mp3")

        # Edge-TTS already returns MP3. Do not ask FFmpeg to read and overwrite
        # the same file when the caller explicitly requests that format.
        if suffix == ".mp3":
            await self._save_mp3_with_retry(text, output_path)
            return str(output_path)

        # Edge-TTS 默认输出 MP3（有损），先用临时文件存储再转为 WAV
        temp_mp3 = output_path.with_suffix(".mp3")

        await self._save_mp3_with_retry(text, temp_mp3)

        # 转换为 WAV 无损格式（强制 WAV 输出）
        try:
            self._convert_to_wav(temp_mp3, output_path)
        finally:
            # 确保清理临时 mp3 文件（无论转换成功与否）
            temp_mp3.unlink(missing_ok=True)

        return str(output_path)

    async def _save_mp3_with_retry(self, text: str, temp_mp3: Path) -> None:
        """Retry transient Edge network failures without rerunning the pipeline."""
        for attempt in range(1, self.MAX_NETWORK_ATTEMPTS + 1):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    self.voice,
                    rate=self.rate,
                    volume=self.volume,
                    pitch=self.pitch,
                    proxy=self.proxy,
                    connect_timeout=self.CONNECT_TIMEOUT_SECONDS,
                    receive_timeout=self.RECEIVE_TIMEOUT_SECONDS,
                )
                await communicate.save(str(temp_mp3))
                return
            except (ClientError, TimeoutError, NoAudioReceived) as exc:
                temp_mp3.unlink(missing_ok=True)
                if attempt >= self.MAX_NETWORK_ATTEMPTS:
                    raise RuntimeError(
                        "Edge TTS request failed after "
                        f"{self.MAX_NETWORK_ATTEMPTS} attempts "
                        f"({type(exc).__name__})"
                    ) from exc
                print(
                    "[EdgeTTS] 网络请求重试 "
                    f"{attempt}/{self.MAX_NETWORK_ATTEMPTS - 1}: "
                    f"{type(exc).__name__}"
                )
                await asyncio.sleep(0.5 * attempt)

    def _convert_to_wav(self, input_path: Path, output_path: Path):
        """将音频转换为 WAV 无损格式"""
        ffmpeg_path = get_ffmpeg()
        cmd = [
            ffmpeg_path,
            "-i", str(input_path),
            "-acodec", "pcm_f32le",  # 32-bit float WAV
            "-ar", "44100",
            "-ac", "2",
            str(output_path),
            "-y",
        ]

        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )

    def synthesize(self, text: str, output_path: str) -> str:
        """同步合成语音"""
        return _run_async(self.synthesize_async(text, output_path))

    async def _synthesize_all_async(self, sentences: List[str], temp_files: List[Path]):
        """Bound Edge requests so one task does not open dozens of WebSockets."""
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)

        async def synthesize_one(sentence: str, temp_file: Path) -> None:
            async with semaphore:
                await self.synthesize_async(sentence, str(temp_file))

        tasks = [
            synthesize_one(sent, tf)
            for sent, tf in zip(sentences, temp_files, strict=True)
            if sent.strip()
        ]
        await asyncio.gather(*tasks)

    def synthesize_long_text(self, text: str, output_path: str) -> str:
        """合成长文本（分段处理）"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 按句子分割
        sentences = self._split_sentences(text)
        sentences = [s for s in sentences if s.strip()]

        if not sentences:
            return str(output_path)

        # 生成临时文件列表（WAV 格式避免有损压缩）
        temp_files = [output_path.parent / f"temp_tts_{i}.wav" for i in range(len(sentences))]

        # 用单个事件循环并发合成所有句子
        _run_async(self._synthesize_all_async(sentences, temp_files))

        # 合并音频
        existing = [f for f in temp_files if f.exists()]
        self._merge_audio(existing, output_path)

        # 清理临时文件
        for f in temp_files:
            f.unlink(missing_ok=True)

        return str(output_path)

    def _split_sentences(self, text: str, max_length: int = 500) -> List[str]:
        """按句子分割文本"""
        # 简单按句号、问号、感叹号分割
        sentences = re.split(r"([。！？])", text)
        result = []
        current = ""

        for i in range(0, len(sentences) - 1, 2):
            sent = sentences[i] + sentences[i + 1]
            if len(current) + len(sent) <= max_length:
                current += sent
            else:
                if current:
                    result.append(current)
                current = sent

        if len(sentences) % 2 == 1 and sentences[-1].strip():
            if len(current) + len(sentences[-1]) <= max_length:
                current += sentences[-1]
            else:
                if current:
                    result.append(current)
                current = sentences[-1]

        if current:
            result.append(current)

        return result

    def _merge_audio(self, input_files: List[Path], output_path: Path):
        """合并多个音频文件"""
        if not input_files:
            return

        # 使用 ffmpeg 合并
        concat_file = output_path.parent / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for fpath in input_files:
                escaped = str(fpath).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        cmd = [
            get_ffmpeg(),
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
            "-y",
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        finally:
            concat_file.unlink(missing_ok=True)
