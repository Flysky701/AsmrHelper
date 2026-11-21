"""Script preparation and matching; never synthesize recording timestamps."""

from __future__ import annotations

import json
from pathlib import Path
from src.core.subtitles.script_tool import ScriptToSubtitleTool
from src.core.subtitles.script_processor import ScriptProcessor
from src.core.subtitles.script_review import (
    ScriptReviewRequired,
    script_fingerprint,
    validate_timed_entries,
    write_new_text,
    subtitle_content,
)


class ScriptToSubtitlePipeline:
    def preview(
        self,
        script_path,
        *,
        track_index=None,
        vertical_mode="auto",
        use_llm_clean=False,
    ):
        raw = ScriptToSubtitleTool.load_script(script_path, vertical_mode=vertical_mode)
        sections = ScriptProcessor.detect_scripts(raw)
        if track_index is not None:
            if type(track_index) is not int or not 0 <= track_index < len(sections):
                raise ValueError("台本章节索引超出范围，请重新选择章节")
            selected = sections[track_index]["text"]
        else:
            selected = raw
        actions = ScriptProcessor.extract_stage_descriptions(selected)[1]
        from src.core.subtitles.generator import SubtitleGenerator

        actions.extend(SubtitleGenerator.extract_action_descriptions(selected))
        # Lenticular brackets are removed by the cleaner as well.
        import re

        actions.extend(
            {"text": m.group(), "type": "bracket"}
            for m in re.finditer(r"【[^】]*】", selected)
        )
        cleaner = (
            ScriptToSubtitleTool.clean_script_with_llm
            if use_llm_clean
            else ScriptToSubtitleTool.clean_script
        )
        cleaned = cleaner(selected)
        if not raw.strip():
            raise ValueError("未提取到文字，请检查PDF文字层或台本格式")
        return {
            "raw_text": selected,
            "clean_text": cleaned,
            "actions": list(dict.fromkeys(a["text"] for a in actions)),
            "sections": [{"index": s["index"], "title": s["title"]} for s in sections],
            "fingerprint": script_fingerprint(script_path),
        }

    def align_draft(self, script_path, segments):
        """Bind script lines to real recording cues and preserve unmatched audio for review."""
        preview = self.preview(script_path)
        lines = [line.strip() for line in preview["clean_text"].splitlines() if line.strip()]
        return self.align_draft_lines(lines, segments)

    @staticmethod
    def align_draft_lines(lines, segments):
        from src.core.engines.llm.script_cleaner import LLMProcessor

        if not lines:
            raise ValueError("台本未提取到可匹配的台词")
        unreliable = {"missing", "estimated", "proportional", "synthetic"}
        source = [seg for seg in segments if str(seg.get("source_text") or "").strip()
                  and seg.get("timestamp_source") not in unreliable]
        anchors = [{"start": s["start"], "end": s["end"], "text": s["source_text"]} for s in source]
        processor = LLMProcessor(allow_llm=False)
        if anchors:
            try:
                processor.align_and_reorder(lines, anchors)
                review = processor.review
            except ScriptReviewRequired as exc:
                review = exc.review
            except ValueError as exc:
                review = {"entries": [], "unmatched": [{"script_idx": i, "text": line} for i, line in enumerate(lines)],
                          "extra_asr": [{"asr_idx": i} for i in range(len(anchors))], "conflicts": [str(exc)]}
        else:
            review = {"entries": [], "unmatched": [{"script_idx": i, "text": line} for i, line in enumerate(lines)],
                      "extra_asr": [], "conflicts": ["缺少原文时间锚点"]}
        positions = {cue["cue_id"]: idx for idx, cue in enumerate(segments)}
        matched_ids = set()
        by_id = {s["cue_id"]: dict(s) for s in segments}
        for cue in by_id.values():
            cue.pop("script_line", None)
        low_confidence = []
        matched = []
        for match in review["entries"]:
            cues = [source[i] for i in match["asr_indices"]]
            span = positions[cues[-1]["cue_id"]] - positions[cues[0]["cue_id"]] + 1
            if span != len(cues):
                review["unmatched"].append({"script_idx": match["script_idx"], "text": match["text"]})
                continue
            matched_ids.update(c["cue_id"] for c in cues)
            first = by_id[cues[0]["cue_id"]]
            first.update(source_text=match["text"], end=match["end"], script_line=match["script_idx"] + 1)
            first["translation"] = " ".join(c["translation"] for c in cues if c.get("translation"))
            for cue in cues[1:]:
                by_id.pop(cue["cue_id"])
            matched.append({"line": first["script_line"], "cue_id": first["cue_id"],
                            "start": first["start"], "end": first["end"]})
            scores = [c["confidence"] for c in cues if c.get("confidence") is not None]
            if scores:
                first["confidence"] = min(scores)
            if scores and min(scores) < 0.6:
                low_confidence.append({**matched[-1], "confidence": min(scores)})
        aligned = sorted(by_id.values(), key=lambda s: s["start"])
        for idx, cue in enumerate(aligned):
            cue["index"] = idx
        report = {"script_lines": list(lines), "matched": matched, "low_confidence": low_confidence,
                  "unmatched": [{"line": u["script_idx"] + 1, "text": u["text"]} for u in review["unmatched"]],
                  "extra_cue_ids": [cue["cue_id"] for cue in segments if cue["cue_id"] not in matched_ids],
                  "conflicts": review["conflicts"]}
        return aligned, report

    def _prepare(
        self,
        script_path,
        *,
        confirmed_text=None,
        fingerprint=None,
        track_index=None,
        vertical_mode="auto",
        use_llm_clean=False,
    ):
        if fingerprint and script_fingerprint(script_path) != fingerprint:
            raise ValueError("台本文件已改变，请重新预览并确认台词")
        preview = self.preview(
            script_path,
            track_index=track_index,
            vertical_mode=vertical_mode,
            use_llm_clean=use_llm_clean if confirmed_text is None else False,
        )
        text = preview["clean_text"] if confirmed_text is None else confirmed_text
        if not isinstance(text, str) or not text.strip():
            raise ValueError("确认后的台词为空")
        return text

    @staticmethod
    def _transcribe(audio_path, model_size, language):
        from src.core.engines.asr.service import AsrEngineRuntime
        from src.core.resources.model_reference import resolve_model_reference

        model_path = Path(resolve_model_reference(f"faster-whisper-{model_size}"))
        if not model_path.is_dir() or not (model_path / "model.bin").is_file():
            raise ValueError(
                "请先在模型管理中安装所选 Faster-Whisper 模型；不会自动下载"
            )
        document = AsrEngineRuntime().transcribe_file(
            input_path=str(audio_path),
            output_path=None,
            profile={
                "provider": "faster_whisper",
                "model": str(model_path),
                "common_options": {"language": language},
                "provider_options": {"preserve_segments": True, "vad_filter": False},
            },
        )
        if any(
            s.recognition_metadata.get("timestamp_source")
            in {"missing", "estimated", "proportional", "synthetic"}
            for s in document.segments
        ):
            raise ValueError("识别结果包含缺失或估算时间，请重新识别或人工核对")
        return [
            {"start": s.start, "end": s.end, "text": s.text} for s in document.segments
        ]

    def _match_and_save(
        self,
        text,
        anchors,
        output_path,
        fmt,
        cb,
        *,
        inputs=(),
        duration=None,
        use_llm_match=False,
        audio_path=None,
        language="ja",
    ):
        from src.core.engines.llm.script_cleaner import LLMProcessor

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        report = {
            "version": 1,
            "complete": False,
            "script_lines": lines,
            "entries": [],
            "asr_segments": anchors,
            "unmatched": [],
            "extra_asr": [],
            "conflicts": [],
            "audio_path": str(audio_path) if audio_path else None,
            "output_path": str(output_path),
            "language": language,
            "duration": duration,
            "timestamp_source": "transcript_segments",
        }
        review_path = str(Path(output_path).with_suffix(".review.json"))
        self.review_path = review_path
        cb("llm_align", 0, "正在核实录音时间锚点并匹配台词")
        try:
            validate_timed_entries(anchors, duration=duration)
            processor = LLMProcessor(
                allow_llm=use_llm_match,
                progress_callback=lambda n, total: cb(
                    "llm_align", int(n / total * 80), f"匹配第 {n + 1}/{total} 批"
                ),
            )
            entries = processor.align_and_reorder(lines, anchors)
            report.update(processor.review)
            validate_timed_entries(entries, duration=duration)
        except ScriptReviewRequired as exc:
            report.update(exc.review)
            report["draft_entries"] = anchors
            write_new_text(
                review_path,
                json.dumps(report, ensure_ascii=False, indent=2),
                inputs=inputs,
            )
            raise
        except Exception as exc:
            report["conflicts"].append(str(exc))
            write_new_text(
                review_path,
                json.dumps(report, ensure_ascii=False, indent=2),
                inputs=inputs,
            )
            raise
        write_new_text(
            review_path, json.dumps(report, ensure_ascii=False, indent=2), inputs=inputs
        )
        write_new_text(output_path, subtitle_content(entries, fmt), inputs=inputs)
        cb("llm_align", 100, f"已生成 {len(entries)} 段录音时间轴字幕，仍需试听核对")
        return str(output_path)

    def run(
        self,
        script_path,
        audio_path,
        output_path,
        fmt="vtt",
        use_llm_clean=False,
        asr_model_size="large-v3",
        asr_language="ja",
        track_index=None,
        vertical_mode="auto",
        progress_callback=None,
        debug_dir=None,
        confirmed_text=None,
        fingerprint=None,
        use_llm_match=False,
    ):
        cb = progress_callback or (lambda *args: None)
        cb("clean_script", 0, "正在准备确认稿")
        text = self._prepare(
            script_path,
            confirmed_text=confirmed_text,
            fingerprint=fingerprint,
            track_index=track_index,
            vertical_mode=vertical_mode,
            use_llm_clean=use_llm_clean,
        )
        cb("clean_script", 100, "台词已准备")
        cb("asr_recognize", 0, "正在识别录音")
        # Probe duration using the existing libsndfile helper; unsupported formats fail visibly.
        from src.core.subtitles.translation_reuse import audio_duration

        duration = audio_duration(str(audio_path))
        if duration is None:
            raise ValueError("无法核实录音时长，请先在音频工具中转为WAV")
        anchors = self._transcribe(audio_path, asr_model_size, asr_language)
        cb("asr_recognize", 100, f"识别返回 {len(anchors)} 个片段")
        return self._match_and_save(
            text,
            anchors,
            output_path,
            fmt,
            cb,
            inputs=(script_path, audio_path),
            duration=duration,
            use_llm_match=use_llm_match,
            audio_path=audio_path,
            language=asr_language,
        )

    def run_from_existing_vtt(
        self,
        script_path,
        vtt_path,
        output_path,
        fmt="vtt",
        use_llm_clean=False,
        track_index=None,
        vertical_mode="auto",
        progress_callback=None,
        debug_dir=None,
        confirmed_text=None,
        fingerprint=None,
        use_llm_match=False,
        audio_path=None,
        asr_language="ja",
    ):
        from src.core.subtitles.service import SubtitleDomainService

        cb = progress_callback or (lambda *args: None)
        cb("clean_script", 0, "正在准备确认稿")
        text = self._prepare(
            script_path,
            confirmed_text=confirmed_text,
            fingerprint=fingerprint,
            track_index=track_index,
            vertical_mode=vertical_mode,
            use_llm_clean=use_llm_clean,
        )
        cb("clean_script", 100, "台词已准备")
        if Path(vtt_path).suffix.lower() not in {".vtt", ".srt"}:
            raise ValueError("参考字幕需要VTT或SRT；LRC没有可信的结束时间")
        content = Path(vtt_path).read_text(encoding="utf-8")
        document = SubtitleDomainService().parse_text(
            content, Path(vtt_path).suffix[1:]
        )
        if sum("-->" in line for line in content.splitlines()) != len(
            document.segments
        ):
            raise ValueError("参考字幕包含无法解析或空白的片段，请先修正")
        anchors = [
            {"start": s.start, "end": s.end, "text": s.text} for s in document.segments
        ]
        duration = None
        if audio_path:
            from src.core.subtitles.translation_reuse import audio_duration

            duration = audio_duration(str(audio_path))
            if duration is None:
                raise ValueError("无法核实录音时长")
        return self._match_and_save(
            text,
            anchors,
            output_path,
            fmt,
            cb,
            inputs=(script_path, vtt_path, audio_path),
            duration=duration,
            use_llm_match=use_llm_match,
            audio_path=audio_path,
            language=asr_language,
        )

    def run_text_only(
        self,
        script_path,
        output_path=None,
        use_llm_clean=False,
        track_index=None,
        vertical_mode="auto",
        progress_callback=None,
        debug_dir=None,
        confirmed_text=None,
        fingerprint=None,
    ):
        cb = progress_callback or (lambda *args: None)
        cb("clean_script", 0, "正在整理台词")
        text = self._prepare(
            script_path,
            confirmed_text=confirmed_text,
            fingerprint=fingerprint,
            track_index=track_index,
            vertical_mode=vertical_mode,
            use_llm_clean=use_llm_clean,
        )
        if output_path:
            write_new_text(output_path, text, inputs=(script_path,))
        cb("clean_script", 100, "已整理台词（无时间轴）")
        return text
