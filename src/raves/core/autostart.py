"""Início automático do RAVES com o Windows (Etapa 8, sem admin).

Usa a chave de usuário ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``.
100% local, sem elevação.
"""

from __future__ import annotations

import sys
from pathlib import Path

VALUE_NAME = "RAVES"


def _command() -> str:
    """Linha de comando registrada no Run (tray, sem janela de console)."""
    exe = None
    try:
        import shutil

        exe = shutil.which("raves")
    except Exception:
        exe = None
    if exe:
        return f'"{exe}" tray'
    candidate = Path(sys.executable).parent / "raves.exe"
    if candidate.exists():
        return f'"{candidate}" tray'
    return f'"{sys.executable}" -m raves tray'


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except OSError:
        return False


def enable() -> None:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
    except OSError as exc:
        raise RuntimeError(f"Falha ao registrar autostart: {exc}") from exc


def disable() -> None:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RuntimeError(f"Falha ao remover autostart: {exc}") from exc
