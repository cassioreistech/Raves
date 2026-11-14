"""Captura de snapshot de erro (screenshot + texto) para diagnóstico de RPA.

100% local: grava em ``~/.winbot/crash_reports``. Sem rede, sem upload.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from winbot.core.logger import logger

CRASH_REPORTS_DIR = Path.home() / ".winbot" / "crash_reports"


def capture_error_snapshot(context_name: str, error_msg: str) -> Path:
    """Salva screenshot + .txt do erro. Retorna o caminho do .txt (ou do dir)."""
    CRASH_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w\-]", "_", (context_name or "context"))[:40]
    base = CRASH_REPORTS_DIR / f"{safe}_{timestamp}"
    txt_path = base.with_suffix(".txt")
    png_path = base.with_suffix(".png")

    try:
        import pyautogui

        pyautogui.screenshot().save(str(png_path))
    except Exception as exc:  # screenshot pode falhar em sessão RDP/segura
        logger.debug(f"diagnostics: screenshot indisponível ({exc})")

    try:
        txt_path.write_text(
            f"Context: {context_name}\nTimestamp: {datetime.now().isoformat()}\n"
            f"Error: {error_msg}\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning(f"diagnostics: não foi possível gravar {txt_path}: {exc}")
    return txt_path
