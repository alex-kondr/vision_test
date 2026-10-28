"""
Модуль UI Automation (Шар 1 гібридної системи автоматизації).
Використовує Windows UI Automation (pywinauto та uiautomation) для семантичної взаємодії:
- Захоплення властивостей елемента під курсором при записі (назва, тип, automation_id, вікно)
- Пошук та клік по елементу за його семантичними властивостями незалежно від зміщення вікна (на 10-25% чи більше)
- Читання реальних рядків та файлів зі списків/таблиць Windows без вигадування координат
"""
import re
import time
import logging
import warnings
from typing import Optional, Tuple, Dict, Any, List

warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")

logger = logging.getLogger("UIAManager")

try:
    import uiautomation as auto
    HAS_UIAUTOMATION = True
except ImportError:
    HAS_UIAUTOMATION = False
    logger.warning("uiautomation не встановлено")

try:
    from pywinauto import Desktop
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto import uia_element_info
    HAS_PYWINAUTO = True
except ImportError:
    HAS_PYWINAUTO = False
    logger.warning("pywinauto не встановлено")


class UIAManager:
    """Менеджер взаємодії з Windows UI Automation."""

    @staticmethod
    def is_available() -> bool:
        return HAS_UIAUTOMATION or HAS_PYWINAUTO

    @staticmethod
    def get_element_at_point(x: int, y: int) -> Dict[str, Any]:
        """
        Визначає елемент інтерфейсу під вказаними координатами (x, y)
        та повертає його семантичний локатор.
        """
        locator = {
            "window_title": "",
            "window_class": "",
            "control_type": "",
            "name": "",
            "automation_id": "",
            "class_name": "",
            "bounding_rect": None,
        }

        # 1. Спроба через uiautomation
        if HAS_UIAUTOMATION:
            try:
                ctrl = auto.ControlFromPoint(x, y)
                if ctrl:
                    locator["name"] = ctrl.Name or ""
                    locator["control_type"] = ctrl.ControlTypeName.replace("Control", "") if ctrl.ControlTypeName else ""
                    locator["automation_id"] = ctrl.AutomationId or ""
                    locator["class_name"] = ctrl.ClassName or ""
                    rect = ctrl.BoundingRectangle
                    if rect:
                        locator["bounding_rect"] = (rect.left, rect.top, rect.right, rect.bottom)

                    # Шукаємо батьківське вікно верхнього рівня
                    curr = ctrl
                    root = auto.GetRootControl()
                    while curr:
                        p = curr.GetParentControl()
                        if not p or p == root:
                            locator["window_title"] = curr.Name or ""
                            locator["window_class"] = curr.ClassName or ""
                            break
                        curr = p
                    return locator
            except Exception as e:
                logger.debug(f"uiautomation.ControlFromPoint помилка: {e}")

        # 2. Fallback через pywinauto
        if HAS_PYWINAUTO:
            try:
                elem = uia_element_info.UIAElementInfo.from_point(x, y)
                if elem:
                    locator["name"] = elem.name or ""
                    locator["control_type"] = elem.control_type or ""
                    locator["automation_id"] = elem.automation_id or ""
                    locator["class_name"] = elem.class_name or ""
                    rect = elem.rectangle
                    if rect:
                        locator["bounding_rect"] = (rect.left, rect.top, rect.right, rect.bottom)
                    top = uia_element_info.UIAElementInfo.top_from_point(x, y)
                    if top:
                        locator["window_title"] = top.name or ""
                        locator["window_class"] = top.class_name or ""
                    return locator
            except Exception as e:
                logger.debug(f"pywinauto UIA from_point помилка: {e}")

        return locator

    @staticmethod
    def find_element(
        locator: Dict[str, Any],
        timeout: float = 1.5,
        target_name: Optional[str] = None
    ) -> Optional[Tuple[int, int]]:
        """
        Шукає елемент за його UIA-локатором та повертає екранні координати його центру (center_x, center_y).
        Якщо передано target_name, він використовується як пріоритетна назва елемента.
        """
        name = target_name or locator.get("name") or locator.get("uia_name") or locator.get("fallback_text") or ""
        control_type = locator.get("control_type") or locator.get("uia_control_type") or ""
        window_title = locator.get("window_title") or locator.get("uia_window") or ""
        automation_id = locator.get("automation_id") or locator.get("uia_automation_id") or ""

        if not name and not automation_id and not control_type:
            return None

        # 1. Пошук через uiautomation
        if HAS_UIAUTOMATION:
            try:
                start_time = time.time()
                while time.time() - start_time < timeout:
                    target_control = None

                    # Якщо вказано заголовок вікна — шукаємо спершу вікно
                    root = auto.GetRootControl()
                    search_scope = root
                    if window_title:
                        # Шукаємо вікно за назвою або підрядком
                        for w in root.GetChildren():
                            if window_title.lower() in (w.Name or "").lower():
                                search_scope = w
                                break

                    # Шукаємо елемент всередині search_scope
                    def match_fn(ctrl: auto.Control, depth: int) -> bool:
                        # Якщо шукаємо пункт меню чи кнопку
                        ctrl_type = (ctrl.ControlTypeName or "").replace("Control", "")
                        if control_type and ctrl_type.lower() != control_type.lower():
                            return False
                        if automation_id and ctrl.AutomationId == automation_id:
                            return True
                        if name:
                            ctrl_name = ctrl.Name or ""
                            if ctrl_name == name or name.lower() in ctrl_name.lower():
                                return True
                        return False

                    target_control = search_scope.FindControl(match_fn, maxDepth=12)
                    if target_control:
                        rect = target_control.BoundingRectangle
                        if rect and (rect.right > rect.left) and (rect.bottom > rect.top):
                            cx = (rect.left + rect.right) // 2
                            cy = (rect.top + rect.bottom) // 2
                            return cx, cy

                    time.sleep(0.1)
            except Exception as e:
                logger.debug(f"uiautomation пошук елемента завершився помилкою: {e}")

        # 2. Пошук через pywinauto
        if HAS_PYWINAUTO and (name or automation_id):
            try:
                desktop = Desktop(backend="uia")
                # Шукаємо серед усіх активних вікон
                for win in desktop.windows():
                    win_text = win.window_text()
                    if window_title and window_title.lower() not in win_text.lower():
                        continue
                    try:
                        kwargs = {}
                        if name:
                            kwargs["title_re"] = f".*{re.escape(name)}.*"
                        if control_type:
                            kwargs["control_type"] = control_type
                        if automation_id:
                            kwargs["auto_id"] = automation_id

                        child = win.child_window(**kwargs)
                        if child.exists(timeout=0.2):
                            r = child.rectangle()
                            return (r.left + r.right) // 2, (r.top + r.bottom) // 2
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"pywinauto пошук елемента завершився помилкою: {e}")

        return None

    @staticmethod
    def get_list_items(
        window_title: str = "",
        area_rect: Optional[Tuple[int, int, int, int]] = None
    ) -> List[Dict[str, Any]]:
        """
        Зчитує реальний вміст списків/таблиць через UI Automation (ListItem, DataItem, TreeItem, Text).
        Повертає список знайдених елементів з їхніми назвами та координатами:
        [{'name': 'Назва_файлу.pdf', 'x': 450, 'y': 720}, ...]
        """
        results = []
        if not HAS_UIAUTOMATION:
            return results

        try:
            root = auto.GetRootControl()
            search_scope = root
            if window_title:
                for w in root.GetChildren():
                    if window_title.lower() in (w.Name or "").lower():
                        search_scope = w
                        break

            item_types = {"ListItemControl", "DataItemControl", "TreeItemControl", "CustomControl", "TextControl"}

            def collector(ctrl: auto.Control, depth: int) -> bool:
                if ctrl.ControlTypeName in item_types:
                    name = (ctrl.Name or "").strip()
                    rect = ctrl.BoundingRectangle
                    if name and rect and (rect.right > rect.left) and (rect.bottom > rect.top):
                        cx = (rect.left + rect.right) // 2
                        cy = (rect.top + rect.bottom) // 2
                        if area_rect:
                            x1, y1, x2, y2 = area_rect
                            if not (x1 <= cx <= x2 and y1 <= cy <= y2):
                                return False
                        results.append({
                            "name": name,
                            "x": cx,
                            "y": cy,
                            "control_type": ctrl.ControlTypeName.replace("Control", "")
                        })
                return False

            search_scope.FindControl(collector, maxDepth=14)
        except Exception as e:
            logger.debug(f"get_list_items помилка: {e}")

        # Видаляємо дублікати за координатами
        unique = []
        seen = set()
        for item in results:
            key = (item["name"], item["x"] // 10, item["y"] // 10)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    @staticmethod
    def scroll_to_bottom(
        window_title: str = "",
        x: Optional[int] = None,
        y: Optional[int] = None
    ) -> bool:
        """
        Прокручує список або таблицю до самого кінця за допомогою UIA ScrollPattern або клавіші End.
        """
        if HAS_UIAUTOMATION and x is not None and y is not None:
            try:
                ctrl = auto.ControlFromPoint(x, y)
                if ctrl:
                    scroll_pattern = ctrl.GetScrollPattern()
                    if scroll_pattern:
                        scroll_pattern.SetScrollPercent(auto.ScrollPercent.NoScroll, 100.0)
                        return True
            except Exception:
                pass

        # Універсальний спосіб: клік у фокус списку та надсилання End
        try:
            import pyautogui
            if x is not None and y is not None:
                pyautogui.click(x, y)
                time.sleep(0.08)
            pyautogui.press('end')
            return True
        except Exception:
            return False
