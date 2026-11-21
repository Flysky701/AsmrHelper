"""Six orthogonal MCP tools wrapping `DraftSessionService` and `SpeechService`."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.mcp_server.protocol import (
    INVALID_PARAMS,
    McpRpcException,
    McpTextContent,
    McpToolCallResult,
    McpToolDefinition,
)
from src.app.errors import (
    AppError,
    AppExecutionError,
    AppValidationError,
    ResourceUnavailableError,
    ResourceValidationError,
)
from src.app.persistence.draft_store import DraftConflictError
from src.app.services.draft_session_service import DraftSessionService


# ─── Tool Input Models ────────────────────────────────────────────────────


class InspectWorkArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_or_dir: str = Field(description="Local ASMR audio file path or work directory path.")


class PrepareDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_or_dir: str = Field(description="Local ASMR audio file path or work directory path.")
    track_path: str | None = Field(default=None, description="Optional explicit primary audio track path.")
    subtitle_path: str | None = Field(default=None, description="Optional explicit subtitle (.srt/.vtt/.lrc) path.")
    script_path: str | None = Field(default=None, description="Optional companion script (.txt/.pdf) path.")
    title: str | None = Field(default=None, description="Optional human-readable work/draft title.")
    source_lang: str = Field(default="ja", description="Source audio/subtitle language code.")
    target_lang: str = Field(default="zh", description="Target translation language code.")
    enable_translation: bool = Field(default=True, description="Run LLM translation when cues lack target text.")
    duration_aware: bool = Field(default=False, description="Include each cue's time and character budget during translation.")
    auto_detect_delivery: bool = Field(default=False, description="Suggest normal, soft or whisper delivery from the source.")
    force_asr: bool = Field(default=False, description="Force ASR recognition even when companion subtitles exist.")
    asr_provider: str | None = Field(default=None, description="Optional ASR provider ID (e.g., anime_whisper, faster_whisper).")
    asr_model: str | None = Field(default=None, description="Optional ASR model identifier.")
    asr_options: dict[str, Any] | None = Field(default=None, description="Optional provider-specific ASR options.")
    llm_provider: str | None = Field(default=None, description="Optional LLM provider ID (e.g., deepseek, openai).")
    llm_model: str | None = Field(default=None, description="Optional LLM model identifier.")
    llm_options: dict[str, Any] | None = Field(default=None, description="Optional LLM provider options.")
    voice_plan: dict[str, Any] | None = Field(default=None, description="Optional VoiceLab recipe_id or speech options.")
    prepare_stems: bool = Field(default=False, description="Prepare vocals and effects using paired stems or source separation.")
    separation_model: str | None = Field(default=None, description="Separation model when preparing missing stems, e.g. mel_band_roformer.")
    extract_voice_reference: bool = Field(default=False, description="Extract highest-SNR 6-10s clean reference candidate.")
    synthesize_samples: bool = Field(default=False, description="Synthesize 1-2 sample cues before review gate.")
    sample_cue_count: int = Field(default=0, ge=0, le=2, description="Explicit number of sample cues (0..2).")
    chars_per_second: float = Field(default=4.2, gt=0.0, description="Target Chinese speech rate for speed audit.")
    max_atempo: float = Field(default=1.35, ge=1.0, description="Maximum allowed time-compression ratio before warning.")
    remote_worker_url: str | None = Field(default=None, description="Optional Colab/remote GPU worker base URL.")
    remote_worker_token: str | None = Field(default=None, description="Optional Bearer token for remote GPU worker.")


class GetDraftAuditArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(description="DraftSession identifier returned by asmr_prepare_draft.")
    include_segments: bool = Field(default=False, description="Include full segment list alongside QualityAuditReport.")


class SegmentEditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int | None = Field(default=None, description="0-based cue index to update.")
    cue_id: str | None = Field(default=None, description="Cue identifier (e.g., 'cue-0001') if index is omitted.")
    source_text: str | None = Field(default=None, description="Updated source transcript text.")
    translation: str | None = Field(default=None, description="Updated target translation text.")
    start: float | None = Field(default=None, description="Updated cue start timestamp in seconds.")
    end: float | None = Field(default=None, description="Updated cue end timestamp in seconds.")
    speaker: str | None = Field(default=None, description="Optional speaker label.")
    delivery: str | None = Field(default=None, description="Delivery style: normal, soft, or whisper.")
    emotion: str | None = Field(default=None, description="Emotion intent: neutral, calm, happy, sad, etc.")


class PatchDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(description="DraftSession identifier to patch.")
    edits: list[SegmentEditItem] = Field(default_factory=list, description="List of cue text/timing/delivery edits.")
    voice_plan_patch: dict[str, Any] | None = Field(default=None, description="Optional voice recipe or TTS parameter updates.")
    title: str | None = Field(default=None, description="Optional updated draft title.")
    expected_revision: int | None = Field(default=None, description="Optimistic concurrency revision guard.")


class CommitDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(description="DraftSession identifier to commit.")
    output_dir: str = Field(description="Destination directory for exported subtitles and dubbed audio.")
    export_formats: list[str] = Field(default_factory=lambda: ["srt", "lrc"], description="Subtitle formats to export (srt, vtt, lrc).")
    regenerate_cue_ids: list[str] = Field(default_factory=list, description="Force new takes only for these cue IDs; all other cues must have cached audio.")
    enable_dubbing: bool = Field(default=True, description="Synthesize TTS timeline and mix final dubbed audio.")
    bilingual: bool = Field(default=True, description="Export bilingual (source + target) subtitles when source text exists.")
    mix_options: dict[str, Any] | None = Field(default=None, description="Optional Mixer options (original_volume, tts_volume_ratio, tts_delay_ms).")
    expected_revision: int | None = Field(default=None, description="Optimistic concurrency revision guard.")


class ListVoicesAndPresetsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_providers: bool = Field(default=True, description="Include TTS provider schemas and builtin voice catalogs.")
    include_archived: bool = Field(default=False, description="Include archived VoiceLab rules.")


def _clean_json_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Generate clean MCP-compatible JSON Schema from a Pydantic v2 model."""
    raw = model_cls.model_json_schema()
    return {
        "type": "object",
        "properties": raw.get("properties", {}),
        **({"required": raw["required"]} if raw.get("required") else {}),
        **({"$defs": raw["$defs"]} if raw.get("$defs") else {}),
        "additionalProperties": False,
    }


def _classify_domain_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, DraftConflictError):
        return "REVISION_CONFLICT", str(exc)
    if isinstance(exc, ResourceUnavailableError):
        return "NOT_FOUND", str(exc)
    if isinstance(exc, (AppValidationError, ResourceValidationError, ValueError, FileNotFoundError)):
        return "VALIDATION_ERROR", str(exc)
    if isinstance(exc, (AppExecutionError, AppError)):
        return "EXECUTION_ERROR", str(exc)
    return "INTERNAL_TOOL_ERROR", str(exc)


class McpToolRegistry:
    """Registry and dispatcher for the 6 ASMR Helper MCP tools."""

    def __init__(
        self,
        *,
        draft_service: DraftSessionService | None = None,
        speech_service: Any | None = None,
        preset_service: Any | None = None,
    ) -> None:
        self._draft_service = draft_service
        self._speech_service = speech_service
        self._preset_service = preset_service
        self._definitions: list[McpToolDefinition] = [
            McpToolDefinition(
                name="asmr_inspect_work",
                description=(
                    "Inspect a local ASMR audio file or work directory: discover audio tracks, "
                    "read duration/channels/sample_rate, discover companion scripts (.txt/.pdf) "
                    "and subtitles (.srt/.vtt/.lrc), auto-pair matching stems, and summarize readiness."
                ),
                inputSchema=_clean_json_schema(InspectWorkArgs),
            ),
            McpToolDefinition(
                name="asmr_prepare_draft",
                description=(
                    "Execute Phase 1 of Two-Phase DraftSession: load existing subtitles or run ASR + "
                    "optional LLM translation, optionally extract a clean 6-10s voice reference candidate "
                    "and 1-2 sample cues, compute QualityAuditReport (untranslated, Japanese residue, "
                    "slack-aware over_speed_cues > 1.35x), and halt at 'awaiting_review' without full TTS."
                ),
                inputSchema=_clean_json_schema(PrepareDraftArgs),
            ),
            McpToolDefinition(
                name="asmr_get_draft_audit",
                description=(
                    "Retrieve the deterministic QualityAuditReport (and optional cue segments) "
                    "for an existing DraftSession."
                ),
                inputSchema=_clean_json_schema(GetDraftAuditArgs),
            ),
            McpToolDefinition(
                name="asmr_patch_draft",
                description=(
                    "Apply concise translation rewrites, start/end timing adjustments, or voice recipe "
                    "changes to a DraftSession in 'awaiting_review', enforcing optimistic revision checks "
                    "and immediately recomputing QualityAuditReport."
                ),
                inputSchema=_clean_json_schema(PatchDraftArgs),
            ),
            McpToolDefinition(
                name="asmr_commit_draft",
                description=(
                    "Execute Phase 2 of DraftSession: export clean bilingual/target .srt/.vtt/.lrc "
                    "subtitles and synthesize/mix dubbed audio (reusing unchanged cached takes on re-commit), "
                    "transitioning the session to 'completed'."
                ),
                inputSchema=_clean_json_schema(CommitDraftArgs),
            ),
            McpToolDefinition(
                name="asmr_list_voices_and_presets",
                description=(
                    "List available VoiceLab voice rules/recipes, configured TTS connections, "
                    "engine voice presets, and workflow presets."
                ),
                inputSchema=_clean_json_schema(ListVoicesAndPresetsArgs),
            ),
        ]
        self._handlers: dict[str, tuple[type[BaseModel], Callable[[Any], dict[str, Any]]]] = {
            "asmr_inspect_work": (InspectWorkArgs, self._handle_inspect_work),
            "asmr_prepare_draft": (PrepareDraftArgs, self._handle_prepare_draft),
            "asmr_get_draft_audit": (GetDraftAuditArgs, self._handle_get_draft_audit),
            "asmr_patch_draft": (PatchDraftArgs, self._handle_patch_draft),
            "asmr_commit_draft": (CommitDraftArgs, self._handle_commit_draft),
            "asmr_list_voices_and_presets": (ListVoicesAndPresetsArgs, self._handle_list_voices_and_presets),
        }

    @property
    def draft_service(self) -> DraftSessionService:
        if self._draft_service is None:
            self._draft_service = DraftSessionService(standalone=True, speech_service=self._speech_service)
        return self._draft_service

    def _get_speech_service(self) -> Any:
        if self._speech_service is not None:
            return self._speech_service
        return self.draft_service._get_speech_service()

    def _get_preset_service(self) -> Any:
        if self._preset_service is not None:
            return self._preset_service
        from src.app.services.preset_catalog_service import get_preset_catalog_service

        return get_preset_catalog_service()

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.model_dump() for tool in self._definitions]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> McpToolCallResult:
        if not isinstance(name, str) or name not in self._handlers:
            raise McpRpcException(INVALID_PARAMS, f"Unknown MCP tool: {name!r}")
        if arguments is not None and not isinstance(arguments, dict):
            raise McpRpcException(INVALID_PARAMS, "Tool 'arguments' must be a JSON object")

        arg_model, handler = self._handlers[name]
        try:
            parsed_args = arg_model.model_validate(arguments or {})
        except ValidationError as exc:
            raise McpRpcException(
                INVALID_PARAMS,
                f"Invalid arguments for {name}: {exc.errors()[0].get('msg', str(exc))}",
                data=exc.errors(),
            ) from exc

        try:
            payload = handler(parsed_args)
            return McpToolCallResult(
                content=[McpTextContent(text=json.dumps(payload, ensure_ascii=False))],
                structuredContent=payload,
                isError=False,
            )
        except Exception as exc:
            code, message = _classify_domain_error(exc)
            err_payload = {"error": {"code": code, "message": message}}
            return McpToolCallResult(
                content=[McpTextContent(text=json.dumps(err_payload, ensure_ascii=False))],
                structuredContent=err_payload,
                isError=True,
            )

    # ─── Handlers ─────────────────────────────────────────────────────────

    def _handle_inspect_work(self, args: InspectWorkArgs) -> dict[str, Any]:
        return self.draft_service.inspect_work(args.path_or_dir)

    def _handle_prepare_draft(self, args: PrepareDraftArgs) -> dict[str, Any]:
        asr_options = dict(args.asr_options or {})
        voice_plan = dict(args.voice_plan or {})
        if args.remote_worker_url:
            asr_options.setdefault("remote_worker_url", args.remote_worker_url)
            voice_plan.setdefault("remote_worker_url", args.remote_worker_url)
        if args.remote_worker_token:
            asr_options.setdefault("remote_worker_token", args.remote_worker_token)
            voice_plan.setdefault("remote_worker_token", args.remote_worker_token)

        return self.draft_service.prepare_draft(
            args.path_or_dir,
            track_path=args.track_path,
            subtitle_path=args.subtitle_path,
            script_path=args.script_path,
            title=args.title,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            enable_translation=args.enable_translation,
            duration_aware=args.duration_aware,
            auto_detect_delivery=args.auto_detect_delivery,
            force_asr=args.force_asr,
            asr_provider=args.asr_provider,
            asr_model=args.asr_model,
            asr_options=asr_options or None,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            llm_options=args.llm_options,
            voice_plan=voice_plan or None,
            prepare_stems=args.prepare_stems,
            separation_model=args.separation_model,
            extract_voice_reference=args.extract_voice_reference,
            synthesize_samples=args.synthesize_samples,
            sample_cue_count=args.sample_cue_count,
            chars_per_second=args.chars_per_second,
            max_atempo=args.max_atempo,
        )

    def _handle_get_draft_audit(self, args: GetDraftAuditArgs) -> dict[str, Any]:
        report = self.draft_service.get_audit_report(args.draft_id)
        if args.include_segments:
            draft = self.draft_service.get_draft(args.draft_id)
            report["segments"] = draft.get("segments", [])
            report["voice_plan"] = draft.get("voice_plan", {})
        return report

    def _handle_patch_draft(self, args: PatchDraftArgs) -> dict[str, Any]:
        edits = [item.model_dump(exclude_unset=True) for item in args.edits]
        return self.draft_service.patch_draft(
            args.draft_id,
            edits=edits,
            voice_plan_patch=args.voice_plan_patch,
            expected_revision=args.expected_revision,
            title=args.title,
        )

    def _handle_commit_draft(self, args: CommitDraftArgs) -> dict[str, Any]:
        return self.draft_service.commit_draft(
            args.draft_id,
            args.output_dir,
            export_formats=args.export_formats,
            enable_dubbing=args.enable_dubbing,
            regenerate_cue_ids=args.regenerate_cue_ids,
            bilingual=args.bilingual,
            mix_options=args.mix_options,
            expected_revision=args.expected_revision,
        )

    def _handle_list_voices_and_presets(self, args: ListVoicesAndPresetsArgs) -> dict[str, Any]:
        speech_svc = self._get_speech_service()
        recipes = (
            speech_svc.active_recipes(include_archived=args.include_archived)
            if hasattr(speech_svc, "active_recipes")
            else []
        )
        connections = (
            speech_svc.list_connections()
            if hasattr(speech_svc, "list_connections")
            else []
        )
        voices = (
            speech_svc.store.list("voices")
            if hasattr(speech_svc, "store") and hasattr(speech_svc.store, "list")
            else []
        )
        providers_data: list[dict[str, Any]] = []
        if args.include_providers:
            from src.core.speech.providers import list_providers

            providers_data = list_providers()

        preset_svc = self._get_preset_service()
        workflow_presets = (
            [
                {
                    "id": p["id"],
                    "label": p["label"],
                    "description": p.get("description", ""),
                    "builtin": p.get("builtin", False),
                }
                for p in preset_svc.list_presets()
            ]
            if hasattr(preset_svc, "list_presets")
            else []
        )

        return {
            "recipes": recipes,
            "voices": voices,
            "connections": connections,
            "providers": providers_data,
            "workflow_presets": workflow_presets,
        }
