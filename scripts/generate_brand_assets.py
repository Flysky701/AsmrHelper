"""Export editable SVG branding with the installed Tauri renderer and Pillow.

Run with the project .venv after installing desktop npm dependencies.
No running application or release build is modified.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "desktop/node_modules/@tauri-apps/cli/tauri.js"
SOURCES = ROOT / "desktop/branding"
DEST = SOURCES / "exports"
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def render(source: Path, width: int, height: int) -> Image.Image:
    """Tauri takes square SVGs; pad the viewport, then crop the padded area."""
    side = max(width, height)
    tree = ET.parse(source)
    svg = tree.getroot()
    svg.set("width", str(side))
    svg.set("height", str(side))
    svg.set("viewBox", f"0 0 {side} {side}")
    with tempfile.TemporaryDirectory(prefix="asmr-brand-") as temporary:
        folder = Path(temporary)
        padded = folder / "source.svg"
        tree.write(padded, encoding="utf-8", xml_declaration=True)
        subprocess.run(
            [shutil.which("node") or "node", str(CLI), "icon", str(padded),
             "--output", str(folder), "--png", str(side)], check=True,
        )
        with Image.open(folder / f"{side}x{side}.png") as result:
            return result.convert("RGBA").crop((0, 0, width, height))


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    icon = render(SOURCES / "asmr-helper.svg", 512, 512)
    icon.save(DEST / "icon.png")
    icon.save(DEST / "icon.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    for name, width, height in (("installer-sidebar", 164, 314), ("installer-header", 150, 57)):
        render(SOURCES / f"{name}.svg", width, height).convert("RGB").save(DEST / f"{name}.bmp")
    make_preview()


def make_preview() -> None:
    """A clearly labelled layout illustration, not a native installer screenshot."""
    board = ET.fromstring('''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760">
      <rect width="1200" height="760" fill="#F2F6F7"/>
      <g font-family="Segoe UI, Microsoft YaHei, sans-serif">
        <text x="56" y="60" font-size="14" fill="#537680" letter-spacing="2">ASMR HELPER / VISUAL IDENTITY</text>
        <text x="56" y="112" font-size="32" fill="#203C47" font-weight="600">让声音，成为作品。</text>
        <text x="56" y="145" font-size="15" fill="#647C85">耳机 × 声波 · 青蓝色系 · 桌面与安装向导统一视觉</text>
        <rect x="56" y="186" width="320" height="418" rx="22" fill="#FFFFFF"/>
        <text x="80" y="225" font-size="14" fill="#647C85">应用图标</text>
        <text x="80" y="530" font-size="12" fill="#647C85">16 / 24 / 32 / 48 px</text>
        <rect x="56" y="628" width="320" height="76" rx="18" fill="#20333E"/>
        <text x="80" y="662" font-size="16" fill="#E8FAF9" font-weight="600">ASMR Helper</text>
        <text x="80" y="685" font-size="12" fill="#A7CCD3">Audio workspace</text>
        <text x="422" y="191" font-size="14" fill="#647C85">安装向导 · 欢迎与完成页共用品牌侧图</text>
        <rect x="422" y="210" width="722" height="404" rx="8" fill="#FFFFFF" stroke="#CEDADD"/>
        <path d="M430 210H1136Q1144 210 1144 218V246H422V218Q422 210 430 210" fill="#F9FAFB"/>
        <text x="457" y="233" font-size="12" fill="#273E47">ASMR Helper Test 安装</text>
        <text x="1116" y="233" font-size="15" fill="#61727A">×</text>
        <text x="614" y="284" font-size="21" font-weight="600" fill="#263F49">欢迎安装 ASMR Helper Test</text>
        <text x="614" y="324" font-size="14" fill="#5A6F78">音频制作工作台</text>
        <text x="614" y="355" font-size="13" fill="#5A6F78">准备好素材，连接你的声音工作流。</text>
        <text x="614" y="396" font-size="13" fill="#5A6F78">安装向导将引导你完成安装。</text>
        <text x="614" y="421" font-size="13" fill="#5A6F78">点击“下一步”继续。</text>
        <path d="M422 560H1144" stroke="#DCE3E6"/>
        <rect x="917" y="575" width="104" height="26" rx="3" fill="#FFFFFF" stroke="#24788F"/>
        <text x="934" y="593" font-size="12" fill="#263F49">下一步(N) &gt;</text>
        <rect x="1035" y="575" width="87" height="26" rx="3" fill="#FFFFFF" stroke="#CEDADD"/>
        <text x="1066" y="593" font-size="12" fill="#263F49">取消</text>
        <text x="422" y="655" font-size="13" fill="#647C85">步骤页页眉</text>
        <rect x="570" y="634" width="160" height="65" rx="8" fill="#FFFFFF" stroke="#DEE7E9"/>
        <text x="759" y="658" font-size="12" fill="#647C85">侧图 164 × 314 / 页眉 150 × 57</text>
        <text x="759" y="683" font-size="12" fill="#647C85">ICO 9 种尺寸 / SVG 可编辑源稿</text>
        <text x="56" y="739" font-size="12" fill="#748891">安装向导为布局示意，非运行截图；实际文案、按钮和窗口由 NSIS 提供。</text>
      </g>
    </svg>''')

    def place(source: Path, x: int, y: int, width: int, height: int) -> None:
        element = ET.parse(source).getroot()
        for key, value in {"x": x, "y": y, "width": width, "height": height}.items():
            element.set(key, str(value))
        board.append(element)

    icon_source = SOURCES / "asmr-helper.svg"
    place(icon_source, 108, 252, 216, 216)
    for x, size in ((80, 16), (120, 24), (168, 32), (228, 48)):
        place(icon_source, x, 546, size, size)
    place(icon_source, 307, 647, 40, 40)
    place(icon_source, 432, 219, 19, 19)
    place(SOURCES / "installer-sidebar.svg", 423, 246, 164, 314)
    place(SOURCES / "installer-header.svg", 575, 638, 150, 57)
    preview = SOURCES / "brand-preview.svg"
    ET.ElementTree(board).write(preview, encoding="utf-8", xml_declaration=True)
    render(preview, 1200, 760).save(SOURCES / "brand-preview.png")


if __name__ == "__main__":
    main()
