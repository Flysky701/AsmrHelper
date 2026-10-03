"""Explicit connection management; graph migrations precede physical record deletion."""
from __future__ import annotations

import hashlib
import json

from src.core.speech.store import ConnectionConflictError


class SpeechConnectionService:
    def __init__(self, speech, catalog=None):
        self.speech = speech
        if catalog is None:
            from .preset_catalog_service import get_preset_catalog_service
            catalog = get_preset_catalog_service()
        self.catalog = catalog

    @staticmethod
    def _token(connection_id, store_token, catalog_token):
        return hashlib.sha256(json.dumps([connection_id, store_token, catalog_token]).encode()).hexdigest()

    @staticmethod
    def _recipe_ids(preview):
        return sorted([item["id"] for item in preview["recipes"]] + preview["historical_recipe_ids"])

    def preview(self, connection_id):
        preview = self.speech.store.connection_deletion_preview(connection_id)
        catalog = self.catalog.speech_connection_references(connection_id, self._recipe_ids(preview))
        return {**preview, "token": self._token(connection_id, preview["token"], catalog["token"]),
                "presets": catalog["references"]}

    @staticmethod
    def _validate_replacement_references(references, current_recipe_ids):
        if any(item["builtin"] for item in references):
            raise ConnectionConflictError("内置流水线引用此连接或音色；请先复制并显式重新绑定，不能自动改写内置定义。")
        if any(item.get("recipe_id") and item["recipe_id"] not in current_recipe_ids for item in references):
            raise ConnectionConflictError("流水线引用历史音色修订；请先在流水线中明确升级或复制该音色，再删除连接。")

    def execute(self, connection_id, *, token, action, replacement_ref=None):
        store = self.speech.store
        receipt = store.connection_deletion_receipt(token)
        if receipt is not None:
            if (receipt["connection_id"], receipt["action"], receipt["replacement_ref"]) != (connection_id, action, replacement_ref):
                raise ConnectionConflictError("删除确认对应另一项选择，请重新预览。")
            if receipt["state"] == "completed":
                return {**receipt["result"], "updated_presets": []}
            recipe_ids = receipt["recipe_ids"]
            catalog = self.catalog.speech_connection_references(connection_id, recipe_ids)
            # A completed graph migration may be retried after the final store write failed.
            # Other edits are never overwritten by replaying a stale graph snapshot.
            if catalog["references"] and catalog["references"] != receipt["catalog_references"]:
                raise ConnectionConflictError("流水线引用在删除期间改变；旧连接已保留，请重新检查。")
            store_token = None
        else:
            preview = store.connection_deletion_preview(connection_id)
            recipe_ids = self._recipe_ids(preview)
            catalog = self.catalog.speech_connection_references(connection_id, recipe_ids)
            if token != self._token(connection_id, preview["token"], catalog["token"]):
                raise ConnectionConflictError("连接、音色或流水线已改变，请重新预览删除影响。")
            store_token = preview["token"]
            if action == "replace":
                if replacement_ref not in {item["id"] for item in preview["replacements"]}:
                    raise ValueError("请选择另一条属于同一引擎的连接。")
                self._validate_replacement_references(catalog["references"], {item["id"] for item in preview["recipes"]})
        if action not in {"replace", "detach"} or (action == "replace") != bool(replacement_ref):
            raise ValueError("请选择替代连接，或明确保留缺失引用。")
        # Lock order is always catalog then speech store. Preparing revisions writes only
        # additions; failure in graph persistence or final deletion retains the old connection.
        with self.catalog.speech_connection_migration(connection_id, recipe_ids, catalog["token"]) as migration:
            try:
                if receipt is None:
                    if action == "replace":
                        self._validate_replacement_references(migration.references, {item["id"] for item in preview["recipes"]})
                    receipt = store.prepare_connection_deletion(connection_id, store_token, action, replacement_ref,
                        request_token=token, catalog_token=catalog["token"], recipe_ids=recipe_ids,
                        catalog_references=migration.references)
                updated = migration.apply(receipt["recipe_id_map"], replacement_ref) if action == "replace" else []
                result = store.finalize_connection_deletion(receipt)
            except (OSError, ValueError) as exc:
                # Preparation is additive, not an all-or-nothing rollback.
                try:
                    store.get("connections", connection_id)
                except KeyError:
                    raise ConnectionConflictError("删除结果需要重新核对，请刷新连接列表和引用影响。") from exc
                raise ConnectionConflictError(
                    "删除未完成，旧连接已保留；部分音色或流水线引用可能已更新。可重试当前操作，或重新预览。 " + str(exc)) from exc
        return {**result, "updated_presets": updated}
