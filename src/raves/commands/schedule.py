"""Agendamento em segundo plano via Windows Task Scheduler (schtasks).

Task Scheduler foi escolhido em vez de Windows Service: não exige elevação nem
conta SYSTEM, é auditável e funciona com o binário Nuitka --onefile.

ATENÇÃO: a tarefa roda SEM terminal e com --apply. Não há confirmação interativa:
a blacklist, as allowlists e a auditoria são a única barreira. Confirme que o
workflow agendado não contém ações destrutivas antes de criar a tarefa.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from raves.core.logger import audit, logger
from raves.core.security import SecurityViolationError

app = typer.Typer(help="Agendamento de rotinas no Task Scheduler do Windows.")
console = Console()

TASK_PREFIX = "RAVES-"
_TASK_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_SC_VALUES = frozenset(
    {"MINUTE", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "ONCE", "ONSTART", "ONLOGON", "ONIDLE"}
)


def _task_name(name: str) -> str:
    clean = name.strip()
    if not _TASK_NAME_RE.fullmatch(clean):
        raise SecurityViolationError("Nome inválido: use letras, números, _, . ou - (até 64)")
    return f"{TASK_PREFIX}{clean}"


def _command(workflow: str) -> str:
    """Em dev usa python -m raves; no build Nuitka, sys.executable já é o .exe."""
    exe = Path(sys.executable)
    if exe.name.lower().startswith("python"):
        return f'"{exe}" -m raves workflow run "{workflow}" --apply'
    return f'"{exe}" workflow run "{workflow}" --apply'


def _run_schtasks(args: list[str], *, dry_run: bool) -> tuple[bool, str]:
    audit(f"schtasks argv={args!r} dry_run={dry_run}")
    if dry_run:
        return True, "simulado"
    if shutil.which("schtasks.exe") is None:
        return False, "schtasks.exe indisponível (requer Windows)"
    proc = subprocess.run(
        ["schtasks.exe", *args],
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out or f"rc={proc.returncode}"


@app.command("create")
def create(
    name: Annotated[str, typer.Argument(help="Nome da tarefa (sem espaços)")],
    workflow: Annotated[str, typer.Argument(help="Nome ou caminho do workflow YAML")],
    at: Annotated[str, typer.Option("--at", help="Horário HH:MM")] = "09:00",
    sc: Annotated[str, typer.Option("--sc", help="DAILY|HOURLY|WEEKLY|...")] = "DAILY",
    apply: Annotated[
        bool, typer.Option("--apply", help="Cria de fato (padrão: simulação).")
    ] = False,
) -> None:
    """Registra uma rotina no Agendador de Tarefas. DRY-RUN é o padrão."""
    task = _task_name(name)
    freq = sc.upper()
    if freq not in _SC_VALUES:
        raise typer.BadParameter(f"--sc inválido: {freq}")
    if not _TIME_RE.fullmatch(at):
        raise typer.BadParameter("--at deve ser HH:MM")

    trigger = _command(workflow)
    args = ["/Create", "/TN", task, "/TR", trigger, "/SC", freq, "/ST", at, "/F"]
    ok, message = _run_schtasks(args, dry_run=not apply)
    if not ok:
        console.print(f"[bold red]Falha:[/bold red] {message}")
        raise typer.Exit(code=1)

    label = "criada" if apply else "simulada"
    console.print(f"[green]OK[/green] tarefa [bold]{task}[/bold] ({label})")
    console.print(f"[dim]{trigger}[/dim]")
    if apply:
        console.print(
            "[yellow]A tarefa roda sem terminal e com --apply. Verifique "
            "security.allow_shell e o conteúdo do workflow.[/yellow]"
        )
    logger.info(f"schedule.create task={task} freq={freq} at={at} apply={apply}")


@app.command("remove")
def remove(
    name: Annotated[str, typer.Argument(help="Nome da tarefa")],
    apply: Annotated[
        bool, typer.Option("--apply", help="Remove de fato (padrão: simulação).")
    ] = False,
) -> None:
    """Remove uma tarefa agendada do RAVES."""
    task = _task_name(name)
    ok, message = _run_schtasks(["/Delete", "/TN", task, "/F"], dry_run=not apply)
    if not ok:
        console.print(f"[bold red]Falha:[/bold red] {message}")
        raise typer.Exit(code=1)
    label = "removida" if apply else "simulada"
    console.print(f"[green]OK[/green] tarefa [bold]{task}[/bold] ({label})")
    logger.info(f"schedule.remove task={task} apply={apply}")
