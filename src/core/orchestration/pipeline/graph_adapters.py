"""Typed values and strict adapters for graph pipeline capabilities."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
import math
from pathlib import Path
from typing import Any

from .executor import PipelineExecutor


@dataclass(frozen=True, slots=True)
class GraphValue:
    kind: str
    path: str | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def clone(self):
        return deepcopy(self)


def _duration(value):
    duration = value.metadata.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (float, int)):
        raise ValueError("音频缺少可验证的时长")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("音频时长无效")
    return float(duration)


def _subtitle(value):
    if value.kind != "subtitle" or not value.segments:
        raise ValueError("缺少带时间轴的字幕输入")
    previous, seen = -1.0, set()
    for cue in value.segments:
        start, end, text = cue.get("start"), cue.get("end"), cue.get("text")
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or start < previous
                or (start, end) in seen or not isinstance(text, str) or not text.strip()):
            raise ValueError("字幕包含无效时间轴、重复或空白条目")
        previous = start
        seen.add((start, end))
    if not value.metadata.get("language"):
        raise ValueError("字幕缺少已确认的语言")


def _paired(first, second):
    timeline = first.metadata.get("timeline_id")
    if (not timeline or timeline != second.metadata.get("timeline_id")
            or first.metadata.get("pair_confirmed") is not True
            or second.metadata.get("pair_confirmed") is not True):
        raise ValueError("共同使用的素材尚未确认属于同一录音和时间轴")


def _inspect_audio(path):
    # Loaded only for a selected capability's actual audio output.
    import soundfile as sf
    info = sf.info(str(path))
    return {"duration": info.duration, "sample_rate": info.samplerate,
            "channels": info.channels}


def _export_audio(audio, directory, cancel_event):
    """Make a task-owned byte copy, never a link to a material or upstream output.

    Exclusive creation also protects files left by an earlier interrupted run.
    A partial copy is removed on failure and is never registered as an artifact.
    """
    from src.core.subtitles.translation_reuse import unused_output
    from src.utils.constants import AUDIO_EXTENSIONS

    if audio is None or not audio.path:
        raise ValueError("音频导出需要明确的音频输入")
    source = Path(audio.path)
    if source.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError("音频导出仅支持现有音频格式，保留原格式且不转码")

    def check_cancel():
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("用户取消任务")

    check_cancel()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = unused_output(directory, f"audio{source.suffix}")
    created = False
    try:
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            created = True
            while True:
                check_cancel()
                chunk = incoming.read(1024 * 1024)
                if not chunk:
                    break
                outgoing.write(chunk)
        check_cancel()
        if target.stat().st_size == 0:
            raise ValueError("音频导出未产生有效文件")
        return {"audio": GraphValue("audio", str(target), metadata=deepcopy(audio.metadata))}
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


class GraphStageRunner:
    """One node, one existing capability; no implicit upstream execution."""

    def __init__(self, executor=None, *, audio_inspector=None):
        self.executor = executor or PipelineExecutor()
        self.audio_inspector = audio_inspector or _inspect_audio

    def run(self, node, inputs, plan, directory, *, cancel_event=None):
        kind = node["kind"]
        audio, speech, subtitle = (inputs.get(port) for port in ("audio", "speech", "subtitle"))
        for value in (audio, speech):
            if value is not None:
                if value.kind != "audio" or not value.path or not Path(value.path).is_file():
                    raise ValueError("所选音频输入不存在或类型错误")
                _duration(value)
        if kind == "audio_export":
            return _export_audio(audio, directory, cancel_event)
        if subtitle is not None:
            _subtitle(subtitle)
            language = subtitle.metadata["language"]
            expected = plan.target_lang if kind == "tts" else plan.source_lang
            if kind in {"tts", "translate", "align"} and language != expected:
                raise ValueError("所选字幕语言与节点所需语言不匹配")
        if kind == "align":
            if audio is None or subtitle is None:
                raise ValueError("时间轴校准需要音频和字幕")
            _paired(audio, subtitle)
            if max(cue["end"] for cue in subtitle.segments) > _duration(audio) + .1:
                raise ValueError("字幕时间轴超出所选音频时长")
        if kind == "mix":
            if audio is None or speech is None:
                raise ValueError("混音需要两个音频输入")
            _paired(audio, speech)
            delay = plan.mix.tts_delay_ms / 1000.0
            if not math.isfinite(delay):
                raise ValueError("混音延迟无效")
            if plan.mix.output_length not in ("main", "longest"):
                raise ValueError("混音输出长度必须为 main 或 longest")
        if kind == "tts" and subtitle is not None:
            duration = subtitle.metadata.get("duration")
            if duration is None:
                duration = max(cue["end"] for cue in subtitle.segments)
            if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                    or not math.isfinite(duration) or duration <= 0
                    or max(cue["end"] for cue in subtitle.segments) > duration + .1):
                raise ValueError("配音字幕时间轴与参考时长不一致")
            plan = replace(plan, tts=replace(plan.tts, common_options={
                **plan.tts.common_options, "reference_duration": float(duration),
            }))
        if kind == "export" and subtitle is not None:
            plan = replace(plan, source_lang=subtitle.metadata["language"])
        result = self.executor.execute_stage(
            kind, plan, directory=directory,
            audio_path=audio.path if audio else None,
            speech_path=speech.path if speech else None,
            segments=deepcopy(subtitle.segments) if subtitle else None,
            cancel_event=cancel_event,
        )
        directory = Path(directory)
        if kind in {"separate", "tts", "mix"}:
            source = subtitle if kind == "tts" else audio
            metadata = deepcopy(source.metadata if source else {})
            metadata.update(self.audio_inspector(Path(result["path"])))
            if kind == "mix":
                metadata.update(output_length=plan.mix.output_length,
                                tts_delay_ms=plan.mix.tts_delay_ms,
                                delay_behavior=("trim_before_zero" if plan.mix.tts_delay_ms < 0
                                                else "pad_start" if plan.mix.tts_delay_ms > 0 else "none"))
            value = GraphValue("audio", result["path"], metadata=metadata)
            _duration(value)
            return {"audio": value}

        source = audio if kind == "asr" else subtitle
        metadata = deepcopy(source.metadata if source else {})
        metadata["language"] = plan.target_lang if kind == "translate" else (
            plan.source_lang if kind == "asr" else metadata.get("language"))
        cues = deepcopy(result["segments"])
        value = GraphValue("subtitle", result["path"], cues, metadata)
        _subtitle(value)
        # ASR/translation's old text sidecar is not a timed-subtitle artifact.
        # Serialize their typed output using the existing subtitle writer.
        if kind in {"asr", "translate"}:
            from src.core.subtitles import SubtitleExporter
            target = directory / "subtitle.vtt"
            SubtitleExporter().export_bilingual_subtitle(cues, str(target), bilingual=False)
            if not target.is_file() or target.stat().st_size == 0:
                raise RuntimeError("节点未产生有效字幕产物")
            value = GraphValue("subtitle", str(target), cues, metadata)
        return {"subtitle": value}
