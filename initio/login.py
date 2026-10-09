import tkinter as tk
from tkinter import font as tkfont
import pam
import os
import socket
import threading
import time
import signal

MAX_ATTEMPTS = 5          # после скольких неудачных попыток включаем блокировку
LOCKOUT_SECONDS = 30       # длительность блокировки
PAM_SERVICE = "login"      # имя PAM-сервиса


class InitioDM:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Initio Login")
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg="#2c3e50")
        self.root.resizable(False, False)

        self.success = False       # результат отдаём в main.py
        self.attempts = 0
        self.locked_until = 0.0
        self.authenticating = False

        # Аккуратно перехватываем закрытие окна и Ctrl+C/сигналы,
        # чтобы не оставить процесс "висящим" без DISPLAY
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.bind('<Escape>', lambda e: self._quit())
        try:
            signal.signal(signal.SIGTERM, lambda *_: self._quit())
        except (ValueError, OSError):
            pass  # не в главном потоке / не поддерживается платформой

        frame = tk.Frame(self.root, bg="#2c3e50")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(frame, text="Initio", font=("Helvetica", 36, "bold"),
                 bg="#2c3e50", fg="#ecf0f1").pack(pady=(0, 5))

        # Имя хоста и часы — обычные элементы экрана входа
        hostname = socket.gethostname()
        tk.Label(frame, text=hostname, font=("Helvetica", 11),
                 bg="#2c3e50", fg="#7f8c8d").pack(pady=(0, 20))

        self.clock_label = tk.Label(frame, text="", font=("Helvetica", 12),
                                     bg="#2c3e50", fg="#7f8c8d")
        self.clock_label.pack(pady=(0, 15))
        self._tick_clock()

        tk.Label(frame, text="Пользователь:", font=("Helvetica", 14),
                 bg="#2c3e50", fg="#bdc3c7").pack(anchor="w")
        self.username_entry = tk.Entry(frame, font=("Helvetica", 14), width=22)
        self.username_entry.pack(pady=5)
        self.username_entry.insert(0, os.environ.get('USER', ''))
        # Enter в поле логина -> переходим к паролю, а не пытаемся войти вслепую
        self.username_entry.bind('<Return>', lambda e: self.password_entry.focus_set())

        tk.Label(frame, text="Пароль:", font=("Helvetica", 14),
                 bg="#2c3e50", fg="#bdc3c7").pack(anchor="w")
        self.password_entry = tk.Entry(frame, font=("Helvetica", 14), width=22, show="*")
        self.password_entry.pack(pady=5)
        self.password_entry.bind('<Return>', lambda e: self.verify())
        self.password_entry.focus()

        # Статус-строка вместо всплывающих messagebox — меньше отвлекает
        # и больше похоже на настоящий экран входа
        self.status_label = tk.Label(frame, text="", font=("Helvetica", 11),
                                      bg="#2c3e50", fg="#e74c3c", wraplength=260,
                                      justify="center")
        self.status_label.pack(pady=(8, 0))

        self.login_button = tk.Button(
            frame, text="Войти", font=("Helvetica", 14, "bold"),
            bg="#2980b9", fg="white", relief="flat", cursor="hand2",
            command=self.verify)
        self.login_button.pack(pady=(15, 5), fill="x")

        tk.Button(frame, text="Выйти", font=("Helvetica", 12), bg="#c0392b",
                  fg="white", relief="flat", cursor="hand2",
                  command=self._quit).pack(fill="x")

    # ------------------------------------------------------------------ #
    def _tick_clock(self):
        if not self.root.winfo_exists():
            return
        self.clock_label.config(text=time.strftime("%H:%M:%S — %d.%m.%Y"))
        self.root.after(1000, self._tick_clock)

    def _set_status(self, text, color="#e74c3c"):
        self.status_label.config(text=text, fg=color)

    def _set_inputs_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.username_entry.config(state=state)
        self.password_entry.config(state=state)
        self.login_button.config(
            state=state,
            text="Войти" if enabled else "Проверка...")

    def _quit(self):
        self.success = False
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ #
    def verify(self):
        if self.authenticating:
            return  # защита от повторного клика/Enter во время проверки

        now = time.time()
        if now < self.locked_until:
            remaining = int(self.locked_until - now) + 1
            self._set_status(f"Слишком много попыток. Подождите {remaining} с.")
            return

        username = self.username_entry.get().strip()
        password = self.password_entry.get()

        if not username or not password:
            self._set_status("Введите имя пользователя и пароль.")
            return

        self.authenticating = True
        self._set_inputs_enabled(False)
        self._set_status("Проверка...", color="#bdc3c7")

        # PAM-обращение может занять заметное время (LDAP/сетевые модули и т.п.),
        # поэтому проверяем в отдельном потоке, чтобы не подвешивать интерфейс
        threading.Thread(
            target=self._authenticate_worker,
            args=(username, password),
            daemon=True,
        ).start()

    def _authenticate_worker(self, username, password):
        try:
            auth = pam.pam()
            ok = auth.authenticate(username, password, service=PAM_SERVICE)
        except Exception:
            ok = False
        # Возвращаемся в главный поток Tkinter, прежде чем трогать виджеты
        self.root.after(0, self._on_auth_result, ok)

    def _on_auth_result(self, ok):
        self.authenticating = False
        if ok:
            self.success = True
            self.root.quit()
            self.root.destroy()
            return

        self.attempts += 1
        self.password_entry.delete(0, tk.END)  # не оставляем пароль в поле
        self._set_inputs_enabled(True)

        if self.attempts >= MAX_ATTEMPTS:
            self.locked_until = time.time() + LOCKOUT_SECONDS
            self.attempts = 0
            self._set_status(f"Слишком много попыток. Блокировка на {LOCKOUT_SECONDS} с.")
            self._set_inputs_enabled(False)
            self.root.after(LOCKOUT_SECONDS * 1000, self._unlock)
        else:
            left = MAX_ATTEMPTS - self.attempts
            self._set_status(f"Неверное имя пользователя или пароль. Осталось попыток: {left}")
            self.password_entry.focus_set()

    def _unlock(self):
        self._set_inputs_enabled(True)
        self._set_status("")
        self.password_entry.focus_set()

    def run(self):
        self.root.mainloop()
        return self.success
