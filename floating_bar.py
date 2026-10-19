"""
Плаваюча панель керування записом дій (Always-on-top Mini Toolbar).
Дозволяє під час запису:
- додавати точки очікування/схвалення (F8)
- ставити запис на паузу / відновлювати (F9), щоб не записувати зайві ручні дії
- завершити запис (F10)
"""
import customtkinter as ctk
from typing import Callable, Optional

class FloatingRecordingBar(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        on_add_checkpoint: Callable[[], None],
        on_toggle_pause: Callable[[], None],
        on_stop_recording: Callable[[], None],
        on_position_changed: Optional[Callable[[int, int, int, int], None]] = None
    ):
        super().__init__(master)
        
        self.on_add_checkpoint = on_add_checkpoint
        self.on_toggle_pause = on_toggle_pause
        self.on_stop_recording = on_stop_recording
        self.on_position_changed = on_position_changed
        self.is_paused = False
        
        # Вікно поверх усіх інших
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        
        # Розмір та позиція
        screen_w = self.winfo_screenwidth()
        bar_w = 600
        bar_h = 56
        pos_x = screen_w - bar_w - 30
        pos_y = 35
        self.geometry(f"{bar_w}x{bar_h}+{pos_x}+{pos_y}")
        
        # Контейнер із рамкою
        self.container = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color=("#1e293b", "#0f172a"),
            border_width=2,
            border_color="#ef4444"
        )
        self.container.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Перетягування панелі мишкою
        self.container.bind("<ButtonPress-1>", self._start_drag)
        self.container.bind("<B1-Motion>", self._on_drag)
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Індикатор стану
        self.lbl_record = ctk.CTkLabel(
            self.container,
            text="🔴 ЗАПИС",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#ef4444"
        )
        self.lbl_record.pack(side="left", padx=(14, 8), pady=8)
        self.lbl_record.bind("<ButtonPress-1>", self._start_drag)
        self.lbl_record.bind("<B1-Motion>", self._on_drag)

        # 1. Кнопка: ТОЧКА СХВАЛЕННЯ (F8)
        self.btn_checkpoint = ctk.CTkButton(
            self.container,
            text="⏸ Точка схвалення (F8)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#f59e0b",
            hover_color="#d97706",
            text_color="#000000",
            width=160,
            height=34,
            corner_radius=8,
            command=self._handle_checkpoint_click
        )
        self.btn_checkpoint.pack(side="left", padx=5, pady=8)

        # 2. Кнопка: ПАУЗА / ПРОДОВЖИТИ ЗАПИС (F9)
        self.btn_pause = ctk.CTkButton(
            self.container,
            text="⏸ Пауза запису (F9)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            text_color="#ffffff",
            width=150,
            height=34,
            corner_radius=8,
            command=self.on_toggle_pause
        )
        self.btn_pause.pack(side="left", padx=5, pady=8)

        # 3. Кнопка: ЗАВЕРШИТИ (F10)
        self.btn_stop = ctk.CTkButton(
            self.container,
            text="⏹ Завершити (F10)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            text_color="#ffffff",
            width=135,
            height=34,
            corner_radius=8,
            command=self.on_stop_recording
        )
        self.btn_stop.pack(side="left", padx=(5, 12), pady=8)
        
        self.after(100, self._update_bounds)

    def _start_drag(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_drag(self, event):
        x = self.winfo_x() + (event.x - self._drag_start_x)
        y = self.winfo_y() + (event.y - self._drag_start_y)
        self.geometry(f"+{x}+{y}")
        self._update_bounds()

    def _update_bounds(self):
        try:
            x = self.winfo_rootx()
            y = self.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            if self.on_position_changed and w > 10 and h > 10:
                self.on_position_changed(x, y, x + w, y + h)
        except Exception:
            pass

    def _handle_checkpoint_click(self):
        self.on_add_checkpoint()
        orig_text = self.btn_checkpoint.cget("text")
        self.btn_checkpoint.configure(text="✅ Додано точку!", fg_color="#10b981")
        self.after(1200, lambda: self.btn_checkpoint.configure(text=orig_text, fg_color="#f59e0b"))

    def set_pause_state(self, is_paused: bool):
        """Оновлює візуальний стан панелі при увімкненні чи вимкненні паузи."""
        self.is_paused = is_paused
        if is_paused:
            self.lbl_record.configure(text="⏸ ПАУЗА", text_color="#f59e0b")
            self.container.configure(border_color="#f59e0b")
            self.btn_pause.configure(
                text="▶ Продовжити (F9)",
                fg_color="#10b981",
                hover_color="#059669",
                text_color="#ffffff"
            )
            self.btn_checkpoint.configure(state="disabled")
        else:
            self.lbl_record.configure(text="🔴 ЗАПИС", text_color="#ef4444")
            self.container.configure(border_color="#ef4444")
            self.btn_pause.configure(
                text="⏸ Пауза запису (F9)",
                fg_color="#334155",
                hover_color="#475569",
                text_color="#ffffff"
            )
            self.btn_checkpoint.configure(state="normal")
        self._update_bounds()

    def show_feedback(self, text: str):
        orig_text = self.btn_checkpoint.cget("text")
        self.btn_checkpoint.configure(text=text, fg_color="#10b981")
        self.after(1200, lambda: self.btn_checkpoint.configure(text=orig_text, fg_color="#f59e0b"))
