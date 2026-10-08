"""Open the current main-project desktop build; refresh stale sources offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
EXE = DESKTOP / "src-tauri/target/release/asmr-helper-local.exe"
STAGED_EXE = EXE.with_name("asmr-helper-local-next.exe")
FINGERPRINT_VERSION = 1


def source_fingerprint() -> str:
    """Hash executable inputs, never user configuration, models, caches or Git."""
    files = set()
    for relative in ("src", "desktop/src", "desktop/public", "desktop/src-tauri/src",
                     "desktop/src-tauri/capabilities", "desktop/src-tauri/icons",
                     ".cargo", "desktop/.cargo", "desktop/src-tauri/.cargo"):
        directory = ROOT / relative
        if directory.is_dir():
            files.update(path for path in directory.rglob("*") if path.is_file()
                         and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"})
    for relative in ("scripts/desktop_local.py", "scripts/desktop_backend.py", "RUNGUI.bat", "GUIRun.bat", "run.bat",
                     "pyproject.toml", "uv.lock", "config/models.yaml", "desktop/index.html", "desktop/package.json", "desktop/package-lock.json",
                     "desktop/tsconfig.json", "desktop/tsconfig.node.json", "desktop/vite.config.ts",
                     "desktop/postcss.config.js", "desktop/tailwind.config.js", "desktop/src-tauri/build.rs",
                     "desktop/src-tauri/Cargo.toml", "desktop/src-tauri/Cargo.lock", "desktop/src-tauri/tauri.conf.json"):
        path = ROOT / relative
        if path.is_file():
            files.add(path)
    digest = hashlib.sha256(f"desktop-source-v{FINGERPRINT_VERSION}\0".encode())
    for path in sorted(files):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def build_receipt(executable: Path, fingerprint: str | None = None):
    try:
        receipt = json.loads(executable.with_suffix(".build.json").read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or hashlib.sha256(executable.read_bytes()).hexdigest() != receipt.get("sha256"):
            return None
        if fingerprint is not None and (receipt.get("fingerprint_version") != FINGERPRINT_VERSION
                                        or receipt.get("source_fingerprint") != fingerprint
                                        or not isinstance(receipt.get("built_at_utc"), str)):
            return None
        return receipt
    except (OSError, ValueError, TypeError):
        return None


def output_locked(executable: Path) -> bool:
    if not executable.exists():
        return False
    try:
        with executable.open("r+b"):
            return False
    except PermissionError:
        return True


def build_target(staged: bool = False) -> Path:
    choices = (STAGED_EXE, EXE) if staged else (EXE, STAGED_EXE)
    for executable in choices:
        if not output_locked(executable):
            return executable
    raise RuntimeError("Both desktop outputs are running or locked; no process was stopped. Finish tasks and close one window, then retry.")


@contextmanager
def launcher_lock():
    """Serialize check/build/launch across double clicks; OS releases on crash."""
    path = ROOT / ".cache/desktop-launch.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        import msvcrt
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Another desktop launch/build is in progress; please wait. No second build or window was started.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def ensure_current_build() -> Path:
    fingerprint = source_fingerprint()
    candidates = [path for path in (EXE, STAGED_EXE) if build_receipt(path, fingerprint)]
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime_ns)
    print("[UPDATE] Source/build fingerprint changed; incrementally building offline. Nothing will be installed.", flush=True)
    executable = build()
    if not build_receipt(executable, source_fingerprint()):
        raise RuntimeError("Built output does not match current sources. Launch cancelled; no stale build was opened.")
    return executable


def verified_staged_build() -> bool:
    return build_receipt(STAGED_EXE) is not None


def build(*, staged: bool = False) -> Path:
    output = build_target(staged)
    fingerprint = source_fingerprint()
    node = ROOT / ".runtimes/node-v24.19.0-win-x64/node.exe"
    cargo = ROOT / ".runtimes/cargo/bin/cargo.exe"
    mingw = next((ROOT / ".runtimes").glob("llvm-mingw-*/bin/gcc.exe"), None)
    required = [node, cargo, DESKTOP / "node_modules/vite/bin/vite.js",
                DESKTOP / "node_modules/typescript/bin/tsc"]
    missing = [str(p) for p in required if not p.is_file()]
    if mingw is None:
        missing.append("project LLVM MinGW")
    if missing:
        raise RuntimeError("Missing build tools; nothing installed: " + ", ".join(missing))
    env = os.environ.copy()
    env.update(CARGO_HOME=str(ROOT / ".runtimes/cargo"),
               RUSTUP_HOME=str(ROOT / ".runtimes/rustup"),
               RUSTUP_TOOLCHAIN="stable-x86_64-pc-windows-gnu",
               RUSTUP_AUTO_INSTALL="0", CARGO_NET_OFFLINE="true",
               CARGO_TARGET_DIR=str(DESKTOP / "src-tauri/target"),
               TAURI_CONFIG=json.dumps({"productName": "ASMR Helper", "identifier": "com.asmrhelper.desktop.local",
                                        "bundle": {"active": False, "resources": None}}))
    env["PATH"] = os.pathsep.join([str(node.parent), str(cargo.parent), str(mingw.parent), env.get("PATH", "")])
    for command, cwd in [
        ([str(node), str(DESKTOP / "node_modules/typescript/bin/tsc"), "-b"], DESKTOP),
        ([str(node), str(DESKTOP / "node_modules/vite/bin/vite.js"), "build"], DESKTOP),
        ([str(cargo), "build", "--release", "--offline", "--locked", "--bin", output.stem,
          "--features", "tauri/custom-protocol"], DESKTOP / "src-tauri"),
    ]:
        subprocess.run(command, cwd=cwd, env=env, check=True)
    if source_fingerprint() != fingerprint:
        raise RuntimeError("Sources changed during the build. No current-build receipt was published; retry when editing is finished.")
    receipt = {
        "executable": str(output),
        "fingerprint_version": FINGERPRINT_VERSION,
        "source_fingerprint": fingerprint,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "frontend": {str(path.relative_to(DESKTOP / "dist")): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted((DESKTOP / "dist").rglob("*")) if path.is_file()},
    }
    destination = output.with_suffix(".build.json")
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true", help="Incrementally build the frontend and native shell, then open")
    mode.add_argument("--build-only", action="store_true")
    mode.add_argument("--build-staged", action="store_true", help="Build a separate offline executable for the next launch; keep the current window running")
    mode.add_argument("--check", action="store_true", help="Show source/build identity without building or opening a window")
    args = parser.parse_args()
    if args.check:
        fingerprint = source_fingerprint()
        print(json.dumps({"source_root": str(ROOT), "source_fingerprint": fingerprint,
                          "builds": [{"path": str(path), "current": bool(build_receipt(path, fingerprint)),
                                      "locked": output_locked(path), "receipt": build_receipt(path)}
                                     for path in (EXE, STAGED_EXE)]}, ensure_ascii=False, indent=2))
        return
    with launcher_lock():
        launch(args)


def launch(args) -> None:
    if args.build or args.build_only or args.build_staged:
        build(staged=args.build_staged)
    if args.build_only or args.build_staged:
        return
    executable = ensure_current_build()
    receipt = build_receipt(executable, source_fingerprint())
    if receipt is None:
        raise RuntimeError("Sources changed before launch; no stale build was opened. Retry after editing is finished.")
    print(f"[BUILD] {executable.name} sha256={receipt['sha256']} built={receipt.get('built_at_utc', 'unknown')}", flush=True)
    if any(output_locked(path) for path in (EXE, STAGED_EXE)):
        print("[READY] Current build is ready. Existing desktop window/tasks were preserved; finish them, close the old window normally, then reopen RUNGUI.bat. No duplicate window was started.")
        return
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("ASMR_HELPER_") and key not in {"ASMR_HELPER_COMPUTE", "ASMR_HELPER_CUDA_LIBRARY_DIR"}:
            env.pop(key)
    env.update(ASMR_HELPER_SOURCE_ROOT=str(ROOT), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    env.update(ASMR_HELPER_BUILD_SHA256=receipt["sha256"], ASMR_HELPER_BUILD_SOURCE=receipt["source_fingerprint"],
               ASMR_HELPER_BUILD_TIME=receipt["built_at_utc"], ASMR_HELPER_BUILD_EXE=str(executable))
    process = subprocess.Popen([str(executable)], cwd=ROOT, env=env)
    # Keep the launcher lock until Windows has mapped the executable. Otherwise a
    # rapid second click can pass the file-lock check before the first app starts.
    deadline = time.monotonic() + 10
    while not output_locked(executable):
        if process.poll() is not None:
            raise RuntimeError(f"Desktop exited during startup (code {process.returncode}).")
        if time.monotonic() >= deadline:
            raise RuntimeError("Desktop startup could not be confirmed; check the existing window before retrying.")
        time.sleep(0.05)
    print(f"Opened {executable.name}. Python changes apply on the next launch.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from None
