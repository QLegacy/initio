import json
import tkinter as tk
from tkinter import messagebox
import os
import sys
import threading
CONFIG_FILE = "config.json"

def load_config():
    default = {"tiling": False}
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f: json.dump(default, f)
        return default
    with open(CONFIG_FILE, "r") as f: return json.load(f)

def open_settings(wm_instance):
    # Оборачиваем весь GUI в функцию, которая будет работать в потоке
    def run_gui():
        root = tk.Tk()
        root.title("Настройки Initio")
        tiling_var = tk.BooleanVar(value=load_config().get("tiling", False))
        
        tk.Checkbutton(root, text="Включить тайлинг", variable=tiling_var).pack(pady=10, padx=20)
        
        def save():
            with open(CONFIG_FILE, "w") as f:
                json.dump({"tiling": tiling_var.get()}, f)
            if messagebox.askyesno("Рестарт", "Настройки сохранены. Перезапустить?"):
                os.execv(sys.executable, ['python'] + sys.argv)
        
        tk.Button(root, text="Сохранить и применить", command=save).pack(pady=5)
        root.mainloop()

    # запускаем в потоке!
    threading.Thread(target=run_gui, daemon=True).start()
