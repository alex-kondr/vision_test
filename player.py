"""
Модуль відтворення сценаріїв автоматизації з підтримкою комп'ютерного зору (Smart Vision),
пауз, точок схвалення та циклів.
"""
import time
import threading
from typing import List, Callable, Optional, Dict, Any, Tuple
import pyautogui
import pynput
from models import WorkflowAction, Workflow
from vision_matcher import VisionMatcher
import winsound
import pyperclip

# Безпечна екстрена зупинка
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.02

class ActionPlayer:
    def __init__(self):
        self.workflow: Optional[Workflow] = None
        self.is_running = False
        self.is_paused = False
        self.abort_requested = False
        
        self.current_cycle = 0
        self.total_cycles = 1
        self.current_step = 0
        
        # Подія для очікування відповіді користувача в точці схвалення
        self._checkpoint_event = threading.Event()
        self._checkpoint_result = "continue"
        
        # Гаряча клавіша екстреної зупинки (Esc)
        self._esc_listener: Optional[pynput.keyboard.Listener] = None
        
        # Колбеки
        self.on_cycle_start: Optional[Callable[[int, int], None]] = None
        self.on_cycle_end: Optional[Callable[[int, int], None]] = None
        self.on_step_change: Optional[Callable[[int, int, WorkflowAction], None]] = None
        self.on_checkpoint: Optional[Callable[[WorkflowAction, int, int], None]] = None
        self.on_finished: Optional[Callable[[bool, str], None]] = None
        self.on_vision_status: Optional[Callable[[str], None]] = None
        
        self._thread: Optional[threading.Thread] = None
        self._keyboard_controller = pynput.keyboard.Controller()

    def play(self, workflow: Workflow, cycles: int = 1, speed: float = 1.0, pause_between_cycles: bool = True):
        """Запускає виконання сценарію у фоновому потоці."""
        if self.is_running:
            return
            
        self.workflow = workflow
        self.total_cycles = max(1, cycles)
        self.current_cycle = 0
        self.speed_factor = max(0.1, speed)
        self.pause_between_cycles = pause_between_cycles
        self.is_running = True
        self.is_paused = False
        self.abort_requested = False
        
        self._start_esc_listener()
        
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def abort(self):
        """Екстрене переривання виконання."""
        self.abort_requested = True
        self.is_running = False
        self._checkpoint_result = "abort"
        self._checkpoint_event.set()
        self._stop_esc_listener()

    def resume_from_checkpoint(self, action_result: str = "continue"):
        self._checkpoint_result = action_result
        if action_result == "abort":
            self.abort_requested = True
        self._checkpoint_event.set()

    def _start_esc_listener(self):
        def on_press(key):
            if key == pynput.keyboard.Key.esc:
                self.abort()

        self._esc_listener = pynput.keyboard.Listener(on_press=on_press)
        self._esc_listener.start()

    def _stop_esc_listener(self):
        if self._esc_listener:
            try:
                self._esc_listener.stop()
            except Exception:
                pass
            self._esc_listener = None

    def _run_loop(self):
        success = True
        message = "Сценарій успішно виконано!"
        
        try:
            for cycle in range(1, self.total_cycles + 1):
                if self.abort_requested:
                    break
                    
                self.current_cycle = cycle
                if self.on_cycle_start:
                    self.on_cycle_start(cycle, self.total_cycles)
                    
                # Якщо це новий цикл (починаючи з 2-го) і ввімкнено очікування вибору наступного листа
                if cycle > 1 and self.pause_between_cycles:
                    pause_action = WorkflowAction(
                        type="checkpoint",
                        title=f"Початок нового листа (Лист {cycle} з {self.total_cycles})",
                        message="Оберіть наступний документ та адресата вручну. Коли будете готові перейти до формування — натисніть 'Продовжити'."
                    )
                    if not self._handle_checkpoint(pause_action, 0, len(self.workflow.actions)):
                        break

                actions = self.workflow.actions
                total_steps = len(actions)
                
                for idx, action in enumerate(actions):
                    if self.abort_requested:
                        break
                        
                    self.current_step = idx + 1
                    if self.on_step_change:
                        self.on_step_change(idx, total_steps, action)
                        
                    if action.type == "checkpoint":
                        if not self._handle_checkpoint(action, idx, total_steps):
                            self.abort_requested = True
                            break
                    else:
                        self._execute_action(action)
                        
                if self.abort_requested:
                    break
                    
                if self.on_cycle_end:
                    self.on_cycle_end(cycle, self.total_cycles)
                    
                try:
                    winsound.Beep(1200, 100)
                except Exception:
                    pass

        except Exception as e:
            success = False
            message = f"Помилка виконання: {str(e)}"
        finally:
            self.is_running = False
            self._stop_esc_listener()
            if self.abort_requested:
                success = False
                message = "Виконання зупинено користувачем (Esc)."
                
            if self.on_finished:
                self.on_finished(success, message)

    def _handle_checkpoint(self, action: WorkflowAction, step_idx: int, total_steps: int) -> bool:
        try:
            winsound.Beep(659, 200)
            time.sleep(0.05)
            winsound.Beep(880, 250)
        except Exception:
            pass

        self._checkpoint_event.clear()
        self._checkpoint_result = "continue"
        
        if self.on_checkpoint:
            self.on_checkpoint(action, step_idx, total_steps)
            
        self._checkpoint_event.wait()
        
        if self._checkpoint_result == "abort" or self.abort_requested:
            return False
        return True

    def _resolve_click_coordinates(self, action: WorkflowAction) -> Tuple[int, int]:
        """
        Визначає реальні координати кліку:
        Якщо увімкнено Smart Vision і збережено шаблон — шукає зміщений елемент на екрані.
        Якщо ні або якщо елемент не знайдено — використовує базові координати (action.x, action.y).
        """
        target_x = action.x or 0
        target_y = action.y or 0

        # Перевірка чи використовується комп'ютерний зір
        use_vision = (
            getattr(self.workflow, "use_smart_vision", True)
            and getattr(action, "use_vision", True)
            and bool(action.template_b64)
        )

        if use_vision:
            # Спроба пошуку зі знімком
            confidence = getattr(action, "confidence", 0.75) or 0.75
            offset_x = action.template_offset_x or (action.template_width // 2 if action.template_width else 0)
            offset_y = action.template_offset_y or (action.template_height // 2 if action.template_height else 0)

            # Робимо до 2 спроб із невеликою затримкою (на випадок появи контекстного меню чи анімації)
            found = None
            for attempt in range(2):
                if self.abort_requested:
                    break
                found = VisionMatcher.find_element_on_screen(
                    template_b64=action.template_b64,
                    expected_x=target_x,
                    expected_y=target_y,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    confidence=confidence,
                    search_vicinity_radius=400
                )
                if found:
                    break
                time.sleep(0.12)

            if found:
                actual_x, actual_y, score = found
                if actual_x != target_x or actual_y != target_y:
                    msg = f"🎯 Зір виявив зміщення: ({target_x}, {target_y}) ➔ ({actual_x}, {actual_y}) [Точність: {int(score*100)}%]"
                    if self.on_vision_status:
                        self.on_vision_status(msg)
                return actual_x, actual_y
            else:
                if self.on_vision_status:
                    self.on_vision_status(f"⚠️ Елемент не виявлено зором, використовуються базові ({target_x}, {target_y})")

        return target_x, target_y

    def _execute_action(self, action: WorkflowAction):
        """Виконує одиничну дію миші або клавіатури з урахуванням затримки."""
        delay = (action.delay_before or 0.1) / self.speed_factor
        delay = max(0.05, min(delay, 10.0))
        
        time_elapsed = 0.0
        while time_elapsed < delay and not self.abort_requested:
            sleep_chunk = min(0.05, delay - time_elapsed)
            time.sleep(sleep_chunk)
            time_elapsed += sleep_chunk
            
        if self.abort_requested:
            return

        if action.type in ("click", "double_click", "right_click"):
            # Визначаємо актуальні координати (зі Smart Vision або базові)
            click_x, click_y = self._resolve_click_coordinates(action)

            if action.type == "click":
                btn = action.button if action.button in ("left", "right", "middle") else "left"
                pyautogui.click(x=click_x, y=click_y, button=btn)
            elif action.type == "double_click":
                pyautogui.doubleClick(x=click_x, y=click_y)
            elif action.type == "right_click":
                pyautogui.rightClick(x=click_x, y=click_y)
                # Коротка пауза після відкриття контекстного меню для його промальовування
                time.sleep(0.1)

        elif action.type == "key_press":
            self._type_key(action.key)
        elif action.type == "delay":
            pass

    def _type_key(self, key_str: Optional[str]):
        if not key_str:
            return
            
        key_map = {
            "enter": "enter",
            "tab": "tab",
            "space": "space",
            "backspace": "backspace",
            "delete": "delete",
            "esc": "esc",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "ctrl_l": "ctrlleft",
            "ctrl_r": "ctrlright",
            "shift_l": "shiftleft",
            "shift_r": "shiftright",
            "alt_l": "altleft",
            "alt_r": "altright",
        }
        
        mapped = key_map.get(key_str.lower())
        if mapped:
            pyautogui.press(mapped)
        elif len(key_str) == 1:
            try:
                self._keyboard_controller.type(key_str)
            except Exception:
                pyautogui.write(key_str)
        else:
            try:
                pyautogui.press(key_str)
            except Exception:
                pass
