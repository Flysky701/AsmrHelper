#!/usr/bin/env python3
"""Compatibility wrapper for the bilingual ASMR pipeline."""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.app import PipelineRequest
from src.app.errors import AppError
from src.app.services import get_pipeline_service


def _resolve_output_dir(input_path: Path, output: str | None) -> Path:
    if output:
        return Path(output)

    safe_name = "".join(
        char if char.isalnum() or char in " _-()" else "_"
        for char in input_path.stem
    )
    return input_path.parent / f"{safe_name}_output"


def _find_vtt_path(input_path: Path, vtt_dir: str | None) -> Path | None:
    search_dirs: list[Path] = []
    if vtt_dir:
        search_dirs.append(Path(vtt_dir))
    search_dirs.append(input_path.parent)

    asmr_o_dir = input_path.parent / "ASMR_O"
    if asmr_o_dir.exists():
        search_dirs.append(asmr_o_dir)

    candidate_names = [
        f"{input_path.name}.vtt",
        f"{input_path.stem}.vtt",
    ]

    for search_dir in search_dirs:
        for candidate_name in candidate_names:
            candidate = search_dir / candidate_name
            if candidate.exists():
                return candidate
    return None


def _resolve_tts_voice(tts_engine: str, tts_voice: str) -> str:
    if tts_engine == "qwen3" and tts_voice == "zh-CN-XiaoxiaoNeural":
        return "Vivian"
    return tts_voice


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ASMR bilingual audio pipeline")
    parser.add_argument("--input", "-i", required=True, help="Input audio file path")
    parser.add_argument("--output", "-o", default=None, help="Output directory")
    parser.add_argument("--tts-engine", default="edge", choices=["edge", "qwen3"], help="TTS engine")
    parser.add_argument("--tts-voice", default="zh-CN-XiaoxiaoNeural", help="TTS voice")
    parser.add_argument("--tts-speed", type=float, default=1.0, help="Qwen3 speech speed")
    parser.add_argument("--tts-delay", type=float, default=0, help="TTS delay in milliseconds")
    parser.add_argument("--tts-ratio", type=float, default=0.5, help="Relative TTS volume ratio")
    parser.add_argument("--original-volume", type=float, default=0.85, help="Original audio volume")
    parser.add_argument("--vocal-model", default="htdemucs", help="Vocal separation model")
    parser.add_argument("--asr-model", default="base", help="ASR model")
    parser.add_argument("--skip-existing", action="store_true", help="Skip outputs that already exist")
    parser.add_argument("--no-vocal", action="store_true", help="Skip vocal separation and use the input file directly")
    parser.add_argument("--vtt-dir", default=None, help="Directory to search for an existing VTT subtitle file")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file does not exist: {input_path}")
        return 1

    output_dir = _resolve_output_dir(input_path, args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    vtt_path = _find_vtt_path(input_path, args.vtt_dir)
    tts_voice = _resolve_tts_voice(args.tts_engine, args.tts_voice)

    print("=" * 60)
    print("ASMR Helper - Bilingual Pipeline")
    print("=" * 60)
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")
    if vtt_path:
        print(f"Subtitle: {vtt_path}")
    if args.no_vocal:
        print("Mode: reuse original audio without vocal separation")
    print()

    request = PipelineRequest(
        input_path=str(input_path),
        output_dir=str(output_dir),
        vtt_path=str(vtt_path) if vtt_path else None,
        source_lang="ja",
        target_lang="zh",
        use_vocal_separator=not args.no_vocal,
        tts_engine=args.tts_engine,
        tts_voice=tts_voice,
        vocal_model=args.vocal_model,
        asr_model=args.asr_model,
        translate_provider="deepseek",
        tts_speed=args.tts_speed,
        original_volume=args.original_volume,
        tts_volume_ratio=args.tts_ratio,
        tts_delay=args.tts_delay,
        skip_existing=args.skip_existing,
    )

    try:
        result = get_pipeline_service().run_audio_pipeline(request)
    except AppError as exc:
        print(f"Error: {exc}")
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    print("Pipeline completed.")
    if result.mix_path:
        print(f"Mix: {result.mix_path}")
    if result.exported_subtitle:
        print(f"Subtitle Output: {result.exported_subtitle}")
    if result.error_message:
        print(f"Warning: {result.error_message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
