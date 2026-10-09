"""Reference checks for local LLM profile deletion; never call provider accounts."""
from contextlib import ExitStack, contextmanager


def references_profile(profile, connection_id):
    nodes = profile.get("graph", {}).get("nodes", [])
    if any(node.get("kind") == "translate" and node.get("options", {}).get("connection_ref") == connection_id
           for node in nodes):
        return True
    stages = profile.get("stages", {})
    stage = stages.get("translate", {}) if isinstance(stages, dict) else {}
    return stage.get("enabled", True) and stage.get("options", {}).get("connection_ref") == connection_id


@contextmanager
def reference_guard():
    # Use existing live services only: a settings preview must not initialize or
    # restore the task database. Match batch -> task lock order used by submission.
    from . import batch_run_service, task_service, preset_catalog_service
    with ExitStack() as stack:
        stack.enter_context(preset_catalog_service._write_lock)
        for service in (batch_run_service._service, task_service._service):
            if service is not None:
                stack.enter_context(service.history_deletion_guard())
        yield


def removal_references(connection_id):
    from . import batch_run_service, task_service
    from .preset_catalog_service import get_preset_catalog_service
    catalog = get_preset_catalog_service()
    references = []
    for preset in [*catalog.list_presets(), *catalog.list_archived_presets()]:
        if references_profile(preset, connection_id):
            references.append({"kind": "workflow", "id": preset["id"], "name": preset["label"]})
    if task_service._service is not None:
        for spec, status in task_service._service.history_snapshot():
            pinned = getattr(task_service._service, "_connection_records", {}).get(spec.task_id, {})
            uses_pinned_default = any(ref.get("kind") == "llm" and ref.get("selected") and ref.get("id") == connection_id
                                      for ref in pinned.get("references", []))
            if (status.state not in {"completed", "failed", "cancelled", "skipped"}
                    and (references_profile(spec.execution_profile or {}, connection_id) or uses_pinned_default)):
                references.append({"kind": "task", "id": spec.task_id, "name": spec.task_id})
    if batch_run_service._service is not None:
        for batch in batch_run_service._service.history_snapshot():
            if batch.state not in batch_run_service.BATCH_TERMINAL_STATES and references_profile(batch.execution_profile, connection_id):
                references.append({"kind": "batch", "id": batch.batch_id, "name": batch.name})
    return sorted(references, key=lambda item: (item["kind"], item["id"]))
