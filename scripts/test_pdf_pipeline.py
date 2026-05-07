#!/usr/bin/env python3
"""
PDF→VTT 流水线独立测试脚本

用法：
    # 纯文本模式（不需要 LLM/ASR）
    python scripts/test_pdf_pipeline.py --pdf sample.pdf --debug-dir ./debug

    # 完整流水线（需要 LLM API key + 音频）
    python scripts/test_pdf_pipeline.py --pdf sample.pdf --audio sample.mp3 --output output.vtt --debug-dir ./debug

    # 已有 VTT 模式
    python scripts/test_pdf_pipeline.py --pdf sample.pdf --vtt existing.vtt --output output.vtt --debug-dir ./debug
"""

import argparse
import json
import sys
from pathlib import Path

# Windows 控制台 UTF-8 输出支持
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def print_stage_summary(debug_dir: Path) -> None:
    """打印各阶段统计信息"""
    print("\n" + "=" * 60)
    print("流水线各阶段统计")
    print("=" * 60)

    stages = {
        "stage1_extract": "Stage 1: PDF 提取",
        "stage1_clean": "Stage 1: 文本清洗",
        "stage2_asr": "Stage 2: ASR 识别",
        "stage3_align": "Stage 3: LLM 对齐",
        "stage4_output": "Stage 4: 最终输出",
    }

    for stage_dir, label in stages.items():
        stage_path = debug_dir / stage_dir
        if not stage_path.exists():
            print(f"\n  {label}: (未生成)")
            continue

        print(f"\n  {label}:")
        for f in sorted(stage_path.iterdir()):
            size = f.stat().st_size
            if f.suffix == ".txt":
                content = f.read_text(encoding="utf-8")
                lines = content.splitlines()
                non_empty = [l for l in lines if l.strip()]
                print(f"    {f.name}: {size} bytes, {len(lines)} 行 ({len(non_empty)} 非空)")
                # 显示前 5 行预览
                for i, line in enumerate(non_empty[:5]):
                    preview = line[:80] + "..." if len(line) > 80 else line
                    print(f"      [{i+1}] {preview}")
                if len(non_empty) > 5:
                    print(f"      ... (还有 {len(non_empty) - 5} 行)")
            elif f.suffix == ".json":
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        print(f"    {f.name}: {size} bytes, {len(data)} 条目")
                        for i, item in enumerate(data[:3]):
                            preview = json.dumps(item, ensure_ascii=False)[:100]
                            print(f"      [{i+1}] {preview}")
                        if len(data) > 3:
                            print(f"      ... (还有 {len(data) - 3} 条)")
                    else:
                        print(f"    {f.name}: {size} bytes")
                except json.JSONDecodeError:
                    print(f"    {f.name}: {size} bytes (JSON 解析失败)")
            else:
                print(f"    {f.name}: {size} bytes")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="PDF→VTT 流水线测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--pdf", required=True, help="PDF 台本文件路径")
    parser.add_argument("--audio", help="音频文件路径（可选，用于 ASR）")
    parser.add_argument("--vtt", help="已有 VTT 字幕路径（可选，跳过 ASR）")
    parser.add_argument("--output", help="输出文件路径（可选）")
    parser.add_argument("--debug-dir", default="./debug", help="调试输出目录（默认 ./debug）")
    parser.add_argument("--use-llm", action="store_true", default=False, help="启用 LLM 辅助清洗")
    parser.add_argument("--track", type=int, default=None, help="指定 Track 索引（从 0 开始），用于多 Track 台本")
    parser.add_argument("--fmt", default="vtt", choices=["vtt", "srt", "lrc"], help="输出格式")

    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"错误: PDF 文件不存在: {pdf_path}")
        sys.exit(1)

    debug_dir = Path(args.debug_dir)
    output_path = Path(args.output) if args.output else debug_dir / "output" / f"output.{args.fmt}"

    from src.core.script_to_subtitle.pipeline import PDFToSubtitlePipeline

    pipeline = PDFToSubtitlePipeline()

    def progress(stage, pct, msg):
        print(f"  [{stage}] {pct:3d}% - {msg}")

    print(f"PDF 文件: {pdf_path}")
    print(f"调试目录: {debug_dir}")
    print(f"输出文件: {output_path}")
    print(f"LLM 清洗: {'启用' if args.use_llm else '禁用'}")
    print(f"Track 索引: {args.track}" if args.track is not None else "Track 索引: 全部")

    if args.audio:
        # 完整流水线
        audio_path = Path(args.audio)
        if not audio_path.exists():
            print(f"错误: 音频文件不存在: {audio_path}")
            sys.exit(1)
        print(f"音频文件: {audio_path}")
        print("\n开始完整流水线 (PDF + 音频 → 字幕)...")
        pipeline.run(
            pdf_path=pdf_path,
            audio_path=audio_path,
            output_path=output_path,
            fmt=args.fmt,
            use_llm_clean=args.use_llm,
            track_index=args.track,
            progress_callback=progress,
            debug_dir=debug_dir,
        )
    elif args.vtt:
        # 已有 VTT 模式
        vtt_path = Path(args.vtt)
        if not vtt_path.exists():
            print(f"错误: VTT 文件不存在: {vtt_path}")
            sys.exit(1)
        print(f"VTT 文件: {vtt_path}")
        print("\n开始已有 VTT 模式 (PDF + VTT → 对齐字幕)...")
        pipeline.run_from_existing_vtt(
            pdf_path=pdf_path,
            vtt_path=vtt_path,
            output_path=output_path,
            fmt=args.fmt,
            use_llm_clean=args.use_llm,
            track_index=args.track,
            progress_callback=progress,
            debug_dir=debug_dir,
        )
    else:
        # 纯文本模式
        print("\n开始纯文本模式 (PDF → 清洗文本)...")
        clean_text = pipeline.run_text_only(
            pdf_path=pdf_path,
            output_path=output_path if args.output else None,
            use_llm_clean=args.use_llm,
            track_index=args.track,
            progress_callback=progress,
            debug_dir=debug_dir,
        )
        print(f"\n清洗完成，共 {len(clean_text.splitlines())} 行台词")

    print_stage_summary(debug_dir)
    print("\n完成！")


if __name__ == "__main__":
    main()
