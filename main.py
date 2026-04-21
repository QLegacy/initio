#!/usr/bin/env python3.11
import sys
import subprocess
import os

def check_setup():
    # Если установщик вернул 0 (успех), продолжаем
    result = subprocess.run([sys.executable, "install/libs.py"])
    if result.returncode != 0:
        print("Ошибка установки. Прерывание.")
        sys.exit(1)

# Если зависимостей нет, вызываем установщик
try:
    import pam, Xlib
except ImportError:
    check_setup()

# Теперь код продолжает работу
from initio.login import InitioDM
from initio.window import InitioWM

def main():
    print("Запуск дисплейного менеджера Initio...")
    dm = InitioDM()
    if dm.run():
        print("Логин успешен. Запуск оконного менеджера (InitioWM)...")
        wm = InitioWM()
        try:
            wm.run()
        except KeyboardInterrupt:
            print("\nСессия завершена.")
    else:
        print("Авторизация отменена.")

if __name__ == "__main__":
    main()
