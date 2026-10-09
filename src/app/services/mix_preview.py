"""Short, temporary previews using the pipeline's actual mixer and existing audio."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess

import numpy as np
import soundfile as sf

from src.app.errors import AppValidationError
from src.mixer import Mixer
from src.utils import get_ffmpeg


def resolve_mix_sources(task_id, tasks, artifacts, inputs):
    task = tasks.get_task(task_id)
    if task.task_type != "pipeline" or task.state in {"pending", "running"}:
        raise AppValidationError("请先完成语音合成任务，再试听已有配音")
    entries = artifacts.get_task_artifacts(task_id).entries
    speech = next((item.path for item in entries if item.artifact_type == "audio.tts"), None)
    manifest = tasks.recovery_store.manifest(task_id) if tasks.recovery_store else None
    original = manifest.get("input_path") if manifest else None
    if not original:
        try:
            original = inputs.get_asset(task.input_asset_id).absolute_path
        except (ValueError, KeyError):
            raise AppValidationError("原始输入记录已不可用，请重新处理此音频") from None
    source = next((item.path for item in entries if item.artifact_type == "audio.vocals"), original)
    if not speech or not Path(speech).is_file() or not source or not Path(source).is_file():
        raise AppValidationError("缺少原音或已生成的配音文件，请先完成语音合成")
    return str(original), str(source), str(speech)


def _rms(path):
    total = 0.0
    count = 0
    for block in sf.blocks(path, blocksize=262144, dtype="float64"):
        total += float(np.sum(np.square(block)))
        count += block.size
    return float(np.sqrt(total / count)) if count else 0.0


def _ffmpeg(*args):
    result = subprocess.run([get_ffmpeg(), "-nostdin", "-v", "error", *args],
                            capture_output=True, timeout=90)
    if result.returncode:
        raise AppValidationError("无法解码或生成试听音频，请检查原音与配音文件是否完整")
    return result.stdout


def render_mix_preview(source, speech, *, original_volume, tts_volume_ratio, tts_delay, start_seconds):
    source_info = sf.info(source)
    duration = source_info.duration
    if start_seconds >= duration:
        raise AppValidationError("试听起点超出音频时长")
    # Once the non-padded TTS track and amix's 2 s dropout transition have ended,
    # production mixing has only the original input. Keeping silent TTS would halve it.
    if tts_delay >= 0 and start_seconds >= sf.info(speech).duration + tts_delay + 2:
        return _ffmpeg("-ss", str(start_seconds), "-i", source, "-t", "15",
                       "-af", f"volume={original_volume}", "-ar", "44100", "-ac", "2",
                       "-c:a", "pcm_s16le", "-f", "wav", "pipe:1")
    # Keep overlap before/after the requested window so both delay signs remain correct.
    clip_start = max(0.0, start_seconds - abs(tts_delay) - 3.0)
    # Align the input window to decoder blocks to retain amix dropout timing.
    clip_start = int(clip_start * source_info.samplerate / 4096) * 4096 / source_info.samplerate
    clip_duration = start_seconds - clip_start + 15.0 + abs(tts_delay) + 3.0
    global_levels = [_rms(source), _rms(speech)]
    with TemporaryDirectory(prefix="asmr-mix-preview-") as directory:
        clips = [str(Path(directory) / name) for name in ("original.wav", "speech.wav")]
        for path, output in zip((source, speech), clips, strict=True):
            # An exhausted TTS track is represented as silence, never a new synthesis.
            if clip_start >= sf.info(path).duration:
                sf.write(output, np.zeros((int(clip_duration * 44100), 2)), 44100, subtype="FLOAT")
            else:
                _ffmpeg("-ss", str(clip_start), "-i", path, "-t", str(clip_duration),
                        "-c:a", "pcm_f32le", "-y", output)

        class PreviewMixer(Mixer):
            def detect_volume(self, path):
                return global_levels[clips.index(path)]

        mixed = str(Path(directory) / "mix.wav")
        # Zero ratio is valid. Mixer uses log10(ratio); suppress its harmless -inf warning.
        with np.errstate(divide="ignore"):
            PreviewMixer(original_volume, tts_volume_ratio, tts_delay * 1000).mix(*clips, mixed)
        return _ffmpeg("-ss", str(start_seconds - clip_start), "-i", mixed, "-t", "15",
                       "-c:a", "pcm_s16le", "-f", "wav", "pipe:1")
