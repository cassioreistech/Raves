"""Processos, aplicativos e janelas (pywin32 + psutil).

Todas as operações com efeito colateral aceitam dry_run (padrão True) e passam
por validação. Nunca usamos shell=True: um YAML não pode injetar comandos.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil
import win32api
import win32con
import win32gui
import win32process

from winbot.core.config import SecuritySettings, load_settings
from winbot.core.logger import audit, logger
from winbot.core.security import SecurityViolationError

_SHELL_METACHARS = "&|;<>^\n\r"


def screen_size() -> tuple[int, int]:
    """Largura e altura da tela primária, em pixels."""
    return (win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1))


def system_snapshot() -> dict[str, Any]:
    """Coleta identidade da máquina e contagem de processos. Nunca altera estado."""
    pids = win32process.EnumProcesses() or []
    return {
        "computer": win32api.GetComputerName(),
        "user": win32api.GetUserName(),
        "process_count": len(pids),
        "screen": screen_size(),
    }


def _validate_argv(values: list[str]) -> None:
    for value in values:
        if any(char in value for char in _SHELL_METACHARS):
            raise SecurityViolationError(f"Argumento contém metacaractere de shell: {value!r}")


def launch_app(
    target: str,
    args: list[str] | None = None,
    *,
    dry_run: bool = True,
    policy: SecuritySettings | None = None,
) -> bool:
    """Abre um executável allowlistado. `shell=False` sempre."""
    arguments = [str(item) for item in (args or [])]
    _validate_argv([target, *arguments])
    if not (shutil.which(target) or Path(target).is_file()):
        raise SecurityViolationError(f"Executável não encontrado: {target!r}")

    active = policy if policy is not None else load_settings().security
    exe = Path(target).name.lower()
    if exe not in {item.lower() for item in active.allowed_apps}:
        raise SecurityViolationError(f"Aplicativo não permitido: {exe}")

    cmd = [target, *arguments]
    audit(f"launch_app argv={cmd!r} dry_run={dry_run}")
    logger.info(f"Iniciando aplicação: {cmd}")
    if dry_run:
        return True
    if target.lower().endswith(".lnk"):
        # Atalhos do Menu Iniciar nao sao executaveis por Popen(shell=False).
        # os.startfile usa ShellExecute sobre um CAMINHO FIXO: nenhuma string de
        # comando e montada e nenhum argv e interpolado. Nao e `shell=True`.
        starter = getattr(os, "startfile", None)
        if starter is None:
            raise SecurityViolationError("Atalhos .lnk so podem ser abertos no Windows")
        starter(target)
        return True
    subprocess.Popen(cmd, shell=False)
    return True


def kill_process_by_name(
    process_name: str,
    *,
    dry_run: bool = True,
    policy: SecuritySettings | None = None,
) -> int:
    """Encerra processos pelo nome, protegendo os críticos do sistema."""
    name = process_name.strip().lower()
    if not name:
        raise SecurityViolationError("kill_process exige params.name")

    active = policy if policy is not None else load_settings().security
    if name in {item.lower() for item in active.deny_processes}:
        raise SecurityViolationError(f"Processo protegido contra encerramento: {name}")

    matches = [
        proc
        for proc in psutil.process_iter(["pid", "name"])
        if (proc.info["name"] or "").lower() == name
    ]
    audit(f"kill_process name={name} matches={len(matches)} dry_run={dry_run}")
    logger.info(f"Processos '{name}' encontrados: {len(matches)} (dry_run={dry_run})")
    if dry_run:
        return len(matches)

    killed = 0
    for proc in matches:
        try:
            proc.terminate()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return killed


def focus_window(title_substring: str, *, dry_run: bool = True) -> bool:
    """Traz para frente a primeira janela visível que contenha o texto no título."""
    if not title_substring.strip():
        raise SecurityViolationError("focus_window exige params.title")
    audit(f"focus_window title={title_substring!r} dry_run={dry_run}")
    if dry_run:
        return True

    target_hwnd: int | None = None

    def enum_handler(hwnd: int, _: Any) -> None:
        nonlocal target_hwnd
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title_substring.lower() in title.lower():
                target_hwnd = hwnd

    win32gui.EnumWindows(enum_handler, None)
    if target_hwnd is None:
        return False
    try:
        # Workaround para o bloqueio de foreground do Windows: anexa a thread
        # de entrada do processo em foreground à thread alvo, foca e desanexa.
        # ASFW_ANY sozinho não basta quando o WinBot roda destacado (tray).
        try:
            import ctypes

            foreground_hwnd = win32gui.GetForegroundWindow()
            foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground_hwnd)
            target_thread, _ = win32process.GetWindowThreadProcessId(target_hwnd)
            attached = False
            if foreground_thread and target_thread and foreground_thread != target_thread:
                attached = bool(
                    ctypes.windll.user32.AttachThreadInput(foreground_thread, target_thread, True)
                )
            win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target_hwnd)
            win32gui.BringWindowToTop(target_hwnd)
            if attached:
                ctypes.windll.user32.AttachThreadInput(foreground_thread, target_thread, False)
        except Exception as exc:
            logger.debug(f"focus_window: não foi possível focar '{title_substring}': {exc}")
            return False
    except Exception as exc:
        logger.debug(f"focus_window: não foi possível focar '{title_substring}': {exc}")
        return False
    logger.info(f"Janela focada: '{title_substring}'")
    return True
