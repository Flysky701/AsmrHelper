"""Review and confirm weight removal with live reference/ownership checks."""
from contextlib import contextmanager, nullcontext
import hashlib
import json
from pathlib import Path

from src.core.resources.model_removal import removal_evidence
from src.core.speech.store import reference_file_guard
from src.workspace_paths import freeze_directories
from .speech_cleanup_service import references


class ModelRemovalService:
    def __init__(self, models, speech=None, catalog=None, settings=None):
        self.models = models
        if speech is None:
            from .speech_service import get_speech_service
            speech = get_speech_service()
        if catalog is None:
            from .preset_catalog_service import get_preset_catalog_service
            catalog = get_preset_catalog_service()
        if settings is None:
            from src.config import config
            settings = config.to_dict
        self.speech, self.catalog, self.settings = speech, catalog, settings
        self.batches = None
        if getattr(speech.tasks, "_state_store", None) is not None:
            from .batch_run_service import get_batch_run_service
            self.batches = get_batch_run_service()

    @contextmanager
    def guard(self):
        from .preset_catalog_service import _write_lock
        with reference_file_guard(), (self.batches.history_deletion_guard() if self.batches else nullcontext()), self.speech.dispatcher.history_deletion_guard(), self.speech.tasks.history_deletion_guard():
            with _write_lock, self.speech.store._locked():
                lock = self.models.core_service._install_lock
                if not lock.acquire(blocking=False):
                    raise ValueError("模型安装或环境准备仍在进行，请稍后重试")
                try:
                    yield
                finally:
                    lock.release()

    @freeze_directories
    def preview(self, model_id):
        with self.guard():
            return self._preview(model_id)

    def _preview(self, model_id):
        entry = self.models.core_service.get_model(model_id)
        blockers, files, path = [], [], None
        try:
            path, files = removal_evidence(entry)
        except (ValueError, OSError) as exc:
            blockers.append(str(exc))
        tasks = self.speech.tasks.history_snapshot()
        if any(status.state not in {"completed", "failed", "cancelled", "skipped"}
               or self.speech.dispatcher.has_live_worker(status.task_id) for _, status in tasks):
            blockers.append("存在未结束任务或尚未退出的工作线程")
        provider = entry.provider or entry.engine
        if entry.category != "tts":
            registry = self.models._get_registry(entry.category)
            if registry.is_loaded(provider):
                blockers.append("模型仍在内存中，请先卸载模型")
        else:
            from src.core.speech.providers import _LOCAL_LOCK
            if _LOCAL_LOCK.locked():
                blockers.append("本地声音引擎正在运行")
        ids = {entry.id, *entry.capability_models}
        if entry.upstream_name:
            ids.add(entry.upstream_name)
        paths = [path] if path else []
        state = self.speech.store._read()
        evidence = {"声音数据": state, "任务历史": tasks, "当前设置": self.settings(),
                    "工作流": self.catalog.list_presets() + self.catalog.list_archived_presets()}
        if self.batches is not None:
            batches = self.batches.history_snapshot()
            evidence["批任务"] = [batches, getattr(self.batches, "_graph_snapshots", {})]
            if any(batch.state not in {"completed", "completed_with_errors", "cancelled", "interrupted", "history_deleted"} for batch in batches):
                blockers.append("存在未结束批任务")
        persisted = getattr(self.speech.tasks, "_state_store", None)
        if persisted is not None:
            evidence["持久任务与恢复记录"] = persisted.deletion_inventory()
        evidence["声音回收区"] = [json.loads((self.speech.store.root / "_trash" / id / "manifest.json").read_text(encoding="utf-8"))
                               for id in state.get("cleanup_receipts", [])]
        for label, data in evidence.items():
            if references(data, ids, paths):
                blockers.append(f"{label}仍引用此模型")
        for other in self.models.core_service.list_models(kind="local"):
            if other.id == entry.id:
                continue
            if model_id in other.required_assets + other.recommended_assets:
                if other.resolved_install_dir().exists():
                    blockers.append(f"已安装模型 {other.id} 依赖此权重")
            other_path = other.resolved_install_dir().resolve()
            if path and (other_path == path or other_path.is_relative_to(path) or path.is_relative_to(other_path)):
                blockers.append(f"目录与模型 {other.id} 重叠")
        payload = {"model_id": model_id, "path": str(path) if path else None, "files": files,
                   "bytes": sum(file["bytes"] for file in files), "blockers": sorted(set(blockers)),
                   "recoverable": False}
        payload["token"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return payload

    @freeze_directories
    def execute(self, model_id, token, confirmed=False):
        if confirmed is not True or not isinstance(token, str) or not token:
            raise ValueError("请先预览影响并确认本次权重删除")
        with self.guard():
            preview = self._preview(model_id)
            if preview["token"] != token:
                raise ValueError("模型目录或引用已改变，请重新预览")
            if preview["blockers"]:
                raise ValueError("；".join(preview["blockers"]))
            return self.models._run_model_operation(action="remove", model_id=model_id,
                runner=lambda: self.models.core_service.remove(model_id))
