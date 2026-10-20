"""
Модуль Gemini Vision — використовує Gemini Vision API для точного розпізнавання
UI-елементів (кнопки, пункти меню, виділені рядки) на поточному екрані.

Алгоритм роботи:
1. Робить знімок поточного екрана
2. Передає знімок екрана + банк шаблонів (template_bank) елемента до Gemini Vision
3. Gemini аналізує зображення та повертає точні координати елемента
4. При невдачі Gemini — fallback до OpenCV matchTemplate

Навчання (template bank):
- При кожному новому записі сценарію до елемента додається ще один знімок
- Чим більше запусків навчання = більший банк = вища точність розпізнавання
"""

import os
import re
import json
import base64
import time
import logging
from typing import Optional, Tuple, List, Dict, Any

logger = logging.getLogger("GeminiVision")

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logger.warning("google-genai не встановлено. Gemini Vision недоступний.")

import numpy as np
import cv2


_gemini_client: Optional[Any] = None


def get_gemini_client(api_key: Optional[str] = None) -> Optional[Any]:
    """Ліниво ініціалізує та повертає Gemini клієнт."""
    global _gemini_client
    if not GENAI_AVAILABLE:
        return None
    if _gemini_client is None:
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            return None
        try:
            _gemini_client = genai.Client(api_key=key)
        except Exception as e:
            logger.error(f"Не вдалося ініціалізувати Gemini клієнт: {e}")
            return None
    return _gemini_client


def set_api_key(api_key: str):
    """Встановлює API-ключ Gemini та скидає поточний клієнт."""
    global _gemini_client
    _gemini_client = None
    os.environ["GEMINI_API_KEY"] = api_key


def _img_np_to_b64(img: np.ndarray, fmt: str = ".png") -> str:
    """Конвертує numpy BGR-зображення у base64 рядок."""
    success, buf = cv2.imencode(fmt, img)
    if not success:
        raise ValueError("Не вдалося закодувати зображення")
    return base64.b64encode(buf).decode("utf-8")


def _b64_to_img(b64: str) -> Optional[np.ndarray]:
    """Декодує base64 рядок у numpy BGR-зображення."""
    try:
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def find_element_with_gemini(
    screen_img: np.ndarray,
    template_bank: List[str],          # список base64 PNG знімків шаблону
    expected_x: int,
    expected_y: int,
    offset_x: int,
    offset_y: int,
    element_hint: str = "",            # текстовий опис (коментар) для покращення точності
    api_key: Optional[str] = None,
    timeout: float = 8.0,
) -> Optional[Tuple[int, int, float]]:
    """
    Шукає UI-елемент на екрані за допомогою Gemini Vision.

    Надсилає до Gemini:
      - поточний знімок екрана
      - один або кілька шаблонних знімків елемента (з різних записів навчання)
      - запит на знаходження точних координат

    Повертає (click_x, click_y, confidence) або None якщо елемент не знайдено.
    """
    client = get_gemini_client(api_key)
    if client is None or not template_bank:
        return None

    sh, sw = screen_img.shape[:2]

    # --- Підготовка зображень для запиту ---
    # Зменшуємо екран якщо він дуже великий (економія токенів)
    max_dim = 1920
    scale = 1.0
    if sw > max_dim or sh > max_dim:
        scale = max_dim / max(sw, sh)
        new_w = int(sw * scale)
        new_h = int(sh * scale)
        screen_small = cv2.resize(screen_img, (new_w, new_h))
    else:
        screen_small = screen_img

    screen_b64 = _img_np_to_b64(screen_small)
    screen_w = screen_small.shape[1]
    screen_h = screen_small.shape[0]

    # Масштабуємо очікувані координати під зменшений екран
    exp_x_scaled = int(expected_x * scale)
    exp_y_scaled = int(expected_y * scale)

    # Беремо кілька шаблонів (не більше 3, щоб не перевантажити запит)
    sample_templates = template_bank[-3:] if len(template_bank) > 3 else template_bank

    # --- Будуємо список частин (parts) для мультимодального запиту ---
    try:
        from google.genai import types as genai_types

        parts = []

        # Перша частина — знімок екрана
        parts.append(genai_types.Part.from_bytes(
            data=base64.b64decode(screen_b64),
            mime_type="image/png"
        ))

        # Далі — шаблони (еталонні знімки елемента)
        for i, tmpl_b64 in enumerate(sample_templates):
            tmpl_img = _b64_to_img(tmpl_b64)
            if tmpl_img is None:
                continue
            # Збільшуємо шаблон для кращого розгляду (мінімум 80x80)
            th, tw = tmpl_img.shape[:2]
            if tw < 80 or th < 80:
                zoom = max(80 / tw, 80 / th)
                tmpl_img = cv2.resize(tmpl_img, (int(tw * zoom), int(th * zoom)),
                                      interpolation=cv2.INTER_CUBIC)
            tmpl_b64_upscaled = _img_np_to_b64(tmpl_img)
            parts.append(genai_types.Part.from_bytes(
                data=base64.b64decode(tmpl_b64_upscaled),
                mime_type="image/png"
            ))

        hint_str = f"\nДодаткова підказка про елемент: {element_hint}" if element_hint else ""
        prompt = (
            f"На першому зображенні — поточний знімок екрана розміром {screen_w}x{screen_h} пікселів.\n"
            f"На наступних зображеннях — еталонні знімки UI-елемента (кнопки, пункту меню або рядка документа), "
            f"який потрібно знайти на екрані.{hint_str}\n"
            f"Очікувана приблизна позиція елемента на екрані: ({exp_x_scaled}, {exp_y_scaled}).\n\n"
            f"Завдання: знайди цей елемент на екрані та поверни JSON з координатами центру елемента.\n"
            f"Важливо: координати мають бути в межах 0..{screen_w} по X та 0..{screen_h} по Y.\n"
            f"Якщо елемент знайдено — повертай: {{\"found\": true, \"x\": <число>, \"y\": <число>, \"confidence\": <0.0-1.0>}}\n"
            f"Якщо елемент НЕ знайдено — повертай: {{\"found\": false}}\n"
            f"Відповідай ТІЛЬКИ JSON, без зайвого тексту."
        )
        parts.append(genai_types.Part.from_text(text=prompt))

        # Запит до Gemini Vision
        start_t = time.time()
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[genai_types.Content(role="user", parts=parts)],
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=128,
            )
        )
        elapsed = time.time() - start_t
        logger.debug(f"Gemini Vision відповів за {elapsed:.2f}с")

        raw_text = response.text.strip() if response.text else ""
        if not raw_text:
            return None

        # Видобуваємо JSON з відповіді (іноді модель загортає в ```json)
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if not json_match:
            return None

        data = json.loads(json_match.group())

        if not data.get("found", False):
            return None

        gx = float(data.get("x", 0))
        gy = float(data.get("y", 0))
        conf = float(data.get("confidence", 0.85))

        # Перевірка меж
        if not (0 <= gx <= screen_w and 0 <= gy <= screen_h):
            return None

        # Масштабуємо назад до оригінальних координат екрана
        real_x = int(gx / scale)
        real_y = int(gy / scale)

        # Застосовуємо зміщення кліку відносно знайденого центру шаблону
        click_x = real_x + offset_x - (sample_templates and _get_template_half_w(sample_templates[0]) or 0)
        click_y = real_y + offset_y - (sample_templates and _get_template_half_h(sample_templates[0]) or 0)

        # Clamp до меж екрана
        click_x = max(0, min(sw - 1, click_x))
        click_y = max(0, min(sh - 1, click_y))

        return click_x, click_y, conf

    except json.JSONDecodeError as e:
        logger.warning(f"Gemini Vision: некоректний JSON: {e} | Відповідь: {raw_text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Gemini Vision помилка: {e}")
        return None


def _get_template_half_w(b64: str) -> int:
    img = _b64_to_img(b64)
    return img.shape[1] // 2 if img is not None else 0


def _get_template_half_h(b64: str) -> int:
    img = _b64_to_img(b64)
    return img.shape[0] // 2 if img is not None else 0


def is_gemini_available() -> bool:
    """Перевіряє чи є API-ключ та встановлений пакет."""
    return GENAI_AVAILABLE and bool(os.environ.get("GEMINI_API_KEY", ""))
