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
        on_position_changed: Optional[Callable[[int, int, int, int], None]] = None,
        on_set_target_type: Optional[Callable[[str], None]] = None,
        on_add_scroll: Optional[Callable[[], None]] = None,
        on_add_file_selection: Optional[Callable[[], None]] = None
    ):
        super().__init__(master)
        
        self.on_add_checkpoint = on_add_checkpoint
        self.on_toggle_pause = on_toggle_pause
        self.on_stop_recording = on_stop_recording
        self.on_position_changed = on_position_changed
        self.on_set_target_type = on_set_target_type
        self.on_add_scroll = on_add_scroll
        self.on_add_file_selection = on_add_file_selection
        self.is_paused = False
        self.current_target_mode = "element"  # 'element', 'area'
        
        # Вікно поверх усіх інших
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        
        # Розмір та позиція
        screen_w = self.winfo_screenwidth()
        bar_w = 840
        bar_h = 56
        pos_x = max(10, screen_w - bar_w - 20)
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
        self.lbl_record.pack(side="left", padx=(10, 5), pady=8)
        self.lbl_record.bind("<ButtonPress-1>", self._start_drag)
        self.lbl_record.bind("<B1-Motion>", self._on_drag)

        # Перемикач типу кліку: ЕЛЕМЕНТ / ОБЛАСТЬ
        self.btn_mode_element = ctk.CTkButton(
            self.container,
            text="🔘 Кнопка/Елемент",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            width=115,
            height=32,
            corner_radius=6,
            command=lambda: self._set_mode("element")
        )
        self.btn_mode_element.pack(side="left", padx=2, pady=8)

        self.btn_mode_area = ctk.CTkButton(
            self.container,
            text="🔲 Клік по області",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="#334155",
            hover_color="#475569",
            width=115,
            height=32,
            corner_radius=6,
            command=lambda: self._set_mode("area")
        )
        self.btn_mode_area.pack(side="left", padx=2, pady=8)

        # Кнопка: ПРОКРУТКА ДО САМОГО НИЗУ
        self.btn_scroll = ctk.CTkButton(
            self.container,
            text="📜 До низу",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#0891b2",
            hover_color="#0e7490",
            text_color="#ffffff",
            width=85,
            height=32,
            corner_radius=6,
            command=self._handle_scroll_click
        )
        self.btn_scroll.pack(side="left", padx=2, pady=8)

        # Кнопка: ВИБІР ФАЙЛУ (З МЕНЮ)
        self.btn_file = ctk.CTkButton(
            self.container,
            text="📁 Файл (Меню)",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            text_color="#ffffff",
            width=95,
            height=32,
            corner_radius=6,
            command=self._handle_file_click
        )
        self.btn_file.pack(side="left", padx=2, pady=8)

        # 1. Кнопка: ТОЧКА СХВАЛЕННЯ (F8)
        self.btn_checkpoint = ctk.CTkButton(
            self.container,
            text="⏸ Точка (F8)",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#f59e0b",
            hover_color="#d97706",
            text_color="#000000",
            width=90,
            height=32,
            corner_radius=6,
            command=self._handle_checkpoint_click
        )
        self.btn_checkpoint.pack(side="left", padx=2, pady=8)

        # 2. Кнопка: ПАУЗА / ПРОДОВЖИТИ ЗАПИС (F9)
        self.btn_pause = ctk.CTkButton(
            self.container,
            text="⏸ Пауза (F9)",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="#334155",
            hover_color="#475569",
            text_color="#ffffff",
            width=85,
            height=32,
            corner_radius=6,
            command=self.on_toggle_pause
        )
        self.btn_pause.pack(side="left", padx=2, pady=8)

        # 3. Кнопка: ЗАВЕРШИТИ (F10)
        self.btn_stop = ctk.CTkButton(
            self.container,
            text="⏹ Стоп (F10)",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            text_color="#ffffff",
            width=85,
            height=32,
            corner_radius=6,
            command=self.on_stop_recording
        )
        self.btn_stop.pack(side="left", padx=(2, 8), pady=8)
        
        self.after(100, self._update_bounds)

    def _set_mode(self, mode: str):
        self.current_target_mode = mode
        if mode == "area":
            self.btn_mode_area.configure(fg_color="#d97706", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"))
            self.btn_mode_element.configure(fg_color="#334155", font=ctk.CTkFont(family="Segoe UI", size=11))
        else:
            self.btn_mode_element.configure(fg_color="#2563eb", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"))
            self.btn_mode_area.configure(fg_color="#334155", font=ctk.CTkFont(family="Segoe UI", size=11))
        if self.on_set_target_type:
            self.on_set_target_type(mode)

    def _handle_scroll_click(self):
        if self.on_add_scroll:
            self.on_add_scroll()
            orig = self.btn_scroll.cget("text")
            self.btn_scroll.configure(text="✅ Додано!")
            self.after(1000, lambda: self.btn_scroll.configure(text=orig))

    def _handle_file_click(self):
        if self.on_add_file_selection:
            self.on_add_file_selection()
            orig = self.btn_file.cget("text")
            self.btn_file.configure(text="✅ Додано!")
            self.after(1000, lambda: self.btn_file.configure(text=orig))


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
