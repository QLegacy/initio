import os
import subprocess
import shutil
import sys
from Xlib import display, X, error, protocol, XK
# Апплет настроек что бы протестировать кривой тайлинг
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
from applet.settings import open_settings, load_config, update_config
from applet.wallpaper import apply_wallpaper
from applet.winlist import WinList
from applet.ximage import put_image, render_text
PANEL_WIDTH = 55       # толщина таскбара у левого/правого края
VBTN_WIDTH = 51        # ширина кнопок в вертикальном таскбаре (влезает слово settings)
PANEL_EDGES = ("bottom", "top", "left", "right")
SNAP_DIST = 40
TITLEBAR_HEIGHT = 25
BORDER_WIDTH = 3
FRAME_COLOR = 0x2c3e50
PANEL_HEIGHT = 40
RESIZE_ZONE = 10

class InitioWM:
    def __init__(self):
        self.display = display.Display()
        self.screen = self.display.screen()
        self.root = self.screen.root
        self.color_counter = 0
        self.buttons = {}
        self.managed_windows = {}
        self.minimized_frames = []

        self.drag_start = None
        self.drag_window = None
        self.drag_window_start_pos = None
        self.drag_window_size = (0, 0)
        self.resize_window = None
        self.resize_start_geom = None
        self.resize_edge = None
        self.config = load_config()
        self.panel_edge = self.config.get("taskbar_edge", "bottom")
        if self.panel_edge not in PANEL_EDGES:
            self.panel_edge = "bottom"
        self.panel_pinned = bool(self.config.get("taskbar_pinned", False))
        self.panel_dragging = False
        self.menu_win = None
        self.menu_gc = None
        self.menu_size = (0, 0)
        self.btn_widths = {}
        font = self.display.open_font('cursor')
        self.cursor_resize = font.create_glyph_cursor(font, 120, 121, (0, 0, 0), (65535, 65535, 65535))
        
        self.taskbar_buttons = {}
        self.taskbar_icons = []

        self.panel = self.create_panel()
        self.root.change_attributes(event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)

        try:
            self.font = self.display.open_font("fixed")
            self.gc_close = self.root.create_gc(foreground=0xffffff, background=0xe74c3c, font=self.font)
            self.gc_grey = self.root.create_gc(foreground=0x000000, background=0x95a5a6, font=self.font)
            # для подписей на кнопках таскбара: только цвет текста, без заливки фона
            self.gc_label = self.root.create_gc(foreground=0x000000, font=self.font)
        except:
            self.font = None

        # Часы в таскбаре рисуем из отдельного потока со своим соединением с X,
        # чтобы не зависеть от основного цикла событий
        threading.Thread(target=self._clock_loop, args=(self.clock.id,), daemon=True).start()

        # Аплеты: WinList (Alt+Tab) и обои
        self.winlist = WinList(self)
        wallpaper = self.config.get("wallpaper")
        if wallpaper:
            threading.Thread(target=apply_wallpaper, args=(wallpaper,), daemon=True).start()

        self.set_system_cursor()

    def event_loop(self):
        while True:
            ev = self.display.next_event()

            if ev.type == X.Expose and ev.count == 0:
                if ev.window.id in self.buttons and self.font:
                    btn_info = self.buttons[ev.window.id]
                    action = btn_info['action']
                    win = ev.window
                    if action == 'close':
                        win.image_text(self.gc_close, 17, 12, "X")
                    elif action == 'maximize':
                        is_max = self.managed_windows[btn_info['frame'].id]['maximized']
                        win.image_text(self.gc_grey, 8 if is_max else 5, 12, "MIN" if is_max else "FULL")
                    elif action == 'minimize':
                        win.image_text(self.gc_grey, 4, 12, "__")
                
                if ev.window.id in self.taskbar_buttons and self.font:
                    app_name = self.taskbar_buttons[ev.window.id]['name']
                    bw = ev.window.get_geometry().width
                    ev.window.fill_rectangle(self.gc_grey, 2, 2, bw - 4, 26)
                    ev.window.image_text(self.gc_grey, 10 if bw >= 60 else 5, 20,
                                         app_name[:min(10, (bw - 8) // 6)])

                if ev.window == self.ini_btn or ev.window == self.settings_btn:
                    self.draw_btn_label(ev.window)

                if self.winlist.is_switcher(ev.window):
                    self.winlist.draw()

                if self.menu_win is not None and ev.window == self.menu_win:
                    self.draw_menu()

            elif ev.type == X.KeyRelease:
                self.winlist.handle_key_release(ev)

            elif ev.type == X.KeyPress:
                if self.winlist.handle_key_press(ev):
                    continue
                if self.minimized_frames:
                    f = self.minimized_frames.pop()
                    try:
                        f.map()
                        f.configure(stack_mode=X.Above)
                    except error.BadWindow:
                        pass

            elif ev.type == X.DestroyNotify:
                for fid, state in list(self.managed_windows.items()):
                    if state['app'] == ev.window:
                        self.destroy_frame(self.display.create_resource_object('window', fid))
                        break
            
            elif ev.type == X.MapRequest:
                self.decorate_and_map(ev.window)

            elif ev.type == X.ConfigureNotify:
                for fid, state in self.managed_windows.items():
                    if state['app'] == ev.window:
                        fw, fh = ev.width + BORDER_WIDTH * 2, ev.height + TITLEBAR_HEIGHT + BORDER_WIDTH * 2
                        frame_win = self.display.create_resource_object('window', fid)
                        try:
                            frame_win.configure(width=fw, height=fh)
                            self.update_buttons_pos(fid, fw)
                        except error.BadWindow: pass
                        break

            elif ev.type == X.ConfigureRequest:
                window = ev.window
                is_managed = any(s['app'] == window for s in self.managed_windows.values())
                args = {}
                if is_managed:
                    self.resize_managed(window, ev)
                    continue
                else:
                    args = {k: getattr(ev, k) for k in ['x', 'y', 'width', 'height'] if ev.value_mask & (1 << (list(['x','y','width','height']).index(k)))}
                try: window.configure(**args)
                except error.BadWindow: pass

            elif ev.type == X.ButtonPress:
                # Открыто контекстное меню таскбара: любой клик его обрабатывает/закрывает
                if self.menu_win is not None:
                    self.handle_menu_click(ev)
                    continue

                # Клики по таскбару и его кнопкам: ПКМ — меню, ЛКМ по пустому месту — перетаскивание
                if ev.window == self.panel or ev.window.id in self.panel_part_ids():
                    if ev.detail == 3:
                        self.show_menu(ev.root_x, ev.root_y)
                        continue
                    if ev.detail != 1:
                        continue
                    if ev.window == self.panel:
                        if not self.panel_pinned:
                            self.panel_dragging = True
                            self.panel.grab_pointer(False, X.PointerMotionMask | X.ButtonReleaseMask,
                                                    X.GrabModeAsync, X.GrabModeAsync, X.NONE, X.NONE, X.CurrentTime)
                        continue

                if ev.window == self.ini_btn:
                    subprocess.Popen(["rofi", "-show", "drun"])
                    continue
                
                if ev.window.id in self.managed_windows and ev.detail == 1:
                    geom = ev.window.get_geometry()
                    edge = self.get_resize_edge(geom, ev.event_x, ev.event_y)
                    if edge != (0, 0):
                        self.resize_window, self.resize_edge = ev.window, edge
                        self.resize_start_geom = (ev.root_x, ev.root_y, geom.width, geom.height, geom.x, geom.y)
                        ev.window.grab_pointer(True, X.PointerMotionMask | X.ButtonReleaseMask, X.GrabModeAsync, X.GrabModeAsync, X.NONE, self.cursor_resize, X.CurrentTime)
                        continue
                if ev.window.id == self.settings_btn.id:
                    open_settings(self)
                    continue
                if ev.window.id in self.taskbar_buttons:
                    data = self.taskbar_buttons[ev.window.id]
                    frame_to_restore = data['frame']
                    self.restore_minimized(frame_to_restore)
                    self.winlist.touch(frame_to_restore.id)
                    continue

                if ev.window.id in self.buttons:
                    b = self.buttons[ev.window.id]
                    if b['action'] == 'close': self.close_app(b['app'])
                    elif b['action'] == 'minimize':
                        self.winlist.snapshot(b['frame'].id)  # превью для Alt+Tab, пока окно видно
                        b['frame'].unmap()
                        self.minimized_frames.append(b['frame'])
                        app_name = self.get_window_class(b['app'])
                        bx, by = self.task_btn_pos(len(self.taskbar_icons))
                        task_btn = self.panel.create_window(bx, by, self.task_btn_width(), 30, 0, self.screen.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=0x34495e, event_mask=X.ButtonPressMask | X.ExposureMask)
                        task_btn.map()
                        self.taskbar_buttons[task_btn.id] = {'frame': b['frame'], 'name': app_name}
                        self.taskbar_icons.append(task_btn)
                    elif b['action'] == 'maximize':
                        state = self.managed_windows[b['frame'].id]
                        if not state['maximized']:
                            state['frame_geom'] = b['frame'].get_geometry()
                            state['geom'] = b['app'].get_geometry()
                            ax, ay, aw, ah = self.work_area()
                            b['frame'].configure(x=ax, y=ay, width=aw, height=ah)
                            b['app'].configure(width=aw - BORDER_WIDTH * 2, height=ah - TITLEBAR_HEIGHT - BORDER_WIDTH * 2)
                            state['maximized'] = True
                            self.update_buttons_pos(b['frame'].id, aw)
                        else:
                            fg, ag = state['frame_geom'], state['geom']
                            b['frame'].configure(x=fg.x, y=fg.y, width=fg.width, height=fg.height)
                            b['app'].configure(width=ag.width, height=ag.height)
                            state['maximized'] = False
                            self.update_buttons_pos(b['frame'].id, fg.width)
                        state['btns']['max'].clear_area(0,0,0,0,True)
                elif ev.window != self.root and ev.detail == 1:
                    ev.window.grab_pointer(True, X.ButtonReleaseMask | X.PointerMotionMask, X.GrabModeAsync, X.GrabModeAsync, X.NONE, X.NONE, X.CurrentTime)
                    ev.window.configure(stack_mode=X.Above)
                    self.raise_panel_if_pinned()
                    self.winlist.touch(ev.window.id)
                    self.drag_start, self.drag_window = (ev.root_x, ev.root_y), ev.window
                    geom = ev.window.get_geometry()
                    self.drag_window_start_pos = (geom.x, geom.y)
                    self.drag_window_size = (geom.width, geom.height)

            elif ev.type == X.MotionNotify:
                if self.panel_dragging:
                    # таскбар липнет к ближайшему краю экрана
                    sw, sh = self.screen.width_in_pixels, self.screen.height_in_pixels
                    dist = {'left': ev.root_x, 'right': sw - ev.root_x,
                            'top': ev.root_y, 'bottom': sh - ev.root_y}
                    self.set_panel_edge(min(dist, key=dist.get))
                elif self.drag_window:
                    dx, dy = ev.root_x - self.drag_start[0], ev.root_y - self.drag_start[1]
                    nx, ny = self.drag_window_start_pos[0] + dx, self.drag_window_start_pos[1] + dy

                    # магнит к краям рабочей области (экран без таскбара)
                    gw, gh = self.drag_window_size  # размер при перетаскивании не меняется
                    ax, ay, aw, ah = self.work_area()
                    if abs(nx - ax) < SNAP_DIST: nx = ax
                    if abs(nx + gw - (ax + aw)) < SNAP_DIST: nx = ax + aw - gw
                    if abs(ny - ay) < SNAP_DIST: ny = ay
                    if abs(ny + gh - (ay + ah)) < SNAP_DIST: ny = ay + ah - gh

                    # закреплённый таскбар: окно нельзя утащить на него
                    if self.panel_pinned:
                        nx = max(ax, min(nx, ax + aw - gw))
                        ny = max(ay, min(ny, ay + ah - gh))

                    self.drag_window.configure(x=nx, y=ny)
                elif self.resize_window and self.resize_edge:
                    dx, dy = ev.root_x - self.resize_start_geom[0], ev.root_y - self.resize_start_geom[1]
                    sw, sh, sx, sy = self.resize_start_geom[2], self.resize_start_geom[3], self.resize_start_geom[4], self.resize_start_geom[5]
                    nw, nh, nx, ny = sw, sh, sx, sy
                    if self.resize_edge[0] != 0:
                        nw = sw + (dx if self.resize_edge[0] == 1 else -dx)
                        if self.resize_edge[0] == -1: nx = sx + dx
                    if self.resize_edge[1] != 0:
                        nh = sh + (dy if self.resize_edge[1] == 1 else -dy)
                        if self.resize_edge[1] == -1: ny = sy + dy
                    if self.panel_pinned:  # изменение размера тоже не заходит под таскбар
                        ax, ay, aw, ah = self.work_area()
                        if nx < ax: nw, nx = nw - (ax - nx), ax
                        if ny < ay: nh, ny = nh - (ay - ny), ay
                        nw = min(nw, ax + aw - nx)
                        nh = min(nh, ay + ah - ny)
                    nw, nh = max(50, nw), max(50, nh)
                    self.resize_window.configure(x=nx, y=ny, width=nw, height=nh)
                    self.managed_windows[self.resize_window.id]['app'].configure(width=nw - BORDER_WIDTH * 2, height=nh - TITLEBAR_HEIGHT - BORDER_WIDTH * 2)
                    self.update_buttons_pos(self.resize_window.id, nw)

            elif ev.type == X.ButtonRelease:
                if self.panel_dragging:
                    self.display.ungrab_pointer(X.CurrentTime)
                    self.panel_dragging = False
                    continue
                if self.drag_window:
                    self.handle_snap_and_swap(self.drag_window) # Чекнем надо ли поменять окна местами
                    self.display.ungrab_pointer(X.CurrentTime)
                    self.drag_window = None
                if self.resize_window or self.drag_window:
                    self.display.ungrab_pointer(X.CurrentTime)
                    self.resize_window = self.drag_window = None
                

    def create_panel(self):
        # геометрия здесь временная, настоящую выставляет layout_panel()
        panel = self.root.create_window(0, self.screen.height_in_pixels - PANEL_HEIGHT, self.screen.width_in_pixels, PANEL_HEIGHT, 0, self.screen.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=0x1a1a1a, event_mask=X.ButtonPressMask | X.ExposureMask)
        self.panel = panel
        self.ini_btn = panel.create_window(5, 5, 60, 30, 0, self.screen.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=0x3498db, event_mask=X.ButtonPressMask | X.ExposureMask)
        self.settings_btn = panel.create_window(70, 5, 80, 30, 0, self.screen.root_depth,
                                                X.InputOutput, X.CopyFromParent,
                                                background_pixel=0x2ecc71, event_mask=X.ButtonPressMask | X.ExposureMask)
        # часы: без маски событий, поэтому клики по ним уходят самому таскбару
        self.clock = panel.create_window(0, 5, 100, 30, 0, self.screen.root_depth,
                                         X.InputOutput, X.CopyFromParent, background_pixel=0x1a1a1a)
        self.layout_panel()
        panel.map()
        self.ini_btn.map()
        self.settings_btn.map()
        self.clock.map()
        self.raise_panel_if_pinned()
        return panel

    # ------------------------------------------------------------------ #
    # Таскбар: раскладка, магнит к краям, закрепление, меню, часы
    def resize_managed(self, window, ev):
        """Приложение само меняет размер окна (Tk после показа виджетов и т.п.):
        подгоняем под него рамку, иначе низ окна (кнопки!) обрезается рамкой."""
        for fid, state in self.managed_windows.items():
            if state['app'] == window:
                break
        else:
            return
        frame = self.display.create_resource_object('window', fid)
        try:
            if state['maximized'] or self.config.get("tiling"):
                # размер задаёт WM: оставляем окно по размеру рамки
                fg = frame.get_geometry()
                window.configure(width=max(1, fg.width - BORDER_WIDTH * 2),
                                 height=max(1, fg.height - TITLEBAR_HEIGHT - BORDER_WIDTH * 2))
                return
            g = window.get_geometry()
            w = ev.width if ev.value_mask & X.CWWidth else g.width
            h = ev.height if ev.value_mask & X.CWHeight else g.height
            fw, fh = w + BORDER_WIDTH * 2, h + TITLEBAR_HEIGHT + BORDER_WIDTH * 2
            window.configure(width=w, height=h)
            # если выросшее окно уезжает за низ/право рабочей области — подвигаем рамку
            ax, ay, aw, ah = self.work_area()
            fg = frame.get_geometry()
            nx = max(ax, min(fg.x, ax + aw - fw))
            ny = max(ay, min(fg.y, ay + ah - fh))
            frame.configure(x=nx, y=ny, width=fw, height=fh)
            self.update_buttons_pos(fid, fw)
        except error.BadWindow:
            pass

    def draw_btn_label(self, win):
        """Подпись на кнопке: rofi / settings (по центру, без заливки фона)."""
        if not self.font:
            return
        label = b"rofi" if win == self.ini_btn else b"settings"
        bw = self.btn_widths.get(win.id, 60)  # без запроса к серверу, иначе подпись мигает
        win.poly_text(self.gc_label, max(1, (bw - len(label) * 6) // 2), 19, [label])

    def panel_is_horizontal(self):
        return self.panel_edge in ("top", "bottom")

    def work_area(self):
        """Область экрана без таскбара: (x, y, width, height)."""
        sw, sh = self.screen.width_in_pixels, self.screen.height_in_pixels
        return {
            'bottom': (0, 0, sw, sh - PANEL_HEIGHT),
            'top': (0, PANEL_HEIGHT, sw, sh - PANEL_HEIGHT),
            'left': (PANEL_WIDTH, 0, sw - PANEL_WIDTH, sh),
            'right': (0, 0, sw - PANEL_WIDTH, sh),
        }[self.panel_edge]

    def panel_part_ids(self):
        ids = {self.ini_btn.id, self.settings_btn.id, self.clock.id}
        ids.update(self.taskbar_buttons.keys())
        return ids

    def task_btn_width(self):
        return 100 if self.panel_is_horizontal() else VBTN_WIDTH

    def task_btn_pos(self, index):
        """Позиция кнопки свёрнутого окна внутри таскбара."""
        if self.panel_is_horizontal():
            return 70 + index * 105, 5
        return 2, 40 + index * 35

    def layout_panel(self):
        sw, sh = self.screen.width_in_pixels, self.screen.height_in_pixels
        if self.panel_is_horizontal():
            py = 0 if self.panel_edge == "top" else sh - PANEL_HEIGHT
            self.panel.configure(x=0, y=py, width=sw, height=PANEL_HEIGHT)
            self.btn_widths = {self.ini_btn.id: 60, self.settings_btn.id: 80}
            self.ini_btn.configure(x=5, y=5, width=60, height=30)
            self.settings_btn.configure(x=sw - 190, y=5, width=80, height=30)
            self.clock.configure(x=sw - 105, y=5, width=100, height=30)
        else:
            px = 0 if self.panel_edge == "left" else sw - PANEL_WIDTH
            self.panel.configure(x=px, y=0, width=PANEL_WIDTH, height=sh)
            self.btn_widths = {self.ini_btn.id: VBTN_WIDTH, self.settings_btn.id: VBTN_WIDTH}
            self.ini_btn.configure(x=2, y=5, width=VBTN_WIDTH, height=30)
            self.settings_btn.configure(x=2, y=sh - 80, width=VBTN_WIDTH, height=30)
            self.clock.configure(x=2, y=sh - 45, width=VBTN_WIDTH, height=40)
        for i, btn in enumerate(self.taskbar_icons):
            bx, by = self.task_btn_pos(i)
            btn.configure(x=bx, y=by, width=self.task_btn_width())

    def raise_panel_if_pinned(self):
        """Закреплённый таскбар всегда выше окон."""
        if self.panel_pinned:
            self.panel.configure(stack_mode=X.Above)

    def refit_windows(self):
        """Подогнать окна под новую рабочую область (смена края / закрепление).

        Обычные окна не растягиваем и не перетайливаем: двигаем только если
        закреплённый таскбар перекрыл бы их, и уменьшаем лишь когда окно не
        помещается. Развёрнутые окна занимают рабочую область целиком.
        """
        ax, ay, aw, ah = self.work_area()
        for fid, state in self.managed_windows.items():
            frame = self.display.create_resource_object('window', fid)
            try:
                if state['maximized']:
                    frame.configure(x=ax, y=ay, width=aw, height=ah)
                    state['app'].configure(width=aw - BORDER_WIDTH * 2,
                                           height=ah - TITLEBAR_HEIGHT - BORDER_WIDTH * 2)
                    self.update_buttons_pos(fid, aw)
                elif self.panel_pinned:
                    g = frame.get_geometry()
                    nw, nh = min(g.width, aw), min(g.height, ah)
                    if (nw, nh) != (g.width, g.height):
                        frame.configure(width=nw, height=nh)
                        state['app'].configure(width=nw - BORDER_WIDTH * 2,
                                               height=nh - TITLEBAR_HEIGHT - BORDER_WIDTH * 2)
                        self.update_buttons_pos(fid, nw)
                    frame.configure(x=max(ax, min(g.x, ax + aw - nw)),
                                    y=max(ay, min(g.y, ay + ah - nh)))
            except error.BadWindow:
                pass

    def set_panel_edge(self, edge):
        if edge == self.panel_edge:
            return
        self.panel_edge = edge
        self.config["taskbar_edge"] = edge
        update_config(taskbar_edge=edge)
        self.layout_panel()
        self.panel.configure(stack_mode=X.Above)  # после переноса таскбар должен быть виден
        self.refit_windows()

    def toggle_pin(self):
        self.panel_pinned = not self.panel_pinned
        self.config["taskbar_pinned"] = self.panel_pinned
        update_config(taskbar_pinned=self.panel_pinned)
        self.raise_panel_if_pinned()
        self.refit_windows()

    # --- контекстное меню (ПКМ по таскбару) ---
    def _menu_label(self):
        return ("[x] " if self.panel_pinned else "[ ] ") + "Закрепить таскбар"

    def show_menu(self, rx, ry):
        label_img = render_text(self._menu_label())
        w = (label_img.width if label_img else len(self._menu_label()) * 6) + 20
        h = 28
        sw, sh = self.screen.width_in_pixels, self.screen.height_in_pixels
        x = min(rx, sw - w - 2)
        y = ry - h if ry + h > sh - 2 else ry  # у нижнего края открываем вверх
        self.menu_size = (w, h)
        self.menu_win = self.root.create_window(
            x, y, w, h, 1, self.screen.root_depth, X.InputOutput, X.CopyFromParent,
            background_pixel=0x2c3e50, border_pixel=0x3498db,
            override_redirect=True, event_mask=X.ExposureMask | X.ButtonPressMask)
        kw = {'foreground': 0xecf0f1, 'background': 0x2c3e50}
        if self.font:
            kw['font'] = self.font
        self.menu_gc = self.menu_win.create_gc(**kw)
        self.menu_win.map()
        self.menu_win.configure(stack_mode=X.Above)
        # Захват указателя: любой клик (в т.ч. мимо меню) придёт сюда и закроет его
        self.menu_win.grab_pointer(False, X.ButtonPressMask, X.GrabModeAsync,
                                   X.GrabModeAsync, X.NONE, X.NONE, X.CurrentTime)

    def draw_menu(self):
        if self.menu_win is None:
            return
        self.menu_win.clear_area(0, 0, 0, 0)
        img = render_text(self._menu_label())
        if img is not None:
            put_image(self.display, self.menu_win, self.menu_gc, 10, 4, img, self.screen.root_depth)
        else:  # нет TTF-шрифта: рисуем ASCII-часть встроенным шрифтом
            text = self._menu_label().encode("latin-1", "replace")
            self.menu_win.image_text(self.menu_gc, 10, 18, text)

    def close_menu(self):
        if self.menu_win is None:
            return
        try:
            self.display.ungrab_pointer(X.CurrentTime)
            self.menu_gc.free()
            self.menu_win.destroy()
        except error.XError:
            pass
        self.menu_win = self.menu_gc = None

    def handle_menu_click(self, ev):
        w, h = self.menu_size
        inside = ev.window == self.menu_win and 0 <= ev.event_x < w and 0 <= ev.event_y < h
        self.close_menu()
        if inside and ev.detail == 1:
            self.toggle_pin()

    # --- часы ---
    def _clock_loop(self, win_id):
        """Рисует время и дату в окне часов (своё соединение с X, свой поток)."""
        try:
            d = display.Display()
            win = d.create_resource_object('window', win_id)
            gc = win.create_gc(foreground=0xecf0f1, background=0x1a1a1a, font=d.open_font("fixed"))
        except Exception:
            return
        vertical = None
        while True:
            try:
                now = time.localtime()
                is_vertical = win.get_geometry().width < 60
                if is_vertical != vertical:  # ориентация сменилась — стираем старый текст
                    win.clear_area(0, 0, 0, 0)
                    vertical = is_vertical
                if is_vertical:  # узкая панель: время / день.месяц / год
                    win.image_text(gc, 10, 12, time.strftime("%H:%M", now).encode())
                    win.image_text(gc, 10, 25, time.strftime("%d.%m", now).encode())
                    win.image_text(gc, 13, 38, time.strftime("%Y", now).encode())
                else:
                    win.image_text(gc, 26, 12, time.strftime("%H:%M:%S", now).encode())
                    win.image_text(gc, 20, 26, time.strftime("%d.%m.%Y", now).encode())
                d.flush()
            except Exception:
                pass
            time.sleep(1.0 - (time.time() % 1.0) + 0.01)

    def logout(self):
        """Завершить сессию: процесс WM — это и есть сессия, выход = завершение процесса.
        Вызывается из потока настроек, поэтому os._exit, а не sys.exit
        (sys.exit в побочном потоке не остановил бы основной цикл событий)."""
        try:
            self.display.flush()
        except Exception:
            pass
        os._exit(0)

    def set_system_cursor(self):
        subprocess.run(["xsetroot", "-cursor_name", "left_ptr"])

    def spawn_terminal(self):
        for t in ["xterm", "alacritty", "kitty", "st"]:
            if shutil.which(t):
                subprocess.Popen([t])
                break
    
    def get_resize_edge(self, geom, x, y):
        dx = -1 if x < RESIZE_ZONE else (1 if x > geom.width - RESIZE_ZONE else 0)
        dy = -1 if y < RESIZE_ZONE else (1 if y > geom.height - RESIZE_ZONE else 0)
        return (dx, dy)

    def destroy_frame(self, frame_win):
        if frame_win.id in self.managed_windows:
            del self.managed_windows[frame_win.id]
        self.winlist.forget(frame_win.id)
        frame_win.destroy()

    def restore_minimized(self, frame):
        """Развернуть свёрнутое окно и убрать его кнопку с панели задач."""
        if frame not in self.minimized_frames:
            return
        frame.map()
        self.minimized_frames.remove(frame)
        for btn_id, data in list(self.taskbar_buttons.items()):
            if data['frame'] == frame:
                try:
                    self.display.create_resource_object('window', btn_id).destroy()
                except error.BadWindow:
                    pass
                del self.taskbar_buttons[btn_id]
                self.taskbar_icons = [b for b in self.taskbar_icons if b.id != btn_id]
        for i, btn in enumerate(self.taskbar_icons):
            bx, by = self.task_btn_pos(i)
            btn.configure(x=bx, y=by)

    def close_app(self, window):
        for fid, state in self.managed_windows.items():
            if state['app'] == window:
                self.destroy_frame(self.display.create_resource_object('window', fid))
                break

    def update_buttons_pos(self, frame_id, new_width):
        if frame_id in self.managed_windows:
            btns = self.managed_windows[frame_id]['btns']
            # Если окно узкое, пытаемся вместить кнопки
            if new_width < 120:
                btns['close'].configure(x=max(10, new_width - 45))
                btns['max'].unmap() # скрываем если места нет
                btns['min'].unmap()
            else:
                btns['close'].map()
                btns['max'].map()
                btns['min'].map()
                btns['close'].configure(x=new_width - 45)
                btns['max'].configure(x=new_width - 85)
                btns['min'].configure(x=new_width - 110)

    def decorate_and_map(self, window):
        try:
            attr = window.get_attributes()
            if attr.override_redirect:
                window.map()
                return

            try:
                name = window.get_wm_name()
                if name and "rofi" in name.lower():
                    window.map()
                    return
            except: pass
            if attr.override_redirect:
                window.map()
                return
            geom = window.get_geometry()
            fw, fh = geom.width + BORDER_WIDTH * 2, geom.height + TITLEBAR_HEIGHT + BORDER_WIDTH * 2
            frame = self.root.create_window((self.screen.width_in_pixels - fw) // 2, (self.screen.height_in_pixels - fh) // 2, fw, fh, 0, self.screen.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=FRAME_COLOR, event_mask=X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask | X.SubstructureRedirectMask | X.ExposureMask)
            window.reparent(frame, BORDER_WIDTH, TITLEBAR_HEIGHT)
            window.configure(x=BORDER_WIDTH, y=TITLEBAR_HEIGHT)
            frame.map()
            window.map()
            
            def make_btn(x, w, col, act):
                b = frame.create_window(x, 5, w, 15, 0, self.screen.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=col, event_mask=X.ButtonPressMask | X.ExposureMask)
                b.map()
                self.buttons[b.id] = {'action': act, 'app': window, 'frame': frame}
                return b

            self.managed_windows[frame.id] = {'app': window, 'maximized': False, 'geom': geom, 'frame_geom': None, 'btns': {'close': make_btn(fw-45, 40, 0xe74c3c, 'close'), 'max': make_btn(fw-85, 35, 0x95a5a6, 'maximize'), 'min': make_btn(fw-110, 20, 0xbdc3c7, 'minimize')}}
            if self.config.get("tiling"):
                self.apply_tiling()
                
            self.winlist.touch(frame.id)
            self.raise_panel_if_pinned()
        except error.BadWindow: pass
    
    def get_window_class(self, window):
        try: return window.get_wm_class()[1]
        except: return "Unknown"

    def run(self):
        self.spawn_terminal()
        self.event_loop()
    # Тайлинг
    def apply_tiling(self):
        windows = [win for win in self.managed_windows.items() if not win[1]['maximized']]
        count = len(windows)
        if count == 0: return
        for fid, state in self.managed_windows.items():
            frame = self.display.create_resource_object('window', fid)
            # очистка и перерендер кнопок
            for btn in state['btns'].values():
                btn.clear_area(0, 0, 0, 0, True)
            self.update_buttons_pos(fid, frame.get_geometry().width)
        ax, ay, aw, ah = self.work_area()
        w_width = aw // count
        for i, (fid, state) in enumerate(windows):
            frame = self.display.create_resource_object('window', fid)

            # применение новыъх размеров
            frame.configure(x=ax + i * w_width, y=ay, width=w_width, height=ah)
            state['app'].configure(width=w_width - BORDER_WIDTH*2,
                                   height=ah - TITLEBAR_HEIGHT - BORDER_WIDTH*2)
            
            # тут вызываем обновление кнопок, чтобы они пересчитали положение под новую ширину
            self.update_buttons_pos(fid, w_width)
    def handle_snap_and_swap(self, frame_win):
        if not self.config.get("tiling"): # ТОЛЬКО если тайлинг включен
            return
        geom = frame_win.get_geometry()
        for fid, state in self.managed_windows.items():
            if fid == frame_win.id: continue
            other_frame = self.display.create_resource_object('window', fid)
            og = other_frame.get_geometry()
            
            # Это если центр нашего окна попал в область другого окна
            if (geom.x + geom.width//2) > og.x and (geom.x + geom.width//2) < (og.x + og.width):
                # Меняем местами в словаре (сортируем по ключам для применения тайлинга)
                keys = list(self.managed_windows.keys())
                idx1, idx2 = keys.index(frame_win.id), keys.index(fid)
                keys[idx1], keys[idx2] = keys[idx2], keys[idx1]
                
                new_managed = {k: self.managed_windows[k] for k in keys}
                self.managed_windows = new_managed
                self.apply_tiling()
                break
            self.apply_tiling()
if __name__ == "__main__":
    InitioWM().run()
