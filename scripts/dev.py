"""Run source API and Vite without installing dependencies or building a desktop app."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_ROOT = ROOT


class WindowsJob:
    """Windows closes this handle on console exit, also stopping all descendants."""

    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("per_process", ctypes.c_int64), ("per_job", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("minimum", ctypes.c_size_t),
                        ("maximum", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Limits(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", Counters), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, child):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, int(child._handle)):
            child.kill()
            child.wait()
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def tools(python: str | None):
    interpreter = Path(python).resolve() if python else ROOT / ".venv/Scripts/python.exe"
    homes = ([Path(os.environ["ASMR_HELPER_NODE_HOME"])] if os.environ.get("ASMR_HELPER_NODE_HOME")
             else sorted((LAUNCHER_ROOT / ".runtimes").glob("node-*-win-x64"), reverse=True))
    node = next((p / "node.exe" for p in homes if (p / "node.exe").is_file()), None)
    node = node or (Path(shutil.which("node")) if shutil.which("node") else None)
    vite = ROOT / "desktop/node_modules/vite/bin/vite.js"
    missing = [str(p) for p in (interpreter, node, vite) if p is None or not p.is_file()]
    if missing:
        raise RuntimeError("Missing development dependencies (nothing installed): " + ", ".join(missing))
    probe = subprocess.run([str(interpreter), "-B", "-c",
                            "import fastapi,uvicorn,httpx,yaml; import sys; print(sys.version.split()[0])"],
                           capture_output=True, text=True, timeout=30)
    if probe.returncode:
        raise RuntimeError("API Python dependencies unavailable: " + probe.stderr[-1000:])
    return interpreter, node, vite


def ensure_port_free(port):
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            if getattr(exc, "winerror", None) == 10013 or exc.errno == 13:
                raise RuntimeError(f"Permission to bind local port {port} was denied: {exc}") from exc
            raise RuntimeError(f"Cannot bind port {port}: {exc}. Close its owner or select another API port; no process was stopped.") from exc


def get(url):
    # A loopback health check must not inherit a system HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return response.read()


def api_port(requested):
    if requested is not None:
        ensure_port_free(requested)
        return requested
    try:
        ensure_port_free(8000)
        return 8000
    except RuntimeError:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            selected = sock.getsockname()[1]
        print(f"Port 8000 unavailable; this session will use API port {selected}. Existing services are unchanged.", flush=True)
        return selected


def wait_ready(child, url, predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"Process exited ({child.returncode}) before {url} became ready; inspect logs/dev.")
        try:
            if predicate(get(url)):
                return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Startup timed out at {url}; inspect logs/dev.")


def source_signature():
    files = []
    for path in (ROOT / 'src').rglob('*.py'):
        try:
            files.append((str(path), path.stat().st_mtime_ns))
        except FileNotFoundError:
            continue
    return tuple(sorted(files))


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="Source worktree to run; defaults to this project")
    parser.add_argument("--runtime-sources", type=Path, help="Explicit read-only borrowed runtime mapping")
    parser.add_argument("--python", help="Explicit API interpreter; defaults to the project .venv")
    parser.add_argument("--port", type=int, help="Fixed API port; default: 8000 or an available port")
    parser.add_argument("--check", action="store_true", help="Check dependencies and ports without starting services")
    parser.add_argument("--smoke", action="store_true", help="Start, verify HTTP identity and frontend, then stop")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if args.project:
        ROOT = args.project.resolve(strict=True)
        if not (ROOT / 'src/api/http/app.py').is_file():
            parser.error('Project does not contain the source API')
    if args.runtime_sources and not args.runtime_sources.is_file():
        parser.error('Runtime mapping does not exist')
    if args.port is not None and (not 1024 <= args.port <= 65535 or args.port == 5173):
        parser.error("API port must be 1024..65535 and different from Vite port 5173")
    interpreter, node, vite = tools(args.python)
    args.port = api_port(args.port)
    ensure_port_free(5173)
    git = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %d %s"], capture_output=True, text=True)
    print(f"Source: {ROOT}\nRevision: {git.stdout.strip()}\nPython: {interpreter}\nNode: {node}", flush=True)
    if args.check:
        print("Development prerequisites ready; no services started.")
        return 0
    session = uuid.uuid4().hex
    env = os.environ.copy()
    # Use this source workspace; do not inherit an installed/trial application's state.
    for key in list(env):
        if key.startswith("ASMR_HELPER_") and key not in {"ASMR_HELPER_NODE_HOME", "ASMR_HELPER_COMPUTE", "ASMR_HELPER_CUDA_LIBRARY_DIR"}:
            env.pop(key)
    env.update(ASMR_HELPER_DATA_DIR=str(ROOT), ASMR_HELPER_DEV_SESSION=session,
               PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               VITE_API_BASE=f"http://127.0.0.1:{args.port}/api/v1",
               PATH=str(node.parent) + os.pathsep + env.get("PATH", ""))
    if args.runtime_sources:
        env['ASMR_HELPER_RUNTIME_SOURCES'] = str(args.runtime_sources.resolve())
    logs = ROOT / "logs/dev"
    logs.mkdir(parents=True, exist_ok=True)
    children, streams = [], []
    job = WindowsJob()
    api_job = WindowsJob()
    try:
        def launch(command, cwd, name, owner):
            log = (logs / name).open("w", encoding="utf-8")
            streams.append(log)
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            children.append(child)
            owner.add(child)
            return child

        api_command = [str(interpreter), "-B", "-m", "src.api.http", "--host", "127.0.0.1",
                       "--port", str(args.port), "--log-dir", str(logs)]
        api = launch(api_command, ROOT, "api-console.log", api_job)
        identity = f"http://127.0.0.1:{args.port}/__dev/identity"
        wait_ready(api, identity, lambda data: json.loads(data).get("session") == session)
        frontend = launch([str(node), str(vite), "--host", "127.0.0.1"], ROOT / "desktop", "vite.log", job)
        url = "http://127.0.0.1:5173"
        wait_ready(frontend, url, lambda data: b"/src/main.tsx" in data)
        print(f"Ready: {url}\nAPI identity: {identity}\nLogs: {logs}\nPress Ctrl+C to stop this development session.", flush=True)
        if args.smoke:
            print("Smoke passed: matching source API and Vite entry.", flush=True)
            return 0
        if not args.no_open:
            webbrowser.open(url)
        previous = source_signature()
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
            current = source_signature()
            if current != previous:
                # Uvicorn's Windows reload uses console Ctrl+C events, which hang
                # in a hidden console. Restart only our API job instead.
                print("Python source changed; restarting this session's API...", flush=True)
                api_job.close()
                if api.poll() is None:
                    api.terminate()
                api.wait(timeout=15)
                children.remove(api)
                api_job = WindowsJob()
                api = launch(api_command, ROOT, "api-console.log", api_job)
                wait_ready(api, identity, lambda data: json.loads(data).get("session") == session)
                previous = current
                print("API reloaded.", flush=True)
        raise RuntimeError("A development process exited; inspect logs/dev.")
    finally:
        api_job.close()
        job.close()
        for child in children:
            if child.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
                else:
                    child.terminate()
            child.wait(timeout=15)
        for stream in streams:
            stream.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Development session stopped.")
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1) from None
