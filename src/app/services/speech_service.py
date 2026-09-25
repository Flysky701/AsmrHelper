"""VoiceLab's persistent recipes, immutable synthesis runs and segment selection."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from src.core.speech.store import SpeechStore, build_plan, validate_plan
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

    def library(self):
        data = {name: self.store.list(name) for name in ("voices", "recipes", "assets", "experiments", "takes", "plans", "selections", "assemblies", "connections")}
        for connection in data["connections"]:
            connection["credential_configured"] = self._credential_path(connection).exists()
        return data

    def _credential_path(self, connection):
        ref = str(connection.get("credential_ref", ""))
        if not ref or any(c not in "0123456789abcdef" for c in ref):
            return Path(self.store.root) / "credentials" / "missing"
        return Path(self.store.root) / "credentials" / (ref + ".json")

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

    def save_recipe(self, body):
        data = self._prepare_recipe(body)
        voice = self.store.get("voices", data["voice_id"])
        if voice.get("bindings") and not any(b["provider_id"] == data["provider_id"] for b in voice["bindings"]):
            raise ValueError("请先为此声音添加对应引擎实现")
        return self.store.create("recipes", data)

    def _prepare_recipe(self, body):
        data = deepcopy(body)
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
        connection = self.store.get("connections", data["connection_ref"])
        if connection["provider_id"] != data["provider_id"]:
            raise ValueError("配方与连接的引擎不一致")
        # The compiler, not UI visibility, is authoritative for provider options.
        probe_plan = build_plan("配置校验。")
        for segment in probe_plan["segments"]:
            segment.update(delivery=data.get("default_delivery", "normal"), emotion=data.get("default_emotion", "neutral"), pause_ms=data.get("default_pause_ms", 0))
        compile_recipe(data, probe_plan, self.assets())
        return data

    def save_rule(self, body):
        """Save a single-engine generation rule without a separate voice wizard."""
        data = deepcopy(body)
        if data.get("mode") not in {"reference", "design"}:
            raise ValueError("生成规则仅支持参考音频或声音设计")
        variant = data.get("variant")
        if not isinstance(variant, dict) or variant.get("kind") != data["mode"]:
            raise ValueError("规则来源必须与生成模式一致")
        if variant.get("style", "normal") != "normal" or any(
            key in data for key in ("default_delivery", "default_emotion", "default_pause_ms")
        ):
            raise ValueError("演绎选项属于试音记录，不能保存为声音标签")
        variant["style"] = "normal"
        if data["mode"] == "reference":
            asset = self.store.get("assets", variant.get("value"))
            if asset.get("archived"):
                raise ValueError("参考素材已归档，请选择可用素材")
            reference = get_provider(data.get("provider_id")).capabilities(
                data.get("model"), data["mode"]
            ).get("reference", {})
            if reference.get("transcript_required") and asset.get("confirmed") is not True:
                raise ValueError("此引擎需要已核对转录的参考素材，请先确认转录")
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
        return self.store.active_recipes(include_archived=include_archived)

    def archive_rule(self, recipe_id, archived=True):
        return self.store.archive_recipe(recipe_id, archived=archived)

    def assets(self):
        return {a["id"]: a for a in self.store.list("assets")}

    def analyze_reference(self, body):
        from src.core.tts.audio_preprocessor import AudioPreprocessor
        original = self.store.inspect_reference(body["path"])
        analyzed = original
        directory = Path(self.store.root) / "_staging" / uuid4().hex
        directory.mkdir(parents=True, exist_ok=True)
        if body.get("separate_vocals"):
            from src.config import config
            from src.core.engines import SeparatorEngineRuntime
            outputs = SeparatorEngineRuntime().separate(input_path=original["path"], output_dir=str(directory),
                model=str(config.get("processing.vocal_model", "htdemucs")), stems=["vocals"])
            analyzed = self.store.inspect_reference(outputs["vocals"])
        result = AudioPreprocessor(output_dir=str(directory)).analyze_segments(
            audio_path=analyzed["path"], audio_language=body.get("language", "zh"), require_text=True)
        return {"original": original, "analyzed": analyzed, "segments": result.get("segments", [])}

    def create_plan(self, body):
        plan = build_plan(body["text"])
        if body.get("segments") is not None:
            plan["segments"] = deepcopy(body["segments"])
            validate_plan(plan["text"], plan)
        return self.store.create("plans", plan)

    def compile(self, recipe_id, plan_id):
        return compile_recipe(self.store.get("recipes", recipe_id), self.store.get("plans", plan_id), self.assets())

    def snapshot(self, recipe_id):
        recipe = self.store.get("recipes", recipe_id)
        connection = self.store.get("connections", recipe["connection_ref"])
        if connection["provider_id"] != recipe["provider_id"]:
            raise ValueError("连接已更换引擎，请保存新的配方")
        assets = self.assets()
        requests = compile_recipe(recipe, build_plan("配置校验。"), assets)
        # Only referenced immutable assets enter a task snapshot.
        used = recipe.get("variant", {}).get("value")
        selected_assets = {used: assets[used]} if used in assets else {}
        context = self.connection_context(connection)
        context.update(model=recipe["model"], mode=recipe["mode"])
        ready = get_provider(recipe["provider_id"]).probe(context)
        if not ready.get("ready"):
            raise ValueError(ready.get("detail") or "配方所需连接或运行环境未就绪")
        return {"recipe": recipe, "connection": connection, "assets": selected_assets,
                "compiler_version": requests[0]["compiler_version"], "provider_version": requests[0]["provider_version"]}

    def generate(self, experiment_id, body):
        experiment = self.store.get("experiments", experiment_id)
        plan = self.store.get("plans", body.get("plan_id") or experiment["plan_id"])
        if plan["text_hash"] != self.store.get("plans", experiment["plan_id"])["text_hash"]:
            raise ValueError("试音文本已改变，请建立新的对比实验")
        snapshot = self.snapshot(body["recipe_id"])
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
        return self.run_requests(data["requests"], data["snapshot"], task_id=spec.task_id,
            experiment_id=data["experiment_id"], plan_id=data["plan_id"],
            cancel_check=lambda: context.cancellation_requested, progress=context.update_progress)

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
        experiment = self.store.create("experiments", {"name": f"正式配音 {task_id}", "plan_id": plan["id"],
            "task_id": task_id, "kind": "formal", "snapshot": snapshot, "timeline": timeline, "reference_duration": reference_duration})
        requests = compile_recipe(snapshot["recipe"], plan, snapshot["assets"])
        if requests[0]["compiler_version"] != snapshot["compiler_version"]:
            raise ValueError("编译器版本已改变，请重新提交任务")
        if requests[0]["provider_version"] != snapshot.get("provider_version"):
            raise ValueError("引擎版本已改变，请重新提交任务")
        takes = self.run_requests(requests, snapshot, task_id=task_id, experiment_id=experiment["id"],
            plan_id=plan["id"], cancel_check=cancel_check)
        for take in takes:
            self.select({"experiment_id": experiment["id"], "segment_id": take["segment_id"], "take_id": take["id"]})
        return self.assemble(experiment["id"], output_path=output_path, timeline=timeline, reference_duration=reference_duration)

    def run_requests(self, requests, snapshot, *, task_id, experiment_id, plan_id, cancel_check=lambda: False, progress=None):
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
            output = Path(self.store.root) / "audio" / (take_id + ".wav")
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
                    "segment_id": request["segment_id"], "compiled_request": request, "status": "completed",
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

    def experiment(self, experiment_id):
        experiment = self.store.get("experiments", experiment_id)
        experiment["takes"] = [t for t in self.store.list("takes") if t["experiment_id"] == experiment_id]
        experiment["selections"] = [s for s in self.store.list("selections") if s["experiment_id"] == experiment_id]
        return experiment

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

    def _align_take(self, take, slot_duration):
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
        target = Path(self.store.root) / "aligned" / (key + ".wav")
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

    def assemble(self, experiment_id, *, output_path=None, timeline=None, reference_duration=0):
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        from math import gcd
        experiment = self.experiment(experiment_id)
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
            aligned_path, ratio = self._align_take(take, timeline[segment["id"]]["end"] - timeline[segment["id"]]["start"] - pause) if timeline else (take["audio_path"], 1)
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
        target = Path(self.store.root) / "assemblies" / (assembly_id + ".wav")
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
