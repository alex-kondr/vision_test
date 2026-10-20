"""
Моделі даних для збереження та завантаження сценаріїв автоматизації
з підтримкою візуальних якорів (Smart Vision Templates) та банку шаблонів
для багаторазового навчання (кожен новий запис додає нові знімки елементів).
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
import json
import time

@dataclass
class WorkflowAction:
    type: str  # 'click', 'double_click', 'right_click', 'key_down', 'key_up', 'key_press', 'checkpoint', 'delay'
    delay_before: float = 0.2  # Затримка перед виконанням дії (в секундах)
    
    # Для миші (базові координати)
    x: Optional[int] = None
    y: Optional[int] = None
    button: Optional[str] = "left"  # 'left', 'right', 'middle'
    
    # Комп'ютерний зір (Smart Vision для зміщених кнопок/меню/рядків)
    template_b64: Optional[str] = None      # Знімок елемента в base64 PNG (перший / останній запис)
    template_offset_x: Optional[int] = None # Зміщення кліку від лівого краю шаблону
    template_offset_y: Optional[int] = None # Зміщення кліку від верхнього краю шаблону
    template_width: Optional[int] = None
    template_height: Optional[int] = None
    use_vision: bool = True                 # Чи використовувати візуальний пошук
    confidence: float = 0.75               # Поріг точності розпізнавання (0.0 - 1.0)
    
    # Банк шаблонів — знімки з КОЖНОГО запуску навчання (для кращого розпізнавання Gemini Vision)
    # Кожен елемент списку — base64 PNG з окремого сеансу навчання
    template_bank: List[str] = field(default_factory=list)
    
    # Для клавіатури
    key: Optional[str] = None  # назва клавіші, наприклад 'enter', 'tab', 'ctrl', тощо.
    
    # Для точки зупинки/схвалення (Checkpoint)
    title: Optional[str] = "Підтвердження користувача"
    message: Optional[str] = "Перевірте дані та натисніть 'Продовжити'"
    
    # Коментар або опис кроку
    comment: Optional[str] = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Видаляємо None поля для компактності JSON
        # template_bank зберігаємо навіть якщо порожній (щоб from_dict завжди міг відновити)
        result = {k: v for k, v in d.items() if v is not None}
        if "template_bank" not in result:
            result["template_bank"] = []
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkflowAction':
        # Забезпечуємо сумісність зі старими файлами
        valid_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def add_to_bank(self, new_template_b64: str):
        """Додає новий знімок елемента до банку шаблонів (при повторному навчанні)."""
        if new_template_b64 and new_template_b64 not in self.template_bank:
            self.template_bank.append(new_template_b64)
            # Оновлюємо основний шаблон до найновішого знімку
            self.template_b64 = new_template_b64

    def get_display_text(self) -> str:
        """Повертає зрозумілий користувачу опис кроку для відображення в списку дій."""
        delay_str = f"[{self.delay_before:.2f}с]" if self.delay_before > 0 else ""
        bank_count = len(self.template_bank)
        vision_str = f" 🎯[Зір×{bank_count}]" if self.template_b64 and self.use_vision and bank_count > 1 else (
            " 🎯[Зір]" if self.template_b64 and self.use_vision else "")
        
        if self.type == "checkpoint":
            return f"🛑 ТОЧКА СХВАЛЕННЯ: \"{self.title}\" — {self.message}"
        elif self.type == "click":
            btn_name = "Лівий клік" if self.button == "left" else ("Правий клік" if self.button == "right" else "Клік коліщатком")
            return f"🖱️ {btn_name} на ({self.x}, {self.y}){vision_str} {delay_str}"
        elif self.type == "double_click":
            return f"🖱️🖱️ Подвійний клік на ({self.x}, {self.y}){vision_str} {delay_str}"
        elif self.type == "right_click":
            return f"🖱️ Контекстне меню (правий клік) на ({self.x}, {self.y}){vision_str} {delay_str}"
        elif self.type == "key_press":
            return f"⌨️ Клавіша: '{self.key}' {delay_str}"
        elif self.type == "delay":
            return f"⏳ Пауза / Очікування {self.delay_before:.2f} сек"
        return f"Дія: {self.type} {delay_str}"


@dataclass
class Workflow:
    name: str = "Сценарій обробки пошти"
    description: str = "Автоматизація формування листів та друку PDF"
    actions: List[WorkflowAction] = field(default_factory=list)
    speed_factor: float = 1.0
    use_smart_vision: bool = True
    created_at: float = field(default_factory=time.time)

    def to_json(self, indent: int = 2) -> str:
        data = {
            "name": self.name,
            "description": self.description,
            "speed_factor": self.speed_factor,
            "use_smart_vision": self.use_smart_vision,
            "created_at": self.created_at,
            "actions": [a.to_dict() for a in self.actions]
        }
        return json.dumps(data, ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> 'Workflow':
        data = json.loads(json_str)
        actions = [WorkflowAction.from_dict(a) for a in data.get("actions", [])]
        return cls(
            name=data.get("name", "Сценарій"),
            description=data.get("description", ""),
            speed_factor=data.get("speed_factor", 1.0),
            use_smart_vision=data.get("use_smart_vision", True),
            created_at=data.get("created_at", time.time()),
            actions=actions
        )

    def save_to_file(self, file_path: str):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def load_from_file(cls, file_path: str) -> 'Workflow':
        with open(file_path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())
