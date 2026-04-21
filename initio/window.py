import os
import subprocess
import shutil
from Xlib import display, X, error, protocol, XK

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
        self.resize_window = None
        self.resize_start_geom = None
        self.resize_edge = None

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
        except:
            self.font = None
        
        self.set_system_cursor()
        self.event_loop()

    def event_loop(self):
        while True:
            ev = self.display.next_event()
            self.color_counter += 1
            new_color = (self.color_counter % 255) << 16 | 0x3498db
            self.ini_btn.change_attributes(background_pixel=new_color)
            self.ini_btn.clear_area(0, 0, 0, 0, True)

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
                    ev.window.fill_rectangle(self.gc_grey, 2, 2, 96, 26)
                    ev.window.image_text(self.gc_grey, 10, 20, app_name[:10])

            elif ev.type == X.KeyPress:
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
                    if ev.value_mask & X.CWWidth: args['width'] = ev.width
                    if ev.value_mask & X.CWHeight: args['height'] = ev.height
                else:
                    args = {k: getattr(ev, k) for k in ['x', 'y', 'width', 'height'] if ev.value_mask & (1 << (list(['x','y','width','height']).index(k)))}
                try: window.configure(**args)
                except error.BadWindow: pass

            elif ev.type == X.ButtonPress:
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
                
                if ev.window.id in self.taskbar_buttons:
                    data = self.taskbar_buttons[ev.window.id]
                    frame_to_restore = data['frame']
                    if frame_to_restore in self.minimized_frames:
                        frame_to_restore.map()
                        self.minimized_frames.remove(frame_to_restore)
                        ev.window.destroy()
                        del self.taskbar_buttons[ev.window.id]
                        self.taskbar_icons = [b for b in self.taskbar_icons if b.id != ev.window.id]
                        for i, btn in enumerate(self.taskbar_icons): btn.configure(x=70 + (i * 105))
                    continue

                if ev.window.id in self.buttons:
                    b = self.buttons[ev.window.id]
                    if b['action'] == 'close': self.close_app(b['app'])
                    elif b['action'] == 'minimize':
                        b['frame'].unmap()
                        self.minimized_frames.append(b['frame'])
                        app_name = self.get_window_class(b['app'])
                        task_btn = self.panel.create_window(70 + (len(self.minimized_frames)-1)*105, 5, 100, 30, 0, self.screen.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=0x34495e, event_mask=X.ButtonPressMask | X.ExposureMask)
                        task_btn.map()
                        self.taskbar_buttons[task_btn.id] = {'frame': b['frame'], 'name': app_name}
                        self.taskbar_icons.append(task_btn)
                    elif b['action'] == 'maximize':
                        state = self.managed_windows[b['frame'].id]
                        if not state['maximized']:
                            state['frame_geom'] = b['frame'].get_geometry()
                            state['geom'] = b['app'].get_geometry()
                            root_g = self.root.get_geometry()
                            b['frame'].configure(x=0, y=0, width=root_g.width, height=root_g.height - PANEL_HEIGHT)
                            b['app'].configure(width=root_g.width - BORDER_WIDTH * 2, height=root_g.height - PANEL_HEIGHT - TITLEBAR_HEIGHT - BORDER_WIDTH * 2)
                            state['maximized'] = True
                            self.update_buttons_pos(b['frame'].id, root_g.width)
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
                    self.drag_start, self.drag_window = (ev.root_x, ev.root_y), ev.window
                    geom = ev.window.get_geometry()
                    self.drag_window_start_pos = (geom.x, geom.y)

            elif ev.type == X.MotionNotify:
                if self.drag_window:
                    dx, dy = ev.root_x - self.drag_start[0], ev.root_y - self.drag_start[1]
                    self.drag_window.configure(x=self.drag_window_start_pos[0] + dx, y=self.drag_window_start_pos[1] + dy)
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
                    nw, nh = max(50, nw), max(50, nh)
                    self.resize_window.configure(x=nx, y=ny, width=nw, height=nh)
                    self.managed_windows[self.resize_window.id]['app'].configure(width=nw - BORDER_WIDTH * 2, height=nh - TITLEBAR_HEIGHT - BORDER_WIDTH * 2)
                    self.update_buttons_pos(self.resize_window.id, nw)

            elif ev.type == X.ButtonRelease:
                if self.resize_window or self.drag_window:
                    self.display.ungrab_pointer(X.CurrentTime)
                    self.resize_window = self.drag_window = None

    def create_panel(self):
        panel = self.root.create_window(0, self.screen.height_in_pixels - PANEL_HEIGHT, self.screen.width_in_pixels, PANEL_HEIGHT, 0, self.screen.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=0x1a1a1a, event_mask=X.ButtonPressMask | X.ExposureMask)
        self.ini_btn = panel.create_window(5, 5, 60, 30, 0, self.screen.root_depth, X.InputOutput, X.CopyFromParent, background_pixel=0x3498db, event_mask=X.ButtonPressMask)
        panel.map()
        self.ini_btn.map()
        return panel

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
        frame_win.destroy()

    def close_app(self, window):
        for fid, state in self.managed_windows.items():
            if state['app'] == window:
                self.destroy_frame(self.display.create_resource_object('window', fid))
                break

    def update_buttons_pos(self, frame_id, new_width):
        if frame_id in self.managed_windows:
            btns = self.managed_windows[frame_id]['btns']
            btns['close'].configure(x=new_width - 45)
            btns['max'].configure(x=new_width - 85)
            btns['min'].configure(x=new_width - 110)

    def decorate_and_map(self, window):
        try:
            attr = window.get_attributes()
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
            self.panel.configure(stack_mode=X.Above)
        except error.BadWindow: pass
    
    def get_window_class(self, window):
        try: return window.get_wm_class()[1]
        except: return "Unknown"

    def run(self):
        self.spawn_terminal()
        while True: self.display.next_event()

if __name__ == "__main__":
    InitioWM().run()
