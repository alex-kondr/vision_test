"""
Діалогові вікна: вікно очікування схвалення користувача (Checkpoint Modal)
та редактор параметрів дій (з підтримкою Smart Vision).
"""
import base64
import threading
import cv2
import numpy as np
import customtkinter as ctk
from typing import Callable, Optional, Tuple
from models import WorkflowAction
from region_selector import ScreenRegionSelector
from pynput import keyboard as pynput_keyboard

try:
    from gemini_vision import extract_element_text_from_crop, is_gemini_available
    HAS_GEMINI_OCR = True
except ImportError:
    HAS_GEMINI_OCR = False
    def extract_element_text_from_crop(*args, **kwargs): return ""
    def is_gemini_available(): return False

try:
    from uia_manager import UIAManager
    HAS_UIA = True
except ImportError:
    HAS_UIA = False


class CheckpointModalDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        action: WorkflowAction,
        cycle_info: str,
        on_response: Callable[[str], None]
    ):
        super().__init__(master)
        
        self.action = action
        self.on_response = on_response
        self.responded = False
        
        self.title("Точка схвалення дії")
        self.geometry("520x330")
        self.resizable(False, False)
        
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.grab_set()
        
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = 520
        h = 330
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        frame = ctk.CTkFrame(self, corner_radius=12, fg_color=("#f8fafc", "#0f172a"))
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        lbl_cycle = ctk.CTkLabel(
            frame,
            text=f"📌 {cycle_info}",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#3b82f6"
        )
        lbl_cycle.pack(anchor="w", padx=20, pady=(15, 5))

        lbl_title = ctk.CTkLabel(
            frame,
            text=f"⏸️  {action.title or 'Підтвердження користувача'}",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=("#1e293b", "#f8fafc")
        )
        lbl_title.pack(anchor="w", padx=20, pady=(0, 10))

        self.msg_box = ctk.CTkTextbox(
            frame,
            height=90,
            font=ctk.CTkFont(family="Segoe UI", size=14),
            wrap="word",
            activate_scrollbars=False,
            fg_color=("#e2e8f0", "#1e293b"),
            text_color=("#0f172a", "#f1f5f9")
        )
        self.msg_box.pack(fill="x", padx=20, pady=5)
        self.msg_box.insert("1.0", action.message or "Перевірте дані на екрані та підтвердіть готовність продовжувати.")
        self.msg_box.configure(state="disabled")

        lbl_hint = ctk.CTkLabel(
            frame,
            text="💡 Натисніть F8 або кнопку нижче для продовження. Esc — зупинити все.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#64748b"
        )
        lbl_hint.pack(anchor="w", padx=20, pady=(6, 12))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 10))

        self.btn_abort = ctk.CTkButton(
            btn_frame,
            text="⏹ Зупинити (Esc)",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            width=130,
            height=40,
            corner_radius=8,
            command=lambda: self._respond("abort")
        )
        self.btn_abort.pack(side="left")

        self.btn_skip = ctk.CTkButton(
            btn_frame,
            text="⏩ Пропустити",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color="#475569",
            hover_color="#64748b",
            width=110,
            height=40,
            corner_radius=8,
            command=lambda: self._respond("skip")
        )
        self.btn_skip.pack(side="left", padx=10)

        self.btn_continue = ctk.CTkButton(
            btn_frame,
            text="✅ Продовжити (F8)",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            height=40,
            corner_radius=8,
            command=lambda: self._respond("continue")
        )
        self.btn_continue.pack(side="right", fill="x", expand=True)

        self.bind("<space>", lambda e: self._respond("continue"))
        self.bind("<Escape>", lambda e: self._respond("abort"))
        self.protocol("WM_DELETE_WINDOW", lambda: self._respond("abort"))

        # F8 — глобальний перехоп через pynput (так само, як працює запис сценарію)
        self._kb_listener = None
        self._start_f8_listener()

    def _start_f8_listener(self):
        """Запускає pynput listener для F8 — глобальне перехоплення клавіши незалежно від фокусу."""
        def on_press(key):
            if not self.responded:
                try:
                    if key == pynput_keyboard.Key.f8:
                        self.after(0, lambda: self._respond("continue"))
                        return False  # зупиняємо listener
                except Exception:
                    pass

        self._kb_listener = pynput_keyboard.Listener(on_press=on_press)
        self._kb_listener.daemon = True
        self._kb_listener.start()

    def _bind_f7_recursive(self, widget):
        """Unused — залишено для сумісності."""
        pass

    def _respond(self, result: str):
        if self.responded:
            return
        self.responded = True
        # Зупиняємо pynput listener
        try:
            if self._kb_listener and self._kb_listener.is_alive():
                self._kb_listener.stop()
        except Exception:
            pass
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass
        self.on_response(result)


class ActionConfigDialog(ctk.CTkToplevel):
    """
    Універсальне модальне вікно для створення нової або редагування існуючої дії.
    Підтримує інтерактивне виділення мишкою на екрані:
    - Вибір області (протягування рамки, клік у центр)
    - Клік по конкретному елементу (виділення кнопки/пункту меню, авторозпізнавання тексту, лівий/правий клік)
    - Вибір документу (протягування 2 областей пошуку файлів із вибором пріоритету та контекстним меню)
    - Очікування підтвердження користувача (Checkpoint)
    - Прокрутка списку до самого низу
    """
    def __init__(
        self,
        master,
        action: Optional[WorkflowAction] = None,
        on_save: Optional[Callable[[WorkflowAction], None]] = None,
        is_new: bool = False
    ):
        super().__init__(master)
        self.is_new = is_new
        self.on_save = on_save
        
        # Якщо нова дія — створюємо порожню
        if action is None:
            self.action = WorkflowAction(
                type="area_click",
                target_type="area",
                delay_before=0.5,
                comment="Клік по області списку"
            )
        else:
            self.action = WorkflowAction.from_dict(action.to_dict())  # глибока копія

        # Збережені дані інтерактивного вибору
        self.area_rect_1 = getattr(self.action, "area_rect_1", None)
        self.area_rect_2 = getattr(self.action, "area_rect_2", None)
        self.template_b64 = self.action.template_b64
        self.template_width = self.action.template_width
        self.template_height = self.action.template_height

        self.title("Додати дію" if is_new else "Налаштування кроку сценарію")
        self.geometry("640x720")
        self.minsize(600, 680)
        self.attributes("-topmost", True)
        self.grab_set()

        # Головний контейнер з прокруткою
        main_container = ctk.CTkFrame(self, corner_radius=12, fg_color=("#1e293b", "#0f172a"))
        main_container.pack(fill="both", expand=True, padx=14, pady=14)

        # 1. Заголовок
        lbl_head = ctk.CTkLabel(
            main_container,
            text="➕ Створення нової дії" if is_new else "✏️ Налаштування кроку сценарію",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_head.pack(anchor="w", padx=16, pady=(12, 6))

        # 2. Селектор типу дії
        lbl_sel = ctk.CTkLabel(
            main_container,
            text="Оберіть тип операції:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#cbd5e1"
        )
        lbl_sel.pack(anchor="w", padx=16, pady=(4, 4))

        self.action_types = [
            "🔲 Вибір області (клік / фокус)",
            "🔘 Клік по елементу (кнопка / меню)",
            "📁 Вибір документу (2 області пошуку)",
            "🛑 Очікування підтвердження",
            "📜 Прокрутка до самого низу"
        ]
        self.combo_type = ctk.CTkComboBox(
            main_container,
            values=self.action_types,
            state="readonly",
            height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=self._on_type_changed
        )
        self.combo_type.pack(fill="x", padx=16, pady=(0, 10))

        # 3. Динамічний контейнер налаштувань відповідно до обраного типу
        self.dynamic_frame = ctk.CTkFrame(main_container, fg_color=("#0f172a", "#1e293b"), corner_radius=10)
        self.dynamic_frame.pack(fill="both", expand=True, padx=16, pady=4)

        # 4. Нижні спільні параметри: затримка та коментар
        bottom_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=16, pady=(10, 4))

        lbl_delay = ctk.CTkLabel(bottom_frame, text="Затримка перед виконанням (сек):", font=ctk.CTkFont(size=12))
        lbl_delay.pack(anchor="w", pady=(0, 2))
        self.entry_delay = ctk.CTkEntry(bottom_frame, height=30)
        self.entry_delay.pack(fill="x", pady=(0, 6))
        self.entry_delay.insert(0, str(self.action.delay_before or 0.5))

        lbl_comment = ctk.CTkLabel(bottom_frame, text="Коментар / примітка кроку:", font=ctk.CTkFont(size=12))
        lbl_comment.pack(anchor="w", pady=(0, 2))
        self.entry_comment = ctk.CTkEntry(bottom_frame, height=30, placeholder_text="Опис дії для оператора")
        self.entry_comment.pack(fill="x", pady=(0, 10))
        self.entry_comment.insert(0, self.action.comment or "")

        # 5. Кнопки збереження та скасування
        btn_bar = ctk.CTkFrame(main_container, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=(4, 10))

        btn_cancel = ctk.CTkButton(
            btn_bar,
            text="Скасувати",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color="#475569",
            hover_color="#64748b",
            height=36,
            width=120,
            command=self.destroy
        )
        btn_cancel.pack(side="left")

        btn_save = ctk.CTkButton(
            btn_bar,
            text="💾 Зберегти дію",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            height=36,
            command=self._save
        )
        btn_save.pack(side="right", fill="x", expand=True, padx=(10, 0))

        # Визначаємо початковий тип дії
        self._init_current_type()

    def _init_current_type(self):
        if self.action.type == "area_click" or self.action.target_type == "area":
            self.combo_type.set(self.action_types[0])
        elif self.action.type in ("click", "double_click", "right_click", "menu_click") and self.action.target_type in ("element", "menu_item", "button"):
            self.combo_type.set(self.action_types[1])
        elif self.action.type == "file_selection" or self.action.target_type == "file_item" or self.action.show_file_menu:
            self.combo_type.set(self.action_types[2])
        elif self.action.type == "checkpoint":
            self.combo_type.set(self.action_types[3])
        elif self.action.type == "scroll_to_bottom" or self.action.scroll_to_bottom:
            self.combo_type.set(self.action_types[4])
        else:
            self.combo_type.set(self.action_types[0])
        self._render_dynamic_fields()

    def _on_type_changed(self, choice):
        self._render_dynamic_fields()

    def _clear_dynamic_frame(self):
        for widget in self.dynamic_frame.winfo_children():
            widget.destroy()

    def _render_dynamic_fields(self):
        self._clear_dynamic_frame()
        choice = self.combo_type.get()

        # ============================================================
        # 1. ВИБІР ОБЛАСТІ
        # ============================================================
        if "Вибір області" in choice:
            lbl_info = ctk.CTkLabel(
                self.dynamic_frame,
                text="🔲 Клік по області використовується для активації та фокусування списку або вікна.\n"
                     "Вміст списку змінюється, тому жорсткий шаблон кнопки тут не потрібен.",
                font=ctk.CTkFont(size=12),
                text_color="#94a3b8",
                justify="left"
            )
            lbl_info.pack(anchor="w", padx=14, pady=(12, 10))

            btn_snip_area = ctk.CTkButton(
                self.dynamic_frame,
                text="🎯 Вказати область мишкою на екрані",
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                fg_color="#0284c7",
                hover_color="#0369a1",
                height=36,
                command=self._snip_for_area
            )
            btn_snip_area.pack(fill="x", padx=14, pady=6)

            cur_rect = self.area_rect_1 or (
                (self.action.x - 50, self.action.y - 30, self.action.x + 50, self.action.y + 30)
                if self.action.x and self.action.y else None
            )
            rect_txt = f"✅ Область: ({cur_rect[0]}, {cur_rect[1]}) ➔ ({cur_rect[2]}, {cur_rect[3]})\n" \
                       f"Точка кліку (центр): ({ (cur_rect[0]+cur_rect[2])//2 }, { (cur_rect[1]+cur_rect[3])//2 })" if cur_rect else "⚠️ Область ще не вказана (натисніть кнопку вище)"
            
            self.lbl_area_coords = ctk.CTkLabel(
                self.dynamic_frame,
                text=rect_txt,
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#38bdf8" if cur_rect else "#f59e0b",
                justify="left"
            )
            self.lbl_area_coords.pack(anchor="w", padx=14, pady=(6, 12))

        # ============================================================
        # 2. КЛІК ПО ЕЛЕМЕНТУ
        # ============================================================
        elif "Клік по елементу" in choice:
            lbl_info = ctk.CTkLabel(
                self.dynamic_frame,
                text="🔘 Точний клік по кнопці або пункту меню зі Smart Vision (Gemini + OpenCV).\n"
                     "Знаходить елемент навіть при його зміщенні на екрані на 10-25%.",
                font=ctk.CTkFont(size=12),
                text_color="#94a3b8",
                justify="left"
            )
            lbl_info.pack(anchor="w", padx=14, pady=(10, 6))

            btn_snip_elem = ctk.CTkButton(
                self.dynamic_frame,
                text="🎯 Виділити елемент мишкою на екрані",
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                fg_color="#7c3aed",
                hover_color="#6d28d9",
                height=36,
                command=self._snip_for_element
            )
            btn_snip_elem.pack(fill="x", padx=14, pady=4)

            # Статус знімка
            has_tmpl = bool(self.template_b64)
            tmpl_txt = f"✅ Знімок елемента захоплено ({self.template_width}x{self.template_height} px)" if has_tmpl else "❌ Знімок не прив'язано"
            self.lbl_elem_status = ctk.CTkLabel(
                self.dynamic_frame,
                text=tmpl_txt,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#10b981" if has_tmpl else "#f87171"
            )
            self.lbl_elem_status.pack(anchor="w", padx=14, pady=(2, 6))

            # Тип кліку: Лівий / Правий / Подвійний
            lbl_btn_type = ctk.CTkLabel(self.dynamic_frame, text="Тип натискання миші:", font=ctk.CTkFont(size=12))
            lbl_btn_type.pack(anchor="w", padx=14, pady=(2, 2))
            
            self.combo_btn = ctk.CTkComboBox(
                self.dynamic_frame,
                values=["Лівий клік (кнопка)", "Правий клік (контекстне меню)", "Подвійний клік"],
                state="readonly",
                height=30
            )
            if self.action.type == "right_click" or self.action.button == "right":
                self.combo_btn.set("Правий клік (контекстне меню)")
            elif self.action.type == "double_click":
                self.combo_btn.set("Подвійний клік")
            else:
                self.combo_btn.set("Лівий клік (кнопка)")
            self.combo_btn.pack(fill="x", padx=14, pady=(0, 6))

            # Текст елемента
            lbl_elem_text = ctk.CTkLabel(
                self.dynamic_frame,
                text="Назва / семантичний текст (наприклад: 'Додаткові дії' або 'Зберегти'):",
                font=ctk.CTkFont(size=12)
            )
            lbl_elem_text.pack(anchor="w", padx=14, pady=(4, 2))
            self.entry_element_text = ctk.CTkEntry(
                self.dynamic_frame,
                height=30,
                placeholder_text="Додаткові дії, Друк, Сформувати..."
            )
            self.entry_element_text.pack(fill="x", padx=14, pady=(0, 6))
            self.entry_element_text.insert(0, self.action.element_text or "")

            # Чекбокс Smart Vision
            self.chk_use_vision = ctk.CTkCheckBox(
                self.dynamic_frame,
                text="Використовувати Smart Vision (шукати при зміщенні 10-25%)",
                font=ctk.CTkFont(size=12),
                onvalue=True,
                offvalue=False
            )
            if getattr(self.action, "use_vision", True):
                self.chk_use_vision.select()
            self.chk_use_vision.pack(anchor="w", padx=14, pady=4)

        # ============================================================
        # 3. ВИБІР ДОКУМЕНТУ (2 ОБЛАСТІ ПОШУКУ З ПРІОРИТЕТОМ)
        # ============================================================
        elif "Вибір документу" in choice:
            lbl_info = ctk.CTkLabel(
                self.dynamic_frame,
                text="📁 Пошук документів за двома областями екрана з пріоритетом:\n"
                     "Якщо назва файлу може з'явитися в одній із двох зон списку або таблиці.",
                font=ctk.CTkFont(size=12),
                text_color="#94a3b8",
                justify="left"
            )
            lbl_info.pack(anchor="w", padx=14, pady=(10, 6))

            # Область 1
            btn_area1 = ctk.CTkButton(
                self.dynamic_frame,
                text="🎯 Протягнути Область 1 (Основна)",
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                fg_color="#0891b2",
                hover_color="#0e7490",
                height=32,
                command=lambda: self._snip_for_document_area(1)
            )
            btn_area1.pack(fill="x", padx=14, pady=4)

            self.lbl_area1_info = ctk.CTkLabel(
                self.dynamic_frame,
                text=f"Область 1: {self.area_rect_1}" if self.area_rect_1 else "Область 1: (не задано)",
                font=ctk.CTkFont(size=11),
                text_color="#38bdf8" if self.area_rect_1 else "#94a3b8"
            )
            self.lbl_area1_info.pack(anchor="w", padx=16, pady=(0, 6))

            # Область 2
            btn_area2 = ctk.CTkButton(
                self.dynamic_frame,
                text="🎯 Протягнути Область 2 (Альтернативна)",
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                fg_color="#0d9488",
                hover_color="#0f766e",
                height=32,
                command=lambda: self._snip_for_document_area(2)
            )
            btn_area2.pack(fill="x", padx=14, pady=4)

            self.lbl_area2_info = ctk.CTkLabel(
                self.dynamic_frame,
                text=f"Область 2: {self.area_rect_2}" if self.area_rect_2 else "Область 2: (не задано)",
                font=ctk.CTkFont(size=11),
                text_color="#2dd4bf" if self.area_rect_2 else "#94a3b8"
            )
            self.lbl_area2_info.pack(anchor="w", padx=16, pady=(0, 6))

            # Пріоритет пошуку
            lbl_priority = ctk.CTkLabel(self.dynamic_frame, text="Пріоритет пошуку файлів:", font=ctk.CTkFont(size=12))
            lbl_priority.pack(anchor="w", padx=14, pady=(4, 2))

            self.priority_options = [
                "🥇 Спочатку Область 1, якщо не знайдено ➔ Область 2",
                "🥈 Спочатку Область 2, якщо не знайдено ➔ Область 1",
                "🔄 Об'єднати файли з обох областей"
            ]
            self.combo_priority = ctk.CTkComboBox(
                self.dynamic_frame,
                values=self.priority_options,
                state="readonly",
                height=30
            )
            pr = getattr(self.action, "search_priority", "area_1_first")
            if pr == "area_2_first":
                self.combo_priority.set(self.priority_options[1])
            elif pr == "both":
                self.combo_priority.set(self.priority_options[2])
            else:
                self.combo_priority.set(self.priority_options[0])
            self.combo_priority.pack(fill="x", padx=14, pady=(0, 8))

            # Чекбокс контекстного меню
            self.chk_show_menu = ctk.CTkCheckBox(
                self.dynamic_frame,
                text="Показувати спливаюче контекстне меню файлів для вибору",
                font=ctk.CTkFont(size=12),
                onvalue=True,
                offvalue=False
            )
            if getattr(self.action, "show_file_menu", True):
                self.chk_show_menu.select()
            self.chk_show_menu.pack(anchor="w", padx=14, pady=4)

        # ============================================================
        # 4. ОЧІКУВАННЯ ПІДТВЕРДЖЕННЯ (CHECKPOINT)
        # ============================================================
        elif "Очікування підтвердження" in choice:
            lbl_title = ctk.CTkLabel(self.dynamic_frame, text="Назва точки перевірки:", font=ctk.CTkFont(size=12))
            lbl_title.pack(anchor="w", padx=14, pady=(10, 2))
            self.entry_cp_title = ctk.CTkEntry(self.dynamic_frame, height=30, placeholder_text="Перевірка адреси...")
            self.entry_cp_title.pack(fill="x", padx=14, pady=(0, 6))
            self.entry_cp_title.insert(0, self.action.title or "Підтвердження користувача")

            lbl_msg = ctk.CTkLabel(self.dynamic_frame, text="Інструкція / повідомлення оператору:", font=ctk.CTkFont(size=12))
            lbl_msg.pack(anchor="w", padx=14, pady=(4, 2))
            self.entry_cp_msg = ctk.CTkTextbox(self.dynamic_frame, height=80)
            self.entry_cp_msg.pack(fill="x", padx=14, pady=(0, 10))
            self.entry_cp_msg.insert("1.0", self.action.message or "Перевірте дані на екрані та натисніть 'Продовжити'.")

        # ============================================================
        # 5. ПРОКРУТКА ДО НИЗУ
        # ============================================================
        elif "Прокрутка" in choice:
            lbl_info = ctk.CTkLabel(
                self.dynamic_frame,
                text="📜 Автоматична прокрутка списку до самого кінця.\n"
                     "Використовує коліщатко миші та клавіші PageDown/End для 100% гарантованого переходу вниз.",
                font=ctk.CTkFont(size=12),
                text_color="#94a3b8",
                justify="left"
            )
            lbl_info.pack(anchor="w", padx=14, pady=16)

    # ============================================================
    # ІНТЕРАКТИВНЕ ВИДІЛЕННЯ ОБЛАСТЕЙ МИШКОЮ (SNIP TOOLS)
    # ============================================================
    def _run_snip(self, title: str, on_done: Callable[[Optional[Tuple[int, int, int, int]], Optional[np.ndarray]], None]):
        # Обов'язково звільняємо модальний grab, інакше приховане вікно блокує всі події миші!
        try:
            self.grab_release()
        except Exception:
            pass
        self.withdraw()
        if self.master:
            self.master.withdraw()

        def callback(rect, crop):
            def restore():
                if self.master:
                    self.master.deiconify()
                self.deiconify()
                self.lift()
                self.focus_force()
                try:
                    self.grab_set()
                except Exception:
                    pass
                on_done(rect, crop)

            self.after(50, restore)

        self.after(80, lambda: ScreenRegionSelector(title=title, on_selected=callback))

    def _snip_for_area(self):
        def on_done(rect, crop):
            if rect:
                self.area_rect_1 = rect
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                self.action.x = cx
                self.action.y = cy
                self.action.area_rect_1 = rect
                self.lbl_area_coords.configure(
                    text=f"✅ Область: ({rect[0]}, {rect[1]}) ➔ ({rect[2]}, {rect[3]})\nЦентр кліку: ({cx}, {cy})",
                    text_color="#38bdf8"
                )
        self._run_snip("Протягніть область списку/панелі для кліку", on_done)

    def _snip_for_element(self):
        def on_done(rect, crop):
            if rect and crop is not None:
                x1, y1, x2, y2 = rect
                w = x2 - x1
                h = y2 - y1
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                
                # Кодуємо знімок у base64
                success, buf = cv2.imencode('.png', crop)
                if success:
                    self.template_b64 = base64.b64encode(buf).decode('utf-8')
                    self.template_width = int(w)
                    self.template_height = int(h)
                    self.action.template_b64 = self.template_b64
                    self.action.template_width = int(w)
                    self.action.template_height = int(h)
                    self.action.template_offset_x = int(w // 2)
                    self.action.template_offset_y = int(h // 2)
                    self.action.x = cx
                    self.action.y = cy
                    
                    # Спроба зчитати UIA елемент під центром виділення
                    uia_found_name = ""
                    if HAS_UIA:
                        uia_info = UIAManager.get_element_at_point(cx, cy)
                        if uia_info.get("name"):
                            uia_found_name = uia_info["name"]
                            self.action.uia_name = uia_found_name
                            self.action.uia_control_type = uia_info.get("control_type", "")
                            self.action.uia_window = uia_info.get("window_title", "")
                            self.action.uia_automation_id = uia_info.get("automation_id", "")
                            self.action.uia_class_name = uia_info.get("class_name", "")
                            if hasattr(self, "entry_element_text"):
                                self.entry_element_text.delete(0, "end")
                                self.entry_element_text.insert(0, uia_found_name)

                    if uia_found_name:
                        self.lbl_elem_status.configure(
                            text=f"⚡ UIA знайдено: \"{uia_found_name}\" ({self.action.uia_control_type})",
                            text_color="#38bdf8"
                        )
                    elif HAS_GEMINI_OCR and is_gemini_available():
                        self.lbl_elem_status.configure(
                            text=f"✅ Знімок ({w}x{h} px) | 🤖 Розпізнавання тексту елемента...",
                            text_color="#38bdf8"
                        )
                        def run_ocr():
                            try:
                                extracted = extract_element_text_from_crop(crop)
                                if extracted and hasattr(self, "entry_element_text"):
                                    self.after(0, lambda: (
                                        self.entry_element_text.delete(0, "end"),
                                        self.entry_element_text.insert(0, extracted),
                                        self.lbl_elem_status.configure(
                                            text=f"✅ Знімок ({w}x{h} px) | Текст: \"{extracted}\"",
                                            text_color="#10b981"
                                        )
                                    ))
                                else:
                                    self.after(0, lambda: self.lbl_elem_status.configure(
                                        text=f"✅ Знімок захоплено ({w}x{h} px) на ({cx}, {cy})",
                                        text_color="#10b981"
                                    ))
                            except Exception:
                                pass
                        threading.Thread(target=run_ocr, daemon=True).start()
                    else:
                        self.lbl_elem_status.configure(
                            text=f"✅ Знімок захоплено ({w}x{h} px) на ({cx}, {cy})",
                            text_color="#10b981"
                        )

        self._run_snip("Виділіть кнопку або пункт меню рамкою", on_done)

    def _snip_for_document_area(self, area_num: int):
        def on_done(rect, crop):
            if rect:
                if area_num == 1:
                    self.area_rect_1 = rect
                    self.action.area_rect_1 = rect
                    self.lbl_area1_info.configure(
                        text=f"✅ Область 1: ({rect[0]}, {rect[1]}) ➔ ({rect[2]}, {rect[3]})",
                        text_color="#38bdf8"
                    )
                else:
                    self.area_rect_2 = rect
                    self.action.area_rect_2 = rect
                    self.lbl_area2_info.configure(
                        text=f"✅ Область 2: ({rect[0]}, {rect[1]}) ➔ ({rect[2]}, {rect[3]})",
                        text_color="#2dd4bf"
                    )
        self._run_snip(f"Протягніть Область {area_num} для пошуку документів", on_done)

    # ============================================================
    # ЗБЕРЕЖЕННЯ ПАРАМЕТРІВ
    # ============================================================
    def _save(self):
        try:
            self.action.delay_before = float(self.entry_delay.get())
        except ValueError:
            self.action.delay_before = 0.5

        self.action.comment = self.entry_comment.get().strip()
        choice = self.combo_type.get()

        if "Вибір області" in choice:
            self.action.type = "area_click"
            self.action.target_type = "area"
            self.action.area_rect_1 = self.area_rect_1
            if self.area_rect_1:
                self.action.x = (self.area_rect_1[0] + self.area_rect_1[2]) // 2
                self.action.y = (self.area_rect_1[1] + self.area_rect_1[3]) // 2
            self.action.use_vision = False

        elif "Клік по елементу" in choice:
            btn_choice = self.combo_btn.get()
            if "Правий" in btn_choice:
                self.action.type = "menu_click"
                self.action.target_type = "menu_item"
                self.action.button = "right"
            elif "Подвійний" in btn_choice:
                self.action.type = "double_click"
                self.action.target_type = "element"
                self.action.button = "left"
            else:
                self.action.type = "click"
                self.action.target_type = "element"
                self.action.button = "left"

            if hasattr(self, "entry_element_text"):
                text_val = self.entry_element_text.get().strip()
                self.action.element_text = text_val
                if not self.action.uia_name and text_val:
                    self.action.uia_name = text_val
            if hasattr(self, "chk_use_vision"):
                self.action.use_vision = bool(self.chk_use_vision.get())

            if self.template_b64:
                self.action.template_b64 = self.template_b64
                self.action.template_width = self.template_width
                self.action.template_height = self.template_height

        elif "Вибір документу" in choice:
            self.action.type = "file_selection"
            self.action.target_type = "file_item"
            self.action.area_rect_1 = self.area_rect_1
            self.action.area_rect_2 = self.area_rect_2

            pr_choice = self.combo_priority.get()
            if "Область 2, якщо" in pr_choice:
                self.action.search_priority = "area_2_first"
            elif "Об'єднати" in pr_choice:
                self.action.search_priority = "both"
            else:
                self.action.search_priority = "area_1_first"

            if hasattr(self, "chk_show_menu"):
                self.action.show_file_menu = bool(self.chk_show_menu.get())

        elif "Очікування підтвердження" in choice:
            self.action.type = "checkpoint"
            if hasattr(self, "entry_cp_title"):
                self.action.title = self.entry_cp_title.get().strip()
            if hasattr(self, "entry_cp_msg"):
                self.action.message = self.entry_cp_msg.get("1.0", "end-1c").strip()

        elif "Прокрутка" in choice:
            self.action.type = "scroll_to_bottom"
            self.action.scroll_to_bottom = True

        if self.on_save:
            self.on_save(self.action)
        self.destroy()


class AddActionDialog(ActionConfigDialog):
    """Діалог додавання нової дії до сценарію."""
    def __init__(self, master, on_save: Callable[[WorkflowAction], None]):
        super().__init__(master, action=None, on_save=on_save, is_new=True)


class EditActionDialog(ActionConfigDialog):
    """Діалог редагування існуючої дії сценарію."""
    def __init__(self, master, action: WorkflowAction, on_save: Callable[[WorkflowAction], None]):
        super().__init__(master, action=action, on_save=on_save, is_new=False)



class FileSelectionContextMenu(ctk.CTkToplevel):
    """
    Контекстне меню / спливаюче вікно для відображення списку знайдених на екрані файлів,
    щоб оператор міг обрати потрібний файл і продовжити виконання сценарію.
    """
    def __init__(
        self,
        master,
        files: list,
        on_file_selected: Callable[[Optional[dict]], None]
    ):
        super().__init__(master)
        self.files = files or []
        self.on_file_selected = on_file_selected
        self.chosen_file = None
        self.responded = False

        self.title("Контекстне меню: Знайдені файли")
        self.geometry("560x420")
        self.resizable(False, False)
        
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.grab_set()

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = 560
        h = 420
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        container = ctk.CTkFrame(self, corner_radius=12, fg_color=("#1e293b", "#0f172a"))
        container.pack(fill="both", expand=True, padx=12, pady=12)

        # Заголовок
        lbl_head = ctk.CTkLabel(
            container,
            text="📁 Список знайдених на екрані файлів",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_head.pack(anchor="w", padx=16, pady=(12, 2))

        count_text = f"Знайдено {len(self.files)} файлів/рядків. Оберіть файл для продовження або натисніть 'Останній внизу':"
        lbl_sub = ctk.CTkLabel(
            container,
            text=count_text,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#94a3b8"
        )
        lbl_sub.pack(anchor="w", padx=16, pady=(0, 8))

        # Список файлів у прокручуваному фреймі
        self.scroll_frame = ctk.CTkScrollableFrame(container, height=220, fg_color=("#0f172a", "#1e293b"))
        self.scroll_frame.pack(fill="both", expand=True, padx=16, pady=4)

        if not self.files:
            lbl_none = ctk.CTkLabel(
                self.scroll_frame,
                text="⚠️ Файлів автоматично не розпізнано.\nВи можете вибрати останній рядок внизу або пропустити крок.",
                font=ctk.CTkFont(family="Segoe UI", size=13),
                text_color="#f59e0b"
            )
            lbl_none.pack(pady=40)
        else:
            # Табличний заголовок
            header = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            header.grid_columnconfigure(0, weight=1)
            header.grid_columnconfigure(1, weight=5)
            header.grid_columnconfigure(2, weight=2)
            header.grid_columnconfigure(3, weight=2)
            ctk.CTkLabel(header, text=" ", width=24).grid(row=0, column=0)
            ctk.CTkLabel(header, text="Назва файлу", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").grid(row=0, column=1, padx=4, sticky="w")
            ctk.CTkLabel(header, text="X", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").grid(row=0, column=2, padx=4, sticky="w")
            ctk.CTkLabel(header, text="Y", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").grid(row=0, column=3, padx=4, sticky="w")
            header.pack(fill="x", pady=(4,2), padx=8)

            for idx, f in enumerate(self.files, start=1):
                name = f.get("name", f"Файл #{idx}")
                fx = f.get("x", 0)
                fy = f.get("y", 0)

                row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
                row.grid_columnconfigure(0, weight=1)
                row.grid_columnconfigure(1, weight=5)
                row.grid_columnconfigure(2, weight=2)
                row.grid_columnconfigure(3, weight=2)

                btn = ctk.CTkButton(
                    row,
                    text="🟢",
                    width=24,
                    height=24,
                    fg_color="#10b981",
                    hover_color="#059669",
                    command=lambda file_dict=f: self._select_file(file_dict)
                )
                btn.grid(row=0, column=0, padx=2, sticky="w")
                ctk.CTkLabel(row, text=name, font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#f8fafc").grid(row=0, column=1, padx=4, sticky="w")
                ctk.CTkLabel(row, text=str(fx), font=ctk.CTkFont(size=12), text_color="#f8fafc").grid(row=0, column=2, padx=4, sticky="w")
                ctk.CTkLabel(row, text=str(fy), font=ctk.CTkFont(size=12), text_color="#f8fafc").grid(row=0, column=3, padx=4, sticky="w")
                row.pack(fill="x", pady=2, padx=4)

        # Панель дій
        btn_bar = ctk.CTkFrame(container, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=(10, 6))

        # Кнопка швидкого вибору останнього файлу (внизу списку)
        btn_bottom = ctk.CTkButton(
            btn_bar,
            text="⬇️ Обрати останній (внизу)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=36,
            command=self._select_bottom_file
        )
        btn_bottom.pack(side="left", padx=(0, 6))

        btn_skip = ctk.CTkButton(
            btn_bar,
            text="⏩ Пропустити крок",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#475569",
            hover_color="#64748b",
            height=36,
            width=120,
            command=lambda: self._select_file(None)
        )
        btn_skip.pack(side="left", padx=4)

        btn_abort = ctk.CTkButton(
            btn_bar,
            text="⏹ Зупинити (Esc)",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            height=36,
            width=120,
            command=self._abort
        )
        btn_abort.pack(side="right")

        self.bind("<Escape>", lambda e: self._abort())
        self.bind("<Return>", lambda e: self._select_bottom_file())
        self.protocol("WM_DELETE_WINDOW", self._abort)

    def _select_file(self, file_dict: Optional[dict]):
        if self.responded:
            return
        self.responded = True
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass
        self.on_file_selected(file_dict)

    def _select_bottom_file(self):
        """Обирає останній файл зі списку (найнижчий рядок на екрані)."""
        if self.files:
            # Останній файл або той, що має найбільшу Y координату
            bottom_file = max(self.files, key=lambda f: f.get("y", 0))
            self._select_file(bottom_file)
        else:
            self._select_file(None)

    def _abort(self):
        if self.responded:
            return
        self.responded = True
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass
        self.on_file_selected(None)


class RetrainChunkDialog(ctk.CTkToplevel):
    """
    Діалогове вікно вибору початкової точки та діапазону кроків
    для повторного навчання (донавчання шматками) Gemini Vision / Smart Vision.
    """
    def __init__(
        self,
        master,
        actions: list,
        initial_step_idx: int = 0,
        on_confirm: Optional[Callable[[int, Optional[int]], None]] = None
    ):
        super().__init__(master)
        self.actions = actions
        self.on_confirm = on_confirm
        self.responded = False
        
        self.title("Донавчання дій (повторне навчання шматками)")
        self.geometry("640x520")
        self.minsize(580, 480)
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.grab_set()

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = 640
        h = 520
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self._build_ui(initial_step_idx)

    def _build_ui(self, initial_step_idx: int):
        total = len(self.actions)
        
        header = ctk.CTkFrame(self, corner_radius=10, fg_color=("#1e1b4b", "#0f0d24"))
        header.pack(fill="x", padx=16, pady=(16, 10))

        lbl_title = ctk.CTkLabel(
            header,
            text="🧠 Донавчання (Повторне навчання шматками)",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#c084fc"
        )
        lbl_title.pack(anchor="w", padx=14, pady=(10, 2))

        lbl_desc = ctk.CTkLabel(
            header,
            text="Оберіть точку початку та шматок кроків для повторної демонстрації дій.\nНові знімки додадуться до банку Gemini Vision, що підвищить надійність розпізнавання.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#94a3b8",
            justify="left"
        )
        lbl_desc.pack(anchor="w", padx=14, pady=(0, 10))

        content = ctk.CTkFrame(self, corner_radius=10)
        content.pack(fill="both", expand=True, padx=16, pady=4)

        # 1. Початковий крок
        row_start = ctk.CTkFrame(content, fg_color="transparent")
        row_start.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            row_start,
            text="Почати з кроку:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            width=130,
            anchor="w"
        ).pack(side="left")

        self.step_options = [
            f"Крок {i+1}: [{a.type}] {a.element_text or a.comment or a.key or ('Область' if getattr(a, 'target_type', '') == 'area' else '')}"[:60]
            for i, a in enumerate(self.actions)
        ]
        
        init_val = self.step_options[min(max(0, initial_step_idx), total - 1)] if self.step_options else ""
        self.combo_start = ctk.CTkComboBox(
            row_start,
            values=self.step_options,
            width=440,
            height=32,
            command=self._on_selection_changed,
            state="readonly"
        )
        if init_val:
            self.combo_start.set(init_val)
        self.combo_start.pack(side="left", fill="x", expand=True)

        # 2. Діапазон (до якого кроку)
        row_scope = ctk.CTkFrame(content, fg_color="transparent")
        row_scope.pack(fill="x", padx=14, pady=4)

        ctk.CTkLabel(
            row_scope,
            text="Діапазон шматка:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            width=130,
            anchor="w"
        ).pack(side="left")

        self.scope_var = ctk.StringVar(value="to_end")

        rb_to_end = ctk.CTkRadioButton(
            row_scope,
            text="До кінця сценарію",
            variable=self.scope_var,
            value="to_end",
            command=self._on_selection_changed
        )
        rb_to_end.pack(side="left", padx=(0, 15))

        rb_chunk = ctk.CTkRadioButton(
            row_scope,
            text="До кроку:",
            variable=self.scope_var,
            value="chunk",
            command=self._on_selection_changed
        )
        rb_chunk.pack(side="left", padx=(0, 6))

        self.combo_end = ctk.CTkComboBox(
            row_scope,
            values=self.step_options,
            width=220,
            height=30,
            command=self._on_selection_changed,
            state="readonly"
        )
        end_init_idx = min(initial_step_idx + 2, total - 1)
        if self.step_options:
            self.combo_end.set(self.step_options[end_init_idx])
        self.combo_end.pack(side="left", fill="x", expand=True)

        # 3. Список дій у вибраному шматку
        lbl_preview = ctk.CTkLabel(
            content,
            text="📋 Кроки, що входять у вибраний шматок для донавчання:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            anchor="w"
        )
        lbl_preview.pack(fill="x", padx=14, pady=(8, 2))

        self.txt_preview = ctk.CTkTextbox(content, height=130, font=("Consolas", 10))
        self.txt_preview.pack(fill="both", expand=True, padx=14, pady=(2, 6))

        self.lbl_summary = ctk.CTkLabel(
            content,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#38bdf8",
            anchor="w"
        )
        self.lbl_summary.pack(fill="x", padx=14, pady=(0, 8))

        # 4. Панель кнопок
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=(6, 16))

        btn_cancel = ctk.CTkButton(
            btn_bar,
            text="Скасувати",
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            width=110,
            height=36,
            command=self._cancel
        )
        btn_cancel.pack(side="right", padx=(8, 0))

        btn_start = ctk.CTkButton(
            btn_bar,
            text="🚀 Почати донавчання шматка (F10 — завершити)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            height=36,
            command=self._confirm
        )
        btn_start.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda e: self._cancel())

        self._update_preview()

    def _get_indices(self) -> Tuple[int, Optional[int]]:
        start_idx = 0
        val_start = self.combo_start.get()
        if val_start in self.step_options:
            start_idx = self.step_options.index(val_start)

        end_idx = None
        if self.scope_var.get() == "chunk":
            val_end = self.combo_end.get()
            if val_end in self.step_options:
                end_step_num = self.step_options.index(val_end)
                end_idx = max(start_idx + 1, end_step_num + 1)
        return start_idx, end_idx

    def _on_selection_changed(self, *args):
        self._update_preview()

    def _update_preview(self):
        start_idx, end_idx = self._get_indices()
        total = len(self.actions)
        eff_end = total if end_idx is None else min(end_idx, total)
        if eff_end <= start_idx:
            eff_end = min(start_idx + 1, total)

        slice_actions = self.actions[start_idx:eff_end]
        vision_count = 0

        self.txt_preview.configure(state="normal")
        self.txt_preview.delete("1.0", "end")

        for idx, act in enumerate(slice_actions, start=start_idx + 1):
            bank_count = len(getattr(act, "template_bank", []) or [])
            if act.template_b64:
                vision_info = f"[🎯 Vision: банк x{bank_count}]"
                vision_count += 1
            elif act.uia_name:
                vision_info = f"[⚡ UIA: {act.uia_control_type or 'Control'}]"
            elif getattr(act, "target_type", "") == "area":
                vision_info = "[🔲 Область]"
            else:
                vision_info = "[Координати/Клавіша]"

            line = f"Крок {idx:2d}: {act.type:12s} | {act.get_display_text()[:45]:45s} {vision_info}\n"
            self.txt_preview.insert("end", line)

        self.txt_preview.configure(state="disabled")
        scope_desc = f"кроки {start_idx + 1} ... {eff_end}"
        self.lbl_summary.configure(
            text=f"ℹ️ У вибраному шматку ({scope_desc}): {len(slice_actions)} дій, з них {vision_count} мають знімки Vision для поповнення банку."
        )

    def _confirm(self):
        if self.responded:
            return
        self.responded = True
        start_idx, end_idx = self._get_indices()
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass
        if self.on_confirm:
            self.on_confirm(start_idx, end_idx)

    def _cancel(self):
        if self.responded:
            return
        self.responded = True
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass


class AppendActionsDialog(ctk.CTkToplevel):
    """
    Діалогове вікно вибору позиції для дозапису дій у сценарій
    (в кінець або після конкретного кроку).
    """
    def __init__(
        self,
        master,
        actions: list,
        selected_idx: Optional[int] = None,
        on_confirm: Optional[Callable[[int], None]] = None
    ):
        super().__init__(master)
        self.actions = actions
        self.on_confirm = on_confirm
        self.responded = False
        
        self.title("Дозапис дій у сценарій")
        self.geometry("540x360")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.grab_set()

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = 540
        h = 360
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self._build_ui(selected_idx)

    def _build_ui(self, selected_idx: Optional[int]):
        total = len(self.actions)
        
        header = ctk.CTkFrame(self, corner_radius=10, fg_color=("#1e293b", "#0f172a"))
        header.pack(fill="x", padx=16, pady=(16, 10))

        lbl_title = ctk.CTkLabel(
            header,
            text="⏺➕ Дозапис дій у сценарій",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#f87171"
        )
        lbl_title.pack(anchor="w", padx=14, pady=(10, 2))

        lbl_desc = ctk.CTkLabel(
            header,
            text="Запишіть нові дії (кліки, клавіші, очікування) та додайте їх до сценарію.\nВи можете вставити їх у кінець або після обраного кроку.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#94a3b8",
            justify="left"
        )
        lbl_desc.pack(anchor="w", padx=14, pady=(0, 10))

        content = ctk.CTkFrame(self, corner_radius=10)
        content.pack(fill="both", expand=True, padx=16, pady=4)

        ctk.CTkLabel(
            content,
            text="Куди додати нові записані дії?",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        ).pack(anchor="w", padx=14, pady=(10, 6))

        self.target_var = ctk.StringVar(value="selected" if selected_idx is not None else "end")

        rb_end = ctk.CTkRadioButton(
            content,
            text=f"В кінець списку дій (після кроку №{total})",
            variable=self.target_var,
            value="end",
            font=ctk.CTkFont(size=12)
        )
        rb_end.pack(anchor="w", padx=14, pady=5)

        self.step_options = [
            f"Крок {i+1}: [{a.type}] {a.element_text or a.comment or a.key or ''}"[:55]
            for i, a in enumerate(self.actions)
        ]

        rb_after_sel = ctk.CTkRadioButton(
            content,
            text="Після вказаного кроку:",
            variable=self.target_var,
            value="selected",
            font=ctk.CTkFont(size=12)
        )
        rb_after_sel.pack(anchor="w", padx=14, pady=(5, 2))

        init_step_idx = selected_idx if selected_idx is not None else max(0, total - 1)
        self.combo_step = ctk.CTkComboBox(
            content,
            values=self.step_options,
            width=470,
            height=30,
            state="readonly"
        )
        if self.step_options:
            self.combo_step.set(self.step_options[min(init_step_idx, total - 1)])
        self.combo_step.pack(anchor="w", padx=32, pady=(2, 10))

        # Підказка
        lbl_hint = ctk.CTkLabel(
            content,
            text="💡 Натисніть F10 під час запису, щоб зупинити його та зберегти кроки.",
            font=ctk.CTkFont(size=11),
            text_color="#38bdf8"
        )
        lbl_hint.pack(anchor="w", padx=14, pady=(0, 6))

        # Кнопки
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=(6, 16))

        btn_cancel = ctk.CTkButton(
            btn_bar,
            text="Скасувати",
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            width=110,
            height=36,
            command=self._cancel
        )
        btn_cancel.pack(side="right", padx=(8, 0))

        btn_start = ctk.CTkButton(
            btn_bar,
            text="⏺ Почати дозапис дій (F10 — стоп)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=36,
            command=self._confirm
        )
        btn_start.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda e: self._cancel())

    def _get_insert_index(self) -> int:
        total = len(self.actions)
        if self.target_var.get() == "end" or not self.step_options:
            return total
        val = self.combo_step.get()
        if val in self.step_options:
            idx = self.step_options.index(val)
            return idx + 1  # вставляємо після цього кроку
        return total

    def _confirm(self):
        if self.responded:
            return
        self.responded = True
        insert_idx = self._get_insert_index()
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass
        if self.on_confirm:
            self.on_confirm(insert_idx)

    def _cancel(self):
        if self.responded:
            return
        self.responded = True
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass

