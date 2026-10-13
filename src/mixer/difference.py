"""Reference-based subtraction, ported from the local audio-difference demo.

This assumes the same underlying recording and a fixed sample offset/linear channel gain.
It is not source separation and cannot undo different mastering, drift, EQ or compression.
"""

from collections.abc import Callable
import math

import numpy as np

from .multitrack import _cancel, _load_audio, _number, _output_target, _rate, _write_audio


def _stats(mixed, reference, delay, start, end, stride=1):
    start, end = max(start, 0, delay), min(end, len(mixed), len(reference) + delay)
    if end <= start:
        return 0.0, 0.0, 0.0, 0
    x = mixed[start:end:stride].astype(np.float64)
    y = reference[start - delay:end - delay:stride].astype(np.float64)
    return float(x @ y), float(x @ x), float(y @ y), len(x)


def _corr(xy, xx, yy):
    return xy / math.sqrt(xx * yy) if xx > 1e-15 and yy > 1e-15 else 0.0


def _downsample(data, start, end, step):
    sample = data[start:end].astype(np.float64)
    if not len(sample):
        return sample
    indices = np.arange(0, len(sample), step)
    return np.add.reduceat(sample, indices) / np.minimum(step, len(sample) - indices)


def _estimate_delay(mixed, reference, rate, start, end, search_seconds, check_cancel):
    """FFT normalized correlation at ~6 kHz, followed by sample-level refinement."""
    end = min(end, start + 20 * rate)
    channel = max(range(mixed.shape[1]), key=lambda c:
                  float(np.sum(mixed[start:end:37, c].astype(np.float64) ** 2)))
    m, r = mixed[:, channel], reference[:, channel]
    step = max(1, rate // 6000)
    maximum = round(search_seconds * rate)
    ref_start, ref_end = max(0, start - maximum), min(len(r), end + maximum)
    x, y = _downsample(m, start, end, step), _downsample(r, ref_start, ref_end, step)
    if not len(y):
        raise ValueError("校准区间在参考音频范围外，请调整区间或搜索范围")
    _cancel(check_cancel)
    length = 1 << (len(x) + len(y) - 1).bit_length()
    correlation = np.fft.irfft(np.fft.rfft(x, length) * np.conj(np.fft.rfft(y, length)), length)
    px, py = np.r_[0.0, np.cumsum(x * x)], np.r_[0.0, np.cumsum(y * y)]
    lags = np.arange(1 - len(y), len(x))
    delays = lags * step + start - ref_start
    lo, hi = np.maximum(0, lags), np.minimum(len(x), len(y) + lags)
    valid = ((np.abs(delays) <= maximum)
             & (hi - lo >= min(len(x) * 0.6, rate / step)))
    lags, delays, lo, hi = (value[valid] for value in (lags, delays, lo, hi))
    if not len(lags):
        raise ValueError("自动对齐没有足够的重叠音频")
    denominator = np.sqrt(np.maximum(0, (px[hi] - px[lo]) * (py[hi-lags] - py[lo-lags])))
    scores = np.divide(np.abs(correlation[lags % length]), denominator,
                       out=np.zeros_like(denominator), where=denominator > 1e-12)
    coarse = int(delays[np.argmax(scores)])
    pieces = [(start + (end - start) * j // 3,
               min(start + (end - start) * j // 3 + int(rate * 0.4), end))
              for j in range(3)]
    best, delay = -1.0, coarse
    for candidate in range(max(-maximum, coarse - 2 * step),
                           min(maximum, coarse + 2 * step) + 1):
        _cancel(check_cancel)
        totals = np.sum([_stats(m, r, candidate, a, b)[:3] for a, b in pieces], axis=0)
        score = abs(_corr(*totals))
        if score > best:
            best, delay = score, candidate
    xy, xx, yy, _ = _stats(m, r, delay, start, end, max(1, rate // 24000))
    corr = _corr(xy, xx, yy)
    if abs(corr) < 0.2:
        raise ValueError("相关性太低，无法可靠自动对齐；请选择同一段底音或手动设置偏移")
    return delay, corr, abs(delay) >= maximum - 2 * step, (end - start) / rate


def extract_difference(
    mixed_path, reference_path, output_path, *, sample_rate: int | None = None,
    calibration_start: float = 0, calibration_end: float | None = None,
    offset_ms: float = 0, gain_left: float = 1, gain_right: float = 1,
    auto_align: bool = False, auto_gain: bool = False, search_seconds: float = 5,
    check_cancel: Callable | None = None,
) -> dict:
    """Subtract an aligned/scaled reference, keeping the mixed file's entire duration.

    Positive offset delays the reference on the mixed timeline. Calibration is measured
    on that timeline; ``None`` ends at the mixed audio's end. Automatic gain
    uses the complete calibration window; automatic alignment analyzes at most 20 s.
    Mono is duplicated when paired with stereo. FLOAT WAV preserves values above 1;
    uncovered edges keep the original mixed audio. Cancellation callbacks may raise.
    """
    rate = _rate(sample_rate)
    offset = _number(offset_ms, "参考偏移")
    gains = [_number(gain_left, "左声道增益"),
             _number(gain_right, "右声道增益")]
    start_seconds = _number(calibration_start, "校准起点", 0)
    search = _number(search_seconds, "偏移搜索范围", 0.01, 30)
    if not isinstance(auto_align, bool) or not isinstance(auto_gain, bool):
        raise ValueError("自动对齐和自动增益必须为布尔值")
    output = _output_target(output_path, [mixed_path, reference_path])
    mixed, rate = _load_audio(mixed_path, rate, check_cancel)
    reference, _ = _load_audio(reference_path, rate, check_cancel)
    channels = max(mixed.shape[1], reference.shape[1])
    if mixed.shape[1] < channels:
        mixed = np.repeat(mixed, channels, axis=1)
    if reference.shape[1] < channels:
        reference = np.repeat(reference, channels, axis=1)
    duration = len(mixed) / rate
    end_seconds = (duration if calibration_end is None
                   else _number(calibration_end, "校准终点", 0))
    if start_seconds >= end_seconds or end_seconds > duration + 0.5 / rate:
        raise ValueError("校准区间必须位于混音内，且终点大于起点")
    start, end = round(start_seconds * rate), min(len(mixed), round(end_seconds * rate))
    if (auto_align or auto_gain) and end - start < math.ceil(rate * 0.2):
        raise ValueError("校准区间至少需要 0.2 秒有效音频")
    delay, corr, boundary, analysis_seconds = round(offset * rate / 1000), None, False, 0.0
    if auto_align:
        delay, corr, boundary, analysis_seconds = _estimate_delay(
            mixed, reference, rate, start, end, search, check_cancel)
    if auto_gain:
        gains = []
        for channel in range(channels):
            _cancel(check_cancel)
            xy, _, yy, count = _stats(mixed[:, channel], reference[:, channel], delay, start, end)
            if count < math.ceil(rate * 0.2) or yy < 1e-10:
                raise ValueError("参考校准区间太短或接近静音，无法估算增益")
            gains.append(xy / yy)
    gains = gains[:channels]
    overlap_start, overlap_end = max(0, delay), min(len(mixed), len(reference) + delay)
    if overlap_end <= overlap_start:
        raise ValueError("两份音频没有重叠，请检查偏移")
    # Subtract in bounded float64 blocks; final float32 keeps the original amplitude.
    peak = 0.0
    sum_squares = 0.0
    for begin in range(0, len(mixed), 262144):
        _cancel(check_cancel)
        finish = min(len(mixed), begin + 262144)
        block = mixed[begin:finish].astype(np.float64)
        a, b = max(begin, overlap_start), min(finish, overlap_end)
        if b > a:
            block[a-begin:b-begin] -= reference[a-delay:b-delay].astype(np.float64) * gains
        block_peak = float(np.max(np.abs(block)))
        if not np.isfinite(block).all() or block_peak > np.finfo(np.float32).max:
            raise ValueError("差分幅度超出浮点 WAV 有效范围，请检查增益")
        peak = max(peak, block_peak)
        sum_squares += float(np.sum(block * block))
        mixed[begin:finish] = block
    _write_audio(output, mixed, rate, check_cancel)
    warnings = ["参考差分只适合同源固定偏移和线性增益；不同母带、压缩、EQ、混响或时间漂移会留下残留。",
                "校准区间中的附加音效可能被增益拟合部分误消。"]
    if overlap_start or overlap_end < len(mixed):
        warnings.append("参考未覆盖的首尾保留原始混音。")
    if boundary:
        warnings.append("自动偏移接近搜索边界，建议扩大搜索范围。")
    if auto_align:
        warnings.append("相关系数不代表准确概率；周期性底音可能误对齐，请试听确认。")
    if peak > 1:
        warnings.append("浮点 WAV 保留超过 0 dBFS 的幅度，播放设备可能削波。")
    return {"path": str(output), "sample_rate": rate, "channels": channels,
            "duration": duration, "offset_samples": delay, "offset_ms": delay / rate * 1000,
            "gains": gains, "correlation": corr, "analysis_seconds": analysis_seconds,
            "coverage_start": overlap_start / rate, "coverage_end": overlap_end / rate,
            "uncaptured_seconds": (len(mixed) - overlap_end + overlap_start) / rate,
            "peak": peak, "rms": math.sqrt(sum_squares / mixed.size), "warnings": warnings}
