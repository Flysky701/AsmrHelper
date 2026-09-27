"""Plan, apply or verify the project's CPU/CUDA installation policy."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.runtime.profiles import RuntimeProfileResolver  # noqa: E402

PROFILES = ("main", "qwen_asr", "fun_asr", "qwen_tts", "voxcpm2")


def has_torch(python: Path) -> bool:
    result = subprocess.run(
        [str(python), "-c", "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('torch') else 1)"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Cannot inspect {python}: {result.stderr.strip()}")
    return result.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compute", choices=("auto", "cpu", "cuda"), help="Override saved mode for this invocation; --apply also saves it")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="Install and verify selected wheels; never downloads models")
    action.add_argument("--check", action="store_true", help="Verify installed builds with real tensor operations; no installation")
    parser.add_argument("--existing", action="store_true", help="Include existing isolated model environments (never create them)")
    parser.add_argument("--require-main", action="store_true", help="Include main environment even if torch is not yet installed")
    parser.add_argument("--offline", action="store_true", help="Only use locally cached wheels")
    args = parser.parse_args(argv)
    old_mode = os.environ.get("ASMR_HELPER_COMPUTE")
    try:
        if args.compute:
            os.environ["ASMR_HELPER_COMPUTE"] = args.compute
        resolver = RuntimeProfileResolver(PROJECT_ROOT)
        target = resolver.resolve_compute_target()
        print(f"Compute mode: {resolver.compute_mode()} -> {target}")
        profiles = []
        for name in PROFILES if args.existing else ("main",):
            profile = resolver.resolve(name)
            if not profile.python_executable.is_file():
                print(f"[SKIP] {name}: environment not installed")
                continue
            if name == "main" and not args.require_main and not has_torch(profile.python_executable):
                print("[SKIP] main: no local audio dependencies; startup-only install")
                continue
            profiles.append(profile)
        if args.apply and args.compute:
            resolver.save_compute_mode(args.compute)
        failures = []
        for profile in profiles:
            print(f"[{profile.id}] {profile.python_executable}")
            try:
                if not args.check:
                    commands = resolver.build_bootstrap_commands(profile)
                    for command in commands:
                        if args.offline:
                            command = [*command, "--offline"]
                        print(subprocess.list2cmdline(command))
                        if args.apply:
                            subprocess.run(command, cwd=PROJECT_ROOT, env=resolver.subprocess_env(), check=True)
                if args.apply or args.check:
                    print(json.dumps(resolver.verify_compute(profile), ensure_ascii=False))
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                failures.append(profile.id)
                print(f"[FAIL] {profile.id}: {exc}", file=sys.stderr)
        if failures:
            print("Incomplete: " + ", ".join(failures) + ". No automatic CPU fallback was applied.", file=sys.stderr)
            return 1
        print("Verification complete." if args.apply or args.check else "Plan only; no files or packages changed. Add --apply to install.")
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    finally:
        if old_mode is None:
            os.environ.pop("ASMR_HELPER_COMPUTE", None)
        else:
            os.environ["ASMR_HELPER_COMPUTE"] = old_mode


if __name__ == "__main__":
    raise SystemExit(main())
