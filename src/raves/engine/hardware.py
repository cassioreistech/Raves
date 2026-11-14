"""Controle de hardware, mídia e captura de tela (Etapa 9, 100% local).

Lazy imports: pycaw/comtypes/pyautogui/win32api só são carregados ao chamar
as funções, para manter o repouso em ~0% de RAM/CPU.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

MediaAction = Literal["play_pause", "next", "prev"]

_VK_MEDIA = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "prev": 0xB1,
}


def _speakers() -> Any:
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers()


def set_volume(percent: int) -> str:
    percent = max(0, min(100, int(percent)))
    try:
        device = _speakers()
        device.volume_percent = percent / 100.0
        return f"Volume ajustado para {percent}%"
    except Exception as exc:
        return f"Falha ao ajustar volume: {exc}"


def change_volume(delta: int) -> str:
    try:
        device = _speakers()
        current = int(round(device.volume_percent * 100))
        return set_volume(current + int(delta))
    except Exception as exc:
        return f"Falha ao ajustar volume: {exc}"


def toggle_mute() -> str:
    try:
        device = _speakers()
        endpoint = device.EndpointVolume
        muted = bool(endpoint.GetMute())
        endpoint.SetMute(not muted, None)
        return "Mudo ativado" if not muted else "Mudo desativado"
    except Exception as exc:
        return f"Falha ao alternar mudo: {exc}"


def media_control(action: MediaAction) -> str:
    if action not in _VK_MEDIA:
        return f"Ação de mídia inválida: {action}"
    try:
        import win32api
        import win32con

        vk = _VK_MEDIA[action]
        win32api.keybd_event(vk, 0, 0, 0)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        label = {"play_pause": "play/pause", "next": "próxima", "prev": "anterior"}[action]
        return f"Mídia: {label}"
    except Exception as exc:
        return f"Falha ao controlar mídia: {exc}"


def take_screenshot(save_to_desktop: bool = True) -> Path:
    import pyautogui

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"Raves_Print_{timestamp}.png"
    base = Path.home() / "Desktop" if save_to_desktop else Path.home() / "Pictures" / "WinBot"
    base.mkdir(parents=True, exist_ok=True)
    path = base / filename
    pyautogui.screenshot().save(str(path))
    return path
