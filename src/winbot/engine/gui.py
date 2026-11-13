"""Automação visual (RPA).

pywinauto (UIA) para descoberta, Win32 nativo para foco e pyautogui para
coordenadas/imagem/teclado. Tudo com dry_run por padrão e trilha de auditoria.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from winbot.core.logger import audit
from winbot.core.security import SecurityViolationError
from winbot.engine import windows_api

MAX_TEXT_LENGTH = 4096
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp"})

# Combinações que um YAML nunca pode disparar.
FORBIDDEN_HOTKEYS: tuple[frozenset[str], ...] = (
    frozenset({"ctrl", "alt", "delete"}),
    frozenset({"ctrl", "shift", "esc"}),
    frozenset({"win", "l"}),
    frozenset({"alt", "f4"}),
)

_SPECIAL_KEYS = frozenset(
    {
        "ctrl",
        "alt",
        "shift",
        "win",
        "enter",
        "return",
        "tab",
        "esc",
        "space",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "pageup",
        "pagedown",
        "up",
        "down",
        "left",
        "right",
        "capslock",
        "numlock",
        "scrolllock",
        "printscreen",
        "pause",
    }
)


def _pyautogui():
    """Import lazy (evita carregar Pillow no --help) com FAILSAFE sempre ligado."""
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
    return pyautogui


def list_windows() -> list[str]:
    from pywinauto import Desktop

    return [win.window_text() for win in Desktop(backend="uia").windows()]


def focus_window(title: str, *, dry_run: bool = True) -> str:
    """Delega ao Win32 nativo para não duplicar a lógica de EnumWindows."""
    ok = windows_api.focus_window(title, dry_run=dry_run)
    if dry_run:
        return "simulado"
    return "focado" if ok else "não encontrado"


def click_at(x: int, y: int, *, dry_run: bool = True) -> str:
    """Clica em uma coordenada absoluta, validada contra o tamanho da tela."""
    width, height = windows_api.screen_size()
    if not (0 <= x < width and 0 <= y < height):
        raise SecurityViolationError(f"Coordenada fora da tela {width}x{height}: ({x}, {y})")
    audit(f"gui.click_at x={x} y={y} dry_run={dry_run}")
    if dry_run:
        return "simulado"
    _pyautogui().click(x, y)
    return f"clique em ({x}, {y})"


def click_image(image: str, *, dry_run: bool = True, timeout: float = 10.0) -> str:
    """Localiza uma imagem de referência na tela e clica no centro."""
    path = Path(image)
    if not path.is_file():
        raise SecurityViolationError(f"Imagem de referência não encontrada: {image}")
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        raise SecurityViolationError(f"Formato de imagem não suportado: {path.suffix}")
    audit(f"gui.click_image image={image} dry_run={dry_run}")
    if dry_run:
        return "simulado"

    gui = _pyautogui()
    not_found = getattr(gui, "ImageNotFoundException", OSError)
    deadline = time.monotonic() + min(max(timeout, 0.0), 30.0)
    while time.monotonic() < deadline:
        try:
            center = gui.locateCenterOnScreen(str(path))
        except not_found:
            center = None
        if center is not None:
            gui.click(center)
            return f"clique na imagem em {center}"
        time.sleep(0.5)
    return "imagem não encontrada na tela"


def type_text_safe(text: str, *, dry_run: bool = True) -> str:
    """Digita via clipboard (ctrl+v), preservando o conteúdo anterior.

    O texto NUNCA é gravado em log: pode conter senha ou dado sensível.
    """
    if not text:
        raise SecurityViolationError("gui_type exige params.text não vazio")
    if len(text) > MAX_TEXT_LENGTH:
        raise SecurityViolationError(f"params.text excede {MAX_TEXT_LENGTH} caracteres")
    audit(f"gui.type_text len={len(text)} dry_run={dry_run}")
    if dry_run:
        return "simulado"

    import pyperclip

    gui = _pyautogui()
    previous = pyperclip.paste()
    try:
        pyperclip.copy(text)
        gui.hotkey("ctrl", "v")
        time.sleep(0.2)  # dá tempo de o app colar antes de restaurar
    finally:
        pyperclip.copy(previous)
    return f"{len(text)} caractere(s) digitado(s)"


def _normalize_keys(keys: list[str]) -> list[str]:
    normalized = [str(key).strip().lower() for key in keys]
    if not normalized or any(not key for key in normalized):
        raise SecurityViolationError("gui_hotkey exige params.keys não vazio")
    for key in normalized:
        if key not in _SPECIAL_KEYS and not re.fullmatch(r"[a-z0-9]|f([1-9]|1[0-2])", key):
            raise SecurityViolationError(f"Tecla não permitida: {key!r}")
    if frozenset(normalized) in FORBIDDEN_HOTKEYS:
        raise SecurityViolationError(f"Combinação de teclas proibida: {normalized}")
    return normalized


def hotkey(keys: list[str], *, dry_run: bool = True) -> str:
    """Dispara uma combinação de teclas allowlistada."""
    normalized = _normalize_keys(keys)
    audit(f"gui.hotkey keys={normalized} dry_run={dry_run}")
    if dry_run:
        return "simulado"
    _pyautogui().hotkey(*normalized)
    return f"hotkey {normalized}"
