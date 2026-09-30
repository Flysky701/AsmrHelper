"""Explicit material bindings for the fixed workbench stages.

This validates a user's selections; it never enables stages or substitutes inputs.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from src.core.subtitles.companions import inspect_subtitle
from src.core.subtitles.translation_reuse import audio_duration, timing_key
from src.core.subtitles.text_utils import normalize_language_code

STAGES = ("separate", "asr", "align", "translate", "tts", "mix", "export")
ROLES = {"separate": {"audio": "audio"}, "asr": {"audio": "audio"},
         "align": {"audio": "audio", "text": "text"}, "translate": {"text": "text"},
         "tts": {"text": "text"}, "mix": {"audio": "audio", "speech": "audio"},
         "export": {"text": "text"}}
OUTPUT_KIND = {"separate": "audio", "asr": "text", "align": "text", "translate": "text",
               "tts": "audio", "mix": "audio", "export": "text"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".wma"}
LABELS = {"separate": "人声分离", "asr": "语音识别", "align": "时间轴校准", "translate": "字幕翻译",
          "tts": "语音合成", "mix": "混音", "export": "字幕导出"}


class WorkflowValidationError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("；".join(f"{LABELS.get(i['stage'], i['stage'])}：{i['message']}" for i in issues))


def path_key(path):
    return str(Path(path).expanduser().resolve()).casefold()


def subtitle_material(reference: dict) -> tuple[list[dict], str]:
    """Require complete explicit cues, and ask for uncertain language confirmation."""
    path = Path(reference["path"])
    if path.suffix.lower() not in {".srt", ".vtt"}:
        raise ValueError("请选择含明确起止时间的 SRT 或 VTT；LRC 的结束时间为推算值")
    inspection = inspect_subtitle(path)
    if not inspection["valid"]:
        raise ValueError(inspection["reason"] or "字幕缺少完整文本或时间轴")
    content = path.read_bytes()
    fingerprint = hashlib.sha256(content).hexdigest()
    if reference.get("sha256") and reference["sha256"] != fingerprint:
        raise ValueError("已绑定字幕在提交后改变，请检查并重新提交")
    blocks = re.split(r"\n\s*\n", content.decode("utf-8-sig").replace("\r\n", "\n").strip())
    if path.suffix.lower() == ".vtt":
        blocks = [b for b in blocks if b.split(maxsplit=1)[0].upper() not in {"WEBVTT", "NOTE", "STYLE", "REGION"}]
    segments = inspection["segments"]
    keys = [timing_key(s) for s in segments]
    if (len(blocks) != len(segments) or None in keys or keys != sorted(keys)
            or len(set(keys)) != len(keys)
            or any(sum("-->" in line for line in b.splitlines()[:2]) != 1 for b in blocks)):
        raise ValueError("字幕含空白、重复、无时间轴或无法解析的条目，请补齐素材")
    language = inspection["language"]
    declared = normalize_language_code(str(reference.get("language", "")))
    if language in {"unknown", "mixed", "auto"}:
        if reference.get("language_confirmed") is not True or declared not in {"ja", "zh", "en"}:
            raise ValueError("字幕语言不确定，请检查内容并明确确认其语言")
        language = declared
    elif reference.get("language_confirmed") is True and declared != language:
        raise ValueError("确认语言与字幕检测语言冲突，请检查素材，不能将异语字幕当作目标文本")
    reference["sha256"] = fingerprint
    reference["resolved_language"] = language
    return [{**s, "text": s["text"].strip()} for s in segments], language


def prepare_workflow(profile: dict, input_path: str | None, paths=None) -> dict:
    """Validate enabled stages and freeze selected subtitle evidence, without changing flags."""
    result = deepcopy(profile)
    workflow = result.get("workflow")
    issues = []
    def issue(stage, message):
        issues.append({"stage": stage, "message": message})
    if not isinstance(workflow, dict) or workflow.get("version") != 1:
        raise WorkflowValidationError([{"stage": "prepare", "message": "工作台素材绑定版本无效"}])
    stages = result.get("stages", {})
    if any(not isinstance(stages.get(s), dict) or not isinstance(stages[s].get("enabled"), bool) for s in STAGES):
        raise WorkflowValidationError([{"stage": "prepare", "message": "请明确勾选需要的每个执行阶段"}])
    enabled = [s for s in STAGES if stages[s]["enabled"]]
    outputs = workflow.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        issue("export", "请至少选择一个需要交付的产出")
    elif any(s not in enabled for s in outputs):
        issue("export", "所选产出对应阶段未勾选，请调整产出或执行步骤")
    bindings = workflow.get("bindings")
    if not isinstance(bindings, dict):
        bindings = {}
        issue("prepare", "请选择步骤所需素材来源")
    declared = None if paths is None else {path_key(p) for p in [input_path, *paths] if p}
    languages, provenance, audio_provenance = {}, {}, {}
    text_audio = {}
    used_paths, durations, subtitles = set(), {}, {}
    status = {}

    def audio_asset(path):
        source = Path(path)
        if source.suffix.lower() not in AUDIO_EXTENSIONS or not source.is_file():
            raise ValueError("缺少可读取音频，请添加并选择音频素材")
        key = path_key(path)
        if declared is not None and key not in declared:
            raise ValueError("绑定的音频未包含在本次所选素材中")
        if key not in durations:
            durations[key] = audio_duration(str(source))
        if durations[key] is None:
            raise ValueError("无法验证所选音频时长或格式")
        used_paths.add(str(source.resolve()))
        return str(source.resolve())

    for stage in enabled:
        stage_bindings = bindings.get(stage, {})
        if not isinstance(stage_bindings, dict):
            stage_bindings = {}
        supplied, text_origins, audio_origins, spoken_audio = {}, [], [], []
        before = len(issues)
        predecessor = False
        for role, kind in ROLES[stage].items():
            reference = stage_bindings.get(role) if isinstance(stage_bindings, dict) else None
            try:
                if not isinstance(reference, dict):
                    raise ValueError(f"缺少{('字幕/文本' if kind == 'text' else '音频')}来源，请选择素材或已选前序产物")
                if reference.get("kind") == "stage":
                    previous = reference.get("stage")
                    if previous not in STAGES or STAGES.index(previous) >= STAGES.index(stage):
                        raise ValueError("来源必须是前序步骤，不能循环或引用后序产物")
                    if previous not in enabled:
                        raise ValueError(f"来源步骤“{LABELS[previous]}”未勾选，请自行选择步骤或其他素材")
                    if OUTPUT_KIND[previous] != kind:
                        raise ValueError("所选前序产物类型不符合该步骤要求")
                    if status.get(previous) == "missing":
                        raise ValueError(f"前序步骤“{LABELS[previous]}”缺少素材，尚不能提供产物")
                    predecessor = True
                    supplied[role] = languages.get(previous)
                    if kind == "text":
                        text_origins.extend(provenance.get(previous, []))
                        spoken_audio.extend(text_audio.get(previous, []))
                    else:
                        audio_origins.extend(audio_provenance.get(previous, []))
                elif reference.get("kind") == "asset":
                    path = reference.get("path")
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("请选择明确的素材文件；多个候选不会自动挑选")
                    if declared is not None and path_key(path) not in declared:
                        raise ValueError("绑定素材未包含在本次所选输入中")
                    if kind == "audio":
                        audio_origins.append(audio_asset(path))
                    else:
                        segments, language = subtitle_material(reference)
                        used_paths.add(str(Path(path).resolve()))
                        origin = f"{stage}:{role}"
                        subtitles[origin] = (segments, reference)
                        supplied[role] = language
                        text_origins.append(origin)
                        if reference.get("audio_path"):
                            spoken_audio.append(reference["audio_path"])
                else:
                    raise ValueError("素材来源无效，请明确选择文件或前序产物")
            except (ValueError, OSError, TypeError, KeyError) as exc:
                issue(stage, str(exc))
        if stage in {"align", "translate"} and supplied.get("text") and supplied["text"] != result.get("source_lang", "ja"):
            issue(stage, "所选文本语言与源语言不同，请修改源语言或选择正确文本")
        if stage == "tts" and supplied.get("text") and supplied["text"] != result.get("target_lang", "zh"):
            issue(stage, "缺少目标语言文本：请选择目标字幕，或自行勾选翻译并绑定其产物")
        if stage == "asr":
            languages[stage] = result.get("source_lang", "ja")
        elif stage == "translate":
            languages[stage] = result.get("target_lang", "zh")
        elif stage in {"align", "tts", "export"}:
            languages[stage] = supplied.get("text")
        provenance[stage] = text_origins
        audio_provenance[stage] = audio_origins
        text_audio[stage] = audio_origins if stage == "asr" else spoken_audio
        if stage == "tts":
            # A synthesized timeline inherits any explicitly associated original audio.
            audio_provenance[stage] = [subtitles[p][1]["audio_path"] for p in text_origins
                                       if subtitles[p][1].get("audio_path")]
        if stage in {"align", "mix"}:
            if stage == "mix":
                speech_ref = stage_bindings.get("speech", {})
                if (isinstance(speech_ref, dict) and speech_ref.get("kind") == "stage"
                        and speech_ref.get("stage") in STAGES):
                    text_origins = provenance.get(speech_ref.get("stage"), [])
                    spoken_audio = text_audio.get(speech_ref.get("stage"), [])
            if spoken_audio and any(path_key(a) not in {path_key(p) for p in spoken_audio} for a in audio_origins):
                issue(stage, "文本对应音频与该步骤所选音频不一致，请检查来源绑定")
            for origin in text_origins:
                reference = subtitles[origin][1]
                for audio in audio_origins:
                    if (not reference.get("audio_path") or path_key(reference["audio_path"]) != path_key(audio)
                            or reference.get("pair_confirmed") is not True):
                        issue(stage, "字幕与音频共同使用前，请明确确认它们对应同一录音及时间轴")
        status[stage] = "missing" if len(issues) > before else "upstream" if predecessor else "ready"
    for segments, reference in subtitles.values():
        if reference.get("audio_path"):
            try:
                audio = audio_asset(reference["audio_path"])
                if reference.get("pair_confirmed") is not True:
                    raise ValueError("请确认所选字幕与音频的对应关系")
                if any(s["end"] > durations[path_key(audio)] + 0.1 for s in segments):
                    raise ValueError("字幕时间轴超出对应音频时长，请先检查素材及对应关系")
            except (ValueError, OSError, TypeError) as exc:
                issue("prepare", str(exc))
    if stages["export"]["enabled"] and stages["export"].get("options", {}).get("subtitle_format", "srt") not in {"srt", "vtt", "lrc"}:
        issue("export", "字幕导出仅支持现有 SRT、VTT、LRC 格式")
    if issues:
        raise WorkflowValidationError(issues)
    from src.app.persistence.recovery_store import file_identity
    identities = {path: file_identity(path) for path in sorted(used_paths)}
    previous_identities = workflow.get("asset_identities")
    if previous_identities is not None and previous_identities != identities:
        raise WorkflowValidationError([{"stage": "prepare", "message": "已绑定素材在提交后改变，请检查并重新提交"}])
    workflow.update(asset_paths=sorted(used_paths), languages=languages, status=status,
                    text_audio=text_audio, asset_identities=identities)
    # Old mode markers must never control a new explicit workflow.
    options = stages["translate"].setdefault("options", {})
    for name in ("direct_tts", "reuse_only", "reuse_unverified", "reuse_companion_paths", "direct_subtitle_path", "direct_subtitle_sha256"):
        options.pop(name, None)
    options["reuse_existing"] = False
    return result


class WorkflowInputs:
    """Resolve only the materials explicitly bound to an enabled stage."""
    def __init__(self, plan):
        profile = {"workflow": plan.workflow, "source_lang": plan.source_lang, "target_lang": plan.target_lang,
                   "stages": {name: {"enabled": getattr(plan, {"separate": "separation", "align": "alignment",
                       "translate": "translation", "export": "subtitle"}.get(name, name)).enabled} for name in STAGES}}
        self.workflow = prepare_workflow(profile, plan.input_path, [*plan.companion_subtitle_paths])["workflow"]
        self.outputs = {}

    def audio(self, stage, role="audio"):
        reference = self.workflow["bindings"][stage][role]
        value = reference["path"] if reference["kind"] == "asset" else self.outputs[reference["stage"]]
        if not Path(value).is_file():
            raise ValueError("所选音频产物未生成，不能替换为其他音频继续执行")
        return Path(value)

    def text(self, stage):
        reference = self.workflow["bindings"][stage]["text"]
        if reference["kind"] == "asset":
            segments, _ = subtitle_material(reference)
            return segments
        return deepcopy(self.outputs[reference["stage"]])

    def record_text(self, stage, segments):
        keys = [timing_key(s) for s in segments]
        if (not segments or None in keys or keys != sorted(keys) or len(set(keys)) != len(keys)
                or any(not str(s.get("text", "")).strip() for s in segments)):
            raise ValueError(f"{LABELS[stage]}未产生完整有效的文本和时间轴，不能继续后续步骤")
        self.outputs[stage] = deepcopy(segments)

    def duration(self, stage):
        reference = self.workflow["bindings"][stage]["text"]
        if reference.get("audio_path"):
            return audio_duration(reference["audio_path"]) or 0
        originals = self.workflow.get("text_audio", {}).get(stage, [])
        if len(originals) == 1:
            return audio_duration(originals[0]) or 0
        return max((s["end"] for s in self.text(stage)), default=0)
