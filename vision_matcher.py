"""
Модуль комп'ютерного зору (Vision Matcher) для пошуку динамічних елементів,
кнопок, виділених документів та пунктів контекстного меню при їх зміщенні.

Стратегія пошуку (гібридна):
  1. Gemini Vision API  — аналізує знімок екрана та банк шаблонів, повертає координати
  2. OpenCV matchTemplate — швидкий fallback якщо Gemini недоступний або не знайшов елемент
"""
import io
import base64
import time
from typing import Optional, Tuple, Dict, Any, List
import numpy as np
import cv2
from PIL import Image, ImageGrab

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

# Gemini Vision (опціональний)
try:
    from gemini_vision import find_element_with_gemini, is_gemini_available
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    def is_gemini_available(): return False


class VisionMatcher:
    @staticmethod
    def capture_screen_image() -> Optional[np.ndarray]:
        """
        Робить знімок екрана та повертає numpy array в форматі BGR.
        Безпечно обробляє винятки (наприклад, коли екран заблоковано).
        """
        # Спроба 1: MSS (найшвидший спосіб захоплення)
        if HAS_MSS:
            try:
                with mss.mss() as sct:
                    monitor = sct.monitors[0]  # всі монітори або основний
                    sct_img = sct.grab(monitor)
                    # MSS повертає BGRA
                    img_np = np.array(sct_img)
                    return cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
            except Exception:
                pass

        # Спроба 2: PIL ImageGrab
        try:
            pil_img = ImageGrab.grab(all_screens=True)
            img_np = np.array(pil_img)
            return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        except Exception:
            return None

    @staticmethod
    def capture_template_around_point(
        x: int,
        y: int,
        width: int = 140,
        height: int = 46,
        screen_img: Optional[np.ndarray] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Вирізає шаблон навколо точки кліку (x, y) та зберігає його у форматі base64 PNG.
        Повертає словник з даними шаблону та зміщенням точки кліку всередині нього.
        """
        if screen_img is None:
            screen_img = VisionMatcher.capture_screen_image()
            
        if screen_img is None:
            return None

        h_screen, w_screen = screen_img.shape[:2]

        # Розрахунок прямокутника навколо точки
        half_w = width // 2
        half_h = height // 2

        x1 = max(0, x - half_w)
        y1 = max(0, y - half_h)
        x2 = min(w_screen, x + half_w)
        y2 = min(h_screen, y + half_h)

        if x2 - x1 < 10 or y2 - y1 < 10:
            return None

        crop = screen_img[y1:y2, x1:x2]

        # Кодування у base64 PNG
        success, encoded_img = cv2.imencode('.png', crop)
        if not success:
            return None

        b64_str = base64.b64encode(encoded_img).decode('utf-8')

        return {
            "template_b64": b64_str,
            "width": int(x2 - x1),
            "height": int(y2 - y1),
            "offset_x": int(x - x1),
            "offset_y": int(y - y1)
        }

    @staticmethod
    def b64_to_image(b64_str: str) -> Optional[np.ndarray]:
        """Декодує base64 рядок у BGR зображення OpenCV."""
        try:
            img_data = base64.b64decode(b64_str)
            np_arr = np.frombuffer(img_data, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            return img
        except Exception:
            return None

    @staticmethod
    def find_element_on_screen(
        template_b64: str,
        expected_x: int,
        expected_y: int,
        offset_x: int,
        offset_y: int,
        confidence: float = 0.75,
        search_vicinity_radius: int = 350,
        screen_img: Optional[np.ndarray] = None,
        template_bank: Optional[List[str]] = None,
        element_hint: str = "",
        use_gemini: bool = True,
    ) -> Optional[Tuple[int, int, float]]:
        """
        Шукає шаблон на поточному екрані.

        Стратегія (гібридна):
          1. Gemini Vision API (якщо доступний та увімкнений):
             - Передає знімок екрана + банк шаблонів до Gemini
             - Повертає точні координати центру елемента
          2. OpenCV matchTemplate (fallback):
             - Спочатку шукає в радіусі очікуваних координат
             - Якщо не знайдено — шукає по всьому екрану
        
        Повертає (actual_click_x, actual_click_y, confidence_score) або None.
        """
        if screen_img is None:
            screen_img = VisionMatcher.capture_screen_image()

        if screen_img is None:
            return None

        # === СТРАТЕГІЯ 1: Gemini Vision ===
        if use_gemini and HAS_GEMINI and is_gemini_available():
            bank = template_bank or ([template_b64] if template_b64 else [])
            if bank:
                result = find_element_with_gemini(
                    screen_img=screen_img,
                    template_bank=bank,
                    expected_x=expected_x,
                    expected_y=expected_y,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    element_hint=element_hint,
                )
                if result:
                    return result

        # === СТРАТЕГІЯ 2: OpenCV matchTemplate (fallback) ===
        return VisionMatcher._find_with_opencv(
            template_b64=template_b64,
            expected_x=expected_x,
            expected_y=expected_y,
            offset_x=offset_x,
            offset_y=offset_y,
            confidence=confidence,
            search_vicinity_radius=search_vicinity_radius,
            screen_img=screen_img,
            template_bank=template_bank,
        )

    @staticmethod
    def _find_with_opencv(
        template_b64: str,
        expected_x: int,
        expected_y: int,
        offset_x: int,
        offset_y: int,
        confidence: float = 0.75,
        search_vicinity_radius: int = 350,
        screen_img: Optional[np.ndarray] = None,
        template_bank: Optional[List[str]] = None,
    ) -> Optional[Tuple[int, int, float]]:
        """
        OpenCV matchTemplate пошук.
        При наявності template_bank — пробує кожен шаблон з банку (кращий виграє).
        """
        if screen_img is None:
            return None

        # Збираємо усі шаблони для перевірки (банк + основний)
        candidates = list(template_bank) if template_bank else []
        if template_b64 and template_b64 not in candidates:
            candidates.insert(0, template_b64)

        if not candidates:
            return None

        s_h, s_w = screen_img.shape[:2]
        screen_gray = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)

        best_result = None
        best_score = 0.0

        for tmpl_b64 in candidates:
            template = VisionMatcher.b64_to_image(tmpl_b64)
            if template is None:
                continue

            t_h, t_w = template.shape[:2]
            if s_h < t_h or s_w < t_w:
                continue

            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

            # ЕТАП 1: Пошук в зоні очікуваних координат (швидкий)
            if search_vicinity_radius > 0:
                vx1 = max(0, expected_x - search_vicinity_radius)
                vy1 = max(0, expected_y - search_vicinity_radius)
                vx2 = min(s_w, expected_x + search_vicinity_radius)
                vy2 = min(s_h, expected_y + search_vicinity_radius)

                if (vx2 - vx1) >= t_w and (vy2 - vy1) >= t_h:
                    vicinity_crop = screen_gray[vy1:vy2, vx1:vx2]
                    res = cv2.matchTemplate(vicinity_crop, template_gray, cv2.TM_CCOEFF_NORMED)
                    _, max_v, _, max_l = cv2.minMaxLoc(res)

                    if max_v > best_score:
                        best_score = max_v
                        found_x = vx1 + max_l[0]
                        found_y = vy1 + max_l[1]
                        best_result = (found_x + offset_x, found_y + offset_y, max_v)

            # ЕТАП 2: Глобальний пошук по всьому екрану
            res_global = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            _, max_v, _, max_l = cv2.minMaxLoc(res_global)

            if max_v > best_score:
                best_score = max_v
                best_result = (max_l[0] + offset_x, max_l[1] + offset_y, max_v)

        if best_result and best_score >= confidence:
            return best_result

        return None
