"""End-to-end offline tests for Two-Phase DraftSession, FastAPI `/api/v1/drafts`, and MCP stdio server."""

from __future__ import annotations

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np
import pytest
import soundfile as sf
import yaml

from packages.mcp_server import MCP_PROTOCOL_VERSION, McpStdioServer, McpToolRegistry
from src.api.http import dependencies
from src.api.http.app import create_app
from src.app.dto import SubtitleSegment as DtoSubtitleSegment, TranscriptionResult, TranslationResult
from src.app.persistence.draft_store import DraftConflictError, DraftStore
from src.app.persistence.state_store import SqliteStateStore
from src.app.services.artifact_service import ArtifactService
from src.app.services.draft_session_service import DraftSessionService
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.core.speech.providers import get_provider
from src.core.speech.store import SpeechStore
from src.core.subtitles.parser import SubtitleParser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_stereo_wav(path: Path, *, duration_sec: float = 12.0, sample_rate: int = 24000) -> Path:
    """Create a deterministic stereo WAV with quiet background and high-SNR speech window [2s, 9s]."""
    path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(round(duration_sec * sample_rate))
    t = np.arange(total_frames, dtype=np.float32) / sample_rate
    # Low noise floor everywhere
    left = (0.002 * np.sin(2.0 * np.pi * 110.0 * t)).astype(np.float32)
    right = (0.002 * np.cos(2.0 * np.pi * 110.0 * t)).astype(np.float32)
    # Clean voice-like burst between 2.0s and 9.0s (7s clean window -> highest SNR)
    s0, s1 = int(2.0 * sample_rate), min(total_frames, int(9.0 * sample_rate))
    carrier = (0.25 * np.sin(2.0 * np.pi * 220.0 * t[s0:s1])).astype(np.float32)
    left[s0:s1] += carrier
    right[s0:s1] += carrier * 0.8
    stereo = np.stack([left, right], axis=1)
    sf.write(str(path), stereo, sample_rate, subtype="PCM_16")
    return path


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide isolated SQLite DraftStore + SpeechService + offline Edge TTS synthesizer."""
    data_dir = tmp_path / "app_data"
    db_path = data_dir / "state.sqlite3"
    voice_lab_dir = data_dir / "voice_lab"
    monkeypatch.setenv("ASMR_HELPER_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ASMR_HELPER_STATE_DB", str(db_path))
    monkeypatch.setenv("ASMR_HELPER_VOICE_LAB_DIR", str(voice_lab_dir))

    state_store = SqliteStateStore(db_path)
    draft_store = DraftStore(state_store=state_store)
    tasks = TaskService(state_store=state_store)
    artifacts = ArtifactService(state_store=state_store)
    speech_svc = SpeechService(
        store=SpeechStore(voice_lab_dir),
        tasks=tasks,
        artifacts=artifacts,
    )

    tts_calls: list[dict] = []

    def _offline_synthesize(request, output_path, context, cancel_check):
        tts_calls.append(deepcopy(request))
        sr = 24000
        # ~0.6s clean sine tone per cue
        frames = int(sr * 0.6)
        tone = (0.12 * np.sin(2.0 * np.pi * 330.0 * (np.arange(frames, dtype=np.float32) / sr))).astype(
            np.float32
        )
        sf.write(str(output_path), tone, sr, subtype="PCM_16")
        return {"model": request["model"], "sample_rate": sr}

    monkeypatch.setattr(get_provider("edge"), "synthesize", _offline_synthesize)

    service = DraftSessionService(
        store=draft_store,
        speech_service=speech_svc,
        artifact_service=artifacts,
    )
    return SimpleNamespace(
        tmp_path=tmp_path,
        db_path=db_path,
        draft_store=draft_store,
        speech_svc=speech_svc,
        service=service,
        tts_calls=tts_calls,
    )


# ─── 1. DraftStore & Optimistic Concurrency ───────────────────────────────


def test_draft_store_crud_and_optimistic_concurrency(isolated_env):
    store: DraftStore = isolated_env.draft_store
    created = store.create_draft(
        draft_id="draft-unit-001",
        state="preparing",
        work_dir="/works/RJ000001",
        title="Whisper Track 01",
        tracks=[{"track_id": "track-01", "path": "/works/RJ000001/01.wav"}],
        segments=[{"index": 0, "start": 0.0, "end": 1.5, "source_text": "おはよう", "translation": "早安"}],
        voice_plan={"provider_id": "edge"},
        audit_report={"gate_passed": True},
        artifacts={},
    )
    assert created.revision == 1
    assert created.state == "preparing"

    updated = store.update_draft(
        "draft-unit-001",
        expected_revision=1,
        state="awaiting_review",
    )
    assert updated.revision == 2
    assert updated.state == "awaiting_review"

    # Stale expected_revision must fail with DraftConflictError
    with pytest.raises(DraftConflictError, match="revision conflict"):
        store.update_draft("draft-unit-001", expected_revision=1, title="Stale Edit")

    listed = store.list_drafts(state="awaiting_review")
    assert [d.draft_id for d in listed] == ["draft-unit-001"]


# ─── 2. inspect_work Stem Auto-Pairing ────────────────────────────────────


def test_inspect_work_discovers_and_auto_pairs_stems(isolated_env):
    work_dir = isolated_env.tmp_path / "RJ123456_EarCleaning"
    _write_stereo_wav(work_dir / "01_whisper.wav", duration_sec=10.0, sample_rate=48000)
    _write_stereo_wav(work_dir / "01_whisper_no_se.wav", duration_sec=10.0, sample_rate=48000)
    _write_stereo_wav(work_dir / "01_whisper_se_only.wav", duration_sec=10.0, sample_rate=48000)
    (work_dir / "01_whisper.ja.srt").write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nこんばんは、ゆっくり休んでね\n",
        encoding="utf-8",
    )
    (work_dir / "01_whisper_script.txt").write_text("こんばんは、ゆっくり休んでね\n", encoding="utf-8")
    (work_dir / "booklet_script.pdf").write_bytes(b"%PDF-1.4 mock script")

    info = isolated_env.service.inspect_work(work_dir)
    assert info["work_dir"] == str(work_dir.resolve())
    assert info["readiness"]["has_audio"] is True
    assert info["readiness"]["track_count"] == 1
    assert info["readiness"]["has_source_subtitles"] is True
    assert info["readiness"]["has_scripts"] is True
    assert info["readiness"]["has_clean_vocal_or_no_se_stem"] is True
    assert info["readiness"]["recommended_mode"] == "translate_existing_subtitle"

    track = info["tracks"][0]
    assert Path(track["path"]).name == "01_whisper.wav"
    assert track["sample_rate"] == 48000
    assert track["channels"] == 2
    assert pytest.approx(track["duration"], rel=1e-2) == 10.0
    assert Path(track["paired_stems"]["no_se"]).name == "01_whisper_no_se.wav"
    assert Path(track["paired_stems"]["se_only"]).name == "01_whisper_se_only.wav"
    assert len(track["paired_subtitles"]) == 1
    assert track["paired_subtitles"][0]["language"] == "ja"
    assert any(Path(p).name == "01_whisper_script.txt" for p in track["paired_scripts"])


# ─── 3. prepare_draft -> patch_draft -> commit_draft + Take Reuse ─────────


def test_two_phase_draft_gate_audit_patch_commit_and_take_reuse(isolated_env):
    work_dir = isolated_env.tmp_path / "work_two_phase"
    _write_stereo_wav(work_dir / "track01.wav", duration_sec=12.0, sample_rate=24000)
    sub_path = work_dir / "track01.srt"

    # Cue 0: 0.0 -> 1.2s, next starts at 1.4s -> natural=1.2s, slack=0.14s, effective=1.34s.
    #        26 Chinese chars -> 26 / 4.2 = 6.19s -> predicted_atempo = 4.62x > 1.35x (OVER SPEED!)
    # Cue 1: 1.4 -> 3.4s -> translation has Japanese kana residue ("ですね")!
    # Cue 2: 3.6 -> 5.2s -> Japanese only, missing Chinese translation (UNTRANSLATED!)
    # Cue 3: 5.5 -> 6.5s, next starts at 11.5s -> 5s post-cue silence slack!
    #        16 Chinese chars -> 16 / 4.2 = 3.81s, effective_slot = 1.0 + 4.94 = 5.94s -> atempo = 1.0x (NOT over-speed thanks to slack!)
    # Cue 4: 11.5 -> 11.9s -> symbol-only ("♪〜") -> empty_or_symbol_indices!
    sub_path.write_text(
        "\n\n".join(
            [
                "1\n00:00:00,000 --> 00:00:01,200\nこんばんは\n今天晚上就让我一直陪在你耳边轻声细语地哄你入睡好不好呀",
                "2\n00:00:01,400 --> 00:00:03,400\nいい天気ですね\n今天天气真好ですね",
                "3\n00:00:03,600 --> 00:00:05,200\nおやすみなさい",
                "4\n00:00:05,500 --> 00:00:06,500\n大好きだよ\n我一直都最喜欢最喜欢温柔的你啦",
                "5\n00:00:11,500 --> 00:00:11,900\n♪〜",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    draft = isolated_env.service.prepare_draft(
        work_dir,
        enable_translation=False,
        extract_voice_reference=True,
    )

    # Phase 1 MUST halt at awaiting_review without synthesizing full-track TTS
    assert draft["state"] == "awaiting_review"
    assert draft["revision"] == 1
    assert len(isolated_env.tts_calls) == 0

    audit = draft["audit_report"]
    assert audit["gate_passed"] is False
    assert audit["untranslated_indices"] == [2]
    assert audit["japanese_residue_indices"] == [1]
    assert audit["empty_or_symbol_indices"] == [4]
    assert [c["index"] for c in audit["over_speed_cues"]] == [0]
    assert audit["over_speed_cues"][0]["predicted_atempo"] > 1.35
    assert audit["over_speed_cues"][0]["max_recommended_chars"] >= 5

    # Clean voice reference candidate extracted from highest-SNR 6-10s window
    ref_cand = draft["voice_plan"]["reference_candidate"]
    assert Path(ref_cand["path"]).is_file()
    assert 6.0 <= ref_cand["duration"] <= 10.0
    assert ref_cand["snr_db"] > 10.0

    # Patch draft to fix over-speed cue 0, residue cue 1, and untranslated cue 2
    patched = isolated_env.service.patch_draft(
        draft["draft_id"],
        edits=[
            {"index": 0, "translation": "今晚陪你入睡吧"},
            {"index": 1, "translation": "今天天气真好呢"},
            {"index": 2, "translation": "晚安好梦"},
        ],
        voice_plan_patch={"provider_id": "edge", "voice": "zh-CN-XiaoxiaoNeural"},
        expected_revision=1,
    )
    assert patched["state"] == "awaiting_review"
    assert patched["revision"] == 2
    assert patched["audit_report"]["over_speed_cues"] == []
    assert patched["audit_report"]["japanese_residue_indices"] == []
    assert patched["audit_report"]["untranslated_indices"] == []
    assert patched["audit_report"]["gate_passed"] is True

    # Stale revision check on patch must fail
    with pytest.raises(DraftConflictError):
        isolated_env.service.patch_draft(
            draft["draft_id"],
            edits=[{"index": 0, "translation": "冲突修改"}],
            expected_revision=1,
        )

    # Commit Phase 2: exports .srt & .lrc and synthesizes + mixes audio
    output_dir = isolated_env.tmp_path / "committed_out"
    committed = isolated_env.service.commit_draft(
        draft["draft_id"],
        output_dir,
        export_formats=("srt", "lrc"),
        enable_dubbing=True,
        expected_revision=2,
    )
    assert committed["state"] == "completed"
    assert len(isolated_env.tts_calls) == 4  # 4 speakable cues (Cue 4 symbol-only skipped)
    assert committed["artifacts"]["dubbing"]["synthesized_take_count"] == 4
    assert committed["artifacts"]["dubbing"]["reused_take_count"] == 0

    srt_file = Path(committed["artifacts"]["subtitles"]["srt"])
    lrc_file = Path(committed["artifacts"]["subtitles"]["lrc"])
    mixed_wav = Path(committed["artifacts"]["mixed_audio_path"])
    assert srt_file.is_file()
    assert lrc_file.is_file()
    assert mixed_wav.is_file()

    lrc_text = lrc_file.read_text(encoding="utf-8")
    assert "[00:00.00]こんばんは / 今晚陪你入睡吧" in lrc_text
    assert "[00:01.40]いい天気ですね / 今天天气真好呢" in lrc_text
    parsed_srt = SubtitleParser().parse_text(srt_file.read_text(encoding="utf-8"), "srt")
    assert len(parsed_srt.segments) == 5
    mixed_info = sf.info(str(mixed_wav))
    assert mixed_info.channels == 2
    assert mixed_info.duration == pytest.approx(12.0, abs=0.25)

    # Patch ONLY 1 cue (index 2) and re-commit -> 3 unchanged takes MUST be reused!
    repatched = isolated_env.service.patch_draft(
        draft["draft_id"],
        edits=[{"index": 2, "translation": "祝你做个甜甜的梦"}],
        expected_revision=committed["revision"],
    )
    assert repatched["state"] == "awaiting_review"

    isolated_env.tts_calls.clear()
    recommitted = isolated_env.service.commit_draft(
        draft["draft_id"],
        output_dir / "v2",
        export_formats=("srt", "lrc"),
        enable_dubbing=True,
        expected_revision=repatched["revision"],
    )
    assert recommitted["state"] == "completed"
    assert len(isolated_env.tts_calls) == 1  # Only the 1 modified cue was synthesized!
    assert recommitted["artifacts"]["dubbing"]["reused_take_count"] == 3
    assert recommitted["artifacts"]["dubbing"]["synthesized_take_count"] == 1


def test_prepare_draft_runs_asr_and_llm_when_no_subtitles_exist(isolated_env):
    work_dir = isolated_env.tmp_path / "work_asr_llm"
    _write_stereo_wav(work_dir / "ep01.wav", duration_sec=8.0)
    _write_stereo_wav(work_dir / "ep01_no_se.wav", duration_sec=8.0)

    asr_inputs: list[str] = []

    class StubAsrService:
        def transcribe_file(self, *, input_path: str, **kwargs):
            asr_inputs.append(input_path)
            return TranscriptionResult(
                segments=[
                    DtoSubtitleSegment(start=0.5, end=2.5, text="おかえりなさい"),
                    DtoSubtitleSegment(start=3.0, end=5.5, text="今日も頑張ったね"),
                ],
                output_path=None,
                text="おかえりなさい\n今日も頑張ったね",
            )

    class StubLlmService:
        def translate_texts(self, *, texts: list[str], **kwargs):
            mapping = {
                "おかえりなさい": "欢迎回家",
                "今日も頑張ったね": "今天也很努力呢",
            }
            return TranslationResult(
                items=[mapping[t] for t in texts],
                provider="stub-llm",
                source_lang="ja",
                target_lang="zh",
            )

    svc = DraftSessionService(
        store=isolated_env.draft_store,
        asr_service=StubAsrService(),
        llm_service=StubLlmService(),
        speech_service=isolated_env.speech_svc,
    )
    draft = svc.prepare_draft(work_dir, sample_cue_count=1)
    assert draft["state"] == "awaiting_review"
    # Preferred clean `no_se` stem for ASR
    assert Path(asr_inputs[0]).name == "ep01_no_se.wav"
    assert [s["translation"] for s in draft["segments"]] == ["欢迎回家", "今天也很努力呢"]
    assert draft["audit_report"]["gate_passed"] is True
    # Sample cue synthesized ONLY 1 cue (not all 2 cues)
    assert len(draft["artifacts"]["sample_takes"]) == 1
    assert len(isolated_env.tts_calls) == 1


# ─── 4. FastAPI `/api/v1/drafts/*` TestClient Flow ────────────────────────


def test_fastapi_draft_routes_end_to_end(isolated_env):
    work_dir = isolated_env.tmp_path / "http_work"
    _write_stereo_wav(work_dir / "scene1.wav", duration_sec=6.0)
    (work_dir / "scene1.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,200\nこんにちは\n你好呀今天也是超级无敌漫长的一整段话肯定会超过语速上限的喔\n"
        "2\n00:00:02,000 --> 00:00:04,500\nありがとう\n非常感谢你\n",
        encoding="utf-8",
    )

    app = create_app()
    app.dependency_overrides[dependencies.draft_session_service] = lambda: isolated_env.service
    try:
        with TestClient(app) as client:
            inspect_resp = client.post("/api/v1/drafts/inspect", json={"path_or_dir": str(work_dir)})
            assert inspect_resp.status_code == 200
            assert inspect_resp.json()["readiness"]["track_count"] == 1

            prep_resp = client.post(
                "/api/v1/drafts/prepare",
                json={"path_or_dir": str(work_dir), "enable_translation": False},
            )
            assert prep_resp.status_code == 200
            draft = prep_resp.json()
            draft_id = draft["draft_id"]
            assert draft["state"] == "awaiting_review"
            assert draft["audit_report"]["gate_passed"] is False

            list_resp = client.get("/api/v1/drafts")
            assert list_resp.status_code == 200
            assert any(item["draft_id"] == draft_id for item in list_resp.json()["drafts"])

            slash_list_resp = client.get("/api/v1/drafts/")
            assert slash_list_resp.status_code == 200

            get_resp = client.get(f"/api/v1/drafts/{draft_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["draft_id"] == draft_id

            missing_resp = client.get("/api/v1/drafts/draft-missing-id")
            assert missing_resp.status_code == 404
            assert missing_resp.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

            bad_inspect = client.post("/api/v1/drafts/inspect", json={"path_or_dir": str(work_dir / "missing")})
            assert bad_inspect.status_code == 400
            assert bad_inspect.json()["error"]["code"] == "VALIDATION_ERROR"

            audit_resp = client.get(f"/api/v1/drafts/{draft_id}/audit")
            assert audit_resp.status_code == 200
            assert len(audit_resp.json()["over_speed_cues"]) == 1

            # Revision conflict returns HTTP 409
            conflict_resp = client.patch(
                f"/api/v1/drafts/{draft_id}",
                json={"edits": [{"index": 0, "translation": "你好呀"}], "expected_revision": 99},
            )
            assert conflict_resp.status_code == 409
            assert conflict_resp.json()["error"]["code"] == "REVISION_CONFLICT"

            patch_resp = client.patch(
                f"/api/v1/drafts/{draft_id}",
                json={"edits": [{"index": 0, "translation": "你好呀"}], "expected_revision": 1},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["revision"] == 2
            assert patch_resp.json()["audit_report"]["gate_passed"] is True

            out_dir = isolated_env.tmp_path / "http_out"
            commit_resp = client.post(
                f"/api/v1/drafts/{draft_id}/commit",
                json={
                    "output_dir": str(out_dir),
                    "export_formats": ["srt", "vtt", "lrc"],
                    "enable_dubbing": False,
                    "expected_revision": 2,
                },
            )
            assert commit_resp.status_code == 200
            committed = commit_resp.json()
            assert committed["state"] == "completed"
            for fmt in ("srt", "vtt", "lrc"):
                assert Path(committed["artifacts"]["subtitles"][fmt]).is_file()
    finally:
        app.dependency_overrides.clear()


# ─── 5. MCP JSON-RPC 2.0 Stdio Server Roundtrip ───────────────────────────


def test_mcp_in_memory_tools_and_error_handling(isolated_env):
    registry = McpToolRegistry(
        draft_service=isolated_env.service,
        speech_service=isolated_env.speech_svc,
    )
    server = McpStdioServer(registry=registry)

    # 1. initialize
    init_resp = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init_resp["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION

    # 2. notifications/initialized emits NO response
    notif_resp = server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notif_resp is None

    # 3. ping
    ping_resp = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping_resp == {"jsonrpc": "2.0", "id": 2, "result": {}}

    # 4. tools/list
    tools_resp = server.handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    tool_names = [t["name"] for t in tools_resp["result"]["tools"]]
    assert tool_names == [
        "asmr_inspect_work",
        "asmr_prepare_draft",
        "asmr_get_draft_audit",
        "asmr_patch_draft",
        "asmr_commit_draft",
        "asmr_list_voices_and_presets",
    ]

    # 5. asmr_list_voices_and_presets
    voices_resp = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "asmr_list_voices_and_presets", "arguments": {"include_providers": True}},
        }
    )
    assert voices_resp["result"]["isError"] is False
    voices_payload = json.loads(voices_resp["result"]["content"][0]["text"])
    assert any(p["provider_id"] == "edge" for p in voices_payload["providers"])

    # 6. Error handling: unknown method, unknown tool, domain not-found, parse error
    unknown_method = server.handle_message({"jsonrpc": "2.0", "id": 5, "method": "nonexistent/method"})
    assert unknown_method["error"]["code"] == -32601

    unknown_tool = server.handle_message(
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "asmr_unknown"}}
    )
    assert unknown_tool["error"]["code"] == -32602

    missing_draft = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "asmr_get_draft_audit", "arguments": {"draft_id": "draft-does-not-exist"}},
        }
    )
    assert missing_draft["result"]["isError"] is True
    assert missing_draft["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"

    parse_err = server.handle_json_line("{not valid json")
    assert parse_err["error"]["code"] == -32700

    # 7. serve_stdio stream roundtrip with print-pollution immunity
    work_dir = isolated_env.tmp_path / "mcp_stdio_work"
    _write_stereo_wav(work_dir / "ch01.wav", duration_sec=5.0)
    (work_dir / "ch01.srt").write_text(
        "1\n00:00:00,500 --> 00:00:03,500\nおやすみ\n晚安好梦\n",
        encoding="utf-8",
    )
    out_dir = isolated_env.tmp_path / "mcp_stdio_out"

    requests_lines = [
        json.dumps({"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "asmr_prepare_draft",
                    "arguments": {"path_or_dir": str(work_dir), "enable_translation": False},
                },
            }
        ),
    ]
    stdin_buf = io.StringIO("\n".join(requests_lines) + "\n")
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    assert server.serve_stdio(stdin=stdin_buf, stdout=stdout_buf, stderr=stderr_buf) == 0

    output_lines = [line for line in stdout_buf.getvalue().splitlines() if line.strip()]
    assert len(output_lines) == 2  # initialize + prepare_draft (notification omitted)
    prep_rpc = json.loads(output_lines[1])
    draft_data = prep_rpc["result"]["structuredContent"]
    assert draft_data["state"] == "awaiting_review"

    # Commit with dubbing via stdio and verify Mixer's print() goes to stderr, NOT stdout!
    commit_in = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "asmr_commit_draft",
                    "arguments": {
                        "draft_id": draft_data["draft_id"],
                        "output_dir": str(out_dir),
                        "export_formats": ["srt", "lrc"],
                        "enable_dubbing": True,
                    },
                },
            }
        )
        + "\n"
    )
    commit_out = io.StringIO()
    commit_err = io.StringIO()
    assert server.serve_stdio(stdin=commit_in, stdout=commit_out, stderr=commit_err) == 0
    commit_lines = [line for line in commit_out.getvalue().splitlines() if line.strip()]
    assert len(commit_lines) == 1
    commit_rpc = json.loads(commit_lines[0])
    assert commit_rpc["result"]["isError"] is False
    assert commit_rpc["result"]["structuredContent"]["state"] == "completed"
    assert "[Mixer]" in commit_err.getvalue()


def test_mcp_server_subprocess_stdio_roundtrip(tmp_path: Path):
    """Spawn real `python -m packages.mcp_server.server` process and run MCP JSON-RPC roundtrip."""
    work_dir = tmp_path / "subproc_work"
    _write_stereo_wav(work_dir / "track_a.wav", duration_sec=4.0)
    (work_dir / "track_a.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,000\nねえねえ\n喂喂我现在要说一段特别特别长的话让你触发超速预警提示\n"
        "2\n00:00:01,500 --> 00:00:03,500\n好きだよ\n最喜欢你啦\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "subproc_out"
    data_dir = tmp_path / "subproc_data"

    env = dict(os.environ)
    existing_py_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{PROJECT_ROOT}{os.pathsep}{existing_py_path}" if existing_py_path else str(PROJECT_ROOT)
    )
    env["ASMR_HELPER_DATA_DIR"] = str(data_dir)
    env["ASMR_HELPER_STATE_DB"] = str(data_dir / "state.sqlite3")
    env["ASMR_HELPER_VOICE_LAB_DIR"] = str(data_dir / "voice_lab")

    proc = subprocess.Popen(
        [sys.executable, "-m", "packages.mcp_server.server"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    def _rpc(msg: dict) -> dict:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        assert line, f"MCP subprocess exited unexpectedly: {proc.stderr.read() if proc.stderr else ''}"
        return json.loads(line)

    try:
        init_res = _rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init_res["result"]["protocolVersion"] == "2024-11-05"

        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        tools_res = _rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert len(tools_res["result"]["tools"]) == 6

        inspect_res = _rpc(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "asmr_inspect_work", "arguments": {"path_or_dir": str(work_dir)}},
            }
        )
        assert inspect_res["result"]["isError"] is False

        prep_res = _rpc(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "asmr_prepare_draft",
                    "arguments": {"path_or_dir": str(work_dir), "enable_translation": False},
                },
            }
        )
        draft = prep_res["result"]["structuredContent"]
        draft_id = draft["draft_id"]
        assert draft["state"] == "awaiting_review"
        assert len(draft["audit_report"]["over_speed_cues"]) == 1

        audit_res = _rpc(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "asmr_get_draft_audit",
                    "arguments": {"draft_id": draft_id, "include_segments": True},
                },
            }
        )
        assert audit_res["result"]["structuredContent"]["over_speed_cues"][0]["index"] == 0

        patch_res = _rpc(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "asmr_patch_draft",
                    "arguments": {
                        "draft_id": draft_id,
                        "edits": [{"index": 0, "translation": "喂喂"}],
                        "expected_revision": 1,
                    },
                },
            }
        )
        patched = patch_res["result"]["structuredContent"]
        assert patched["audit_report"]["gate_passed"] is True

        commit_res = _rpc(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "asmr_commit_draft",
                    "arguments": {
                        "draft_id": draft_id,
                        "output_dir": str(out_dir),
                        "export_formats": ["srt", "lrc"],
                        "enable_dubbing": False,
                        "expected_revision": patched["revision"],
                    },
                },
            }
        )
        committed = commit_res["result"]["structuredContent"]
        assert committed["state"] == "completed"
        assert Path(committed["artifacts"]["subtitles"]["lrc"]).is_file()
        assert Path(committed["artifacts"]["subtitles"]["srt"]).is_file()
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=15)
    assert proc.returncode == 0


# ─── 6. Skill & Preferences Config Validation ─────────────────────────────


def test_skill_frontmatter_and_preferences_template_are_valid():
    skill_path = PROJECT_ROOT / "skills" / "asmr-producer" / "SKILL.md"
    prefs_path = PROJECT_ROOT / "config" / "agent_preferences.example.yaml"
    assert skill_path.is_file()
    assert prefs_path.is_file()
    assert not (PROJECT_ROOT / "packages" / "__init__.py").exists()

    skill_text = skill_path.read_text(encoding="utf-8")
    assert skill_text.startswith("---\n")
    _, frontmatter_raw, body = skill_text.split("---", 2)
    frontmatter = yaml.safe_load(frontmatter_raw)
    assert frontmatter["name"] == "asmr-producer"
    assert isinstance(frontmatter.get("description"), str) and frontmatter["description"].strip()
    for tool_name in (
        "asmr_inspect_work",
        "asmr_prepare_draft",
        "asmr_get_draft_audit",
        "asmr_patch_draft",
        "asmr_commit_draft",
        "asmr_list_voices_and_presets",
    ):
        assert tool_name in body

    prefs = yaml.safe_load(prefs_path.read_text(encoding="utf-8"))
    assert "library_roots" in prefs
    assert "translation_style" in prefs
    assert "voice_preferences" in prefs
    assert "compute" in prefs


def test_saved_voicelab_recipe_and_sample_take_reuse_on_commit(isolated_env):
    """Verify saved VoiceLab recipe_id selection and automatic reuse of Phase-1 sample takes in Phase-2."""
    speech_svc: SpeechService = isolated_env.speech_svc
    conn = speech_svc.save_connection({"name": "Edge Cloud", "provider_id": "edge", "deployment": "cloud"})
    voice = speech_svc.store.create("voices", {"name": "Whisper Voice", "bindings": []})
    recipe = speech_svc.save_recipe(
        {
            "name": "Gentle Xiaoxiao",
            "voice_id": voice["id"],
            "provider_id": "edge",
            "model": "edge-tts",
            "mode": "builtin",
            "connection_ref": conn["id"],
            "variant": {"kind": "builtin", "value": "zh-CN-XiaoxiaoNeural", "style": "normal"},
            "language": "zh",
            "provider_options": {"schema_version": 1, "speed": 1},
        }
    )

    work_dir = isolated_env.tmp_path / "RJ999999 【耳かき】ささやき"
    _write_stereo_wav(work_dir / "01_ささやき.wav", duration_sec=6.0)
    (work_dir / "01_ささやき.srt").write_text(
        "1\n00:00:00,500 --> 00:00:02,500\nただいま\n我回来啦\n"
        "2\n00:00:03,000 --> 00:00:05,500\nおやすみ\n晚安好梦\n",
        encoding="utf-8",
    )

    draft = isolated_env.service.prepare_draft(
        work_dir,
        enable_translation=False,
        voice_plan={"recipe_id": recipe["id"]},
        sample_cue_count=1,
    )
    assert draft["state"] == "awaiting_review"
    assert len(isolated_env.tts_calls) == 1  # Sample cue 0 synthesized during Phase 1

    isolated_env.tts_calls.clear()
    committed = isolated_env.service.commit_draft(
        draft["draft_id"],
        isolated_env.tmp_path / "out_unicode",
        export_formats=("srt", "lrc"),
        enable_dubbing=True,
    )
    assert committed["state"] == "completed"
    # Cue 0 was reused from Phase-1 sample take; only Cue 1 needed synthesis!
    assert len(isolated_env.tts_calls) == 1
    assert committed["artifacts"]["dubbing"]["reused_take_count"] == 1
    assert committed["artifacts"]["dubbing"]["synthesized_take_count"] == 1

