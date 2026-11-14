"""RPA nativo via Windows UI Automation (Etapa 2).

Diferente do clique cego por coordenada, o UIA conecta na árvore de
acessibilidade do Windows: funciona com janela redimensionada/movida e em
monitores com escalas DPI diferentes. Toda função retorna (sucesso, detalhe)
ou lista estruturada; nenhuma delas executa shell=True.

Pywinauto é importado dentro das funções para manter ``winbot --help`` rápido.
"""

from __future__ import annotations

import re
from typing import Any

from tenacity import Retrying, stop_after_delay, wait_fixed

from winbot.core.logger import audit, logger
from winbot.core.security import SecurityViolationError

_DEFAULT_TIMEOUT = 15


def _desktop() -> Any:
    from pywinauto import Desktop

    return Desktop(backend="uia")


def _find_window(window_title: str) -> Any:
    """Localiza a primeira janela cujo título contém ``window_title`` (case-insens.)."""
    needle = window_title.strip().lower()
    if not needle:
        raise SecurityViolationError("uia: título de janela vazio")
    for window in _desktop().windows():
        title = (window.window_text() or "").lower()
        if needle in title:
            return window
    raise ValueError(f"Janela '{window_title}' não encontrada")


def wait_for_window(title_substring: str, timeout: int = _DEFAULT_TIMEOUT) -> bool:
    """Aguarda a janela ficar visível e pronta (tenacity, backoff de 0.5s)."""
    needle = title_substring.strip()
    if not needle:
        return False

    def _find() -> bool:
        for window in _desktop().windows():
            title = (window.window_text() or "").lower()
            if needle.lower() in title and window.is_visible():
                return True
        raise ValueError("window not found")

    try:
        for attempt in Retrying(
            stop=stop_after_delay(max(1, int(timeout))),
            wait=wait_fixed(0.5),
            reraise=False,
        ):
            with attempt:
                return _find()
    except Exception:  # RetryError ou qualquer falha do backend UIA
        return False
    return False  # inalcançável: satisfaz pyright


def _find_control(window: Any, control_title: str, control_type: str | None) -> Any:
    """Encontra um controle descendente por título (case-insens.) + tipo opcional."""
    title_re = re.compile(re.escape(control_title), re.IGNORECASE)
    kwargs: dict[str, Any] = {"title_re": title_re}
    if control_type:
        kwargs["control_type"] = control_type
    try:
        control = window.child_window(**kwargs)
        control.wait("exists enabled visible ready", timeout=5)
        return control
    except Exception:
        pass
    # Fallback: busca entre todos os descendentes.
    for descendant in window.descendants():
        text = (descendant.window_text() or "").lower()
        if control_title.lower() in text:
            ctype = descendant.element_info.control_type or ""
            if not control_type or ctype.lower() == control_type.lower():
                return descendant
    raise ValueError(f"Controle '{control_title}' não encontrado")


def click_control(
    window_title: str, control_title: str, control_type: str | None = None
) -> tuple[bool, str]:
    """Localiza a janela, encontra o controle e dispara o clique (invoke/click_input)."""
    try:
        window = _find_window(window_title)
        window.set_focus()
        control = _find_control(window, control_title, control_type)
        try:
            control.invoke()
        except Exception:
            control.click_input()
        audit(f"uia.click window={window_title!r} control={control_title!r} type={control_type!r}")
        logger.info(f"UIA clique: '{control_title}' em '{window_title}'")
        return True, f"Clique em '{control_title}' ({control_type or 'auto'})"
    except Exception as exc:
        audit(f"uia.click FAIL window={window_title!r} control={control_title!r}: {exc}")
        logger.warning(f"UIA falhou: {exc}")
        return False, str(exc)


def fill_field(
    window_title: str,
    field_title: str,
    text: str,
    press_enter: bool = False,
) -> tuple[bool, str]:
    """Preenche um campo Edit: tenta set_edit_text, fallback para clipboard (acentos)."""
    if not text:
        return False, "Texto vazio"
    try:
        window = _find_window(window_title)
        window.set_focus()
        control = _find_control(window, field_title, "Edit")
        control.set_focus()
        try:
            control.set_edit_text(text)
        except Exception:
            import pyperclip

            pyperclip.copy(text)
            control.type_keys("^v", with_spaces=True)
        if press_enter:
            control.type_keys("{ENTER}")
        audit(f"uia.fill window={window_title!r} field={field_title!r} len={len(text)}")
        logger.info(f"UIA preenchimento: '{field_title}' em '{window_title}' ({len(text)} chars)")
        return True, f"Campo '{field_title}' preenchido ({len(text)} caractere(s))"
    except Exception as exc:
        audit(f"uia.fill FAIL window={window_title!r} field={field_title!r}: {exc}")
        logger.warning(f"UIA falhou: {exc}")
        return False, str(exc)


def list_window_controls(window_title: str, max_depth: int = 3) -> list[dict[str, str]]:
    """Lista controles visíveis (title, control_type, auto_id) de uma janela."""
    result: list[dict[str, str]] = []
    window = _find_window(window_title)

    def walk(control: Any, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = control.children()
        except Exception:
            return
        for child in children:
            try:
                title = (child.window_text() or "").strip()
                ctype = child.element_info.control_type or ""
                auto_id = child.element_info.automation_id or ""
            except Exception:
                title, ctype, auto_id = "", "", ""
            if title or ctype:
                result.append({"title": title, "control_type": ctype, "auto_id": auto_id})
            walk(child, depth + 1)

    walk(window, 0)
    return result


def foreground_window_title() -> str | None:
    """Título da janela em primeiro plano (ou None se não houver)."""
    try:
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        return title or None
    except Exception:
        return None
