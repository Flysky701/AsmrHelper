"""Stage-boundary recovery. Checkpoints never represent partially executed work."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import shutil

from src.app.persistence.recovery_store import file_identity, fingerprint


class PipelineRecovery:
    # These providers consume their complete task-bound synthesis settings.
    # Local engines additionally resolve mutable voice profiles, prompt caches,
    # default weights, and (VoxCPM2) denoisers outside the plan. Their loaded
    # singleton state has no verifiable revision. Hashing only the current files
    # would incorrectly attest to the model which produced an earlier output.
    # Unknown/new providers must opt in only after their dependencies are audited.
    _REUSABLE_TTS_PROVIDERS = frozenset({"edge", "openai_compatible"})
    _REUSABLE_SPEECH_PROVIDERS = frozenset({"edge", "openai_compatible", "fish_audio", "mimo_audio", "qwen3", "voxcpm2"})

    def __init__(self, store, task_id, source_task_id, plan, connection_fingerprint=""):
        self.store = store
        self.task_id = task_id
        self.source_task_id = source_task_id
        self.plan = plan
        self.connection_fingerprint = connection_fingerprint
        self._reuse = bool(source_task_id)
        self._upstream = fingerprint({"version": 1, "input": file_identity(plan.input_path),
            "companion": file_identity(plan.companion_subtitle_path) if plan.companion_subtitle_path else None})
        self._models = {}
        self._speech_audit = None

    def _uses_speech_snapshot(self):
        # Production plans retain the concrete provider. Presence (rather than
        # truthiness) ensures malformed snapshots fail instead of falling back.
        return self.plan.tts.provider == "speech" or "speech_snapshot" in self.plan.tts.provider_options

    def _speech_identity(self):
        """Attest only to the new immutable recipe, never to global TTS defaults."""
        from src.core.speech.compiler import COMPILER_VERSION
        from src.core.speech.providers import get_provider
        snapshot = self.plan.tts.provider_options.get("speech_snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("语音恢复缺少固定配置快照，请建立新任务")
        recipe, connection, assets = snapshot.get("recipe"), snapshot.get("connection"), snapshot.get("assets", {})
        if not isinstance(recipe, dict) or not isinstance(connection, dict) or not isinstance(assets, dict):
            raise ValueError("语音恢复快照不完整，请建立新任务")
        if snapshot.get("compiler_version") != COMPILER_VERSION:
            raise ValueError("语音编译器版本已改变，请建立新任务")
        provider_id = recipe.get("provider_id")
        if provider_id not in self._REUSABLE_SPEECH_PROVIDERS:
            raise ValueError("该语音引擎尚未通过阶段恢复审计，请建立新任务")
        if self.plan.tts.provider not in {"speech", provider_id}:
            raise ValueError("语音引擎与固定配置快照不符，请建立新任务")
        provider = get_provider(provider_id)
        if snapshot.get("provider_version", provider.version) != provider.version:
            raise ValueError("语音引擎版本已改变，请建立新任务")
        if connection.get("provider_id") != provider_id or connection.get("id") != recipe.get("connection_ref"):
            raise ValueError("语音连接与固定配方不符，请建立新任务")
        def check_public(value):
            if isinstance(value, dict):
                if any(key.lower() in {"api_key", "credential", "token", "password", "authorization"} for key in value):
                    raise ValueError("语音恢复连接必须仅包含凭据引用")
                for item in value.values():
                    check_public(item)
            elif isinstance(value, list):
                for item in value:
                    check_public(item)
        check_public(connection)
        provider.validate(recipe, assets)
        reference_files = {}
        if recipe["variant"]["kind"] == "reference":
            aid = recipe["variant"]["value"]
            asset = assets[aid]
            try:
                identity = file_identity(asset["path"])
            except (OSError, KeyError, TypeError):
                raise ValueError("语音参考素材缺失，不能恢复原任务，请建立新任务") from None
            if identity["sha256"] != asset.get("sha256"):
                raise ValueError("语音参考素材已改变，不能恢复原任务，请建立新任务")
            reference_files[aid] = identity
        model_identity = None
        if not provider.remote:
            from src.core.resources.model_reference import resolve_model_reference
            reference = connection.get("model_path") or resolve_model_reference(recipe["model"])
            directory = Path(reference)
            if not directory.is_dir():
                raise ValueError("语音模型目录缺失，不能恢复原任务，请建立新任务")
            # Include weights, tokenizer, config and local model implementation.
            # Files are hashed before inference, with no singleton model fallback.
            files = [item for item in sorted(directory.rglob("*")) if item.is_file()]
            if not (directory / "config.json").is_file() or not any(item.suffix in {".safetensors", ".bin", ".pth", ".pt"} for item in files):
                raise ValueError("语音模型权重或配置缺失，不能恢复原任务，请建立新任务")
            model_identity = {"path": str(directory.resolve()), "files": [file_identity(item) for item in files]}
        return {"version": 1, "provider_id": provider_id, "provider_version": provider.version,
            "compiler_version": COMPILER_VERSION, "recipe": fingerprint(recipe),
            "connection": fingerprint(connection), "reference_files": reference_files,
            "model": model_identity}

    def _fingerprint(self, stage):
        attribute = {"separate": "separation", "align": "alignment", "translate": "translation",
                     "export": "subtitle"}.get(stage, stage)
        binding = getattr(self.plan, attribute)
        model = getattr(binding, "model", "")
        if stage == "tts" and self._uses_speech_snapshot():
            self._speech_audit = self._speech_identity()
            # A completed synthesis must never be regenerated implicitly when
            # its producer's dependencies can no longer be attested to.
            prior = self.store.checkpoint(self.source_task_id, "tts") if self.source_task_id else None
            if prior and prior.get("payload", {}).get("speech_identity") != self._speech_audit:
                raise ValueError("语音快照、引擎版本、素材或模型已改变；不能复用或自动重做已完成语音，请明确建立新任务")
            return fingerprint({"version": 2, "stage": stage, "binding": asdict(binding),
                "speech_identity": self._speech_audit, "upstream": self._upstream,
                "language": [self.plan.source_lang, self.plan.target_lang]})
        if model and model not in self._models:
            from src.core.resources.model_reference import resolve_model_reference
            reference = resolve_model_reference(model)
            path = Path(reference)
            files = sorted(path.rglob("*")) if path.is_dir() else [path]
            self._models[model] = {"reference": reference, "files": [
                file_identity(item) for item in files if item.is_file()]}
        connection = self.connection_fingerprint
        if isinstance(connection, dict):
            connection = connection.get("llm" if stage == "translate" else "tts", connection)
        return fingerprint({"version": 1, "stage": stage, "binding": asdict(binding),
            "model": self._models.get(model), "upstream": self._upstream,
            "language": [self.plan.source_lang, self.plan.target_lang] if stage in ("translate", "tts", "export")
                else self.plan.source_lang,
            "connection": connection if stage in ("translate", "tts") else None})

    def run(self, stage, operation, results, segments, translations, by_product_dir, mix_path):
        stage_fingerprint = self._fingerprint(stage)
        reusable = (stage != "tts" or self.plan.tts.provider in self._REUSABLE_TTS_PROVIDERS
                    or (self._uses_speech_snapshot() and self._speech_audit is not None))
        record = (self.store.validated(self.source_task_id, stage, stage_fingerprint)
                  if self._reuse and reusable else None)
        if (stage == "tts" and self._uses_speech_snapshot() and self.source_task_id
                and not record and self.store.checkpoint(self.source_task_id, stage)):
            raise ValueError("已完成语音的检查点或上游结果已失效；请明确建立新任务，避免恢复时重复生成与计费")
        if record:
            payload = deepcopy(record["payload"])
            mapping = {}
            for item in record["files"]:
                original = Path(item["original"])
                old_root = Path(payload["output_dir"])
                try:
                    destination = by_product_dir / original.relative_to(old_root)
                except ValueError:
                    destination = mix_path if stage == "mix" else by_product_dir / original.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item["path"], destination)
                mapping[str(original)] = str(destination)
            def remap(value):
                if isinstance(value, dict):
                    return {key: remap(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [remap(item) for item in value]
                if isinstance(value, str):
                    return mapping.get(value, value)
                return value
            payload = remap(payload)
            # Only merge this stage's changes, preserving current attempt paths.
            results.update(payload["results"])
            results["steps"].update(payload["steps"])
            segments[:] = payload["segments"]
            translations[:] = payload["translations"]
            value = Path(payload["value"]) if payload["path_value"] else payload["value"]
            outputs = list(mapping.values())
            payload["output_dir"] = str(by_product_dir)
            self.store.commit(self.task_id, stage, stage_fingerprint, payload, outputs)
        else:
            # A missing/invalid upstream invalidates every downstream checkpoint.
            self._reuse = False
            before = deepcopy(results)
            value = operation()
            if results["step_errors"]:
                raise RuntimeError(f"{stage} 阶段失败: {next(iter(results['step_errors'].values()))}")
            if stage == "tts" and self._speech_audit is not None and self._speech_identity() != self._speech_audit:
                raise ValueError("语音生成期间模型、素材或引擎版本发生变化，不能保存可恢复检查点，请建立新任务")
            if stage == "export" and segments and not value:
                raise RuntimeError("字幕导出失败")
            changes = {key: deepcopy(item) for key, item in results.items()
                       if key != "steps" and item != before.get(key)}
            steps = {key: deepcopy(item) for key, item in results["steps"].items()
                     if item != before["steps"].get(key)}
            outputs = []
            for item in list(changes.values()) + [item.get("output") for item in steps.values()] + [value]:
                if isinstance(item, (str, Path)) and Path(item).is_file():
                    outputs.append(str(Path(item).resolve()))
            # Missing declared outputs must fail, not produce a reusable success.
            for step in steps.values():
                if step.get("output") and not Path(step["output"]).is_file():
                    raise RuntimeError(f"{stage} 阶段产物缺失")
            payload = {"output_dir": str(by_product_dir), "results": changes, "steps": steps,
                "segments": deepcopy(segments), "translations": deepcopy(translations),
                "value": str(value) if isinstance(value, Path) else deepcopy(value),
                "path_value": isinstance(value, Path)}
            if stage == "tts" and self._speech_audit is not None:
                payload["speech_identity"] = deepcopy(self._speech_audit)
            self.store.commit(self.task_id, stage, stage_fingerprint, payload, outputs)
        self._upstream = stage_fingerprint
        return value
