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

try:
    from gemini_vision import is_gemini_available
except ImportError:
    def is_gemini_available(): return False

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
        
        # Подія для вибору файлу з контекстного меню
        self._file_menu_event = threading.Event()
        self._selected_file_result: Optional[dict] = None
        
        # Гаряча клавіша екстреної зупинки (Esc)
        self._esc_listener: Optional[pynput.keyboard.Listener] = None
        
        # Колбеки
        self.on_cycle_start: Optional[Callable[[int, int], None]] = None
        self.on_cycle_end: Optional[Callable[[int, int], None]] = None
        self.on_step_change: Optional[Callable[[int, int, WorkflowAction], None]] = None
        self.on_checkpoint: Optional[Callable[[WorkflowAction, int, int], None]] = None
        self.on_file_menu_request: Optional[Callable[[List[dict], WorkflowAction], None]] = None
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
        self._file_menu_event.set()
        self._stop_esc_listener()

    def resume_from_checkpoint(self, action_result: str = "continue"):
        self._checkpoint_result = action_result
        if action_result == "abort":
            self.abort_requested = True
        self._checkpoint_event.set()

    def resume_from_file_menu(self, file_dict: Optional[dict]):
        """Отримує обраний файл із контекстного меню та продовжує роботу."""
        self._selected_file_result = file_dict
        self._file_menu_event.set()


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
        1. Для кліку по області (area_click): використовує координати зони фокусування.
        2. Для конкретного елемента / кнопки / пункту меню:
           a. Gemini Vision API (якщо доступний) — аналізує весь банк шаблонів, семантичний текст
              ('Додаткові дії') та знаходить елемент навіть при зміщенні на 10-25%.
           b. OpenCV matchTemplate — fallback у радіусі 500px або по всьому екрану.
        3. Якщо нічого не знайдено — використовує базові координати (action.x, action.y).
        """
        target_x = action.x or 0
        target_y = action.y or 0

        # Клік по області — не потребує піксельного шаблону, клікає для фокусу списку/панелі
        if action.type == "area_click" or getattr(action, "target_type", "") == "area":
            return target_x, target_y

        elem_text = getattr(action, "element_text", "") or ""
        target_type = getattr(action, "target_type", "element") or "element"

        # Перевірка чи використовується комп'ютерний зір
        use_vision = (
            getattr(self.workflow, "use_smart_vision", True)
            and getattr(action, "use_vision", True)
            and (bool(action.template_b64) or bool(elem_text))
        )

        if use_vision:
            confidence = getattr(action, "confidence", 0.75) or 0.75
            offset_x = action.template_offset_x or (action.template_width // 2 if action.template_width else 0)
            offset_y = action.template_offset_y or (action.template_height // 2 if action.template_height else 0)

            # Банк шаблонів з усіх попередніх сеансів навчання
            bank = getattr(action, "template_bank", []) or []

            # Текстова підказка для Gemini Vision (коментар кроку)
            hint = getattr(action, "comment", "") or ""

            # Повідомляємо про режим пошуку
            gemini_on = is_gemini_available()
            if self.on_vision_status:
                bank_info = f" [банк: {len(bank)} знімків]" if bank else ""
                name_info = f" \"{elem_text}\"" if elem_text else ""
                mode_str = "Gemini Vision" if gemini_on else "OpenCV"
                self.on_vision_status(f"🔍 {mode_str}: пошук елемента{name_info}{bank_info}...")

            # Робимо до 2 спроб із невеликою затримкою
            found = None
            for attempt in range(2):
                if self.abort_requested:
                    break
                found = VisionMatcher.find_element_on_screen(
                    template_b64=action.template_b64 or "",
                    expected_x=target_x,
                    expected_y=target_y,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    confidence=confidence,
                    search_vicinity_radius=500,
                    template_bank=bank,
                    element_hint=hint,
                    element_text=elem_text,
                    target_type=target_type,
                    use_gemini=gemini_on,
                )
                if found:
                    break
                time.sleep(0.15)

            if found:
                actual_x, actual_y, score = found
                if actual_x != target_x or actual_y != target_y:
                    mode = "🤖 Gemini" if gemini_on else "🎯 OpenCV"
                    label = f" \"{elem_text}\"" if elem_text else ""
                    msg = f"{mode} знайшов{label} зі зміщенням: ({target_x}, {target_y}) ➔ ({actual_x}, {actual_y}) [Точність: {int(score*100)}%]"
                    if self.on_vision_status:
                        self.on_vision_status(msg)
                else:
                    if self.on_vision_status:
                        self.on_vision_status(f"✅ Елемент знайдено на ({actual_x}, {actual_y}) [Точність: {int(score*100)}%]")
                return actual_x, actual_y
            else:
                if self.on_vision_status:
                    self.on_vision_status(f"⚠️ Елемент не знайдено, використовуються базові ({target_x}, {target_y})")

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

        # 1. Прокрутка списку виключно вниз (по осі X не рухаємо) – спрощена реалізація
        if action.type == "scroll_to_bottom" or getattr(action, "scroll_to_bottom", False):
            if self.on_vision_status:
                self.on_vision_status("📜 Вертикальна прокрутка списку вниз (вісь X зафіксована)...")
            # Прокручування коліщатком вниз
            for _ in range(10):
                if self.abort_requested:
                    break
                pyautogui.scroll(-500)
                time.sleep(0.02)
            # Додаткові натискання PageDown для гарантованого переходу до кінця
            try:
                for _ in range(2):
                    pyautogui.press("pagedown")
                    time.sleep(0.05)
            except Exception:
                pass
            time.sleep(0.15)
            return

        # 2. Вибір файлу зі списку на екрані (з відображенням контекстного меню або авто)
        if action.type == "file_selection" or getattr(action, "show_file_menu", False):
            rect1 = getattr(action, "area_rect_1", None)
            rect2 = getattr(action, "area_rect_2", None)
            priority = getattr(action, "search_priority", "area_1_first")
            
            area_desc = ""
            if rect1 and rect2:
                pr_text = "Область 1 ➔ 2" if priority == "area_1_first" else ("Область 2 ➔ 1" if priority == "area_2_first" else "Область 1 + 2")
                area_desc = f" (за 2 областями, {pr_text})"
            elif rect1:
                area_desc = f" (в Області 1: {rect1})"

            if self.on_vision_status:
                self.on_vision_status(f"🔍 Сканування екрана: пошук списку файлів{area_desc}...")

            # Шукаємо файли на екрані за двома областями з урахуванням пріоритету
            files = VisionMatcher.detect_files_with_priority(
                area_rect_1=rect1,
                area_rect_2=rect2,
                priority=priority
            )

            if getattr(action, "show_file_menu", False) and self.on_file_menu_request:
                self._file_menu_event.clear()
                self._selected_file_result = None
                self.on_file_menu_request(files, action)
                self._file_menu_event.wait()
                
                if self.abort_requested:
                    return

                chosen = self._selected_file_result
                if chosen and "x" in chosen and "y" in chosen:
                    cx = chosen["x"]
                    cy = chosen["y"]
                    fname = chosen.get("name", "файл")
                    if self.on_vision_status:
                        self.on_vision_status(f"📄 Вибрано файл: {fname} на ({cx}, {cy})")
                    pyautogui.click(x=cx, y=cy)
                    time.sleep(0.15)
            else:
                # Автоматичний вибір: клікаємо на останній файл у списку (найнижчий)
                if files:
                    bottom_file = max(files, key=lambda f: f.get("y", 0))
                    cx = bottom_file["x"]
                    cy = bottom_file["y"]
                    fname = bottom_file.get("name", "файл")
                    if self.on_vision_status:
                        self.on_vision_status(f"📄 Авто-вибір останнього файлу: {fname} на ({cx}, {cy})")
                    pyautogui.click(x=cx, y=cy)
                elif action.x and action.y:
                    pyautogui.click(x=action.x, y=action.y)
                time.sleep(0.15)
            return

        # 3. Кліки (по області, кнопці, подвійний або контекстне меню)
        if action.type in ("click", "double_click", "right_click", "area_click", "menu_click"):
            # Клік по області (фокусування вікна списку)
            if action.type == "area_click" or getattr(action, "target_type", "") == "area":
                rect1 = getattr(action, "area_rect_1", None)
                if rect1:
                    click_x = (rect1[0] + rect1[2]) // 2
                    click_y = (rect1[1] + rect1[3]) // 2
                else:
                    click_x = action.x or 500
                    click_y = action.y or 500
                if self.on_vision_status:
                    self.on_vision_status(f"🔲 Клік по області списку на ({click_x}, {click_y})")
                pyautogui.click(x=click_x, y=click_y, button="left")
                time.sleep(0.15)
                return


            # Визначаємо актуальні координати (зі Smart Vision або базові)
            click_x, click_y = self._resolve_click_coordinates(action)

            # Захист від нульових координат — запобігаємо PyAutoGUI fail-safe (кут 0,0)
            if click_x <= 5 and click_y <= 5:
                if self.on_vision_status:
                    self.on_vision_status(f"⚠️ Пропуск кліку: координати ({click_x}, {click_y}) занадто близько до кута екрана (fail-safe захист)")
                return

            if action.type in ("click", "menu_click"):
                btn = action.button if action.button in ("left", "right", "middle") else "left"
                pyautogui.click(x=click_x, y=click_y, button=btn)
            elif action.type == "double_click":
                pyautogui.doubleClick(x=click_x, y=click_y)
            elif action.type == "right_click":
                pyautogui.rightClick(x=click_x, y=click_y)
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
