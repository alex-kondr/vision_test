"""
Головна точка входу для запуску програми AutoFlow Assistant.
Підтримує безконсольний запуск (pythonw) з безпечною обробкою stdout/stderr
та виводом критичних помилок запуску у вікно повідомлення.
"""
import sys
import os
import traceback

# Безпечне перенаправлення для pythonw (коли stdout/stderr рівні None)
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

def main():
    try:
        from app import AutoFlowApp
        app = AutoFlowApp()
        app.mainloop()
    except Exception as e:
        err_msg = traceback.format_exc()
        try:
            os.makedirs("logs", exist_ok=True)
            with open("logs/crash.log", "a", encoding="utf-8") as f:
                f.write(err_msg + "\n")
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Помилка запуску AutoFlow Assistant",
                f"Сталася критична помилка під час запуску програми:\n\n{e}\n\nПовний опис збережено у файлі logs/crash.log"
            )
            root.destroy()
        except Exception:
            pass

if __name__ == "__main__":
    main()
