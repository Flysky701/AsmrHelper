from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from src.app.dto import VoiceCloneRequest, VoicePreviewRequest
from src.app.errors import AppValidationError
from src.app.services.voice_service import VoiceService


def _voice_service_without_runtime() -> VoiceService:
    return object.__new__(VoiceService)


def test_icl_clone_requires_exact_reference_text(tmp_path) -> None:
    audio_path = tmp_path / "reference.wav"
    audio_path.write_bytes(b"RIFF")
    service = _voice_service_without_runtime()

    with pytest.raises(AppValidationError, match="ref_text is required for ICL"):
        service.submit_clone_voice(
            VoiceCloneRequest(
                audio_path=str(audio_path),
                name="ICL Voice",
                ref_text="   ",
            )
        )


@pytest.mark.parametrize(
    ("x_vector_only_mode", "ref_text"),
    [
        (False, "Reference transcript"),
        (True, "Ignored transcript"),
    ],
)
def test_clone_submission_preserves_qwen_clone_mode(
    tmp_path,
    x_vector_only_mode: bool,
    ref_text: str,
) -> None:
    audio_path = tmp_path / "reference.wav"
    audio_path.write_bytes(b"RIFF")
    captured: dict = {}
    service = _voice_service_without_runtime()

    def submit(operation: str, payload: dict):
        captured["operation"] = operation
        captured["payload"] = payload
        return SimpleNamespace(task_id="voice.clone-1")

    service._submit_voice_task = submit

    service.submit_clone_voice(
        VoiceCloneRequest(
            audio_path=str(audio_path),
            name="Clone Voice",
            ref_text=ref_text,
            x_vector_only_mode=x_vector_only_mode,
        )
    )

    assert captured["operation"] == "clone"
    expected_ref_text = None if x_vector_only_mode else ref_text
    assert captured["payload"]["ref_text"] == expected_ref_text
    assert captured["payload"]["x_vector_only_mode"] is x_vector_only_mode


def test_voice_preview_submission_preserves_target_language() -> None:
    captured: dict = {}
    service = _voice_service_without_runtime()
    service._get_profile_or_raise = lambda _profile_id: SimpleNamespace(id="voice-1")

    def submit(operation: str, payload: dict):
        captured["operation"] = operation
        captured["payload"] = payload
        return SimpleNamespace(task_id="voice.preview-1")

    service._submit_voice_task = submit

    service.submit_preview_voice(
        VoicePreviewRequest(
            profile_id="voice-1",
            text="こんにちは",
            speed=1.0,
            language="ja",
        )
    )

    assert captured["operation"] == "preview"
    assert captured["payload"]["language"] == "ja"


def test_voice_preview_rejects_blank_text_and_unsupported_language() -> None:
    service = _voice_service_without_runtime()
    service._get_profile_or_raise = lambda _profile_id: SimpleNamespace(id="voice-1")

    with pytest.raises(AppValidationError, match="text is required"):
        service.submit_preview_voice(
            VoicePreviewRequest(profile_id="voice-1", text="   ", language="ja")
        )

    with pytest.raises(AppValidationError, match="does not support language"):
        service.submit_preview_voice(
            VoicePreviewRequest(profile_id="voice-1", text="Hello", language="th")
        )


def test_clone_rejects_directory_as_reference_audio(tmp_path) -> None:
    service = _voice_service_without_runtime()

    with pytest.raises(AppValidationError, match="audio file does not exist"):
        service.submit_clone_voice(
            VoiceCloneRequest(
                audio_path=str(tmp_path),
                name="Directory is not audio",
                ref_text="Reference transcript",
            )
        )


def test_voice_clone_tasks_share_one_runtime_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state_lock = threading.Lock()
    active = 0
    max_active = 0
    generated_profiles: dict[str, str] = {}

    class RuntimeRouter:
        def clone_voice(self, profile):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
                profile_id = f"C{len(generated_profiles) + 1}"

            # Model loading and prompt creation leave a window in which an
            # unlocked second task would choose the same max+1 profile id.
            time.sleep(0.05)
            with state_lock:
                generated_profiles[profile_id] = profile["name"]
                active -= 1
            return {
                "profile_id": profile_id,
                "name": profile["name"],
                "category": "clone",
                "ref_audio_path": str(tmp_path / f"{profile_id}.wav"),
                "prompt_cache_path": str(tmp_path / f"{profile_id}.pt"),
            }

    class ArtifactService:
        def register_artifact(self, **_kwargs):
            return None

    class Context:
        cancellation_requested = False

        @staticmethod
        def update_progress(*_args, **_kwargs):
            return None

    service = _voice_service_without_runtime()
    service._runtime_router = RuntimeRouter()
    service._artifact_service = ArtifactService()
    monkeypatch.setattr(
        VoiceService,
        "_restore_profile",
        staticmethod(lambda _result: None),
    )

    start = threading.Barrier(2)

    def execute(index: int):
        start.wait(timeout=2)
        return service._execute_voice_task(
            SimpleNamespace(
                task_id=f"voice.clone-{index}",
                task_type="voice.clone",
                execution_profile={"operation": "clone", "name": f"Voice {index}"},
            ),
            Context(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, (1, 2)))

    assert max_active == 1
    assert {result["profile_id"] for result in results} == {"C1", "C2"}
    assert set(generated_profiles) == {"C1", "C2"}


def test_voice_task_wait_can_be_cancelled() -> None:
    import src.app.services.voice_service as voice_service_module

    class Context:
        checks = 0

        @property
        def cancellation_requested(self):
            self.checks += 1
            return self.checks > 1

        @staticmethod
        def update_progress(*_args, **_kwargs):
            return None

    service = _voice_service_without_runtime()
    acquired = voice_service_module._VOICE_TASK_LOCK.acquire(timeout=1)
    assert acquired
    try:
        with pytest.raises(RuntimeError, match="cancelled by user"):
            service._execute_voice_task(
                SimpleNamespace(
                    task_id="voice.preview-cancelled",
                    task_type="voice.preview",
                    execution_profile={"operation": "preview"},
                ),
                Context(),
            )
    finally:
        voice_service_module._VOICE_TASK_LOCK.release()


def test_http_voice_routes_preserve_clone_mode_and_preview_language() -> None:
    from src.api.http.routes.voice import clone_voice, preview_voice
    from src.api.http.schemas.voice import (
        VoiceCloneRequest as VoiceCloneBody,
        VoicePreviewRequest as VoicePreviewBody,
    )
    from src.core.tasks import TaskStatus

    captured: dict = {}

    class Service:
        def submit_clone_voice(self, request):
            captured["clone"] = request
            return TaskStatus(
                task_id="voice.clone-1",
                task_type="voice.clone",
                task_source="voice-lab",
                state="running",
                created_at="2026-08-18T00:00:00+00:00",
            )

        def submit_preview_voice(self, request):
            captured["preview"] = request
            return TaskStatus(
                task_id="voice.preview-1",
                task_type="voice.preview",
                task_source="voice-lab",
                state="running",
                created_at="2026-08-18T00:00:00+00:00",
            )

    service = Service()
    clone_voice(
        VoiceCloneBody(
            audio_path="reference.wav",
            name="Cross-language",
            x_vector_only_mode=True,
        ),
        service,
    )
    preview_voice(
        "C1",
        VoicePreviewBody(text="Hello", language="en"),
        service,
    )

    assert captured["clone"].x_vector_only_mode is True
    assert captured["clone"].ref_text == ""
    assert captured["preview"].profile_id == "C1"
    assert captured["preview"].language == "en"


def test_voice_worker_does_not_invent_clone_reference_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.core.tts.voice_designer as voice_designer_module
    from src.core.runtime.stage_worker import _execute

    captured: dict = {}

    class Profile:
        id = "C1"
        name = "Cross-language"
        category = "clone"
        engine = "qwen3_clone"
        description = "x-vector"
        design_instruct = ""

        @staticmethod
        def get_ref_audio_path() -> str:
            return "reference.wav"

        @staticmethod
        def get_prompt_cache_path() -> str:
            return "prompt.pt"

    class Designer:
        def __init__(self, output_dir=None):
            captured["output_dir"] = output_dir

        def clone_from_audio(self, **kwargs):
            captured.update(kwargs)
            return Profile()

    monkeypatch.setattr(voice_designer_module, "VoiceDesigner", Designer)

    result = _execute(
        {
            "operation": "voice.clone",
            "payload": {
                "audio_path": "reference.wav",
                "name": "Cross-language",
                "ref_text": None,
                "x_vector_only_mode": True,
            },
        }
    )

    assert captured["ref_text"] == ""
    assert captured["x_vector_only_mode"] is True
    assert result["profile_id"] == "C1"


def test_voice_worker_preserves_and_serializes_clone_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.core.tts.voice_designer as voice_designer_module
    from src.core.runtime.stage_worker import _execute

    captured: dict = {}
    analysis_manifest = {
        "analysis_id": "voice-analysis-1",
        "candidate_id": "candidate-0001",
        "source_fingerprint": "sha256:source",
        "source_variant": "separated_vocals",
        "start": 1.25,
        "end": 7.5,
        "original_text": "识别文本",
        "confirmed_text": "用户确认文本",
        "score": 91,
        "details": {"rms_score": 94},
    }

    class Profile:
        id = "C1"
        name = "Candidate Voice"
        category = "clone"
        engine = "qwen3_clone"
        description = "candidate"
        design_instruct = ""

        @staticmethod
        def get_ref_audio_path() -> str:
            return "C1_ref.wav"

        @staticmethod
        def get_prompt_cache_path() -> str:
            return "C1_prompt.pt"

        @staticmethod
        def get_clone_manifest_path() -> str:
            return "C1_clone_manifest.json"

    class Designer:
        def __init__(self, output_dir=None):
            captured["output_dir"] = output_dir

        def clone_from_audio(self, **kwargs):
            captured.update(kwargs)
            return Profile()

    monkeypatch.setattr(voice_designer_module, "VoiceDesigner", Designer)

    result = _execute(
        {
            "operation": "voice.clone",
            "payload": {
                "audio_path": "candidate-0001.wav",
                "name": "Candidate Voice",
                "ref_text": "用户确认文本",
                "x_vector_only_mode": False,
                "clone_manifest": analysis_manifest,
            },
        }
    )

    assert captured["clone_manifest"] == analysis_manifest
    assert captured["ref_text"] == "用户确认文本"
    assert result["ref_audio_path"] == "C1_ref.wav"
    assert result["clone_manifest_path"] == "C1_clone_manifest.json"


def test_voice_worker_preserves_preview_target_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.core.tts.voice_designer as voice_designer_module
    import src.core.tts.voice_profile as voice_profile_module
    from src.core.runtime.stage_worker import _execute

    captured: dict = {}

    class Designer:
        def preview_profile(self, **kwargs):
            captured.update(kwargs)
            return "preview.wav"

    class Manager:
        @staticmethod
        def get_by_id(profile_id: str):
            return SimpleNamespace(id=profile_id, name="Voice")

    monkeypatch.setattr(
        voice_designer_module,
        "get_voice_designer",
        lambda: Designer(),
    )
    monkeypatch.setattr(
        voice_profile_module,
        "get_voice_manager",
        lambda: Manager(),
    )

    result = _execute(
        {
            "operation": "voice.preview",
            "payload": {
                "profile_id": "C1",
                "text": "こんにちは",
                "language": "ja",
            },
        }
    )

    assert captured["language"] == "ja"
    assert result["output_path"] == "preview.wav"


def test_voice_designer_forwards_x_vector_mode_to_qwen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.tts.qwen3_manager as qwen_manager_module
    import src.core.tts.voice_profile as voice_profile_module
    from src.core.tts.voice_designer import VoiceDesigner

    audio_path = tmp_path / "reference.wav"
    audio_path.write_bytes(b"RIFF")
    captured: dict = {}

    class BaseModel:
        def create_voice_clone_prompt(self, **kwargs):
            captured.update(kwargs)
            return []

    class VoiceManager:
        def get_all(self):
            return []

        def add_profile(self, profile):
            captured["profile"] = profile

    monkeypatch.setattr(
        qwen_manager_module.Qwen3ModelManager,
        "get_base_model",
        classmethod(lambda cls, download_root=None: BaseModel()),
    )
    monkeypatch.setattr(
        voice_profile_module,
        "get_voice_manager",
        lambda: VoiceManager(),
    )

    profile = VoiceDesigner(output_dir=str(tmp_path / "profiles")).clone_from_audio(
        audio_path=str(audio_path),
        name="Cross-language",
        ref_text="Ignored transcript",
        x_vector_only_mode=True,
    )

    persisted_audio = tmp_path / "profiles" / "C1_ref.wav"
    assert captured["ref_audio"] == str(persisted_audio)
    assert persisted_audio.read_bytes() == audio_path.read_bytes()
    assert captured["ref_text"] is None
    assert captured["x_vector_only_mode"] is True
    assert profile.category == "clone"
    assert "x-vector" in profile.description
    manifest = json.loads(Path(profile.get_clone_manifest_path()).read_text(encoding="utf-8"))
    assert manifest["profile_id"] == "C1"
    assert manifest["clone_mode"] == "x_vector_only"
    assert manifest["ref_audio_path"] == str(persisted_audio)


def test_voice_designer_persists_candidate_audio_and_analysis_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.tts.qwen3_manager as qwen_manager_module
    import src.core.tts.voice_profile as voice_profile_module
    from src.core.tts.voice_designer import VoiceDesigner

    candidate_path = tmp_path / "analysis" / "candidate-0001.wav"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_bytes(b"candidate-audio")
    captured: dict = {}
    analysis_manifest = {
        "analysis_id": "voice-analysis-1",
        "candidate_id": "candidate-0001",
        "source_fingerprint": "sha256:source",
        "source_variant": "original",
        "start": 2.0,
        "end": 8.0,
        "original_text": "识别文本",
        "confirmed_text": "用户确认文本",
        "score": 93,
        "details": {"duration_score": 100, "rms_score": 90},
    }

    class BaseModel:
        def create_voice_clone_prompt(self, **kwargs):
            captured.update(kwargs)
            return []

    class VoiceManager:
        @staticmethod
        def get_all():
            return []

        @staticmethod
        def add_profile(profile):
            captured["profile"] = profile

    monkeypatch.setattr(
        qwen_manager_module.Qwen3ModelManager,
        "get_base_model",
        classmethod(lambda cls, download_root=None: BaseModel()),
    )
    monkeypatch.setattr(
        voice_profile_module,
        "get_voice_manager",
        lambda: VoiceManager(),
    )

    profile = VoiceDesigner(output_dir=str(tmp_path / "profiles")).clone_from_audio(
        audio_path=str(candidate_path),
        name="Candidate Voice",
        ref_text="用户确认文本",
        clone_manifest=analysis_manifest,
    )

    persisted_audio = tmp_path / "profiles" / "C1_ref.wav"
    persisted_manifest = tmp_path / "profiles" / "C1_clone_manifest.json"
    assert persisted_audio.read_bytes() == candidate_path.read_bytes()
    assert captured["ref_audio"] == str(persisted_audio)
    assert captured["ref_text"] == "用户确认文本"
    assert profile.get_ref_audio_path() == str(persisted_audio)
    assert profile.get_clone_manifest_path() == str(persisted_manifest)

    manifest = json.loads(persisted_manifest.read_text(encoding="utf-8"))
    assert manifest["ref_audio_path"] == str(persisted_audio)
    assert manifest["source_audio_path"] == str(persisted_audio)
    assert manifest["ref_text"] == "用户确认文本"
    assert manifest["analysis"] == analysis_manifest


def test_voice_designer_rolls_back_profile_and_files_when_profile_save_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.tts.qwen3_manager as qwen_manager_module
    import src.core.tts.voice_profile as voice_profile_module
    from src.core.tts.voice_designer import VoiceDesigner
    from src.core.tts.voice_profile import VoiceProfileManager

    audio_path = tmp_path / "reference.wav"
    audio_path.write_bytes(b"RIFF")
    output_dir = tmp_path / "profiles"
    manager = VoiceProfileManager(config_path=str(tmp_path / "voice-profiles.json"))

    class BaseModel:
        @staticmethod
        def create_voice_clone_prompt(**_kwargs):
            return []

    def fail_save():
        raise OSError("profile save failed")

    monkeypatch.setattr(
        qwen_manager_module.Qwen3ModelManager,
        "get_base_model",
        classmethod(lambda cls, download_root=None: BaseModel()),
    )
    monkeypatch.setattr(voice_profile_module, "get_voice_manager", lambda: manager)
    monkeypatch.setattr(manager, "save", fail_save)

    with pytest.raises(OSError, match="profile save failed"):
        VoiceDesigner(output_dir=str(output_dir)).clone_from_audio(
            audio_path=str(audio_path),
            name="Failed Clone",
            ref_text="Reference transcript",
        )

    assert manager.get_by_id("C1") is None
    assert not list(output_dir.glob("C1_*"))


def test_delete_clone_profile_only_removes_managed_clone_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.tts.voice_profile as voice_profile_module
    from src.core.tts.voice_profile import VoiceProfile, VoiceProfileManager

    monkeypatch.setattr(voice_profile_module, "PROJECT_ROOT", tmp_path)
    voice_dir = tmp_path / "models" / "voice_profiles"
    voice_dir.mkdir(parents=True)

    managed_ref = voice_dir / "C1_ref.wav"
    managed_prompt = voice_dir / "C1_prompt.pt"
    managed_manifest = voice_dir / "C1_clone_manifest.json"
    for path in (managed_ref, managed_prompt, managed_manifest):
        path.write_bytes(b"managed")

    external_dir = tmp_path / "legacy-user-files"
    external_dir.mkdir()
    external_ref = external_dir / "original-reference.wav"
    external_manifest = external_dir / "legacy-manifest.json"
    external_ref.write_bytes(b"user-audio")
    external_manifest.write_text("{}", encoding="utf-8")
    legacy_prompt = voice_dir / "C2_prompt.pt"
    legacy_prompt.write_bytes(b"managed-prompt")

    manager = VoiceProfileManager(config_path=str(tmp_path / "profiles.json"))
    manager.add_profile(
        VoiceProfile(
            id="C1",
            name="Managed Clone",
            category="clone",
            engine="qwen3_clone",
            ref_audio=str(managed_ref),
            prompt_cache=str(managed_prompt),
            clone_manifest=str(managed_manifest),
            generated=True,
        )
    )
    manager.add_profile(
        VoiceProfile(
            id="C2",
            name="Legacy Clone",
            category="clone",
            engine="qwen3_clone",
            ref_audio=str(external_ref),
            prompt_cache=str(legacy_prompt),
            clone_manifest=str(external_manifest),
            generated=True,
        )
    )

    assert manager.delete_profile("C1") is True
    assert not managed_ref.exists()
    assert not managed_prompt.exists()
    assert not managed_manifest.exists()

    assert manager.delete_profile("C2") is True
    assert not legacy_prompt.exists()
    assert external_ref.read_bytes() == b"user-audio"
    assert external_manifest.exists()


def test_delete_profile_holds_lock_until_managed_files_are_removed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.tts.voice_profile as voice_profile_module
    from src.core.tts.voice_profile import VoiceProfile, VoiceProfileManager

    monkeypatch.setattr(voice_profile_module, "PROJECT_ROOT", tmp_path)
    voice_dir = tmp_path / "models" / "voice_profiles"
    voice_dir.mkdir(parents=True)
    old_prompt = voice_dir / "C1_prompt.pt"
    old_prompt.write_bytes(b"old")
    manager = VoiceProfileManager(config_path=str(tmp_path / "profiles.json"))
    manager.add_profile(
        VoiceProfile(
            id="C1",
            name="Old Clone",
            category="clone",
            engine="qwen3_clone",
            prompt_cache=str(old_prompt),
            generated=True,
        )
    )

    unlink_started = threading.Event()
    allow_unlink = threading.Event()
    add_started = threading.Event()
    add_completed = threading.Event()
    original_unlink = Path.unlink

    def blocking_unlink(path: Path, *args, **kwargs):
        if path == old_prompt:
            unlink_started.set()
            assert allow_unlink.wait(timeout=2)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocking_unlink)

    delete_thread = threading.Thread(target=manager.delete_profile, args=("C1",))
    delete_thread.start()
    assert unlink_started.wait(timeout=2)

    def add_replacement():
        add_started.set()
        manager.add_profile(
            VoiceProfile(
                id="C1",
                name="Replacement Clone",
                category="clone",
                engine="qwen3_clone",
                generated=True,
            )
        )
        add_completed.set()

    add_thread = threading.Thread(target=add_replacement)
    add_thread.start()
    assert add_started.wait(timeout=2)
    assert not add_completed.wait(timeout=0.1)

    allow_unlink.set()
    delete_thread.join(timeout=2)
    add_thread.join(timeout=2)

    assert add_completed.is_set()
    assert manager.get_by_id("C1").name == "Replacement Clone"


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("auto", "Auto"),
        ("zh-CN", "Chinese"),
        ("zh-TW", "Chinese"),
        ("ja", "Japanese"),
        ("English", "English"),
        ("pt_BR", "Portuguese"),
    ],
)
def test_qwen_language_mapping(language: str, expected: str) -> None:
    from src.core.tts import normalize_qwen3_language

    assert normalize_qwen3_language(language) == expected


def test_qwen_language_mapping_rejects_unsupported_language() -> None:
    from src.core.tts import normalize_qwen3_language

    with pytest.raises(ValueError, match="does not support language"):
        normalize_qwen3_language("th")


def test_qwen_capability_and_http_synthesis_preserve_target_language(
    tmp_path,
) -> None:
    from src.api.http.routes.tts import synthesize
    from src.api.http.schemas.tts import SynthesizeRequest
    from src.app.services.capability_descriptor_service import (
        CapabilityDescriptorService,
    )
    from src.app.services.execution_profile_builder import ExecutionProfileBuilder
    from src.app.services.tts_engine_service import TtsEngineService

    captured: dict = {}

    class Settings:
        @staticmethod
        def get_effective_settings(*, masked=False):
            assert masked is False
            return {"tts": {"engine": "qwen3"}}

    class Runtime:
        @staticmethod
        def synthesize_text(*, text, output_path, profile):
            captured["text"] = text
            captured["output_path"] = output_path
            captured["profile"] = profile
            return output_path

    descriptor_service = CapabilityDescriptorService()
    profile_builder = ExecutionProfileBuilder(
        settings_service=Settings(),
        descriptor_service=descriptor_service,
    )
    service = TtsEngineService(
        capability_service=descriptor_service,
        profile_builder=profile_builder,
        runtime=Runtime(),
    )
    input_path = tmp_path / "input.txt"
    input_path.write_text("こんにちは", encoding="utf-8")
    output_path = tmp_path / "output.wav"

    result = synthesize(
        SynthesizeRequest(
            input_path=str(input_path),
            output_path=str(output_path),
            engine="qwen3",
            model="qwen3-custom-voice",
            voice="Ono_Anna",
            common_options={"language": "ja"},
        ),
        service,
    )

    language_option = next(
        option
        for option in descriptor_service.get_descriptor("tts", "qwen3")["common_option_schema"]
        if option["name"] == "language"
    )
    assert language_option["default"] == "auto"
    assert language_option["enum"] == [
        "auto",
        "zh",
        "en",
        "ja",
        "ko",
        "de",
        "fr",
        "ru",
        "pt",
        "es",
        "it",
    ]
    assert captured["profile"]["common_options"]["language"] == "ja"
    assert result.output_path == str(output_path)


def test_qwen_voice_list_reports_native_languages() -> None:
    from src.core.tts import Qwen3TTSEngine

    languages = {voice["id"]: voice["language"] for voice in Qwen3TTSEngine.list_voices()}

    assert languages["Ryan"] == "en"
    assert languages["Aiden"] == "en"
    assert languages["Ono_Anna"] == "ja"
    assert languages["Sohee"] == "ko"
    assert languages["Vivian"] == "zh"


def test_qwen_engine_rejects_missing_voice_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.core.tts.voice_profile as voice_profile_module
    from src.core.tts import Qwen3TTSEngine

    class Manager:
        @staticmethod
        def get_by_id(_profile_id: str):
            return None

    monkeypatch.setattr(voice_profile_module, "get_voice_manager", lambda: Manager())

    with pytest.raises(ValueError, match="voice profile not found: deleted-profile"):
        Qwen3TTSEngine(voice_profile_id="deleted-profile")


def test_cached_clone_synthesis_uses_selected_target_language(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    torch = pytest.importorskip("torch")
    from src.core.tts import Qwen3TTSEngine, normalize_qwen3_language

    prompt_path = tmp_path / "prompt.pt"
    torch.save([], prompt_path)
    output_path = tmp_path / "preview.wav"
    captured: dict = {}

    class BaseModel:
        def generate_voice_clone(self, text, **kwargs):
            captured["text"] = text
            captured.update(kwargs)
            return [np.zeros(240, dtype=np.float32)], 24000

    monkeypatch.setattr(
        Qwen3TTSEngine,
        "_get_base_model",
        classmethod(lambda cls: BaseModel()),
    )
    engine = object.__new__(Qwen3TTSEngine)
    engine.prompt_cache = str(prompt_path)
    engine.language = normalize_qwen3_language("ja")

    engine._synthesize_from_cache("こんにちは", str(output_path))

    assert captured["language"] == "Japanese"
    assert captured["voice_clone_prompt"] == []
    assert output_path.exists()


def test_custom_voice_synthesis_uses_selected_target_language(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from src.core.tts import Qwen3TTSEngine, normalize_qwen3_language

    captured: dict = {}

    class CustomModel:
        def generate_custom_voice(self, text, **kwargs):
            captured["text"] = text
            captured.update(kwargs)
            return [np.zeros(240, dtype=np.float32)], 24000

    monkeypatch.setattr(
        Qwen3TTSEngine,
        "_get_custom_model",
        classmethod(lambda cls: CustomModel()),
    )
    engine = object.__new__(Qwen3TTSEngine)
    engine.profile = None
    engine.voice = "Ono_Anna"
    engine.extra_options = {}
    engine.language = normalize_qwen3_language("en")
    output_path = tmp_path / "custom.wav"

    engine._synthesize("Hello", str(output_path))

    assert captured["language"] == "English"
    assert output_path.exists()
