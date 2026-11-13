"""Execução segura de processos no Windows.

Regras: shell=False sempre, argv como lista, timeout obrigatório, gate antes de tudo.
O comando do usuário vai para um .ps1 temporário via -File (sem interpolação em -Command).
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from winbot.core.config import SecuritySettings, load_settings
from winbot.core.logger import logger
from winbot.core.security import enforce, validate_shell_command

_POWERSHELL = "powershell.exe"


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    simulated: bool

    @property
    def success(self) -> bool:
        return self.returncode == 0

    @property
    def return_code(self) -> int:
        return self.returncode


def run(
    argv: tuple[str, ...] | list[str],
    policy: SecuritySettings,
    *,
    dry_run: bool = True,
    timeout: int | None = None,
    extra_text: str = "",
) -> CommandResult:
    decision = enforce(argv, policy, dry_run=dry_run, extra_text=extra_text)
    if dry_run:
        return CommandResult(decision.argv, 0, "", "", True)

    effective_timeout = timeout or policy.command_timeout_s
    try:
        completed = subprocess.run(
            list(decision.argv),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout excedido ({effective_timeout}s) em {decision.argv[0]}")
        return CommandResult(
            decision.argv, -1, "", f"Timeout de {effective_timeout}s excedido.", False
        )
    except OSError as exc:
        logger.exception("Falha inesperada ao executar processo")
        return CommandResult(decision.argv, -1, "", str(exc), False)

    return CommandResult(
        decision.argv, completed.returncode, completed.stdout, completed.stderr, False
    )


def run_powershell(
    command: str,
    timeout: int = 30,
    *,
    policy: SecuritySettings | None = None,
    dry_run: bool = True,
) -> CommandResult:
    """Executa um comando PowerShell de forma segura e controlada."""
    validate_shell_command(command)
    logger.debug(f"Executando PowerShell: {command}")
    active = policy if policy is not None else load_settings().security

    with tempfile.TemporaryDirectory(prefix="winbot-ps-") as tmp:
        script_path = Path(tmp) / "step.ps1"
        script_path.write_text(command, encoding="utf-8")
        argv = (
            _POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        )
        return run(argv, active, dry_run=dry_run, timeout=timeout, extra_text=command)
