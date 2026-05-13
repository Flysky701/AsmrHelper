#!/usr/bin/env python
"""Compatibility wrapper for shared model-management installation."""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.resources import get_model_service


WHISPER_IDS = {
    "tiny": "faster-whisper-tiny",
    "base": "faster-whisper-base",
    "small": "faster-whisper-small",
    "medium": "faster-whisper-medium",
    "large-v3": "faster-whisper-large-v3",
}

QWEN3_IDS = {
    "CustomVoice": "qwen3-custom-voice",
    "VoiceDesign": "qwen3-voice-design",
    "Base": "qwen3-base",
}


def print_header(title: str):
    print()
    print("=" * 65)
    print(f"  {title}")
    print("=" * 65)


def print_step(msg: str):
    print(f"  [INFO] {msg}")


def print_ok(msg: str):
    print(f"  [OK] {msg}")


def print_fail(msg: str):
    print(f"  [FAIL] {msg}")


def check_status(service) -> bool:
    print_header("模型状态检查")
    all_ok = True
    for status in service.get_all_statuses(kind="local"):
        marker = print_ok if status.status == "installed" else print_fail
        marker(f"{status.model_id}: {status.status} - {status.detail}")
        all_ok = all_ok and status.status == "installed"
    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="AsmrHelper 模型下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="仅检查模型状态，不下载")
    parser.add_argument("--whisper", nargs="?", const="base", help="下载 Whisper 模型")
    parser.add_argument("--qwen3", nargs="?", const="all", help="下载 Qwen3-TTS 模型")
    parser.add_argument("--all", action="store_true", help="下载全部模型")
    parser.add_argument("--mirror", type=str, default=None, help="HuggingFace 镜像地址")
    parser.add_argument("--force", action="store_true", help="强制重新下载已存在的模型")
    args = parser.parse_args()

    service = get_model_service()

    if args.check:
        raise SystemExit(0 if check_status(service) else 1)

    targets = []
    if args.all:
        targets.extend(WHISPER_IDS.values())
        targets.extend(QWEN3_IDS.values())
    else:
        if args.whisper is not None:
            model_id = WHISPER_IDS.get(args.whisper)
            if not model_id:
                print_fail(f"未知的 Whisper 模型: {args.whisper}")
                raise SystemExit(1)
            targets.append(model_id)
        if args.qwen3 is not None:
            if args.qwen3 == "all":
                targets.extend(QWEN3_IDS.values())
            else:
                model_id = QWEN3_IDS.get(args.qwen3)
                if not model_id:
                    print_fail(f"未知的 Qwen3 模型: {args.qwen3}")
                    raise SystemExit(1)
                targets.append(model_id)

    if not targets:
        targets.append("faster-whisper-base")

    print_header(f"下载模型: {', '.join(targets)}")
    success_count = 0
    fail_count = 0

    for model_id in targets:
        print_step(f"处理模型: {model_id}")
        try:
            ok = service.install(model_id, mirror=args.mirror, force=args.force)
        except Exception as exc:
            ok = False
            print_fail(f"{model_id}: {exc}")

        if ok:
            print_ok(model_id)
            success_count += 1
        else:
            print_fail(model_id)
            fail_count += 1

    print_header("下载结果")
    print(f"  {success_count} 成功, {fail_count} 失败")
    check_status(service)
    raise SystemExit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
