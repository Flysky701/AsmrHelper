"""Packaged desktop bootstrap: immutable resources, versioned user Python, loopback API."""
from __future__ import annotations
import argparse
import hmac
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

VERSION = "0.2.1-beta.5"

def extended_path(path: Path) -> Path:
    """Use Win32 extended paths without requiring a machine policy change."""
    text = str(path)
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        text = "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text
    return Path(text)

def prepare_runtime(bundle: Path, data: Path) -> Path:
    """Copy only the clean bundled interpreter; never migrate a developer venv."""
    bundle, data = extended_path(bundle.resolve()), extended_path(data.resolve())
    source = bundle / "python"
    identity_file = bundle / "runtime-id.txt"
    identity = identity_file.read_text(encoding="utf-8").strip()[:16] if identity_file.exists() else VERSION
    if not identity or any(c not in "0123456789abcdef.-bet" for c in identity):
        raise RuntimeError("Invalid bundled runtime identity")
    target = data / "runtimes" / ("base-" + identity)
    ready = target / ".asmr-ready"
    if ready.is_file() and (target / "python.exe").is_file():
        return target / "python.exe"
    if target.exists():
        raise RuntimeError(f"Incomplete runtime at {target}; preserve it and contact support")
    temporary = target.with_name(target.name + ".preparing-" + uuid.uuid4().hex)
    temporary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, temporary)
    dll_dir = temporary / "Library" / "bin"
    dll_dir.mkdir(parents=True, exist_ok=True)
    for dll in (bundle / "ffmpeg" / "bin").glob("*.dll"):
        shutil.copy2(dll, dll_dir / dll.name)
    (temporary / ".asmr-ready").write_text(identity, encoding="utf-8")
    temporary.rename(target)
    return target / "python.exe"

def configure_environment(bundle: Path, data: Path) -> None:
    os.environ["ASMR_HELPER_DATA_DIR"] = str(data)
    os.environ["ASMR_HELPER_STATE_DB"] = str(data / "state.sqlite3")
    os.environ["ASMR_HELPER_TOOL_DIR"] = str(bundle / "tools")
    os.environ["IMAGEIO_FFMPEG_EXE"] = str(bundle / "ffmpeg" / "bin" / "ffmpeg.exe")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONUTF8"] = "1"
    sys.path.insert(0, str(bundle / "app"))
    from src.workspace_environment import application_environment
    import tempfile
    os.environ.update(application_environment(data))
    Path(os.environ["TEMP"]).mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = None
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["PATH"] = os.pathsep.join([str(bundle / "tools"), str(bundle / "ffmpeg" / "bin"), os.environ.get("PATH", "")])
    os.environ["PYTHONPATH"] = str(bundle / "app")
    sys.path.insert(0, str(bundle / "app"))
    os.chdir(data)

def serve(bundle: Path, data: Path, port: int, token: str, *, source_root: Path | None = None) -> None:
    if source_root is None:
        configure_environment(bundle, data)
    else:
        # Local desktop mode reuses the project's interpreter, models and config.
        # It must never prepare/copy an installation runtime or relocate caches.
        os.environ["ASMR_HELPER_DATA_DIR"] = str(source_root)
        os.environ["ASMR_HELPER_STATE_DB"] = str(source_root / "state.sqlite3")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        sys.path.insert(0, str(source_root))
        os.chdir(source_root)
    from src.api.http.logging_config import configure_backend_logging
    configure_backend_logging(data / "logs")
    import uvicorn
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from src.api.http.app import create_app
    app = create_app()
    app.version = VERSION
    # Captured at process startup; never pretend an old process loaded later edits.
    build_identity = {key: os.environ.get("ASMR_HELPER_BUILD_" + suffix) for key, suffix in
                      (("sha256", "SHA256"), ("source_fingerprint", "SOURCE"), ("built_at_utc", "TIME"), ("executable", "EXE"))}
    @app.middleware("http")
    async def authorize(request: Request, call_next):
        # OPTIONS carries no user operation; CORS still validates the origin.
        if request.method != "OPTIONS":
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            supplied = supplied or request.query_params.get("_desktop_token", "")
            if not supplied or not hmac.compare_digest(supplied, token):
                return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "Desktop session required"}}, status_code=401)
        return await call_next(request)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_config=None)
    server = uvicorn.Server(config)
    @app.get("/__desktop/health")
    def desktop_health():
        return {"status": "ok", "version": VERSION,
                "source_root": str(source_root) if source_root else None,
                "workspace": str(data), "python": sys.executable, "pid": os.getpid(), "build": build_identity}
    @app.get("/__desktop/workspace-switch-ready")
    def workspace_switch_ready():
        from src.app.services.task_service import get_task_service
        return {"ready": get_task_service().workspace_switch_ready()}
    @app.post("/__desktop/workspace-switch-ready")
    def prepare_workspace_switch():
        from src.app.services.task_service import get_task_service
        return {"ready": get_task_service().prepare_workspace_switch()}
    @app.post("/__desktop/shutdown")
    def shutdown():
        server.should_exit = True
        return {"status": "stopping"}
    server.run()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    if args.source_root is not None:
        root = args.source_root.resolve(strict=True)
        if root != Path(__file__).resolve().parents[1] or not (root / "src/api/http/app.py").is_file():
            raise RuntimeError("Local desktop must use this script's project source")
        token = os.environ.get("ASMR_HELPER_DESKTOP_TOKEN", "")
        if len(token) < 32:
            raise RuntimeError("A per-launch desktop token is required")
        if os.environ.get("ASMR_HELPER_START_GATE") == "1" and sys.stdin.readline().strip() != "start":
            raise RuntimeError("Desktop process did not authorize startup")
        serve(root, root, args.port, token, source_root=root)
        return 0
    bundle = extended_path(Path(__file__).resolve().parent.parent)
    data = extended_path(args.data_dir.resolve())
    if data == bundle or bundle in data.parents:
        raise RuntimeError("Workspace must be outside the bundled backend resources")
    data.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("ASMR_HELPER_DESKTOP_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("A per-launch desktop token is required")
    if args.serve:
        serve(bundle, data, args.port, token)
        return 0
    if os.environ.get("ASMR_HELPER_START_GATE") == "1" and sys.stdin.readline().strip() != "start":
        raise RuntimeError("Desktop process did not authorize startup")
    configure_environment(bundle, data)
    python = prepare_runtime(bundle, data)
    return subprocess.call([str(python), "-I", "-B", str(Path(__file__).resolve()), "--serve", "--data-dir", str(data), "--port", str(args.port)])

if __name__ == "__main__":
    raise SystemExit(main())
