"""Build a clean, relocatable backend resource tree (never copies a developer venv)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

VERSION = "0.2.1-beta.5"
ROOT = Path(__file__).resolve().parents[1]
PUBLIC_CONFIG = ("models.yaml", "presets.yaml", "asmr_terms.json", "config.example.json", "voice_profiles.example.json")
EXCLUDED = ["developer venv/runtime", "config.json", "voice_profiles.json", "voice_lab", "models", "output", "logs", "databases", ".git", ".env", "__pycache__", "imageio_ffmpeg bundled executable", "ffplay"]


def run(args: list[str], **kwargs):
    print("Running", Path(args[0]).name, args[1], flush=True)
    subprocess.run(args, check=True, **kwargs)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def copy_file(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python-source", "ffmpeg-source", "uv", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    python_source = args.python_source.resolve()
    ffmpeg_source = args.ffmpeg_source.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Refusing non-empty output directory; choose a fresh staging directory")
    if output == ROOT or output in ROOT.parents or output == python_source or python_source in output.parents:
        raise SystemExit("Unsafe output directory")
    if not (python_source / "python.exe").is_file() or (python_source / "pyvenv.cfg").exists():
        raise SystemExit("python-source must be a complete clean CPython distribution, not a venv")
    site = python_source / "Lib" / "site-packages"
    unexpected = [p.name for p in site.iterdir() if p.name != "README.txt" and not p.name.startswith(("pip", "__pycache__"))] if site.exists() else []
    if unexpected:
        raise SystemExit("Python source contains unexpected installed packages")
    launcher = ROOT / "scripts" / "desktop_backend.py"
    if not launcher.is_file():
        raise SystemExit("scripts/desktop_backend.py must exist before staging")
    for name in PUBLIC_CONFIG:
        subprocess.run(["git", "ls-files", "--error-unmatch", "config/" + name], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(python_source, output / "python", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    # This private copy is application-managed; leave the uv source distribution untouched.
    (output / "python" / "Lib" / "EXTERNALLY-MANAGED").unlink(missing_ok=True)
    app = output / "app"
    tracked = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "src"], cwd=ROOT).decode("utf-8").split("\0")
    for name in tracked:
        if name.endswith(".py"):
            copy_file(ROOT / name, app / name)
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        copy_file(ROOT / name, app / name)
    copy_file(launcher, app / "desktop_backend.py")
    for name in PUBLIC_CONFIG:
        source = ROOT / "config" / name
        text = source.read_text(encoding="utf-8")
        if re.search(r"(?i)(sk-[a-z0-9]{16,}|ghp_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|[a-z]:[\\/](?:Users|Projects|WorkSpace)[\\/])", text):
            raise SystemExit("Public config audit failed: " + name)
        if name == "config.example.json":
            data = json.loads(text)
            if any(v for k, v in data.get("api", {}).items() if k.endswith("_api_key")):
                raise SystemExit("Example API credentials must be empty")
        copy_file(source, app / "config" / name)
    copy_file(args.uv, output / "tools" / "uv.exe")
    for source in (ffmpeg_source / "bin").iterdir():
        if source.suffix.lower() == ".dll" or source.name.lower() in {"ffmpeg.exe", "ffprobe.exe"}:
            copy_file(source, output / "ffmpeg" / "bin" / source.name)
    for name in ("LICENSE", "README.txt"):
        copy_file(ffmpeg_source / name, output / "ffmpeg" / name)
    licenses = output / "licenses"
    licenses.mkdir()
    copy_file(python_source / "LICENSE.txt", licenses / "python-LICENSE.txt")
    requirements = licenses / "base-requirements.txt"
    uv = str(args.uv.resolve())
    uv_version = subprocess.check_output([uv, "--version"], text=True).split()[1]
    if not re.fullmatch(r"\d+\.\d+\.\d+", uv_version):
        raise SystemExit("Unsupported uv version for official license lookup")
    for name in ("LICENSE-MIT", "LICENSE-APACHE"):
        url = f"https://raw.githubusercontent.com/astral-sh/uv/{uv_version}/{name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = response.read()
        (licenses / ("uv-" + name)).write_bytes(payload)
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", UV_NO_CONFIG="1", UV_CACHE_DIR=str(Path(tempfile.gettempdir()) / "asmrhelper-bundle-uv-cache"), UV_PYTHON=str(output / "python" / "python.exe"), UV_PYTHON_DOWNLOADS="never")
    run([uv, "export", "--project", str(app), "--locked", "--no-dev", "--no-editable", "--no-emit-project", "--no-header", "--output-file", str(requirements)], cwd=app, env=env, stdout=subprocess.DEVNULL)
    run([uv, "pip", "install", "--python", str(output / "python" / "python.exe"), "--index-url", "https://pypi.org/simple", "--require-hashes", "-r", str(requirements)], env=env)
    installed_site = output / "python" / "Lib" / "site-packages"
    for exe in (installed_site / "imageio_ffmpeg" / "binaries").glob("*.exe"):
        exe.unlink()
    records = []
    for info in sorted(installed_site.glob("*.dist-info")):
        metadata = info / "METADATA"
        if metadata.exists():
            content = metadata.read_text(encoding="utf-8", errors="replace")
            fields = {}
            for line in content.splitlines():
                for key in ("Name", "Version", "License", "License-Expression", "Home-page"):
                    if line.startswith(key + ": ") and key not in fields:
                        fields[key] = line[len(key) + 2:]
            records.append(fields)
        for source in info.rglob("*"):
            if source.is_file() and ("license" in str(source.relative_to(info)).lower() or "notice" in source.name.lower() or source.name == "METADATA"):
                copy_file(source, licenses / "python-packages" / info.name / source.relative_to(info))
    # Keep native notices alongside binaries, and index them in the central license directory.
    for source in installed_site.rglob("*"):
        if source.is_file() and (source.name.lower().startswith(("license", "copying", "notice"))) and not any(p.endswith(".dist-info") for p in source.parts):
            copy_file(source, licenses / "native" / source.relative_to(installed_site))
    (licenses / "packages.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    if any(r.get("Name", "").lower() in {"torch", "torchaudio", "transformers", "demucs", "faster-whisper", "qwen-tts", "qwen-asr", "voxcpm"} for r in records):
        raise SystemExit("Unexpected model/audio dependency in base bundle")
    from collect_windows_notices import collect
    collect(ROOT, licenses)
    # Generated console launchers embed staging paths; runtime uses python -m instead.
    scripts_dir = output / "python" / "Scripts"
    if scripts_dir.is_dir():
        for entry in scripts_dir.iterdir():
            if entry.is_file(): entry.unlink()
    identity = hashlib.sha256(requirements.read_bytes() + launcher.read_bytes() + (python_source / "python.exe").read_bytes()).hexdigest()
    (output / "runtime-id.txt").write_text(identity, encoding="utf-8")
    files = [{"path": p.relative_to(output).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(output.rglob("*")) if p.is_file()]
    manifest = {"version": VERSION, "uv_version": uv_version, "python_source_sha256": digest(python_source / "python.exe"), "excluded": EXCLUDED, "packages": records, "files": files}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "files": len(files), "bytes": sum(f["bytes"] for f in files), "version": VERSION}), flush=True)


if __name__ == "__main__":
    main()
