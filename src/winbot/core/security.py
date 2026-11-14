"""Trava de segurança — nenhum módulo do engine executa sem passar por aqui."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PureWindowsPath
from typing import Any

from winbot.core.config import SecuritySettings
from winbot.core.logger import audit, logger


class SecurityViolationError(Exception):
    """Exceção disparada quando uma ação viola as políticas de segurança."""


# Nome histórico mantido para compatibilidade com os módulos e testes internos.
SecurityError = SecurityViolationError

# NUNCA podem ser liberados por configuração do cliente.
# Case-insensitive; não exigem ordem fixa de flags nem caminho literal C:\.
BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"\bformat\s+[a-z]:|\bformat-volume\b|\bclear-disk\b|\bremove-partition\b",
    r"\binitialize-disk\b|\bdiskpart\b",
    # Qualquer del/rd com /s, /q ou /f — independente do alvo (não só c:\windows).
    r"\b(del|erase|rd|rmdir)\b(?=[^\n]*\/[sqf])",
    # Qualquer Remove-Item com -Recurse ou -Force, em qualquer ordem e qualquer path.
    r"\bremove-item\b(?=[^\n]*-(?:recurse|force))",
    r"\bbcdedit\b",
    r"\breg\s+delete\b",
    r"\b(stop|restart)-computer\b|\bshutdown\b",
    r"\binvoke-expression\b|\biex\b",
    r"-verb\s+runas\b|\bset-executionpolicy\b",
    r"\bvssadmin\b[^\n]*delete\b|\bwevtutil\b[^\n]*\bcl\b|\bcipher\s+\/w\b",
)

HARD_DENY = BLACKLIST_PATTERNS


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    argv: tuple[str, ...]


def _find_violation(text: str) -> str | None:
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def validate_shell_command(command: str) -> None:
    """Valida um comando contra a blacklist. Levanta ANTES de qualquer execução."""
    pattern = _find_violation(command)
    if pattern is None:
        return
    logger.critical(f"BLOQUEIO DE SEGURANÇA: comando proibido -> {command}")
    audit(f"bloqueio pattern={pattern} command={command!r}")
    raise SecurityViolationError(f"Comando bloqueado pela política de segurança: '{command}'")


def check_command(
    argv: tuple[str, ...] | list[str],
    policy: SecuritySettings,
    *,
    extra_text: str = "",
) -> Decision:
    """Valida um argv. Função pura: não executa nada nem grava log."""
    args = tuple(argv)
    if not args or not args[0].strip():
        return Decision(False, "argv vazio", args)

    inspected = " ".join((*args, extra_text))
    pattern = _find_violation(inspected)
    if pattern is not None:
        return Decision(False, f"padrão negado: {pattern}", args)
    for custom in policy.deny_patterns:
        if re.search(custom, inspected, re.IGNORECASE):
            return Decision(False, f"padrão negado: {custom}", args)

    exe = PureWindowsPath(args[0]).name.lower()
    allowed = {item.lower() for item in policy.allowed_executables}
    if exe not in allowed:
        return Decision(False, f"executável não permitido: {exe}", args)

    return Decision(True, "ok", args)


def enforce(
    argv: tuple[str, ...] | list[str],
    policy: SecuritySettings,
    *,
    dry_run: bool,
    extra_text: str = "",
) -> Decision:
    """Aplica o gate, registra auditoria e bloqueia (fail-closed)."""
    decision = check_command(argv, policy, extra_text=extra_text)
    audit(
        f"gate dry_run={dry_run} allowed={decision.allowed} "
        f"argv={list(decision.argv)!r} reason={decision.reason}"
    )
    if not decision.allowed:
        raise SecurityViolationError(decision.reason)
    if not dry_run and not policy.allow_shell:
        raise SecurityViolationError("security.allow_shell=false: apenas dry-run é permitido")
    return decision


# ---------------------------------------------------------------------------
# Classificação de risco em 3 níveis (Etapa 6)
# ---------------------------------------------------------------------------


class RiskLevel(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


_GREEN_ACTIONS = frozenset(
    {
        "launch_app",
        "focus_window",
        "wait",
        "wait_window",
        "tocar_musica",
        "gui_type",
    }
)
_RED_ACTIONS = frozenset({"clean_temp", "powershell"})
# Ações que escrevem/clicam via UIA/OCR são amarelas (efeito colateral visível).
_YELLOW_ACTIONS = frozenset(
    {
        "kill_process",
        "gui_click",
        "gui_click_image",
        "gui_hotkey",
        "uia_click",
        "uia_fill",
        "ocr_click",
        "clean_temp",  # redundante, mas RED prevalece abaixo
    }
)


def classify_risk(action: str, params: dict[str, Any] | None = None) -> RiskLevel:
    """Classifica uma ação em GREEN/YELLOW/RED.

    - GREEN: leitura/abertura/foco/espera/música (execução imediata).
    - YELLOW: fechar, RPA/UIA/OCR (confirmação rápida se interativo).
    - RED: limpar temp, ps, kill em massa (confirmação explícita).
    """
    params = params or {}
    action = (action or "").strip().lower()

    if action in _RED_ACTIONS:
        return RiskLevel.RED
    if action == "kill_process":
        name = params.get("name")
        if isinstance(name, list) and len(name) > 3:
            return RiskLevel.RED
        if isinstance(name, str) and name.strip().lower() in {"*", "all", "todos"}:
            return RiskLevel.RED
        return RiskLevel.YELLOW
    if action in _YELLOW_ACTIONS:
        return RiskLevel.YELLOW
    if action in _GREEN_ACTIONS:
        return RiskLevel.GREEN
    # Ações desconhecidas: amarelo por segurança (não verde por padrão).
    return RiskLevel.YELLOW


def classify_workflow(steps: list[Any]) -> RiskLevel:
    """Risco de um workflow = nível mais alto entre suas etapas."""
    level = RiskLevel.GREEN
    order = {RiskLevel.GREEN: 0, RiskLevel.YELLOW: 1, RiskLevel.RED: 2}
    for step in steps:
        action = getattr(step, "action", None)
        if action is None and isinstance(step, dict):
            action = step.get("action")
        params = getattr(step, "params", None)
        if params is None and isinstance(step, dict):
            params = step.get("params", {})
        risk = classify_risk(str(action or ""), params or {})
        if order[risk] > order[level]:
            level = risk
    return level
