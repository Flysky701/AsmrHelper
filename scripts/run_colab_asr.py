"""Run the ASMR Helper notebook on an existing Colab session and retrieve its SRT."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid


NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks/colab_gpu_worker.ipynb"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Destination .srt file")
    parser.add_argument("--colab", required=True, type=Path, help="Path to the Colab executable")
    parser.add_argument("--session", required=True, help="Name of the existing Colab GPU session")
    parser.add_argument("--model", choices=("tiny", "base", "small", "medium", "large-v3"), default="small")
    parser.add_argument("--language", choices=("ja", "zh", "en", "ko", "auto"), default="ja")
    args = parser.parse_args()

    audio = args.audio.resolve()
    output = args.output.resolve()
    colab = args.colab.resolve()
    if not audio.is_file() or not audio.suffix:
        parser.error("audio must be an existing file with an audio extension")
    if output.suffix.lower() != ".srt" or output.exists():
        parser.error("--output must be an unused .srt path")
    if not colab.is_file():
        parser.error("--colab must point to the installed CLI executable")

    job = f"content/asmr-asr-{uuid.uuid4().hex}"
    remote_input = f"{job}/input{audio.suffix.lower()}"

    def call(command: str, *options: str, input_code: str | None = None) -> None:
        subprocess.run(
            [str(colab), command, "-s", args.session, *options],
            input=input_code,
            text=True,
            check=True,
        )

    with tempfile.TemporaryDirectory(prefix="asmr-colab-") as temporary:
        notebook = Path(temporary) / NOTEBOOK.name
        shutil.copyfile(NOTEBOOK, notebook)
        call("exec", input_code=f"from pathlib import Path\nPath('/{job}').mkdir()\n")
        call("upload", str(audio), remote_input)
        call(
            "exec", "-f", str(notebook), "--timeout", "1200",
            "--env", f"ASMR_COLAB_JOB_DIR=/{job}",
            "--env", f"ASMR_COLAB_MODEL={args.model}",
            "--env", f"ASMR_COLAB_LANGUAGE={args.language}",
        )
        downloaded = Path(temporary) / "result.srt"
        call("download", f"{job}/result.srt", str(downloaded))
        if not downloaded.stat().st_size:
            raise RuntimeError("Colab returned an empty subtitle")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as target:
            target.write(downloaded.read_bytes())
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
