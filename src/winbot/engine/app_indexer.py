"""Indexador de aplicativos instalados no Windows (Etapa 1 de Blindagem).

Varre atalhos ``.lnk`` do Menu Iniciar e as chaves ``App Paths`` do registro.
Nenhuma chamada COM/ShellExecute é feita aqui: o scan nunca pode travar a CLI.
Falhas de permissão são ignoradas **por item**, há limites duros de varredura e o
resultado é sempre consolidado em ``database.upsert_apps()``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from winbot.core import database
from winbot.core.logger import logger

_UNINSTALL_MARKERS = ("uninstall", "remover", "desinstal")
_MAX_SHORTCUTS = 2000
_MAX_REGISTRY_KEYS = 500
_APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

_NAME_SUFFIXES = (
    " (x64)",
    " (64-bit)",
    " (32-bit)",
    " (x86)",
    " - atalho",
    " (administrador)",
)


def _normalize_name(text: str) -> str:
    """``Google Chrome.lnk`` -> ``google chrome`` (minúsculo, sem ruído)."""
    cleaned = re.sub(r"\s+", " ", text.lower().strip())
    for suffix in _NAME_SUFFIXES:
        cleaned = cleaned.removesuffix(suffix)
    return cleaned.strip(" .-_")


def _aliases(name: str) -> list[str]:
    """Nome normalizado + alias curto sem espaços, quando aplicável."""
    result = [name]
    compact = name.replace(" ", "")
    if compact and compact != name and len(compact) >= 3:
        result.append(compact)
    return result


def _clean_exe_path(value: str) -> str | None:
    """Extrai só o ``.exe`` de um valor padrão que pode vir com aspas/argumentos."""
    text = os.path.expandvars(value.strip())
    if not text:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 1 else None
    match = re.match(r"^(.+?\.exe)(?:\s|$)", text, re.IGNORECASE)
    return match.group(1) if match else None


def _start_menu_dirs() -> list[tuple[Path, str]]:
    programdata = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    common = programdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    user = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return [(common, "start_menu_all"), (user, "start_menu_user")]


def _scan_shortcuts(directory: Path, source: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    if not directory.is_dir():
        return rows
    # rglob pode levantar OSError no meio (pasta inacessível): mantém o que já
    # coletou e segue. Nada de COM: .lnk é guardado como caminho, sem resolver.
    try:
        for index, shortcut in enumerate(directory.rglob("*.lnk")):
            if index >= _MAX_SHORTCUTS:
                break
            stem = shortcut.stem
            if any(marker in stem.lower() for marker in _UNINSTALL_MARKERS):
                continue
            name = _normalize_name(stem)
            if not name:
                continue
            for alias in _aliases(name):
                rows.append((alias, str(shortcut), source))
    except OSError as exc:
        logger.debug(f"app_indexer: varredura parcial de {directory}: {exc}")
    return rows


def _read_app_paths(winreg: Any, root: int, label: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    try:
        parent = winreg.OpenKey(root, _APP_PATHS_KEY, 0, winreg.KEY_READ)
    except OSError:
        return rows
    with parent:
        index = 0
        while index < _MAX_REGISTRY_KEYS:
            try:
                subname = winreg.EnumKey(parent, index)
            except OSError:
                break
            index += 1
            try:
                subkey = winreg.OpenKey(parent, subname, 0, winreg.KEY_READ)
            except OSError:
                continue
            with subkey:
                try:
                    # Valor padrão da subchave = caminho do executável.
                    value = winreg.QueryValueEx(subkey, "")[0]
                except OSError:
                    continue
            target = _clean_exe_path(str(value))
            if not target:
                continue
            base = re.sub(r"\.exe$", "", subname, flags=re.IGNORECASE)
            normalized = _normalize_name(base)
            if not normalized:
                continue
            for alias in _aliases(normalized):
                rows.append((alias, target, f"app_paths_{label}"))
    return rows


def scan_and_index_windows_apps() -> int:
    """Indexia Start Menu + registro e retorna o nº de nomes gravados.

    Registro tem prioridade sobre ``.lnk`` para o mesmo nome: entrega um ``.exe``
    real em vez de um atalho. Em não-Windows, a parte de registro é ignorada.
    """
    database.init_db()
    collected: dict[str, tuple[str, str, str]] = {}

    for directory, source in _start_menu_dirs():
        for name, target, source_name in _scan_shortcuts(directory, source):
            collected.setdefault(name, (name, target, source_name))

    registry: Any = None
    try:
        import winreg

        registry = winreg
    except ImportError:  # pragma: no cover - projeto é Windows-only
        pass
    if registry is not None:
        for root, label in (
            (registry.HKEY_LOCAL_MACHINE, "hklm"),
            (registry.HKEY_CURRENT_USER, "hkcu"),
        ):
            for name, target, source in _read_app_paths(registry, root, label):
                collected[name] = (name, target, source)

    written = database.upsert_apps(list(collected.values()))
    logger.info(f"app_indexer: {written} aplicativo(s) indexado(s)")
    return written
