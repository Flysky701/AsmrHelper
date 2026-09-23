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

    def _fingerprint(self, stage):
        attribute = {"separate": "separation", "align": "alignment", "translate": "translation",
                     "export": "subtitle"}.get(stage, stage)
        binding = getattr(self.plan, attribute)
        model = getattr(binding, "model", "")
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
        reusable = stage != "tts" or self.plan.tts.provider in self._REUSABLE_TTS_PROVIDERS
        record = (self.store.validated(self.source_task_id, stage, stage_fingerprint)
                  if self._reuse and reusable else None)
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
            self.store.commit(self.task_id, stage, stage_fingerprint, payload, outputs)
        self._upstream = stage_fingerprint
        return value
