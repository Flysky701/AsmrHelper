#!/usr/bin/env python3
"""
批量处理脚本 - ASMR 双语双轨批量处理

用法:
    # 处理整个文件夹
    python scripts/batch_process.py --input-dir "D:/ASMR_WORK/RJ12345678"

    # 处理多个指定文件
    python scripts/batch_process.py --input "file1.wav" "file2.wav" "file3.wav"

    # 使用参数
    python scripts/batch_process.py --input-dir "D:/ASMR" --tts-ratio 0.6 --tts-delay 50
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# 添加项目根目录到 sys.path（支持直接运行脚本）
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core import (
    VocalSeparator,
    ASRRecognizer,
    Translator,
    TTSEngine,
)
from src.mixer import Mixer


# 支持的音频格式
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}


def find_audio_files(directory: str) -> List[Path]:
    """递归查找目录中的音频文件"""
    audio_files = []
    for ext in AUDIO_EXTENSIONS:
        audio_files.extend(Path(directory).rglob(f"*{ext}"))
    return sorted(audio_files)


def process_single_file(
    input_path: Path,
    output_base_dir: Optional[Path] = None,
    skip_existing: bool = True,
    **params
) -> dict:
    """
    处理单个音频文件

    Args:
        input_path: 输入文件路径
        output_base_dir: 输出基础目录
        skip_existing: 跳过已存在的输出
        **params: 其他参数

    Returns:
        dict: 处理结果
    """
    result = {
        "file": str(input_path),
        "status": "pending",
        "error": None,
        "output": None,
        "time": 0,
    }

    t0 = time.time()

    try:
        # 设置输出目录
        if output_base_dir:
            # 在输出基础目录下创建与输入文件同结构的子目录
            safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in input_path.stem)
            output_dir = output_base_dir / safe_name
        else:
            safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in input_path.stem)
            output_dir = input_path.parent / f"{safe_name}_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 如果已存在且跳过
        final_mix = output_dir / "final_mix.wav"
        if skip_existing and final_mix.exists():
            result["status"] = "skipped"
            result["output"] = str(final_mix)
            result["time"] = time.time() - t0
            return result

        print(f"\n{'='*60}")
        print(f"[批量处理] 处理: {input_path.name}")
        print(f"{'='*60}")

        # ===== Step 1: 人声分离 =====
        print("[1/5] 人声分离...")
        separator = VocalSeparator(model_name=params.get("vocal_model", "htdemucs"))
        sep_results = separator.separate(str(input_path), str(output_dir), stems=["vocals"])
        vocal_path = Path(sep_results.get("vocals", ""))
        if not vocal_path.exists():
            raise RuntimeError("人声分离失败")

        # ===== Step 2: ASR 识别 =====
        print("[2/5] ASR 识别...")
        recognizer = ASRRecognizer(
            model_size=params.get("asr_model", "base"),
            language="ja"
        )
        asr_path = output_dir / "asr_result.txt"
        asr_results = recognizer.recognize(str(vocal_path), str(asr_path))
        print(f"  -> 识别到 {len(asr_results)} 段")

        if not asr_results:
            raise RuntimeError("ASR 未识别到任何内容")

        # ===== Step 3: 翻译 =====
        print("[3/5] 翻译...")
        translator = Translator(provider="deepseek")
        texts = [r["text"] for r in asr_results]
        translations = translator.translate_batch(texts)
        trans_path = output_dir / "translated.txt"
        trans_path.write_text("\n".join(translations), encoding="utf-8")

        # ===== Step 4: TTS 合成 =====
        print(f"[4/5] TTS 合成...")
        tts_engine = TTSEngine(
            engine=params.get("tts_engine", "edge"),
            voice=params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
            speed=params.get("tts_speed", 1.0),
        )
        full_text = "。".join(translations)
        tts_ext = "wav" if params.get("tts_engine") == "qwen3" else "mp3"
        tts_path = output_dir / f"tts_output.{tts_ext}"
        tts_engine.synthesize(full_text, str(tts_path))

        # ===== Step 5: 混音 =====
        print("[5/5] 混音...")
        mixer = Mixer(
            original_volume=params.get("original_volume", 0.85),
            tts_volume_ratio=params.get("tts_ratio", 0.5),
            tts_delay_ms=params.get("tts_delay", 0),
        )
        mixer.mix(str(vocal_path), str(tts_path), str(final_mix))

        result["status"] = "success"
        result["output"] = str(final_mix)
        result["time"] = time.time() - t0
        print(f"\n[完成] {input_path.name} -> {final_mix.name} ({result['time']:.1f}s)")

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        result["time"] = time.time() - t0
        print(f"\n[失败] {input_path.name}: {e}")

    return result


def batch_process(
    input_files: List[Path],
    output_base_dir: Optional[Path] = None,
    max_workers: int = 1,
    **params
) -> List[dict]:
    """
    批量处理多个文件

    Args:
        input_files: 输入文件列表
        output_base_dir: 输出基础目录
        max_workers: 并行处理数
        **params: 其他参数

    Returns:
        List[dict]: 处理结果列表
    """
    results = []
    total = len(input_files)

    print(f"\n{'#'*60}")
    print(f"# ASMR 批量处理")
    print(f"# 文件数: {total}")
    print(f"# 并行数: {max_workers}")
    print(f"# 输出目录: {output_base_dir or '与源文件同目录'}")
    print(f"{'#'*60}\n")

    if max_workers > 1:
        print(
            f"[警告] workers={max_workers} 时，每个线程都会独立加载 Demucs + Whisper 模型到 GPU。\n"
            f"       RTX 4070 Ti SUPER (16GB) 建议 workers <= 1（串行处理）。\n"
            f"       若显存不足请设置 --workers 1 以避免 OOM。"
        )


    if max_workers == 1:
        # 串行处理
        for i, input_path in enumerate(input_files, 1):
            print(f"\n[文件 {i}/{total}]")
            result = process_single_file(input_path, output_base_dir, **params)
            results.append(result)
    else:
        # 并行处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_single_file, f, output_base_dir, **params): f
                for f in input_files
            }

            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                results.append(result)
                print(f"\n[进度 {i}/{total}] {result['status']}: {Path(result['file']).name}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="ASMR 双语双轨批量处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 处理整个文件夹
  python scripts/batch_process.py --input-dir "D:/ASMR/RJ12345678"

  # 处理多个文件
  python scripts/batch_process.py -i "file1.wav" "file2.wav"

  # 带参数处理
  python scripts/batch_process.py -i "file.wav" --tts-ratio 0.6 --tts-delay 50

  # 并行处理（最多2个）
  python scripts/batch_process.py --input-dir "D:/ASMR" --workers 2
        """
    )

    # 输入源（互斥）
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input-dir", "-d", help="输入目录（递归处理所有音频）")
    input_group.add_argument("--input", "-i", nargs="+", help="输入文件列表")

    # 输出设置
    parser.add_argument("--output", "-o", default=None, help="输出基础目录")
    parser.add_argument("--skip-existing", "-s", action="store_true", default=True,
                        help="跳过已处理的文件（默认）")
    parser.add_argument("--no-skip", action="store_true", help="不跳过，重新处理")

    # TTS 设置
    parser.add_argument("--tts-engine", default="edge", choices=["edge", "qwen3"],
                        help="TTS 引擎 (默认: edge)")
    parser.add_argument("--tts-voice", default="zh-CN-XiaoxiaoNeural",
                        help="TTS 音色 (默认: zh-CN-XiaoxiaoNeural)")
    parser.add_argument("--tts-speed", type=float, default=1.0,
                        help="Qwen3 语速 0.5-2.0 (默认: 1.0)")

    # 混音设置
    parser.add_argument("--original-volume", type=float, default=0.85,
                        help="原音音量 0.0-1.0 (默认: 0.85)")
    parser.add_argument("--tts-ratio", type=float, default=0.5,
                        help="配音音量比例 0.0-1.0 (默认: 0.5)")
    parser.add_argument("--tts-delay", type=float, default=0,
                        help="TTS 延迟 ms (默认: 0)")

    # 模型设置
    parser.add_argument("--vocal-model", default="htdemucs", help="人声分离模型")
    parser.add_argument("--asr-model", default="base", help="ASR 模型")

    # 性能设置
    parser.add_argument("--workers", type=int, default=1,
                        help="并行处理数 (默认: 1)")

    args = parser.parse_args()

    # 设置跳过逻辑
    skip_existing = not args.no_skip

    # 获取输入文件
    if args.input_dir:
        audio_files = find_audio_files(args.input_dir)
        if not audio_files:
            print(f"错误: 目录中未找到音频文件: {args.input_dir}")
            return 1
        print(f"找到 {len(audio_files)} 个音频文件")
    else:
        audio_files = [Path(f) for f in args.input]
        # 检查文件存在
        missing = [f for f in audio_files if not f.exists()]
        if missing:
            print(f"错误: 以下文件不存在:")
            for f in missing:
                print(f"  - {f}")
            return 1

    # 设置输出目录
    output_base_dir = Path(args.output) if args.output else None

    # 构建参数
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

    # 开始批量处理
    t0 = time.time()
    results = batch_process(audio_files, output_base_dir, args.workers, **params)

    # 打印统计
    total_time = time.time() - t0
    success = sum(1 for r in results if r["status"] == "success")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")

    print(f"\n{'#'*60}")
    print(f"# 处理完成!")
    print(f"# 总文件: {len(results)}")
    print(f"# 成功: {success}")
    print(f"# 跳过: {skipped}")
    print(f"# 失败: {failed}")
    print(f"# 总耗时: {total_time:.1f}s")
    print(f"{'#'*60}")

    # 输出失败的文件
    if failed > 0:
        print("\n失败的文件:")
        for r in results:
            if r["status"] == "failed":
                print(f"  - {r['file']}: {r['error']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
