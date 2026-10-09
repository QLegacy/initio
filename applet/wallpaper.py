"""Аплет обоев для Initio.

apply_wallpaper(path) ставит картинку на root-окно X-сервера.
Работает через отдельное соединение с X (безопасно вызывать из любого потока)
и делает pixmap "постоянным" (RetainPermanent), как это делают feh/xsetroot.
Если Pillow не установлен, пробуем внешние утилиты feh / xwallpaper / hsetroot.
"""
import os
import shutil
import subprocess

from Xlib import X, display, Xatom

from applet.ximage import put_image

try:
    from PIL import Image, ImageOps
except ImportError:  # Pillow необязателен, есть запасной вариант
    Image = None


def _fallback_tools(path):
    """Запасной вариант: внешние утилиты."""
    for cmd in (["feh", "--bg-fill", path],
                ["xwallpaper", "--zoom", path],
                ["hsetroot", "-cover", path]):
        if shutil.which(cmd[0]):
            return subprocess.run(cmd).returncode == 0
    return False


def _kill_old_pixmaps(d, root):
    """Освобождаем pixmap'ы, оставшиеся от прошлых установок обоев."""
    for name in ("_XROOTPMAP_ID", "ESETROOT_PMAP_ID"):
        try:
            atom = d.intern_atom(name)
            prop = root.get_full_property(atom, Xatom.PIXMAP)
            if prop and prop.value:
                d.create_resource_object("pixmap", prop.value[0]).kill_client()
        except Exception:
            pass


def apply_wallpaper(path):
    """Установить обои. Возвращает (ok, сообщение)."""
    if not path:
        return False, "Файл обоев не указан."
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return False, f"Файл не найден: {path}"

    if Image is None:
        ok = _fallback_tools(path)
        return ok, "" if ok else "Нет Pillow и feh/xwallpaper/hsetroot."

    d = None
    try:
        d = display.Display()
        screen = d.screen()
        root = screen.root
        w, h, depth = screen.width_in_pixels, screen.height_in_pixels, screen.root_depth

        # "fill": масштабируем с обрезкой под размер экрана
        img = Image.open(path).convert("RGB")
        img = ImageOps.fit(img, (w, h), Image.LANCZOS)

        _kill_old_pixmaps(d, root)

        pixmap = root.create_pixmap(w, h, depth)
        gc = root.create_gc()
        put_image(d, pixmap, gc, 0, 0, img, depth)

        # pixmap должен пережить закрытие нашего соединения
        d.set_close_down_mode(X.RetainPermanent)

        root.change_attributes(background_pixmap=pixmap)
        root.clear_area(0, 0, 0, 0)

        # свойства, по которым прозрачные терминалы и т.п. находят обои
        for name in ("_XROOTPMAP_ID", "ESETROOT_PMAP_ID"):
            root.change_property(d.intern_atom(name), Xatom.PIXMAP, 32,
                                 [pixmap.id])
        d.sync()
        return True, ""
    except Exception as e:
        # Если Xlib-путь не сработал (экзотическая глубина цвета и т.п.)
        if _fallback_tools(path):
            return True, ""
        return False, f"Не удалось установить обои: {e}"
    finally:
        if d is not None:
            try:
                d.close()
            except Exception:
                pass
