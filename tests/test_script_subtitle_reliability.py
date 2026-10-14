"""Regression cases from short offline reproductions of the script tool."""

from pathlib import Path

import pytest

from src.core.engines.llm.script_cleaner import LLMProcessor
from src.core.subtitles.script_tool import ScriptToSubtitleTool
from src.core.subtitles.script_processor import ScriptProcessor
from src.core.subtitles.script_to_subtitle import ScriptToSubtitlePipeline
from src.core.subtitles.generator import SubtitleGenerator
from src.core.subtitles.loader import load_subtitle_with_timestamps

ANCHORS = [
    dict(start=1.25, end=2.5, text="one"),
    dict(start=3.125, end=4.25, text="two"),
]


class Reply(LLMProcessor):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def _call_llm(self, prompt, content):
        return self.value(content) if callable(self.value) else self.value


@pytest.mark.parametrize(
    "reply",
    [
        "not JSON",
        "[]",
        '[{"script_idx":0,"asr_idx":0,"text":"one"}]',
        '[{"script_idx":0,"asr_idx":0,"text":"译文"},{"script_idx":1,"asr_idx":1,"text":"two"}]',
        '[{"script_idx":0,"asr_idx":0},{"script_idx":1,"asr_idx":0}]',
    ],
)
def test_incomplete_or_untrustworthy_reply_requires_review(reply):
    with pytest.raises(ValueError):
        Reply(reply).align_and_reorder(["one", "two"], ANCHORS)


def test_empty_anchors_never_invent_ten_minutes(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text("Alice: one", encoding="utf-8")
    vtt = tmp_path / "empty.vtt"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    output = tmp_path / "out.vtt"
    with pytest.raises(ValueError):
        ScriptToSubtitlePipeline().run_from_existing_vtt(
            script, vtt, output, use_llm_clean=False
        )
    assert not output.exists()


def test_mapping_uses_original_text_real_anchor_and_recording_order():
    reply = '[{"script_idx":0,"asr_idx":1},{"script_idx":1,"asr_idx":0}]'
    result = Reply(reply).align_and_reorder(["two", "one"], ANCHORS)
    assert [(e["text"], e["start"], e["end"]) for e in result] == [
        ("one", 1.25, 2.5),
        ("two", 3.125, 4.25),
    ]


def test_unmatched_line_has_no_estimated_timestamps():
    reply = '[{"script_idx":0,"asr_idx":0},{"script_idx":1,"asr_idx":null}]'
    with pytest.raises(ValueError) as caught:
        Reply(reply).align_and_reorder(["one", "unspoken"], ANCHORS)
    assert caught.value.review["unmatched"][0]["text"] == "unspoken"
    assert caught.value.review["unmatched"][0].get("start") is None


def test_empty_speaker_and_body_marker_do_not_duplicate_or_erase():
    assert (
        ScriptToSubtitleTool.clean_script("Alice: First\nBob:\nSecond")
        == "First\nSecond"
    )
    assert (
        ScriptToSubtitleTool.clean_script("（以下、台本）\nこんにちは。\n元気ですか。")
        == "こんにちは。\n元気ですか。"
    )
    assert (
        ScriptProcessor.detect_scripts("第1話\n太郎：one\n第2話\n花子：two")[0]["title"]
        == "1"
    )


def test_long_cleaning_keeps_each_original_line_once():
    text = "\n".join(f"{i:02d}-" + "a" * 500 for i in range(10))
    assert Reply(lambda content: content).clean_script(text) == text


def test_fractional_lrc_roundtrips_text_and_centiseconds(tmp_path):
    output = tmp_path / "test.lrc"
    SubtitleGenerator.save(ANCHORS, str(output), fmt="lrc")
    result = load_subtitle_with_timestamps(str(output))
    assert [e["text"] for e in result] == ["one", "two"]
    assert result[0]["start"] == pytest.approx(1.25, abs=0.01)


def test_bad_chapter_and_output_collision_stop_before_write(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text("Alice: one", encoding="utf-8")
    with pytest.raises(ValueError):
        ScriptToSubtitlePipeline().run_text_only(
            script, use_llm_clean=False, track_index=1
        )
    with pytest.raises(ValueError):
        ScriptToSubtitlePipeline().run_text_only(script, script, use_llm_clean=False)
    assert script.read_text(encoding="utf-8") == "Alice: one"


def test_each_real_task_has_immutable_output(tmp_path):
    import time
    from src.app.dto.script_subtitle import ScriptSubtitleRequest
    from src.app.services.script_subtitle_service import ScriptSubtitleService
    from src.app.services.task_service import TaskService
    from src.app.services.artifact_service import ArtifactService
    from src.core.tasks import TaskDispatcher

    tasks = TaskService()
    artifacts = ArtifactService()
    service = ScriptSubtitleService(
        task_service=tasks,
        dispatcher=TaskDispatcher(tasks.registry, task_service=tasks),
        artifact_service=artifacts,
    )
    script = tmp_path / "script.txt"
    script.write_text("Alice: one", encoding="utf-8")

    def run():
        accepted = service.create_task(
            ScriptSubtitleRequest(script_path=str(script), use_llm_clean=False)
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = tasks.get_task(accepted.task_id)
            if status.state in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert status.state == "completed", status.error
        return Path(artifacts.get_task_artifacts(status.task_id).entries[0].path)

    first = run()
    script.write_text("Alice: two", encoding="utf-8")
    second = run()
    assert first != second
    assert first.read_text(encoding="utf-8") == "one"
    assert second.read_text(encoding="utf-8") == "two"


@pytest.mark.parametrize(
    "anchors",
    [
        [],
        [dict(start=-1, end=2, text="one")],
        [dict(start=0, end=float("nan"), text="one")],
        [dict(start=1, end=2, text="one"), dict(start=1.5, end=3, text="two")],
    ],
)
def test_invalid_recording_anchors_stop_before_llm(anchors):
    processor = Reply(
        lambda _: pytest.fail("Invalid anchors must stop before external calls")
    )
    with pytest.raises(ValueError):
        processor.align_and_reorder(["one"], anchors)


def test_preview_actions_fingerprint_and_changed_file(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text("太郎：（笑う）こんにちは。", encoding="utf-8")
    pipeline = ScriptToSubtitlePipeline()
    preview = pipeline.preview(script)
    assert preview["clean_text"] == "こんにちは。"
    assert "（笑う）" in preview["actions"]
    script.write_text("太郎：変わった。", encoding="utf-8")
    with pytest.raises(ValueError, match="改变"):
        pipeline.run_text_only(
            script,
            use_llm_clean=False,
            confirmed_text=preview["clean_text"],
            fingerprint=preview["fingerprint"],
        )


def test_actions_only_preview_can_be_restored_but_empty_text_cannot_export(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text("（朗读这一句）", encoding="utf-8")
    pipeline = ScriptToSubtitlePipeline()
    preview = pipeline.preview(script)
    assert preview["clean_text"] == ""
    assert preview["actions"] == ["（朗读这一句）"]
    with pytest.raises(ValueError, match="台词为空"):
        pipeline.run_text_only(script, tmp_path / "out.txt")


def test_incomplete_real_task_registers_review_without_subtitle(tmp_path):
    import time
    import wave
    from src.app.dto.script_subtitle import ScriptSubtitleRequest
    from src.app.services.script_subtitle_service import ScriptSubtitleService
    from src.app.services.task_service import TaskService
    from src.app.services.artifact_service import ArtifactService
    from src.core.tasks import TaskDispatcher

    tasks = TaskService()
    artifacts = ArtifactService()
    service = ScriptSubtitleService(
        task_service=tasks,
        dispatcher=TaskDispatcher(tasks.registry, task_service=tasks),
        artifact_service=artifacts,
    )
    script = tmp_path / "script.txt"
    script.write_text("Alice: one\nBob: not spoken", encoding="utf-8")
    audio = tmp_path / "recording.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\x00\x00" * 16000 * 5)
    preview = service.preview(ScriptSubtitleRequest(script_path=str(script)))
    reference = tmp_path / "source.vtt"
    reference.write_text(
        "WEBVTT\n\n00:00:01.250 --> 00:00:02.500\none\n", encoding="utf-8"
    )
    accepted = service.create_task(
        ScriptSubtitleRequest(
            script_path=str(script),
            vtt_path=str(reference),
            reference_confirmed=True,
            audio_path=str(audio),
            confirmed_text=preview["clean_text"],
            fingerprint=preview["fingerprint"],
            asr_language="en",
        )
    )
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = tasks.get_task(accepted.task_id)
        if status.state in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert status.state == "failed"
    records = artifacts.get_task_artifacts(status.task_id).entries
    assert [a.artifact_type for a in records] == ["analysis.script_review"]
    review = service.review(status.task_id)
    assert review["unmatched"] == [{"script_idx": 1, "text": "not spoken"}]
    assert not Path(review["output_path"]).exists()
    assert review["draft_entries"] == [dict(start=1.25, end=2.5, text="one")]


def test_unified_tool_preserves_short_anchor_and_rejects_missing_lines():
    tool = ScriptToSubtitleTool()
    anchors = [dict(start=1.25, end=1.4, text="one")]
    assert tool.align_with_asr("one", anchors, 5)[0]["end"] == 1.4
    with pytest.raises(ValueError):
        tool.align_with_asr("one\nmissing", anchors, 5)


def test_timed_backend_requires_confirmed_dialogue_and_recording(tmp_path):
    from src.app.dto.script_subtitle import ScriptSubtitleRequest
    from src.app.services.script_subtitle_service import ScriptSubtitleService
    from src.app.errors import AppValidationError
    from src.core.subtitles.script_review import script_fingerprint

    script = tmp_path / "script.txt"
    script.write_text("one", encoding="utf-8")
    service = ScriptSubtitleService()
    with pytest.raises(AppValidationError, match="确认台词"):
        service.validate_confirmed_request(
            ScriptSubtitleRequest(script_path=str(script), audio_path="recording.wav")
        )
    with pytest.raises(AppValidationError, match="对应录音"):
        service.validate_confirmed_request(
            ScriptSubtitleRequest(
                script_path=str(script),
                vtt_path="reference.vtt",
                reference_confirmed=True,
                confirmed_text="one",
                fingerprint=script_fingerprint(script),
            )
        )


def test_unified_tool_refuses_overwrite_of_source_or_previous_result(tmp_path):
    source = tmp_path / "script.txt"
    source.write_text("one", encoding="utf-8")
    anchors = [dict(start=1.25, end=1.4, text="one")]
    with pytest.raises(ValueError, match="已存在"):
        ScriptToSubtitleTool.process(source, anchors, 5, output_path=source)
    assert source.read_text(encoding="utf-8") == "one"
    output = tmp_path / "out.srt"
    ScriptToSubtitleTool.process(source, anchors, 5, output_path=output)
    original = output.read_bytes()
    with pytest.raises(ValueError, match="已存在"):
        ScriptToSubtitleTool.process(source, anchors, 5, output_path=output)
    assert output.read_bytes() == original
