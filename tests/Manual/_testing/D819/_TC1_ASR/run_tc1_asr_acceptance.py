"""Run one real TC1 ASR-only pipeline without overwriting another task's evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.dto import PipelineRequest  # noqa: E402
from src.app.services.artifact_service import ArtifactService  # noqa: E402
from src.app.services.model_service import ModelService  # noqa: E402
from src.app.services.pipeline_service import PipelineService  # noqa: E402
from src.app.services.resource_service import ResourceService  # noqa: E402
from src.app.services.task_service import TaskService  # noqa: E402
from src.core.subtitles import load_subtitle_with_timestamps  # noqa: E402


PROFILES = {
    "fun_asr": {
        "model": "fun-asr-nano-2512",
        "provider_options": {
            "hub": "hf",
            "device": "auto",
            "batch_size": 1,
            "sentence_timestamp": True,
            "trust_remote_code": True,
            "vad_model": "fun-asr-fsmn-vad",
            "vad_kwargs": {"max_single_segment_time": 30000},
        },
    },
    "qwen3_asr": {
        "model": "qwen3-asr-0.6b",
        "provider_options": {
            "device_map": "cpu",
            "dtype": "bfloat16",
            "max_inference_batch_size": 1,
            "max_new_tokens": 512,
            "forced_aligner": "qwen3-forced-aligner-0.6b",
            "return_time_stamps": True,
            "max_alignment_chunk_seconds": 15.0,
        },
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _normalized_sentences(text: str) -> list[str]:
    return [
        re.sub(r"\s+", "", item)
        for item in re.split(r"(?<=[。！？!?])", text)
        if re.sub(r"[\s。！？!?]+", "", item)
    ]


def _tail_repeat_count(segments) -> int:
    sentences = _normalized_sentences("".join(str(segment.get("text", "")) for segment in segments))
    if not sentences:
        return 0
    last = sentences[-1]
    count = 0
    for sentence in reversed(sentences):
        if sentence != last:
            break
        count += 1
    return count


def _build_profile(provider: str) -> dict:
    selected = PROFILES[provider]
    return {
        "version": 1,
        "source_lang": "ja",
        "target_lang": "zh",
        "skip_existing": False,
        "output_mode": "single",
        "batch_root_dir": "",
        "stages": {
            "separate": {
                "enabled": False,
                "provider": "demucs",
                "model": "htdemucs",
                "options": {},
                "provider_options": {},
            },
            "asr": {
                "enabled": True,
                "provider": provider,
                "model": selected["model"],
                "options": {
                    "language": "ja",
                    "output_format": "segments",
                    "timestamps": True,
                },
                "provider_options": dict(selected["provider_options"]),
            },
            "translate": {
                "enabled": False,
                "provider": "deepseek",
                "model": "default",
                "options": {},
                "provider_options": {},
            },
            "tts": {
                "enabled": False,
                "provider": "edge",
                "model": "default",
                "options": {},
                "provider_options": {},
            },
            "mix": {
                "enabled": False,
                "provider": "ffmpeg",
                "model": "default",
                "options": {},
                "provider_options": {},
            },
            "export": {
                "enabled": True,
                "provider": "subtitle",
                "model": "default",
                "options": {"subtitle_format": "srt"},
                "provider_options": {},
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=sorted(PROFILES))
    parser.add_argument(
        "--fixture-root",
        default=r"E:\Projects\AutoCollect\ASMR\TC1",
    )
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "output" / "TC1_acceptance"),
    )
    args = parser.parse_args()

    fixture_root = Path(args.fixture_root)
    audio_path = fixture_root / "音轨01_序章.wav"
    reference_path = fixture_root / "音轨01_序章.wav.vtt"
    if not audio_path.is_file() or not reference_path.is_file():
        raise FileNotFoundError("TC1 audio or reference VTT is missing")

    run_name = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    output_root = str(Path(args.output_root) / args.provider / run_name)
    task_service = TaskService()
    model_service = ModelService(task_service=task_service)
    result = PipelineService(
        task_service=task_service,
        artifact_service=ArtifactService(),
        resource_service=ResourceService(
            project_root=PROJECT_ROOT,
            model_service=model_service,
        ),
    ).run_audio_pipeline(
        PipelineRequest(
            input_path=str(audio_path),
            output_dir=output_root,
            source_lang="ja",
            target_lang="zh",
            execution_profile=_build_profile(args.provider),
        )
    )
    subtitle_path = Path(result.exported_subtitle or "")
    if not subtitle_path.is_file():
        raise RuntimeError("pipeline did not produce an ASR subtitle")

    actual = load_subtitle_with_timestamps(str(subtitle_path))
    reference = load_subtitle_with_timestamps(str(reference_path))
    adjacent_duplicates = sum(
        1
        for previous, current in zip(actual, actual[1:], strict=False)
        if re.sub(r"\s+", "", str(previous.get("text", "")))
        == re.sub(r"\s+", "", str(current.get("text", "")))
    )
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "task_id": result.task_id,
        "input": {
            "path": str(audio_path),
            "sha256": _sha256(audio_path),
        },
        "reference": {
            "path": str(reference_path),
            "sha256": _sha256(reference_path),
            "segments": len(reference),
            "start": reference[0]["start"] if reference else None,
            "end": reference[-1]["end"] if reference else None,
        },
        "actual": {
            "subtitle_path": str(subtitle_path),
            "subtitle_sha256": _sha256(subtitle_path),
            "transcript_path": result.steps.get("asr", {}).get("output"),
            "segments": len(actual),
            "start": actual[0]["start"] if actual else None,
            "end": actual[-1]["end"] if actual else None,
            "adjacent_duplicate_segments": adjacent_duplicates,
            "terminal_sentence_repeat_count": _tail_repeat_count(actual),
        },
        "output_layout": {
            "root": output_root,
            "expected_suffix": str(Path(str(result.task_id)) / audio_path.stem),
            "isolated": Path(str(result.steps.get("asr", {}).get("output", ""))).is_relative_to(
                Path(output_root) / str(result.task_id) / audio_path.stem
            ),
        },
        "timing_seconds": result.total_duration,
    }
    report_path = subtitle_path.parent / "acceptance_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"REPORT={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
