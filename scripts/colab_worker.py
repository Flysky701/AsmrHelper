"""Package and start the current ASMR Helper Worker on an existing Colab runtime."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PORTS = {"pipeline": 8765, "qwen3": 8766, "voxcpm2": 8767}
EXTRAS = {"pipeline": "audio,qwen_asr", "qwen3": "qwen3", "voxcpm2": "voxcpm2"}
MODELS = {
    "pipeline": ("demucs-htdemucs", "faster-whisper-base", "qwen3-forced-aligner-0.6b"),
    "qwen3": ("qwen3-custom-voice", "qwen3-base", "qwen3-voice-design"),
    "voxcpm2": ("voxcpm2",),
}
CUDA_126 = "https://download.pytorch.org/whl/cu126"
SEED_REPO = "https://github.com/Plachtaa/seed-vc.git"
SEED_REV = "51383efd921027683c89e5348211d93ff12ac2a8"


def run(*args: str | Path, **kwargs) -> None:
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT, **kwargs)


def bundle(output: Path) -> None:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
         "src", "packages/gpu_worker", "packages/protocol"], cwd=ROOT,
    ).decode("utf-8").split("\0")
    files = {path for path in paths if path.endswith(".py")}
    files.update({
        "pyproject.toml", "README.md", "LICENSE", "THIRD-PARTY-NOTICES.md",
        "config/models.yaml", "scripts/colab_worker.py",
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", ZIP_DEFLATED) as archive:
        for name in sorted(files):
            path = ROOT / name
            if path.is_file() and path.resolve().is_relative_to(ROOT):
                archive.write(path, name)


def venv(state: Path, profile: str, version: str) -> Path:
    directory = state / "envs" / profile
    python = directory / "bin" / "python"
    if not python.is_file():
        run("uv", "venv", "--python", version, directory)
    return python


def prepare_seed_vc(state: Path) -> None:
    root = state / "seed-vc"
    if not root.exists():
        run("git", "clone", "--no-checkout", SEED_REPO, root)
    run("git", "-C", root, "checkout", "--detach", SEED_REV)
    python = venv(state, "seed-vc", "3.10")
    run("uv", "pip", "install", "--python", python,
        "torch==2.4.0", "torchaudio==2.4.0", "torchvision==0.19.0",
        "--index-url", "https://download.pytorch.org/whl/cu121")
    # The upstream file opens with alternate nightly commands and includes UI packages.
    skipped = {"torch", "torchvision", "torchaudio", "gradio", "freesimplegui", "sounddevice"}
    requirements = state / "seed-vc-requirements.txt"
    lines = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    requirements.write_text("\n".join(
        line for line in lines
        if line.strip() and line.split("==", 1)[0].split()[0].lower() not in skipped
    ) + "\n", encoding="utf-8")
    run("uv", "pip", "install", "--python", python, "-r", requirements)


def runtime_env(state: Path, python: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ASMR_HELPER_DATA_DIR", None)
    env.setdefault("ASMR_HELPER_MODEL_ROOT", str(state / "models"))
    env.setdefault("HF_HOME", str(state / "hf"))
    env.setdefault("TORCH_HOME", str(state / "torch"))
    env["ASMR_HELPER_COMPUTE"] = "cuda"
    # CTranslate2 resolves the CUDA 12/cuDNN 9 libraries by their shared names.
    libs = sorted(python.parent.parent.glob("lib/python*/site-packages/nvidia/*/lib"))
    if env.get("LD_LIBRARY_PATH"):
        libs.append(env["LD_LIBRARY_PATH"])
    env["LD_LIBRARY_PATH"] = os.pathsep.join(map(str, libs))
    if (state / "seed-vc" / "inference.py").is_file():
        env.setdefault("ASMR_SEED_VC_ROOT", str(state / "seed-vc"))
        env.setdefault("ASMR_SEED_VC_PYTHON", str(state / "envs/seed-vc/bin/python"))
    return env


def prepare(state: Path, profile: str, *, models: list[str], roformer: bool, seed_vc: bool) -> None:
    if shutil.which("uv") is None:
        raise SystemExit("Install uv in Colab first: python -m pip install uv")
    python = venv(state, profile, "3.11")
    run("uv", "pip", "install", "--python", python,
        "torch==2.10.0", "torchaudio==2.10.0", "torchvision==0.25.0", "--index-url", CUDA_126)
    dependencies = [
        f".[{EXTRAS[profile]}]", "numpy>=2,<2.5", "torchcodec>=0.10,<0.11",
        "ctranslate2==4.8.1",  # Match the notebook's CUDA 12 + cuDNN 9 build.
    ]
    if profile != "pipeline":
        dependencies.append("faster-whisper>=1.0")  # TTS transcript verification
    if roformer:
        dependencies.extend(["audio-separator[gpu]==0.41.1", "onnxruntime-gpu>=1.20,<1.24"])
    run("uv", "pip", "install", "--python", python, *dependencies)
    if seed_vc:
        prepare_seed_vc(state)
    run(python, "-c", """
import sys
from src.core.resources.model_catalog import ModelCatalog
from src.core.resources.model_installer import ModelInstaller

catalog = ModelCatalog()
installer = ModelInstaller()
for model_id in sys.argv[1:]:
    entry = catalog.get(model_id)
    if not installer.install_local_model(entry, mirror='huggingface'):
        raise RuntimeError(f'Incomplete model: {model_id}')
""", *models, env=runtime_env(state, python))


def serve(state: Path, profile: str) -> None:
    python = state / "envs" / profile / "bin" / "python"
    if not python.is_file():
        raise SystemExit(f"Run prepare --profile {profile} first.")
    env = runtime_env(state, python)
    if not env.get("ASMR_WORKER_TOKEN", "").strip():
        raise SystemExit("Set ASMR_WORKER_TOKEN before starting the Worker.")
    run(python, "-c", "import torch; assert torch.cuda.is_available(), 'CUDA GPU is unavailable'", env=env)
    os.chdir(ROOT)
    os.execve(python, [str(python), "-m", "packages.gpu_worker.cli", "--serve", "--port",
                       str(PORTS[profile]), "--max-heavy-models", "1"], env)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bundle").add_argument("output", type=Path)
    for name in ("prepare", "serve"):
        command = commands.add_parser(name)
        command.add_argument("--profile", choices=PORTS, default="pipeline")
        command.add_argument("--state", type=Path, default=ROOT / ".colab")
        if name == "prepare":
            command.add_argument("--roformer", action="store_true")
            command.add_argument("--seed-vc", action="store_true")
            command.add_argument("--model", action="append", help="TTS model ID to prepare with this profile")
    args = parser.parse_args()
    if args.command == "bundle":
        bundle(args.output)
        return
    if sys.platform != "linux":
        parser.error("Run prepare and serve inside the Colab Linux runtime.")
    if args.command == "prepare":
        if args.roformer and args.profile != "pipeline":
            parser.error("--roformer is available in the pipeline profile")
        models = MODELS[args.profile]
        if args.model and (args.profile == "pipeline" or any(model not in models for model in args.model)):
            parser.error("--model must be a TTS model ID for the selected profile")
        selected = list(models if args.profile == "pipeline" else (args.model or models[:1]))
        if args.profile != "pipeline":
            selected.append("faster-whisper-small")
        prepare(args.state.resolve(), args.profile, models=selected, roformer=args.roformer, seed_vc=args.seed_vc)
    else:
        serve(args.state.resolve(), args.profile)


if __name__ == "__main__":
    main()
