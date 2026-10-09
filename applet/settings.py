import json
import tkinter as tk
from tkinter import messagebox, filedialog
import os
import threading

from applet.wallpaper import apply_wallpaper

# Конфиг лежит в домашней папке, а не рядом с cwd: иначе при запуске из менеджера входа
# (другая рабочая папка) читался бы/писался совсем другой файл.
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "initio")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_CONFIG = {"tiling": False, "wallpaper": "",
                  "taskbar_edge": "bottom", "taskbar_pinned": False}

_settings_open = False  # не даём открыть несколько окон настроек


def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}
    return {**DEFAULT_CONFIG, **data}  # недостающие ключи берём из default


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:  # пишем во временный файл и подменяем, чтобы не получить обрезанный конфиг
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_FILE)


def update_config(**changes):
    """Изменить только указанные ключи, остальное берём свежим с диска.

    Нельзя записывать целиком устаревший словарь из памяти: он затёр бы
    настройки, сохранённые окном настроек (например, выключенный тайлинг).
    """
    cfg = load_config()
    cfg.update(changes)
    save_config(cfg)
    return cfg


def open_settings(wm_instance):
    global _settings_open
    if _settings_open:
        return
    _settings_open = True

    # Весь GUI работает в отдельном потоке, чтобы не блокировать WM
    def run_gui():
        global _settings_open
        try:
            root = tk.Tk()
            root.title("Настройки Initio")
            cfg = load_config()
            tiling_var = tk.BooleanVar(value=cfg["tiling"])
            wall_var = tk.StringVar(value=cfg["wallpaper"])

            tk.Checkbutton(root, text="Включить тайлинг",
                           variable=tiling_var).pack(pady=(10, 5), padx=20, anchor="w")

            # --- Обои ---
            wall_frame = tk.LabelFrame(root, text="Обои")
            wall_frame.pack(padx=20, pady=5, fill="x")
            tk.Entry(wall_frame, textvariable=wall_var, width=40).pack(
                side="left", padx=5, pady=5, fill="x", expand=True)

            def browse():
                path = filedialog.askopenfilename(
                    parent=root, title="Выберите изображение для обоев",
                    filetypes=[("Изображения", "*.png *.jpg *.jpeg *.bmp *.webp"),
                               ("Все файлы", "*.*")])
                if path:
                    wall_var.set(path)

            tk.Button(wall_frame, text="Обзор...", command=browse).pack(
                side="left", padx=5, pady=5)

            def save():
                new_cfg = load_config()
                tiling_changed = new_cfg["tiling"] != tiling_var.get()
                new_cfg["tiling"] = tiling_var.get()
                new_cfg["wallpaper"] = wall_var.get().strip()
                save_config(new_cfg)
                try:
                    wm_instance.config.update(new_cfg)  # чтобы WM не работал со старыми значениями
                except Exception:
                    pass

                # Обои применяются сразу, без перезапуска
                if new_cfg["wallpaper"]:
                    ok, msg = apply_wallpaper(new_cfg["wallpaper"])
                    if not ok:
                        messagebox.showerror("Обои", msg, parent=root)

                # Для применения тайлинга нужен новый вход в сессию
                if tiling_changed and messagebox.askyesno(
                        "Выход", "Настройки сохранены. Чтобы применить тайлинг, нужно "
                                 "перезайти в сессию. Выйти сейчас?", parent=root):
                    wm_instance.logout()

            tk.Button(root, text="Сохранить и применить", command=save).pack(pady=10)
            root.mainloop()
        finally:
            _settings_open = False

    threading.Thread(target=run_gui, daemon=True).start()
