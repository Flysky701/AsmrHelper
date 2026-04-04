"""
人声分离模块 - 使用 Demucs 4.0

功能：从混合音频中分离出人声、鼓点、贝斯和其他乐器
"""

import os
import time
from pathlib import Path
from typing import Optional, Literal

import numpy as np
import soundfile as sf
import torch
from demucs.pretrained import get_model
from demucs.apply import apply_model

from src.utils import ensure_dir


class VocalSeparator:
    """人声分离器（基于 Demucs 4.0）"""

    # 支持的模型
    MODELS = {
        "htdemucs": "htdemucs",  # 默认模型，分离 4 轨
        "htdemucs_ft": "htdemucs_ft",  # 微调版本
        "htdemucs_6s": "htdemucs_6s",  # 6 轨版本
        "mdx": "mdx",  # MDX 模型
        "mdx_extra": "mdx_extra",  # MDX 扩展
    }

    def __init__(
        self,
        model_name: str = "htdemucs",
        device: Optional[str] = None,
        progress: bool = True,
    ):
        """
        初始化人声分离器

        Args:
            model_name: 模型名称
            device: 计算设备 (cuda/cpu)
            progress: 是否显示进度
        """
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.progress = progress

        # 加载模型
        self.model = get_model(model_name)
        self.model = self.model.to(self.device)
        self.model.eval()

        print(f"[VocalSeparator] 模型: {model_name}, 设备: {self.device}")

    def separate(
        self,
        audio_path: str,
        output_dir: str,
        stems: Optional[list] = None,
    ) -> dict:
        """
        分离音频

        Args:
            audio_path: 输入音频路径
            output_dir: 输出目录
            stems: 要提取的音轨列表 (vocals/drums/bass/other)

        Returns:
            dict: 分离结果 {stem: path}
        """
        audio_path = Path(audio_path)
        output_dir = Path(output_dir)
        ensure_dir(output_dir)

        # 默认提取人声
        if stems is None:
            stems = ["vocals"]

        print(f"[VocalSeparator] 分离音频: {audio_path.name}")

        t0 = time.time()

        # 使用 soundfile 加载音频（避免 ffmpeg 依赖）
        wav_data, sample_rate = sf.read(str(audio_path))
        
        # 转换为 tensor 并调整为 (channels, samples) 格式
        if wav_data.ndim == 1:
            wav_data = wav_data[:, None]
        wav = torch.from_numpy(wav_data.T).float()

        # 重采样到模型采样率（如果需要）
        if sample_rate != self.model.samplerate:
            import torchaudio
            resampler = torchaudio.transforms.Resample(sample_rate, self.model.samplerate)
            wav = resampler(wav)
        
        # 确保声道数匹配
        if wav.shape[0] != self.model.audio_channels:
            if wav.shape[0] == 1:
                wav = wav.repeat(self.model.audio_channels, 1)
            else:
                wav = wav[:self.model.audio_channels, :]

        # 分离
        with torch.no_grad():
            separated = apply_model(self.model, wav[None], device=self.device)

        # 获取源名称（Demucs 4.0 API）
        sources = self.model.sources
        results = {}

        # 清理文件名中的特殊字符
        safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in audio_path.stem)

        for i, source in enumerate(sources):
            # 只处理指定的音轨
            if stems is not None and source not in stems:
                continue

            # 转换为 numpy (shape: [channel, time]) -> 需要转为 [time, channel]
            source_wav = separated[0, i].cpu().numpy()  # (channel, time)
            source_wav = source_wav.T  # (time, channel)

            # 确保是 float32
            source_wav = source_wav.astype(np.float32)

            # 保存为 WAV（使用无损float格式避免量化失真）
            stem_path = output_dir / f"{safe_name}_{source}.wav"
            sf.write(stem_path, source_wav, self.model.samplerate, subtype="FLOAT")

            results[source] = str(stem_path)
            print(f"  - {source}: {stem_path.name}")

        print(f"[VocalSeparator] 分离完成，耗时: {time.time() - t0:.1f}s")

        return results

    def separate_vocals(self, audio_path: str, output_dir: str) -> str:
        """
        快速分离人声

        Args:
            audio_path: 输入音频路径
            output_dir: 输出目录

        Returns:
            str: 人声音轨路径
        """
        results = self.separate(audio_path, output_dir, stems=["vocals"])
        return results.get("vocals", "")

    def unload(self):
        """
        释放模型占用的 GPU 内存（Phase 3）

        在批量处理完成后调用以释放显存。
        """
        if hasattr(self, "model") and self.model is not None:
            del self.model
            self.model = None
            if self.device.startswith("cuda"):
                import torch
                torch.cuda.empty_cache()
            print(f"[VocalSeparator] 模型已卸载，设备: {self.device}")


# 便捷函数
def separate_vocals(
    audio_path: str,
    output_dir: str,
    model_name: str = "htdemucs",
) -> str:
    """快速分离人声"""
    separator = VocalSeparator(model_name=model_name)
    return separator.separate_vocals(audio_path, output_dir)
