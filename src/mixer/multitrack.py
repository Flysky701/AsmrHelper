"""Linear N-track mixing on one output timeline, independent of legacy TTS mixing."""

from collections.abc import Callable, Mapping, Sequence
import math
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import soundfile as sf

from ..utils import get_ffmpeg


def _cancel(check_cancel: Callable | None) -> None:
    if check_cancel is not None and check_cancel():
        raise RuntimeError("音频处理已取消")


def _number(value, name: str, minimum=None, maximum=None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须为有效数值") from exc
    if (not math.isfinite(result) or (minimum is not None and result < minimum)
            or (maximum is not None and result > maximum)):
        raise ValueError(f"{name}超出有效范围")
    return result


def _rate(sample_rate) -> int | None:
    if sample_rate is None:
        return None
    value = _number(sample_rate, "采样率", 8000, 192000)
    if not value.is_integer():
        raise ValueError("采样率必须为整数")
    return int(value)


def _run_ffmpeg(command: list[str], check_cancel: Callable | None) -> None:
    _cancel(check_cancel)
    with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        try:
            while True:
                try:
                    _, stderr = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    _cancel(check_cancel)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace")[-2000:]
            raise ValueError(f"无法解码音频: {detail}")
    _cancel(check_cancel)


def _load_audio(path, sample_rate=None, check_cancel=None) -> tuple[np.ndarray, int]:
    """Decode without normalization; FFmpeg handles resampling/unsupported containers."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"音频文件不存在: {path.name}")
    _cancel(check_cancel)
    try:
        info = sf.info(path)
    except (RuntimeError, sf.LibsndfileError):
        info = None
    if info is not None and info.channels not in (1, 2):
        raise ValueError("仅支持单声道或双声道音频")
    if info is not None and (sample_rate is None or sample_rate == info.samplerate):
        data, rate = sf.read(path, dtype="float32", always_2d=True)
    else:
        with tempfile.TemporaryDirectory(prefix="asmr-audio-decode-") as directory:
            converted = Path(directory) / "decoded.wav"
            command = [get_ffmpeg(), "-nostdin", "-v", "error", "-i", str(path),
                       "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le"]
            if sample_rate is not None:
                command += ["-ar", str(sample_rate)]
            # Preserve the channel count for validation; never silently downmix surround.
            command += ["-y", str(converted)]
            _run_ffmpeg(command, check_cancel)
            data, rate = sf.read(converted, dtype="float32", always_2d=True)
    if data.shape[1] not in (1, 2):
        raise ValueError("仅支持单声道或双声道音频")
    if not len(data) or not np.isfinite(data).all():
        raise ValueError("音频为空或包含无效采样")
    _cancel(check_cancel)
    return data, rate


def _output_target(output_path, input_paths) -> Path:
    output = Path(output_path)
    if output.suffix.lower() != ".wav":
        raise ValueError("输出必须为 WAV 文件")
    if any(output.resolve() == Path(path).resolve() for path in input_paths):
        raise ValueError("输出不能覆盖输入音频")
    return output


def _write_audio(output: Path, data: np.ndarray, rate: int, check_cancel=None) -> None:
    """Publish only a complete float WAV, retaining any previous output on cancellation."""
    _cancel(check_cancel)
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{output.stem}-", suffix=".wav", dir=output.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        with sf.SoundFile(temporary, "w", samplerate=rate, channels=data.shape[1],
                          subtype="FLOAT", format="WAV") as stream:
            for start in range(0, len(data), 262144):
                _cancel(check_cancel)
                block = data[start:start + 262144]
                if (not np.isfinite(block).all()
                        or np.max(np.abs(block)) > np.finfo(np.float32).max):
                    raise ValueError("输出幅度超出浮点 WAV 有效范围")
                stream.write(block)
        _cancel(check_cancel)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def mix_tracks(
    tracks: Sequence[Mapping], output_path, *, output_length: str = "longest",
    sample_rate: int | None = None, check_cancel: Callable | None = None,
) -> dict:
    """Sum tracks with explicit linear gains; positive offsets delay, negative ones trim.

    Each track has ``path``, ``gain`` (>= 0), ``offset_ms``, and ``muted``.
    The first track defines the default rate and ``main`` duration, after its offset.
    All tracks, including muted tracks, define ``longest`` duration and channel count.
    Mono is copied to both channels when paired with stereo. Peak safety only attenuates
    sums above 1.0 to 0.98; it never amplifies a quiet signal or changes relative gains.
    A timeline entirely before zero yields one silent sample, retaining a valid WAV.
    """
    if not tracks or isinstance(tracks, (str, bytes)):
        raise ValueError("混音至少需要一条音轨")
    if output_length not in ("main", "longest"):
        raise ValueError("混音输出长度必须为 main 或 longest")
    rate = _rate(sample_rate)
    parsed = []
    for track in tracks:
        if not isinstance(track, Mapping) or not track.get("path"):
            raise ValueError("每条音轨都需要音频文件")
        gain = _number(track.get("gain", 1), "音轨增益", 0)
        offset = _number(track.get("offset_ms", 0), "音轨偏移")
        muted = track.get("muted", False)
        if not isinstance(muted, bool):
            raise ValueError("静音参数必须为布尔值")
        parsed.append((track["path"], gain, offset, muted))
    output = _output_target(output_path, [item[0] for item in parsed])

    # Use temporary float files instead of retaining every decoded source in memory.
    with tempfile.TemporaryDirectory(prefix="asmr-multitrack-") as directory:
        prepared = []
        channels = 1
        frames = main_frames = 0
        for index, (path, gain, offset_ms, muted) in enumerate(parsed):
            data, decoded_rate = _load_audio(path, rate, check_cancel)
            rate = decoded_rate
            shift = round(offset_ms * rate / 1000)
            if index == 0:
                main_frames = len(data) + shift
            frames = max(frames, len(data) + shift)
            channels = max(channels, data.shape[1])
            decoded = Path(directory) / f"track-{index}.wav"
            _write_audio(decoded, data, rate, check_cancel)
            prepared.append((decoded, gain, shift, muted, len(data)))
            del data
        if output_length == "main":
            frames = main_frames
        frames = max(1, frames)
        # Disk-backed accumulation bounds RAM even for long ASMR tracks and large offsets.
        mixed = np.memmap(Path(directory) / "sum.f64", mode="w+", dtype="float64",
                          shape=(frames, channels))
        try:
            mixed[:] = 0
            for decoded, gain, shift, muted, count in prepared:
                _cancel(check_cancel)
                if muted or gain == 0:
                    continue
                start, end = max(0, shift), min(frames, count + shift)
                if start >= end:
                    continue
                with sf.SoundFile(decoded) as stream:
                    stream.seek(start - shift)
                    for position in range(start, end, 262144):
                        _cancel(check_cancel)
                        block = stream.read(min(262144, end - position), dtype="float64",
                                            always_2d=True)
                        mixed[position:position + len(block)] += block * gain
            peak = 0.0
            for start in range(0, frames, 262144):
                _cancel(check_cancel)
                value = float(np.max(np.abs(mixed[start:start + 262144])))
                if not math.isfinite(value):
                    raise ValueError("混音幅度超出有效范围，请减小增益")
                peak = max(peak, value)
            safety_gain = 0.98 / peak if peak > 1 else 1.0
            if safety_gain < 1:
                for start in range(0, frames, 262144):
                    _cancel(check_cancel)
                    mixed[start:start + 262144] *= safety_gain
            _write_audio(output, mixed, rate, check_cancel)
        finally:
            # Close the mmap explicitly before TemporaryDirectory cleanup on Windows.
            mixed._mmap.close()
    return {"path": str(output), "sample_rate": rate, "channels": channels,
            "duration": frames / rate, "peak_before": peak, "safety_gain": safety_gain,
            "track_count": len(parsed), "output_length": output_length,
            "peak_policy": "attenuate_above_1_to_0.98"}
