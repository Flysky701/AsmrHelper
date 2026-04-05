#!/usr/bin/env python
"""
模型下载安装脚本

功能：
1. 下载 Faster-Whisper ASR 模型（支持 tiny/base/small/medium/large-v3）
2. 下载 Qwen3-TTS 模型（CustomVoice / VoiceDesign / Base）
3. 验证已下载模型的完整性

用法：
    uv run python scripts/install_models.py                    # 下载所有基础模型
    uv run python scripts/install_models.py --check            # 仅检查模型状态
    uv run python scripts/install_models.py --whisper base     # 仅下载指定 ASR 模型
    uv run python scripts/install_models.py --qwen3            # 下载所有 Qwen3-TTS 模型
    uv run python scripts/install_models.py --qwen3 CustomVoice # 仅下载指定 Qwen3 模型
    uv run python scripts/install_models.py --all              # 下载全部模型（含 Qwen3）
    uv run python scripts/install_models.py --mirror https://hf-mirror.com  # 使用 HuggingFace 镜像
"""

import sys
import os
import argparse
from pathlib import Path
from typing import Optional

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


# ============================================================
# 模型定义
# ============================================================

# Faster-Whisper 模型（HuggingFace 仓库 -> 本地目录）
WHISPER_MODELS = {
    "tiny":      {"repo": "guillaumeln/rft-tiny",    "size_mb": 39,   "desc": "最快，精度低"},
    "base":      {"repo": "guillaumeln/rft-base",    "size_mb": 74,   "desc": "速度与精度的平衡（推荐）"},
    "small":     {"repo": "guillaumeln/rft-small",   "size_mb": 244,  "desc": "较高精度"},
    "medium":    {"repo": "guillaumeln/rft-medium",  "size_mb": 769,  "desc": "高精度"},
    "large-v3":  {"repo": "guillaumeln/rft-large-v3", "size_mb": 1550, "desc": "最高精度（需要 10GB+ 显存）"},
}

# Qwen3-TTS 模型
QWEN3_MODELS = {
    "CustomVoice": {
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "local_subdir": "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "size_mb": "~8400",
        "desc": "预设音色合成（9 个内置 speaker）",
        "required_files": ["model.safetensors", "config.json", "vocab.json"],
        "required_dirs": ["speech_tokenizer"],
    },
    "VoiceDesign": {
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "local_subdir": "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "size_mb": "~8400",
        "desc": "自然语言音色生成",
        "required_files": ["model.safetensors", "config.json", "vocab.json"],
        "required_dirs": ["speech_tokenizer"],
    },
    "Base": {
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "local_subdir": "models--Qwen--Qwen3-TTS-12Hz-1.7B-Base",
        "size_mb": "~8400",
        "desc": "音色克隆（voice_clone）",
        "required_files": ["model.safetensors", "config.json", "vocab.json"],
        "required_dirs": ["speech_tokenizer"],
    },
}


# ============================================================
# 工具函数
# ============================================================

def print_header(title: str):
    print()
    print("=" * 65)
    print(f"  {title}")
    print("=" * 65)


def print_step(msg: str):
    print(f"  [INFO] {msg}")


def print_ok(msg: str):
    print(f"  [OK] {msg}")


def print_warn(msg: str):
    print(f"  [WARN] {msg}")


def print_fail(msg: str):
    print(f"  [FAIL] {msg}")


def get_dir_size_mb(path: Path) -> float:
    """计算目录大小 (MB)"""
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def verify_qwen3_model(model_dir: Path, model_info: dict) -> bool:
    """验证 Qwen3-TTS 模型完整性"""
    if not model_dir.exists():
        return False

    for f in model_info.get("required_files", []):
        if not (model_dir / f).exists():
            return False

    for d in model_info.get("required_dirs", []):
        if not (model_dir / d).exists():
            return False

    return True


def verify_whisper_model(model_dir: Path) -> bool:
    """验证 Faster-Whisper 模型完整性"""
    if not model_dir.exists():
        return False

    # 检查模型文件（CTranslate2 格式）
    required_patterns = ["model.bin", "config.json", "tokenizer.json"]
    for pattern in required_patterns:
        if not any(model_dir.glob(f"*{pattern}*")):
            return False

    return True


# ============================================================
# 下载函数
# ============================================================

def download_whisper_model(model_name: str, mirror: Optional[str] = None, force: bool = False) -> bool:
    """
    下载 Faster-Whisper 模型

    Args:
        model_name: 模型大小 (tiny/base/small/medium/large-v3)
        mirror: HuggingFace 镜像地址 (如 https://hf-mirror.com)
        force: 强制重新下载

    Returns:
        是否成功
    """
    if model_name not in WHISPER_MODELS:
        print_fail(f"未知的 Whisper 模型: {model_name}")
        print_warn(f"可用模型: {', '.join(WHISPER_MODELS.keys())}")
        return False

    info = WHISPER_MODELS[model_name]
    target_dir = project_root / "models" / "whisper" / model_name

    if target_dir.exists() and not force:
        size = get_dir_size_mb(target_dir)
        if size > 10:  # 大于 10MB 认为已下载
            print_ok(f"Whisper {model_name} 已存在 ({size:.1f} MB)，跳过（使用 --force 重新下载）")
            return True

    print_step(f"下载 Whisper {model_name} ({info['desc']}, 约 {info['size_mb']} MB)...")

    # 设置镜像环境变量
    env = os.environ.copy()
    if mirror:
        env["HF_ENDPOINT"] = mirror
        print_step(f"使用镜像: {mirror}")

    # 使用 faster_whisper 的 download_model 函数下载
    cmd = [
        sys.executable, "-c",
        f"""
import sys
sys.stderr = open(os.devnull, 'w')
from faster_whisper import download_model
path = download_model("{info['repo']}", output_dir="{str(target_dir)}")
print(path)
"""
    ]

    import subprocess
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(project_root),
            env=env,
            timeout=600,  # 10 分钟超时
        )

        if result.returncode == 0:
            # faster_whisper 下载到子目录，检查实际路径
            downloaded_path = result.stdout.strip()
            if downloaded_path and Path(downloaded_path).exists():
                size = get_dir_size_mb(Path(downloaded_path))
                print_ok(f"Whisper {model_name} 下载完成: {downloaded_path} ({size:.1f} MB)")
                return True
            # 回退：检查目标目录
            if verify_whisper_model(target_dir):
                size = get_dir_size_mb(target_dir)
                print_ok(f"Whisper {model_name} 下载完成 ({size:.1f} MB)")
                return True
            # 可能下载到了 target_dir 内的子目录
            for sub in target_dir.iterdir():
                if sub.is_dir() and verify_whisper_model(sub):
                    size = get_dir_size_mb(sub)
                    print_ok(f"Whisper {model_name} 下载完成: {sub.name} ({size:.1f} MB)")
                    return True
            print_fail(f"Whisper {model_name} 下载后验证失败")
            return False
        else:
            error = result.stderr.strip() if result.stderr else result.stdout.strip()
            print_fail(f"Whisper {model_name} 下载失败: {error}")
            return False
    except subprocess.TimeoutExpired:
        print_fail(f"Whisper {model_name} 下载超时（10 分钟）")
        return False
    except Exception as e:
        print_fail(f"Whisper {model_name} 下载异常: {e}")
        return False


def download_qwen3_model(model_name: str, mirror: Optional[str] = None, force: bool = False) -> bool:
    """
    下载 Qwen3-TTS 模型

    Args:
        model_name: 模型类型 (CustomVoice/VoiceDesign/Base)
        mirror: HuggingFace 镜像地址
        force: 强制重新下载

    Returns:
        是否成功
    """
    if model_name not in QWEN3_MODELS:
        print_fail(f"未知的 Qwen3 模型: {model_name}")
        print_warn(f"可用模型: {', '.join(QWEN3_MODELS.keys())}")
        return False

    info = QWEN3_MODELS[model_name]
    target_dir = project_root / "models" / "qwen3tts" / info["local_subdir"]

    if target_dir.exists() and not force:
        if verify_qwen3_model(target_dir, info):
            size = get_dir_size_mb(target_dir)
            print_ok(f"Qwen3 {model_name} 已存在 ({size:.1f} MB)，跳过（使用 --force 重新下载）")
            return True
        else:
            print_warn(f"Qwen3 {model_name} 目录存在但不完整，将重新下载")

    print_step(f"下载 Qwen3 {model_name} ({info['desc']}, 约 {info['size_mb']} MB)...")

    # 设置镜像环境变量
    env = os.environ.copy()
    if mirror:
        env["HF_ENDPOINT"] = mirror
        print_step(f"使用镜像: {mirror}")

    import subprocess
    try:
        cmd = [sys.executable, "-m", "huggingface_hub.commands.huggingface_cli",
               "download", info["repo"],
               "--local-dir", str(target_dir),
               "--local-dir-use-symlinks", "False"]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(project_root),
            env=env,
            timeout=3600,  # 60 分钟超时（Qwen3 模型很大）
        )

        if result.returncode == 0:
            if verify_qwen3_model(target_dir, info):
                size = get_dir_size_mb(target_dir)
                print_ok(f"Qwen3 {model_name} 下载完成 ({size:.1f} MB)")
                return True
            else:
                print_fail(f"Qwen3 {model_name} 下载后验证失败（文件不完整）")
                return False
        else:
            error = result.stderr.strip() if result.stderr else result.stdout.strip()
            print_fail(f"Qwen3 {model_name} 下载失败: {error}")
            return False

    except subprocess.TimeoutExpired:
        print_fail(f"Qwen3 {model_name} 下载超时（60 分钟）")
        return False
    except FileNotFoundError:
        print_fail("huggingface-cli 未找到，请确保已安装 huggingface_hub")
        print_step("运行: uv add huggingface_hub")
        return False
    except Exception as e:
        print_fail(f"Qwen3 {model_name} 下载异常: {e}")
        return False


# ============================================================
# 状态检查
# ============================================================

def check_status():
    """检查所有模型状态"""
    print_header("模型状态检查")

    # Whisper 模型
    print()
    print("--- Faster-Whisper ASR 模型 ---")
    print()

    whisper_dir = project_root / "models" / "whisper"
    whisper_ok = 0
    whisper_total = len(WHISPER_MODELS)

    for name, info in WHISPER_MODELS.items():
        # faster_whisper 会下载到 models/whisper/<model_name>/ 或 models/whisper/models--guillaumeln--rft-<model>/
        model_dir = whisper_dir / name
        alt_dir = whisper_dir / f"models--guillaumeln--rft-{name}"

        found = False
        found_path = None
        for d in [model_dir, alt_dir]:
            if d.exists():
                size = get_dir_size_mb(d)
                if size > 10:
                    found = True
                    found_path = d
                    break

        if found:
            print_ok(f"  {name:12s} 已下载 ({get_dir_size_mb(found_path):.1f} MB) - {info['desc']}")
            whisper_ok += 1
        else:
            print_warn(f"  {name:12s} 未下载 - {info['desc']} (约 {info['size_mb']} MB)")

    # Qwen3 模型
    print()
    print("--- Qwen3-TTS 模型 ---")
    print()

    qwen3_ok = 0
    qwen3_total = len(QWEN3_MODELS)

    for name, info in QWEN3_MODELS.items():
        model_dir = project_root / "models" / "qwen3tts" / info["local_subdir"]

        if verify_qwen3_model(model_dir, info):
            size = get_dir_size_mb(model_dir)
            print_ok(f"  {name:12s} 已下载 ({size:.1f} MB) - {info['desc']}")
            qwen3_ok += 1
        else:
            print_warn(f"  {name:12s} 未下载/不完整 - {info['desc']} (约 {info['size_mb']} MB)")

    # 总计
    print()
    print("-" * 50)
    total_ok = whisper_ok + qwen3_ok
    total_all = whisper_total + qwen3_total
    print(f"  Whisper: {whisper_ok}/{whisper_total}  |  Qwen3: {qwen3_ok}/{qwen3_total}  |  总计: {total_ok}/{total_all}")
    print("-" * 50)

    return total_ok == total_all


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="AsmrHelper 模型下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  uv run python scripts/install_models.py                    # 下载 Whisper base + Demucs
  uv run python scripts/install_models.py --check            # 检查模型状态
  uv run python scripts/install_models.py --whisper large-v3 # 下载 Whisper large-v3
  uv run python scripts/install_models.py --qwen3            # 下载所有 Qwen3-TTS
  uv run python scripts/install_models.py --qwen3 Base       # 仅下载 Qwen3 Base
  uv run python scripts/install_models.py --all              # 下载全部模型
  uv run python scripts/install_models.py --mirror https://hf-mirror.com
""",
    )

    parser.add_argument("--check", action="store_true",
                        help="仅检查模型状态，不下载")
    parser.add_argument("--whisper", nargs="?", const="base",
                        help="下载 Whisper 模型（指定大小，默认 base）")
    parser.add_argument("--qwen3", nargs="?", const="all",
                        help="下载 Qwen3-TTS 模型（指定模型名或 all，默认 all）")
    parser.add_argument("--all", action="store_true",
                        help="下载全部模型（Whisper base + Qwen3 全部）")
    parser.add_argument("--mirror", type=str, default=None,
                        help="HuggingFace 镜像地址（如 https://hf-mirror.com）")
    parser.add_argument("--force", action="store_true",
                        help="强制重新下载已存在的模型")

    args = parser.parse_args()

    # 确保目录存在
    (project_root / "models" / "whisper").mkdir(parents=True, exist_ok=True)
    (project_root / "models" / "qwen3tts").mkdir(parents=True, exist_ok=True)

    # 仅检查模式
    if args.check:
        all_ok = check_status()
        sys.exit(0 if all_ok else 1)

    # 打印 header
    mode_desc = []
    if args.all:
        mode_desc.append("全部模型")
    if args.whisper is not None:
        mode_desc.append(f"Whisper {args.whisper}")
    if args.qwen3 is not None:
        if args.qwen3 == "all" or args.qwen3 is None:
            mode_desc.append("Qwen3 全部")
        else:
            mode_desc.append(f"Qwen3 {args.qwen3}")

    if not mode_desc:
        # 默认：下载基础模型
        args.whisper = "base"
        mode_desc.append("Whisper base（默认）")

    print_header(f"下载模型: {', '.join(mode_desc)}")

    if args.mirror:
        print_step(f"HuggingFace 镜像: {args.mirror}")
    print()

    results = []

    # --- Whisper 模型 ---
    if args.all or args.whisper is not None:
        if args.whisper is None or args.whisper == "all":
            whisper_targets = ["base"]
        else:
            whisper_targets = [args.whisper]

        for model_name in whisper_targets:
            success = download_whisper_model(model_name, args.mirror, args.force)
            results.append(("Whisper", model_name, success))

    # --- Qwen3 模型 ---
    if args.all:
        qwen3_targets = list(QWEN3_MODELS.keys())
    elif args.qwen3 is not None:
        if args.qwen3 == "all":
            qwen3_targets = list(QWEN3_MODELS.keys())
        elif args.qwen3 in QWEN3_MODELS:
            qwen3_targets = [args.qwen3]
        else:
            print_fail(f"未知的 Qwen3 模型: {args.qwen3}")
            print_warn(f"可用: {', '.join(QWEN3_MODELS.keys())}")
            qwen3_targets = []
    else:
        qwen3_targets = []

    for model_name in qwen3_targets:
        success = download_qwen3_model(model_name, args.mirror, args.force)
        results.append(("Qwen3", model_name, success))

    # --- 结果汇总 ---
    print_header("下载结果")

    success_count = 0
    fail_count = 0
    for category, name, success in results:
        if success:
            print_ok(f"  {category} {name}")
            success_count += 1
        else:
            print_fail(f"  {category} {name}")
            fail_count += 1

    print()
    if fail_count == 0:
        print(f"  全部 {success_count} 个模型下载成功!")
    else:
        print(f"  {success_count} 成功, {fail_count} 失败")

        if args.mirror is None and fail_count > 0:
            print()
            print("  提示: 如果下载失败，可以尝试使用镜像:")
            print("    uv run python scripts/install_models.py --mirror https://hf-mirror.com")
            print()

    # --- 验证最终状态 ---
    print()
    check_status()

    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
