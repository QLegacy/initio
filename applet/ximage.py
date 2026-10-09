"""Отправка PIL-картинки на X-drawable.

Замена Drawable.put_pil_image(): в старых python-xlib он вызывает
Image.tostring(), которого нет в Pillow >= 10. Здесь используем tobytes()
и отправляем картинку полосами, чтобы не упереться в лимит размера запроса X.
"""
from Xlib import X


def put_image(display, drawable, gc, x, y, img, depth):
    """Нарисовать RGB-картинку img в точке (x, y). depth — глубина drawable."""
    fmt = next((f for f in display.display.info.pixmap_formats if f.depth == depth), None)
    if fmt is None or fmt.bits_per_pixel != 32:
        raise RuntimeError(f"Неподдерживаемый формат пикселей (depth={depth})")

    img = img.convert("RGB")
    w, h = img.size
    rows = max(1, 200_000 // (w * 4))  # ~200 КБ на запрос
    for top in range(0, h, rows):
        strip = img.crop((0, top, w, min(h, top + rows)))
        drawable.put_image(gc, x, y + top, strip.width, strip.height,
                           X.ZPixmap, depth, 0, strip.tobytes("raw", "BGRX"))


# ---------------------------------------------------------------------- #
# Текст с кириллицей. Встроенный X-шрифт "fixed" на многих системах не
# содержит кириллицы, поэтому рисуем текст через Pillow и TTF-шрифт.
import os
import shutil
import subprocess

_FONT_CANDIDATES = (
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)
_font_path_cache = []


def find_ttf():
    """Путь к подходящему TTF-шрифту или None."""
    if _font_path_cache:
        return _font_path_cache[0]
    path = None
    if shutil.which("fc-match"):
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", "sans:lang=ru"],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            if out and os.path.isfile(out) and out.lower().endswith((".ttf", ".otf")):
                path = out
        except Exception:
            pass
    if path is None:
        path = next((p for p in _FONT_CANDIDATES if os.path.isfile(p)), None)
    _font_path_cache.append(path)
    return path


def render_text(text, size=13, fg=(236, 240, 241), bg=(44, 62, 80)):
    """PIL-картинка с текстом (с кириллицей, если нашёлся TTF) или None."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        path = find_ttf()
        if path is None:
            return None
        font = ImageFont.truetype(path, size)
        left, top, right, bottom = font.getbbox(text)
        img = Image.new("RGB", (right + 4, bottom + 4), bg)
        ImageDraw.Draw(img).text((2, 0), text, font=font, fill=fg)
        return img
    except Exception:
        return None
