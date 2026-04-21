#!/usr/bin/env python3
import subprocess, sys, shutil
import os
def install():
    pm = "pacman" if shutil.which("pacman") else "apt" if shutil.which("apt") else None
    
    # Системные команды
    if pm == "pacman":
        subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "python-pip", "python-tk", "rofi", "python-pam", "python-xlib"], check=True)
    else:
        subprocess.run(["sudo", "apt", "update"], check=True)
        subprocess.run(["sudo", "apt", "install", "-y", "python3-pip", "python3-tk", "rofi", "python3-pam", "python3-xlib"], check=True)
    
    subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "pam", "python-xlib"], check=True)
    
    print("[+] УСТАНОВКА ЗАВЕРШЕНА УСПЕШНО!")
    print("[+] СОЗДАЁМ ФАЙЛ СЕССИИ ДЛЯ ВАШЕГО ВХОДА!")
    
    # Создаем файл сессии для логин-менеджера
    session_file = "/usr/share/xsessions/initio.desktop"
    desktop_entry = f"""[Desktop Entry]
Name=Initio
Exec={os.path.abspath("main.py")}
Type=Application
"""
    try:
        with open("initio.tmp", "w") as f:
            f.write(desktop_entry)
        subprocess.run(["sudo", "mv", "initio.tmp", session_file], check=True)
        print(f"[+] Файл сессии создан: {session_file}")
    except Exception as e:
        print(f"[!] Ошибка создания сессии: {e}")
    sys.exit(0) # Отдаем статус успеха главному скрипту

if __name__ == "__main__":
    install()
