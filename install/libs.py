#!/usr/bin/env python3
"""Установщик зависимостей Initio и регистрация X-сессии.

Возвращает 0 при успехе, иначе 1 (main.py смотрит на код возврата).
"""
import os
import shutil
import subprocess
import sys
import tempfile

SESSION_FILE = "/usr/share/xsessions/initio.desktop"

# Arch: tkinter входит в пакет "tk", отдельного python-tk нет.
PACMAN_PKGS = ["python-pip", "tk", "rofi", "python-pam", "python-xlib", "python-pillow"]
APT_PKGS = ["python3-pip", "python3-tk", "rofi", "python3-pam", "python3-xlib", "python3-pil"]

# Имена на PyPI. Пакет "pam" — это не то: нужен именно python-pam.
PIP_PKGS = {"pam": "python-pam", "Xlib": "python-xlib", "PIL": "pillow"}


def run(cmd):
    print("[*] " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def install_system_packages():
    if shutil.which("pacman"):
        run(["sudo", "pacman", "-S", "--needed", "--noconfirm"] + PACMAN_PKGS)
    elif shutil.which("apt"):
        run(["sudo", "apt", "update"])
        run(["sudo", "apt", "install", "-y"] + APT_PKGS)
    else:
        print("[!] Не найден pacman или apt: поставьте зависимости вручную "
              "(python-xlib, python-pam, pillow, tkinter, rofi).")


def install_missing_pip_packages():
    """pip нужен только если после системных пакетов модуль всё ещё не импортируется."""
    for module, pip_name in PIP_PKGS.items():
        check = subprocess.run([sys.executable, "-c", f"import {module}"],
                               capture_output=True)
        if check.returncode == 0:
            continue
        cmd = [sys.executable, "-m", "pip", "install", pip_name]
        try:
            run(cmd + ["--break-system-packages"])
        except subprocess.CalledProcessError:
            run(cmd)  # старый pip не знает флага --break-system-packages


def register_session():
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    desktop_entry = f"""[Desktop Entry]
Name=Initio
Comment=Initio window manager
Exec={sys.executable} {main_py}
Type=Application
"""
    with tempfile.NamedTemporaryFile("w", suffix=".desktop", delete=False) as f:
        f.write(desktop_entry)
        tmp = f.name
    try:
        run(["sudo", "install", "-Dm644", tmp, SESSION_FILE])
    finally:
        os.unlink(tmp)
    print(f"[+] Файл сессии создан: {SESSION_FILE}")


def install():
    try:
        install_system_packages()
        install_missing_pip_packages()
    except subprocess.CalledProcessError as e:
        print(f"[!] Ошибка установки зависимостей: {e}")
        return 1
    print("[+] ЗАВИСИМОСТИ УСТАНОВЛЕНЫ!")

    try:
        register_session()
    except (subprocess.CalledProcessError, OSError) as e:
        # Сессия не зарегистрирована, но зависимости стоят — это не повод валить запуск
        print(f"[!] Ошибка создания сессии: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(install())
