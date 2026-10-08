"""Reviewable uploads and durable receipts. Never automatically retry a creation."""
import hashlib
import json
from pathlib import Path
from uuid import UUID

from src.core.speech import fish_cloning
from src.core.speech.providers import ProviderError


class FishCloneService:
    def __init__(self, speech):
        self.speech, self.store = speech, speech.store

    def preview(self, body):
        if set(body) != {"connection_ref", "asset_id", "title"}:
            raise ValueError("克隆预览字段不正确")
        title = body["title"]
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
            raise ValueError("音色名称须为 1–100 个字符")
        connection = self.store.get("connections", body["connection_ref"])
        endpoint = fish_cloning.model_endpoint(connection)
        asset = self.store.get("assets", body["asset_id"])
        if asset.get("archived") or asset.get("confirmed") is not True or not asset.get("transcript", "").strip():
            raise ValueError("请选择未归档且已核对原文的参考素材，避免隐式远程转写")
        path = Path(asset["path"]).resolve()
        if not path.is_relative_to(self.store.assets_root.resolve()) or path.suffix.lower() != ".wav":
            raise ValueError("只能上传声音库保存的 WAV 参考素材")
        if not path.is_file() or not 0 < path.stat().st_size <= 25 * 1024 * 1024:
            raise ValueError("本应用单次克隆限 25 MB 以内的一段参考音频，请先裁剪并保存")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        review = {"connection_ref": connection["id"], "connection_revision": connection["revision"],
                  "asset_id": asset["id"], "asset_revision": asset["revision"], "audio_sha256": digest,
                  "transcript": asset["transcript"], "title": title.strip(), "endpoint": endpoint,
                  "asset_name": asset.get("name") or asset["id"], "bytes": path.stat().st_size,
                  "duration": asset.get("duration"), "visibility": "private"}
        review["token"] = hashlib.sha256(json.dumps(review, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return review

    @staticmethod
    def _public(record):
        # A process may have stopped between dispatch and persisting its response.
        if record["state"] == "submitting":
            return {**record, "state": "unknown", "message": "提交中或结果未知，请刷新记录并到 Fish 核查；不要重复上传"}
        return record

    def list(self, include_deleted=False):
        return [self._public(item) for item in self.store.list("fish_clones")
                if include_deleted or not item.get("deleted", False)]

    def set_deleted(self, clone_id, deleted):
        # This lock also covers dispatch: an in-flight creation must settle first.
        # Keep the receipt and review token even when hidden, for deduplication.
        with self.store._locked(".fish-clones.lock"):
            record = self.store.get("fish_clones", clone_id)
            if deleted and record["state"] in {"created", "training"}:
                raise ValueError("音色仍在远程处理中，请查询状态后再删除本地记录")
            patch = {"deleted": deleted}
            if record["state"] == "submitting":
                # With the dispatch lock acquired, this is an interrupted receipt.
                patch.update(state="unknown", message="提交曾中断，结果未知；请到 Fish 核查，勿重复上传")
            return self.store.update("fish_clones", clone_id, patch)

    def create(self, body):
        if set(body) != {"connection_ref", "asset_id", "title", "token", "request_id"}:
            raise ValueError("克隆提交字段不正确")
        if not isinstance(body["request_id"], str):
            raise ValueError("提交编号须为 UUID")
        request_id = str(UUID(body["request_id"]))
        with self.store._locked(".fish-clones.lock"):
            existing = next((item for item in self.store.list("fish_clones") if item["id"] == request_id), None)
            if existing:
                if existing["review_token"] != body["token"]:
                    raise ValueError("此提交编号已用于其他克隆，请刷新记录")
                return self._public(existing)
            preview = self.preview({key: body[key] for key in ("connection_ref", "asset_id", "title")})
            if body["token"] != preview["token"]:
                raise ValueError("素材或连接已变更，请重新预览和确认")
            connection = self.store.get("connections", body["connection_ref"])
            context = self.speech.connection_context(connection)["connection"]
            if not context.get("api_key"):
                raise ValueError("请先在现有服务连接入口配置 Fish 凭据")
            asset = self.store.get("assets", body["asset_id"])
            record = self.store.create("fish_clones", {"id": request_id, "title": preview["title"],
                "asset_id": asset["id"], "connection_ref": connection["id"],
                "connection_revision": connection["revision"], "review_token": preview["token"],
                "state": "submitting", "remote_voice_id": None, "message": "", "recipe_id": None})
            try:
                result = fish_cloning.create_voice(context, title=preview["title"], path=asset["path"], transcript=asset["transcript"])
            except ProviderError as exc:
                result = {"state": "unknown" if exc.result_unknown else "failed", "message": str(exc)}
            except (OSError, ValueError):
                result = {"state": "unknown", "message": "提交未能完成，结果未知；请先到 Fish 核查"}
            return self.store.update("fish_clones", record["id"], result)

    def _connection(self, record):
        connection = self.store.get("connections", record["connection_ref"])
        if connection["revision"] != record["connection_revision"]:
            raise ValueError("原连接已修改，请到 Fish 核查并手动绑定音色 ID")
        return connection

    def refresh(self, clone_id):
        with self.store._locked(".fish-clones.lock"):
            record = self.store.get("fish_clones", clone_id)
            if record.get("deleted"):
                raise ValueError("请先撤销本地记录删除，再查询远程状态")
            if not record.get("remote_voice_id"):
                return self._public(record)
            connection = self._connection(record)
            result = fish_cloning.get_voice(self.speech.connection_context(connection)["connection"], record["remote_voice_id"])
            return self.store.update("fish_clones", clone_id, {**result, "message": ""})

    def save_rule(self, clone_id):
        with self.store._locked(".fish-clones.lock"):
            record = self.store.get("fish_clones", clone_id)
            if record.get("deleted"):
                raise ValueError("请先撤销本地记录删除，再打开或保存音色")
            if record.get("recipe_id"):
                return self.store.get("recipes", record["recipe_id"])
            if record["state"] != "trained" or not record.get("remote_voice_id"):
                raise ValueError("远程音色尚未就绪，请刷新状态；不会自动发起试听")
            self._connection(record)
            rule = self.speech.save_rule({"name": record["title"], "provider_id": "fish_audio",
                "model": "s2.1-pro-free", "mode": "hosted", "connection_ref": record["connection_ref"],
                "variant": {"kind": "hosted", "value": record["remote_voice_id"], "style": "normal"},
                "language": "auto", "provider_options": {"schema_version": 1}})
            self.store.update("fish_clones", clone_id, {"recipe_id": rule["id"]})
            return rule
