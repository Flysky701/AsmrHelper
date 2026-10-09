"""Export the approved character art to desktop and NSIS asset formats.

Requires existing Pillow and desktop's Tauri CLI. Does not build or install the app.
"""

import base64
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "desktop/branding/character"
DEST = ROOT / "desktop/src-tauri/icons/character"
PUBLIC = ROOT / "desktop/public/brand"
CLI = ROOT / "desktop/node_modules/@tauri-apps/cli/tauri.js"
ET.register_namespace("", "http://www.w3.org/2000/svg")


def render(template: str, width: int, height: int) -> Image.Image:
    side = max(width, height)
    svg = ET.fromstring(template)
    svg.set("width", str(side * 4))
    svg.set("height", str(side * 4))
    svg.set("viewBox", f"0 0 {side} {side}")
    with tempfile.TemporaryDirectory(prefix="asmr-character-") as temporary:
        folder = Path(temporary)
        path = folder / "source.svg"
        ET.ElementTree(svg).write(path, encoding="utf-8", xml_declaration=True)
        subprocess.run([
            shutil.which("node") or "node", str(CLI), "icon", str(path),
            "--output", str(folder), "--png", str(side * 4),
        ], check=True)
        with Image.open(folder / f"{side * 4}x{side * 4}.png") as result:
            return result.convert("RGBA").resize(
                (side, side), Image.Resampling.LANCZOS,
            ).crop((0, 0, width, height))


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE / "icon-source.png") as source:
        icon = source.convert("RGBA")
    icon.resize((512, 512), Image.Resampling.LANCZOS).save(DEST / "icon.png")
    icon.save(DEST / "icon.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    icon.resize((128, 128), Image.Resampling.LANCZOS).save(PUBLIC / "app-icon.png")
    icon.save(PUBLIC / "favicon.ico", sizes=[(s, s) for s in (16, 32, 48)])
    art = "data:image/png;base64," + base64.b64encode((SOURCE / "installer-art.png").read_bytes()).decode("ascii")
    for name, width, height in (("installer-sidebar", 164, 314), ("installer-header", 150, 57)):
        template = (SOURCE / f"{name}.svg").read_text(encoding="utf-8").replace("ART_DATA", art)
        exported = render(template, width, height).convert("RGB")
        exported.save(DEST / f"{name}.bmp")
        exported.save(SOURCE / f"{name}-preview.png")


if __name__ == "__main__":
    main()
