import tkinter as tk
from tkinter import messagebox
import pam
import os

class InitioDM:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Initio Login")
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg="#2c3e50")
        
        self.success = False # Это мы потом изменим и отправим в главный скрипт

        frame = tk.Frame(self.root, bg="#2c3e50")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(frame, text="Initio", font=("Helvetica", 36, "bold"), bg="#2c3e50", fg="#ecf0f1").pack(pady=30)

        tk.Label(frame, text="Пользователь:", font=("Helvetica", 14), bg="#2c3e50", fg="#bdc3c7").pack(anchor="w")
        self.username_entry = tk.Entry(frame, font=("Helvetica", 14), width=20)
        self.username_entry.pack(pady=5)
        self.username_entry.insert(0, os.environ.get('USER', ''))

        tk.Label(frame, text="Пароль:", font=("Helvetica", 14), bg="#2c3e50", fg="#bdc3c7").pack(anchor="w")
        self.password_entry = tk.Entry(frame, font=("Helvetica", 14), width=20, show="*")
        self.password_entry.pack(pady=5)
        self.password_entry.bind('<Return>', lambda e: self.verify())
        self.password_entry.focus()

        tk.Button(frame, text="Войти", font=("Helvetica", 14, "bold"), bg="#2980b9", fg="white",
                  relief="flat", cursor="hand2", command=self.verify).pack(pady=20, fill="x")
        
        tk.Button(frame, text="Выйти", font=("Helvetica", 12), bg="#c0392b", fg="white",
                  relief="flat", cursor="hand2", command=self.root.quit).pack(fill="x")

    def verify(self):
        username = self.username_entry.get()
        password = self.password_entry.get()
        auth = pam.pam()
        
        if auth.authenticate(username, password):
            self.success = True
            self.root.quit()    # Останавливаем цикл Tkinter
            self.root.destroy() # Уничтожаем графическое окно входа
        else:
            messagebox.showerror("Ошибка", "Неверное имя пользователя или пароль.")

    def run(self):
        self.root.mainloop()
        return self.success
