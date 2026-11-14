"""Visão e OCR nativo do Windows (Sprint A, 100% local).

Captura a tela (ou só a janela ativa, 3x mais rápido e menos RAM) e extrai
texto. Backend preferencial: WinRT (Windows.Media.Ocr, nativo do Windows 10/11).
Fallback: rapidocr-onnxruntime. Sem rede, sem nuvem.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import ImageGrab

from raves.core.logger import logger


def _active_window_rect() -> tuple[int, int, int, int] | None:
    try:
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        rect = win32gui.GetWindowRect(hwnd)
        left = int(rect[0])
        top = int(rect[1])
        right = int(rect[2])
        bottom = int(rect[3])
        if right - left <= 0 or bottom - top <= 0:
            return None
        return (left, top, right - left, bottom - top)
    except Exception:
        return None


def _capture(region: tuple[int, int, int, int] | None) -> tuple[Any, tuple[int, int]]:
    """Retorna (PIL.Image, origem) onde origem é o offset (x, y) da captura."""
    if region is not None:
        x, y, w, h = region
        bbox = (x, y, x + w, y + h)
        return ImageGrab.grab(bbox=bbox), (x, y)
    rect = _active_window_rect()
    if rect is not None:
        x, y, w, h = rect
        return ImageGrab.grab(bbox=(x, y, x + w, y + h)), (x, y)
    image = ImageGrab.grab()
    return image, (0, 0)


def _ocr_winrt(pil_image: Any) -> tuple[list[dict[str, Any]], str] | None:
    try:
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except ImportError:
        return None
    try:
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        data = buf.getvalue()

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(data)
        writer.store_async().get()
        stream.seek(0)

        decoder = BitmapDecoder.create_async(stream).get()
        bitmap = decoder.get_software_bitmap_async().get()

        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return None
        result = engine.recognize_async(bitmap).get()

        words: list[dict[str, Any]] = []
        for line in result.lines:
            for word in line.words:
                rect = word.bounding_rect
                words.append(
                    {
                        "text": word.text,
                        "x": int(rect.x),
                        "y": int(rect.y),
                        "w": int(rect.width),
                        "h": int(rect.height),
                    }
                )
        full_text = (result.text or "").strip()
        if not full_text and words:
            full_text = " ".join(item["text"] for item in words)
        return words, full_text
    except Exception as exc:
        logger.debug(f"vision: winrt OCR falhou ({exc})")
        return None


def _ocr_rapidocr(pil_image: Any) -> tuple[list[dict[str, Any]], str] | None:
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    try:
        ocr = RapidOCR()
        result, _ = ocr(np.array(pil_image))
        if not result:
            return [], ""
        words: list[dict[str, Any]] = []
        for box, text, _score in result:
            xs = [int(point[0]) for point in box]
            ys = [int(point[1]) for point in box]
            words.append(
                {
                    "text": str(text),
                    "x": int(min(xs)),
                    "y": int(min(ys)),
                    "w": int(max(xs) - min(xs)),
                    "h": int(max(ys) - min(ys)),
                }
            )
        full_text = " ".join(item["text"] for item in words)
        return words, full_text
    except Exception as exc:
        logger.debug(f"vision: rapidocr falhou ({exc})")
        return None


def _ocr(pil_image: Any) -> tuple[list[dict[str, Any]], str]:
    result = _ocr_winrt(pil_image)
    if result is not None:
        return result
    result = _ocr_rapidocr(pil_image)
    if result is not None:
        return result
    return [], ""


def read_screen_text(region: tuple[int, int, int, int] | None = None) -> str:
    """Extrai todo o texto da tela (ou da região informada)."""
    image, _origin = _capture(region)
    _words, full_text = _ocr(image)
    return full_text


def find_text_on_screen(
    target_text: str, region: tuple[int, int, int, int] | None = None
) -> tuple[int, int] | None:
    """Localiza um texto na tela e retorna o centro (x, y) para clique."""
    needle = target_text.strip().lower()
    if not needle:
        return None
    image, origin = _capture(region)
    words, _full = _ocr(image)
    if not words:
        return None

    # 1) correspondência por palavra única (case-insensitive, contains).
    for word in words:
        if needle in word["text"].lower():
            cx = origin[0] + word["x"] + word["w"] // 2
            cy = origin[1] + word["y"] + word["h"] // 2
            return (cx, cy)

    # 2) correspondência por frase (palavras consecutivas).
    tokens = needle.split()
    if len(tokens) > 1:
        texts = [word["text"].lower() for word in words]
        for index in range(len(words) - len(tokens) + 1):
            if texts[index : index + len(tokens)] == tokens:
                span = words[index : index + len(tokens)]
                xs = [item["x"] for item in span] + [item["x"] + item["w"] for item in span]
                ys = [item["y"] for item in span] + [item["y"] + item["h"] for item in span]
                cx = origin[0] + (min(xs) + max(xs)) // 2
                cy = origin[1] + (min(ys) + max(ys)) // 2
                return (cx, cy)
    return None


def click_text(target_text: str) -> tuple[bool, str]:
    """Localiza um texto na tela (janela ativa) e clica no seu centro."""
    pos = find_text_on_screen(target_text)
    if pos is None:
        return False, f"Texto '{target_text}' não encontrado na tela"
    try:
        import pyautogui

        pyautogui.click(*pos)
        return True, f"Clique em '{target_text}' em {pos}"
    except Exception as exc:
        return False, str(exc)
