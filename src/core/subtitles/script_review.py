"""Trust boundaries for script review, timing and immutable local outputs."""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from pathlib import Path


class ScriptReviewRequired(ValueError):
    def __init__(self, review: dict):
        self.review = review
        super().__init__(
            "台本匹配需要核对：未匹配、额外录音或冲突项尚未解决，未导出字幕"
        )


def validate_timed_entries(
    entries: list[dict], *, duration: float | None = None
) -> None:
    if not entries:
        raise ValueError("没有可信的字幕时间锚点；请先识别录音或提供原文字幕")
    previous_end = 0.0
    for i, entry in enumerate(entries):
        a, b, text = entry.get("start"), entry.get("end"), entry.get("text")
        if (
            isinstance(a, bool)
            or isinstance(b, bool)
            or not isinstance(a, (int, float))
            or not isinstance(b, (int, float))
            or not math.isfinite(a)
            or not math.isfinite(b)
            or a < 0
            or b <= a
            or a < previous_end
            or (duration is not None and b > duration + 0.001)
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError(
                f"第 {i + 1} 段时间轴或文本无效（负值、倒序、重叠、越界或空白）"
            )
        previous_end = b


def script_fingerprint(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new_text(path: str | Path, content: str, *, inputs=()) -> str:
    target = Path(path).resolve()
    if any(target == Path(source).resolve() for source in inputs if source):
        raise ValueError("输出不能覆盖输入文件")
    if target.exists():
        raise ValueError("输出文件已存在，请使用新的文件名")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Publish complete bytes exclusively; a interrupted write never replaces a result.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=".script-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if os.name == "nt":
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        except FileExistsError as exc:
            raise ValueError("输出文件已存在，请使用新的文件名") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(target)


def subtitle_content(entries: list[dict], fmt: str) -> str:
    from .exporter import SubtitleExporter
    from .models import SubtitleDocument, SubtitleSegment

    validate_timed_entries(entries)
    document = SubtitleDocument(
        segments=[SubtitleSegment(e["start"], e["end"], e["text"]) for e in entries]
    )
    exporters = {
        "vtt": "export_vtt_text",
        "srt": "export_srt_text",
        "lrc": "export_lrc_text",
    }
    if fmt not in exporters:
        raise ValueError(f"unsupported subtitle format: {fmt}")
    return getattr(SubtitleExporter(), exporters[fmt])(document)
