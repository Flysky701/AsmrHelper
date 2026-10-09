"""VoiceLab's persistent recipes, immutable synthesis runs and segment selection."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4

from src.core.speech.store import SpeechStore, build_plan, validate_plan, companion_subtitle_paths, _reference_file_operation
from src.core.speech.compiler import compile_recipe
from src.core.speech.providers import get_provider
from src.core.tasks import TaskDispatcher
from .task_service import get_task_service, get_task_dispatcher
from .artifact_service import get_artifact_service


class SpeechService:
    def __init__(self, store=None, tasks=None, dispatcher=None, artifacts=None):
        self.store = store or SpeechStore()
        self.tasks = tasks or get_task_service()
        self.dispatcher = dispatcher or (get_task_dispatcher() if tasks is None else TaskDispatcher(self.tasks.registry, task_service=self.tasks))
        self.artifacts = artifacts or get_artifact_service()
        self._lock = threading.RLock()
        self._connection_locks = {}
        self.dispatcher.register_executor("speech.generate", self._execute)
        self.dispatcher.register_executor("speech.reference_analyze", self._execute_reference_analysis)

    def library(self):
        self.ensure_default_preset()
        data = {name: self.store.list(name) for name in ("voices", "recipes", "assets", "experiments", "takes", "plans", "selections", "assemblies", "connections")}
        data["connections"], data["connection_defaults"] = self.store.connection_catalog()
        for connection in data["connections"]:
            connection["credential_configured"] = self._credential_path(connection).exists()
        return data

    def list_connections(self):
        """Return connection settings without loading credentials or other collections."""
        fields = ("id", "name", "provider_id", "deployment", "base_url", "revision", "is_default")
        connections, _ = self.store.connection_catalog()
        return [
            {**{key: connection[key] for key in fields if key in connection},
             "credential_configured": self._credential_path(connection).exists()}
            for connection in connections
        ]

    def connection_defaults(self):
        return self.store.connection_catalog()[1]

    def set_default_connection(self, connection_id, expected_revision, expected_default_revision):
        return self.store.set_default_connection(connection_id, expected_revision, expected_default_revision)

    def connection_deletion_preview(self, connection_id):
        from .speech_connection_service import SpeechConnectionService
        return SpeechConnectionService(self).preview(connection_id)

    def delete_connection(self, connection_id, **choice):
        from .speech_connection_service import SpeechConnectionService
        return SpeechConnectionService(self).execute(connection_id, **choice)

    def _credential_path(self, connection):
        ref = str(connection.get("credential_ref", ""))
        if not ref or any(c not in "0123456789abcdef" for c in ref):
            return Path(self.store.root) / "credentials" / "missing"
        return Path(self.store.root) / "credentials" / (ref + ".json")

    def resolve_local_connection(self, provider_id, model, mode):
        provider = get_provider(provider_id)
        if provider.remote:
            raise ValueError("此引擎需要明确选择连接，不能使用本机默认连接")
        if not any(item["id"] == mode and model in item["models"] for item in provider.modes):
            raise ValueError("模型与本机引擎模式不匹配")
        name = {"qwen3": "Qwen3 TTS", "voxcpm2": "VoxCPM2"}.get(provider_id, provider_id)
        connection = self.store.resolve_local_connection(provider_id, name + " · 本机")
        if connection is None:
            return {"connection": None, "readiness": None,
                    "detail": "已有多个连接或非本机配置，请在高级连接设置中明确选择。"}
        # Local readiness inspects paths/config metadata only. Never resolve a credential here.
        public = {key: connection[key] for key in
                  ("id", "name", "provider_id", "deployment", "timeout", "model_path", "device")
                  if key in connection}
        context = {key: connection[key] for key in ("model_path", "device", "precision", "runtime") if key in connection}
        readiness = provider.probe({**context, "model": model, "mode": mode})
        if readiness.get("ready"):
            readiness["detail"] = "模型与运行环境文件已找到；尚未验证依赖或执行合成。"
        return {"connection": public, "readiness": readiness,
                "detail": "保存音色只保存配置，不会启动或安装模型。"}

    def save_connection(self, body):
        allowed = {"id", "name", "provider_id", "deployment", "base_url", "api_key", "timeout", "model_path", "device", "precision", "runtime", "concurrency"}
        if set(body) - allowed:
            raise ValueError("未知连接字段")
        data = deepcopy(body)
        previous = self.store.get("connections", data["id"]) if data.get("id") else None
        data = {**(previous or {}), **data}
        provider = get_provider(data.get("provider_id", ""))
        if not str(data.get("name", "")).strip():
            raise ValueError("请填写连接名称")
        if data.get("deployment") not in {"local", "lan", "cloud"}:
            raise ValueError("请选择明确的运行位置")
        if not provider.remote and data["deployment"] != "local":
            raise ValueError("此引擎执行本地推理，请选择本机运行连接")
        from urllib.parse import urlsplit
        if data.get("base_url"):
            url = urlsplit(data["base_url"])
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("连接地址必须是无凭据的 HTTP(S) 基础地址")
        data["timeout"] = float(data.get("timeout", 120))
        if not 1 <= data["timeout"] <= 600:
            raise ValueError("超时应在 1–600 秒之间")
        key = data.pop("api_key", "")
        if previous and any(data.get(k) != previous.get(k) for k in ("base_url", "provider_id")) and not key:
            raise ValueError("更换服务地址或协议后请重新提供凭据")
        if key:
            data["credential_ref"] = uuid4().hex
            path = self._credential_path(data)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"api_key": key}), encoding="utf-8")
        if previous:
            saved = self.store.update("connections", previous["id"], data, expected_revision=previous["revision"])
        else:
            saved = self.store.create("connections", data)
        saved["credential_configured"] = self._credential_path(saved).exists()
        return saved

    def connection_context(self, connection):
        value = deepcopy(connection)
        path = self._credential_path(connection)
        if connection.get("credential_ref"):
            if not path.exists():
                raise ValueError("任务原凭据已不可用，请重新建立任务；不会切换到当前连接")
            value.update(json.loads(path.read_text(encoding="utf-8")))
        return {"connection": value, **{k: value[k] for k in ("model_path", "device", "precision", "runtime") if k in value}}

    @_reference_file_operation
    def save_recipe(self, body):
        data = self._prepare_recipe(body)
        voice = self.store.get("voices", data["voice_id"])
        if voice.get("bindings") and not any(b["provider_id"] == data["provider_id"] for b in voice["bindings"]):
            raise ValueError("请先为此声音添加对应引擎实现")
        return self.store.create("recipes", data)

    def _prepare_recipe(self, body):
        data = deepcopy(body)
        if isinstance(data.get("variant"), dict):
            data["variant"].setdefault("style", "normal")
        allowed = {"id", "revision", "created_at", "updated_at", "previous_id", "name", "description", "voice_id", "provider_id", "model", "mode", "connection_ref", "variant", "language", "provider_options", "default_delivery", "default_emotion", "default_pause_ms"}
        if set(data) - allowed:
            raise ValueError("未知配方字段")
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError("请填写规则名称")
        if not isinstance(data.get("description", ""), str):
            raise ValueError("规则说明必须是文本")
        data.pop("id", None)
        data["id"] = uuid4().hex
        previous_id = body.get("id")
        data["revision"] = 1
        if previous_id:
            previous = self.store.get("recipes", previous_id)
            data.update(revision=previous["revision"] + 1, previous_id=previous_id)
        connection = self._recipe_connection(data)
        data["connection_ref"] = connection["id"]
        if connection["provider_id"] != data["provider_id"]:
            raise ValueError("配方与连接的引擎不一致")
        self._validate_reference(data)
        # The compiler, not UI visibility, is authoritative for provider options.
        probe_plan = build_plan("配置校验。")
        for segment in probe_plan["segments"]:
            segment.update(delivery=data.get("default_delivery", "normal"), emotion=data.get("default_emotion", "neutral"), pause_ms=data.get("default_pause_ms", 0))
        compile_recipe(data, probe_plan, self.assets())
        return data

    def _recipe_connection(self, recipe, *, allow_default=True):
        provider = get_provider(recipe.get("provider_id"))
        ref = recipe.get("connection_ref")
        default_id = "engine-default-" + provider.provider_id
        connection_required = getattr(provider, "http", provider.remote)
        if not ref and allow_default:
            selected = self.store.default_connection(provider.provider_id)
            if selected is not None:
                return selected
        if not ref or (not connection_required and ref == default_id):
            if connection_required:
                raise ValueError("请选择外部语音服务连接")
            return {"id": default_id, "revision": 1, "provider_id": provider.provider_id,
                    "deployment": "cloud" if provider.remote else "local"}
        if not isinstance(ref, str):
            raise ValueError("连接必须是明确的引用")
        return self.store.get("connections", ref)

    def _validate_reference(self, recipe):
        variant = recipe.get("variant") or {}
        if isinstance(variant, dict) and variant.get("kind") == "reference":
            asset = self.store.get("assets", variant.get("value"))
            if asset.get("archived"):
                raise ValueError("参考素材已归档，请选择可用素材")
            provider = get_provider(recipe.get("provider_id"))
            requires_transcript = getattr(provider, "reference_requires_transcript", lambda _recipe: False)
            if requires_transcript(recipe):
                if asset.get("confirmed") is not True or not str(asset.get("transcript", "")).strip():
                    raise ValueError("此模式需要已核对转录原文的参考素材；或明确选择仅使用声音特征")

    def _resolve_recipe_input(self, recipe_id=None, recipe_draft=None):
        """Resolve a saved immutable revision or an unsaved, strictly bounded draft."""
        if (recipe_id is None) == (recipe_draft is None):
            raise ValueError("recipe_id 与 recipe_draft 必须且只能提供一个")
        if recipe_id is not None:
            if not isinstance(recipe_id, str) or not recipe_id.strip():
                raise ValueError("recipe_id 必须是非空字符串")
            recipe = self.store.get("recipes", recipe_id)
            connection = self._recipe_connection(recipe, allow_default=False)
            # Old saved revisions retain their bytes. Move only their legacy device
            # into the execution connection copy; new draft/save options reject it.
            device = recipe.get("provider_options", {}).pop("device", None)
            if device is not None:
                connection.setdefault("device", device)
            return recipe, connection
        allowed = {"name", "description", "provider_id", "model", "mode", "connection_ref",
                   "variant", "language", "provider_options", "default_delivery", "default_emotion", "default_pause_ms"}
        if not isinstance(recipe_draft, dict) or set(recipe_draft) - allowed:
            raise ValueError("试听草稿包含未知或不可编辑的字段")
        data = deepcopy(recipe_draft)
        if isinstance(data.get("name", ""), str) and not data.get("name", "").strip():
            data["name"] = "未保存试听"
        data.setdefault("provider_options", {"schema_version": 1})
        data.setdefault("language", "auto")
        prepared = self._prepare_recipe(data)
        prepared["id"] = "preview-" + prepared["id"]
        return prepared, self._recipe_connection(prepared)

    @_reference_file_operation
    def save_rule(self, body):
        """Save any validated single-engine recipe as an immutable named rule."""
        data = deepcopy(body)
        previous = self.store.get("recipes", data["id"]) if data.get("id") else None
        if previous:
            if data.get("voice_id", previous["voice_id"]) != previous["voice_id"]:
                raise ValueError("修改规则不能更换声音归属")
            data["voice_id"] = previous["voice_id"]
        voice_data = None
        if not data.get("voice_id"):
            data["voice_id"] = uuid4().hex
            voice_data = {"id": data["voice_id"], "name": data.get("name"), "bindings": []}
        else:
            voice = self.store.get("voices", data["voice_id"])
            if voice.get("bindings"):
                raise ValueError("旧声音绑定保持不变，请创建独立生成规则")
        prepared = self._prepare_recipe(data)
        return self.store.create_rule(voice_data, prepared)

    def active_recipes(self, include_archived=False):
        self.ensure_default_preset()
        return self.store.active_recipes(include_archived=include_archived)

    def ensure_default_preset(self, *, add=False):
        from src.core.speech.defaults import EDGE_STARTER_KEY, edge_starter_recipe
        recipe = edge_starter_recipe()
        compile_recipe({**recipe, "id": "builtin-check", "revision": 1}, build_plan("配置校验。"), {})
        return self.store.ensure_builtin_recipe(EDGE_STARTER_KEY, recipe, add=add)

    def assets(self):
        return {a["id"]: a for a in self.store.list("assets")}

    @_reference_file_operation
    def start_reference_analysis(self, body):
        path = Path(str(body.get("path", "")))
        if not path.is_file():
            raise ValueError("请选择存在的录音文件")
        for key in ("require_text", "separate_vocals"):
            if key in body and type(body[key]) is not bool:
                raise ValueError(f"{key} 必须是布尔值")
        self._validate_subtitle_input(body)
        spec, _ = self.tasks.create_task_spec(
            task_type="speech.reference_analyze", task_source="voice-lab", session_id=uuid4().hex,
            execution_profile={"reference_analysis": {
                "path": str(path.resolve()), "language": body.get("language", "auto"),
                "require_text": body.get("require_text", True),
                "separate_vocals": body.get("separate_vocals", False),
                "subtitle_text": body.get("subtitle_text", ""),
                "subtitle_format": body.get("subtitle_format", "vtt"),
            }},
        )
        return self.dispatcher.submit(spec.task_id)

    def reference_analysis(self, task_id):
        status = self.tasks.get_task(task_id)
        if status.task_type != "speech.reference_analyze":
            raise ValueError("此任务不是录音片段分析")
        # Task lookup above validates the identifier before using it as a filename.
        path = self.store.root / "_analyses" / (task_id + ".json")
        result = json.loads(path.read_text(encoding="utf-8")) if status.state == "completed" and path.exists() else None
        return status, result

    @_reference_file_operation
    def start_reference_transcription(self, body):
        """Explicit selection ASR never consults companion subtitles."""
        path = Path(str(body.get("path", "")))
        if not path.is_file():
            raise ValueError("请选择存在的录音文件")
        start, end = float(body.get("start", -1)), float(body.get("end", -1))
        if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
            raise ValueError("请选择有效的识别片段")
        language = body.get("language", "auto")
        if not isinstance(language, str) or not language.strip():
            raise ValueError("请选择录音语言")
        spec, _ = self.tasks.create_task_spec(
            task_type="speech.reference_analyze", task_source="voice-lab", session_id=uuid4().hex,
            execution_profile={"reference_analysis": {
                "operation": "transcribe_selection", "path": str(path.resolve()),
                "start": start, "end": end, "language": language,
            }},
        )
        return self.dispatcher.submit(spec.task_id)

    def transcribe_reference_selection(self, body, progress_callback):
        import soundfile as sf
        from tempfile import TemporaryDirectory
        from src.core.tts.audio_preprocessor import AudioPreprocessor

        progress_callback("读取录音并裁剪所选片段…", 1)
        original = self.store.inspect_reference(body["path"])
        start, end = body["start"], body["end"]
        if end > original["duration"]:
            raise ValueError("识别片段超出录音时间范围")
        staging = self.store.root / "_staging"
        staging.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="selection-asr-", dir=staging) as temporary:
            with sf.SoundFile(original["path"]) as audio:
                first, last = round(start * audio.samplerate), round(end * audio.samplerate)
                if last <= first:
                    raise ValueError("识别片段未包含音频采样")
                audio.seek(first)
                samples = audio.read(last - first, dtype="float32", always_2d=True)
                crop = Path(temporary) / "selection.wav"
                sf.write(crop, samples.mean(axis=1), audio.samplerate, subtype="PCM_16")
            progress_callback("已裁剪所选片段，准备 ASR 识别…", 20)
            segments = AudioPreprocessor(output_dir=temporary)._run_asr(
                str(crop), language=body["language"], progress_callback=progress_callback)
            progress_callback("ASR 识别完成，请试听核对原文", 100)
            transcript = " ".join(str(segment.get("text", "")).strip() for segment in segments).strip()
            if not transcript:
                raise ValueError("所选片段未识别到原文，请调整选段或录音语言")
            return {"transcript": transcript, "confirmed": False, "transcript_source": "asr",
                "start": start, "end": end, "language": body["language"],
                "segments": [{**segment, "start": start + max(0, min(end - start, float(segment["start"]))),
                    "end": start + max(0, min(end - start, float(segment["end"])))} for segment in segments]}

    def _execute_reference_analysis(self, spec, context):
        reported = 0.0

        def progress(message, percent):
            nonlocal reported
            if context.cancellation_requested:
                raise RuntimeError("片段分析已取消")
            reported = max(reported, min(percent / 100, 1.0))
            stage = "reference_analysis"
            for words, value in (
                (("读取录音", "检查音频", "原始音频"), "reference_read"),
                (("字幕",), "reference_subtitles"),
                (("分离",), "reference_separate"),
                (("转换",), "reference_decode"),
                (("ASR", "识别"), "reference_transcribe"),
                (("切割", "筛选", "合并", "VAD"), "reference_segment"),
                (("质量", "分析完成"), "reference_score"),
            ):
                if any(word in message for word in words):
                    stage = value
                    break
            context.update_progress(reported, message, stage=stage)

        body = spec.execution_profile["reference_analysis"]
        operation = self.transcribe_reference_selection if body.get("operation") == "transcribe_selection" else self.analyze_reference
        result = operation(body, progress_callback=progress)
        if context.cancellation_requested:
            raise RuntimeError("片段分析已取消")
        path = self.store.root / "_analyses" / (spec.task_id + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return result

    @_reference_file_operation
    def analyze_reference(self, body, progress_callback=None):
        from src.core.tts.audio_preprocessor import AudioPreprocessor
        if progress_callback:
            progress_callback("读取录音…", 1)
        original = self.store.inspect_reference(body["path"])
        analyzed = original
        directory = Path(self.store.root) / "_staging" / uuid4().hex
        directory.mkdir(parents=True, exist_ok=True)
        if progress_callback:
            progress_callback("检查同目录字幕与时间范围…", 2)
        subtitle, subtitle_path, warnings = self._reference_subtitle(original, body.get("language", "auto"), directory, body)
        if body.get("separate_vocals"):
            if progress_callback:
                progress_callback("正在分离人声…", 3)
            from src.config import config
            from src.core.engines import SeparatorEngineRuntime
            outputs = SeparatorEngineRuntime().separate(input_path=original["path"], output_dir=str(directory),
                model=str(config.get("processing.vocal_model", "htdemucs")), stems=["vocals"])
            analyzed = self.store.inspect_reference(outputs["vocals"])

        def analysis_progress(message, percent):
            if subtitle and not subtitle["language_verified"] and "匹配模式" in message:
                message = "复用字幕时间轴；字幕语言尚未与录音核验"
            if progress_callback:
                progress_callback(message, percent)

        result = AudioPreprocessor(output_dir=str(directory)).analyze_segments(
            audio_path=analyzed["path"],
            audio_language=subtitle["language"] if subtitle else body.get("language", "auto"),
            subtitle_path=subtitle_path,
            require_text=bool(subtitle) or body.get("require_text", True), progress_callback=analysis_progress)
        return {"original": original, "analyzed": analyzed, "segments": result.get("segments", []),
            "mode": result.get("mode", "manual"), "warnings": warnings + result.get("warnings", []),
            "transcript_source": "subtitle" if subtitle else "asr" if result.get("mode") == "asr" else "none",
            "subtitle": subtitle}

    @staticmethod
    def _validate_subtitle_input(body):
        text = body.get("subtitle_text", "")
        if not isinstance(text, str):
            raise ValueError("字幕内容必须是文本")
        if len(text.encode("utf-8")) > 5 * 1024 * 1024:
            raise ValueError("字幕超过 5 MB")
        if body.get("subtitle_format", "vtt") not in {"vtt", "srt"}:
            raise ValueError("字幕格式必须是 vtt 或 srt")

    def _reference_subtitle(self, original, language, directory, body):
        """Reuse only a same-name sidecar tied to unprocessed, inspected source audio."""
        from src.core.subtitles.companions import inspect_subtitle, is_source_subtitle
        from src.core.subtitles.text_utils import normalize_language_code
        source = original.get("companion_source_path")
        warnings = []
        self._validate_subtitle_input(body)
        if body.get("subtitle_text", "").strip():
            manual = directory / ("manual." + body.get("subtitle_format", "vtt"))
            manual.write_text(body["subtitle_text"], encoding="utf-8")
            # Explicitly loaded text takes precedence, even when invalid; do not
            # silently replace the user's selection with a different sidecar.
            candidates = [(manual, "手动加载字幕")]
        else:
            candidates = [(path, path.name) for path in companion_subtitle_paths(source)]
        requested = normalize_language_code(language)
        for candidate, name in candidates:
            try:
                if candidate.stat().st_size > 5 * 1024 * 1024:
                    raise ValueError("字幕超过 5 MB")
                # Snapshot the sidecar; validation and analysis use identical bytes.
                staged = directory / ("companion" + candidate.suffix.lower())
                staged.write_bytes(candidate.read_bytes())
                inspection = inspect_subtitle(staged)
                if not inspection["valid"]:
                    raise ValueError(inspection["reason"])
                entries = inspection["segments"]
                if not entries or any(
                    not str(entry.get("text", "")).strip()
                    or not all(math.isfinite(float(entry[key])) for key in ("start", "end"))
                    or not 0 <= float(entry["start"]) < float(entry["end"]) <= original["duration"]
                    for entry in entries
                ):
                    raise ValueError("字幕为空或时间范围超出当前录音")
                detected = inspection["language"]
                if detected in {"unknown", "mixed"}:
                    raise ValueError("无法确定字幕语言")
                if requested in {"auto", "unknown"}:
                    raise ValueError("录音语言尚未确定，不能将字幕当作原文；请明确语言或使用 ASR")
                if not is_source_subtitle(inspection, requested):
                    raise ValueError(f"字幕语言 {detected} 与录音所选语言 {requested} 不一致，可能是译文")
                warnings.append(f"已复用 {name}，语言与所选语言一致；仍需试听核对字幕原文。")
                return {"name": name, "language": detected, "language_verified": True}, str(staged), warnings
            except (ValueError, OSError, KeyError, TypeError) as exc:
                warnings.append(f"未使用 {name}：{exc}")
        return None, None, warnings

    def create_plan(self, body):
        plan = build_plan(body["text"])
        plan["use_recipe_defaults"] = body.get("use_recipe_defaults", body.get("segments") is None)
        if body.get("segments") is not None:
            plan["segments"] = deepcopy(body["segments"])
        validate_plan(plan["text"], plan)
        return self.store.create("plans", plan)

    def compile(self, recipe_id, plan_id, recipe_draft=None):
        recipe, _ = self._resolve_recipe_input(recipe_id, recipe_draft)
        return compile_recipe(recipe, self.store.get("plans", plan_id), self.assets())

    def snapshot(self, recipe_id):
        recipe, connection = self._resolve_recipe_input(recipe_id)
        return self._snapshot_recipe(recipe, connection)

    def pipeline_snapshot(self, stage):
        """Resolve either an optional saved rule or a task-owned engine recipe.

        No voice/rule/connection is created by readiness or task submission.
        Existing task snapshots remain on the recovery path, never re-resolved.
        """
        options = stage.get("options", {})
        if not isinstance(options, dict) or set(options) - {"speech_recipe_id", "speech_overrides", "speech_source", "voice", "speed", "language"}:
            raise ValueError("语音配置包含未支持的选项，请选择明确的 Speech 规则或声音来源")
        legacy_parameters = stage.get("provider_options", {})
        if not isinstance(legacy_parameters, dict) or set(legacy_parameters) - {"speech_snapshot"}:
            raise ValueError("引擎参数应放入 speech_source.provider_options，不能使用旧 TTS 参数层")
        provider_id, model = stage.get("provider"), stage.get("model")
        recipe_id = options.get("speech_recipe_id")
        if recipe_id:
            if set(options) - {"speech_recipe_id", "speech_overrides"}:
                raise ValueError("保存的规则不能同时附带声音、语速、语言或直接来源覆盖")
            recipe = self.store.get("recipes", recipe_id)
            if provider_id not in (None, "", "speech", recipe["provider_id"]):
                raise ValueError("自定义规则与当前 TTS 引擎不兼容")
            if model not in (None, "", "default", recipe["model"]):
                raise ValueError("自定义规则与当前 TTS 模型不兼容")
            if options.get("speech_source"):
                raise ValueError("自定义规则和直接声音来源不能同时指定")
            if "speech_overrides" not in options:
                return self.snapshot(recipe_id)
            from src.core.speech.overrides import apply_speech_overrides
            base_recipe = deepcopy(recipe)
            recipe, connection = self._resolve_recipe_input(recipe_id)
            effective = apply_speech_overrides(recipe, options["speech_overrides"], get_provider(recipe["provider_id"]))
            snapshot = self._snapshot_recipe(effective, connection)
            snapshot.update(base_recipe=base_recipe, speech_overrides=deepcopy(options["speech_overrides"]))
            return snapshot
        if "speech_overrides" in options:
            raise ValueError("本次微调需要先选择已保存音色")
        provider = get_provider(provider_id)
        source = options.get("speech_source", {})
        if not isinstance(source, dict) or set(source) - {"mode", "variant", "connection_ref", "provider_options",
                                                         "default_delivery", "default_emotion", "default_pause_ms"}:
            raise ValueError("直接声音配置包含未知字段")
        mode = source.get("mode")
        if not mode:
            compatible = [m for m in provider.modes if not model or model == "default" or not m["models"] or model in m["models"]]
            mode = next((m["id"] for m in compatible if provider.voice_sources(m["id"])["default"] is not None), None)
            if not mode and len(compatible) == 1:
                mode = compatible[0]["id"]
        descriptor = next((m for m in provider.modes if m["id"] == mode), None)
        if descriptor is None:
            raise ValueError("请选择当前引擎的发声模式")
        if not model or model == "default":
            if len(descriptor["models"]) != 1:
                raise ValueError("请明确选择 TTS 模型")
            model = descriptor["models"][0]
        catalog = provider.voice_sources(mode)
        variant = deepcopy(source.get("variant"))
        if variant is None:
            value = (options.get("voice") if mode == "builtin" else None) or catalog["default"]
            if not value:
                raise ValueError(catalog["description"] or "请指定声音来源")
            variant = {"kind": mode, "value": value}
        if "voice" in options and (not isinstance(variant, dict) or options["voice"] != variant.get("value")):
            raise ValueError("音色参数与当前声音来源不一致，请只保留一种明确来源")
        connection_ref = source.get("connection_ref")
        connection = self._recipe_connection({"provider_id": provider_id, "connection_ref": connection_ref})
        parameters = deepcopy(source.get("provider_options", {"schema_version": 1}))
        if not isinstance(parameters, dict):
            raise ValueError("引擎参数必须是对象")
        if "speed" in options:
            if "speed" not in provider.options_schema:
                raise ValueError("当前引擎不支持语速参数，请使用其声明的演绎选项")
            if "speed" in parameters and parameters["speed"] != options["speed"]:
                raise ValueError("重复语速参数不一致，请只保留一个值")
            parameters["speed"] = options["speed"]
        recipe = {"id": "pipeline-" + uuid4().hex, "revision": 1, "name": "主流程引擎配置",
                    "provider_id": provider_id, "model": model, "mode": mode,
                    "connection_ref": connection["id"], "variant": variant,
                    "language": options.get("language", "auto"), "provider_options": parameters}
        for field in ("default_delivery", "default_emotion", "default_pause_ms"):
            if field in source:
                recipe[field] = deepcopy(source[field])
        if isinstance(variant, dict) and variant.get("kind") == "reference":
            asset = self.store.get("assets", variant.get("value"))
            if asset.get("archived"):
                raise ValueError("参考素材已归档，请选择可用素材")
            self._validate_reference(recipe)
        return self._snapshot_recipe(recipe, connection)

    def _snapshot_recipe(self, recipe, connection):
        recipe, connection = deepcopy(recipe), deepcopy(connection)
        if connection["provider_id"] != recipe["provider_id"]:
            raise ValueError("连接已更换引擎，请保存新的配方")
        assets = self.assets()
        self._validate_reference(recipe)
        validation_plan = build_plan("配置校验。")
        validation_plan["use_recipe_defaults"] = True
        requests = compile_recipe(recipe, validation_plan, assets)
        # Only referenced immutable assets enter a task snapshot.
        used = recipe.get("variant", {}).get("value")
        selected_assets = {used: assets[used]} if used in assets else {}
        context = self.connection_context(connection)
        context.update(model=recipe["model"], mode=recipe["mode"])
        ready = get_provider(recipe["provider_id"]).probe(context)
        if not ready.get("ready"):
            raise ValueError(ready.get("detail") or "配方所需连接或运行环境未就绪")
        # Pin resolved local paths, so later runtime/model settings cannot redirect a task.
        if not get_provider(recipe["provider_id"]).remote:
            for field in ("model_path", "runtime"):
                if ready.get(field):
                    connection[field] = ready[field]
        return {"recipe": recipe, "connection": connection, "assets": selected_assets,
                "compiler_version": requests[0]["compiler_version"], "provider_version": requests[0]["provider_version"]}

    @_reference_file_operation
    def generate(self, experiment_id, body):
        if not isinstance(body, dict) or set(body) - {"recipe_id", "recipe_draft", "plan_id", "segment_id"}:
            raise ValueError("试听请求包含未知字段")
        if ("recipe_id" in body) == ("recipe_draft" in body):
            raise ValueError("recipe_id 与 recipe_draft 必须且只能提供一个")
        recipe, connection = self._resolve_recipe_input(body.get("recipe_id"), body.get("recipe_draft"))
        experiment = self.store.get("experiments", experiment_id)
        plan = self.store.get("plans", body.get("plan_id") or experiment["plan_id"])
        if plan["text_hash"] != self.store.get("plans", experiment["plan_id"])["text_hash"]:
            raise ValueError("试音文本已改变，请建立新的对比实验")
        snapshot = self._snapshot_recipe(recipe, connection)
        requests = compile_recipe(snapshot["recipe"], plan, snapshot["assets"])
        if body.get("segment_id"):
            requests = [r for r in requests if r["segment_id"] == body["segment_id"]]
            if not requests:
                raise ValueError("台词片段不存在")
        spec, status = self.tasks.create_task_spec(task_type="speech.generate", task_source="voice-lab",
            session_id=experiment_id, execution_profile={"speech_version": 2, "snapshot": snapshot,
                "requests": requests, "experiment_id": experiment_id, "plan_id": plan["id"], "regenerate": True})
        self.dispatcher.submit(spec.task_id)
        return status

    def _execute(self, spec, context):
        data = spec.execution_profile
        experiment = self.store.get("experiments", data["experiment_id"])
        return self.run_requests(data["requests"], data["snapshot"], task_id=spec.task_id,
            experiment_id=data["experiment_id"], plan_id=data["plan_id"],
            cancel_check=lambda: context.cancellation_requested, progress=context.update_progress,
            media_root=self._experiment_media_root(experiment))

    def _experiment_media_root(self, experiment):
        # Existing records retain their original paths; only new formal runs
        # carry a task-owned media root. Laboratory audio stays in the library.
        if experiment.get("kind") == "formal" and experiment.get("media_root"):
            return Path(experiment["media_root"])
        return Path(self.store.root)

    @_reference_file_operation
    def synthesize_text(self, snapshot, text, output_path):
        """Synchronous standalone entry using the same compiler and take runner."""
        import soundfile as sf
        target = Path(output_path).resolve()
        formats = {".wav": "WAV", ".flac": "FLAC", ".ogg": "OGG", ".mp3": "MP3"}
        format_name = formats.get(target.suffix.lower())
        if not format_name or format_name not in sf.available_formats():
            raise ValueError("输出扩展名须为当前音频库支持的 WAV、FLAC、OGG 或 MP3")
        plan = build_plan(text)
        plan["use_recipe_defaults"] = True
        requests = compile_recipe(snapshot["recipe"], plan, snapshot["assets"])
        if any(r["compiler_version"] != snapshot["compiler_version"] or
               r["provider_version"] != snapshot["provider_version"] for r in requests):
            raise ValueError("语音快照版本已改变，请重新提交")
        plan = self.store.create("plans", plan)
        # Compile against the saved plan so every take points at its actual segment.
        requests = compile_recipe(snapshot["recipe"], plan, snapshot["assets"])
        task_id = "speech-cli-" + uuid4().hex
        experiment_id = uuid4().hex
        media_root = target.parent / "speech" / experiment_id
        experiment = self.store.create("experiments", {"id": experiment_id, "name": "命令行配音",
            "kind": "formal", "task_id": task_id, "media_root": str(media_root),
            "plan_id": plan["id"], "snapshot": snapshot})
        takes = self.run_requests(requests, snapshot, task_id=task_id, experiment_id=experiment_id,
            plan_id=plan["id"], media_root=media_root)
        for take in takes:
            self.select({"experiment_id": experiment_id, "segment_id": take["segment_id"], "take_id": take["id"]})
        assembly = self.assemble(experiment["id"])
        samples, rate = sf.read(assembly["audio_path"], dtype="float32")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name("." + target.name + "." + uuid4().hex + ".tmp")
        try:
            sf.write(temporary, samples, rate, format=format_name)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return str(target)

    @_reference_file_operation
    def synthesize_timeline(self, snapshot, segments, output_path, task_id, cancel_check=lambda: False, reference_duration=0):
        """Formal dubbing uses the identical compiler/runner as laboratory takes."""
        text = "".join(s["text"] for s in segments)
        plan = build_plan(text)
        plan["segments"] = []
        timeline, cursor = {}, 0
        for index, segment in enumerate(segments):
            end = cursor + len(segment["text"])
            sid = f"sentence-{index + 1}"
            plan["segments"].append({"id": sid, "start": cursor, "end": end,
                "delivery": snapshot["recipe"].get("default_delivery", "normal"),
                "emotion": snapshot["recipe"].get("default_emotion", "neutral"), "pause_ms": snapshot["recipe"].get("default_pause_ms", 0)})
            timeline[sid] = {"start": segment["start_time"], "end": segment["end_time"]}
            cursor = end
        plan = self.store.create("plans", plan)
        experiment_id = uuid4().hex
        media_root = Path(output_path).resolve().parent / "speech" / experiment_id
        experiment = self.store.create("experiments", {"id": experiment_id, "name": f"正式配音 {task_id}", "plan_id": plan["id"],
            "task_id": task_id, "kind": "formal", "media_root": str(media_root),
            "snapshot": snapshot, "timeline": timeline, "reference_duration": reference_duration})
        requests = compile_recipe(snapshot["recipe"], plan, snapshot["assets"])
        if requests[0]["compiler_version"] != snapshot["compiler_version"]:
            raise ValueError("编译器版本已改变，请重新提交任务")
        if requests[0]["provider_version"] != snapshot.get("provider_version"):
            raise ValueError("引擎版本已改变，请重新提交任务")
        takes = self.run_requests(requests, snapshot, task_id=task_id, experiment_id=experiment["id"],
            plan_id=plan["id"], cancel_check=cancel_check, media_root=media_root)
        for take in takes:
            self.select({"experiment_id": experiment["id"], "segment_id": take["segment_id"], "take_id": take["id"]})
        return self.assemble(experiment["id"], output_path=output_path, timeline=timeline, reference_duration=reference_duration)

    def run_requests(self, requests, snapshot, *, task_id, experiment_id, plan_id, cancel_check=lambda: False, progress=None, media_root=None):
        context = self.connection_context(snapshot["connection"])
        context["assets"] = deepcopy(snapshot["assets"])
        outputs = []
        for index, request in enumerate(requests):
            request = deepcopy(request)
            request["connection_snapshot"] = deepcopy(snapshot["connection"])
            # Connection revisions and deployment options participate in identity.
            request["cache_key"] = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            request["id"] = request["cache_key"]
            if cancel_check():
                raise InterruptedError("已取消，后续台词未生成")
            provider = get_provider(request["provider_id"])
            take_id = uuid4().hex
            output = Path(media_root if media_root is not None else self.store.root) / "audio" / (take_id + ".wav")
            output.parent.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            try:
                connection_id = snapshot["connection"]["id"]
                with self._lock:
                    guard = self._connection_locks.setdefault(connection_id, threading.Lock())
                while not guard.acquire(timeout=.1):
                    if cancel_check():
                        raise InterruptedError("排队期间已取消")
                try:
                    audio = provider.synthesize(deepcopy(request), output, context, cancel_check)
                finally:
                    guard.release()
                if cancel_check():
                    raise InterruptedError("已取消，不采用未完成候选")
                import soundfile as sf
                info = sf.info(output)
                if info.frames < 1:
                    raise ValueError("引擎返回空音频")
                import numpy as np
                with sf.SoundFile(output) as stream:
                    decoded_frames = 0
                    for block in stream.blocks(blocksize=65536, dtype="float32"):
                        if not np.isfinite(block).all():
                            raise ValueError("引擎返回无效音频采样")
                        decoded_frames += len(block)
                    if decoded_frames != info.frames:
                        raise ValueError("引擎返回不完整音频")
                take = self.store.create("takes", {"id": take_id, "task_id": task_id,
                    "experiment_id": experiment_id, "plan_id": plan_id, "recipe_id": snapshot["recipe"]["id"],
                    "segment_id": request["segment_id"], "compiled_request": request,
                    "recipe_snapshot": deepcopy(snapshot["recipe"]), "status": "completed",
                    "audio_path": str(output), "audio": {**(audio or {}), "duration": info.duration,
                        "sample_rate": info.samplerate, "channels": info.channels, "format": info.format},
                    "elapsed_seconds": time.monotonic() - started})
                outputs.append(take)
                self.artifacts.register_artifact(task_id=task_id, artifact_type="audio.speech_take",
                    path=str(output), label=f"台词 {index + 1} 候选", preview_kind="audio", stage="tts",
                    metadata={"take_id": take_id, "experiment_id": experiment_id})
            except BaseException:
                if not any(t["id"] == take_id for t in outputs):
                    output.unlink(missing_ok=True)
                raise
            finally:
                provider.release()
            if progress:
                progress((index + 1) / len(requests), f"已生成 {index + 1}/{len(requests)} 句", stage="tts")
        return outputs

    @_reference_file_operation
    def save_rule_from_take(self, take_id, body):
        if not isinstance(body, dict) or set(body) - {"name", "description"}:
            raise ValueError("仅提供名称和说明；设置来自所选试听快照")
        if not isinstance(body.get("name"), str) or not body["name"].strip():
            raise ValueError("请填写预设名称")
        take = self.store.get("takes", take_id)
        if take.get("status") != "completed":
            raise ValueError("只能保存已完成试听的设置")
        recipe = deepcopy(take.get("recipe_snapshot"))
        if recipe is None:
            # Legacy takes always referenced an immutable saved recipe.
            recipe = self.store.get("recipes", take["recipe_id"])
        request = take["compiled_request"]
        if any(request.get(key) != recipe.get(key) for key in ("provider_id", "model", "mode")):
            raise ValueError("试听快照与执行记录不一致，不能保存")
        for key in ("id", "revision", "previous_id", "created_at", "updated_at", "voice_id"):
            recipe.pop(key, None)
        recipe["provider_options"] = deepcopy(request["parameters"]["options"])
        recipe["provider_options"].pop("device", None)
        recipe["variant"] = deepcopy(request["parameters"]["variant"])
        recipe["language"] = request["parameters"]["language"]
        recipe.update(name=body["name"].strip(), description=body.get("description", ""),
                      default_delivery=request["parameters"]["delivery"],
                      default_emotion=request["parameters"]["emotion"], default_pause_ms=request["pause_ms"])
        return self.save_rule(recipe)

    def experiment(self, experiment_id):
        experiment = self.store.get("experiments", experiment_id)
        experiment["takes"] = [t for t in self.store.list("takes") if t["experiment_id"] == experiment_id]
        experiment["selections"] = [s for s in self.store.list("selections") if s["experiment_id"] == experiment_id]
        return experiment

    @_reference_file_operation
    def select(self, body):
        take = self.store.get("takes", body["take_id"])
        if take["experiment_id"] != body["experiment_id"] or take["segment_id"] != body["segment_id"]:
            raise ValueError("候选不属于这句台词")
        prior = next((s for s in self.store.list("selections") if s["experiment_id"] == body["experiment_id"] and s["segment_id"] == body["segment_id"]), None)
        with self._lock:
            return self.store.update("selections", prior["id"], body, expected_revision=prior["revision"]) if prior else self.store.create("selections", body)

    def record_formal_mix(self, experiment_id, source_path, mix_options):
        source = Path(source_path)
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return self.store.update("experiments", experiment_id, {"mix_context": {
            "source_path": str(source), "source_sha256": digest.hexdigest(), **mix_options}})

    def _align_take(self, take, slot_duration, *, media_root=None):
        """Derived duration-fit audio; raw takes remain immutable and reusable."""
        import soundfile as sf
        import subprocess
        from src.utils import get_ffmpeg
        duration = sf.info(take["audio_path"]).duration
        if slot_duration <= 0:
            raise ValueError("台词停顿超过字幕时段，请调整演绎方案")
        ratio = max(1.0, duration / slot_duration)
        if ratio == 1:
            return take["audio_path"], ratio
        key = hashlib.sha256(f"{take['id']}:{slot_duration:.9f}:atempo-v1".encode()).hexdigest()
        target = Path(media_root if media_root is not None else self.store.root) / "aligned" / (key + ".wav")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            steps, factor = [], ratio
            while factor > 2:
                steps.append("atempo=2")
                factor /= 2
            steps.append(f"atempo={factor:.9f}")
            temporary = target.with_suffix(".pending.wav")
            try:
                result = subprocess.run([get_ffmpeg(), "-v", "error", "-y", "-i", take["audio_path"],
                    "-af", ",".join(steps), str(temporary)], capture_output=True, timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode or not temporary.exists() or sf.info(temporary).frames == 0:
                    raise ValueError("音频时长适配失败，原始候选仍保留")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return str(target), ratio

    @_reference_file_operation
    def assemble(self, experiment_id, *, output_path=None, timeline=None, reference_duration=0):
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        from math import gcd
        experiment = self.experiment(experiment_id)
        media_root = self._experiment_media_root(experiment)
        timeline = timeline if timeline is not None else experiment.get("timeline")
        reference_duration = reference_duration or experiment.get("reference_duration", 0)
        plan = self.store.get("plans", experiment["plan_id"])
        selected = {s["segment_id"]: self.store.get("takes", s["take_id"]) for s in experiment["selections"]}
        rate, cursor, chunks, processing = 44100, 0, [], []
        for segment in plan["segments"]:
            take = selected.get(segment["id"])
            if take is None:
                raise ValueError("请先为每句台词选择真实候选")
            pause = take["compiled_request"].get("pause_ms", 0) / 1000
            aligned_path, ratio = self._align_take(take, timeline[segment["id"]]["end"] - timeline[segment["id"]]["start"] - pause, media_root=media_root) if timeline else (take["audio_path"], 1)
            audio, source_rate = sf.read(aligned_path, dtype="float32", always_2d=True)
            audio = audio.mean(axis=1)
            if source_rate != rate:
                divisor = gcd(source_rate, rate)
                audio = resample_poly(audio, rate // divisor, source_rate // divisor)
            start = round(timeline[segment["id"]]["start"] * rate) if timeline else cursor
            chunks.append((start, audio))
            cursor = start + len(audio) + round(pause * rate)
            processing.append({"segment_id": segment["id"], "take_id": take["id"], "start": start / rate,
                "duration": len(audio) / rate, "pause_ms": pause * 1000, "operation": "atempo_resample_and_place" if ratio > 1 else "resample_and_place",
                "time_stretch": ratio, "aligned_path": aligned_path})
        length = max([round(reference_duration * rate), cursor, *[start + len(a) for start, a in chunks]])
        if length <= 0:
            raise ValueError("没有可组装音频")
        mixed = np.zeros(length, dtype="float32")
        for start, audio in chunks:
            mixed[start:start + len(audio)] += audio
        assembly_id = uuid4().hex
        target = media_root / "assemblies" / (assembly_id + ".wav")
        target.parent.mkdir(parents=True, exist_ok=True)
        sf.write(target, np.clip(mixed, -1, 1), rate, subtype="PCM_16")
        mixed_path = None
        if experiment.get("mix_context"):
            from src.mixer import Mixer
            mix = experiment["mix_context"]
            source = Path(mix["source_path"])
            digest = hashlib.sha256()
            with source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != mix["source_sha256"]:
                raise ValueError("原混音素材已改变，不能覆盖采用结果")
            mixed_path = target.with_name(assembly_id + "-mix.wav")
            Mixer(original_volume=mix["original_volume"], tts_volume_ratio=mix["tts_volume_ratio"],
                tts_delay_ms=mix["tts_delay_ms"]).mix(original_path=str(source), tts_path=str(target), output_path=str(mixed_path))
        assembly = self.store.create("assemblies", {"id": assembly_id, "experiment_id": experiment_id,
            "selection_ids": [s["id"] for s in experiment["selections"]], "selections": experiment["selections"],
            "processing": processing, "audio_path": str(target), "mixed_path": str(mixed_path) if mixed_path else None,
            "sample_rate": rate, "duration": length / rate})
        if output_path:
            import shutil
            shutil.copyfile(target, output_path)
        return assembly

    def auto_performance(self, plan_id, connection_ref=None):
        """Ask only for bounded intentions; never accept replacement text or providers."""
        import requests
        from src.config import config
        from src.provider_profiles import profiles_for
        profiles = profiles_for(config.to_dict())
        selected = connection_ref or profiles.get("active_llm")
        connection = next((p for p in profiles["llm"] if p["id"] == selected), None)
        if not connection or not connection.get("api_key"):
            raise ValueError("请先配置用于演绎规划的 LLM 连接")
        plan = self.store.get("plans", plan_id)
        prompt = {"text": plan["text"], "text_hash": plan["text_hash"], "segments": plan["segments"]}
        response = requests.post(connection["base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + connection["api_key"]}, timeout=90,
            json={"model": connection["model"], "messages": [
                {"role": "system", "content": "Return JSON only: {text_hash,segments:[{id,start,end,delivery,emotion,pause_ms}]}. Keep hash, ids and offsets EXACTLY. Do not return or rewrite text. delivery normal/soft/whisper; emotion neutral/happy/sad/calm; pause_ms integer 0..3000. Never choose a provider or voice."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]})
        if response.status_code != 200:
            raise ValueError(f"演绎规划请求失败（HTTP {response.status_code}），未修改原文")
        raw = response.json()["choices"][0]["message"]["content"]
        proposed = json.loads(raw)
        if set(proposed) != {"text_hash", "segments"} or proposed["text_hash"] != plan["text_hash"]:
            raise ValueError("演绎规划修改了原文标识，已拒绝")
        original = [(s["id"], s["start"], s["end"]) for s in plan["segments"]]
        if [(s["id"], s["start"], s["end"]) for s in proposed["segments"]] != original:
            raise ValueError("演绎规划遗漏或改变了台词位置，已拒绝")
        return self.create_plan({"text": plan["text"], "segments": proposed["segments"]})


_service = None
_lock = threading.Lock()


def get_speech_service():
    global _service
    with _lock:
        if _service is None:
            _service = SpeechService()
    return _service
