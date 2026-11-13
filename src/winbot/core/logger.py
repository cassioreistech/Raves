"""Logging e auditoria.

Sem side-effects no import: ``setup_logger()`` é chamado explicitamente pela CLI.
Isso evita criar diretórios durante o pytest e dentro do binário --onefile.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

_WINBOT_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WinBot"
LOG_DIR = _WINBOT_HOME / "logs"
AUDIT_LOG = _WINBOT_HOME / "audit.log"

_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}:{function}:{line} - {message}"
_AUDIT_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | AUDIT | {message}"

_sinks: set[int] = set()


def _is_audit(record: Any) -> bool:
    """Filtra registros marcados como auditoria (loguru passa um ``Record``)."""
    return record["extra"].get("audit") is True


def setup_logger() -> None:
    """Configura os sinks uma única vez (idempotente)."""
    if _sinks:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()

    _sinks.add(
        logger.add(
            LOG_DIR / "winbot_{time:YYYY-MM-DD}.log",
            rotation="5 MB",
            retention="15 days",
            level="DEBUG",
            filter=lambda r: not _is_audit(r),
            format=_LOG_FORMAT,
            encoding="utf-8",
        )
    )
    _sinks.add(logger.add(sys.stderr, level="ERROR", filter=lambda r: not _is_audit(r)))
    _sinks.add(
        logger.add(
            AUDIT_LOG,
            rotation="10 MB",
            retention="90 days",
            level="INFO",
            filter=_is_audit,
            format=_AUDIT_FORMAT,
            encoding="utf-8",
        )
    )


def audit(message: str) -> None:
    """Grava na trilha de auditoria append-only (90 dias de retenção)."""
    setup_logger()
    logger.bind(audit=True).info(message)
