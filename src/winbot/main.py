"""Orquestrador principal da CLI."""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from winbot import __version__
from winbot.commands import rpa_tools, schedule, system, workflow
from winbot.core.licensing import current_status
from winbot.core.logger import setup_logger


def _configure_stdout() -> None:
    """Console Windows legacy usa cp1252; força UTF-8 para acentos em pt-BR."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


app = typer.Typer(
    name="winbot",
    help="WinBot CLI - Automação Profissional para Windows.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(system.app, name="sys")
app.add_typer(workflow.app, name="workflow")
app.add_typer(schedule.app, name="schedule")
app.add_typer(rpa_tools.app, name="rpa")

console = Console()


@app.callback()
def _bootstrap() -> None:
    """Prepara encoding e sinks de log antes de qualquer comando."""
    _configure_stdout()
    setup_logger()


@app.command("version")
def version_cmd() -> None:
    """Exibe a versão atual do WinBot."""
    console.print(
        f"[bold cyan]WinBot Engine[/bold cyan] v{__version__} [dim](Enterprise Core)[/dim]"
    )


@app.command("license")
def license_cmd() -> None:
    """Exibe o HWID e o status da licença (validação 100% offline)."""
    status = current_status()
    style = "green" if status.state in {"LICENSED", "TRIAL"} else "red"
    table = Table(title="WinBot · Licenciamento", border_style="cyan")
    table.add_column("Campo", style="bold white")
    table.add_column("Valor")
    table.add_row("Status", f"[bold {style}]{status.state}[/bold {style}]")
    table.add_row("Detalhe", status.detail)
    table.add_row("HWID", status.hwid)
    table.add_row("Plano", status.plan or "-")
    table.add_row("Validade", status.expires or "-")
    console.print(table)


if __name__ == "__main__":
    app()
