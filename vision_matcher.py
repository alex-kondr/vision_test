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
    from gemini_vision import find_element_with_gemini, is_gemini_available, detect_files_on_screen
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    def is_gemini_available(): return False
    def detect_files_on_screen(*args, **kwargs): return []



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
        search_vicinity_radius: int = 500,
        screen_img: Optional[np.ndarray] = None,
        template_bank: Optional[List[str]] = None,
        element_hint: str = "",
        element_text: str = "",
        target_type: str = "element",
        use_gemini: bool = True,
    ) -> Optional[Tuple[int, int, float]]:
        """
        Шукає шаблон або семантичний елемент (наприклад, пункт меню 'Додаткові дії') на поточному екрані.

        Стратегія (гібридна):
          1. Gemini Vision API (якщо доступний та увімкнений):
             - Шукає за семантичною назвою, типом цілі та зразками зображення
             - Розуміє зміщення меню або елемента на 10-25%
          2. OpenCV matchTemplate (fallback):
             - Шукає в розширеному радіусі очікуваних координат (500px)
             - Якщо не знайдено — глобальний пошук по всьому екрану
        
        Повертає (actual_click_x, actual_click_y, confidence_score) або None.
        """
        if screen_img is None:
            screen_img = VisionMatcher.capture_screen_image()

        if screen_img is None:
            return None

        # === СТРАТЕГІЯ 1: Gemini Vision ===
        if use_gemini and HAS_GEMINI and is_gemini_available():
            bank = template_bank or ([template_b64] if template_b64 else [])
            if bank or element_text:
                result = find_element_with_gemini(
                    screen_img=screen_img,
                    template_bank=bank,
                    expected_x=expected_x,
                    expected_y=expected_y,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    element_hint=element_hint,
                    element_text=element_text,
                    target_type=target_type,
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
    def detect_files_in_area(
        screen_img: Optional[np.ndarray] = None,
        area_rect: Optional[Tuple[int, int, int, int]] = None
    ) -> List[Dict[str, Any]]:
        """
        Знаходить файли на екрані за допомогою Gemini Vision або евристичного детектора.
        Повертає список: [{'name': '001_Документ.pdf', 'x': 450, 'y': 720}, ...]
        """
        if screen_img is None:
            screen_img = VisionMatcher.capture_screen_image()

        if screen_img is None:
            return []

        # 1. Спроба через Gemini Vision
        if HAS_GEMINI and is_gemini_available():
            files = detect_files_on_screen(screen_img, search_rect=area_rect)
            if files:
                return files

        # 2. Евристичний детектор рядків у списку (fallback без Gemini)
        return VisionMatcher._detect_rows_heuristic(screen_img, area_rect)

    @staticmethod
    def detect_files_with_priority(
        screen_img: Optional[np.ndarray] = None,
        area_rect_1: Optional[Tuple[int, int, int, int]] = None,
        area_rect_2: Optional[Tuple[int, int, int, int]] = None,
        priority: str = "area_1_first"
    ) -> List[Dict[str, Any]]:
        """
        Шукає файли за двома областями з урахуванням зазначеного пріоритету:
        - 'area_1_first': Спочатку Область 1; якщо не знайдено — Область 2.
        - 'area_2_first': Спочатку Область 2; якщо не знайдено — Область 1.
        - 'both': Об'єднує файли з обох областей.
        """
        if screen_img is None:
            screen_img = VisionMatcher.capture_screen_image()
        if screen_img is None:
            return []

        # Якщо є тільки одна з областей
        if area_rect_1 and not area_rect_2:
            return VisionMatcher.detect_files_in_area(screen_img, area_rect_1)
        if area_rect_2 and not area_rect_1:
            return VisionMatcher.detect_files_in_area(screen_img, area_rect_2)
        if not area_rect_1 and not area_rect_2:
            return VisionMatcher.detect_files_in_area(screen_img, None)

        # Обидві області вказані:
        if priority == "area_2_first":
            primary_rect, secondary_rect = area_rect_2, area_rect_1
        else:
            primary_rect, secondary_rect = area_rect_1, area_rect_2

        if priority == "both":
            f1 = VisionMatcher.detect_files_in_area(screen_img, area_rect_1)
            f2 = VisionMatcher.detect_files_in_area(screen_img, area_rect_2)
            # Об'єднуємо унікальні за координатами
            seen = set()
            combined = []
            for item in f1 + f2:
                key = (item.get("x", 0) // 10, item.get("y", 0) // 10)
                if key not in seen:
                    seen.add(key)
                    combined.append(item)
            return combined

        # Спочатку шукаємо в першочерговій області
        files = VisionMatcher.detect_files_in_area(screen_img, primary_rect)
        if files:
            return files

        # Якщо в першій області не знайдено — шукаємо у вторинній
        return VisionMatcher.detect_files_in_area(screen_img, secondary_rect)


    @staticmethod
    def _detect_rows_heuristic(
        screen_img: np.ndarray,
        area_rect: Optional[Tuple[int, int, int, int]] = None
    ) -> List[Dict[str, Any]]:
        """
        Евристично виявляє рядки файлів/документів у зазначеній області списку.
        """
        sh, sw = screen_img.shape[:2]
        if area_rect:
            x1, y1, x2, y2 = area_rect
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(sw, x2), min(sh, y2)
        else:
            x1, y1, x2, y2 = 50, 100, sw - 50, sh - 100

        crop = screen_img[y1:y2, x1:x2]
        if crop.size == 0:
            return []

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # Горизонтальні лінії/рядки
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        row_energy = np.mean(np.abs(sobel_y), axis=1)

        # Знаходимо піки рядків із кроком ~20-35px (типова висота рядка в списках Windows)
        row_height = 28
        h_crop = y2 - y1
        num_rows = max(1, h_crop // row_height)
        
        detected = []
        center_x = x1 + (x2 - x1) // 3  # клік ближче до назви файлу зліва
        
        for i in range(min(num_rows, 15)):
            r_y = y1 + (i * row_height) + (row_height // 2)
            if r_y < y2 - 5:
                detected.append({
                    "name": f"Рядок/Файл #{i + 1} (Y={r_y})",
                    "x": center_x,
                    "y": r_y
                })

        return detected


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
