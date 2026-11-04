"""
Модуль анімації запуску застосунку (Splash Screen).
Відображає сучасне вікно з плавною неоновою анімацією завантаження,
поки ініціалізуються важкі бібліотеки (CustomTkinter, RapidOCR, OpenCV).
"""
import os
import time
import threading
import tkinter as tk
from typing import Callable, Optional

class SplashScreen:
    def __init__(self, on_ready_callback: Optional[Callable[[], None]] = None):
        self.root = tk.Tk()
        self.on_ready_callback = on_ready_callback
        self.is_running = True
        self.anim_pos = 0.0
        self.anim_dir = 1.0

        # Безрамкове вікно поверх інших
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # Розміри та центрування
        w, h = 460, 250
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.configure(bg="#0f172a")

        # Зовнішня рамка з неоновою каймою
        border_frame = tk.Frame(self.root, bg="#38bdf8", bd=2)
        border_frame.pack(fill="both", expand=True)

        inner_frame = tk.Frame(border_frame, bg="#0f172a")
        inner_frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Логотип / Назва
        lbl_logo = tk.Label(
            inner_frame,
            text="⚡ AutoFlow Assistant",
            font=("Segoe UI", 19, "bold"),
            fg="#38bdf8",
            bg="#0f172a"
        )
        lbl_logo.pack(pady=(28, 4))

        lbl_sub = tk.Label(
            inner_frame,
            text="Розумна автоматизація пошти, документів та Smart Vision",
            font=("Segoe UI", 10),
            fg="#94a3b8",
            bg="#0f172a"
        )
        lbl_sub.pack(pady=(0, 24))

        # Полотно анімованого прогрес-бару
        self.canvas_w = 380
        self.canvas_h = 6
        self.canvas = tk.Canvas(
            inner_frame,
            width=self.canvas_w,
            height=self.canvas_h,
            bg="#1e293b",
            highlightthickness=0
        )
        self.canvas.pack(pady=(0, 16))

        # Бігунок прогресу (градієнтний неоновий повзунок)
        self.runner_len = 90
        self.runner = self.canvas.create_rectangle(
            0, 0, self.runner_len, self.canvas_h,
            fill="#38bdf8",
            outline="#818cf8"
        )

        # Статусний текст
        self.lbl_status = tk.Label(
            inner_frame,
            text="Ініціалізація компонентів...",
            font=("Segoe UI", 10, "bold"),
            fg="#cbd5e1",
            bg="#0f172a"
        )
        self.lbl_status.pack(pady=(0, 18))

        # Створюємо мітку готовності для start.bat
        try:
            os.makedirs("logs", exist_ok=True)
            with open("logs/.ready", "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except Exception:
            pass

        self._animate()

    def set_status(self, text: str):
        """Оновлює повідомлення поточного етапу завантаження."""
        try:
            self.lbl_status.config(text=text)
            self.root.update_idletasks()
        except Exception:
            pass

    def _animate(self):
        """Плавна анімація неонового бігунка прогресу."""
        if not self.is_running:
            return

        # Переміщення бігунка вперед-назад
        speed = 5.5
        self.anim_pos += speed * self.anim_dir

        max_pos = self.canvas_w - self.runner_len
        if self.anim_pos >= max_pos:
            self.anim_pos = max_pos
            self.anim_dir = -1.0
        elif self.anim_pos <= 0:
            self.anim_pos = 0
            self.anim_dir = 1.0

        try:
            self.canvas.coords(
                self.runner,
                self.anim_pos, 0,
                self.anim_pos + self.runner_len, self.canvas_h
            )
            self.root.after(20, self._animate)
        except Exception:
            pass

    def close(self):
        """Закриває вікно завантаження."""
        self.is_running = False
        try:
            self.root.destroy()
        except Exception:
            pass


def run_with_splash():
    """
    Запускає SplashScreen, у фоні імпортує важкі бібліотеки AutoFlowApp,
    оновлює статусні повідомлення та плавно передає керування основному вікну.
    """
    splash = SplashScreen()

    app_instance = [None]
    error_box = [None]

    def load_heavy_app():
        try:
            time.sleep(0.15)
            splash.set_status("🔍 Завантаження AI Vision та OCR рушіїв...")
            time.sleep(0.2)

            from app import AutoFlowApp
            splash.set_status("⚡ Ініціалізація інтерфейсу користувача...")
            time.sleep(0.15)

            app = AutoFlowApp()
            app_instance[0] = app
            splash.set_status("✅ Готово! Відкриття програми...")
            time.sleep(0.2)
        except Exception as e:
            import traceback
            error_box[0] = (str(e), traceback.format_exc())

    loader_thread = threading.Thread(target=load_heavy_app, daemon=True)
    loader_thread.start()

    def check_loaded():
        if error_box[0] is not None:
            err, tb = error_box[0]
            splash.close()
            try:
                os.makedirs("logs", exist_ok=True)
                with open("logs/crash.log", "a", encoding="utf-8") as f:
                    f.write(f"\n[SPLASH ERROR] {tb}\n")
            except Exception:
                pass
            import tkinter.messagebox as mb
            mb.showerror("Помилка запуску", f"Не вдалося запустити AutoFlow Assistant:\n\n{err}\n\nДеталі у logs/crash.log")
            return

        if app_instance[0] is not None:
            app = app_instance[0]
            splash.close()
            # Відображаємо та активуємо головне вікно
            app.deiconify()
            app.lift()
            app.focus_force()
            app.mainloop()
        else:
            splash.root.after(40, check_loaded)

    splash.root.after(50, check_loaded)
    splash.root.mainloop()
