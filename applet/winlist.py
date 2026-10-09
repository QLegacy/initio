"""Аплет WinList для Initio: переключатель окон Alt+Tab с превью.

Как это работает:
  * Alt+Tab / Alt+Shift+Tab перехватываются на root-окне (passive grab).
  * При первом нажатии захватываем клавиатуру целиком, показываем окно
    (override-redirect) с миниатюрами и держим его, пока зажат Alt.
  * Tab / Shift+Tab / стрелки — выбор, отпускание Alt или Enter — переключиться,
    Escape — отмена.
  * Порядок окон — по недавности использования (MRU), как в обычных DE.

Превью делаются через GetImage. Чтобы они были корректны и у перекрытых окон,
по возможности включаем расширение Composite (автоматический режим).
Свёрнутые окна показываются по последнему снимку (его делаем при сворачивании).
Без Pillow вместо превью рисуются цветные заглушки.
"""
from Xlib import X, XK, error

from applet.ximage import put_image

try:
    from PIL import Image
    _BILINEAR = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
except ImportError:
    Image = None

THUMB_W, THUMB_H = 190, 120
CELL_W, CELL_H = 210, 165
PAD = 12
BG = 0x1c2833
SEL = 0x3498db
PLACEHOLDER = 0x34495e
TEXT = 0xecf0f1

_ALT_KEYSYMS = (XK.XK_Alt_L, XK.XK_Alt_R, XK.XK_Meta_L, XK.XK_Meta_R)


def _ignore_error(err, request):
    """Ошибки X (например, клавиша уже занята) не должны валить WM."""
    pass


class WinList:
    def __init__(self, wm):
        self.wm = wm
        self.display = wm.display
        self.root = wm.root
        self.screen = wm.screen

        self.mru = []          # frame id, самый свежий первым
        self.snapshots = {}    # frame id -> PIL.Image (последняя миниатюра)
        self.items = []
        self.sel = 0
        self.cols = 1
        self.active = False
        self.win = None
        self.gcs = {}
        self.composite = False

        try:
            self.font = self.display.open_font("fixed")
        except Exception:
            self.font = None

        self._setup_composite()
        self._grab_keys()

    # ------------------------------------------------------------------ #
    # инициализация
    def _setup_composite(self):
        """Чтобы GetImage отдавал содержимое и перекрытых окон."""
        try:
            from Xlib.ext import composite
            if not self.display.has_extension("Composite"):
                return
            self.display.composite_query_version()
            self.root.composite_redirect_subwindows(composite.RedirectAutomatic)
            self.display.sync()
            self.composite = True
        except Exception:
            self.composite = False

    def _grab_keys(self):
        tab = self.display.keysym_to_keycode(XK.XK_Tab)
        # учитываем CapsLock (Lock) и NumLock (Mod2), иначе с ними комбинация не сработает
        for base in (X.Mod1Mask, X.Mod1Mask | X.ShiftMask):
            for extra in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):
                self.root.grab_key(tab, base | extra, True,
                                   X.GrabModeAsync, X.GrabModeAsync,
                                   onerror=_ignore_error)
        self.display.flush()

    # ------------------------------------------------------------------ #
    # API для WM
    def touch(self, fid):
        """Окно стало активным — переносим в начало MRU."""
        if fid in self.mru:
            self.mru.remove(fid)
        self.mru.insert(0, fid)

    def forget(self, fid):
        if fid in self.mru:
            self.mru.remove(fid)
        self.snapshots.pop(fid, None)

    def is_switcher(self, window):
        return self.win is not None and window.id == self.win.id

    def snapshot(self, fid):
        """Сделать снимок окна (вызывается WM перед сворачиванием)."""
        state = self.wm.managed_windows.get(fid)
        if state:
            self._capture(fid, state)

    def handle_key_press(self, ev):
        """True, если событие обработано аплетом."""
        keysym = self.display.keycode_to_keysym(ev.detail, 0)
        shift = bool(ev.state & X.ShiftMask)

        if not self.active:
            if keysym == XK.XK_Tab and ev.state & X.Mod1Mask:
                self._open(reverse=shift)
                return True
            return False

        n = len(self.items)
        if keysym == XK.XK_Tab:
            self._move(-1 if shift else 1)
        elif keysym in (XK.XK_Right,):
            self._move(1)
        elif keysym in (XK.XK_Left,):
            self._move(-1)
        elif keysym == XK.XK_Down:
            self._move(self.cols if n > self.cols else 1)
        elif keysym == XK.XK_Up:
            self._move(-self.cols if n > self.cols else -1)
        elif keysym == XK.XK_Escape:
            self._close(commit=False)
        elif keysym in (XK.XK_Return, XK.XK_KP_Enter):
            self._close(commit=True)
        return True  # пока открыт переключатель, клавиши никому не отдаём

    def handle_key_release(self, ev):
        if not self.active:
            return False
        if self.display.keycode_to_keysym(ev.detail, 0) in _ALT_KEYSYMS:
            self._close(commit=True)
        return True

    # ------------------------------------------------------------------ #
    # внутренняя логика
    def _ordered_ids(self):
        ids = list(self.wm.managed_windows.keys())
        fresh = [f for f in ids if f not in self.mru]   # новые окна — в начало
        return fresh + [f for f in self.mru if f in ids]

    def _title(self, state):
        try:
            name = state['app'].get_wm_name()
        except Exception:
            name = None
        if isinstance(name, bytes):
            name = name.decode("latin-1", "replace")
        if not name:
            name = self.wm.get_window_class(state['app'])
        return name

    def _capture(self, fid, state):
        """Миниатюра окна или None. Для свёрнутых — последний снимок."""
        if Image is None:
            return None
        app = state['app']
        try:
            if app.get_attributes().map_state == X.IsViewable:
                g = app.get_geometry()
                if g.width > 0 and g.height > 0:
                    raw = app.get_image(0, 0, g.width, g.height,
                                        X.ZPixmap, 0xffffffff)
                    if raw.depth in (24, 32):
                        img = Image.frombytes("RGB", (g.width, g.height),
                                              raw.data, "raw", "BGRX")
                        img.thumbnail((THUMB_W, THUMB_H), _BILINEAR)
                        self.snapshots[fid] = img
        except Exception:
            pass  # окно закрыто / вылезает за экран без Composite и т.п.
        return self.snapshots.get(fid)

    def _open(self, reverse=False):
        ids = self._ordered_ids()
        if not ids:
            return

        # Захватываем клавиатуру, чтобы получить отпускание Alt
        status = self.root.grab_keyboard(False, X.GrabModeAsync,
                                         X.GrabModeAsync, X.CurrentTime)
        if status != X.GrabSuccess:
            return

        self.items = []
        for fid in ids:
            state = self.wm.managed_windows[fid]
            frame = self.display.create_resource_object('window', fid)
            self.items.append({
                'fid': fid,
                'title': self._title(state),
                'thumb': self._capture(fid, state),
                'minimized': frame in self.wm.minimized_frames,
            })

        n = len(self.items)
        self.sel = (n - 1) if reverse else (1 if n > 1 else 0)

        sw, sh = self.screen.width_in_pixels, self.screen.height_in_pixels
        self.cols = max(1, min(n, (sw - 80) // CELL_W))
        rows = -(-n // self.cols)
        w, h = self.cols * CELL_W + 2 * PAD, rows * CELL_H + 2 * PAD

        self.win = self.root.create_window(
            (sw - w) // 2, (sh - h) // 2, w, h, 0,
            self.screen.root_depth, X.InputOutput, X.CopyFromParent,
            background_pixel=BG, override_redirect=True,
            event_mask=X.ExposureMask)
        self.gcs = {
            'sel': self.win.create_gc(foreground=SEL),
            'ph': self.win.create_gc(foreground=PLACEHOLDER),
            'img': self.win.create_gc(),
        }
        if self.font:
            self.gcs['txt'] = self.win.create_gc(
                foreground=TEXT, background=BG, font=self.font)
            self.gcs['txt_sel'] = self.win.create_gc(
                foreground=0xffffff, background=SEL, font=self.font)
        self.win.map()
        self.win.configure(stack_mode=X.Above)
        self.active = True
        self.display.flush()

        # Если Alt уже отпустили, пока мы грабили клавиатуру — сразу переключаемся
        if not self.root.query_pointer().mask & X.Mod1Mask:
            self._close(commit=True)

    def _move(self, step):
        if self.items:
            self.sel = (self.sel + step) % len(self.items)
            self.draw()

    def _close(self, commit):
        self.active = False
        target = self.items[self.sel]['fid'] if (commit and self.items) else None
        try:
            self.display.ungrab_keyboard(X.CurrentTime)
            for gc in self.gcs.values():
                gc.free()
            if self.win is not None:
                self.win.destroy()
        except error.XError:
            pass
        self.gcs, self.win, self.items = {}, None, []
        self.display.flush()
        if target is not None:
            self._activate(target)

    def _activate(self, fid):
        state = self.wm.managed_windows.get(fid)
        if not state:
            return
        try:
            frame = self.display.create_resource_object('window', fid)
            if frame in self.wm.minimized_frames:
                self.wm.restore_minimized(frame)
            frame.configure(stack_mode=X.Above)
            self.wm.raise_panel_if_pinned()
            state['app'].set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
            self.touch(fid)
            self.display.flush()
        except error.XError:
            pass

    # ------------------------------------------------------------------ #
    def draw(self):
        if not self.win or not self.items:
            return
        try:
            self.win.clear_area(0, 0, 0, 0)
            for i, item in enumerate(self.items):
                col, row = i % self.cols, i // self.cols
                x0, y0 = PAD + col * CELL_W, PAD + row * CELL_H
                selected = (i == self.sel)

                if selected:
                    self.win.fill_rectangle(self.gcs['sel'], x0, y0,
                                            CELL_W - 4, CELL_H - 4)

                # область превью
                tx, ty = x0 + 8, y0 + 8
                thumb = item['thumb']
                if thumb is not None:
                    ox = tx + (THUMB_W - thumb.width) // 2
                    oy = ty + (THUMB_H - thumb.height) // 2
                    put_image(self.display, self.win, self.gcs['img'], ox, oy,
                              thumb, self.screen.root_depth)
                else:
                    self.win.fill_rectangle(self.gcs['ph'], tx, ty,
                                            THUMB_W, THUMB_H)

                # подпись (fixed — 6 px на символ)
                if self.font:
                    label = ("[_] " if item['minimized'] else "") + item['title']
                    label = label[:(CELL_W - 20) // 6]
                    gc = self.gcs['txt_sel' if selected else 'txt']
                    self.win.image_text(gc, tx, ty + THUMB_H + 20,
                                        label.encode("latin-1", "replace"))
            self.display.flush()
        except error.XError:
            pass
