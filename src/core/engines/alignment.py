"""Local Qwen forced alignment. Public timestamps are always seconds."""
from __future__ import annotations

import math
from pathlib import Path

from src.core.resources.model_reference import resolve_model_reference

MODEL_ID = "qwen3-forced-aligner-0.6b"
LANGUAGES = dict(ja="Japanese", zh="Chinese", en="English", yue="Cantonese",
                 fr="French", de="German", it="Italian", ko="Korean",
                 pt="Portuguese", ru="Russian", es="Spanish")


class AlignmentRuntime:
    def __init__(self, *, local=False, model=None):
        self.local = local
        self.model = model

    def align_file(self, *, input_path, segments, language):
        if language not in LANGUAGES:
            raise ValueError(f"对齐模型不支持此语言: {language}")
        if not segments or not any(str(s.get("text", "")).strip() for s in segments):
            raise ValueError("字幕对齐需要非空的识别文字或台本")
        if not self.local:
            from src.core.runtime import get_runtime_router
            return get_runtime_router().align_file(dict(input_path=input_path, segments=segments, language=language))

        import soundfile as sf
        with sf.SoundFile(input_path) as audio:
            rate = audio.samplerate
            duration = len(audio) / rate
            windows = alignment_windows(segments, duration)
            model = self.model or self._load_model()
            aligned, words, warnings = [], [], []
            previous_end = 0.0
            for index, (segment, start, end) in enumerate(windows):
                first = round(start * rate)
                audio.seek(first)
                samples = audio.read(round(end * rate) - first, dtype="float32", always_2d=True).mean(axis=1)
                offset = first / rate
                outputs = model.align(audio=(samples, rate), text=segment["text"], language=LANGUAGES[language])
                items = list(outputs[0].items) if outputs else []
                if not items:
                    raise ValueError(f"第 {index + 1} 段对齐未返回时间戳")
                local_words = []
                last = 0.0
                for item in items:
                    a, b = float(item.start_time), float(item.end_time)
                    clip_duration = len(samples) / rate
                    if not all(math.isfinite(v) for v in (a, b)) or a < last or b < a or a > clip_duration or b > clip_duration + .001:
                        raise ValueError(f"第 {index + 1} 段对齐返回无效时间戳")
                    b = min(b, clip_duration)
                    if a == b:
                        warnings.append(f"第 {index + 1} 段存在零时长文字，请检查")
                    elif b - a > 15:
                        warnings.append(f"第 {index + 1} 段存在异常长的单词时间跨度，请检查")
                    local_words.append(dict(text=item.text, start=a + offset, end=b + offset, segment_index=index))
                    last = b
                a, b = local_words[0]["start"], local_words[-1]["end"]
                if a < previous_end:
                    warnings.append(f"第 {index + 1} 段与前段重叠，请检查")
                previous_end = b
                aligned.append({**segment, "start": a, "end": b})
                words.extend(local_words)
        return dict(segments=aligned, words=words, warnings=warnings, model=MODEL_ID, time_unit="seconds")

    @staticmethod
    def _load_model():
        path = Path(resolve_model_reference(MODEL_ID))
        if not path.is_dir() or not (path / "model.safetensors").is_file():
            raise RuntimeError("请先在模型管理中安装 Qwen3-ForcedAligner-0.6B 及 qwen_asr 运行环境")
        import torch
        from qwen_asr import Qwen3ForcedAligner
        cuda = torch.cuda.is_available()
        return Qwen3ForcedAligner.from_pretrained(str(path), dtype=torch.bfloat16 if cuda else torch.float32,
                                                device_map="cuda:0" if cuda else "cpu", local_files_only=True)


def alignment_windows(segments, duration):
    """Use real anchors; never invent text distribution for a long script."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("对齐音频时长无效")
    windows = []
    previous = -1.0
    for segment in segments:
        if not str(segment.get("text", "")).strip():
            continue
        if "start" not in segment or "end" not in segment:
            if len(segments) != 1 or duration > 300:
                raise ValueError("长台本对齐需要已有识别时间锚点；请先识别或提供带时间轴字幕")
            start, end = 0.0, duration
        else:
            a, b = float(segment["start"]), float(segment["end"])
            if not all(math.isfinite(v) for v in (a, b)) or a < 0 or b <= a or a < previous or b > duration + .1:
                raise ValueError("输入字幕时间锚点无效，请先检查识别结果")
            previous = a
            start, end = max(0.0, a - .75), min(duration, b + .75)
        if end - start > 300:
            raise ValueError("单个字幕片段超过对齐模型的 5 分钟限制，请先重新分段识别")
        windows.append((segment, start, end))
    return windows
