"""Genera los íconos rasterizados de VEXA Local a partir de los SVG (la única fuente del dibujo).

    .\\.venv\\Scripts\\python.exe scripts\\generar_iconos.py

Usa Microsoft Edge en modo sin ventana para dibujar los SVG tal como los ve un navegador, y Pillow para
recortar, reducir y empaquetar el .ico. Crea en frontend/static/img/:
  icon.ico         ícono de Windows (instalador, acceso directo y ventana de Electron), 16 a 256 px
  icon_square.png  ícono de la app 512 px (favicon de respaldo)
  logo.png         logo completo sobre fondo claro (documentos y README)

Solo hace falta volver a ejecutarlo si cambian vexa-app.svg o vexa-icon-azul.svg.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

IMG = Path(__file__).resolve().parents[1] / "frontend" / "static" / "img"
EDGE_PATHS = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
              Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe"]

APP_PAGE = """<!doctype html><html><body style="margin:0;background:transparent">
<img src="vexa-app.svg" style="width:{size}px;height:{size}px;display:block"></body></html>"""

LOGO_PAGE = """<!doctype html><html><body style="margin:0;background:#fff">
<div style="display:flex;align-items:center;gap:56px;padding:90px 110px;font-family:'Segoe UI',Arial,sans-serif">
  <img src="vexa-icon-azul.svg" style="width:330px;height:330px">
  <div><div style="font-weight:700;font-size:178px;line-height:1;letter-spacing:.09em;color:#0B1020">VEXA</div>
       <div style="margin-top:34px;font-weight:700;font-size:40px;letter-spacing:.62em;color:#2A4BD7">LOCAL</div></div>
</div></body></html>"""


def _edge() -> Path:
    for path in EDGE_PATHS:
        if path.is_file():
            return path
    raise SystemExit("No se encontró Microsoft Edge: hace falta para dibujar los SVG.")


def _render(html: str, width: int, height: int, transparent: bool) -> Image.Image:
    """Dibuja una página HTML (junto a los SVG) y devuelve la captura."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for svg in IMG.glob("vexa-*.svg"):
            shutil.copy(svg, work / svg.name)
        page, shot = work / "pagina.html", work / "captura.png"
        page.write_text(html, encoding="utf-8")
        args = [str(_edge()), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--disable-lcd-text", f"--user-data-dir={work / 'perfil'}",
                f"--window-size={width},{height}", f"--screenshot={shot}", page.as_uri()]
        if transparent:
            args.insert(4, "--default-background-color=00000000")
        subprocess.run(args, capture_output=True, timeout=60, check=False)
        if not shot.is_file():
            raise SystemExit("Edge no pudo generar la captura.")
        return Image.open(shot).convert("RGBA").copy()


def _trim(img: Image.Image, margin: int) -> Image.Image:
    """Recorta el fondo blanco sobrante dejando un margen parejo."""
    background = Image.new("RGB", img.size, "#FFFFFF")
    left, top, right, bottom = ImageChops.difference(img.convert("RGB"), background).getbbox()
    return img.crop((max(0, left - margin), max(0, top - margin),
                     min(img.width, right + margin), min(img.height, bottom + margin)))


def main() -> int:
    app = _render(APP_PAGE.format(size=512), 512, 512, transparent=True)
    app.save(IMG / "icon_square.png")
    sizes = [256, 128, 64, 48, 32, 24, 16]
    frames = [app.resize((s, s), Image.LANCZOS) for s in sizes]
    frames[0].save(IMG / "icon.ico", sizes=[(s, s) for s in sizes], append_images=frames[1:])
    logo = _trim(_render(LOGO_PAGE, 1400, 600, transparent=False), margin=60)
    logo.convert("RGB").save(IMG / "logo.png", optimize=True)
    for name in ("icon.ico", "icon_square.png", "logo.png"):
        print(f"{name}: {(IMG / name).stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
