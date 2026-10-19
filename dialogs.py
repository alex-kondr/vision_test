"""
Діалогові вікна: вікно очікування схвалення користувача (Checkpoint Modal)
та редактор параметрів дій (з підтримкою Smart Vision).
"""
import customtkinter as ctk
from typing import Callable, Optional
from models import WorkflowAction

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
            text="💡 Натисніть Enter або кнопку нижче для продовження. Esc — зупинити все.",
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
            text="✅ Продовжити (Enter)",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            height=40,
            corner_radius=8,
            command=lambda: self._respond("continue")
        )
        self.btn_continue.pack(side="right", fill="x", expand=True)

        self.bind("<Return>", lambda e: self._respond("continue"))
        self.bind("<space>", lambda e: self._respond("continue"))
        self.bind("<Escape>", lambda e: self._respond("abort"))
        self.protocol("WM_DELETE_WINDOW", lambda: self._respond("abort"))

    def _respond(self, result: str):
        if self.responded:
            return
        self.responded = True
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass
        self.on_response(result)


class EditActionDialog(ctk.CTkToplevel):
    def __init__(self, master, action: WorkflowAction, on_save: Callable[[WorkflowAction], None]):
        super().__init__(master)
        self.action = action
        self.on_save = on_save
        
        self.title("Редагування кроку")
        self.geometry("490x440")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.grab_set()

        frame = ctk.CTkFrame(self, corner_radius=10)
        frame.pack(fill="both", expand=True, padx=15, pady=15)

        lbl_header = ctk.CTkLabel(
            frame, 
            text=f"Параметри дії: {action.type.upper()}",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        )
        lbl_header.pack(anchor="w", padx=15, pady=(10, 10))

        # Затримка
        lbl_delay = ctk.CTkLabel(frame, text="Затримка перед дією (сек):")
        lbl_delay.pack(anchor="w", padx=15, pady=(0, 2))
        self.entry_delay = ctk.CTkEntry(frame)
        self.entry_delay.pack(fill="x", padx=15, pady=(0, 10))
        self.entry_delay.insert(0, str(action.delay_before))

        # Якщо це точка схвалення:
        if action.type == "checkpoint":
            lbl_title = ctk.CTkLabel(frame, text="Назва точки перевірки:")
            lbl_title.pack(anchor="w", padx=15, pady=(0, 2))
            self.entry_title = ctk.CTkEntry(frame)
            self.entry_title.pack(fill="x", padx=15, pady=(0, 10))
            self.entry_title.insert(0, action.title or "")

            lbl_msg = ctk.CTkLabel(frame, text="Текст підказки для оператора:")
            lbl_msg.pack(anchor="w", padx=15, pady=(0, 2))
            self.entry_msg = ctk.CTkTextbox(frame, height=80)
            self.entry_msg.pack(fill="x", padx=15, pady=(0, 10))
            self.entry_msg.insert("1.0", action.message or "")
            self.chk_vision = None
            self.entry_conf = None
        else:
            self.entry_title = None
            self.entry_msg = None
            
            if action.x is not None and action.y is not None:
                lbl_coords = ctk.CTkLabel(
                    frame, 
                    text=f"Базові координати: X={action.x}, Y={action.y} (Кнопка: {action.button})"
                )
                lbl_coords.pack(anchor="w", padx=15, pady=3)

                # Блок Smart Vision
                has_template = bool(action.template_b64)
                vision_status = f"✅ Знімок елемента прив'язано ({action.template_width}x{action.template_height} px)" if has_template else "❌ Знімок відсутній (тільки точні координати)"
                
                lbl_v_status = ctk.CTkLabel(
                    frame,
                    text=vision_status,
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#10b981" if has_template else "#94a3b8"
                )
                lbl_v_status.pack(anchor="w", padx=15, pady=(5, 5))

                self.chk_vision = ctk.CTkCheckBox(
                    frame,
                    text="Використовувати Smart Vision (пошук за зміщенням)",
                    font=ctk.CTkFont(size=12),
                    onvalue=True,
                    offvalue=False
                )
                if getattr(action, "use_vision", True) and has_template:
                    self.chk_vision.select()
                else:
                    self.chk_vision.deselect()
                self.chk_vision.pack(anchor="w", padx=15, pady=5)

                lbl_conf = ctk.CTkLabel(frame, text="Поріг точності розпізнавання (0.6 - 0.95):")
                lbl_conf.pack(anchor="w", padx=15, pady=(5, 2))
                self.entry_conf = ctk.CTkEntry(frame)
                self.entry_conf.pack(fill="x", padx=15, pady=(0, 10))
                self.entry_conf.insert(0, str(getattr(action, "confidence", 0.75) or 0.75))
            else:
                self.chk_vision = None
                self.entry_conf = None
                if action.key is not None:
                    lbl_key = ctk.CTkLabel(frame, text=f"Клавіша: '{action.key}'")
                    lbl_key.pack(anchor="w", padx=15, pady=5)

        btn_save = ctk.CTkButton(
            frame,
            text="Зберегти зміни",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#3b82f6",
            command=self._save
        )
        btn_save.pack(fill="x", padx=15, pady=15)

    def _save(self):
        try:
            self.action.delay_before = float(self.entry_delay.get())
        except ValueError:
            pass

        if self.entry_title:
            self.action.title = self.entry_title.get()
        if self.entry_msg:
            self.action.message = self.entry_msg.get("1.0", "end-1c")

        if self.chk_vision:
            self.action.use_vision = self.chk_vision.get()
        if self.entry_conf:
            try:
                self.action.confidence = float(self.entry_conf.get())
            except ValueError:
                pass

        self.on_save(self.action)
        self.destroy()
