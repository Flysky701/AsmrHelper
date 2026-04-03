#!/usr/bin/env python3
"""
ASMR 双语双轨处理脚本

用法:
    python scripts/asmr_bilingual.py --input audio.wav

参数:
    --input: 输入音频文件
    --output: 输出目录（可选，默认与输入同目录）
    --tts-engine: TTS 引擎 (edge/qwen3)
    --tts-voice: TTS 音色
    --tts-delay: TTS 延迟 ms (正=延后，负=提前, 范围 -3000~3000)
    --tts-ratio: TTS 音量相对于原声的比例 (0.0-1.0)
"""

import os
import sys
import argparse
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core import (
    VocalSeparator,
    ASRRecognizer,
    Translator,
    TTSEngine,
)
from src.core.translate import load_vtt_translations
from src.mixer import Mixer


def main():
    parser = argparse.ArgumentParser(description="ASMR 双语双轨处理")
    parser.add_argument("--input", "-i", required=True, help="输入音频文件")
    parser.add_argument("--output", "-o", default=None, help="输出目录")
    parser.add_argument("--tts-engine", default="edge", choices=["edge", "qwen3"], help="TTS 引擎")
    parser.add_argument("--tts-voice", default="zh-CN-XiaoxiaoNeural", help="TTS 音色")
    parser.add_argument("--tts-speed", type=float, default=1.0, help="Qwen3 语速 (0.5-2.0)")
    parser.add_argument("--tts-delay", type=float, default=0, help="TTS 延迟 (ms)")
    parser.add_argument("--tts-ratio", type=float, default=0.5, help="TTS 音量比例 (0.0-1.0)")
    parser.add_argument("--original-volume", type=float, default=0.85, help="原音音量 (0.0-1.0)")
    parser.add_argument("--vocal-model", default="htdemucs", help="人声分离模型")
    parser.add_argument("--asr-model", default="base", help="ASR 模型")
    parser.add_argument("--skip-existing", action="store_true", help="跳过已存在的步骤")
    parser.add_argument("--no-vocal", action="store_true", help="跳过人声分离（直接使用输入文件）")
    parser.add_argument("--vtt-dir", default=None, help="VTT字幕目录（与输入同目录时可不指定）")

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 输入文件不存在: {input_path}")
        return 1

    # 输出目录（使用安全的目录名）
    if args.output:
        output_dir = Path(args.output)
    else:
        # 清理文件名中的特殊字符
        safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in input_path.stem)
        output_dir = input_path.parent / f"{safe_name}_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ASMR Helper - 双语双轨处理")
    print("=" * 60)
    print(f"输入: {input_path}")
    print(f"输出: {output_dir}")
    print()

    # ===== Step 1: 人声分离 =====
    if args.no_vocal:
        vocal_path = str(input_path)
        print("[跳过] 人声分离")
    else:
        vocal_path = output_dir / "vocal.wav"
        if args.skip_existing and vocal_path.exists():
            print(f"[跳过] 人声分离已存在")
        else:
            print("[1/5] 人声分离 (Demucs)...")
            separator = VocalSeparator(model_name=args.vocal_model)
            results = separator.separate(str(input_path), str(output_dir), stems=["vocals"])
            vocal_path = Path(results.get("vocals", ""))
            print(f"  -> {vocal_path.name}")

    # ===== Step 2: ASR 识别 =====
    asr_path = output_dir / "asr_result.txt"
    if args.skip_existing and asr_path.exists():
        print(f"[跳过] ASR 识别已存在")
        asr_results = []
        for line in asr_path.read_text(encoding="utf-8").split("\n"):
            if line.strip() and not line.startswith("["):
                asr_results.append({"text": line.strip()})
    else:
        print("[2/5] ASR 语音识别 (Whisper)...")
        recognizer = ASRRecognizer(model_size=args.asr_model, language="ja")
        asr_results = recognizer.recognize(str(vocal_path), str(asr_path))
        print(f"  -> 识别到 {len(asr_results)} 段")

    # ===== Step 3: 翻译 =====
    trans_path = output_dir / "translated.txt"

    # 查找 VTT 文件
    vtt_path = None

    # 可能的 VTT 目录列表
    vtt_search_dirs = []
    if args.vtt_dir:
        vtt_search_dirs.append(Path(args.vtt_dir))
    # 默认在输入文件同目录和 ASMR_O 目录查找
    vtt_search_dirs.append(input_path.parent)
    asmr_o_dir = input_path.parent / "ASMR_O"
    if asmr_o_dir.exists():
        vtt_search_dirs.append(asmr_o_dir)

    # 查找对应的 VTT 文件
    possible_vtt_names = [
        f"{input_path.name}.vtt",  # audio.wav.vtt
        f"{input_path.stem}.vtt",  # audio.vtt
    ]

    for search_dir in vtt_search_dirs:
        for vtt_name in possible_vtt_names:
            candidate = search_dir / vtt_name
            if candidate.exists():
                vtt_path = candidate
                break
        if vtt_path:
            break

    if vtt_path:
        print(f"[INFO] 找到 VTT 字幕: {vtt_path}")

    if vtt_path:
        # 使用 VTT 字幕作为翻译
        print(f"[3/5] 加载翻译 (VTT: {vtt_path.name})...")
        translations = load_vtt_translations(str(vtt_path))
        trans_path.write_text("\n".join(translations), encoding="utf-8")
        print(f"  -> 加载了 {len(translations)} 条翻译")
    elif args.skip_existing and trans_path.exists():
        # 跳过已存在
        print(f"[跳过] 翻译已存在")
        translations = trans_path.read_text(encoding="utf-8").split("\n")
    else:
        # 调用 API 翻译
        print("[3/5] 翻译 (DeepSeek)...")
        translator = Translator(provider="deepseek")
        texts = [r["text"] for r in asr_results]
        translations = translator.translate_batch(texts)
        trans_path.write_text("\n".join(translations), encoding="utf-8")
        print(f"  -> 翻译了 {len(translations)} 段")

    # ===== Step 4: TTS 合成 =====
    ext = "wav" if args.tts_engine == "qwen3" else "mp3"
    tts_path = output_dir / f"tts_output.{ext}"
    if args.skip_existing and tts_path.exists():
        print(f"[跳过] TTS 合成已存在")
    else:
        voice = args.tts_voice if args.tts_engine == "edge" else "Vivian"
        print(f"[4/5] TTS 合成 ({args.tts_engine}, {voice}, speed={args.tts_speed})...")
        tts_engine = TTSEngine(
            engine=args.tts_engine,
            voice=voice,
            speed=args.tts_speed,
        )
        full_text = "。".join(translations)
        tts_engine.synthesize(full_text, str(tts_path))
        print(f"  -> {tts_path.name}")

    # ===== Step 5: 混音 =====
    mix_path = output_dir / "final_mix.wav"
    if args.skip_existing and mix_path.exists():
        print(f"[跳过] 混音已存在")
    else:
        print("[5/5] 混音...")
        print(f"  原音音量: {args.original_volume*100:.0f}%")
        print(f"  配音音量: {args.tts_ratio*100:.0f}%")
        print(f"  TTS延迟: {args.tts_delay}ms")
        mixer = Mixer(
            original_volume=args.original_volume,
            tts_volume_ratio=args.tts_ratio,
            tts_delay_ms=args.tts_delay,
        )
        mixer.mix(str(vocal_path), str(tts_path), str(mix_path))
        print(f"  -> {mix_path.name}")

    # 完成
    print()
    print("=" * 60)
    print("处理完成!")
    print("=" * 60)
    print(f"输出目录: {output_dir}")
    print(f"最终文件: {mix_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
