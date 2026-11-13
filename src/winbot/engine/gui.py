"""Automação visual: pywinauto (UIA) para descoberta, Win32 nativo para foco.

``pyautogui`` é opcional (extra ``gui``) e só entra se houver necessidade de
clique por imagem; o FAILSAFE permanece ligado.
"""

from __future__ import annotations

from winbot.engine import windows_api


def list_windows() -> list[str]:
    from pywinauto import Desktop

    return [win.window_text() for win in Desktop(backend="uia").windows()]


def focus_window(title: str, *, dry_run: bool = True) -> str:
    """Delega ao Win32 nativo para não duplicar a lógica de EnumWindows."""
    ok = windows_api.focus_window(title, dry_run=dry_run)
    if dry_run:
        return "simulado"
    return "focado" if ok else "não encontrado"
