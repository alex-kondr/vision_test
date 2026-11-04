"""
Головний модуль графічного інтерфейсу (AutoFlow Assistant).
Дозволяє записувати дії (з точками підтвердження та Smart Vision),
редагувати їх, зберігати/завантажувати та виконувати багаторазові цикли.
Підтримує багаторазове навчання: кожен запис додає нові знімки до банку Gemini Vision.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
from typing import Optional, List

from models import Workflow, WorkflowAction
from recorder import ActionRecorder
from player import ActionPlayer
from floating_bar import FloatingRecordingBar
from dialogs import (
    CheckpointModalDialog,
    EditActionDialog,
    FileSelectionContextMenu,
    AddActionDialog,
    RetrainChunkDialog,
    AppendActionsDialog
)

try:
    from gemini_vision import set_api_key, is_gemini_available
except ImportError:
    def set_api_key(k): os.environ["GEMINI_API_KEY"] = k
    def is_gemini_available(): return False

# Налаштування теми CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AutoFlowApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("AutoFlow Assistant — Автоматизація пошти та документів")
        self.geometry("1120x780")
        self.minsize(940, 680)

        # Об'єкти моделі, запису та відтворення
        self.workflow = Workflow(
            name="Новий сценарій",
            description="Автоматизація формування пошти та друку"
        )
        self.recorder = ActionRecorder(enable_smart_vision=True)
        self.player = ActionPlayer()
        
        # Лічильник навчань: кількість записів для поточного сценарію
        self._training_runs: int = 0
        self._append_insert_idx: Optional[int] = None
        self._retrain_start_idx: int = 0
        self._retrain_end_idx: Optional[int] = None

        self.floating_bar: Optional[FloatingRecordingBar] = None

        # Налаштування зворотних викликів (колбеків)
        self._setup_callbacks()

        # Побудова графічного інтерфейсу
        self._build_ui()

        # Завантажуємо Gemini API ключ з .env / змінного середовища (якщо є)
        self._load_gemini_api_key()

        # Спробуємо завантажити шаблон за замовчуванням, якщо існує
        self._load_default_template_if_exists()

    def _setup_callbacks(self):
        # Колбеки записувача
        self.recorder.on_action_recorded = self._on_recorder_action
        self.recorder.on_checkpoint_added = self._on_recorder_checkpoint
        self.recorder.on_stop_requested = self._stop_recording_from_hotkey
        self.recorder.on_pause_toggled = self._on_recorder_pause_toggled

        # Колбеки програвача
        self.player.on_cycle_start = self._on_player_cycle_start
        self.player.on_cycle_end = self._on_player_cycle_end
        self.player.on_step_change = self._on_player_step_change
        self.player.on_checkpoint = self._on_player_checkpoint
        self.player.on_file_menu_request = self._on_player_file_menu_request
        self.player.on_finished = self._on_player_finished
        self.player.on_vision_status = self._on_vision_status


    def _build_ui(self):
        # 1. Верхній заголовок
        header_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("#1e293b", "#0f172a"))
        header_frame.pack(fill="x", padx=15, pady=(15, 8))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left", padx=15, pady=10)

        lbl_app_name = ctk.CTkLabel(
            title_box,
            text="⚡ AutoFlow Assistant  [Gemini Vision + Smart Vision]",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_app_name.pack(anchor="w")

        lbl_subtitle = ctk.CTkLabel(
            title_box,
            text="Багаторазове навчання: кожен новий запис додає знімки Gemini Vision для кращого розпізнавання",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#94a3b8"
        )
        lbl_subtitle.pack(anchor="w")

        # Статусний бейдж у правому кутку
        self.lbl_status_badge = ctk.CTkLabel(
            header_frame,
            text="🟢 Готовий до роботи",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#1e3a8a",
            text_color="#93c5fd",
            corner_radius=8,
            padx=12,
            pady=6
        )
        self.lbl_status_badge.pack(side="right", padx=15, pady=15)

        # 2. Панель головних кнопок керування
        controls_frame = ctk.CTkFrame(self, corner_radius=10)
        controls_frame.pack(fill="x", padx=15, pady=5)

        # Кнопка ЗАПИСАТИ (перший запис / повне перезаписування)
        self.btn_record = ctk.CTkButton(
            controls_frame,
            text="⏺ Навчити",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=38,
            width=115,
            corner_radius=8,
            command=self.start_recording
        )
        self.btn_record.pack(side="left", padx=(12, 3), pady=8)

        # Кнопка ДОЗАПИСАТИ ДІЇ (в кінець або після конкретного кроку)
        self.btn_append = ctk.CTkButton(
            controls_frame,
            text="⏺➕ Дозапис",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            height=38,
            width=115,
            corner_radius=8,
            command=self.open_append_recording_dialog
        )
        self.btn_append.pack(side="left", padx=3, pady=8)

        # Кнопка ДОНАВЧАННЯ (повторне навчання з точки / шматками)
        self.btn_retrain = ctk.CTkButton(
            controls_frame,
            text="🧠 Донавчання",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            height=38,
            width=125,
            corner_radius=8,
            command=self.open_retrain_chunk_dialog
        )
        self.btn_retrain.pack(side="left", padx=3, pady=8)

        # Лічильник навчань 
        self.lbl_training_runs = ctk.CTkLabel(
            controls_frame,
            text="📚 0 навч.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#a78bfa",
            width=58
        )
        self.lbl_training_runs.pack(side="left", padx=(0, 4))

        sep0 = ctk.CTkFrame(controls_frame, width=2, height=34, fg_color="#334155")
        sep0.pack(side="left", padx=6, pady=8)

        # Кнопка ВІДТВОРИТИ ВСЕ
        self.btn_play = ctk.CTkButton(
            controls_frame,
            text="▶ Запустити все",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=38,
            width=135,
            corner_radius=8,
            command=self.start_playback
        )
        self.btn_play.pack(side="left", padx=3, pady=8)

        # Кнопка ВІДТВОРИТИ З ОБРАНОГО / ШМАТОК
        self.btn_play_chunk = ctk.CTkButton(
            controls_frame,
            text="▶️ З обраного",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=38,
            width=115,
            corner_radius=8,
            command=self.start_playback_from_selected
        )
        self.btn_play_chunk.pack(side="left", padx=3, pady=8)

        # Кнопка ЗУПИНИТИ
        self.btn_stop = ctk.CTkButton(
            controls_frame,
            text="⏹ Зупинити (Esc)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#475569",
            hover_color="#334155",
            height=38,
            width=120,
            corner_radius=8,
            state="disabled",
            command=self.stop_playback
        )
        self.btn_stop.pack(side="left", padx=3, pady=8)

        sep = ctk.CTkFrame(controls_frame, width=2, height=34, fg_color="#334155")
        sep.pack(side="left", padx=8, pady=8)

        # Налаштування циклів (Повторення: наприклад 50 разів)
        lbl_cycles = ctk.CTkLabel(
            controls_frame,
            text="Листів:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_cycles.pack(side="left", padx=(2, 4))

        self.spin_cycles = ctk.CTkEntry(
            controls_frame,
            width=58,
            height=32,
            font=ctk.CTkFont(size=13, weight="bold"),
            justify="center"
        )
        self.spin_cycles.insert(0, "50")
        self.spin_cycles.pack(side="left", padx=(0, 10))

        # Швидкість відтворення
        lbl_speed = ctk.CTkLabel(
            controls_frame,
            text="Швидкість:",
            font=ctk.CTkFont(size=12)
        )
        lbl_speed.pack(side="left", padx=(2, 4))

        self.combo_speed = ctk.CTkComboBox(
            controls_frame,
            values=["1.0x (Реальна)", "1.25x (Швидше)", "1.5x (Дуже швидко)", "0.8x (Спокійна)"],
            width=140,
            height=32,
            state="readonly"
        )
        self.combo_speed.set("1.0x (Реальна)")
        self.combo_speed.pack(side="left", padx=5)

        # Чекбокс Smart Vision
        self.chk_smart_vision = ctk.CTkCheckBox(
            controls_frame,
            text="🎯 Smart Vision",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8",
            onvalue=True,
            offvalue=False
        )
        self.chk_smart_vision.select()
        self.chk_smart_vision.pack(side="right", padx=8)

        # Опція паузи на початку кожного циклу
        self.chk_pause_cycle = ctk.CTkCheckBox(
            controls_frame,
            text="Чекати вибору листа",
            font=ctk.CTkFont(size=12),
            onvalue=True,
            offvalue=False
        )
        self.chk_pause_cycle.select()
        self.chk_pause_cycle.pack(side="right", padx=10)

        # 2b. Панель Gemini Vision API Key
        gemini_frame = ctk.CTkFrame(self, corner_radius=8, fg_color=("#1e1b4b", "#0a0a1a"))
        gemini_frame.pack(fill="x", padx=15, pady=(0, 4))

        lbl_gemini = ctk.CTkLabel(
            gemini_frame,
            text="🤖 Gemini Vision API:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#a78bfa"
        )
        lbl_gemini.pack(side="left", padx=(12, 8), pady=6)

        self.entry_api_key = ctk.CTkEntry(
            gemini_frame,
            placeholder_text="AIza... (Google AI Studio API Key)",
            width=350,
            height=28,
            font=ctk.CTkFont(size=12),
            show="*"
        )
        self.entry_api_key.pack(side="left", padx=(0, 8), pady=6)

        self.btn_save_key = ctk.CTkButton(
            gemini_frame,
            text="✔ Застосувати",
            font=ctk.CTkFont(size=11),
            fg_color="#4f46e5",
            hover_color="#4338ca",
            height=28,
            width=100,
            command=self._apply_gemini_api_key
        )
        self.btn_save_key.pack(side="left", padx=4, pady=6)

        self.lbl_gemini_status = ctk.CTkLabel(
            gemini_frame,
            text="❌ Не налаштовано",
            font=ctk.CTkFont(size=11),
            text_color="#f87171"
        )
        self.lbl_gemini_status.pack(side="left", padx=8, pady=6)

        lbl_gemini_hint = ctk.CTkLabel(
            gemini_frame,
            text="ℹ️ Ключ отримайте на aistudio.google.com",
            font=ctk.CTkFont(size=10),
            text_color="#64748b"
        )
        lbl_gemini_hint.pack(side="right", padx=12)

        # 3. Центральна частина — Таблиця дій сценарію
        center_frame = ctk.CTkFrame(self, corner_radius=10)
        center_frame.pack(fill="both", expand=True, padx=15, pady=5)

        list_header = ctk.CTkFrame(center_frame, fg_color="transparent")
        list_header.pack(fill="x", padx=15, pady=(8, 4))

        self.lbl_actions_count = ctk.CTkLabel(
            list_header,
            text="📋 Кроки сценарію (0 дій):",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.lbl_actions_count.pack(side="left")

        # Кнопки для збереження / завантаження
        btn_template = ctk.CTkButton(
            list_header,
            text="📄 Зразок (Пошта + 2 PDF)",
            font=ctk.CTkFont(size=11),
            fg_color="#6366f1",
            hover_color="#4f46e5",
            height=28,
            command=self._load_example_template
        )
        btn_template.pack(side="right", padx=4)

        btn_save = ctk.CTkButton(
            list_header,
            text="💾 Зберегти у файл",
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            height=28,
            command=self.save_workflow_dialog
        )
        btn_save.pack(side="right", padx=4)

        btn_open = ctk.CTkButton(
            list_header,
            text="📂 Відкрити файл",
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            height=28,
            command=self.load_workflow_dialog
        )
        btn_open.pack(side="right", padx=4)

        # Стиль для Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background="#1e293b",
            foreground="#f8fafc",
            fieldbackground="#1e293b",
            rowheight=30,
            font=("Segoe UI", 11)
        )
        style.configure(
            "Treeview.Heading",
            background="#0f172a",
            foreground="#93c5fd",
            relief="flat",
            font=("Segoe UI", 11, "bold")
        )
        style.map("Treeview", background=[("selected", "#2563eb")])

        # Таблиця дій
        tree_container = ctk.CTkFrame(center_frame, fg_color="transparent")
        tree_container.pack(fill="both", expand=True, padx=15, pady=4)

        columns = ("num", "type", "description", "vision", "delay")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("num", text="№")
        self.tree.heading("type", text="Тип дії")
        self.tree.heading("description", text="Деталі / Повідомлення")
        self.tree.heading("vision", text="Vision (знімки)")
        self.tree.heading("delay", text="Затримка")

        self.tree.column("num", width=40, anchor="center")
        self.tree.column("type", width=150, anchor="w")
        self.tree.column("description", width=520, anchor="w")
        self.tree.column("vision", width=120, anchor="center")
        self.tree.column("delay", width=80, anchor="center")

        self.tree.tag_configure("checkpoint", background="#451a03", foreground="#fde68a")
        self.tree.tag_configure("click", foreground="#e2e8f0")
        self.tree.tag_configure("area", foreground="#38bdf8")
        self.tree.tag_configure("scroll", foreground="#a78bfa")
        self.tree.tag_configure("file", foreground="#34d399")
        self.tree.tag_configure("menu", foreground="#fcd34d")
        self.tree.tag_configure("key", foreground="#cbd5e1")
        self.tree.tag_configure("running", background="#1e3a8a", foreground="#ffffff")

        scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self.edit_selected_action())
        self.tree.bind("<Button-3>", self._show_tree_context_menu)

        # Нижня панель дій над списком
        list_toolbar = ctk.CTkFrame(center_frame, fg_color="transparent")
        list_toolbar.pack(fill="x", padx=15, pady=(4, 8))

        btn_add_action = ctk.CTkButton(
            list_toolbar,
            text="➕ Додати дію",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            text_color="#ffffff",
            height=30,
            command=self.open_add_action_dialog
        )
        btn_add_action.pack(side="left", padx=(0, 6))

        btn_start_seq = ctk.CTkButton(
            list_toolbar,
            text="✨ Старт (Область ➔ До низу ➔ Файл)",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0d9488",
            hover_color="#0f766e",
            text_color="#ffffff",
            height=30,
            command=self.add_start_sequence_dialog
        )
        btn_start_seq.pack(side="left", padx=4)

        btn_add_cp = ctk.CTkButton(
            list_toolbar,
            text="➕ Точка схвалення",
            font=ctk.CTkFont(size=12),
            fg_color="#f59e0b",
            hover_color="#d97706",
            text_color="#000000",
            height=30,
            command=self.add_manual_checkpoint
        )
        btn_add_cp.pack(side="left", padx=4)


        btn_edit = ctk.CTkButton(
            list_toolbar,
            text="✏️ Редагувати крок",
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            height=30,
            command=self.edit_selected_action
        )
        btn_edit.pack(side="left", padx=4)

        btn_del = ctk.CTkButton(
            list_toolbar,
            text="🗑️ Видалити",
            font=ctk.CTkFont(size=12),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            height=30,
            command=self.delete_selected_action
        )
        btn_del.pack(side="left", padx=4)

        btn_up = ctk.CTkButton(
            list_toolbar,
            text="⬆️ Вгору",
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            width=70,
            height=30,
            command=lambda: self._move_action(-1)
        )
        btn_up.pack(side="left", padx=4)

        btn_down = ctk.CTkButton(
            list_toolbar,
            text="⬇️ Вниз",
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            width=70,
            height=30,
            command=lambda: self._move_action(1)
        )
        btn_down.pack(side="left", padx=4)

        btn_clear = ctk.CTkButton(
            list_toolbar,
            text="🧹 Очистити все",
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            height=30,
            command=self.clear_actions
        )
        btn_clear.pack(side="right")

        # 4. Нижня статусна панель та Прогрес-бар
        status_frame = ctk.CTkFrame(self, corner_radius=10)
        status_frame.pack(fill="x", padx=15, pady=(4, 12))

        self.lbl_progress_text = ctk.CTkLabel(
            status_frame,
            text="Очікування запуску. Оберіть кількість листів та натисніть 'Запустити автоматизацію'.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        self.lbl_progress_text.pack(anchor="w", padx=15, pady=(6, 2))

        self.progress_bar = ctk.CTkProgressBar(status_frame, height=10)
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=15, pady=(2, 8))

    def _refresh_table(self):
        """Оновлює відображення дій у таблиці."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        for idx, action in enumerate(self.workflow.actions, start=1):
            delay_str = f"{action.delay_before:.2f} с" if action.delay_before else "0.1 с"
            vision_badge = "-"

            if action.type == "checkpoint":
                type_str = "🛑 ТОЧКА СХВАЛЕННЯ"
                desc = f"\"{action.title}\": {action.message}"
                tag = "checkpoint"
            elif action.type == "scroll_to_bottom" or getattr(action, "scroll_to_bottom", False):
                type_str = "📜 Прокрутка списку"
                desc = "Прокрутка списку до самого низу (лише по вертикалі)"
                vision_badge = "Навігація"
                tag = "scroll"
            elif action.type == "area_click" or (getattr(action, "target_type", "") == "area" and not getattr(action, "scroll_to_bottom", False)):
                type_str = "🔲 Клік по області"
                comment_part = f" [{action.comment}]" if action.comment else ""
                area_part = f" Обл: {action.area_rect_1}" if getattr(action, "area_rect_1", None) else ""
                desc = f"Фокус області на ({action.x}, {action.y}){area_part}{comment_part}"
                vision_badge = "Область"
                tag = "area"
            elif action.type == "file_selection" or getattr(action, "show_file_menu", False):
                type_str = "📁 Вибір файлу"
                mode_str = "Контекстне меню" if getattr(action, "show_file_menu", False) else "Авто-вибір внизу"
                areas = []
                if getattr(action, "area_rect_1", None):
                    areas.append("Обл.1")
                if getattr(action, "area_rect_2", None):
                    areas.append("Обл.2")
                areas_str = f" [{'+'.join(areas)}]" if areas else ""
                prio_map = {"area_1_first": "Обл.1 спочатку", "area_2_first": "Обл.2 спочатку", "both": "Обидві"}
                prio = getattr(action, "search_priority", "area_1_first")
                prio_str = f" [{prio_map.get(prio, prio)}]" if len(areas) > 1 else ""
                elem_info = f" '{action.element_text}'" if action.element_text else ""
                desc = f"Пошук файлів на екрані{elem_info} [{mode_str}]{areas_str}{prio_str}"
                vision_badge = "🤖 Файли"
                tag = "file"
            elif action.type == "print_file":
                type_str = "🖨️ Прямий друк"
                fname = os.path.basename(action.print_file_path) if action.print_file_path else "файл"
                desc = f"Друк \"{fname}\" ➔ [{action.printer_name or 'типовий принтер'}]"
                vision_badge = "Системний"
                tag = "file"
            elif action.type == "menu_click" or getattr(action, "target_type", "") == "menu_item":
                type_str = "📋 Пункт меню"
                name_str = f" \"{action.element_text or action.uia_name}\"" if (action.element_text or action.uia_name) else ""
                desc = f"Пункт меню{name_str} на ({action.x}, {action.y})"
                if action.comment:
                    desc += f"  [{action.comment}]"
                if action.uia_name:
                    vision_badge = f"⚡ UIA: {action.uia_control_type or 'MenuItem'}"
                elif action.template_b64 and getattr(action, "use_vision", True):
                    bank = getattr(action, "template_bank", [])
                    bank_count = len(bank) if bank else 1
                    vision_badge = f"🎯 Зір [x{bank_count}]"
                else:
                    vision_badge = "🔍 OCR" if action.element_text else "Координати"
                tag = "menu"
            elif "click" in action.type:
                is_right = ("right" in action.type or action.button == "right")
                text_part = f" \"{action.element_text or action.uia_name}\"" if (action.element_text or action.uia_name) else ""
                type_str = "🖱️ Контекстне меню" if is_right else ("🖱️🖱️ Подвійний" if "double" in action.type else f"🔘 Клік{text_part}")
                desc = f"Базові: ({action.x}, {action.y})"
                if action.comment:
                    desc += f"  [{action.comment}]"
                if action.uia_name:
                    vision_badge = f"⚡ UIA: {action.uia_control_type or 'Button'}"
                elif action.template_b64 and getattr(action, "use_vision", True):
                    bank = getattr(action, "template_bank", [])
                    bank_count = len(bank) if bank else 1
                    vision_badge = f"🎯 Зір [x{bank_count}]"
                elif action.element_text:
                    vision_badge = "🔍 OCR"
                else:
                    vision_badge = "Тільки координати"
                tag = "click"
            elif "key" in action.type:
                type_str = "⌨️ Клавіша"
                desc = f"Натискання: '{action.key}'"
                tag = "key"
            elif action.type == "delay":
                type_str = "⏳ Пауза"
                desc = f"Очікування {delay_str}"
                tag = "delay"
            else:
                type_str = action.type
                desc = action.comment or ""
                tag = ""

            self.tree.insert("", "end", iid=str(idx - 1), values=(idx, type_str, desc, vision_badge, delay_str), tags=(tag,))


        total = len(self.workflow.actions)
        checkpoints_count = sum(1 for a in self.workflow.actions if a.type == "checkpoint")
        vision_count = sum(1 for a in self.workflow.actions if a.template_b64)
        max_bank = max((len(getattr(a, "template_bank", []) or []) for a in self.workflow.actions if a.template_b64), default=0)
        gemini_str = f" | 🤖 Gemini: налаштовано" if is_gemini_available() else " | 🤖 Gemini: не налаштовано"
        bank_str = f" | 📚 Банк: до {max_bank} знімків" if max_bank > 1 else ""
        self.lbl_actions_count.configure(
            text=f"📋 Кроки: {total} ({checkpoints_count} точок схвалення, {vision_count} Vision){bank_str}{gemini_str}"
        )

    # ==========================================================
    # GEMINI API KEY
    # ==========================================================
    def _load_gemini_api_key(self):
        """Завантажує Gemini API ключ з змінних середовища або файлу .env."""
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            # Спроба завантажити з .env файлу поруч з програмою
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("GEMINI_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
        if key:
            self.entry_api_key.insert(0, key)
            set_api_key(key)
            self._update_gemini_status()

    def _apply_gemini_api_key(self):
        """Застосовує введений API ключ до Gemini Vision."""
        key = self.entry_api_key.get().strip()
        if not key:
            messagebox.showwarning("Gemini API", "Будь ласка, введіть API ключ.", parent=self)
            return
        set_api_key(key)
        # Зберігаємо до .env для наступного запуску
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f'GEMINI_API_KEY="{key}"\n')
        except Exception:
            pass
        self._update_gemini_status()

    def _update_gemini_status(self):
        """Оновлює індикатор статусу Gemini Vision."""
        if is_gemini_available():
            self.lbl_gemini_status.configure(
                text="✅ Gemini Vision активний",
                text_color="#4ade80"
            )
        else:
            self.lbl_gemini_status.configure(
                text="❌ Не налаштовано",
                text_color="#f87171"
            )
        self._refresh_table()

    # ==========================================================
    # ДОНАВЧАННЯ ШМАТКАМИ (Retraining in Chunks)
    # ==========================================================
    def open_retrain_chunk_dialog(self, initial_step_idx: Optional[int] = None):
        """
        Відкриває діалогове вікно вибору початкової точки та діапазону кроків
        для повторного навчання (донавчання шматками) Gemini Vision / Smart Vision.
        """
        if self.player.is_running or self.recorder.is_recording:
            return

        if not self.workflow.actions:
            messagebox.showwarning(
                "Донавчання дій",
                "Сценарій порожній! Спочатку запишіть базові кроки (кнопка '⏺ Навчити').",
                parent=self
            )
            return

        if initial_step_idx is None:
            sel_idx = self._get_selected_action_index()
            initial_step_idx = sel_idx if sel_idx is not None else 0

        RetrainChunkDialog(
            self,
            actions=self.workflow.actions,
            initial_step_idx=initial_step_idx,
            on_confirm=self.start_retrain_chunk
        )

    def add_training_run(self):
        """Сумісність зі старим викликом — відкриває діалог донавчання з першого кроку."""
        self.open_retrain_chunk_dialog(initial_step_idx=0)

    def start_retrain_chunk(self, start_idx: int, end_idx: Optional[int] = None):
        """
        Запускає процес донавчання (повторної демонстрації) для конкретного шматка кроків.
        Нові знімки додаються до банку шаблонів поточного сценарію.
        """
        if self.recorder.is_recording or self.player.is_running:
            return

        total = len(self.workflow.actions)
        start_idx = max(0, min(start_idx, total - 1))
        eff_end = total if end_idx is None else min(end_idx, total)
        if eff_end <= start_idx:
            eff_end = min(start_idx + 1, total)

        self._retrain_start_idx = start_idx
        self._retrain_end_idx = eff_end

        # Передаємо діапазон шматка в рекордер
        self.recorder.set_existing_workflow(self.workflow, start_idx=start_idx, end_idx=eff_end)
        self.recorder.enable_smart_vision = self.chk_smart_vision.get()

        chunk_desc = f"кроки {start_idx + 1}..{eff_end}"
        self.lbl_status_badge.configure(
            text=f"🧠 ДОНАВЧ. ({chunk_desc})",
            fg_color="#6b21a8",
            text_color="#e9d5ff"
        )
        self.lbl_progress_text.configure(
            text=f"🧠 Донавчання ({chunk_desc}): виконайте дії цієї ділянки повторно. F10 — завершити."
        )

        self.floating_bar = FloatingRecordingBar(
            self,
            on_add_checkpoint=self._add_checkpoint_from_floating_bar,
            on_toggle_pause=self.recorder.toggle_pause,
            on_stop_recording=self._stop_training_run,
            on_position_changed=self._on_floating_bar_moved,
            on_set_target_type=self.recorder.set_target_type,
            on_add_scroll=self.recorder.add_scroll_to_bottom,
            on_add_file_selection=self.recorder.add_file_selection,
            mode_title="🧠 ДОНАВЧАННЯ",
            mode_color="#a855f7",
            info_text=f"Шматок: {start_idx+1}..{eff_end}"
        )

        self.iconify()
        self.recorder.start_recording()

    def _stop_training_run(self):
        """Зупиняє повторне навчання шматка та об'єднує нові знімки з банком шаблонів."""
        if not self.recorder.is_recording:
            return

        new_actions = self.recorder.stop_recording()

        if self.floating_bar:
            try:
                self.floating_bar.destroy()
            except Exception:
                pass
            self.floating_bar = None

        self.deiconify()
        self.lift()
        self.focus_force()

        # Об'єднуємо банки шаблонів для вказаного шматка
        merged, updated_count, leftover = self.recorder.merge_template_banks(new_actions)
        self.workflow.actions = merged
        self.recorder.set_existing_workflow(None)

        self._training_runs += 1
        self.lbl_training_runs.configure(
            text=f"📚 {self._training_runs} навч."
        )

        self.lbl_status_badge.configure(
            text="🟢 Навчання оновлено",
            fg_color="#1e3a8a",
            text_color="#93c5fd"
        )
        self._refresh_table()

        start_num = getattr(self, "_retrain_start_idx", 0) + 1
        end_num = getattr(self, "_retrain_end_idx", len(self.workflow.actions))
        v_count = sum(1 for a in new_actions if a.template_b64)

        extra_msg = ""
        if leftover:
            reply = messagebox.askyesno(
                "Додаткові нові кроки",
                f"Під час донавчання записано {len(leftover)} нових дій, яких не було у вихідному шматку.\n\n"
                f"Бажаєте додати їх до списку сценарію після кроку №{end_num}?",
                parent=self
            )
            if reply:
                pos = min(end_num, len(self.workflow.actions))
                self.workflow.actions[pos:pos] = leftover
                self._refresh_table()
                extra_msg = f"\n• Додано нових дій до сценарію: {len(leftover)}"

        messagebox.showinfo(
            "Донавчання завершено!",
            f"✅ Шматок кроків {start_num}..{end_num} успішно донавчено!\n\n"
            f"• Оновлено дій у банку шаблонів: {updated_count}\n"
            f"• Захоплено знімків: {v_count}\n"
            f"• Загалом запусків навчання: {self._training_runs}{extra_msg}\n\n"
            f"Gemini Vision та Smart Vision тепер мають ще більше зразків для безпомилкового розпізнавання!",
            parent=self
        )

    # ==========================================================
    # ДОЗАПИС ДІЙ (Append / Insert Recording)
    # ==========================================================
    def open_append_recording_dialog(self, selected_idx: Optional[int] = None):
        """Відкриває діалогове вікно вибору точки для дозапису нових дій у сценарій."""
        if self.player.is_running or self.recorder.is_recording:
            return

        if selected_idx is None:
            selected_idx = self._get_selected_action_index()

        AppendActionsDialog(
            self,
            actions=self.workflow.actions,
            selected_idx=selected_idx,
            on_confirm=self.start_append_recording
        )

    def start_append_recording(self, insert_idx: int):
        """Починає дозапис дій з подальшою вставкою у позицію insert_idx."""
        if self.recorder.is_recording or self.player.is_running:
            return

        total = len(self.workflow.actions)
        self._append_insert_idx = max(0, min(insert_idx, total))
        self.recorder.enable_smart_vision = self.chk_smart_vision.get()

        desc = f"після кроку #{self._append_insert_idx}" if 0 < self._append_insert_idx < total else (
            "в кінець" if self._append_insert_idx >= total else "на початок"
        )

        self.lbl_status_badge.configure(
            text="🔴 ДОЗАПИС ДІЙ",
            fg_color="#7f1d1d",
            text_color="#fca5a5"
        )
        self.lbl_progress_text.configure(
            text=f"⏺ Триває дозапис нових дій ({desc}). F8 — точка, F9 — пауза, F10 — завершити."
        )

        self.floating_bar = FloatingRecordingBar(
            self,
            on_add_checkpoint=self._add_checkpoint_from_floating_bar,
            on_toggle_pause=self.recorder.toggle_pause,
            on_stop_recording=self.stop_recording,
            on_position_changed=self._on_floating_bar_moved,
            on_set_target_type=self.recorder.set_target_type,
            on_add_scroll=self.recorder.add_scroll_to_bottom,
            on_add_file_selection=self.recorder.add_file_selection,
            mode_title="🔴 ДОЗАПИС",
            mode_color="#ef4444",
            info_text=f"Вставка: #{self._append_insert_idx}"
        )

        self.iconify()
        self.recorder.start_recording()

    # ==========================================================
    # ПОВНИЙ ЗАПИС ДІЙ
    # ==========================================================
    def start_recording(self):
        if self.recorder.is_recording or self.player.is_running:
            return

        if self.workflow.actions:
            reply = messagebox.askyesno(
                "Новий запис дій",
                "У сценарії вже є записані дії.\nОчистити список перед початком нового запису?\n\n(Ні — додасть нові дії в кінець списку)",
                parent=self
            )
            if reply:
                self.workflow.actions.clear()
                self._refresh_table()

        self._append_insert_idx = None
        self.recorder.enable_smart_vision = self.chk_smart_vision.get()

        self.lbl_status_badge.configure(
            text="🔴 ТРИВАЄ ЗАПИС ДІЙ",
            fg_color="#7f1d1d",
            text_color="#fca5a5"
        )
        self.lbl_progress_text.configure(
            text="Запис розпочато! При кліках на кнопки, документи та меню зберігаються їхні візуальні знімки. Натискайте F8 для точки схвалення. F10 — завершити."
        )

        self.floating_bar = FloatingRecordingBar(
            self,
            on_add_checkpoint=self._add_checkpoint_from_floating_bar,
            on_toggle_pause=self.recorder.toggle_pause,
            on_stop_recording=self.stop_recording,
            on_position_changed=self._on_floating_bar_moved,
            on_set_target_type=self.recorder.set_target_type,
            on_add_scroll=self.recorder.add_scroll_to_bottom,
            on_add_file_selection=self.recorder.add_file_selection,
            mode_title="🔴 ЗАПИС",
            mode_color="#ef4444"
        )

        self.iconify()
        self.recorder.start_recording()

    def _on_floating_bar_moved(self, x1, y1, x2, y2):
        self.recorder.set_ignored_region(x1, y1, x2, y2)

    def _add_checkpoint_from_floating_bar(self):
        self.recorder.add_checkpoint(
            title="Точка перевірки",
            message="Будь ласка, перевірте стан на екрані та підтвердіть продовження"
        )

    def _on_recorder_checkpoint(self, action: WorkflowAction):
        if self.floating_bar:
            self.floating_bar.show_feedback("✅ Додано точку!")

    def _on_recorder_pause_toggled(self, is_paused: bool):
        def update():
            if self.floating_bar:
                self.floating_bar.set_pause_state(is_paused)
            if is_paused:
                self.lbl_status_badge.configure(
                    text="⏸ ЗАПИС НА ПАУЗІ",
                    fg_color="#b45309",
                    text_color="#fef3c7"
                )
                self.lbl_progress_text.configure(
                    text="⏸ Запис тимчасово на паузі. Будь-які ручні дії зараз НЕ записуються. Натисніть F9, щоб продовжити запис."
                )
            else:
                self.lbl_status_badge.configure(
                    text="🔴 ТРИВАЄ ЗАПИС ДІЙ",
                    fg_color="#7f1d1d",
                    text_color="#fca5a5"
                )
                self.lbl_progress_text.configure(
                    text="▶ Запис відновлено! Дії записуються. F8 — точка схвалення, F9 — пауза, F10 — завершити."
                )
        self.after(0, update)

    def _on_recorder_action(self, action: WorkflowAction):
        def update():
            if self.floating_bar:
                self.floating_bar.update_action_count(len(self.recorder.actions))
        self.after(0, update)

    def _stop_recording_from_hotkey(self):
        self.after(0, self.stop_recording)

    def stop_recording(self):
        if not self.recorder.is_recording:
            return

        actions = self.recorder.stop_recording()

        insert_idx = getattr(self, "_append_insert_idx", None)
        if insert_idx is not None:
            insert_idx = max(0, min(insert_idx, len(self.workflow.actions)))
            self.workflow.actions[insert_idx:insert_idx] = actions
            self._append_insert_idx = None
            msg_target = f"вставлено {len(actions)} дій після кроку #{insert_idx}" if insert_idx > 0 else f"додано {len(actions)} дій на початок"
            new_select_iid = str(min(insert_idx, len(self.workflow.actions) - 1))
        else:
            self.workflow.actions.extend(actions)
            msg_target = f"записано {len(actions)} дій"
            new_select_iid = str(len(self.workflow.actions) - 1) if self.workflow.actions else "0"

        if self.floating_bar:
            try:
                self.floating_bar.destroy()
            except Exception:
                pass
            self.floating_bar = None

        self.deiconify()
        self.lift()
        self.focus_force()

        self.lbl_status_badge.configure(
            text="🟢 Запис завершено",
            fg_color="#1e3a8a",
            text_color="#93c5fd"
        )
        self._refresh_table()

        if self.tree.exists(new_select_iid):
            self.tree.selection_set(new_select_iid)
            self.tree.see(new_select_iid)

        total = len(actions)
        cps = sum(1 for a in actions if a.type == "checkpoint")
        v_anchors = sum(1 for a in actions if a.template_b64)
        messagebox.showinfo(
            "Запис завершено",
            f"Успішно {msg_target}!\n"
            f"• Точок схвалення оператора: {cps}\n"
            f"• Захоплено Smart Vision якорів: {v_anchors}\n\n"
            f"Сценарій оновлено та готовий до виконання!",
            parent=self
        )

    # ==========================================================
    # ВІДТВОРЕННЯ (PLAYBACK) ТА ЦИКЛИ (У Т.Ч. ШМАТКАМИ)
    # ==========================================================
    def start_playback(self, start_step: int = 0, end_step: Optional[int] = None):
        """Запускає виконання сценарію або вибраного шматка дій."""
        if not self.workflow.actions:
            messagebox.showwarning("Немає дій", "Сценарій порожній! Запишіть дії або завантажте зразок.", parent=self)
            return

        total_actions = len(self.workflow.actions)
        start_step = max(0, min(start_step, total_actions - 1))

        try:
            cycles = int(self.spin_cycles.get())
        except ValueError:
            cycles = 1

        speed_str = self.combo_speed.get()
        speed = 1.0
        if "1.25x" in speed_str:
            speed = 1.25
        elif "1.5x" in speed_str:
            speed = 1.5
        elif "0.8x" in speed_str:
            speed = 0.8

        pause_cycle = self.chk_pause_cycle.get()
        self.workflow.use_smart_vision = self.chk_smart_vision.get()

        self.btn_record.configure(state="disabled")
        if hasattr(self, "btn_append"):
            self.btn_append.configure(state="disabled")
        if hasattr(self, "btn_retrain"):
            self.btn_retrain.configure(state="disabled")
        self.btn_play.configure(state="disabled")
        if hasattr(self, "btn_play_chunk"):
            self.btn_play_chunk.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        eff_end = total_actions if end_step is None else min(end_step, total_actions)
        if start_step > 0 or end_step is not None:
            badge_title = f"🔵 ШМАТОК ({start_step + 1}..{eff_end})"
        else:
            badge_title = "🔵 ВИКОНАННЯ СЦЕНАРІЮ"

        self.lbl_status_badge.configure(
            text=badge_title,
            fg_color="#0369a1",
            text_color="#e0f2fe"
        )

        self.progress_bar.set(0.0)

        self.player.play(
            workflow=self.workflow,
            cycles=cycles,
            speed=speed,
            pause_between_cycles=pause_cycle,
            start_step=start_step,
            end_step=end_step
        )

    def start_playback_from_selected(self):
        """Запускає виконання сценарію, починаючи з поточного обраного в таблиці кроку."""
        sel_idx = self._get_selected_action_index()
        if sel_idx is None:
            messagebox.showinfo(
                "Виконання з кроку",
                "Оберіть крок у списку нижче, з якого бажаєте розпочати виконання.",
                parent=self
            )
            return
        self.start_playback(start_step=sel_idx)

    def test_single_action(self, step_idx: Optional[int] = None):
        """Виконує ТІЛЬКИ один окремий крок для швидкої перевірки розпізнавання та дії."""
        if step_idx is None:
            step_idx = self._get_selected_action_index()
        if step_idx is None:
            return
        self.start_playback(start_step=step_idx, end_step=step_idx + 1)

    def _get_selected_action_index(self) -> Optional[int]:
        """Повертає числовий індекс поточної вибраної дії у таблиці (0-based) або None."""
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except (ValueError, TypeError):
            return None

    def _show_tree_context_menu(self, event):
        """Відображає інтерактивне контекстне меню дій для обраного рядка списку."""
        if self.player.is_running or self.recorder.is_recording:
            return

        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)

        idx = self._get_selected_action_index()
        if idx is None or idx < 0 or idx >= len(self.workflow.actions):
            return

        act = self.workflow.actions[idx]
        step_num = idx + 1

        menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1e293b",
            fg="#f8fafc",
            activebackground="#2563eb",
            activeforeground="#ffffff",
            font=("Segoe UI", 10)
        )

        menu.add_command(
            label=f"▶️ Запустити з цього кроку (№{step_num} до кінця)",
            command=lambda: self.start_playback(start_step=idx)
        )
        menu.add_command(
            label=f"🔬 Протестувати тільки крок №{step_num}",
            command=lambda: self.test_single_action(step_idx=idx)
        )
        menu.add_separator()
        menu.add_command(
            label=f"🧠 Донавчити шматок з кроку №{step_num}...",
            command=lambda: self.open_retrain_chunk_dialog(initial_step_idx=idx)
        )
        menu.add_command(
            label=f"⏺➕ Дозаписати нові дії після кроку №{step_num}...",
            command=lambda: self.open_append_recording_dialog(selected_idx=idx)
        )
        menu.add_separator()
        menu.add_command(
            label=f"✏️ Редагувати крок №{step_num}",
            command=self.edit_selected_action
        )
        menu.add_command(
            label=f"🗑️ Видалити крок №{step_num}",
            command=self.delete_selected_action
        )
        menu.add_separator()
        menu.add_command(
            label="⬆️ Перемістити вгору",
            command=lambda: self._move_action(-1)
        )
        menu.add_command(
            label="⬇️ Перемістити вниз",
            command=lambda: self._move_action(1)
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def stop_playback(self):
        self.player.abort()

    def _on_vision_status(self, msg: str):
        def update():
            self.lbl_progress_text.configure(text=msg)
        self.after(0, update)

    def _on_player_cycle_start(self, cycle: int, total_cycles: int):
        def update():
            self.lbl_status_badge.configure(
                text=f"🔵 Лист {cycle} з {total_cycles}",
                fg_color="#0369a1",
                text_color="#e0f2fe"
            )
            self.lbl_progress_text.configure(
                text=f"Обробка листа {cycle} з {total_cycles}..."
            )
            progress = max(0.0, min(1.0, (cycle - 1) / max(1, total_cycles)))
            self.progress_bar.set(progress)
        self.after(0, update)

    def _on_player_cycle_end(self, cycle: int, total_cycles: int):
        def update():
            progress = max(0.0, min(1.0, cycle / max(1, total_cycles)))
            self.progress_bar.set(progress)
        self.after(0, update)

    def _on_player_step_change(self, step_idx: int, total_steps: int, action: WorkflowAction):
        def update():
            for item in self.tree.get_children():
                tags = list(self.tree.item(item, "tags"))
                if "running" in tags:
                    tags.remove("running")
                    self.tree.item(item, tags=tags)

            item_id = str(step_idx)
            if self.tree.exists(item_id):
                tags = list(self.tree.item(item_id, "tags"))
                if "running" not in tags:
                    tags.append("running")
                self.tree.item(item_id, tags=tags)
                self.tree.see(item_id)

            self.lbl_progress_text.configure(
                text=f"Лист {self.player.current_cycle}/{self.player.total_cycles} • Крок {step_idx + 1}/{total_steps}: {action.get_display_text()}"
            )
            start_s = getattr(self.player, "start_step", 0)
            end_s = getattr(self.player, "end_step", None) or total_steps
            span = max(1, end_s - start_s)
            curr = max(0, min(span, step_idx - start_s + 1))
            self.progress_bar.set(curr / span)
        self.after(0, update)

    def _on_player_checkpoint(self, action: WorkflowAction, step_idx: int, total_steps: int):
        def show_dialog():
            cycle_info = f"Лист {self.player.current_cycle} з {self.player.total_cycles} • Крок {step_idx + 1} з {total_steps}"
            self.lbl_status_badge.configure(
                text="⏸ ОЧІКУВАННЯ СХВАЛЕННЯ",
                fg_color="#b45309",
                text_color="#fef3c7"
            )

            dialog = CheckpointModalDialog(
                self,
                action=action,
                cycle_info=cycle_info,
                on_response=self._on_checkpoint_dialog_response
            )

        self.after(0, show_dialog)

    def _on_checkpoint_dialog_response(self, result: str):
        self.lbl_status_badge.configure(
            text=f"🔵 Лист {self.player.current_cycle} з {self.player.total_cycles}",
            fg_color="#0369a1",
            text_color="#e0f2fe"
        )
        self.player.resume_from_checkpoint(result)

    def _on_player_file_menu_request(self, files: list, action: WorkflowAction):
        def show_dialog():
            self.lbl_status_badge.configure(
                text="📁 ВИБІР ФАЙЛУ НА ЕКРАНІ",
                fg_color="#581c87",
                text_color="#f3e8ff"
            )
            FileSelectionContextMenu(
                self,
                files=files,
                on_file_selected=self._on_file_selected_from_menu
            )
        self.after(0, show_dialog)

    def _on_file_selected_from_menu(self, chosen_file: Optional[dict]):
        self.lbl_status_badge.configure(
            text=f"🔵 Лист {self.player.current_cycle} з {self.player.total_cycles}",
            fg_color="#0369a1",
            text_color="#e0f2fe"
        )
        self.player.resume_from_file_menu(chosen_file)

    def _on_player_finished(self, success: bool, message: str):
        def update():
            self.btn_record.configure(state="normal")
            if hasattr(self, "btn_append"):
                self.btn_append.configure(state="normal")
            if hasattr(self, "btn_retrain"):
                self.btn_retrain.configure(state="normal")
            self.btn_play.configure(state="normal")
            if hasattr(self, "btn_play_chunk"):
                self.btn_play_chunk.configure(state="normal")
            self.btn_stop.configure(state="disabled")

            badge_color = "#1e3a8a" if success else "#7f1d1d"
            text_color = "#93c5fd" if success else "#fca5a5"
            status_text = "🟢 Виконання завершено" if success else "⚠️ Зупинено"

            self.lbl_status_badge.configure(
                text=status_text,
                fg_color=badge_color,
                text_color=text_color
            )
            self.lbl_progress_text.configure(text=message)
            if success:
                self.progress_bar.set(1.0)

            for item in self.tree.get_children():
                tags = list(self.tree.item(item, "tags"))
                if "running" in tags:
                    tags.remove("running")
                    self.tree.item(item, tags=tags)

            if success:
                messagebox.showinfo("Готово!", f"Усі заплановані цикли успішно завершено!\n\n{message}", parent=self)
            else:
                messagebox.showwarning("Зупинено", message, parent=self)

        self.after(0, update)

    # ==========================================================
    # РУЧНЕ РЕДАГУВАННЯ СЦЕНАРІЮ
    # ==========================================================
    def open_add_action_dialog(self):
        """Відкриває діалог додавання та повного налаштування нової дії."""
        if self.player.is_running:
            messagebox.showwarning("Виконання активне", "Не можна змінювати сценарій під час його відтворення.", parent=self)
            return
        AddActionDialog(self, on_save=self._on_action_added)

    def _on_action_added(self, new_action: WorkflowAction):
        if self.player.is_running:
            return
        selected = self.tree.selection()
        if selected:
            idx = int(selected[0]) + 1
            self.workflow.actions.insert(idx, new_action)
            new_idx = str(idx)
        else:
            self.workflow.actions.append(new_action)
            new_idx = str(len(self.workflow.actions) - 1)
        self._refresh_table()
        self.tree.selection_set(new_idx)
        self.tree.see(new_idx)

    def add_start_sequence_dialog(self):
        """Додає початковий ланцюжок дій: Клік по області -> Прокрутка до низу -> Вибір файлу."""
        if self.player.is_running:
            messagebox.showwarning("Виконання активне", "Не можна змінювати сценарій під час його відтворення.", parent=self)
            return
        default_x = 500
        default_y = 400
        for a in self.workflow.actions:
            if a.x and a.y:
                default_x = a.x
                default_y = a.y
                break

        seq = [
            WorkflowAction(
                type="area_click",
                target_type="area",
                x=default_x,
                y=default_y,
                delay_before=0.5,
                comment="Клік по області списку (фокусування)"
            ),
            WorkflowAction(
                type="scroll_to_bottom",
                scroll_to_bottom=True,
                delay_before=0.5,
                comment="Прокрутка списку до самого низу"
            ),
            WorkflowAction(
                type="file_selection",
                target_type="file_item",
                show_file_menu=True,
                delay_before=0.8,
                comment="Вибір файлу внизу списку (контекстне меню знайдених файлів)"
            )
        ]

        selected = self.tree.selection()
        if selected:
            idx = int(selected[0]) + 1
            for offset, act in enumerate(seq):
                self.workflow.actions.insert(idx + offset, act)
        else:
            self.workflow.actions = seq + self.workflow.actions

        self._refresh_table()
        messagebox.showinfo(
            "Початковий блок створено",
            "Успішно створено обов'язковий початковий блок дій:\n\n"
            "1. 🔲 Клік по області списку (фокусування панелі)\n"
            "2. 📜 Прокрутка списку до самого низу\n"
            "3. 📁 Вибір файлу зі списку на екрані (контекстне меню)\n\n"
            "Ви можете відредагувати координати області, двічі клікнувши по 1-му кроку в таблиці.",
            parent=self
        )

    def add_manual_checkpoint(self):
        if self.player.is_running:
            messagebox.showwarning("Виконання активне", "Не можна змінювати сценарій під час його відтворення.", parent=self)
            return
        action = WorkflowAction(
            type="checkpoint",
            delay_before=0.5,
            title="Точка перевірки",
            message="Перевірте стан та натисніть 'Продовжити'"
        )

        selected = self.tree.selection()
        if selected:
            idx = int(selected[0]) + 1
            self.workflow.actions.insert(idx, action)
        else:
            self.workflow.actions.append(action)

        self._refresh_table()

    def edit_selected_action(self):
        if self.player.is_running:
            messagebox.showwarning("Виконання активне", "Не можна редагувати кроки під час відтворення.", parent=self)
            return
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        action = self.workflow.actions[idx]

        def on_saved(updated_action):
            self.workflow.actions[idx] = updated_action
            self._refresh_table()

        EditActionDialog(self, action, on_saved)

    def delete_selected_action(self):
        if self.player.is_running:
            messagebox.showwarning("Виконання активне", "Не можна видаляти кроки під час відтворення.", parent=self)
            return
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        del self.workflow.actions[idx]
        self._refresh_table()

    def _move_action(self, delta: int):
        if self.player.is_running:
            return
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        new_idx = idx + delta
        if 0 <= new_idx < len(self.workflow.actions):
            self.workflow.actions[idx], self.workflow.actions[new_idx] = (
                self.workflow.actions[new_idx],
                self.workflow.actions[idx],
            )
            self._refresh_table()
            self.tree.selection_set(str(new_idx))

    def clear_actions(self):
        if self.player.is_running:
            messagebox.showwarning("Виконання активне", "Не можна очищувати сценарій під час відтворення.", parent=self)
            return
        if not self.workflow.actions:
            return
        if messagebox.askyesno("Очистити", "Ви дійсно бажаєте очистити всі кроки сценарію?", parent=self):
            self.workflow.actions.clear()
            self._refresh_table()

    # ==========================================================
    # ФАЙЛОВІ ОПЕРАЦІЇ ТА ШАБЛОНИ
    # ==========================================================
    def save_workflow_dialog(self):
        if not self.workflow.actions:
            messagebox.showwarning("Порожньо", "Немає дій для збереження!", parent=self)
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Файли сценаріїв (*.json)", "*.json"), ("Усі файли", "*.*")],
            title="Зберегти сценарій",
            initialfile="mail_workflow.json",
            parent=self
        )
        if file_path:
            try:
                self.workflow.save_to_file(file_path)
                messagebox.showinfo("Збережено", f"Сценарій успішно збережено у:\n{file_path}", parent=self)
            except Exception as e:
                messagebox.showerror("Помилка збереження", str(e), parent=self)

    def load_workflow_dialog(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Файли сценаріїв (*.json)", "*.json"), ("Усі файли", "*.*")],
            title="Відкрити сценарій",
            parent=self
        )
        if file_path:
            try:
                self.workflow = Workflow.load_from_file(file_path)
                self._refresh_table()
                messagebox.showinfo("Завантажено", f"Сценарій успішно завантажено!\nКроків: {len(self.workflow.actions)}", parent=self)
            except Exception as e:
                messagebox.showerror("Помилка завантаження", str(e), parent=self)

    def _load_example_template(self):
        template_path = os.path.join(os.path.dirname(__file__), "mail_template.json")
        if os.path.exists(template_path):
            try:
                self.workflow = Workflow.load_from_file(template_path)
                self._refresh_table()
                messagebox.showinfo(
                    "Зразок завантажено",
                    "Завантажено зразок сценарію: 'Обробка пошти та друк двох PDF' з точками перевірки адреси та аркушів у принтері!\n\nВи можете записати власні кроки зі знімками кнопок та контекстних меню для вашої програми.",
                    parent=self
                )
            except Exception as e:
                messagebox.showerror("Помилка", str(e), parent=self)
        else:
            messagebox.showwarning("Не знайдено", "Файл mail_template.json не знайдено.", parent=self)

    def _load_default_template_if_exists(self):
        template_path = os.path.join(os.path.dirname(__file__), "mail_template.json")
        if os.path.exists(template_path):
            try:
                self.workflow = Workflow.load_from_file(template_path)
                self._refresh_table()
            except Exception:
                pass


if __name__ == "__main__":
    app = AutoFlowApp()
    app.mainloop()
