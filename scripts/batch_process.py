#!/usr/bin/env python3
"""Compatibility wrapper for batch audio pipeline processing."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.app import BatchPipelineRequest
from src.app.services import get_batch_pipeline_service


def find_audio_files(directory: str) -> list[Path]:
    """Discover audio files recursively through the app layer."""
    return get_batch_pipeline_service().discover_audio_files(directory)


def process_single_file(
    input_path: Path,
    output_base_dir: Path | None = None,
    skip_existing: bool = True,
    **params,
) -> dict:
    """Preserve the legacy single-file helper shape for compatibility."""
    print(f"\n{'=' * 60}")
    print(f"[Batch] Processing: {input_path.name}")
    print(f"{'=' * 60}")
    print("[Pipeline] Delegating through the application API...")

    request = BatchPipelineRequest(
        input_files=[str(input_path)],
        output_base_dir=str(output_base_dir) if output_base_dir else "",
        source_lang="ja",
        target_lang="zh",
        use_vocal_separator=True,
        tts_engine=params.get("tts_engine", "edge"),
        tts_voice=params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
        vocal_model=params.get("vocal_model", "htdemucs"),
        asr_model=params.get("asr_model", "base"),
        translate_provider="deepseek",
        tts_speed=params.get("tts_speed", 1.0),
        original_volume=params.get("original_volume", 0.85),
        tts_volume_ratio=params.get("tts_ratio", 0.5),
        tts_delay=params.get("tts_delay", 0.0),
        skip_existing=skip_existing,
    )
    batch_result = get_batch_pipeline_service().run_batch(request)
    if not batch_result.items:
        return {
            "file": str(input_path),
            "status": "failed",
            "error": "batch service returned no results",
            "output": None,
            "time": 0.0,
        }

    item = batch_result.items[0]
    if item.status == "success" and item.output:
        print(f"\n[Done] {input_path.name} -> {Path(item.output).name} ({item.duration:.1f}s)")
    elif item.status == "failed":
        print(f"\n[Failed] {input_path.name}: {item.error}")

    return {
        "file": item.file,
        "status": item.status,
        "error": item.error,
        "output": item.output,
        "time": item.duration,
    }


def batch_process(
    input_files: list[Path],
    output_base_dir: Path | None = None,
    max_workers: int = 1,
    **params,
) -> list[dict]:
    """Run the legacy batch flow through the app-layer batch service."""
    total = len(input_files)

    print(f"\n{'#' * 60}")
    print("# ASMR Batch Processing")
    print(f"# Files: {total}")
    print(f"# Workers: {max_workers}")
    print(f"# Output Dir: {output_base_dir or 'alongside source files'}")
    print(f"{'#' * 60}\n")

    if max_workers > 1:
        print(
            "[Warning] Parallel workers may multiply GPU/runtime load. "
            "For constrained environments, prefer --workers 1.\n"
        )

    request = BatchPipelineRequest(
        input_files=[str(path) for path in input_files],
        output_base_dir=str(output_base_dir) if output_base_dir else "",
        source_lang="ja",
        target_lang="zh",
        use_vocal_separator=True,
        tts_engine=params.get("tts_engine", "edge"),
        tts_voice=params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
        vocal_model=params.get("vocal_model", "htdemucs"),
        asr_model=params.get("asr_model", "base"),
        translate_provider="deepseek",
        tts_speed=params.get("tts_speed", 1.0),
        original_volume=params.get("original_volume", 0.85),
        tts_volume_ratio=params.get("tts_ratio", 0.5),
        tts_delay=params.get("tts_delay", 0.0),
        skip_existing=params.get("skip_existing", True),
        max_workers=max_workers,
    )

    def on_progress(current: int, batch_total: int, item) -> None:
        print(f"\n[Progress {current}/{batch_total}] {item.status}: {Path(item.file).name}")

    batch_result = get_batch_pipeline_service().run_batch(
        request,
        progress_callback=on_progress,
    )
    return [
        {
            "file": item.file,
            "status": item.status,
            "error": item.error,
            "output": item.output,
            "time": item.duration,
        }
        for item in batch_result.items
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ASMR bilingual batch processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input-dir", "-d", help="Input directory to scan recursively")
    input_group.add_argument("--input", "-i", nargs="+", help="Explicit input files")

    parser.add_argument("--output", "-o", default=None, help="Batch output base directory")
    parser.add_argument(
        "--skip-existing",
        "-s",
        action="store_true",
        default=True,
        help="Skip files whose outputs already exist",
    )
    parser.add_argument("--no-skip", action="store_true", help="Re-run files even if outputs exist")
    parser.add_argument("--tts-engine", default="edge", choices=["edge", "qwen3"], help="TTS engine")
    parser.add_argument("--tts-voice", default="zh-CN-XiaoxiaoNeural", help="TTS voice")
    parser.add_argument("--tts-speed", type=float, default=1.0, help="TTS speed")
    parser.add_argument("--original-volume", type=float, default=0.85, help="Original audio volume")
    parser.add_argument("--tts-ratio", type=float, default=0.5, help="Relative TTS volume ratio")
    parser.add_argument("--tts-delay", type=float, default=0.0, help="TTS delay in milliseconds")
    parser.add_argument("--vocal-model", default="htdemucs", help="Vocal separation model")
    parser.add_argument("--asr-model", default="base", help="ASR model")
    parser.add_argument("--workers", type=int, default=1, help="Parallel worker count")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    skip_existing = not args.no_skip

    if args.input_dir:
        audio_files = find_audio_files(args.input_dir)
        if not audio_files:
            print(f"Error: no audio files found under {args.input_dir}")
            return 1
        print(f"Found {len(audio_files)} audio files.")
    else:
        audio_files = [Path(value) for value in args.input]
        missing = [path for path in audio_files if not path.exists()]
        if missing:
            print("Error: the following files do not exist:")
            for path in missing:
                print(f"  - {path}")
            return 1

    output_base_dir = Path(args.output) if args.output else None
    params = {
        "skip_existing": skip_existing,
        "tts_engine": args.tts_engine,
        "tts_voice": args.tts_voice,
        "tts_speed": args.tts_speed,
        "original_volume": args.original_volume,
        "tts_ratio": args.tts_ratio,
        "tts_delay": args.tts_delay,
        "vocal_model": args.vocal_model,
        "asr_model": args.asr_model,
    }

    started_at = time.time()
    results = batch_process(audio_files, output_base_dir, args.workers, **params)
    elapsed = time.time() - started_at

    success = sum(1 for result in results if result["status"] == "success")
    skipped = sum(1 for result in results if result["status"] == "skipped")
    failed = sum(1 for result in results if result["status"] == "failed")

    print(f"\n{'#' * 60}")
    print("# Processing finished")
    print(f"# Total files: {len(results)}")
    print(f"# Success: {success}")
    print(f"# Skipped: {skipped}")
    print(f"# Failed: {failed}")
    print(f"# Total time: {elapsed:.1f}s")
    print(f"{'#' * 60}")

    if failed:
        print("\nFailed files:")
        for result in results:
            if result["status"] == "failed":
                print(f"  - {result['file']}: {result['error']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
